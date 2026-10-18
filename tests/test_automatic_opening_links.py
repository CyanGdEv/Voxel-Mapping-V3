import copy
import unittest
from unittest.mock import patch

import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import box, mapping, shape

from voxel_mapper import automatic_opening_links as links
from voxel_mapper import clipped_plan_fills, fill_endcaps
from voxel_mapper.drawing_view_components import inspect_view
from voxel_mapper.reconstruction_evidence_queue import digest


class AutomaticOpeningLinkTests(unittest.TestCase):
    def view(self, identifier='plan', kind='plan', state='unspecified'):
        return {'id': identifier, 'document_sha256': 'a'*64, 'page': 1,
                'geometry': mapping(box(0, 0, 200, 200)), 'caption_text': identifier,
                'printed_claim': {'view_kind': kind, 'printed_state': state},
                'nominal_metres_per_pdf_point': .03,
                'native_to_nominal_local_affine': [.03, 0, 0, .03, 0, 0],
                'caption_evidence': {'reading_direction_pdf_native': [1, 0]}}

    def page(self, document):
        page = document.new_page(width=200, height=200)
        for rect in [(20, 80, 80, 90), (110, 80, 180, 90)]:
            page.draw_rect(rect, color=None, fill=(.5, .5, .5))
        return page

    def inventories(self):
        plan = {'view_id': 'p', 'printed_claim': {'view_kind': 'plan', 'printed_state': 'unspecified'},
                'plan_gap_review': {'status': 'whole_view_source_endcap_gaps_only', 'gaps': [
                    {'id': 'gap', 'nominal_gap_width_m': .9, 'source_fill_overlap_present': True}]}}
        elevation = {'view_id': 'e', 'printed_claim': {'view_kind': 'elevation', 'printed_state': 'unspecified'},
                     'plan_gap_review': {'gaps': []}, 'nominal_metres_per_pdf_point': .03,
                     'raster_coordinate_receipt': {'pixel_edge_to_pdf_native_matrix': [1, 0, 0, -1, 0, 200]},
                     'residual_raster_scan': {'status': 'indexed_jamb_head_correspondence_candidates_only',
                        'index': {'consensus_families': [{'bounds_pixels': [10, 20, x, 80]} for x in (40, 45, 70)]}},
                     'residual_raster_hypotheses': [
                         {'id': 'f'+str(i), 'consensus_family_index': i, 'status': 'residual_jamb_head_context_candidate'}
                         for i in range(3)]}
        return [plan, elevation]

    def test_original_fills_endcaps_and_overlap_are_retained_without_traces(self):
        with pymupdf.open() as doc:
            page = self.page(doc)
            page.draw_rect((85, 78, 105, 92), color=None, fill=(1, 1, 1))
            view = self.view(); result = links.plan_gaps(page, view)
            self.assertEqual(len(result['gaps']), 1)
            self.assertAlmostEqual(result['gaps'][0]['nominal_gap_width_m'], .9)
            self.assertTrue(result['gaps'][0]['source_fill_overlap_present'])
            self.assertEqual(result['page_fill_recovery'], clipped_plan_fills.recover(page, 'a'*64, 1))
            original = fill_endcaps.recover(result['page_fill_recovery']['candidates'], .03)
            self.assertEqual(result['page_endcap_recovery'], original)
            source = original['gaps'][0]; gap = result['gaps'][0]
            matrix = pymupdf.Matrix(result['unrotated_mupdf_to_pdf_native_matrix'])
            self.assertTrue(shape(gap['geometry_pdf_native']).equals_exact(
                affine_transform(shape(source['gap_corridor_geometry']), links.affine(matrix)), 0))
            self.assertEqual(gap['source_gap_sha256'], digest(source))
            self.assertFalse(gap['physical_opening_verified']); self.assertIsNone(gap['opening_type'])
            page.set_rotation(90)
            self.assertEqual(links.plan_gaps(page, view), result)
            self.assertEqual(page.rotation, 90)

    def test_view_scope_withholds_whole_crossing_parent_and_never_clips(self):
        with pymupdf.open() as doc:
            page = self.page(doc); view = self.view(); view['geometry'] = mapping(box(50, 0, 200, 200))
            result = links.plan_gaps(page, view)
            self.assertEqual(result['gaps'], [])
            self.assertEqual(len(result['withheld_scope_gap_ids']), 1)
            self.assertEqual(len(result['page_endcap_recovery']['gaps']), 1)
            self.assertEqual(len(result['page_fill_recovery']['candidates']), 2)

    def test_plan_recipe_budgets_and_missing_inputs_are_explicit(self):
        with pymupdf.open() as doc:
            page = self.page(doc); view = self.view()
            with patch.object(fill_endcaps, 'recover', side_effect=ValueError('Endcap comparison budget exceeded')):
                result = links.plan_gaps(page, view)
            self.assertEqual(result['status'], 'plan_gap_budget_withheld'); self.assertIsNone(result['page_fill_recovery'])
            self.assertEqual(result['gaps'], [])
            self.assertEqual(links.plan_gaps(page, view, max_checks=1)['status'], 'plan_gap_budget_withheld')
            view['nominal_metres_per_pdf_point'] = None
            self.assertEqual(links.plan_gaps(page, view)['status'], 'nominal_view_scale_required')
            self.assertEqual(links.plan_gaps(None, self.view())['status'], 'original_source_page_required')
            view = self.view(); view['printed_claim']['plan_level_or_form'] = 'roof'
            self.assertEqual(links.plan_gaps(page, view)['status'], 'not_a_floor_plan')
            view = self.view(); view['page'] = 2
            with self.assertRaises(ValueError): links.plan_gaps(page, view)

    def test_all_width_alternatives_and_unmatched_families_remain_explicit(self):
        source = self.inventories(); before = copy.deepcopy(source); result = links.compare(source)
        self.assertEqual(source, before); self.assertEqual(len(result['matches']), 2)
        self.assertEqual(result['counts']['scoped_residual_families'], 3)
        self.assertEqual(result['counts']['linked_residual_families'], 2)
        self.assertEqual(result['plan_gaps'][0]['status'], 'multiple_nominal_width_alternatives')
        for match in result['matches']:
            self.assertTrue(match['source_fill_overlap_present']); self.assertTrue(match['construction_state_unresolved'])
            self.assertFalse(match['physical_correspondence_verified']); self.assertFalse(match['position_alignment_verified'])
        self.assertFalse(result['building_identity_verified'])
        # Ordering the input views differently must not pick a different alternative.
        self.assertEqual(result, links.compare(list(reversed(source))))

    def test_scales_apply_to_pixel_edges_without_bounding_native_rotations(self):
        source = self.inventories(); elevation = source[1]
        elevation['raster_coordinate_receipt']['pixel_edge_to_pdf_native_matrix'] = [0, 2, 2, 0, 50, 70]
        elevation['nominal_metres_per_pdf_point'] = .015
        result = links.compare(source)
        self.assertAlmostEqual(result['matches'][0]['elevation_nominal_width_m'], .9)
        self.assertEqual(len(result['matches']), 2)

    def test_explicit_state_conflicts_do_not_inherit_or_cross_match(self):
        source = self.inventories(); source[0]['printed_claim']['printed_state'] = 'existing'
        source[1]['printed_claim']['printed_state'] = 'proposed'
        result = links.compare(source)
        self.assertEqual(result['matches'], [])
        self.assertEqual(result['plan_gaps'][0]['explicit_state_conflict_view_ids'], ['e'])
        source[1]['printed_claim']['printed_state'] = 'existing'
        result = links.compare(source)
        self.assertEqual(len(result['matches']), 2)
        self.assertTrue(all(not m['construction_state_unresolved'] for m in result['matches']))
        self.assertFalse(result['view_association_verified'])

    def test_pair_exhaustion_discards_all_partial_links_even_after_first_match(self):
        result = links.compare(self.inventories(), max_checks=1)
        self.assertEqual(result['status'], 'opening_link_budget_withheld')
        self.assertEqual(result['matches'], []); self.assertEqual(result['plan_gaps'], [])
        self.assertNotIn('counts', result)
        source = self.inventories(); source[0]['plan_gap_review']['gaps'] *= 4001
        with self.assertRaises(ValueError): links.compare(source)
        source[0]['plan_gap_review']['gaps'] = [
            {'id': str(i), 'nominal_gap_width_m': .9, 'source_fill_overlap_present': False} for i in range(4001)]
        self.assertEqual(links.compare(source)['reason'], 'source_inventory_budget')
        for value in (0, True, 100001):
            with self.assertRaises(ValueError): links.compare([], max_checks=value)
            with self.assertRaises(ValueError): fill_endcaps.recover([], .03, max_checks=value)

    def test_missing_scale_withheld_scans_and_scope_crossings_stay_out_of_links(self):
        source = self.inventories(); source[1]['nominal_metres_per_pdf_point'] = None
        self.assertEqual(links.compare(source)['matches'], [])
        source = self.inventories(); source[1]['residual_raster_scan']['index'] = None
        self.assertEqual(links.compare(source)['elevation_views'][0]['status'], 'source_scan_withheld')
        source = self.inventories(); source[1]['residual_raster_hypotheses'][0]['status'] = 'candidate_scope_crossing_withheld'
        self.assertEqual(len(links.compare(source)['matches']), 1)
        source[0]['plan_gap_review']['gaps'][0]['nominal_gap_width_m'] = 10
        self.assertEqual(links.compare(source)['plan_gaps'][0]['status'], 'no_retained_nominal_width_match')

    def test_inspect_view_automatically_recovers_source_plan_gaps(self):
        with pymupdf.open() as doc:
            page = self.page(doc)
            result = inspect_view(self.view(), [], None, [1, 0, 0, -1, 0, 200], source_page=page)
        self.assertEqual(result['counts']['source_plan_gaps'], 1)
        self.assertEqual(result['plan_gap_review']['status'], 'whole_view_source_endcap_gaps_only')
        self.assertEqual(result['accepted_physical_components'], 0)


if __name__ == '__main__': unittest.main()
