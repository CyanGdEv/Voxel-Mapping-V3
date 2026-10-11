import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pymupdf
from shapely.geometry import box,shape
from tests import test_linework_boundaries as fixtures
from voxel_mapper.architectural_interpretation import claim,wall_bands,interpret_page,run,options
from voxel_mapper.drawing_geometry import extract_page
from voxel_mapper.linework_boundaries import recover_page

SHA='a'*64
SCALE={'document_sha256':SHA,'page':1,'status':'one_visible_printed_scale','expected_metres_per_pdf_point':.1}

class ArchitecturalTests(unittest.TestCase):
    def test_printed_roles_and_vertical_references_are_distinct(self):
        self.assertEqual(claim('brick wall 0.80ht')['printed_height'],.8)
        self.assertEqual(claim('ridge u/s 6.57')['role'],'ridge_underside')
        self.assertEqual(claim('ridge level 184.60')['vertical_datum'],'unspecified')
        self.assertEqual(claim('eaves level 181.49 m')['printed_units'],'m')
        self.assertEqual(claim('stone ret wall')['role'],'retaining_wall')
        for text in ['brick paving','carpet tiles','tiles','replace brick wall','rooflight','ridge level 4 or 5']:
            self.assertIsNone(claim(text))

    def test_unique_parallel_band_preserves_actual_source_support(self):
        parents=fixtures.LineworkTests().parents([[ (20,20),(100,20)],[(30,23),(90,23)]])
        original=copy.deepcopy(parents);bands,report=wall_bands(parents,.1)
        self.assertEqual(len(bands),1);self.assertEqual(parents,original)
        self.assertTrue(shape(bands[0]['geometry']).equals(box(30,20,90,23)))
        self.assertAlmostEqual(bands[0]['overlap_m'],6)
        self.assertEqual(bands[0]['wall_type'],'interior_or_exterior_unresolved')
        from voxel_mapper.drawing_footprints import reviewed_feature
        with self.assertRaisesRegex(ValueError,'diagnostic'):reviewed_feature(bands[0],{},None,None,'EPSG:27700')

    def test_competing_offsets_dashes_and_budget_cannot_select_wall(self):
        parents=fixtures.LineworkTests().parents([[(20,20),(100,20)],[(20,23),(100,23)],[(20,26),(100,26)]])
        self.assertEqual(wall_bands(parents,.1)[0],[])
        bands,report=wall_bands(parents,.1,interpretation_options={'max_pair_comparisons':1})
        self.assertEqual(bands,[]);self.assertEqual(report['status'],'pair_budget_withheld')
        parents=parents[:2];parents[1]['paint_references'][0]['stroke_style']['dashes_pdf']='[1 2] 0'
        self.assertEqual(wall_bands(parents,.1)[0],[])
        with self.assertRaises(ValueError):options({'min_band_width_m':True})

    def test_roof_label_requires_visible_unique_complete_enclosure(self):
        with pymupdf.open() as document:
            page=document.new_page(width=400,height=400);page.draw_rect((20,20,200,180));page.insert_text((60,80),'flat roof',fontsize=12)
            parents,_=extract_page(page,SHA,1);records=[r for r in recover_page(parents)[0] if r['geometry']['type']=='Polygon']
            report=interpret_page(page,SHA,1,parents,records,SCALE)
            self.assertEqual(report['bound_roof_labels'],1)
            self.assertEqual(report['printed_claims'][0]['candidate_id'],records[0]['id'])
            with patch('voxel_mapper.architectural_interpretation.screen_span',return_value={'status':'withheld'}):
                self.assertEqual(interpret_page(page,SHA,1,parents,records,SCALE)['bound_roof_labels'],0)
            other=copy.deepcopy(records[0]);other['id']='overlapping'
            self.assertEqual(interpret_page(page,SHA,1,parents,records+[other],SCALE)['bound_roof_labels'],0)
            with self.assertRaisesRegex(ValueError,'Source-bound'):interpret_page(page,SHA,1,parents,records,{**SCALE,'page':2})

    def test_native_stage_resume_tamper_and_park_pipeline(self):
        from voxel_mapper.planning_bulk import Corpus
        from voxel_mapper.drawing_geometry import run as extract
        from voxel_mapper.park_pipeline import run as park
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);corpus=Corpus(root/'corpus')
            with pymupdf.open() as document:
                page=document.new_page(width=400,height=400);page.draw_rect((20,20,200,180))
                page.draw_line((230,20),(300,20))
                page.insert_text((60,80),'flat roof',fontsize=12);page.insert_text((20,300),'Scale 1:200',fontsize=12)
                data=document.tobytes()
            try:
                corpus.ingest([{'url':'https://portal.test/plan','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda _:data)
                extract(corpus,root/'drawing-geometry')
                receipt=run(corpus,root/'drawing-geometry',root/'architecture')
                self.assertEqual(receipt['counts']['bound_roof_labels'],1)
                self.assertEqual(receipt,run(corpus,root/'drawing-geometry',root/'architecture'))
                extract(corpus,root/'partial-geometry',max_candidates=1)
                partial=run(corpus,root/'partial-geometry',root/'partial-architecture')
                self.assertEqual(partial['counts']['bound_roof_labels'],0)
                self.assertEqual(partial['counts']['complete_extraction_and_visible_scale_required'],1)
                with self.assertRaisesRegex(ValueError,'inputs changed'):run(corpus,root/'drawing-geometry',root/'architecture',interpretation_options={'min_overlap_m':2})
                job=root/'job.json';job.write_text(json.dumps({'work_directory':'.','acquisition':{'offline':True},'drawing_analysis':{'enabled':False},'drawing_geometry':{'enabled':True},'architectural_interpretation':{'enabled':True}}))
                report=park(job,'acquire');self.assertEqual(report['stages']['architectural_interpretation']['counts']['bound_roof_labels'],1)
                self.assertEqual(park(job,'acquire')['stages']['architectural_interpretation']['counts']['bound_roof_labels'],1)
                from voxel_mapper.area_reconstruction import run as area_run
                import hashlib
                sha=hashlib.sha256(data).hexdigest();sources=root/'sources';sources.mkdir();(sources/(sha+'.pdf')).write_bytes(data)
                (root/'catalogue.json').write_text(json.dumps({'entries':[{'applicationReference':'A','url':'https://portal.test/plan','sha256':sha,'title':'Plan'}]}))
                area_job=root/'areas.json';area_job.write_text(json.dumps({'work_directory':'areas','catalogue':'catalogue.json','official_hosts':['portal.test'],
                    'offline':True,'source_directories':['sources'],'architectural_interpretation':{'enabled':True},
                    'areas':[{'id':'a','name':'A','application_references':['A'],'required_families':['roof']}]}))
                area=area_run(area_job)['areas']['a']
                self.assertEqual(area['architectural_interpretation']['counts']['bound_roof_labels'],1)
                self.assertEqual(area['status'],'awaiting_reconstruction')
                self.assertEqual(area_run(area_job)['areas']['a']['architectural_interpretation'],area['architectural_interpretation'])
                (root/'architecture/architectural-pages.jsonl').write_text('tampered')
                with self.assertRaisesRegex(ValueError,'output changed'):run(corpus,root/'drawing-geometry',root/'architecture')
                path=corpus.root/'files'/receipt['source_documents'][0];path=path.with_suffix('.pdf');path.write_bytes(path.read_bytes()+b'changed')
                with self.assertRaisesRegex(ValueError,'Source PDF'):run(corpus,root/'drawing-geometry',root/'changed-source')
            finally:corpus.close()
