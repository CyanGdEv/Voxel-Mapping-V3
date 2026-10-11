import copy
import json
import tempfile
import unittest
from pathlib import Path
import pymupdf
from shapely.geometry import box
from tests import test_linework_boundaries as fixtures
from voxel_mapper.linework_boundaries import recover_page
from voxel_mapper.landmark_context import page_context,run,options

SHA='a'*64
SCALE={'document_sha256':SHA,'page':1,'status':'one_visible_printed_scale','expected_metres_per_pdf_point':.1}

class LandmarkContextTests(unittest.TestCase):
    def context(self,parents,records=None,scale=None):
        if records is None:records=[r for r in recover_page(parents)[0] if r['geometry']['type']=='Polygon']
        with pymupdf.open() as document:
            page=document.new_page(width=500,height=500)
            return page_context(page,SHA,1,parents,records,scale or SCALE)

    def test_true_boundary_retains_exact_record(self):
        parents=fixtures.LineworkTests().parents([list(box(20,20,100,100).exterior.coords)])
        records=[r for r in recover_page(parents)[0] if r['geometry']['type']=='Polygon']
        kept,report=self.context(parents,records)
        self.assertEqual(kept,records);self.assertIs(kept[0],records[0])
        self.assertFalse(report['physical_identity_verified']);self.assertEqual(report['world_geometry_additions'],0)

    def test_parallel_survey_lines_withhold_band_but_keep_source(self):
        parents=fixtures.LineworkTests().parents([[(-200,20),(300,20)],[(-200,60),(300,60)],[(20,20),(20,60)],[(100,20),(100,60)]])
        original=copy.deepcopy(parents);kept,report=self.context(parents)
        self.assertEqual(kept,[]);self.assertEqual(parents,original)
        self.assertEqual(report['reason_counts']['parallel_through_line_boundary_candidate'],1)

    def test_dashed_continuations_do_not_supply_boundary_evidence(self):
        parents=fixtures.LineworkTests().parents([list(box(20,20,100,60).exterior.coords)])
        records=[r for r in recover_page(parents)[0] if r['geometry']['type']=='Polygon']
        extended=fixtures.LineworkTests().parents([[(-200,20),(300,20)],[(-200,60),(300,60)]])
        for row in extended:row['paint_references'][0]['stroke_style']['dashes_pdf']='[1 2] 0'
        kept,report=self.context(parents+extended,records)
        self.assertEqual(kept,records);self.assertEqual(report['decisions'][0]['continuation_count'],0)
        with self.assertRaisesRegex(ValueError,'Unique'):self.context(parents,records+records)

    def test_area_policy_is_not_object_identity_and_scale_is_pinned(self):
        parents=fixtures.LineworkTests().parents([list(box(20,20,30,30).exterior.coords)])
        kept,report=self.context(parents);self.assertEqual(kept,[])
        self.assertEqual(report['reason_counts']['below_landmark_area_threshold'],1)
        with self.assertRaisesRegex(ValueError,'Source-bound'):self.context(parents,scale={**SCALE,'page':2})
        with self.assertRaises(ValueError):options({'min_area_m2':True})

    def test_visible_room_label_needs_unique_full_glyph_enclosure(self):
        from voxel_mapper.drawing_geometry import extract_page
        from unittest.mock import patch
        with pymupdf.open() as document:
            page=document.new_page(width=400,height=400)
            page.draw_rect((20,20,200,180));page.insert_text((60,80),'KITCHEN',fontsize=12)
            parents,_=extract_page(page,SHA,1)
            records=[r for r in recover_page(parents)[0] if r['geometry']['type']=='Polygon']
            kept,report=page_context(page,SHA,1,parents,records,SCALE)
            self.assertEqual(kept,[])
            self.assertEqual(report['reason_counts']['contained_room_or_roof_detail_label'],1)
            with patch('voxel_mapper.landmark_context.screen_span',return_value={'status':'withheld'}):
                kept,report=page_context(page,SHA,1,parents,records,SCALE)
                self.assertEqual(kept,records)
            duplicate=copy.deepcopy(records[0]);duplicate['id']='different'
            kept,report=page_context(page,SHA,1,parents,records+[duplicate],SCALE)
            self.assertEqual(len(kept),2);self.assertEqual(report['labels'][0]['association'],'ambiguous_atomic_faces')

    def test_native_stage_replay_tamper_and_pipeline(self):
        from voxel_mapper.planning_bulk import Corpus
        from voxel_mapper.drawing_geometry import run as extract
        from voxel_mapper.linework_boundaries import run as boundaries
        from voxel_mapper.park_pipeline import run as park
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);corpus=Corpus(root/'corpus')
            with pymupdf.open() as document:
                page=document.new_page(width=400,height=400)
                page.draw_rect((20,20,200,180));page.insert_text((20,300),'Scale 1:200',fontsize=12)
                data=document.tobytes()
            try:
                corpus.ingest([{'url':'https://portal.test/plan','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda _:data)
                extract(corpus,root/'drawing-geometry')
                parents=root/'drawing-geometry/geometry-candidates.jsonl'
                boundaries(corpus,parents,root/'linework-boundaries',envelopes=True)
                candidates=root/'linework-boundaries/polygon-candidates.jsonl'
                receipt=run(corpus,parents,candidates,root/'context')
                self.assertGreater(receipt['counts']['eligible_candidates'],0)
                self.assertEqual(receipt,run(corpus,parents,candidates,root/'context'))
                with self.assertRaisesRegex(ValueError,'inputs changed'):run(corpus,parents,candidates,root/'context',context_options={'min_area_m2':5})
                rows=[json.loads(s) for s in candidates.read_text().splitlines()]
                kept=[json.loads(s) for s in (root/'context/landmark-candidates.jsonl').read_text().splitlines()]
                self.assertTrue(all(r in rows for r in kept))
                job=root/'job.json';job.write_text(json.dumps({'work_directory':'.','acquisition':{'offline':True},'drawing_analysis':{'enabled':False},'drawing_geometry':{'enabled':True},'linework_boundaries':{'enabled':True,'envelopes':True},'landmark_context':{'enabled':True}}))
                report=park(job,'acquire');self.assertGreater(report['stages']['landmark_context']['counts']['eligible_candidates'],0)
                (root/'context/landmark-candidates.jsonl').write_text('changed')
                with self.assertRaisesRegex(ValueError,'output changed'):run(corpus,parents,candidates,root/'context')
                rows[0]['physical_identity_verified']=True;candidates.write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
                with self.assertRaisesRegex(ValueError,'differs'):run(corpus,parents,candidates,root/'tampered')
            finally:corpus.close()
