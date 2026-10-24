from concurrent.futures import CancelledError
import hashlib
import json
import unittest
from unittest.mock import patch

import pymupdf

from voxel_mapper import planning_section_cuts as cuts
from voxel_mapper.building_spec import digest
from voxel_mapper.drawing_page_tools import native_inverse


def fixture(*, vertical=False, rectangle=False, rotation=0, hidden=False,
            key='A', other_key=None, enclosed=True, gap=0, split=False, covered=False, two=False):
    document = pymupdf.open()
    page = document.new_page(width=500, height=400)
    centers = [(70, 70), (70, 250)] if vertical else [(70, 100), (330, 100)]
    for i, (x, y) in enumerate(centers):
        if enclosed:
            if rectangle:
                page.draw_rect((x-16, y-16, x+16, y+16))
            else:
                page.draw_circle((x, y), 16)
        page.insert_text((x-3, y+3), key if i == 0 or other_key is None else other_key, fontsize=8)
    start, end = ((70, 86+gap), (70, 234)) if vertical else ((86+gap, 100), (314, 100))
    if split:
        mid = tuple((a+b)/2 for a, b in zip(start, end))
        page.draw_line(start, mid); page.draw_line(mid, end)
    else:
        page.draw_line(start, end)
    if hidden:
        x, y = centers[0]
        page.draw_rect((x-5, y-7, x+8, y+6), fill=(1, 1, 1), color=None)
    if covered:
        page.draw_rect((150, 95, 200, 105), fill=(1, 1, 1), color=None)
    if two:
        for x in (70, 330):
            page.draw_circle((x, 200), 16)
            page.insert_text((x-3, 203), key, fontsize=8)
        page.draw_line((86, 200), (314, 200))
    page.set_rotation(rotation)
    return document, page


def recover(page, **kwargs):
    return cuts.page_evidence(page, hashlib.sha256(page.parent.tobytes()).hexdigest(), page.number+1, **kwargs)


class SectionCutTests(unittest.TestCase):
    def source(self, **kwargs):
        document, page = fixture(**kwargs)
        self.addCleanup(document.close)
        return page

    def test_horizontal_original_connector_between_visible_circle_labels(self):
        page = self.source()
        result = recover(page)
        self.assertTrue(result['analysis_complete'])
        self.assertEqual(len(result['cuts']), 1)
        cut = result['cuts'][0]
        self.assertEqual(cut['section_key_candidate'], 'A-A')
        source = page.get_drawings(extended=True)[cut['source_line']['source_path_index']]
        expected = [list(p*native_inverse(page)) for p in source['items'][0][1:]]
        self.assertEqual(cut['endpoints_pdf_native'], expected)
        self.assertFalse(cut['endpoints_snapped'])
        self.assertFalse(cut['cut_direction_verified'])
        self.assertFalse(cut['physical_component_correspondence_verified'])
        self.assertFalse(result['physical_height_verified'])
        self.assertEqual(result['local_3d_components'], 0)
        self.assertEqual(result['world_geometry_additions'], 0)
        self.assertEqual(result['id'], digest({k: v for k, v in result.items() if k != 'id'}))

    def test_vertical_rectangular_and_rotated_original_marker_topologies(self):
        for kwargs in ({'vertical': True}, {'rectangle': True}, {'rotation': 90}, {'rotation': 270}, {'key': 'A-A'}):
            with self.subTest(kwargs=kwargs):
                page = self.source(**kwargs)
                result = recover(page)
                self.assertEqual(len(result['cuts']), 1)
                self.assertEqual(page.rotation, kwargs.get('rotation', 0))

    def test_numbers_wrong_letters_and_unenclosed_labels_do_not_identify_a_section(self):
        for kwargs in ({'key': '1'}, {'other_key': 'B'}, {'enclosed': False}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(recover(self.source(**kwargs))['cuts'], [])

    def test_hidden_letter_or_later_filled_paint_over_connector_withholds_cut(self):
        for kwargs in ({'hidden': True}, {'covered': True}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(recover(self.source(**kwargs))['cuts'], [])

    def test_disconnected_or_split_connector_is_not_repaired(self):
        for kwargs in ({'gap': .125}, {'split': True}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(recover(self.source(**kwargs))['cuts'], [])

    def test_two_same_label_connector_hypotheses_are_retained_without_selection(self):
        result = recover(self.source(two=True))
        self.assertEqual(len(result['cuts']), 2)
        self.assertTrue(all(row['section_key_candidate'] == 'A-A' for row in result['cuts']))
        self.assertEqual(len({row['source_line']['source_path_index'] for row in result['cuts']}), 2)

    def test_nested_marker_enclosures_do_not_select_smallest(self):
        page = self.source()
        page.draw_circle((70, 100), 20)
        result = recover(page)
        self.assertEqual(result['cuts'], [])
        self.assertTrue(any(row['status'] == 'withheld_ambiguous_or_hidden_marker_label' for row in result['markers']))

    def test_intermediate_labelled_marker_is_not_skipped_by_longer_connector(self):
        page = self.source()
        page.draw_circle((200, 100), 16)
        page.insert_text((197, 103), 'B', fontsize=8)
        result = recover(page)
        self.assertEqual(result['cuts'], [])
        self.assertEqual(result['source_scope_holds']['intermediate_labelled_source_marker'], 1)

    def test_line_crossing_its_endpoint_marker_interior_is_not_an_outward_connector(self):
        document = pymupdf.open()
        self.addCleanup(document.close)
        page = document.new_page(width=500, height=400)
        for x in (70, 330):
            page.draw_circle((x, 100), 16)
            page.insert_text((x-3, 94), 'A', fontsize=5)
        page.draw_line((54, 100), (314, 100))
        result = recover(page)
        self.assertEqual(result['cuts'], [])
        self.assertEqual(result['source_scope_holds']['connector_crosses_own_marker_enclosure'], 1)

    def test_units_and_cropped_pages_withhold_all_results(self):
        for case in ('unit', 'crop'):
            with self.subTest(case=case):
                page = self.source()
                if case == 'unit':
                    page.parent.xref_set_key(page.xref, 'UserUnit', '2')
                else:
                    page.set_cropbox((0, 0, 490, 390))
                result = recover(page)
                self.assertFalse(result['analysis_complete'])
                self.assertEqual(result['cuts'], [])

    def test_count_work_path_label_and_output_budgets_clear_partial_cuts(self):
        page = self.source(two=True)
        for options in ({'max_checks': 1}, {'max_paths': 1}, {'max_labels': 1},
                        {'max_markers': 1}, {'max_cuts': 1}):
            with self.subTest(options=options):
                result = recover(page, options=options)
                self.assertFalse(result['analysis_complete'])
                self.assertEqual(result['cuts'], [])
                self.assertEqual(result['markers'], [])
        with patch.object(cuts.glyph_visibility, 'screen_architectural_span',
                return_value={'status': 'raster_consistent_candidate', 'large_receipt': 'x'*20000}):
            result = recover(page, options={'max_output_bytes': 16384})
            self.assertFalse(result['analysis_complete'])
            self.assertEqual(result['cuts'], [])
            self.assertEqual(result['markers'], [])

    def test_invalid_source_or_raised_limits_rejected_and_cancellation_propagates(self):
        page = self.source()
        for options in ({'max_checks': True}, {'max_cuts': 129}, {'max_output_bytes': 16383}, {'unknown': 1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                recover(page, options=options)
        for sha, number in (('x'*64, 1), ('f'*64, 2), ('f'*64, True)):
            with self.assertRaises(ValueError):
                cuts.page_evidence(page, sha, number)
        with self.assertRaises(CancelledError):
            recover(page, cancelled=lambda: True)

    def test_round_trip_receipt_is_self_hashed(self):
        result = recover(self.source())
        round_trip = json.loads(json.dumps(result))
        self.assertEqual(result['id'], digest({k: v for k, v in round_trip.items() if k != 'id'}))


if __name__ == '__main__':
    unittest.main()
