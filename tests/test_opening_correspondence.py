import math
import unittest
from voxel_mapper.opening_correspondence import compare, nearby_plan_segments
from shapely.geometry import box, mapping


class OpeningCorrespondenceTests(unittest.TestCase):
    def test_nearby_door_strokes_keep_all_roles_unassigned(self):
        edges=[{'id':'near','points':[[0,0],[8,0]]},
               {'id':'far','points':[[100,100],[108,100]]},
               {'id':'long','points':[[0,0],[80,0]]}]
        r=nearby_plan_segments(edges,mapping(box(0,-1,10,1)),.1,[1,0,0,1,0,0],[[1.1,0],[0,1]])
        self.assertEqual([row['source_edge']['id'] for row in r],['near'])
        self.assertAlmostEqual(r[0]['layout_normalized_length_m'],.88)
        self.assertFalse(r[0]['door_leaf_or_reveal_role_verified'])
    def gap(self, points=((0, 0), (10, 0))):
        return {'coordinate_frame': 'unrotated_mupdf_points_y_down', 'fill_candidate_id': 'fill',
                'projected_gap_endpoints': points, 'nominal_gap_width_m': 1}

    def run_compare(self, gaps, openings, **kwargs):
        return compare(gaps, openings, kwargs.get('native', [1, 0, 0, 1, 0, 0]),
                       kwargs.get('layout', [[1, 0], [0, 1]]), .1, .01)

    def test_same_width_elsewhere_cannot_match_and_endpoint_order_is_irrelevant(self):
        openings = [{'id': 'near', 'raw_native_endpoints': [[10, 0], [0, 0]]},
                    {'id': 'far', 'raw_native_endpoints': [[100, 0], [110, 0]]}]
        r = self.run_compare([self.gap()], openings)[0]
        self.assertEqual([m['reviewed_opening_id'] for m in r['reviewed_trace_candidates']], ['near'])
        self.assertFalse(r['physical_opening_verified'])

    def test_layout_scaling_is_directional_and_does_not_move_source_points(self):
        r = self.run_compare([self.gap()], [], layout=[[1.1, 0], [0, 1.2]])[0]
        self.assertAlmostEqual(r['layout_normalized_width_m'], 1.1)
        self.assertEqual(r['source_gap_endpoints_native'], [[0, 0], [10, 0]])
        y = self.run_compare([self.gap(((0, 0), (0, 10)))], [], layout=[[1.1, 0], [0, 1.2]])[0]
        self.assertAlmostEqual(y['layout_normalized_width_m'], 1.2)

    def test_native_conversion_precedes_layout_correction(self):
        r = self.run_compare([self.gap()], [{'id': 'a', 'raw_native_endpoints': [[50, 100], [50, 110]]}],
                             native=[0, 1, -1, 0, 50, 100], layout=[[1.1, 0], [0, 1.2]])[0]
        self.assertEqual(r['status'], 'unverified_reviewed_trace_candidate')
        self.assertAlmostEqual(r['layout_normalized_width_m'], 1.2)

    def test_discovery_match_outside_sampling_bound_remains_flagged(self):
        r = self.run_compare([self.gap()], [{'id': 'a', 'raw_native_endpoints': [[0, 1], [10, 1]]}])[0]
        m = r['reviewed_trace_candidates'][0]
        self.assertFalse(m['within_manual_endpoint_sampling_bound'])
        self.assertFalse(m['physical_correspondence_verified'])

    def test_duplicates_remain_ambiguous_and_invalid_inputs_are_refused(self):
        opening = {'id': 'a', 'raw_native_endpoints': [[0, 0], [10, 0]]}
        self.assertEqual(self.run_compare([self.gap()], [opening, {**opening, 'id': 'b'}])[0]['status'], 'ambiguous_reviewed_traces')
        for layout in ([[1, 0], [0, -1]], [[math.nan, 0], [0, 1]]):
            with self.assertRaises(ValueError):
                self.run_compare([self.gap()], [], layout=layout)
        with self.assertRaises(ValueError):
            self.run_compare([self.gap(((math.nan, 0), (10, 0)))], [])
