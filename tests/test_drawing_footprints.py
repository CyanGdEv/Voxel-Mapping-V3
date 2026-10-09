import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import pymupdf
from shapely.geometry import Polygon,box,shape,mapping
from voxel_mapper.drawing_footprints import extract_page,fill_geometry,reviewed_feature,promote,run
from voxel_mapper.reconstruction.model import Source,Feature
from voxel_mapper.reconstruction.registration import review_registration
from voxel_mapper.reconstruction.batch import GeometryStore
from voxel_mapper.reconstruction.engine import Context
from voxel_mapper.reconstruction.sources import evidence
from voxel_mapper.planning_bulk import Corpus

class FootprintTests(unittest.TestCase):
    def candidate(self):
        geometry=mapping(box(20,20,40,40));sha='a'*64
        identifier=hashlib.sha256((sha+'/1/'+shape(geometry).normalize().wkb_hex).encode()).hexdigest()
        return {'id':identifier,'document_sha256':sha,'page':1,'geometry':geometry,'coordinate_frame':'pdf_native_points_y_up','rendering_status':'supported_straight_unclipped_polygon'}
    def alignment(self):
        def pair(id,x,y):return {'id':id,'local':[x,y],'target':[100+x,200+y],'source_id':'controls' if id in ('a','b','c') else 'checks','source_sha256':('c' if id in ('a','b','c') else 'd')*64,'independent':id in ('d','e')}
        report=review_registration([pair('a',0,0),pair('b',100,0),pair('c',0,100)],[pair('d',60,60),pair('e',80,20)])
        report['target_crs']='EPSG:27700';return report
    def source(self,alignment):
        return Source('drawing','planning','https://portal.test/a','fixture','EPSG:27700','ODN','accepted','a'*64,{'horizontal_registration_review':alignment,'registration_document_sha256':'a'*64,'registration_page':1})
    def review(self):
        return {'candidate_id':self.candidate()['id'],'feature_id':'path/a','source_id':'drawing','family':'path','physical_identity_verified':True,'verification_reference':'fixture-reviewed-corner-identity','reuse_allowed':True,'drawing_state':'existing','state_verification_reference':'fixture-existing-survey','parameters':{'surface':evidence('asphalt','drawing')}}
    def test_fill_rules_preserve_holes_and_nonzero_orientation(self):
        outer=list(box(0,0,10,10).exterior.coords);inner=list(box(2,2,8,8).exterior.coords)
        self.assertAlmostEqual(fill_geometry([outer,inner],True,True).area,64)
        self.assertAlmostEqual(fill_geometry([outer,inner],False,True).area,100)
        self.assertAlmostEqual(fill_geometry([outer,inner[::-1]],False,True).area,64)
    def test_real_closed_outline_and_label_hypothesis(self):
        doc=pymupdf.open();page=doc.new_page(width=400,height=600);page.draw_rect(pymupdf.Rect(100,100,250,220));page.insert_text((120,160),'Existing path asphalt')
        candidates,report=extract_page(page,'a'*64,1)
        self.assertEqual(len(candidates),1);self.assertTrue(candidates[0]['label_hypotheses']);self.assertFalse(candidates[0]['physical_identity_verified'])
        self.assertEqual(report['world_geometry_additions'],0);doc.close()
    def test_open_lines_curves_and_sheet_border_are_not_footprints(self):
        doc=pymupdf.open();page=doc.new_page(width=400,height=600);page.draw_line((20,20),(100,20));page.draw_circle((150,150),30);page.draw_rect(page.rect)
        candidates,report=extract_page(page,'a'*64,1);self.assertFalse(candidates)
        self.assertIn('Open stroked path; not a footprint',report['rejections']);doc.close()
    def test_evenodd_hole_survives_real_pdf_and_rotation(self):
        doc=pymupdf.open();page=doc.new_page(width=400,height=600);drawing=page.new_shape();drawing.draw_rect(pymupdf.Rect(100,100,300,300));drawing.draw_rect(pymupdf.Rect(150,150,250,250));drawing.finish(color=None,fill=(.5,.5,.5),even_odd=True);drawing.commit()
        identities=[]
        for angle in (0,90,180,270):
            page.set_rotation(angle);candidates,_=extract_page(page,'a'*64,1);self.assertEqual(len(candidates),1);self.assertEqual(len(shape(candidates[0]['geometry']).interiors),1);identities.append(candidates[0]['id']);self.assertEqual(page.rotation,angle)
        self.assertEqual(len(set(identities)),1);doc.close()
    def test_path_budget_is_explicit(self):
        doc=pymupdf.open();page=doc.new_page();page.draw_rect(pymupdf.Rect(20,20,50,50));candidates,report=extract_page(page,'a'*64,1,max_paths=0)
        self.assertFalse(candidates);self.assertEqual(report['status'],'path_budget_withheld');doc.close()
    def test_reviewed_polygon_enters_existing_batch_generator(self):
        alignment=self.alignment();source=self.source(alignment);feature=reviewed_feature(self.candidate(),self.review(),source,alignment,'EPSG:27700')
        with tempfile.TemporaryDirectory() as directory:
            store=GeometryStore(Path(directory)/'geometry.sqlite',{'fixture':'reviewed-polygon'})
            try:
                ctx=Context({'drawing':source},lambda x,z:0,box(0,0,500,500),'ODN')
                report=store.compile([feature],ctx);self.assertEqual(report['decisions'],{'planned':1});self.assertEqual(report['unique_voxel_cells'],400)
            finally:store.close()
    def test_proposal_missing_identity_or_state_reviews_are_withheld(self):
        alignment=self.alignment();source=self.source(alignment)
        for key,value in [('drawing_state','proposed'),('physical_identity_verified',False),('reuse_allowed',False),('state_verification_reference','')]:
            review=self.review();review[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):reviewed_feature(self.candidate(),review,source,alignment,'EPSG:27700')
    def test_candidate_tampering_page_and_alignment_evidence_mismatch(self):
        alignment=self.alignment();source=self.source(alignment);candidate=self.candidate();candidate['geometry']=mapping(box(21,20,41,40))
        with self.assertRaises(ValueError):reviewed_feature(candidate,self.review(),source,alignment,'EPSG:27700')
        source=self.source(alignment);source.metadata['registration_page']=2
        with self.assertRaises(ValueError):reviewed_feature(self.candidate(),self.review(),source,alignment,'EPSG:27700')
        altered=copy.deepcopy(alignment);altered['translation_m'][0]+=1
        with self.assertRaises(ValueError):reviewed_feature(self.candidate(),self.review(),self.source(altered),altered,'EPSG:27700')
    def test_checked_landmark_overlap_and_domain_extrapolation(self):
        alignment=self.alignment();review=self.review();review['checked_landmark']={'id':'path-corners','independently_checked':True,'source_sha256':'b'*64,'crs':'EPSG:27700','geometry':mapping(box(120,220,140,240))}
        feature=reviewed_feature(self.candidate(),review,self.source(alignment),alignment,'EPSG:27700')
        self.assertAlmostEqual(feature.metadata['checked_landmark_association']['intersection_over_union'],1)
        review['checked_landmark']['geometry']=mapping(box(300,300,320,320))
        with self.assertRaises(ValueError):reviewed_feature(self.candidate(),review,self.source(alignment),alignment,'EPSG:27700')
        candidate=self.candidate();candidate['geometry']=mapping(box(150,150,170,170));candidate['id']=hashlib.sha256(('a'*64+'/1/'+shape(candidate['geometry']).normalize().wkb_hex).encode()).hexdigest();review=self.review();review['candidate_id']=candidate['id']
        with self.assertRaises(ValueError):reviewed_feature(candidate,review,self.source(alignment),alignment,'EPSG:27700')
    def test_promotion_streams_only_current_corpus_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);alignment=self.alignment();corpus=Corpus(root/'corpus')
            doc=pymupdf.open();page=doc.new_page(width=400,height=600);page.draw_rect(pymupdf.Rect(20,560,40,580));data=doc.tobytes();doc.close();sha=hashlib.sha256(data).hexdigest()
            try:
                corpus.ingest([{'url':'https://portal.test/a','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda u:data);run(corpus,root/'out')
                candidate=json.loads((root/'out/footprint-candidates.jsonl').read_text());review=self.review();review['candidate_id']=candidate['id']
                source=Source('drawing','planning','https://portal.test/a','fixture','EPSG:27700','ODN','accepted',sha,{'horizontal_registration_review':alignment,'registration_document_sha256':sha,'registration_page':1})
                (root/'reviews.json').write_text(json.dumps([review,{**review,'candidate_id':'missing'}]));(root/'manifest.json').write_text(json.dumps({'crs':'EPSG:27700','sources':[source.__dict__]}))
                report=promote(root/'out/footprint-candidates.jsonl',root/'reviews.json',root/'manifest.json',root/'features.jsonl',corpus)
                self.assertEqual(report['reviewed_records'],1);self.assertEqual(report['decisions'][-1]['status'],'withheld')
                candidate['paint_ordinals']=[999];(root/'altered.jsonl').write_text(json.dumps(candidate)+'\n')
                report=promote(root/'altered.jsonl',root/'reviews.json',root/'manifest.json',root/'changed-features.jsonl',corpus)
                self.assertEqual(report['reviewed_records'],0)
            finally:corpus.close()
    def test_park_job_promotes_compiles_exports_and_resumes_reviewed_footprint(self):
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin
        from voxel_mapper.park_pipeline import run as run_job
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);work=root/'work';corpus=Corpus(work/'corpus');alignment=self.alignment()
            doc=pymupdf.open();page=doc.new_page(width=400,height=600);page.draw_rect(pymupdf.Rect(20,560,40,580));data=doc.tobytes();doc.close();sha=hashlib.sha256(data).hexdigest()
            try:
                corpus.ingest([{'url':'https://portal.test/a','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda u:data);run(corpus,work/'footprints')
            finally:corpus.close()
            candidate=json.loads((work/'footprints/footprint-candidates.jsonl').read_text());review=self.review();review['candidate_id']=candidate['id'];(root/'reviews.json').write_text(json.dumps([review]))
            source=Source('drawing','planning','https://portal.test/a','fixture','EPSG:27700','ODN','accepted',sha,{'horizontal_registration_review':alignment,'registration_document_sha256':sha,'registration_page':1})
            with rasterio.open(root/'terrain.tif','w',driver='GTiff',height=100,width=100,count=1,dtype='float32',crs='EPSG:27700',transform=from_origin(0,500,5,5)) as raster:raster.write(np.zeros((100,100),dtype='float32'),1)
            (root/'terrain-config.json').write_text(json.dumps({'sources':[{'id':'terrain'}],'terrain':{'path':str(root/'terrain.tif'),'source_id':'terrain','vertical_datum':'ODN','units':'m'}}))
            (root/'manifest.json').write_text(json.dumps({'crs':'EPSG:27700','vertical_datum':'ODN','terrain_sha256':hashlib.sha256((root/'terrain.tif').read_bytes()).hexdigest(),'boundary':mapping(box(0,0,500,500)),'sources':[source.__dict__]}))
            (root/'job.json').write_text(json.dumps({'work_directory':'work','manifest':'manifest.json','terrain_config':'terrain-config.json','footprint_extraction':{'enabled':True,'feature_reviews':'reviews.json'}}))
            result=run_job(root/'job.json','reconstruct');self.assertEqual(result['stages']['reconstruction']['unique_voxel_cells'],400);self.assertTrue((work/'tiles/tiles.jsonl').exists())
            result=run_job(root/'job.json','reconstruct');self.assertEqual(result['stages']['reconstruction']['features'],1);self.assertEqual(result['stages']['reconstruction']['unique_voxel_cells'],400)
            review['drawing_state']='proposed';(root/'reviews.json').write_text(json.dumps([review]))
            with self.assertRaises(ValueError):run_job(root/'job.json','reconstruct')
    def test_corpus_resume_and_corrupt_source_exclusion(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);corpus=Corpus(root/'corpus');doc=pymupdf.open();page=doc.new_page();page.draw_rect(pymupdf.Rect(100,100,200,200));data=doc.tobytes();doc.close()
            try:
                corpus.ingest([{'url':'https://portal.test/a','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda u:data)
                report=run(corpus,root/'out');self.assertEqual(report['polygon_candidates'],1)
                self.assertEqual(run(corpus,root/'out')['resumed_pages'],1)
                next((root/'corpus/files').glob('*.pdf')).write_bytes(b'changed');report=run(corpus,root/'out');self.assertEqual(report['polygon_candidates'],0);self.assertTrue(report['errors'])
            finally:corpus.close()

if __name__=='__main__':unittest.main()
