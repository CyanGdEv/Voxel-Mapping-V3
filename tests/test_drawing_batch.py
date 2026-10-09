import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import pymupdf
from pypdf import PdfWriter
from voxel_mapper.planning_bulk import Corpus
from voxel_mapper.drawing_batch import analyze,classify,construction_state,reviewed_alignment


class DrawingBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.corpus=Corpus(self.temp.name)
        pdf=pymupdf.open()
        for text in ('Existing site plan 1:500\nPath surface asphalt','Proposed elevation 1:100'):
            page=pdf.new_page();page.insert_text((30,40),text)
        self.data=pdf.tobytes();pdf.close();self.sha=hashlib.sha256(self.data).hexdigest()
        self.corpus.ingest([{'url':'https://portal.test/plan','title':'Site Plan','applicationReference':'A','state':'existing'}],['portal.test'])
        self.corpus.acquire(fetch=lambda u:self.data)
    def tearDown(self):self.corpus.close();self.temp.cleanup()
    def analyze(self,**kwargs):return analyze(self.corpus,ocr=False,**kwargs)
    def records(self):return [json.loads(s) for s in (Path(self.temp.name)/'drawing-analysis.jsonl').read_text().splitlines()]
    def test_page_evidence_is_unplaced_and_mixed_state_is_not_accepted(self):
        r=self.analyze(registration=False)
        self.assertEqual(r['analyzed_pages'],2);self.assertEqual(r['world_geometry_additions'],0)
        pages=self.records();self.assertEqual(pages[0]['scale_denominator_candidates'],[500])
        self.assertEqual(pages[1]['construction_state']['candidate'],'mixed')
        self.assertFalse(pages[1]['construction_state']['authoritative_current_state'])
        self.assertEqual(pages[0]['evidence_candidates']['materials'][0]['association_status'],'unplaced_unverified')
    def test_budget_and_resume(self):
        self.assertEqual(self.analyze(max_pages=1,registration=False)['analyzed_pages'],1)
        r=self.analyze(max_pages=1,registration=False)
        self.assertEqual(r['analyzed_pages'],2);self.assertEqual(r['resumed_pages'],1)
        self.assertEqual(self.analyze(registration=False)['run_analyzed_pages'],0)
    def test_changed_catalogue_invalidates_page_classification(self):
        self.analyze(registration=False)
        self.corpus.ingest([{'url':'https://portal.test/plan','title':'Site Plan','applicationReference':'A','state':'proposed'}],['portal.test'])
        self.assertEqual(self.analyze(registration=False)['run_analyzed_pages'],2)
        self.assertEqual(self.records()[0]['construction_state']['candidate'],'mixed')
    def test_corrupt_blob_is_not_analyzed(self):
        self.analyze(registration=False)
        (Path(self.temp.name)/'files'/f'{self.sha}.pdf').write_bytes(b'changed')
        r=self.analyze(registration=False);self.assertEqual(r['analyzed_pages'],0);self.assertIn('checksum',r['errors'][0]['error'])
    def test_missing_coordinates_does_not_create_alignment(self):
        self.analyze();self.assertTrue(all(p['horizontal_alignment']['status']=='needs_controls' for p in self.records()))
    def test_embedded_registration_remains_candidate(self):
        from tests.test_geopdf import GeoPdfTests
        writer,_,_=GeoPdfTests().fixture();stream=io.BytesIO();writer.write(stream);data=stream.getvalue()
        self.corpus.ingest([{'url':'https://portal.test/geopdf','title':'Survey'}],['portal.test'])
        self.corpus.acquire(fetch=lambda u:data)
        r=self.analyze();self.assertEqual(r['alignment_statuses']['candidate_alignment'],1)
        candidate=next(p for p in self.records() if p['horizontal_alignment']['status']=='candidate_alignment')
        self.assertEqual(candidate['horizontal_alignment']['independent_accuracy'],'not_verified')
    def test_ambiguous_categories_and_states_are_explicit(self):
        self.assertEqual(classify(['Site Plan','Elevation'],'')['primary'],'ambiguous')
        self.assertEqual(construction_state([{'state':'existing'},{'state':'proposed'}],'')['candidate'],'mixed')
        self.assertEqual(classify([],'unrelated')['primary'],'unclassified')
    def spec(self):
        def row(id,p,check=False):return {'id':id,'local':p,'target':[406000+p[0],343000+p[1]],'source_id':'check-survey' if check else 'control-survey','source_sha256':('b' if check else 'a')*64,'independent':check}
        return {'local_frame':'pdf_native_points_y_up','landmark_identity_reviewed':True,'target_crs':'EPSG:27700','expected_metres_per_pdf_point':1,'controls':[row('a',[10,10]),row('b',[100,10]),row('c',[10,100])],'checkpoints':[row('d',[20,20],True),row('e',[60,20],True)]}
    def test_independent_review_and_wrong_checkpoint(self):
        page=PdfWriter().add_blank_page(600,800);spec=self.spec()
        self.assertEqual(reviewed_alignment(spec,page)['status'],'accepted_horizontal_fit')
        spec['checkpoints'][0]['target'][0]+=10
        self.assertEqual(reviewed_alignment(spec,page)['status'],'withheld')
    def test_batch_review_is_bound_to_pdf_page_and_never_creates_geometry(self):
        spec=self.spec();spec.update(document_sha256=self.sha,page=1)
        r=self.analyze(reviews=[spec])
        self.assertEqual(r['alignment_statuses']['accepted_horizontal_fit'],1)
        review=self.records()[0]['horizontal_alignment']
        self.assertEqual(review['validated_domain']['type'],'Polygon')
        self.assertEqual(review['target_crs'],'EPSG:27700')
        self.assertEqual(r['world_geometry_additions'],0)
        spec['checkpoints'][0]['target'][0]+=10
        r=self.analyze(reviews=[spec])
        self.assertNotIn('accepted_horizontal_fit',r['alignment_statuses'])
    def test_review_requires_frame_identity_source_and_independence(self):
        page=PdfWriter().add_blank_page(600,800)
        for change in ('frame','identity','source','independence','shared','crop'):
            spec=self.spec()
            if change=='frame':spec['local_frame']='pixels'
            if change=='identity':spec['landmark_identity_reviewed']=False
            if change=='source':spec['controls'][0]['source_sha256']='missing'
            if change=='independence':spec['checkpoints'][0]['independent']=False
            if change=='shared':spec['checkpoints'][0].update(source_id='control-survey',source_sha256='a'*64)
            if change=='crop':spec['controls'][0]['local']=[-1,10]
            with self.subTest(change=change),self.assertRaises(ValueError):reviewed_alignment(spec,page)
    def test_unmatched_reviews_are_reported(self):
        r=self.analyze(registration=False,reviews=[{'document_sha256':'c'*64,'page':1}])
        self.assertEqual(len(r['unmatched_review_pages']),1)

    def test_invalid_review_identity_rejected(self):
        for spec in ({'document_sha256':'bad','page':1},{'document_sha256':'c'*64,'page':True}):
            with self.subTest(spec=spec),self.assertRaises(ValueError):self.analyze(reviews=[spec])

    def test_mixed_multi_cell_fixture_uses_all_ten_families(self):
        from scripts.benchmark_park_mixed import run
        with tempfile.TemporaryDirectory() as directory:
            report=run(directory,10)
            self.assertEqual(len(report['families']),10)
            self.assertGreater(report['unique_voxel_cells'],200)
            self.assertEqual(report['resume_features'],10)

if __name__=='__main__':unittest.main()
