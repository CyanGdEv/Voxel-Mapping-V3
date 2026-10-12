from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pymupdf
from shapely.geometry import LineString,Polygon,box,shape
from voxel_mapper.drawing_geometry import flatten_cubic,extract_page,subpaths,DEFAULTS,run
from voxel_mapper.drawing_footprints import reviewed_feature,promote
from voxel_mapper.planning_bulk import Corpus
from voxel_mapper.reconstruction.sources import evidence
from voxel_mapper.reconstruction.model import Source
import tests.test_drawing_footprints as footprint_tests

class GeometryTests(unittest.TestCase):
    def test_cubic_error_bound_agrees_with_dense_original_samples(self):
        controls=[(0,0),(0,100),(100,100),(100,0)];points,bound=flatten_cubic(controls,.1);line=LineString(points)
        samples=[]
        for t in np.linspace(0,1,1001):samples.append(tuple((1-t)**3*controls[0][i]+3*(1-t)**2*t*controls[1][i]+3*(1-t)*t*t*controls[2][i]+t**3*controls[3][i] for i in (0,1)))
        self.assertLessEqual(LineString(samples).hausdorff_distance(line),bound+1e-8);self.assertLessEqual(bound,.1);self.assertEqual(points[0],controls[0]);self.assertEqual(points[-1],controls[-1])
    def test_collinear_backtracking_and_curve_budgets_are_not_silently_flattened(self):
        points,bound=flatten_cubic([(0,0),(100,0),(-100,0),(0,0)])
        self.assertGreater(max(p[0] for p in points),20);self.assertLess(min(p[0] for p in points),-20)
        with self.assertRaises(ValueError):flatten_cubic([(0,0),(0,100),(100,100),(100,0)],.01,max_points=2)
        with self.assertRaises(ValueError):flatten_cubic([(0,0),(0,100),(100,100),(100,0)],.01,max_depth=1)
    def test_curved_polygon_hole_survives_all_rotations(self):
        doc=pymupdf.open();page=doc.new_page(width=400,height=600);drawing=page.new_shape();drawing.draw_circle((200,250),90);drawing.draw_circle((200,250),30);drawing.finish(color=None,fill=(.5,.5,.5),even_odd=True);drawing.commit();ids=[]
        try:
            for angle in (0,90,180,270):
                page.set_rotation(angle);rows,report=extract_page(page,'a'*64,1);self.assertEqual(len(rows),1);self.assertEqual(len(shape(rows[0]['geometry']).interiors),1);self.assertGreater(rows[0]['curve_approximation']['cubic_segments'],0);ids.append(rows[0]['id']);self.assertEqual(page.rotation,angle)
            self.assertEqual(len(set(ids)),1)
        finally:doc.close()
    def test_open_curve_is_line_not_filled_region(self):
        doc=pymupdf.open();page=doc.new_page(width=400,height=600);drawing=page.new_shape();drawing.draw_bezier((100,100),(100,200),(200,200),(200,100));drawing.finish(color=(0,0,0),closePath=False);drawing.commit()
        try:
            rows,_=extract_page(page,'a'*64,1);self.assertEqual(rows[0]['geometry']['type'],'LineString');self.assertFalse(rows[0]['physical_identity_verified']);self.assertEqual(rows[0]['line_role'],'unclassified_stroked_path')
        finally:doc.close()
    def test_disconnected_open_subpaths_are_not_stitched(self):
        doc=pymupdf.open();page=doc.new_page();drawing=page.new_shape();drawing.draw_line((100,100),(200,100));drawing.draw_line((300,200),(400,200));drawing.finish(color=(0,0,0),closePath=False);drawing.commit()
        try:
            rows,_=extract_page(page,'a'*64,1);self.assertEqual(len(rows),2);self.assertTrue(all(r['geometry']['type']=='LineString' for r in rows))
        finally:doc.close()
    def test_clipping_crossings_and_transparency_withheld(self):
        doc=pymupdf.open();page=doc.new_page(width=400,height=600);page.draw_line((0,0),(1,1));doc.update_stream(page.get_contents()[0],b'q 100 100 100 100 re W n 50 150 m 250 150 l S Q')
        try:
            rows,report=extract_page(page,'a'*64,1);self.assertFalse(rows);self.assertIn('Paint group crosses clipping boundary',report['rejections'])
        finally:doc.close()
        doc=pymupdf.open();page=doc.new_page(width=400,height=600);page.draw_line((0,0),(1,1));doc.update_stream(page.get_contents()[0],b'q 100 100 0 0 re W n 50 150 m 250 150 l S Q')
        try:self.assertFalse(extract_page(page,'a'*64,1)[0])
        finally:doc.close()
        doc=pymupdf.open();page=doc.new_page();page.draw_rect(pymupdf.Rect(100,100,200,200),fill=(0,0,0),fill_opacity=.5)
        try:self.assertFalse(extract_page(page,'a'*64,1)[0])
        finally:doc.close()
    def test_page_candidate_and_point_budgets_report_deferral(self):
        doc=pymupdf.open();page=doc.new_page();page.draw_line((100,100),(200,100));page.draw_line((100,200),(200,200))
        try:
            rows,report=extract_page(page,'a'*64,1,max_candidates=1);self.assertEqual(len(rows),1);self.assertEqual(report['status'],'partial_candidate_budget')
            rows,report=extract_page(page,'a'*64,1,max_total_points=2);self.assertEqual(len(rows),1);self.assertEqual(report['rejections']['page_point_budget_deferred'],1)
        finally:doc.close()
    def line_candidate(self):
        doc=pymupdf.open();page=doc.new_page(width=400,height=600);page.draw_line((20,570),(40,570));data=doc.tobytes();doc.close();sha=hashlib.sha256(data).hexdigest()
        with pymupdf.open(stream=data,filetype='pdf') as pdf:candidate=extract_page(pdf[0],sha,1)[0][0]
        helper=footprint_tests.FootprintTests();alignment=helper.alignment();source=helper.source(alignment);source=replace(source,sha256=sha,metadata={**source.metadata,'registration_document_sha256':sha});review=helper.review();review.update(candidate_id=candidate['id'],family='wall',line_role='boundary',line_role_verification_reference='fixture checked fence alignment',parameters={'height_m':evidence(2,'drawing'),'material':evidence('stone_bricks','drawing')})
        return data,candidate,source,alignment,review
    def test_reviewed_line_requires_role_and_does_not_accept_2d_ride_track(self):
        _,candidate,source,alignment,review=self.line_candidate();feature=reviewed_feature(candidate,review,source,alignment,'EPSG:27700');self.assertEqual(shape(feature.geometry).geom_type,'LineString')
        for changes in ({'line_role_verification_reference':''},{'family':'ride_layout'},{'family':'path','line_role':'boundary'}):
            with self.assertRaises(ValueError):reviewed_feature(candidate,{**review,**changes},source,alignment,'EPSG:27700')
    def test_curved_polygon_requires_approximation_review_and_metric_budget(self):
        doc=pymupdf.open();page=doc.new_page(width=400,height=600);page.draw_circle((30,570),10,fill=(0,0,0));data=doc.tobytes();doc.close();sha=hashlib.sha256(data).hexdigest()
        with pymupdf.open(stream=data,filetype='pdf') as pdf:candidate=extract_page(pdf[0],sha,1)[0][0]
        helper=footprint_tests.FootprintTests();alignment=helper.alignment();source=helper.source(alignment);source=replace(source,sha256=sha,metadata={**source.metadata,'registration_document_sha256':sha});review={**helper.review(),'candidate_id':candidate['id']}
        with self.assertRaisesRegex(ValueError,'approximation review'):reviewed_feature(candidate,review,source,alignment,'EPSG:27700')
        review.update(curve_approximation_reviewed=True,approximation_verification_reference='fixture error envelope checked');feature=reviewed_feature(candidate,review,source,alignment,'EPSG:27700');self.assertGreater(feature.metadata['curve_approximation_error_bound_m'],0)
        candidate['curve_approximation']['chord_error_bound_pdf_points']=10
        with self.assertRaisesRegex(ValueError,'certificate'):reviewed_feature(candidate,review,source,alignment,'EPSG:27700')
    def test_corpus_resume_streams_lines_polygons_and_rejects_source_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);corpus=Corpus(root/'corpus');data,candidate,source,alignment,review=self.line_candidate()
            try:
                corpus.ingest([{'url':'https://portal.test/a','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda u:data);report=run(corpus,root/'out');self.assertEqual(report['candidate_types'],{'line':1});self.assertEqual(run(corpus,root/'out')['resumed_pages'],1)
                (root/'reviews').write_text(json.dumps([review]));(root/'manifest').write_text(json.dumps({'crs':'EPSG:27700','sources':[source.__dict__]}));result=promote(root/'out/geometry-candidates.jsonl',root/'reviews',root/'manifest',root/'features',corpus);self.assertEqual(result['reviewed_records'],1)
                next((root/'corpus/files').glob('*.pdf')).write_bytes(b'changed');report=run(corpus,root/'out');self.assertEqual(report['candidates'],0);self.assertTrue(report['errors'])
            finally:corpus.close()

    def test_curved_polygon_feed_uses_current_retained_matching_records(self):
        from shapely.geometry import mapping,Point
        from voxel_mapper.footprint_matching import run as match
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);corpus=Corpus(root/'corpus');doc=pymupdf.open();page=doc.new_page();page.draw_circle((200,200),80,fill=(.8,.8,.8));page.insert_text((170,200),'Lake');data=doc.tobytes();doc.close()
            try:
                corpus.ingest([{'url':'https://portal.test/a','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda u:data);run(corpus,root/'out')
                (root/'refs').write_text(json.dumps({'type':'FeatureCollection','features':[{'type':'Feature','id':'lake','geometry':mapping(Point(1000,2000).buffer(80)),'properties':{'name':'Lake'}}]}))
                report=match(root/'out/polygon-candidates.jsonl',root/'refs','EPSG:27700','EPSG:27700',root/'matches',corpus=corpus);self.assertEqual(report['counts']['native_with_name_match'],1);self.assertEqual(report['world_geometry_additions'],0)
                candidate=json.loads((root/'out/polygon-candidates.jsonl').read_text());candidate['extraction_contract']='0'*64;(root/'altered').write_text(json.dumps(candidate)+'\n')
                with self.assertRaisesRegex(ValueError,'retained'):match(root/'altered',root/'refs','EPSG:27700','EPSG:27700',root/'changed',corpus=corpus)
            finally:corpus.close()

    def test_park_job_promotes_registered_line_compiles_exports_and_resumes(self):
        import rasterio
        from rasterio.transform import from_origin
        from voxel_mapper.park_pipeline import run as run_job
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);data,candidate,source,alignment,review=self.line_candidate();corpus=Corpus(root/'work/corpus')
            try:corpus.ingest([{'url':'https://portal.test/a','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda u:data)
            finally:corpus.close()
            (root/'reviews').write_text(json.dumps([review]))
            with rasterio.open(root/'terrain.tif','w',driver='GTiff',height=100,width=100,count=1,dtype='float32',crs='EPSG:27700',transform=from_origin(0,500,5,5)) as raster:raster.write(np.zeros((100,100),dtype='float32'),1)
            (root/'terrain-config').write_text(json.dumps({'sources':[{'id':'terrain'}],'terrain':{'path':str(root/'terrain.tif'),'source_id':'terrain','vertical_datum':'ODN','units':'m'}}))
            from shapely.geometry import mapping
            (root/'manifest').write_text(json.dumps({'crs':'EPSG:27700','vertical_datum':'ODN','terrain_sha256':hashlib.sha256((root/'terrain.tif').read_bytes()).hexdigest(),'boundary':mapping(box(0,0,500,500)),'sources':[source.__dict__]}))
            (root/'job').write_text(json.dumps({'work_directory':'work','manifest':'manifest','terrain_config':'terrain-config','acquisition':{'offline':True},'drawing_analysis':{'enabled':False},'drawing_geometry':{'enabled':True,'feature_reviews':'reviews'}}))
            result=run_job(root/'job');self.assertEqual(result['stages']['reconstruction']['features'],1);self.assertGreater(result['stages']['reconstruction']['unique_voxel_cells'],30);self.assertTrue((root/'work/tiles/tiles.jsonl').exists())
            again=run_job(root/'job');self.assertEqual(again['stages']['reconstruction']['unique_voxel_cells'],result['stages']['reconstruction']['unique_voxel_cells'])
            review['line_role_verification_reference']='changed';(root/'reviews').write_text(json.dumps([review]))
            with self.assertRaisesRegex(ValueError,'inputs changed'):run_job(root/'job','reconstruct')

if __name__=='__main__':unittest.main()
