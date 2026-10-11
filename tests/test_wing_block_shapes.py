import copy
import json
from pathlib import Path
import unittest
from shapely.geometry import box
from voxel_mapper.wing_block_shapes import assemble,fit,occupied_halves
from voxel_mapper.bedrock import material_block


class WingShapeTests(unittest.TestCase):
    def setUp(self):
        from tests.test_local_wing_review import WingReviewTests
        from voxel_mapper.local_wing_review import build
        self.f=WingReviewTests();self.f.setUp();r=self.f.recipe
        r['elevation_trace']['eave_point']=[50,40];r['elevation_trace']['ridge_point']=[50,0]
        r['openings'][0]['points_pixels']=[[65,200],[110,200],[110,80],[65,80]]
        r['openings'][1]['points_pixels']=[[150,175],[200,175],[200,95],[150,95]]
        self.model=build(r,self.f.paths)

    def tearDown(self):self.f.tearDown()

    def test_whole_profile_retains_low_sill_and_inverted_head(self):
        self.assertEqual(fit(box(0,0,1,.3))[1],'slab')
        self.assertEqual(fit(box(0,.7,1,1))[1],'slab_top')
        cells,a=assemble(self.model)
        self.assertTrue(a['native_passage_air_verified'])
        self.assertGreater(sum('slab' in m or 'stairs' in m for m in cells.values()),0)

    def test_source_mesh_and_scale_are_unchanged_and_output_deterministic(self):
        original=copy.deepcopy(self.model);a=assemble(self.model);b=assemble(self.model)
        self.assertEqual(a,b);self.assertEqual(self.model,original)
        self.assertEqual(a[1]['world_blocks_per_source_metre'],1)
        self.assertFalse(a[1]['world_placement_eligible'])

    def test_all_passage_cells_are_air_at_native_shape_resolution(self):
        c,a=assemble(self.model);occupied=occupied_halves(c)
        for passage in a['passage_clearance']:
            for x in passage['columns']:
                for dx in (0,1):
                    for y in range(4):
                        for dz in (0,1):self.assertNotIn((2*x+dx,y,dz),occupied)

    def test_stair_direction_and_upside_down_occupancy_match_native_properties(self):
        for direction,expected in [('east',1),('west',0)]:
            m='stone_brick_stairs_'+direction+'_top';b=material_block(m)
            self.assertEqual(str(b.properties['facing']),direction);self.assertEqual(str(b.properties['half']),'top')
            half=occupied_halves({(0,0,0):m});self.assertEqual(len(half),6)
            self.assertEqual({p[0] for p in half if p[1]==0},{expected})
        for direction,expected in [('north',1),('south',0)]:
            half=occupied_halves({(0,0,0):'dark_oak_stairs_'+direction})
            self.assertEqual({p[2] for p in half if p[1]==1},{expected})

    def test_changed_wall_or_roof_mesh_cannot_be_silently_rebuilt(self):
        altered=copy.deepcopy(self.model);altered['wall_mesh']['vertices'][0][0]+=.2
        with self.assertRaisesRegex(ValueError,'disagree'):assemble(altered)
        altered=copy.deepcopy(self.model);altered['roof_mesh']['vertices'][0][2]+=.2
        with self.assertRaisesRegex(ValueError,'roof mesh'):assemble(altered)

    def test_budget_and_unrepresentable_door_withhold_complete_output(self):
        with self.assertRaisesRegex(ValueError,'budget'):assemble(self.model,max_checks=1)
        with self.assertRaises(ValueError):assemble(self.model,max_checks=True)
        altered=copy.deepcopy(self.model);altered['world_placement_eligible']=True
        with self.assertRaises(ValueError):assemble(altered)
        from voxel_mapper.local_wing_review import build
        recipe=copy.deepcopy(self.f.recipe)
        recipe['openings'][0]['points_pixels']=[[65,200],[75,200],[75,80],[65,80]]
        narrow=build(recipe,self.f.paths)
        with self.assertRaisesRegex(ValueError,'Standing passage'):assemble(narrow)

    def test_glazing_is_optional_and_kept_out_of_passages(self):
        c,a=assemble(self.model);plain,_=assemble(self.model,glazing=False)
        self.assertGreater(len(a['glass_proxy_cells']),0)
        self.assertFalse(any(m=='glass' for m in plain.values()))
        for glass in a['glass_proxy_cells']:
            x,y,z=glass['cell'];self.assertEqual(z,1)
            self.assertTrue(any(c.get((x,below,0),'').startswith('stone') for below in range(y)))

    def test_roof_profiles_and_native_states_survive_cold_export(self):
        from scripts.build_local_wing_review import isolated_world
        r=isolated_world(self.model,self.f.root/'world',native_shapes=True)
        a=r['native_shape_audit']
        self.assertLessEqual(a['roof_top_profile_hausdorff_m'],a['roof_profile_error_bound_m'])
        self.assertTrue(a['roof_adjacent_profile_contact_verified'])
        self.assertEqual(r['world']['round_trip_validation'],'all written blocks and all unwritten air cells verified')

if __name__=='__main__':unittest.main()
