import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import pymupdf
from voxel_mapper.local_wing_review import VERSION,build,run


class WingReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.paths={};specs={}
        for key,den in [('plan',100),('elevation',50),('roof',200)]:
            doc=pymupdf.open();p=doc.new_page(width=700,height=300);p.insert_text((10,280),'Existing '+key)
            raw=doc.tobytes();sha=hashlib.sha256(raw).hexdigest();path=self.root/(key+'.pdf');path.write_bytes(raw)
            pix=p.get_pixmap();self.paths[key]=path
            specs[key]={'sha256':sha,'page':1,'state':'existing','caption':'Existing '+key,'scale_denominator':den,
                'render_width_pixels':700,'render_size_pixels':[pix.width,pix.height],
                'render_samples_sha256':hashlib.sha256(pix.samples).hexdigest()};doc.close()
        self.recipe={'version':VERSION,'component_id':'test-wing','reviewed_trace_seed':True,'documents':specs,
          'endpoint_sampling_bound_pixels':2,'plan_trace':{'facade_endpoints':[[10,20],[110,20]],'rear_point':[10,70]},
          'elevation_trace':{'baseline_endpoints':[[50,200],[250,200]],'eave_point':[50,120],'ridge_point':[50,70]},
          'roof_trace':{'cross_section_points':[[10,20],[35,20],[60,20]]},
          'openings':[{'id':'door','kind':'door','points_pixels':[[80,200],[100,200],[100,155],[80,155]]},
                      {'id':'window','kind':'window','points_pixels':[[150,170],[180,170],[180,135],[150,135]]}]}

    def tearDown(self):self.tmp.cleanup()

    def test_real_height_mesh_preserves_opening_area_and_is_never_placed(self):
        m=build(self.recipe,self.paths)
        self.assertGreater(max(v[2] for v in m['roof_mesh']['vertices']),0)
        self.assertAlmostEqual(m['wall_area_m2']+m['opening_area_m2'],m['width_check']['elevation_length_m']*m['measurements']['eaves_m'])
        from shapely.geometry import Polygon
        triangles=[Polygon([(m['wall_mesh']['vertices'][i][0],m['wall_mesh']['vertices'][i][2]) for i in f]) for f in m['wall_mesh']['triangles']]
        for hole in m['openings']:
            self.assertTrue(all(t.intersection(Polygon(hole['local_polygon_xz'])).area<1e-10 for t in triangles))
        self.assertFalse(m['world_placement_eligible']);self.assertEqual(m['world_geometry_additions'],0)
        self.assertFalse(m['automatic_trace_extraction'])
        self.assertEqual(build(self.recipe,self.paths),m)

    def test_width_conflict_withholds_entire_mesh_without_fitting_scale(self):
        self.recipe['plan_trace']['facade_endpoints'][1]=[180,20]
        m=build(self.recipe,self.paths);self.assertEqual(m['status'],'withheld_cross_sheet_width_conflict')
        self.assertIsNone(m['wall_mesh']);self.assertIsNone(m['roof_mesh'])

    def test_wrong_state_caption_or_source_is_rejected(self):
        for field,value in [('state','proposed'),('caption','Another building'),('sha256','0'*64)]:
            r=copy.deepcopy(self.recipe);r['documents']['elevation'][field]=value
            with self.assertRaises(ValueError):build(r,self.paths)
        self.paths['plan'].write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'checksum'):build(self.recipe,self.paths)

    def test_stale_raster_and_outside_points_rejected(self):
        self.recipe['documents']['plan']['render_samples_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'raster'):build(self.recipe,self.paths)
        self.recipe['documents']['plan']['render_samples_sha256']=hashlib.sha256(pymupdf.open(self.paths['plan'])[0].get_pixmap().samples).hexdigest()
        self.recipe['plan_trace']['rear_point']=[float('nan'),70]
        with self.assertRaisesRegex(ValueError,'finite'):build(self.recipe,self.paths)

    def test_overlapping_or_overheight_openings_rejected(self):
        self.recipe['openings'].append({**self.recipe['openings'][0],'id':'duplicate'})
        with self.assertRaisesRegex(ValueError,'overlap'):build(self.recipe,self.paths)
        self.recipe['openings'].pop();self.recipe['openings'][0]['points_pixels'][2]=[100,50]
        with self.assertRaisesRegex(ValueError,'opening'):build(self.recipe,self.paths)

    def test_unchanged_replay_reuses_and_modified_receipt_rejects(self):
        path=self.root/'recipe.json';path.write_text(json.dumps(self.recipe));out=self.root/'out'
        first=run(path,self.paths,out);second=run(path,self.paths,out)
        self.assertFalse(first['reused']);self.assertTrue(second['reused'])
        Path(first['model_path']).write_text('{}')
        with self.assertRaisesRegex(ValueError,'fresh output'):run(path,self.paths,out)

    def test_ridge_point_must_belong_to_reviewed_cross_section(self):
        self.recipe['roof_trace']['cross_section_points'][1]=[35,100]
        with self.assertRaisesRegex(ValueError,'Ridge'):build(self.recipe,self.paths)
