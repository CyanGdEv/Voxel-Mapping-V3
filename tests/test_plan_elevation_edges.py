import math
import unittest
from unittest.mock import patch

import pymupdf
from voxel_mapper.plan_elevation_edges import plan_scale, straight_edges, match_edges


class EdgeTests(unittest.TestCase):
    def test_all_equal_length_edges_retained_without_nearest_selection(self):
        edges = [{'id': name, 'length_pdf_points': length} for name, length in
                 [('b', 100), ('a', 101), ('c', 400)]]
        matches = match_edges(edges, .1, 10, tolerance_m=.25)
        self.assertEqual([m['id'] for m in matches], ['a', 'b'])
        self.assertAlmostEqual(matches[0]['plan_minus_elevation_width_m'], .1)
        self.assertFalse(any('selected' in m for m in matches))

    def test_fragmented_line_is_not_bridged_into_false_outer_edge(self):
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.draw_line((10, 10), (60, 10))
            page.draw_line((60, 10), (110, 10))
            edges = straight_edges(page, 'source', 1)
            self.assertEqual(match_edges(edges, .1, 10), [])
            self.assertEqual(len(match_edges(edges, .1, 5)), 2)

    def test_dashed_and_transparent_drafting_is_excluded(self):
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.draw_line((10, 10), (110, 10), dashes='[2 2] 0')
            page.draw_line((10, 20), (110, 20), stroke_opacity=.5)
            page.draw_line((10, 30), (110, 30))
            edges = straight_edges(page, 'source', 1)
            self.assertEqual(len(edges), 1)
            self.assertEqual(edges[0]['points'], [[10, 30], [110, 30]])
            self.assertFalse(edges[0]['clipping_and_visibility_verified'])
            self.assertFalse(edges[0]['outer_component_edge_verified'])

    def test_rotated_rectangle_retains_native_provenance_and_lengths(self):
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.draw_rect((10, 20, 110, 70))
            before = straight_edges(page, 'source', 1)
            page.set_rotation(90)
            self.assertEqual(before, straight_edges(page, 'source', 1))
            self.assertEqual(sorted(e['length_pdf_points'] for e in before), [50, 50, 100, 100])
            self.assertEqual(len({e['id'] for e in before}), 4)

    def test_scale_claims_need_visibility_and_conflicts_remain_held(self):
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((50, 50), '1 : 100')
            with patch('voxel_mapper.plan_elevation_edges.screen_span', return_value={'status': 'withheld'}):
                self.assertIsNone(plan_scale(page)['nominal_metres_per_pdf_point_candidate'])
            with patch('voxel_mapper.plan_elevation_edges.screen_span', return_value={'status': 'raster_consistent_candidate'}):
                scale = plan_scale(page)
                self.assertAlmostEqual(scale['nominal_metres_per_pdf_point_candidate'], 100 * .0254 / 72)
                self.assertFalse(scale['scale_verified'])
                page.insert_text((50, 80), '1 : 200@A1')
                self.assertIsNone(plan_scale(page)['nominal_metres_per_pdf_point_candidate'])

    def test_budget_and_nonfinite_inputs_fail_closed(self):
        for width in (math.nan, math.inf, 0, -1):
            with self.assertRaises(ValueError):
                match_edges([], .1, width)
        with self.assertRaises(ValueError):
            match_edges([], .1, 10, tolerance_m=2)
        with self.assertRaises(ValueError):
            match_edges([{}] * 20001, .1, 10)
        with self.assertRaises(ValueError):
            match_edges([{'id': str(i), 'length_pdf_points': 100} for i in range(501)], .1, 10)


if __name__ == '__main__':
    unittest.main()
