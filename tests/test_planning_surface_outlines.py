"""Unclassified closed drawing outlines remain independent of surface labels."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

import pymupdf
from shapely.geometry import shape

from voxel_mapper import ordinary_surfaces as surfaces


class PlanningSurfaceOutlineTests(unittest.TestCase):
    def page(self, mode='rectangle'):
        document = pymupdf.open()
        page = document.new_page(width=600, height=600)
        if mode == 'hole':
            drawing = page.new_shape()
            drawing.draw_rect((100, 100, 300, 300))
            drawing.draw_rect((150, 150, 250, 250))
            drawing.finish(color=None, fill=(.5, .5, .5), even_odd=True)
            drawing.commit()
        elif mode == 'linework':
            for a, b in [((100, 100), (300, 100)), ((300, 100), (300, 300)),
                         ((300, 300), (100, 300)), ((100, 300), (100, 100))]:
                page.draw_line(a, b)
        else:
            page.draw_rect((100, 100, 300, 300))
            if mode == 'two':
                page.draw_rect((350, 100, 500, 300))
            if mode == 'covered':
                page.draw_rect((98, 98, 104, 302), color=None, fill=(1, 1, 1))
            if mode == 'label':
                page.insert_text((140, 170), 'Footpath', fontsize=10)
            if mode == 'scale':
                page.insert_text((20, 560), 'Scale 1:100', fontsize=10)
        self.addCleanup(document.close)
        return page

    def inventory(self, page, **options):
        rows, labels, report = surfaces.page_candidates(page, 'a' * 64, 1, **options)
        return rows, labels, report, report['source_outline_inventory']

    def test_unlabelled_rectangle_retains_native_metrics_without_surface_or_scale(self):
        rows, labels, report, inventory = self.inventory(self.page('scale'))
        self.assertEqual(rows, [])
        self.assertEqual(labels, [])
        self.assertEqual(report['surface_candidates'], 0)
        self.assertEqual(inventory['status'], 'complete_source_outline_inventory')
        self.assertTrue(inventory['inventory_complete'])
        self.assertEqual(inventory['retained_outline_count'], 1)
        row = inventory['records'][0]
        self.assertEqual(row['type'], 'unclassified_closed_source_outline')
        self.assertEqual(row['native_metrics'], {'area_square_pdf_points': 40000,
            'perimeter_pdf_points': 800, 'bounds_pdf_points': [100, 300, 300, 500],
            'hole_count': 0})
        for key in ('semantic_classification_verified', 'physical_identity_verified',
                    'registration_verified', 'scale_verified', 'world_placement_eligible'):
            self.assertIs(row[key], False)
        self.assertIsNone(row['geometric_accuracy'])
        self.assertEqual(row['training_labels_generated'], 0)
        self.assertEqual(row['world_geometry_additions'], 0)
        self.assertEqual(row['document_sha256'], 'a' * 64)
        self.assertEqual(row['page'], 1)
        self.assertEqual(row['coordinate_frame'], 'pdf_native_points_y_up')

    def test_hole_preserves_full_original_geometry_and_boundary_measurement(self):
        _, _, _, inventory = self.inventory(self.page('hole'))
        self.assertEqual(inventory['retained_outline_count'], 1)
        row = inventory['records'][0]
        polygon = shape(row['candidate']['geometry'])
        self.assertEqual(len(polygon.interiors), 1)
        self.assertEqual(row['native_metrics']['hole_count'], 1)
        self.assertEqual(row['native_metrics']['area_square_pdf_points'], 30000)
        self.assertEqual(row['native_metrics']['perimeter_pdf_points'], 1200)

    def test_recovered_straight_face_retains_original_line_and_paint_provenance(self):
        rows, _, report, inventory = self.inventory(self.page('linework'))
        self.assertEqual(rows, [])
        self.assertEqual(report['recovery']['status'], 'enclosed_faces_only')
        self.assertEqual(inventory['retained_outline_count'], 1)
        source = inventory['records'][0]['candidate']
        self.assertEqual(source['extraction_kind'], 'linework_boundaries')
        self.assertEqual(len(source['line_parent_references']), 4)
        self.assertEqual(len(source['paint_references']), 4)

    def test_label_binding_behavior_is_unchanged(self):
        rows, labels, report, inventory = self.inventory(self.page('label'))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['surface'], 'stone')
        self.assertEqual(labels[0]['status'], 'unique_contained_surface_label')
        self.assertEqual(report['surface_candidates'], 1)
        self.assertEqual(inventory['retained_outline_count'], 1)
        self.assertEqual(inventory['records'][0]['candidate'],
                         json.loads(json.dumps(rows[0]['candidate'])))

    def test_partial_extraction_withholds_entire_outline_inventory(self):
        page = self.page('label')
        parents, extraction = surfaces.extract_page(page, 'a' * 64, 1)
        with patch.object(surfaces, 'extract_page', return_value=(parents,
                {**extraction, 'status': 'partial_candidate_budget'})):
            rows, _, _, inventory = self.inventory(page)
        self.assertEqual(len(rows), 1)  # Existing material behavior is preserved.
        self.assertEqual(inventory['records'], [])
        self.assertFalse(inventory['inventory_complete'])
        self.assertFalse(inventory['extraction_complete'])
        self.assertEqual(inventory['reason'], 'complete_geometry_extraction_required')

    def test_incomplete_recovery_does_not_publish_a_complete_outline_inventory(self):
        page = self.page()
        parents, _ = surfaces.extract_page(page, 'a' * 64, 1)
        for result in [
            {'status': 'network_budget_withheld', 'reason': 'intersection_pair_budget'},
            {'status': 'enclosed_faces_only', 'counts': {'provenance_budget_deferred': 1}},
        ]:
            with self.subTest(result=result), patch.object(surfaces, 'recover_page',
                    return_value=(parents, result)):
                _, _, _, inventory = self.inventory(page)
            self.assertEqual(inventory['records'], [])
            self.assertFalse(inventory['inventory_complete'])
            self.assertFalse(inventory['line_recovery_complete'])
            self.assertEqual(inventory['reason'], 'complete_line_recovery_required')

    def test_inventory_limit_withholds_all_records_and_reports_eligible_count(self):
        _, _, _, inventory = self.inventory(self.page('two'), max_outline_candidates=1)
        self.assertEqual(inventory['eligible_outline_count'], 2)
        self.assertEqual(inventory['retained_outline_count'], 0)
        self.assertEqual(inventory['records'], [])
        self.assertEqual(inventory['reason'], 'outline_candidate_budget_exceeded')
        self.assertFalse(inventory['inventory_complete'])
        for value in (0, 501, True, 1.0):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'outline inventory'):
                self.inventory(self.page(), max_outline_candidates=value)

    def test_later_boundary_occlusion_remains_excluded(self):
        _, _, report, inventory = self.inventory(self.page('covered'))
        self.assertGreater(report['covered_boundaries_withheld'], 0)
        self.assertEqual(inventory['records'], [])
        self.assertTrue(inventory['inventory_complete'])

    def test_source_record_hash_is_deterministic_and_binds_complete_provenance(self):
        page = self.page('linework')
        _, _, _, first = self.inventory(page)
        _, _, _, second = self.inventory(page)
        self.assertEqual(first, second)
        row = first['records'][0]
        def digest(value):
            return hashlib.sha256(json.dumps(value, sort_keys=True,
                separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        self.assertEqual(row['source_record_sha256'], digest(row['candidate']))
        altered = copy.deepcopy(row['candidate'])
        altered['paint_references'] = []
        self.assertNotEqual(row['source_record_sha256'], digest(altered))


if __name__ == '__main__':
    unittest.main()
