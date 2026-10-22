import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pymupdf

from voxel_mapper import split_level_labels as split
from voxel_mapper import preshow_roof_patches as patches
from voxel_mapper import preshow_level_geometry as geometry
from voxel_mapper import roof_reference_evidence as reference
from tests import test_roof_reference_evidence as parent_tests
from tests import test_roof_source_topology as topology_tests
from voxel_mapper.roof_source_topology import connected_candidates


class PreshowLevelTests(unittest.TestCase):
    def drawing(self, duplicate='183300', second=True):
        doc = pymupdf.open(); page = doc.new_page(width=500, height=500)
        def marker(y):
            page.draw_circle((400, y), 10)
            page.draw_rect((400, y, 410, y+10), fill=(0,0,0), color=None)
            page.draw_rect((390, y-10, 400, y), fill=(0,0,0), color=None)
            page.draw_line((350, y), (390, y))
        def right(text, y, size=10):
            width = pymupdf.get_text_length(text, fontsize=size)
            page.insert_text((380-width, y), text, fontsize=size)
        marker(200); right('Preshow Top Level', 180); right('+183.30', 193)
        if duplicate: right(duplicate, 216, 7)
        if second: marker(306); right('Undercroft Level +178.000', 299)
        views = [{'view_key_candidate': ['demo', 30, 8], 'display_bounds': [0,0,500,500],
            'nominal_metres_per_pdf_point_candidate': .05}]
        return doc, views

    def fixture(self, root):
        args = parent_tests.RoofReferenceTests().fixture(root); r = reference.build(*args)
        gradient = next(root.rglob('source-gradient-gables.json')).parent
        return Path(r['directory']), args[0], gradient, *args[1:-1], root/'level-geometry'

    def cap(self):
        inv = topology_tests.RoofSourceTopologyTests().inventory()
        topology = connected_candidates(inv, lambda: None)
        candidate = next(c for c in topology['candidates'] if c['ridge_source_id'] == 'r')
        return patches.source_cap_variants(topology, candidate)[0]

    def test_split_labels_bind_to_original_marker_and_match_relative_scale(self):
        doc, views = self.drawing()
        try:
            before = doc.tobytes(no_new_id=True); r = split.review(doc[0], 'a'*64, 1, views)
            self.assertEqual(len(r['split_pairs']), 1)
            self.assertEqual(r['split_pairs'][0]['numeric_duplicate_status'], 'consistent_assumed_mm_duplicate')
            self.assertEqual(len(r['marker_bindings']), 2)
            self.assertTrue(all(q['status'] == 'unverified_source_level_marker_binding' for q in r['marker_bindings']))
            self.assertEqual(r['relative_checks'][0]['status'], 'source_relative_level_scale_agrees')
            split_marker = next(q for q in r['marker_bindings'] if q['label']['split_pair_id'])
            self.assertEqual(split_marker['legacy_marker_status'], 'withheld_nonunique_level_label_line_or_view')
            self.assertFalse(split_marker['legacy_marker_record_changed'])
            self.assertFalse(split_marker['physical_floor_role_verified']); self.assertFalse(split_marker['vertical_datum_verified'])
            self.assertEqual(before, doc.tobytes(no_new_id=True))
        finally: doc.close()

    def test_conflicting_duplicate_and_hidden_original_fragment_keep_binding_held(self):
        doc, views = self.drawing(duplicate='183400')
        try:
            r = split.review(doc[0], 'a'*64, 1, views)
            self.assertEqual(r['split_pairs'][0]['numeric_duplicate_status'], 'conflicting_assumed_mm_duplicate')
            self.assertTrue(any(q['status'] == 'split_level_marker_source_check_held' for q in r['marker_bindings']))
        finally: doc.close()
        doc, views = self.drawing()
        try:
            with patch.object(split, 'screen_architectural_span', return_value={'status': 'withheld'}):
                r = split.review(doc[0], 'a'*64, 1, views)
            self.assertEqual(r['split_pairs'][0]['status'], 'split_level_label_source_check_held')
        finally: doc.close()

    def test_ambiguous_view_or_missing_datum_line_never_selects_nearest(self):
        doc, views = self.drawing(second=False)
        try:
            r = split.review(doc[0], 'a'*64, 1, views+copy.deepcopy(views))
            self.assertEqual(r['marker_bindings'][0]['status'], 'split_level_marker_source_check_held')
            paths = doc[0].get_drawings(extended=True)
            paths = [p for p in paths if not (len(p.get('items', [])) == 1 and p['items'][0][0] == 'l')]
            with patch.object(type(doc[0]), 'get_drawings', return_value=paths):
                r = split.review(doc[0], 'a'*64, 1, views)
            self.assertEqual(r['marker_bindings'][0]['status'], 'split_level_marker_source_check_held')
        finally: doc.close()

    def test_split_pairing_requires_style_reading_direction_and_aligned_following_line(self):
        doc, _ = self.drawing()
        try:
            source = split.fragments(doc[0], lambda: None)
            for key, value in [('font', 'other'), ('direction', [0.,1.]), ('font_size_points', 9.)]:
                changed = copy.deepcopy(source); changed['values'][0][key] = value
                self.assertEqual(split.pair_fragments(changed, lambda: None), [])
            changed = copy.deepcopy(source); changed['values'][0]['bbox_page_points'] = [0,0,20,10]
            self.assertEqual(split.pair_fragments(changed, lambda: None), [])
        finally: doc.close()

    def test_split_budget_failure_clears_every_partial_binding(self):
        doc, views = self.drawing()
        try:
            r = split.review(doc[0], 'a'*64, 1, views, max_checks=1)
            self.assertEqual(r['status'], 'split_source_level_budget_withheld')
            self.assertEqual(r['marker_bindings'], []); self.assertEqual(r['split_pairs'], [])
        finally: doc.close()

    def test_literal_ink_columns_recover_one_pixel_caps_and_preserve_all_pixels(self):
        gray = np.full((120,120), 255, np.uint8); gray[40:69,20] = 160; gray[40:69,21] = 230
        mask = np.zeros_like(gray, bool); before = gray.copy()
        first = patches.vertical_caps(gray, mask, 220, lambda: None)
        second = patches.vertical_caps(gray, mask, 235, lambda: None)
        self.assertEqual([c['x'] for c in first], [20]); self.assertEqual([c['x'] for c in second], [20,21])
        self.assertEqual(first[0]['source_y_interval_pixels'], [40,68])
        self.assertEqual(len(first[0]['source_pixels']), 29); self.assertFalse(first[0]['source_gaps_filled'])
        np.testing.assert_array_equal(gray, before)

    def test_cap_exclusions_large_gaps_and_long_filled_columns_are_not_repaired(self):
        gray = np.full((120,120), 255, np.uint8); gray[10:111,30:40] = 0; gray[40:69,20] = 0
        mask = np.zeros_like(gray, bool); mask[50:58,20] = True
        self.assertEqual(patches.vertical_caps(gray, mask, 220, lambda: None), [])
        with self.assertRaises(ValueError): patches.vertical_caps(gray, mask.astype('uint8'), 220, lambda: None)

    def test_exact_source_caps_keep_original_vertices_and_unmeshed_tails(self):
        cap = self.cap(); self.assertEqual(len(cap['source_vertices_pdf_native']), 6)
        self.assertEqual(cap['native_runs_m'], [5.,5.])
        self.assertTrue(all(t['nominal_source_tails_m'] == [0.,.5] for t in cap['source_rail_tails_left_unmeshed']))

    def test_corner_checks_retain_failures_and_mesh_keeps_separate_eave_heights(self):
        cap = self.cap(); pair = {'id': 'ridge', 'inferred_ridge_pixel': [60.,20.], 'left_pitch_degrees': 30., 'right_pitch_degrees': 30.}
        caps = [{'id': 'left', 'x': 10, 'source_y_interval_pixels': [49,75]},
            {'id': 'right', 'x': 110, 'source_y_interval_pixels': [48,75]},
            {'id': 'wrong', 'x': 10, 'source_y_interval_pixels': [10,30]}]
        checks = patches.endcap_checks(pair, caps, cap, .1, lambda: None)
        self.assertEqual({c['status'] for c in checks}, {'conditional_source_endcaps_agree', 'source_endcap_check_held'})
        check = next(c for c in checks if c['status'] == 'conditional_source_endcaps_agree')
        mesh = patches.patch_mesh(cap, pair, check, 100., .1)
        np.testing.assert_allclose(mesh['eave_endcap_heights_above_printed_level_nominal_m'], [5.1,5.2], atol=1e-12, rtol=0)
        self.assertEqual(len(mesh['triangles']), 4); self.assertFalse(mesh['complete_wing_mesh'])
        self.assertTrue(mesh['source_cap_patch_only']); self.assertFalse(mesh['source_plan_vertices_moved'])

    def test_inter_sheet_height_check_uses_printed_level_offset_and_keeps_taller_roof_held(self):
        context = {'id': 'context', 'candidate_id': 'candidate'}; binding = {'id': 'level', 'label': {'value_m_candidate': 183.30}}
        witness = {'candidate_id': 'candidate', 'source_pair_id': 'old', 'nominal_ridge_height_above_source_level_m': 5.89, 'printed_level_value_m_candidate': 182.50}
        pair = {'id': 'low', 'inferred_ridge_pixel': [10.,49.1]}
        result = geometry.height_checks(context, pair, binding, 100., .1, [witness], lambda: None)
        self.assertEqual(result[0]['status'], 'conditional_inter_sheet_ridge_height_agrees')
        self.assertTrue(result[0]['shared_printed_level_datum_assumed']); self.assertFalse(result[0]['independent_survey_check'])
        pair['inferred_ridge_pixel'][1] = 18.
        self.assertEqual(geometry.height_checks(context, pair, binding, 100., .1, [witness], lambda: None)[0]['status'], 'inter_sheet_ridge_height_held')

    def test_source_threshold_checks_preserve_disagreements_and_shared_source_warning(self):
        a = {'id': 'a', 'context_id': 'c', 'source_level_binding_id': 'l', 'source_cap_variant_id': 'v',
            'image_left_to_native_rail_orientation': 1, 'source_ink_threshold': 220,
            'source_ridge_pixel': [20.,20.], 'source_eave_top_pixels': [[10,30],[30,30]]}
        b = {**a, 'id': 'b', 'source_ink_threshold': 235}
        c = {**b, 'id': 'c', 'source_ridge_pixel': [20.,26.]}
        result = geometry.threshold_checks([a,b,c], lambda: None)
        self.assertEqual([c['status'] for c in result], ['source_threshold_patch_measurements_agree', 'source_threshold_patch_measurements_disagree'])

    def test_full_source_build_replays_without_promoting_missing_geometry(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.fixture(Path(temp)); r = geometry.build(*args)
            self.assertEqual(r, geometry.build(*args)); self.assertEqual(r, json.loads(json.dumps(r)))
            self.assertEqual(r['world_geometry_additions'], 0); self.assertFalse(r['previous_source_holds_overridden'])

    def test_early_and_late_overflow_discards_all_source_and_patch_results(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.fixture(Path(temp)); r = geometry.build(*args, max_checks=1)
            self.assertEqual(r['status'], 'preshow_level_geometry_budget_withheld')
            with patch.object(geometry, 'threshold_checks', side_effect=OverflowError('late')): r = geometry.build(*args)
            self.assertEqual(r['level_pages'], []); self.assertEqual(r['conditional_roof_patches'], [])

    def test_changed_parent_crop_and_saved_geometry_cache_are_rejected(self):
        for mode in ('crop','cache'):
            with tempfile.TemporaryDirectory() as temp:
                args = self.fixture(Path(temp))
                if mode == 'crop': next((args[0]/'views').rglob('view.png')).write_bytes(b'changed')
                else:
                    r = geometry.build(*args); (Path(r['directory'])/'preshow-level-geometry.json').write_text('{}')
                with self.assertRaises(ValueError): geometry.build(*args)

    def test_independent_original_source_audit_replays_level_pipeline(self):
        from scripts.audit_preshow_level_geometry import audit
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp)); result=geometry.build(*args)
            checked=audit(result['directory'],*args[:-1],Path(temp)/'audit.json')
            self.assertEqual(checked['status'],'passed'); self.assertTrue(checked['fresh_replay_identical'])

    def test_parent_crop_changed_during_final_comparison_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp)); original=geometry.threshold_checks
            def changed(*values):
                result=original(*values); path=next((args[0]/'views').rglob('view.png'))
                path.write_bytes(path.read_bytes()+b'changed'); return result
            with patch.object(geometry,'threshold_checks',side_effect=changed):
                with self.assertRaisesRegex(ValueError,'during build'):geometry.build(*args)
