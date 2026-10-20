import copy
import json
import unittest
from unittest.mock import patch

import numpy as np
import pymupdf
from shapely.geometry import Polygon, MultiPolygon, box, mapping, shape

from voxel_mapper import automatic_facade_alignment as alignment
from voxel_mapper.automatic_elevation_context import family_review
from voxel_mapper.clipped_plan_fills import recover
from voxel_mapper.raster_opening_scan import scan
from voxel_mapper.reconstruction_evidence_queue import digest


class FacadeAlignmentTests(unittest.TestCase):
    def fixture(self):
        pixels = np.full((180, 260), 255, dtype=np.uint8)
        for left, top, right, bottom in [(20, 20, 220, 150), (60, 80, 90, 150)]:
            pixels[top:bottom, left:left+2] = 40; pixels[top:bottom, right:right+2] = 40
            pixels[top:top+2, left:right+2] = 40
        found = scan(pixels, representation='indexed')
        self.assertEqual([f['bounds_pixels'] for f in found['index']['consensus_families']],
                         [[22, 20, 220, 150], [62, 80, 90, 150]])
        geometry = Polygon([(0,0), (198,0), (198,90), (0,90)],
                           holes=[[(20,20), (20,30), (30,30), (30,20)]])
        enclosure = {'id': 'enclosure', 'geometry_pdf_native': mapping(geometry)}
        fill = {'id': 'paint', 'fill_color': [.5,.5,.5],
                'geometry': mapping(MultiPolygon([box(0,0,90,1), box(110,0,198,1)]))}
        plan = {'view_id': 'p', 'nominal_metres_per_pdf_point': .05,
            'building_scope_review': {'labels': [{'id': 'label', 'candidates': [enclosure]}]},
            'plan_gap_review': {'unrotated_mupdf_to_pdf_native_matrix': [1,0,0,1,0,0],
                                'page_fill_recovery': {'candidates': [fill]}}}
        elevation = {'view_id': 'e', 'nominal_metres_per_pdf_point': .05, 'residual_raster_scan': found}
        sources = [{'views': [{'id': key, 'geometry': mapping(box(0,0,260,180))} for key in ('p', 'e')]}]
        for view in sources[0]['views']:
            (plan if view['id']=='p' else elevation)['source_view_sha256'] = digest(view)
        inventories = [plan, elevation]; pins = {v['view_id']: digest(v) for v in inventories}
        frame = {'id': 'frame', 'diagnostic_axis': [1,0], 'projection_min_m': 0,
                 'source_native_endpoints': [[0,0], [198,0]], 'ray_hits_pdf_native': [[80,0]]}
        record = {'id': 'record', 'plan_view_id': 'p', 'label_id': 'label', 'enclosure_id': 'enclosure',
                  'target_elevation_view_ids': ['e'], 'frame_review': {'frames': [frame]}}
        projection = {'id': 'projection', 'facade_record_id': 'record', 'frame_id': 'frame',
                      'nominal_plan_position_interval_m': [2,3.4]}
        buildings = {'status': 'numbered_source_facade_candidates_only', 'source_inventory_sha256': pins,
                     'frames': [record], 'projected_gaps': [projection]}
        families = []
        for index in (0, 1):
            family = family_review(elevation, index, {'datum_y_display_points': 130},
                                   [1,0,0,1,0,0], lambda: None)
            family.update(residual_family_id='family-'+str(index), candidate_scope_status='residual_jamb_head_context_candidate')
            families.append(family)
        levels = {'status': 'source_relative_elevation_context_only', 'source_inventory_sha256': pins,
            'source_building_links_sha256': digest(buildings),
            'views': [{'view_id': 'e', 'status': 'all_original_residual_families_reviewed_against_source_level',
                       'pixel_edge_to_source_display_matrix': [1,0,0,1,0,0], 'families': families}],
            'level_supported_width_links': [{'projection_id': 'projection', 'elevation_view_id': 'e',
                                             'residual_family_id': 'family-1'}]}
        return sources, inventories, buildings, levels

    def rebind(self, sources, inventories, buildings, levels):
        for view in sources[0]['views']:
            next(v for v in inventories if v['view_id']==view['id'])['source_view_sha256'] = digest(view)
        pins = {v['view_id']: digest(v) for v in inventories}
        buildings['source_inventory_sha256'] = pins; levels['source_inventory_sha256'] = pins
        levels['source_building_links_sha256'] = digest(buildings)

    def test_independent_extents_anchor_positions_without_fitting_or_changing_source(self):
        args = self.fixture(); before = copy.deepcopy(args); result = alignment.run(*args)
        self.assertEqual(args, before)
        self.assertEqual(result['counts']['parent_child_relations'], 1)
        self.assertEqual(result['counts']['all_witness_extent_widths_compatible'], 2)
        self.assertEqual(result['counts']['all_witness_positions_compatible'], 2)
        self.assertEqual(result['counts']['independent_origin_position_mismatch'], 2)
        review = result['frames'][0]['frame_reviews'][0]
        self.assertEqual({e['source_kind'] for e in review['plan_extents']}, {'named_enclosure', 'near_ray_original_paint'})
        self.assertEqual([e['source_hole_count'] for e in review['plan_extents']], [1, 0])
        self.assertEqual([e['source_part_count'] for e in review['plan_extents']], [1, 2])
        self.assertTrue(all(not e['span_establishes_continuity'] for e in review['plan_extents']))
        for comparison in review['position_comparisons']:
            self.assertFalse(comparison['origin_fit_to_opening']); self.assertFalse(comparison['scale_correction_applied'])
            self.assertFalse(comparison['position_alignment_verified'])
            self.assertEqual(len(comparison['witnesses']), 4)
        self.assertFalse(result['physical_opening_verified']); self.assertEqual(result['world_geometry_additions'], 0)

    def test_both_parities_are_retained_and_position_disagreement_cannot_move_the_origin(self):
        args = self.fixture(); sources, inventories, buildings, levels = args
        buildings['projected_gaps'][0]['nominal_plan_position_interval_m'] = [6.5,7.9]
        self.rebind(*args); result = alignment.run(*args)
        positions = result['frames'][0]['frame_reviews'][0]['position_comparisons']
        self.assertTrue(all(p['elevation_x_reversed'] for p in positions if p['status']=='all_witness_positions_compatible'))
        buildings['projected_gaps'][0]['nominal_plan_position_interval_m'] = [4,5.4]
        self.rebind(*args); result = alignment.run(*args)
        self.assertEqual(result['counts']['independent_origin_position_mismatch'], 4)
        self.assertNotIn('all_witness_positions_compatible', result['counts'])

    def test_width_mismatch_prevents_position_fit_even_when_an_opening_width_matches(self):
        args = self.fixture(); args[1][0]['nominal_metres_per_pdf_point'] = .04
        self.rebind(*args); result = alignment.run(*args)
        self.assertEqual(result['counts']['independent_extent_width_mismatch'], 2)
        self.assertEqual(result['counts']['position_comparisons'], 0)
        for row in result['frames'][0]['frame_reviews'][0]['extent_comparisons']:
            self.assertAlmostEqual(row['witnesses'][0]['diagnostic_elevation_to_plan_width_ratio'], 1.25)
            self.assertFalse(row['scale_correction_applied'])

    def test_all_parent_and_child_witnesses_must_surround_with_distinct_jambs(self):
        args = self.fixture(); parent, child = args[3]['views'][0]['families']
        self.assertTrue(alignment.surrounds(parent, child, lambda: None))
        altered = copy.deepcopy(parent); altered['witnesses'][1]['source_bounds_pixels'][0] = 63
        self.assertFalse(alignment.surrounds(altered, child, lambda: None))
        altered = copy.deepcopy(parent)
        altered['witnesses'][1]['jamb_group_indices'][0] = child['witnesses'][1]['jamb_group_indices'][0]
        self.assertFalse(alignment.surrounds(altered, child, lambda: None))
        self.assertFalse(alignment.surrounds(child, child, lambda: None))

    def test_threshold_disagreement_is_explicit_in_extent_and_position_reviews(self):
        args = self.fixture(); parent, child = copy.deepcopy(args[3]['views'][0]['families'])
        extent = {'id': 'extent', 'nominal_plan_position_interval_m': [0,9.9]}
        parent['witnesses'][1]['source_bounds_pixels'][2] = 230
        result = alignment.compare_extent(extent, parent, [1,0,0,1,0,0], .05, lambda: None)
        self.assertEqual(result['status'], 'extent_width_witnesses_disagree')
        parent['witnesses'][1]['source_bounds_pixels'][0] = 30
        result = alignment.compare_position(extent, parent, child, args[2]['projected_gaps'][0],
                                            [1,0,0,1,0,0], .05, False, lambda: None)
        self.assertEqual(result['status'], 'position_witnesses_disagree')
        self.assertEqual({w['source_child_bounds_pixels'][3] for w in result['witnesses']}, {150})

    def test_crossing_paint_is_withheld_whole_and_exact_source_extrema_are_retained(self):
        args = self.fixture(); sources, inventories, buildings, levels = args
        sources[0]['views'][0]['geometry'] = mapping(box(0,0,150,180))
        self.rebind(*args); result = alignment.run(*args); review = result['frames'][0]['frame_reviews'][0]
        self.assertEqual(len(review['plan_extents']), 1)
        self.assertEqual(review['withheld_plan_paints'][0]['status'], 'whole_source_paint_crosses_plan_view')
        extent = review['plan_extents'][0]
        self.assertEqual(extent['nominal_plan_position_interval_m'], [0,9.9])
        self.assertEqual(extent['source_extreme_vertices'][1]['point_pdf_native'][0], 198)

    def test_original_pdf_paints_keep_holes_parts_and_provenance(self):
        args = self.fixture(); sources, inventories, buildings, levels = args
        with pymupdf.open() as document:
            page = document.new_page(width=260,height=180)
            drawing = page.new_shape(); drawing.draw_rect((0,0,198,90)); drawing.draw_rect((20,20,30,30))
            drawing.finish(color=None, fill=(.5,.5,.5), even_odd=True); drawing.commit()
            fills = recover(page, 'a'*64, 1)['candidates']
            inventories[0]['plan_gap_review']['page_fill_recovery']['candidates'] = fills
            self.rebind(*args); result = alignment.run(*args)
        paints = [e for e in result['frames'][0]['frame_reviews'][0]['plan_extents'] if e['source_kind']=='near_ray_original_paint']
        self.assertEqual(len(paints), 1); self.assertEqual(paints[0]['source_hole_count'], 1)
        self.assertEqual(paints[0]['source_record_sha256'], digest(fills[0]))
        self.assertTrue(shape(paints[0]['geometry_pdf_native']).equals_exact(shape(fills[0]['geometry']), 0))

    def test_budget_exhaustion_discards_early_and_late_partial_reviews(self):
        args = self.fixture(); result = alignment.run(*args, max_checks=1)
        self.assertEqual(result['status'], 'facade_alignment_budget_withheld'); self.assertEqual(result['frames'], [])
        original = alignment.compare_position; calls = []
        def late_hold(*args):
            calls.append(1)
            if len(calls)==2: raise OverflowError('facade_alignment_work_budget')
            return original(*args)
        with patch.object(alignment, 'compare_position', side_effect=late_hold): result = alignment.run(*args)
        self.assertEqual(len(calls), 2); self.assertEqual(result['frames'], []); self.assertEqual(result['counts'], {})

    def test_missing_ambiguous_and_inside_views_preserve_holds(self):
        for targets in ([], ['e','other']):
            args = self.fixture(); args[2]['frames'][0]['target_elevation_view_ids'] = targets; self.rebind(*args)
            self.assertEqual(alignment.run(*args)['frames'][0]['status'], 'single_numbered_elevation_target_required')
        args = self.fixture(); args[2]['frames'][0]['frame_review'] = {'frames': [], 'status': 'withheld_marker_inside_enclosure'}
        self.rebind(*args)
        self.assertEqual(alignment.run(*args)['frames'][0]['status'], 'withheld_marker_inside_enclosure')
        args = self.fixture(); args[3]['status'] = 'elevation_context_budget_withheld'
        self.assertEqual(alignment.run(*args)['status'], 'source_facade_and_level_context_required')
        args = self.fixture(); args[3]['views'][0]['families'][0]['candidate_scope_status'] = 'candidate_scope_crossing_withheld'
        self.assertEqual(alignment.run(*args)['counts']['parent_child_relations'], 0)

    def test_stale_duplicate_and_nonfinite_inputs_are_rejected(self):
        args = self.fixture(); args[1][0]['nominal_metres_per_pdf_point'] = .06
        with self.assertRaisesRegex(ValueError, 'Matching source inventory'): alignment.run(*args)
        args = self.fixture(); args[0][0]['views'].append(copy.deepcopy(args[0][0]['views'][0]))
        with self.assertRaisesRegex(ValueError, 'Matching automatic source views'): alignment.run(*args)
        args = self.fixture(); args[1].append(copy.deepcopy(args[1][0]))
        with self.assertRaisesRegex(ValueError, 'Bounded unique'): alignment.run(*args)
        for value in (0, True, 100001):
            with self.assertRaises(ValueError): alignment.run(*self.fixture(), max_checks=value)
        args = self.fixture(); args[3]['views'][0]['pixel_edge_to_source_display_matrix'][0] = float('nan')
        with self.assertRaisesRegex(ValueError, 'Positive aligned'): alignment.run(*args)

    def test_independent_audit_checks_conditional_positions_and_every_source_witness(self):
        from collections import Counter
        from scripts.audit_drawing_view_components import verify_facade_alignment
        args = self.fixture(); result = json.loads(json.dumps(alignment.run(*args))); checked = Counter()
        verify_facade_alignment(*args, result, checked, 100000)
        self.assertEqual(checked['independent_plan_extent_vertex_proofs'], 4)
        self.assertEqual(checked['independent_extent_threshold_widths'], 4)
        self.assertEqual(checked['independent_origin_position_witnesses'], 16)


if __name__ == '__main__': unittest.main()
