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

    def test_disjoint_opposite_fragments_preserve_gap_and_touching_spans(self):
        parents=fixtures.LineworkTests().parents([[(0,20),(100,20)],[(0,23),(40,23)],[(60,23),(100,23)]])
        before=copy.deepcopy(parents);bands,review=wall_bands(parents,.1)
        self.assertEqual(len(bands),2);self.assertEqual(parents,before)
        geometries=[shape(r['geometry']) for r in bands]
        self.assertEqual(sorted(g.bounds for g in geometries),[(0.,20.,40.,23.),(60.,20.,100.,23.)])
        self.assertTrue(all(g.intersection(box(40,20,60,23)).area==0 for g in geometries))
        self.assertEqual(review['ambiguous_pairs_withheld'],0)
        touching=fixtures.LineworkTests().parents([[(0,20),(100,20)],[(0,23),(50,23)],[(50,23),(100,23)]])
        self.assertEqual(len(wall_bands(touching,.1)[0]),2)
        self.assertEqual(wall_bands(list(reversed(parents)),.1)[0],bands)
        # One overlapping alternative withholds both conflicting spans; a
        # disjoint supported fragment remains available.
        competing=fixtures.LineworkTests().parents([[(0,20),(100,20)],[(0,23),(40,23)],[(60,23),(100,23)],[(10,24),(30,24)]])
        result,review=wall_bands(competing,.1)
        self.assertEqual(len(result),1)
        self.assertEqual(shape(result[0]['geometry']).bounds,(60.,20.,100.,23.))
        self.assertGreater(review['ambiguous_pairs_withheld'],0)
        dense=fixtures.LineworkTests().parents([[(20,20),(100,20)],[(20,23),(100,23)],[(20,26),(100,26)]])
        limited,receipt=wall_bands(dense,.1,interpretation_options={'max_pair_comparisons':3})
        self.assertEqual(limited,[])
        self.assertEqual(receipt['status'],'span_pair_budget_withheld')

    def test_roof_label_requires_visible_unique_complete_enclosure(self):
        with pymupdf.open() as document:
            page=document.new_page(width=400,height=400);page.draw_rect((20,20,200,180));page.insert_text((60,80),'flat roof',fontsize=12)
            parents,_=extract_page(page,SHA,1);records=[r for r in recover_page(parents)[0] if r['geometry']['type']=='Polygon']
            report=interpret_page(page,SHA,1,parents,records,SCALE)
            self.assertEqual(report['bound_roof_labels'],1)
            self.assertEqual(report['printed_claims'][0]['candidate_id'],records[0]['id'])
            self.assertEqual(report['roof_region_associations'][0]['source_candidate'],records[0])
            self.assertEqual(report['roof_region_associations'][0]['printed_claim_indices'],[0])
            self.assertFalse(report['roof_region_associations'][0]['physical_identity_verified'])
            self.assertEqual(report['roof_region_associations'][0]['world_geometry_additions'],0)
            with patch('voxel_mapper.architectural_interpretation.screen_span',return_value={'status':'withheld'}):
                self.assertEqual(interpret_page(page,SHA,1,parents,records,SCALE)['bound_roof_labels'],0)
            other=copy.deepcopy(records[0]);other['id']='overlapping'
            ambiguous=interpret_page(page,SHA,1,parents,records+[other],SCALE)
            self.assertEqual(ambiguous['bound_roof_labels'],0)
            self.assertEqual(ambiguous['roof_region_associations'],[])
            with self.assertRaisesRegex(ValueError,'Source-bound'):interpret_page(page,SHA,1,parents,records,{**SCALE,'page':2})

    def test_empty_pages_do_not_stop_later_vector_pages(self):
        from voxel_mapper.planning_bulk import Corpus
        from voxel_mapper.drawing_geometry import run as extract
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);corpus=Corpus(root/'corpus')
            with pymupdf.open() as document:
                document.new_page(width=400,height=400)
                page=document.new_page(width=400,height=400)
                page.insert_text((20,300),'Scanned plan: no vectors',fontsize=12)
                page=document.new_page(width=400,height=400)
                page.draw_rect((20,20,200,180))
                page.insert_text((60,80),'flat roof',fontsize=12)
                page.insert_text((20,300),'Scale 1:200',fontsize=12)
                data=document.tobytes()
            try:
                corpus.ingest([{'url':'https://portal.test/plan','title':'Plan'}],['portal.test'])
                corpus.acquire(fetch=lambda _:data)
                extract(corpus,root/'geometry')
                receipt=run(corpus,root/'geometry',root/'architecture')
                self.assertEqual(receipt['pages'],3)
                self.assertEqual(receipt['counts']['bound_roof_labels'],1)
                rows=[json.loads(line) for line in (root/'architecture/architectural-pages.jsonl').read_text().splitlines()]
                for row in rows[:2]:
                    self.assertEqual(row['source_geometry_graph']['counts']['edges'],0)
                    self.assertNotIn('view_layout_review',row)
                    self.assertEqual(row['world_geometry_additions'],0)
                self.assertEqual(receipt,run(corpus,root/'geometry',root/'architecture'))
            finally:corpus.close()

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
