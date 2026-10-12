import copy,hashlib,json
import unittest
from shapely.geometry import Polygon,box
from voxel_mapper.wing_shell_study import build,solid,VERSION
from voxel_mapper.wing_block_shapes import assemble,occupied_halves


class ShellStudyTests(unittest.TestCase):
    def setUp(self):
        from tests.test_wing_block_shapes import WingShapeTests
        from voxel_mapper.local_wing_review import build as front_build
        self.f=WingShapeTests();self.f.setUp();r=copy.deepcopy(self.f.f.recipe)
        r['plan_trace']['rear_point']=[10,105]
        r['openings'][0]['kind']='archway';r['openings'][0]['points_pixels']=[[110,200],[170,200],[170,80],[110,80]]
        r['openings'][1]['points_pixels']=[[180,175],[230,175],[230,80],[180,80]]
        self.parent=front_build(r,self.f.f.paths)
        self.seed={'version':VERSION,'review_hypotheses_acknowledged':True,'parent_model_sha256':hashlib.sha256((json.dumps(self.parent,sort_keys=True,indent=2)+'\n').encode()).hexdigest(),
                   'wall_display_thickness_m':.25,'roof_vertical_display_thickness_m':.25,'floor_display_thickness_m':.25}
    def tearDown(self):self.f.tearDown()

    def test_extrusion_keeps_holes_closed_edges_and_expected_volume(self):
        p=box(0,0,5,3).difference(box(1,1,2,2))
        for axis in range(3):
            m=solid(p,axis,0,.5);self.assertTrue(m['watertight']);self.assertAlmostEqual(m['volume_m3'],7)
        notch=box(0,0,5,3).difference(box(1,0,2,2));self.assertAlmostEqual(solid(notch,1,0,.5)['volume_m3'],6.5)

    def test_shell_preserves_source_front_and_roof_and_records_hypotheses(self):
        original=copy.deepcopy(self.parent);front,_=assemble(self.parent);m,c,a=build(self.parent,self.seed)
        self.assertEqual(self.parent,original);self.assertTrue(all(c[p]==v for p,v in front.items()))
        self.assertEqual(len(m['components']),6);self.assertTrue(all(r['mesh']['watertight'] for r in m['components']))
        self.assertTrue(m['complete_core_shell_preview']);self.assertFalse(m['surveyed_complete_structure'])
        self.assertFalse(m['world_placement_eligible']);self.assertFalse(m['assembly_boolean_union']);self.assertGreater(len(m['assumptions']),0)
        self.assertGreater(a['added_cells'],0);self.assertFalse(any('glass' in v for v in c.values()))

    def test_arch_standing_air_is_preserved_across_full_depth(self):
        m,c,a=build(self.parent,self.seed);half=occupied_halves(c)
        for x in a['arch_columns']:
            for z in range(a['native_grid'][1]):
                for dx in (0,1):
                    for y in range(4):
                        for dz in (0,1):self.assertNotIn((2*x+dx,y,2*z+dz),half)
        self.assertTrue(a['arch_standing_air_verified_through_depth'])

    def test_changed_source_pin_or_unacknowledged_closure_rejects(self):
        for key,value in [('parent_model_sha256','0'*64),('review_hypotheses_acknowledged',False),('wall_display_thickness_m',2),('floor_display_thickness_m',float('nan'))]:
            s=copy.deepcopy(self.seed);s[key]=value
            with self.assertRaises(ValueError):build(self.parent,s)

    def test_deterministic_shell_and_no_mirrored_rear_windows(self):
        a=build(self.parent,self.seed);b=build(self.parent,self.seed);self.assertEqual(a,b)
        m,c,report=a;self.assertEqual(m['rear_arch_profile'],self.parent['openings'][0]['local_polygon_xz'])
        self.assertFalse(m['full_complex_reconstructed'])

if __name__=='__main__':unittest.main()
