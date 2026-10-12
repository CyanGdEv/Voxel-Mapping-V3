import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import pymupdf
from voxel_mapper.retained_evidence_matching import match,run
from voxel_mapper.reconstruction_evidence_queue import build
from voxel_mapper.planning_bulk import Corpus
from voxel_mapper.generation_cycles import file_hash


class RetainedMatchingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        pdf=pymupdf.open();p=pdf.new_page()
        p.insert_text((30,30),'EXISTING FLOOR PLAN 1:100')
        p.insert_text((30,60),'PROPOSED ELEVATION Archway 4')
        p.insert_text((30,90),'eaves level 181.63; ridge u/s 6.57')
        p.insert_text((30,120),'FFL 0.00; datum unspecified; National Grid')
        raw=pdf.tobytes();pdf.close();sha=hashlib.sha256(raw).hexdigest()
        self.document={'sha256':sha,'path':str(self.root/(sha+'.pdf')),'source_links':[{'declared_state':'unknown'}]}
        Path(self.document['path']).write_bytes(raw)
        self.queue=build('mutiny-bay',[{'document_sha256':sha,'page':1}])

    def tearDown(self):self.temp.cleanup()

    def test_exact_source_proofs_and_state_competition_never_accept(self):
        before=copy.deepcopy(self.queue);result=match(self.queue,[self.document])
        with pymupdf.open(self.document['path']) as pdf:text=pdf[0].get_text()
        for hit in result['hits']:
            p=hit['proof'];self.assertEqual(text[p['character_start']:p['character_end']],p['matched_text'])
            self.assertFalse(hit['geometry_export_authorized'])
        self.assertEqual(result['source_pages'][0]['printed_state_claims'],['existing','proposed'])
        self.assertTrue(all(not row['requirement_resolved'] for row in result['task_results']))
        self.assertEqual(self.queue,before)

    def test_all_supported_requirements_and_missing_leads_are_explicit(self):
        from voxel_mapper.retained_evidence_matching import PATTERNS
        queue=copy.deepcopy(self.queue)
        queue['tasks']=[{'id':k,'kind':k} for k in PATTERNS]
        result=match(queue,[self.document])
        self.assertTrue(all(r['candidate_hit_ids'] for r in result['task_results']))
        by_kind={r['kind']:r for r in result['task_results']}
        self.assertEqual(by_kind['vertical_datum']['status'],'related_text_only')
        self.assertEqual(by_kind['horizontal_registration']['status'],'related_text_only')
        self.assertEqual(by_kind['vertical_datum']['direct_requirement_hit_ids'],[])
        empty=match(queue,[])
        self.assertTrue(all(r['status']=='no_retained_text_lead' for r in empty['task_results']))

    def test_late_budget_withholds_all_matches_and_assignments(self):
        full=match(self.queue,[self.document]);self.assertGreater(len(full['hits']),1)
        limited=match(self.queue,[self.document],max_hits=1)
        self.assertEqual(limited['status'],'matching_budget_withheld')
        self.assertEqual(limited['hits'],[]);self.assertEqual(limited['task_results'],[])
        limited=match(self.queue,[self.document],max_assignments=1)
        self.assertEqual(limited['hits'],[]);self.assertEqual(limited['task_results'],[])
        with self.assertRaises(ValueError):match(self.queue,[self.document],max_pages=True)

    def test_changed_pdf_and_duplicate_sources_reject(self):
        with self.assertRaises(ValueError):match(self.queue,[self.document,self.document])
        Path(self.document['path']).write_bytes(b'%PDF-edited')
        with self.assertRaisesRegex(ValueError,'Pinned retained'):match(self.queue,[self.document])

    def corpus_and_queue(self):
        corpus=Corpus(self.root/'corpus');sha=self.document['sha256']
        raw=Path(self.document['path']).read_bytes();corpus._retain(raw,sha)
        corpus.ingest([{'url':'https://portal.test/a','title':'Existing floor plan','sha256':sha}],['portal.test'])
        corpus.acquire(offline=True)
        directory=self.root/'queue';directory.mkdir()
        (directory/'missing-evidence.json').write_text(json.dumps(self.queue))
        (directory/'queue-report.json').write_text(json.dumps({'output_sha256':file_hash(directory/'missing-evidence.json')}))
        return corpus,directory

    def test_resume_reuses_and_changed_inventory_creates_new_attempt(self):
        corpus,directory=self.corpus_and_queue()
        try:
            first=run(corpus,directory,self.root/'matches');second=run(corpus,directory,self.root/'matches')
            self.assertEqual(first['run_pages'],1);self.assertEqual(second['run_pages'],0)
            self.assertEqual(second['reused_pages'],1);self.assertEqual(first['run_id'],second['run_id'])
            corpus.ingest([{'url':'https://portal.test/missing','title':'Topographical survey'}],['portal.test'])
            third=run(corpus,directory,self.root/'matches')
            self.assertNotEqual(first['run_id'],third['run_id']);self.assertEqual(third['pending_documents'],1)
            output=json.loads((self.root/'matches'/third['run_id']/'source-matches.json').read_text())
            self.assertIn('horizontal_registration',output['unavailable_document_leads'][0]['candidate_requirement_kinds'])
            self.assertTrue((self.root/'matches'/first['run_id']).exists())
        finally:corpus.close()

    def test_edited_match_and_requirement_outputs_reject(self):
        corpus,directory=self.corpus_and_queue()
        try:
            first=run(corpus,directory,self.root/'matches')
            (self.root/'matches'/first['run_id']/'source-matches.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'matches changed'):run(corpus,directory,self.root/'matches')
            (directory/'missing-evidence.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'queue output changed'):run(corpus,directory,self.root/'matches')
        finally:corpus.close()

    def test_optional_archive_is_pinned_and_preserved_in_attempt(self):
        corpus,directory=self.corpus_and_queue()
        archive=self.root/'archive.csv'
        archive.write_text('NG LETTERS,EASTING,NORTHING,HEIGHT,DATUM,DESCRIPTION\nSK,0744,4354,178.9000,N,building corner\n')
        configuration={'file':str(archive),'sha256':file_hash(archive),'search_bounds_bng':[407000,343000,408000,344000]}
        try:
            first=run(corpus,directory,self.root/'matches',benchmark_archive=configuration)
            result=json.loads((self.root/'matches'/first['run_id']/'source-matches.json').read_text())
            self.assertIn('benchmark_archive_review',result)
            self.assertFalse(result['benchmark_archive_review']['coordinate_control_verified'])
            self.assertEqual(run(corpus,directory,self.root/'matches',benchmark_archive=configuration)['run_pages'],0)
            archive.write_text('changed')
            with self.assertRaisesRegex(ValueError,'archive input changed'):
                run(corpus,directory,self.root/'matches',benchmark_archive=configuration)
        finally:corpus.close()
