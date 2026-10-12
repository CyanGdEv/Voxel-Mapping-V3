import copy
import hashlib
import unittest
from types import SimpleNamespace

import numpy as np
from shapely.affinity import rotate,scale,translate
from shapely.geometry import Polygon,box,mapping
from voxel_mapper.boundary_registration import fit_boundary,checked_registration

class BoundaryTests(unittest.TestCase):
    def polygon(self):return Polygon([(10,10),(70,10),(70,30),(40,30),(40,65),(10,65)])
    def test_asymmetric_corners_recover_known_rotation_scale_and_translation(self):
        local=self.polygon();target=translate(rotate(scale(local,xfact=2,yfact=2,origin=(0,0)),27,origin=(0,0)),1000,2000)
        result=fit_boundary(local,target)
        self.assertAlmostEqual(result['best_fit']['intersection_over_union'],1)
        self.assertAlmostEqual(result['best_fit']['rotation_degrees'],27)
        self.assertAlmostEqual(result['best_fit']['scale_metres_per_pdf_point'],2)
        self.assertFalse(result['registration_verified']);self.assertFalse(result['independent_checkpoints'])
    def test_rectangle_symmetry_is_ambiguous_even_with_perfect_overlap(self):
        result=fit_boundary(box(0,0,20,10),box(100,200,140,220))
        self.assertAlmostEqual(result['best_fit']['intersection_over_union'],1)
        self.assertIn('ambiguous_boundary_orientation',result['review_flags'])
    def test_holes_preserved_and_mismatch_withheld(self):
        local=Polygon(box(0,0,100,100).exterior.coords,[box(20,20,30,30).exterior.coords])
        self.assertEqual(fit_boundary(local,box(0,0,100,100))['status'],'withheld')
        self.assertAlmostEqual(fit_boundary(local,translate(local,100,200))['best_fit']['intersection_over_union'],1)
    def test_printed_scale_rejects_resizing_to_make_geometry_fit(self):
        result=fit_boundary(self.polygon(),scale(self.polygon(),xfact=2,yfact=2),scale_denominators=[100])
        self.assertIn('printed_scale_disagreement',result['review_flags'])
        result=fit_boundary(self.polygon(),scale(self.polygon(),xfact=500*.0254/72,yfact=500*.0254/72),scale_denominators=[500])
        self.assertNotIn('printed_scale_disagreement',result['review_flags'])
    def fixture(self):
        local=self.polygon();sha='a'*64;reference=translate(local,100,200)
        candidate={'id':hashlib.sha256((sha+'/1/'+local.normalize().wkb_hex).encode()).hexdigest(),'geometry':mapping(local),'document_sha256':sha,'page':1,'coordinate_frame':'pdf_native_points_y_up'}
        hypothesis=fit_boundary(local,reference);hypothesis.update(candidate_id=candidate['id'],document_sha256=sha,page=1,reference_id='mapped',reference_sha256='b'*64,target_crs='EPSG:27700')
        def pair(id,x,y,check=False):return {'id':id,'local':[x,y],'target':[x+100,y+200],'source_id':'checks' if check else 'controls','source_sha256':('d' if check else 'c')*64,'independent':check}
        spec={'candidate_id':candidate['id'],'document_sha256':sha,'page':1,'reference_id':'mapped','reference_sha256':'b'*64,'target_crs':'EPSG:27700','local_frame':'pdf_native_points_y_up','landmark_identity_reviewed':True,'expected_metres_per_pdf_point':1,'controls':[pair('a',0,0),pair('b',100,0),pair('c',0,100)],'checkpoints':[pair('d',100,100,True),pair('e',50,50,True)]}
        return candidate,hypothesis,spec,SimpleNamespace(cropbox=[0,0,200,200])
    def test_independent_review_recomputed_and_binds_exact_source(self):
        candidate,hypothesis,spec,page=self.fixture();result=checked_registration(hypothesis,candidate,spec,page)
        self.assertEqual(result['status'],'accepted_horizontal_fit');self.assertLess(result['boundary_hypothesis_disagreement_m'],1e-8)
        for key in ('candidate_id','document_sha256','reference_id','reference_sha256'):
            bad=copy.deepcopy(spec);bad[key]='wrong'
            with self.assertRaises(ValueError):checked_registration(hypothesis,candidate,bad,page)
    def test_boundary_reference_cannot_be_relabelled_as_independent_check(self):
        candidate,hypothesis,spec,page=self.fixture();spec['checkpoints'][0]['source_sha256']='b'*64
        with self.assertRaisesRegex(ValueError,'independently sourced'):checked_registration(hypothesis,candidate,spec,page)
    def test_wrong_fit_withheld_and_domain_extrapolation_rejected(self):
        candidate,hypothesis,spec,page=self.fixture();hypothesis['best_fit']['translation_m']=[200,300];hypothesis['equivalent_orientations']=[]
        self.assertEqual(checked_registration(hypothesis,candidate,spec,page)['status'],'withheld')
        candidate,hypothesis,spec,page=self.fixture()
        for row in spec['controls']+spec['checkpoints']:
            row['local']=[v*.2 for v in row['local']];row['target']=[row['local'][0]+100,row['local'][1]+200]
        with self.assertRaisesRegex(ValueError,'extrapolation'):checked_registration(hypothesis,candidate,spec,page)

    def test_park_job_checks_registration_and_resumes_with_pinned_review(self):
        import json
        from pathlib import Path
        import tempfile
        import pymupdf
        from voxel_mapper.planning_bulk import Corpus
        from voxel_mapper.drawing_footprints import run as extract
        from voxel_mapper.park_pipeline import run as run_job
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);corpus=Corpus(root/'work/corpus');doc=pymupdf.open();page=doc.new_page(width=400,height=600);page.draw_rect(pymupdf.Rect(10,530,70,590));data=doc.tobytes();doc.close()
            try:
                corpus.ingest([{'url':'https://portal.test/a','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda u:data);extract(corpus,root/'work/footprints')
            finally:corpus.close()
            candidate=json.loads((root/'work/footprints/footprint-candidates.jsonl').read_text())
            geometry=translate(box(10,10,70,70),100,200)
            (root/'refs').write_text(json.dumps({'type':'FeatureCollection','features':[{'type':'Feature','id':'mapped','geometry':mapping(geometry),'properties':{'name':'Building'}}]}))
            _,_,spec,_=self.fixture();spec.update(candidate_id=candidate['id'],document_sha256=candidate['document_sha256'],reference_id='mapped',reference_sha256=hashlib.sha256((root/'refs').read_bytes()).hexdigest())
            (root/'reviews').write_text(json.dumps([spec]))
            (root/'job').write_text(json.dumps({'work_directory':'work','acquisition':{'offline':True},'drawing_analysis':{'enabled':False},'footprint_extraction':{'enabled':True},'footprint_matching':{'enabled':True,'references':'refs','reference_crs':'EPSG:27700','target_crs':'EPSG:27700'},'boundary_registration':{'enabled':True,'reviews':'reviews'}}))
            first=run_job(root/'job','acquire');report=first['stages']['boundary_registration']
            self.assertEqual(report['accepted_independent_reviews'],1);self.assertEqual(report['world_geometry_additions'],0)
            records=[json.loads(line) for line in (root/'work/boundary-registration/boundary-hypotheses.jsonl').read_text().splitlines()]
            self.assertTrue(records[0]['registration_verified']);self.assertFalse(records[0]['physical_identity_verified'])
            self.assertEqual(run_job(root/'job','acquire')['stages']['boundary_registration'],report)
            spec['tolerance_m']=.1;(root/'reviews').write_text(json.dumps([spec]))
            with self.assertRaisesRegex(ValueError,'Boundary inputs changed'):run_job(root/'job','acquire')

if __name__=='__main__':unittest.main()
