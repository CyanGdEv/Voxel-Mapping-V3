from dataclasses import replace
import json
import unittest
from unittest.mock import patch
from voxel_mapper.registration_qualification import qualify_page, run, input_contract
from voxel_mapper.planning_bulk import Corpus
from voxel_mapper.drawing_geometry import run as extract
from voxel_mapper.evidence_memory import EvidenceMemory
from voxel_mapper.generation_cycles import file_hash
from tests import test_drawing_registration_bridge as bridge_fixture
from tests import test_ordinary_surfaces as surface_fixture


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = bridge_fixture.BridgeTests(); self.fixture.setUp(); self.root = self.fixture.root
        self.fixture.batch_inputs()
        self.corpus = Corpus(self.root/'corpus')
        self.corpus.ingest([{'url': 'https://example.test/drawing', 'title': 'Fixture'}], ['example.test'])
        self.corpus.acquire(fetch=lambda _: self.fixture.pdf.read_bytes())
        extract(self.corpus, self.root/'geometry')
        self.store = self.root/'memory.sqlite'

    def tearDown(self):
        self.corpus.close(); self.fixture.tearDown()

    def qualify(self, source=None):
        f = self.fixture
        return qualify_page(f.pdf, 1, source or f.source, f.refs, f.sources)

    def audit(self, output='output', policies=True):
        return run(self.corpus,self.root/'geometry',self.store,self.root/output,
            manifest=self.root/'manifest.json' if policies else None,
            references=self.root/'refs.json' if policies else None)

    def test_named_frame_is_qualified_without_accepting_components(self):
        source, receipt = self.qualify()
        self.assertEqual(receipt['status'], 'qualified_horizontal_frame')
        self.assertEqual(source.registration_status, 'accepted')
        self.assertEqual(receipt['physical_components_accepted'], 0)
        self.assertGreater(receipt['registration']['reference_and_attachment_error_budget_m'], .2)
        self.assertIn('physical_component_identity', receipt['remaining_component_requirements'])

    def test_proposed_source_frame_does_not_accept_proposed_components(self):
        source = replace(self.fixture.source,metadata={**self.fixture.source.metadata,'drawing_state':'proposed'})
        registered, receipt = self.qualify(source)
        self.assertEqual(receipt['status'], 'qualified_horizontal_frame')
        self.assertEqual(registered.metadata['drawing_state'], 'proposed')
        from voxel_mapper.drawing_registration_bridge import bridge_page
        with self.assertRaisesRegex(ValueError,'existing/as-built'):
            bridge_page(self.fixture.pdf,1,source,self.fixture.refs,self.fixture.sources)

    def test_native_ordinary_frame_retains_parent_budget_for_context_matching(self):
        fixture = surface_fixture.OrdinarySurfaceTests(); fixture.setUp()
        try:
            source, receipt = qualify_page(fixture.pdf,1,fixture.source,fixture.refs,fixture.surveys)
            self.assertEqual(receipt['status'],'qualified_horizontal_frame')
            review = source.metadata['horizontal_registration_review']
            self.assertIn('reference_and_attachment_error_budget_m', review)
            self.assertEqual(review['target_crs'], 'EPSG:27700')
        finally: fixture.tearDown()

    def test_policy_and_scale_failures_are_retained_as_missing_requirements(self):
        report = self.audit(policies=False)
        self.assertEqual(report['qualified_frames'], 0)
        self.assertEqual(report['missing_requirements']['unique_checksum_bound_source_policy'],1)
        self.assertEqual(report['missing_requirements']['independent_survey_reference_bundle'],1)
        self.assertNotIn('visible_unambiguous_printed_scale',report['missing_requirements'])

    def test_scale_budget_failure_is_retained_and_other_pages_still_qualify(self):
        from pypdf import PdfReader, PdfWriter
        from voxel_mapper.mapped_alignment_checks import printed_scale_review
        pdf = self.fixture.pdf; writer = PdfWriter()
        reader = PdfReader(pdf)
        writer.add_page(reader.pages[0]); writer.add_page(reader.pages[0])
        with pdf.open('wb') as stream: writer.write(stream)
        manifest = json.loads((self.root/'manifest.json').read_text())
        manifest['sources'][0]['sha256'] = file_hash(pdf)
        (self.root/'manifest.json').write_text(json.dumps(manifest))
        corpus = Corpus(self.root/'two-page-corpus')
        try:
            corpus.ingest([{'url': 'https://example.test/two-pages'}], ['example.test'])
            corpus.acquire(fetch=lambda _: pdf.read_bytes())
            extract(corpus, self.root/'two-page-geometry')
            def bounded_review(path, page):
                if page == 1: raise ValueError('Map scale text budget exceeded')
                return printed_scale_review(path, page)
            with patch('voxel_mapper.registration_qualification.printed_scale_review', side_effect=bounded_review):
                report = run(corpus, self.root/'two-page-geometry', self.store, self.root/'two-page-output',
                    manifest=self.root/'manifest.json', references=self.root/'refs.json')
            self.assertEqual(report['pages'], 2)
            self.assertEqual(report['qualified_frames'], 1)
            records = [json.loads(line) for line in (self.root/'two-page-output'/report['run_id']/'page-frames.jsonl').read_text().splitlines()]
            self.assertEqual(records[0]['scale_review']['reason'], 'Map scale text budget exceeded')
            self.assertEqual(records[0]['status'], 'awaiting_registration_evidence')
            self.assertEqual(records[1]['status'], 'qualified_horizontal_frame')
            replay = run(corpus, self.root/'two-page-geometry', self.store, self.root/'two-page-replay',
                manifest=self.root/'manifest.json', references=self.root/'refs.json')
            self.assertEqual(replay['output_sha256'], report['output_sha256'])
            self.assertEqual(replay['reused_pages'], 2)
        finally: corpus.close()

    def test_scale_review_failure_cannot_hide_changed_original(self):
        def changed(path, page):
            path.write_bytes(path.read_bytes()+b'changed')
            raise ValueError('Map scale text budget exceeded')
        with patch('voxel_mapper.registration_qualification.printed_scale_review', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                self.audit()

    def test_exact_replay_reuses_frames_and_rejection_blocks_recipe_preflight(self):
        first = self.audit()
        self.assertEqual(first['qualified_frames'],1)
        with patch('voxel_mapper.registration_qualification.qualify_page',side_effect=AssertionError('Recomputed')):
            second = self.audit('second')
            again = self.audit()
        self.assertEqual(second['reused_pages'],1)
        self.assertEqual(first['output_sha256'],second['output_sha256'])
        self.assertEqual(again['run_pages'],0)
        fact = first['page_facts'][0]
        with EvidenceMemory(self.store) as memory:
            memory.reject(fact['parents'][0],reviewer='qa',reason='incorrect source evidence',review_reference='qa/1')
        with self.assertRaisesRegex(ValueError,'rejected|Retained evidence parent'):
            self.audit()

    def test_changed_reference_requires_new_qualification_and_does_not_reuse_acceptance(self):
        first = self.audit()
        (self.root/'refs.json').write_text(json.dumps({'landmarks':self.fixture.refs[:3]}))
        second = self.audit()
        self.assertNotEqual(first['run_id'],second['run_id'])
        self.assertEqual(second['qualified_frames'],0)
        self.assertEqual(second['run_pages'],1)

    def test_manifest_crs_change_cannot_reuse_frame(self):
        first = self.audit()
        path = self.root/'manifest.json'; manifest = json.loads(path.read_text())
        manifest['crs'] = 'EPSG:32630'; path.write_text(json.dumps(manifest))
        second = self.audit()
        self.assertNotEqual(first['run_id'],second['run_id'])
        self.assertEqual(second['qualified_frames'],0)

    def test_unrelated_source_does_not_invalidate_page_memory(self):
        first = self.audit()
        path = self.root/'manifest.json'; manifest = json.loads(path.read_text())
        manifest['sources'].append({**manifest['sources'][0],'id':'unrelated','sha256':'f'*64})
        path.write_text(json.dumps(manifest))
        with patch('voxel_mapper.registration_qualification.qualify_page',side_effect=AssertionError('Recomputed')):
            second = self.audit()
        self.assertEqual(second['reused_pages'],1)
        self.assertEqual(first['page_facts'],second['page_facts'])

    def test_modified_receipt_cannot_claim_more_qualified_frames(self):
        first = self.audit()
        path = self.root/'output'/first['run_id']/'qualification-report.json'
        report = json.loads(path.read_text()); report['qualified_frames'] = 999
        path.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError,'inputs or outputs changed'): self.audit()

    def test_modified_original_and_output_fail_resume(self):
        first = self.audit()
        output = self.root/'output'/first['run_id']/'page-frames.jsonl'
        original = output.read_bytes(); output.write_text('')
        with self.assertRaisesRegex(ValueError,'inputs or outputs changed'): self.audit()
        output.write_bytes(original)
        pdf = next((self.corpus.root/'files').glob('*.pdf')); pdf.write_bytes(pdf.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'checksum mismatch'): self.audit()

    def test_overpainted_scale_cannot_qualify(self):
        self.fixture.make_pdf('1 1 1 rg 0 0 180 30 re f')
        source = replace(self.fixture.source,sha256=file_hash(self.fixture.pdf))
        with self.assertRaisesRegex(ValueError,'verified visibility'): self.qualify(source)

    def test_preflight_is_wired_into_area_stage_before_boundary(self):
        from voxel_mapper.area_reconstruction import run as area_run
        (self.root/'catalogue.json').write_text(json.dumps({'entries':[{'applicationReference':'A',
            'url':'https://example.test/drawing','title':'Plan','sha256':self.fixture.source.sha256}]}))
        job = {'work_directory':'area','catalogue':'catalogue.json','official_hosts':['example.test'],
            'offline':True,'source_directories':['corpus/files'],
            'registration_qualification':{'enabled':True,'manifest':'manifest.json','references':'refs.json'},
            'areas':[{'id':'a','name':'A','application_references':['A'],'required_families':['paving']}]}
        (self.root/'job.json').write_text(json.dumps(job))
        result = area_run(self.root/'job.json')['areas']['a']['registration_qualification']
        self.assertEqual(result['qualified_frames'],1)
        self.assertEqual(result['world_geometry_additions'],0)
        self.assertEqual(area_run(self.root/'job.json')['areas']['a']['registration_qualification']['reused_pages'],1)
        config = {'registration_qualification':job['registration_qualification']}
        before = input_contract(config,lambda p:self.root/p)
        (self.root/'refs.json').write_text('{}')
        self.assertNotEqual(before,input_contract(config,lambda p:self.root/p))

    def test_duplicate_policies_and_page_budget_are_withheld(self):
        path = self.root/'manifest.json'; manifest=json.loads(path.read_text())
        manifest['sources'].append({**manifest['sources'][0],'id':'alias'})
        path.write_text(json.dumps(manifest))
        self.assertEqual(self.audit()['qualified_frames'],0)
        for budget in [True,0,10001]:
            with self.assertRaises(ValueError):run(self.corpus,self.root/'geometry',self.store,self.root/'x',max_pages=budget)

    def test_verified_paper_caption_reaches_named_survey_registration(self):
        from pypdf import PdfReader,PdfWriter
        from pypdf.generic import DecodedStreamObject,NameObject,RectangleObject
        writer=PdfWriter();writer.clone_document_from_reader(PdfReader(self.fixture.pdf))
        page=writer.pages[0]
        page.mediabox=RectangleObject([0,0,841*72/25.4,594*72/25.4])
        data=page.get_contents().get_data().replace(b'(Scale 1:100)',b'(1/100 @ A1)')
        data+=b'\nBT /F1 8 Tf 1 0 0 1 10 25 Tm (1/200 @ A3) Tj ET'
        stream=DecodedStreamObject();stream.set_data(data);page[NameObject('/Contents')]=writer._add_object(stream)
        with self.fixture.pdf.open('wb') as output:writer.write(output)
        source=replace(self.fixture.source,sha256=file_hash(self.fixture.pdf))
        registered,receipt=self.qualify(source)
        self.assertEqual(registered.registration_status,'accepted')
        self.assertEqual(receipt['scale_review']['denominators'],[100])
        self.assertAlmostEqual(receipt['registration']['expected_scale_metres_per_pdf_point'],100*.0254/72)
        self.assertEqual(receipt['physical_components_accepted'],0)

    def test_supplied_scale_receipt_cannot_override_original_source(self):
        from voxel_mapper.mapped_alignment_checks import printed_scale_review
        review=printed_scale_review(self.fixture.pdf,1)
        forged={**review,'denominators':[200],'expected_metres_per_pdf_point':200*.0254/72}
        with self.assertRaisesRegex(ValueError,'differs from original source'):
            qualify_page(self.fixture.pdf,1,self.fixture.source,self.fixture.refs,self.fixture.sources,scale_review=forged)
