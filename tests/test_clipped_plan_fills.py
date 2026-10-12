import unittest
from shapely.geometry import shape, Point, box, MultiPolygon, mapping
from shapely.affinity import rotate
import pymupdf
from voxel_mapper.clipped_plan_fills import recover, discontinuities, audit_discontinuities


def page_with_content(doc, content):
    page = doc.new_page(width=300, height=300)
    page.draw_rect((1, 1, 2, 2))
    doc.update_stream(page.get_contents()[0], content.encode())
    return page


class ClippedFillTests(unittest.TestCase):
    def test_gap_coordinates_follow_rotation_and_width(self):
        from shapely.geometry import LineString
        g = MultiPolygon([box(0, 0, 40, 2), box(60, 0, 100, 2)])
        original = None
        for angle in (0, 35, 90, 180):
            gap = discontinuities({'id': 'wall', 'geometry': mapping(rotate(g, angle, origin=(0, 0))), 'fill_color': [.5]*3}, .1)[0]
            corridor = shape(gap['gap_corridor_geometry'])
            if original is None:
                original = corridor
            self.assertLess(corridor.symmetric_difference(rotate(original, angle, origin=(0, 0))).area, 1e-8)
            self.assertAlmostEqual(LineString(gap['projected_gap_endpoints']).length * .1, gap['nominal_gap_width_m'])
            self.assertFalse(gap['physical_attachment_points_verified'])

    def test_gap_overlap_audit_retains_masks_without_claiming_visibility(self):
        wall = {'id': 'wall', 'geometry': mapping(MultiPolygon([box(0, 0, 40, 2), box(60, 0, 100, 2)])), 'fill_color': [.5]*3, 'paint_seqno': 1}
        mask = {'id': 'mask', 'geometry': mapping(box(45, 0, 55, 2)), 'fill_color': [1]*3, 'paint_seqno': 2}
        touch = {'id': 'touch', 'geometry': mapping(box(40, 2, 60, 4)), 'fill_color': [.5]*3, 'paint_seqno': 3}
        gap = audit_discontinuities([wall, mask, touch], .1)[0]
        self.assertEqual([r['fill_candidate_id'] for r in gap['intersecting_fill_candidates']], ['mask'])
        self.assertAlmostEqual(gap['intersecting_fill_candidates'][0]['gap_area_fraction'], .5)
        self.assertFalse(gap['complete_page_visibility_verified'])
        self.assertEqual(audit_discontinuities([wall], .1)[0]['visibility_review_status'], 'no_retained_fill_overlap')

    def test_discontinuity_width_is_rotation_independent_and_not_a_door_claim(self):
        g = MultiPolygon([box(0, 0, 40, 2), box(60, 0, 100, 2)])
        for angle in (0, 45, 90):
            candidate = {'id': 'a', 'geometry': mapping(rotate(g, angle, origin=(0, 0))), 'fill_color': [.5, .5, .5]}
            gaps = discontinuities(candidate, .1)
            self.assertEqual(len(gaps), 1)
            self.assertAlmostEqual(gaps[0]['nominal_gap_width_m'], 2)
            self.assertIsNone(gaps[0]['opening_type'])
            self.assertFalse(gaps[0]['geometry_bridge_added'])
            self.assertEqual(gaps[0]['world_geometry_additions'], 0)

    def test_nonparallel_or_offset_fill_parts_do_not_become_openings(self):
        for g in (MultiPolygon([box(0, 0, 40, 2), box(60, 10, 62, 50)]),
                  MultiPolygon([box(0, 0, 40, 2), box(60, 5, 100, 7)])):
            self.assertEqual(discontinuities({'id': 'a', 'geometry': mapping(g), 'fill_color': [.5, .5, .5]}, .1), [])

    def test_background_mask_is_not_an_opening_candidate(self):
        candidate = {'id': 'a', 'geometry': mapping(MultiPolygon([box(0, 0, 40, 2), box(60, 0, 100, 2)])), 'fill_color': [1, 1, 1]}
        self.assertEqual(discontinuities(candidate, .1), [])

    def test_triangle_clip_recovers_actual_fill_instead_of_bounding_rectangle(self):
        with pymupdf.open() as doc:
            page = page_with_content(doc, 'q 20 20 m 120 20 l 20 120 l h W n .5 g 0 0 200 200 re f Q')
            receipt = recover(page, 'source', 1)
            self.assertEqual(len(receipt['candidates']), 1)
            candidate = receipt['candidates'][0]
            self.assertEqual(shape(candidate['geometry']).area, 5000)
            self.assertEqual(len(candidate['clip_references']), 1)
            self.assertFalse(candidate['later_overpaint_visibility_verified'])
            self.assertFalse(candidate['accepted_feature'])

    def test_even_odd_clip_preserves_real_opening(self):
        with pymupdf.open() as doc:
            page = page_with_content(doc, 'q 10 10 200 200 re 70 70 80 80 re W* n .5 g 0 0 300 300 re f Q')
            candidate = recover(page, 'source', 1)['candidates'][0]
            g = shape(candidate['geometry'])
            self.assertEqual(g.area, 33600)
            self.assertEqual(len(g.interiors), 1)
            self.assertFalse(g.contains(Point(100, 200)))
            self.assertTrue(candidate['clip_references'][0]['even_odd'])

    def test_nested_clips_intersect_and_restored_scope_does_not_leak(self):
        with pymupdf.open() as doc:
            content = 'q 10 10 100 100 re W n q 60 60 100 100 re W n .5 g 0 0 300 300 re f Q Q .7 g 200 200 20 20 re f'
            candidates = recover(page_with_content(doc, content), 'source', 1)['candidates']
            self.assertEqual([shape(c['geometry']).area for c in candidates], [2500, 400])
            self.assertEqual([len(c['clip_references']) for c in candidates], [2, 0])

    def test_disjoint_clip_parts_keep_open_gap(self):
        with pymupdf.open() as doc:
            content = 'q 10 10 40 10 re 70 10 40 10 re W n .5 g 0 0 300 300 re f Q'
            candidate = recover(page_with_content(doc, content), 'source', 1)['candidates'][0]
            self.assertEqual(candidate['polygon_parts'], 2)
            self.assertEqual(shape(candidate['geometry']).area, 800)
            self.assertFalse(shape(candidate['geometry']).contains(Point(60, 285)))

    def test_curved_clip_is_withheld_and_next_unclipped_fill_survives(self):
        with pymupdf.open() as doc:
            content = 'q 10 10 m 10 100 100 100 100 10 c h W n .5 g 0 0 200 200 re f Q .7 g 200 200 20 20 re f'
            receipt = recover(page_with_content(doc, content), 'source', 1)
            self.assertEqual(receipt['counts']['unsupported_clip_or_compositing_scope'], 1)
            self.assertEqual(len(receipt['candidates']), 1)
            self.assertEqual(receipt['candidates'][0]['area_pdf_points_squared'], 400)

    def test_rotation_changes_no_native_geometry(self):
        with pymupdf.open() as doc:
            page = page_with_content(doc, 'q 20 20 m 120 20 l 20 120 l h W n .5 g 0 0 200 200 re f Q')
            original = recover(page, 'source', 1)
            page.set_rotation(90)
            self.assertEqual(original, recover(page, 'source', 1))


if __name__ == '__main__':
    unittest.main()
