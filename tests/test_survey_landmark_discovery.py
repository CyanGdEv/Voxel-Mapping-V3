from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import pymupdf
from pypdf import PdfReader
from voxel_mapper.survey_landmark_discovery import inspect_page, survey_references, run
from voxel_mapper.planning_bulk import Corpus
from voxel_mapper.drawing_geometry import run as extract
from voxel_mapper.generation_cycles import file_hash
from voxel_mapper.evidence_memory import EvidenceMemory
from tests import test_drawing_registration_bridge as fixture_module


class StationDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture_module.BridgeTests();self.fixture.setUp();self.root=self.fixture.root
        self.drawing=self.root/'drawing.pdf';self.drawing.write_bytes(self.fixture.pdf.read_bytes())
        self.policies=[];self.pdfs=[]
        for role,indices in [('control',range(3)),('checkpoint',range(3,5))]:
            rows=['BT /F1 8 Tf 1 0 0 1 120 100 Tm (EPSG:27700) Tj ET']
            for ordinal,index in enumerate(indices):
                ref=self.fixture.refs[index]
                rows.append(f'BT /F1 8 Tf 1 0 0 1 120 {480-ordinal*15} Tm (CP:{ref["id"]} E={ref["target"][0]:.6f} N={ref["target"][1]:.6f}) Tj ET')
            self.fixture.make_pdf('\n'.join(rows))
            path=self.root/(role+'.pdf');path.write_bytes(self.fixture.pdf.read_bytes());self.pdfs.append(path)
            source=replace(self.fixture.sources['control' if role=='control' else 'check'],sha256=file_hash(path),
                metadata={'physical_landmarks_verified':True,'reuse_allowed':True,
                    'station_coordinate_identity_verified':True,'station_coordinate_table_contract':'explicit_cp_en_station_table_v1',
                    'station_verification_reference':'fixture-survey-review','station_pages':[1],
                    'station_reference_role':role,'reference_accuracy_m':.1})
            self.policies.append(source.__dict__)
        self.manifest=self.root/'manifest.json'
        self.manifest.write_text(json.dumps({'crs':'EPSG:27700','sources':[self.fixture.source.__dict__,*self.policies]}))
        self.corpus=Corpus(self.root/'corpus')
        blobs={f'https://example.test/{i}':p.read_bytes() for i,p in enumerate([self.drawing,*self.pdfs])}
        self.corpus.ingest([{'url':url,'title':'Fixture'} for url in blobs],['example.test'])
        self.corpus.acquire(fetch=lambda url:blobs[url],interval=0);extract(self.corpus,self.root/'geometry')
        self.store=self.root/'memory.sqlite'

    def tearDown(self):self.corpus.close();self.fixture.tearDown()

    def page(self,path=None):
        path=path or self.pdfs[0]
        with pymupdf.open(path) as doc:
            return inspect_page(PdfReader(path).pages[0],doc[0],file_hash(path),1)

    def audit(self,output='output',manifest=True):
        return run(self.corpus,self.root/'geometry',self.store,self.root/output,
            manifest=self.manifest if manifest else None)

    def test_station_table_binds_exact_ids_to_unique_visible_leaders(self):
        page=self.page()
        self.assertEqual(len(page['candidates']),3)
        self.assertTrue(all(c['status']=='source_bound_station_coordinate_candidate' for c in page['candidates']),page)
        self.assertEqual(page['visible_epsg_candidates'],[27700])
        self.assertEqual(page['candidates'][0]['local'],[50,50])
        refs,status=survey_references(page,self.policies)
        self.assertEqual(status,'verified_policy_station_references')
        self.assertEqual(len(refs),3)
        self.assertEqual(page['accepted_controls'],0)

    def test_discovered_registry_qualifies_different_drawing_with_independent_sources(self):
        from voxel_mapper.registration_qualification import qualify_page
        report=self.audit();self.assertEqual(report['reference_count'],5)
        refs=json.loads(Path(report['references_file']).read_text())['landmarks']
        from voxel_mapper.reconstruction.model import Source
        sources={s['id']:Source(**s) for s in self.policies}
        registered,qualification=qualify_page(self.drawing,1,self.fixture.source,refs,sources)
        self.assertEqual(qualification['status'],'qualified_horizontal_frame')
        self.assertEqual(registered.registration_status,'accepted')

    def test_missing_policy_local_grid_and_wrong_crs_never_release_references(self):
        page=self.page()
        self.assertEqual(survey_references(page,[])[0],[])
        page['survey_context']['restriction_flags']=['local_grid']
        self.assertEqual(survey_references(page,self.policies)[1],'withheld_local_or_restricted_survey_grid')
        page=self.page();page['visible_epsg_candidates']=[32630]
        self.assertEqual(survey_references(page,self.policies)[0],[])
        self.assertEqual(self.audit(manifest=False)['reference_count'],0)

    def test_table_approval_scope_accuracy_and_identity_are_required(self):
        page=self.page()
        for change in [{'station_pages':[2]},{'reference_accuracy_m':True},{'reference_accuracy_m':2},
                       {'station_coordinate_identity_verified':False},{'station_verification_reference':''},
                       {'reuse_allowed':False},{'station_reference_role':'automatic'}]:
            policies=json.loads(json.dumps(self.policies));policies[0]['metadata'].update(change)
            self.assertEqual(survey_references(page,policies)[0],[])

    def test_form_location_and_unattached_coordinate_rows_cannot_be_station_anchors(self):
        self.fixture.make_pdf('BT /F1 8 Tf 1 0 0 1 120 400 Tm (Easting: 407345 Northing: 343810) Tj ET\n'
            'BT /F1 8 Tf 1 0 0 1 120 380 Tm (CP:UNKNOWN E=407345 N=343810) Tj ET')
        page=self.page(self.fixture.pdf)
        self.assertEqual(len(page['candidates']),1)
        self.assertEqual(page['candidates'][0]['status'],'withheld_missing_station_mark')
        self.assertNotIn('local',page['candidates'][0])

    def test_repeated_station_rows_are_ambiguous(self):
        self.fixture.make_pdf('BT /F1 8 Tf 1 0 0 1 120 400 Tm (CP:A E=1 N=2) Tj ET\n'
            'BT /F1 8 Tf 1 0 0 1 120 380 Tm (CP:A E=1 N=2) Tj ET')
        self.assertEqual(self.page(self.fixture.pdf)['candidates'][0]['status'],'withheld_ambiguous_station_identity')

    def test_overpainted_station_table_cannot_supply_coordinates(self):
        # Keep exact station row and leader, then obscure just the table text.
        self.fixture.make_pdf('BT /F1 8 Tf 1 0 0 1 120 400 Tm (CP:A E=1 N=2) Tj ET\n1 1 1 rg 115 390 200 25 re f')
        page=self.page(self.fixture.pdf)
        self.assertEqual(page['candidates'][0]['status'],'withheld_station_glyph_visibility')

    def test_overpainted_crosshair_cannot_supply_attachment(self):
        self.fixture.make_pdf('BT /F1 8 Tf 1 0 0 1 120 400 Tm (CP:A E=1 N=2) Tj ET\n1 1 1 rg 40 40 20 20 re f')
        page=self.page(self.fixture.pdf)
        self.assertEqual(page['candidates'][0]['status'],'withheld_station_attachment_visibility')

    def test_original_and_reference_receipt_tampering_fail_resume(self):
        first=self.audit()
        refs=Path(first['references_file']);original=refs.read_bytes();refs.write_text('{"landmarks":[]}')
        with self.assertRaisesRegex(ValueError,'output changed'):self.audit()
        refs.write_bytes(original)
        pdf=next((self.corpus.root/'files').glob('*.pdf'));pdf.write_bytes(pdf.read_bytes()+b'corrupt')
        with self.assertRaisesRegex(ValueError,'checksum mismatch'):self.audit()

    def test_replay_source_tampering_and_parent_rejection(self):
        first=self.audit()
        with patch('voxel_mapper.survey_landmark_discovery.inspect_page',side_effect=AssertionError('Recomputed')):
            second=self.audit('second');again=self.audit()
        self.assertEqual(second['reused_pages'],3)
        self.assertEqual(again['run_pages'],0)
        self.assertEqual(first['output_sha256'],second['output_sha256'])
        fact=next(f for f in first['page_facts'] if f['parents'])
        with EvidenceMemory(self.store) as memory:
            memory.reject(fact['parents'][0],reviewer='qa',reason='wrong survey identity',review_reference='qa/1')
        with self.assertRaisesRegex(ValueError,'rejected|Retained evidence parent'):self.audit()

    def test_duplicate_identity_across_revisions_is_excluded(self):
        manifest=json.loads(self.manifest.read_text())
        # Expose the same table from two distinct source bytes.
        self.fixture.make_pdf('BT /F1 8 Tf 1 0 0 1 120 100 Tm (EPSG:27700) Tj ET\n'
            'BT /F1 8 Tf 1 0 0 1 120 400 Tm (CP:A E=1.763889 N=1.763889) Tj ET')
        blob=self.fixture.pdf.read_bytes()
        self.corpus.ingest([{'url':'https://example.test/revision','title':'Revision'}],['example.test'])
        self.corpus.acquire(fetch=lambda _:blob,interval=0);extract(self.corpus,self.root/'geometry')
        manifest['sources'].append({**self.policies[0],'id':'revision','sha256':file_hash(self.fixture.pdf)})
        self.manifest.write_text(json.dumps(manifest));report=self.audit()
        self.assertIn('A',report['ambiguous_station_ids'])
        self.assertNotIn('A',[r['id'] for r in json.loads(Path(report['references_file']).read_text())['landmarks']])

    def test_area_recipe_uses_discovered_refs_without_handwritten_reference_file(self):
        from voxel_mapper.area_reconstruction import run as area_run
        self.manifest.write_text(json.dumps({**json.loads(self.manifest.read_text()),'boundary':{'type':'Polygon',
            'coordinates':[[[0,0],[24,0],[24,24],[0,24],[0,0]]]}}))
        (self.root/'terrain.json').write_text('{}')
        entries=[{'applicationReference':'A','url':f'https://example.test/{i}','sha256':file_hash(p),'title':'Plan'}
            for i,p in enumerate([self.drawing,*self.pdfs])]
        (self.root/'catalogue.json').write_text(json.dumps({'entries':entries}))
        job={'work_directory':'area','catalogue':'catalogue.json','official_hosts':['example.test'],'offline':True,
            'source_directories':['corpus/files'],'survey_landmark_discovery':{'enabled':True,'use_discovered_references':True},
            'automatic_reconstruction':{'enabled':True,'manifest':'manifest.json','terrain_config':'terrain.json'},
            'areas':[{'id':'a','name':'A','application_references':['A'],'required_families':['path'],
                'bounds':[0,0,24,24],'bounds_crs':'EPSG:27700'}]}
        (self.root/'job.json').write_text(json.dumps(job))
        state=area_run(self.root/'job.json','extract')['areas']['a']
        self.assertEqual(state['survey_landmark_discovery']['reference_count'],5)
        self.assertEqual(state['registration_qualification']['qualified_frames'],1)
        from voxel_mapper.automatic_reconstruction import prepare
        refs=Path(state['survey_landmark_discovery']['references_file'])
        recipe,report=prepare(job,job['areas'][0],lambda p:self.root/p,self.root/'area/a',
            {file_hash(p) for p in [self.drawing,*self.pdfs]},references_override=refs)
        self.assertEqual(report['feature_count'],3)
        self.assertEqual(report['status'],'recipe_ready')
        self.assertIsNotNone(recipe)
