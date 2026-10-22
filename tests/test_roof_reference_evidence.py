import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pymupdf
from shapely.geometry import box, mapping, shape

from voxel_mapper import drawing_side_references as side
from voxel_mapper import roof_reference_evidence as reference
from voxel_mapper import roof_source_topology as topology
from voxel_mapper.architectural_view_layout import view_claim
from voxel_mapper.drawing_view_candidates import staggered_rows
from voxel_mapper.drawing_views import page_labels
from voxel_mapper.numbered_elevation_captions import parse
from tests import test_roof_source_topology as parent_tests


class RoofReferenceTests(unittest.TestCase):
    def page(self, doc, duplicate=False):
        page = doc.new_page(width=500, height=500)
        page.insert_text((330, 450), '2967-48', fontsize=10)
        page.draw_circle((200, 200), 17)
        page.draw_line((212.02, 187.98), (224., 200.))
        page.draw_line((224., 200.), (212.02, 212.02))
        if duplicate: page.draw_line((224., 200.), (212.02, 187.98))
        page.insert_text((194, 203), '30', fontsize=8)
        page.insert_text((231, 203), '8', fontsize=8)
        return page

    def screened(self, page, **kwargs):
        with patch.object(side, 'screen_span', return_value={'status': 'raster_consistent_candidate'}):
            return side.page_references(page, **kwargs)

    def rows(self):
        return [{'low': 10., 'high': 20., 'captions': [{'id': 'lower', 'label_geometry': mapping(box(10, 10, 30, 20))}]},
            {'low': 65., 'high': 75., 'captions': [{'id': 'upper', 'label_geometry': mapping(box(80, 65, 100, 75))}]}]

    def fixture(self, root):
        old = parent_tests.RoofSourceTopologyTests().fixture(root)
        parent = topology.build(*old)
        pdfdir = root / 'additional'; pdfdir.mkdir()
        with pymupdf.open() as doc:
            page = doc.new_page(width=900, height=800)
            for (x, y), number, direction in zip([(40, 300), (460, 300), (40, 660), (460, 710)],
                    (5, 6, 7, 8), ('South', 'East', 'North', 'West')):
                page.draw_rect((x, y-200, x+280, y-30), fill=(.7, .7, .7))
                page.insert_text((x, y), f'Elevation {number} to the {direction}', fontsize=10)
                page.insert_text((x, y+15), '1 : 100', fontsize=8)
            for i in range(3): page.insert_text((780, 40 + 15*i), 'note', fontsize=8)
            page.insert_text((780, 780), '2967-30', fontsize=10)
            raw = doc.tobytes()
        sha = hashlib.sha256(raw).hexdigest(); (pdfdir / (sha + '.pdf')).write_bytes(raw)
        catalogue = root / 'catalogue.json'; catalogue.write_text(json.dumps({'entries': [{'sha256': sha}]}))
        # Parent fixture order: gradient, partial, gable, profile, preview, components, views, corpus, output.
        return Path(parent['directory']), old[5], old[6], old[7], catalogue, pdfdir, root / 'references'

    def test_cardinal_and_legacy_diagonal_captions_keep_exact_number_direction_and_state(self):
        for number, value, bearing in [(5, 'South', 'S'), (6, 'East', 'E'), (7, 'North', 'N'),
                (8, 'West', 'W'), (1, 'S. East', 'SE'), (4, 'N.West', 'NW')]:
            text = f'Elevation {number} to the {value}'
            self.assertEqual(parse(text)['bearing'], bearing)
            self.assertEqual(view_claim(text)['view_number'], number)
            self.assertEqual(view_claim(text)['printed_state'], 'unspecified')
        self.assertEqual(parse("Elevation 8 to the West 'as proposed' | 1:200")['printed_scale_denominator'], 200)

    def test_noncaption_numbers_prose_and_invalid_scales_never_become_directions_or_pitch(self):
        for text in ('30', '30 degrees', 'See Elevation 8 to the West', 'Elevation 0 to the West',
                'Elevation 8 to the West | 1:0', 'Elevation 8 to the West | 1:99999',
                'Elevation 8 to the N.Eest', 'Elevation 8 to the West wall', None, 'x'*501):
            self.assertIsNone(parse(text))

    def test_cardinal_page_labels_keep_original_scale_and_visibility_gates(self):
        with pymupdf.open() as doc:
            page = doc.new_page(width=600, height=600)
            page.insert_text((400, 500), '2967-30', fontsize=10)
            page.insert_text((40, 230), 'Elevation 8 to the West', fontsize=10)
            page.insert_text((40, 250), '1 : 100', fontsize=8)
            groups = [{'id': 'original', 'bbox_page_points': [30, 40, 300, 200]}]
            label = page_labels(page, groups)['views'][0]
            self.assertEqual(label['view_key_candidate'], ['2967', 30, 8])
            self.assertEqual(label['bearing_label_candidate'], 'W')
            with patch('voxel_mapper.drawing_views.screen_span', return_value={'status': 'withheld'}):
                self.assertNotIn('view_key_candidate', page_labels(page, groups)['views'][0])

    def test_side_head_retains_whole_arms_and_all_exact_duplicate_witnesses(self):
        with pymupdf.open() as doc:
            page = self.page(doc, duplicate=True); before = page.get_drawings()
            result = self.screened(page); row = result['references'][0]
            self.assertEqual(row['target_view_key_candidate'], ['2967', 30, 8])
            self.assertIsNone(row['pitch_degrees']); self.assertFalse(row['marker_clipping_verified'])
            self.assertEqual(sorted(len(a['source_path_indices']) for a in row['head_alternatives'][0]['head_source_arms']), [1, 2])
            self.assertEqual(before, page.get_drawings())

    def test_unrelated_fill_rectangle_and_missing_arm_do_not_create_side_head(self):
        with pymupdf.open() as doc:
            page = doc.new_page(width=500, height=500)
            page.draw_circle((200, 200), 17); page.insert_text((194, 203), '30', fontsize=8)
            page.draw_rect((212, 188, 225, 212), fill=(0, 0, 0))
            page.draw_line((212.02, 187.98), (224, 200)); page.insert_text((231, 203), '8', fontsize=8)
            self.assertEqual(self.screened(page)['references'], [])

    def test_competing_view_numbers_and_failed_glyphs_stay_held(self):
        with pymupdf.open() as doc:
            page = self.page(doc); page.insert_text((235, 204), '7', fontsize=8)
            row = self.screened(page)['references'][0]
            self.assertEqual(len(row['head_alternatives']), 2); self.assertNotIn('target_view_key_candidate', row)
        with pymupdf.open() as doc:
            page = self.page(doc)
            with patch.object(side, 'screen_span', return_value={'status': 'withheld'}):
                row = side.page_references(page)['references'][0]
            self.assertNotIn('target_view_key_candidate', row)

    def test_side_reference_budget_clears_all_partial_candidates(self):
        with pymupdf.open() as doc:
            page = self.page(doc)
            result = self.screened(page, max_checks=1)
            self.assertEqual(result['status'], 'side_reference_budget_withheld')
            self.assertEqual(result['references'], []); self.assertEqual(result['glyph_screens'], {})
        for bad in (0, True, 100001):
            with self.assertRaises(ValueError): side.page_references(None, max_checks=bad)

    def test_staggered_disjoint_rows_use_artwork_gap_not_blank_caption_margin(self):
        gray = np.zeros((120, 120), np.uint8); gray[20:37] = 255; rows = self.rows(); before = copy.deepcopy(rows)
        result, receipts = staggered_rows(rows, gray, pymupdf.Matrix(1, 0, 0, 1, 0, 0), (1, 0), lambda: None)
        self.assertEqual(rows, before); self.assertEqual(len(result), 1)
        self.assertEqual(receipts[0]['source_raster_window_pixels'][1], 40)
        self.assertEqual(receipts[0]['white_row_runs_relative_pixels'], [])

    def test_actual_white_artwork_corridor_keeps_two_caption_rows(self):
        gray = np.zeros((120, 120), np.uint8); gray[42:54] = 255
        result, receipts = staggered_rows(self.rows(), gray, pymupdf.Matrix(1, 0, 0, 1, 0, 0), (1, 0), lambda: None)
        self.assertEqual(len(result), 2); self.assertEqual(receipts[0]['status'], 'separate_caption_rows_with_white_corridor')

    def test_same_caption_column_is_not_merged_without_white_gap(self):
        rows = self.rows(); rows[1]['captions'][0]['label_geometry'] = mapping(box(10, 65, 30, 75))
        result, receipts = staggered_rows(rows, np.zeros((120, 120), np.uint8), pymupdf.Matrix(1, 0, 0, 1, 0, 0), (1, 0), lambda: None)
        self.assertEqual(len(result), 2); self.assertEqual(receipts, [])

    def test_missing_competing_and_held_reference_targets_do_not_select_nearest(self):
        row = {'id': 'source', 'target_view_key_candidate': ['2967', 30, 8]}
        target = {'view_key_candidate': ['2967', 30, 8], 'view_id': 'a'}
        self.assertEqual(reference.target_links([row], [target], lambda: None)[0]['status'], 'unique_source_view_reference_candidate')
        self.assertEqual(reference.target_links([row], [target, {**target, 'view_id': 'b'}], lambda: None)[0]['status'], 'competing_source_view_targets')
        self.assertEqual(reference.target_links([row], [], lambda: None)[0]['status'], 'missing_source_view_target')
        row.pop('target_view_key_candidate')
        self.assertEqual(reference.target_links([row], [target], lambda: None)[0]['target_candidates'], [])

    def test_complete_build_replays_with_cardinal_source_crops_and_no_mesh(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.fixture(Path(temp)); result = reference.build(*args)
            self.assertEqual(result, json.loads(json.dumps(result)))
            self.assertEqual(result, reference.build(*args))
            self.assertEqual(result['counts']['additional_view_candidates'], 4)
            self.assertEqual(result['new_roof_models'], []); self.assertEqual(result['world_geometry_additions'], 0)
            self.assertFalse(result['previous_source_holds_overridden'])

    def test_late_and_early_work_hold_clear_all_source_views_and_render_pins(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.fixture(Path(temp)); result = reference.build(*args, max_checks=1)
            self.assertEqual(result['status'], 'roof_reference_evidence_budget_withheld')
            with patch.object(reference, 'target_links', side_effect=OverflowError('late')):
                result = reference.build(*args)
            self.assertEqual(result['additional_pages'], []); self.assertEqual(result['output_artifact_sha256'], {})

    def test_changed_additional_pdf_or_saved_crop_is_rejected(self):
        for mode in ('pdf', 'crop'):
            with tempfile.TemporaryDirectory() as temp:
                args = self.fixture(Path(temp))
                if mode == 'pdf': next(args[5].glob('*.pdf')).write_bytes(b'changed')
                else:
                    result = reference.build(*args); (Path(result['directory']) / result['rendered_views'][0]['png']).write_bytes(b'changed')
                with self.assertRaises(ValueError): reference.build(*args)

    def test_independent_source_audit_preserves_four_crops(self):
        from scripts.audit_roof_reference_evidence import audit
        with tempfile.TemporaryDirectory() as temp:
            args = self.fixture(Path(temp)); result = reference.build(*args)
            checked = audit(result['directory'], *args[:-1], Path(temp) / 'audit.json')
            self.assertEqual(checked['status'], 'passed')
            self.assertEqual(checked['checked']['original_caption_traces'], 4)
            self.assertEqual(checked['checked']['original_render_artifacts'], 8)
