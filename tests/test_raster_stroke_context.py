import copy
import hashlib
import unittest
from unittest.mock import patch

import numpy as np
import pymupdf
from shapely.geometry import box, mapping

from voxel_mapper.raster_stroke_context import review
from voxel_mapper.raster_opening_scan import scan
from voxel_mapper.drawing_annotation_context import review as text_review, printed_role


class StrokeContextTests(unittest.TestCase):
    def drawing(self):
        gray = np.full((180, 300), 255, dtype=np.uint8)
        # Narrow periodic stems can be hatch OR real mullions; no role inferred.
        for x in range(20, 161, 5): gray[30:75, x:x+1] = 70
        gray[30:32, 20:161] = 70
        # A separate two-jamb frame must survive the residual proposal scope.
        gray[90:160, 190:193] = 70; gray[90:160, 260:263] = 70; gray[90:93, 190:263] = 70
        return gray

    def test_repeated_strokes_keep_full_source_groups_and_residual_frame(self):
        gray = self.drawing(); original = gray.copy(); context = review(gray)
        self.assertEqual(context['status'], 'repeated_stroke_layout_context_only')
        self.assertTrue(all(len(v['residual_excluded_group_indices']) >= 20 for v in context['variants']))
        residual = scan(gray, representation='indexed', excluded_groups=context['excluded_groups'])
        self.assertEqual(residual['search_scope'], 'residual_jamb_groups_only')
        self.assertFalse(residual['complete_unscreened_inventory'])
        self.assertTrue(any(f['bounds_pixels'] == [193, 90, 260, 160] for f in residual['index']['consensus_families']))
        self.assertTrue(np.array_equal(gray, original))
        self.assertFalse(context['physical_identity_verified']); self.assertEqual(context, review(gray))
        self.assertEqual(residual['source_gray_sha256'], hashlib.sha256(original.tobytes()).hexdigest())

    def test_sparse_or_wide_stems_are_not_classified_as_repeated_narrow_strokes(self):
        for count, width in [(5, 1), (10, 4)]:
            gray = np.full((120, 240), 255, dtype=np.uint8)
            for x in range(20, 20+count*8, 8): gray[20:85, x:x+width] = 70
            context = review(gray)
            self.assertTrue(all(not v['residual_excluded_group_indices'] for v in context['variants']))

    def test_endpoint_and_pitch_variation_is_bounded_without_moving_pixels(self):
        gray = np.full((150, 220), 255, dtype=np.uint8)
        for i, x in enumerate(range(20, 161, 5)): gray[30+i%3:90+i%3, x:x+1] = 70
        context = review(gray)
        self.assertTrue(any(v['lattices'] for v in context['variants']))
        for variant in context['variants']:
            groups = variant['original_vertical_groups']
            for lattice in variant['lattices']:
                sequence = [groups[i] for i in lattice['group_indices']]
                self.assertLessEqual(max(g[1] for g in sequence)-min(g[1] for g in sequence), 2)
                self.assertLessEqual(max(g[3] for g in sequence)-min(g[3] for g in sequence), 2)
                self.assertGreaterEqual(len(sequence), 6)

    def test_threshold_specific_context_does_not_claim_role_consensus(self):
        gray = self.drawing(); gray[gray==70] = 228
        context = review(gray)
        self.assertFalse(context['variants'][0]['residual_excluded_group_indices'])
        self.assertTrue(context['variants'][1]['residual_excluded_group_indices'])
        self.assertTrue(all(l['semantic_status']=='hatch_or_repeated_mullion_identity_unresolved'
            for v in context['variants'] for l in v['lattices']))

    def test_budget_failure_discards_every_partial_variant(self):
        for options in [{'max_checks': 1}, {'max_groups': 1}]:
            context = review(self.drawing(), **options)
            self.assertEqual(context['status'], 'stroke_context_budget_withheld')
            self.assertEqual(context['variants'], []); self.assertEqual(context['excluded_groups'], {})
        for options in [{'max_checks': True}, {'max_groups': 4097}]:
            with self.assertRaises(ValueError): review(self.drawing(), **options)

    def test_exclusions_must_be_unchanged_complete_original_groups(self):
        gray = self.drawing(); groups = review(gray)['excluded_groups']
        for mutate in ['not_dark', 'partial_height', 'partial_width', 'duplicate', 'wrong_threshold']:
            altered = copy.deepcopy(groups)
            if mutate == 'not_dark': altered['220'][0][0] += 2; altered['220'][0][2] += 2
            elif mutate == 'partial_height': altered['220'][0][1] += 1
            elif mutate == 'partial_width':
                modified = gray.copy(); modified[30:75, 21] = 70
                with self.assertRaises(ValueError): scan(modified, excluded_groups=altered)
                continue
            elif mutate == 'duplicate': altered['220'].append(altered['220'][0])
            else: altered.pop('235')
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): scan(gray, excluded_groups=altered)

    def test_residual_heads_use_original_strokes_and_do_not_fill_gaps(self):
        gray = self.drawing(); gray[90:93, 193:260] = 255
        context = review(gray); residual = scan(gray, representation='indexed', excluded_groups=context['excluded_groups'])
        self.assertFalse(any(f['bounds_pixels']==[193, 90, 260, 160] for f in residual['index']['consensus_families']))

    def test_real_repeated_mullions_remain_preserved_as_ambiguous_context(self):
        gray = self.drawing(); context = review(gray)
        for variant in context['variants']:
            for group in variant['original_vertical_groups']:
                left, top, right, bottom = group
                self.assertTrue((gray[top:bottom, left:right] < variant['threshold']).all())
        raw = scan(gray, representation='indexed')
        residual = scan(gray, representation='indexed', excluded_groups=context['excluded_groups'])
        self.assertGreater(len(raw['index']['consensus_families']), len(residual['index']['consensus_families']))
        self.assertEqual(raw['recipe']['pair_scope'], 'all')


class AnnotationContextTests(unittest.TestCase):
    def test_only_complete_visible_numeric_or_level_labels_give_context(self):
        with pymupdf.open() as document:
            page = document.new_page(width=400, height=300)
            page.insert_text((40, 80), 'Shop Level +182.50', fontsize=10)
            frame = {'id': 'frame', 'geometry_pdf_native': mapping(box(20, 200, 200, 240))}
            result = text_review(page, box(0, 0, 400, 300), [frame])
            self.assertEqual(result['cycles'][0]['status'], 'visible_numeric_or_level_text_overlap')
            self.assertEqual(result['labels'][0]['printed_role'], 'level_caption')
            self.assertTrue(result['labels'][0]['trace_indices'])
            self.assertFalse(result['cycles'][0]['physical_opening_verified'])
            self.assertFalse(result['cycles'][0]['automatic_geometry_selection'])
            # Crossing native metrics remain explicit, with the full label screened.
            smaller = {'id': 'partial', 'geometry_pdf_native': mapping(box(40, 200, 65, 240))}
            partial = text_review(page, box(0, 0, 400, 300), [smaller])
            self.assertEqual(partial['labels'][0]['containing_cycle_ids'], [])
            self.assertEqual(partial['labels'][0]['cycle_box_relations'][0]['relationship'], 'label_box_crosses_cycle')
            page.draw_rect((25, 60, 200, 90), fill=(1, 1, 1), color=(1, 1, 1))
            hidden = text_review(page, box(0, 0, 400, 300), [frame])
            self.assertEqual(hidden['cycles'][0]['status'], 'no_supported_identifying_text')

    def test_opening_references_and_numeric_context_cannot_select_geometry(self):
        self.assertEqual(printed_role('W.3.01'), 'opening_reference')
        self.assertEqual(printed_role('182500'), 'numeric_label')
        for text in ['remove Shop Level +182.50 please', '1234567', 'window', '1 or 2']:
            self.assertIsNone(printed_role(text))
        with pymupdf.open() as document:
            page = document.new_page(width=400, height=300); page.insert_text((40, 80), 'W.3.01', fontsize=10)
            frames = [{'id': name, 'geometry_pdf_native': mapping(box(20, 200, 200, 240))} for name in ['a', 'b']]
            result = text_review(page, box(0, 0, 400, 300), frames)
            self.assertEqual(result['labels'][0]['containing_cycle_ids'], ['a', 'b'])
            self.assertTrue(all(c['status']=='visible_opening_reference_context' for c in result['cycles']))
            exhausted = text_review(page, box(0, 0, 400, 300), frames, max_checks=1)
            self.assertEqual(exhausted['labels'], []); self.assertEqual(exhausted['cycles'], [])
