import unittest
from shapely.geometry import box, Polygon, MultiPolygon, mapping, shape
from shapely.affinity import rotate
from voxel_mapper.fill_endcaps import recover
from voxel_mapper.opening_correspondence import cap_corner_options


class FillEndcapTests(unittest.TestCase):
    def candidate(self, name, geom, color=(.5,.5,.5)):
        return {'id': name, 'geometry': mapping(geom), 'fill_color': color}

    def test_separate_paints_keep_source_edges_and_open_gap(self):
        fills = [self.candidate('a', box(0,0,30,2)), self.candidate('b', box(40,0,70,2))]
        r = recover(fills, .1)
        self.assertEqual(len(r['gaps']), 1)
        gap = r['gaps'][0]
        self.assertAlmostEqual(gap['nominal_gap_width_m'], 1)
        self.assertEqual(gap['parent_fill_candidate_ids'], ['a','b'])
        self.assertAlmostEqual(shape(gap['gap_corridor_geometry']).area, 20)
        self.assertFalse(gap['geometry_bridge_added'])
        self.assertEqual(r, recover(fills[::-1], .1))

    def test_complex_wall_return_and_multipart_fill_do_not_need_rectangular_parts(self):
        left = Polygon([(0,0),(30,0),(30,2),(28,2),(28,10),(0,10)])
        right = box(40,0,70,2)
        r = recover([self.candidate('a',MultiPolygon([left,right]))],.1)
        self.assertTrue(any(abs(g['nominal_gap_width_m']-1)<1e-8 for g in r['gaps']))
        self.assertFalse(any(g['physical_opening_verified'] for g in r['gaps']))

    def test_rotation_preserves_width_and_source_corridor(self):
        for angle in (0,35,90,180):
            fills=[self.candidate('a',rotate(box(0,0,30,2),angle,origin=(0,0))),
                   self.candidate('b',rotate(box(40,0,70,2),angle,origin=(0,0)))]
            r=recover(fills,.1)
            self.assertEqual(len(r['gaps']),1)
            self.assertAlmostEqual(r['gaps'][0]['nominal_gap_width_m'],1)

    def test_masks_remain_overlap_flags_and_offset_caps_are_not_joined(self):
        fills=[self.candidate('a',box(0,0,30,2)),self.candidate('b',box(40,0,70,2)),
               self.candidate('mask',box(30,0,40,2),(1,1,1))]
        r=recover(fills,.1)
        self.assertEqual(r['gaps'][0]['intersecting_fill_candidates'],[{'fill_candidate_id':'mask','gap_area_fraction':1}])
        self.assertEqual(recover([fills[0],self.candidate('offset',box(40,10,70,12))],.1)['gaps'],[])
        self.assertEqual(recover([fills[0],self.candidate('different',box(40,0,70,2),(.7,.7,.7))],.1)['gaps'],[])

    def test_budget_duplicate_and_nonfinite_scale_are_refused(self):
        c=self.candidate('a',box(0,0,30,2))
        for fills,unit in (([c,c],.1),([c],float('nan')),([c]*4001,.1)):
            with self.assertRaises(ValueError):recover(fills,unit)

    def test_corner_options_preserve_all_choices_without_selecting_wall_face(self):
        caps=[{'source_endpoints':[[0,0],[0,2]]},{'source_endpoints':[[10,2],[10,0]]}]
        options=cap_corner_options(caps,{'raw_native_endpoints':[[0,0],[10,0]]},[1,0,0,1,0,0],.1,.01)
        self.assertEqual(len(options),8)
        self.assertEqual(sum(o['within_manual_endpoint_sampling_bound'] for o in options),1)
        self.assertTrue(all(not o['physical_wall_face_identity_verified'] for o in options))
