import unittest
from shapely.geometry import LineString
from voxel_mapper.park_completion import line_cells,above_terrain_profile,audit_full_route
from voxel_mapper.bedrock import material_block,DETAIL_MATERIALS
class CompletionTests(unittest.TestCase):
    def test_route_audit_rejects_missing_intended_deck_not_just_emitted_subset(self):
        line=LineString([(0,0),(3,0)])
        samples=[{'station_m':s,'corrected_rail_m':105,'terrain_envelope_m':100} for s in (0,1,2)]
        def blocks(x,y,z):return material_block('oak_planks' if y==104 else 'air')
        self.assertEqual(audit_full_route(line,samples,blocks)['route_samples_checked'],3)
        def missing(x,y,z):return material_block('air') if x==1 else blocks(x,y,z)
        with self.assertRaises(ValueError):audit_full_route(line,samples,missing)
    def test_uplift_prevents_burial_and_spreads_into_neighbouring_spans(self):
        import numpy as np
        original=np.full(100,100.2);ground=np.full(100,95.)
        ground[50]=102.8
        corrected,uplift=above_terrain_profile(original,ground,spacing=1,ramp=.5)
        self.assertTrue(np.all(np.floor(corrected)-1 >= np.floor(ground)+2))
        self.assertGreater(uplift[49],0)
        self.assertLessEqual(np.max(np.abs(np.diff(np.r_[uplift,uplift[0]]))),.5+1e-9)
    def test_profile_wrap_is_smooth_and_non_buried_profile_is_unchanged(self):
        import numpy as np
        original=np.full(50,110.);ground=np.full(50,100.)
        corrected,uplift=above_terrain_profile(original,ground)
        np.testing.assert_array_equal(corrected,original)
        ground[0]=112
        corrected,uplift=above_terrain_profile(original,ground)
        self.assertGreater(uplift[-1],0)
        self.assertLessEqual(abs(uplift[0]-uplift[-1]),.048+1e-9)
        with self.assertRaises(ValueError):above_terrain_profile([100],[float('nan')])
    def test_diagonal_route_includes_endpoints_and_only_nearby_cells(self):
        cells=line_cells(LineString([(0,0),(10,10)]))
        self.assertIn((0,0),cells);self.assertIn((10,10),cells)
        self.assertTrue(all(abs(x-z)<=1 for x,z in cells));self.assertLessEqual(len(cells),30)
        reached={(0,0)}
        while True:
            nxt=reached|{p for p in cells if any((p[0]+dx,p[1]+dz) in reached for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)))}
            if nxt==reached:break
            reached=nxt
        self.assertEqual(reached,set(cells))
    def test_transport_geometry_budget(self):
        with self.assertRaises(ValueError):line_cells(LineString([(0,0),(10001,0)]))
    def test_partial_blocks_have_native_bedrock_identifiers(self):
        import PyMCTranslate
        translator=PyMCTranslate.new_translation_manager().get_version('bedrock',(1,21,130)).block
        for material in sorted(DETAIL_MATERIALS):
            with self.subTest(material=material):
                native=translator.from_universal(material_block(material))[0]
                self.assertEqual(native.namespace,'minecraft')
    def test_spruce_planks_keep_material(self):
        self.assertEqual(material_block('spruce_planks').properties['material'].py_data,'spruce')
if __name__=='__main__':unittest.main()
