import copy
from concurrent.futures import CancelledError
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf
from shapely.geometry import shape

from voxel_mapper import architectural_graph, architectural_view_layout, drawing_view_candidates
from voxel_mapper import planning_component_measurements, planning_section_profiles as profiles
from voxel_mapper.building_spec import digest


def fixture(*, two=False, caption='Proposed Section A-A | 1:100', label='Container', rotation=0):
    doc = pymupdf.open()
    page = doc.new_page(width=640, height=400)
    page.draw_rect((60, 40, 120, 110))
    page.insert_text((70, 80), label, fontsize=5)
    page.insert_text((30, 190), caption, fontsize=8)
    if two:
        page.draw_rect((400, 40, 470, 120))
        page.insert_text((410, 80), 'Container', fontsize=5)
        page.insert_text((330, 190), 'Proposed Section B-B | 1:100', fontsize=8)
    page.set_rotation(rotation)
    return doc, page


def inputs(page):
    sha = hashlib.sha256(page.parent.tobytes()).hexdigest()
    graph = architectural_graph.build([])
    graph.update(document_sha256=sha, page=1)
    layout = architectural_view_layout.review(page, sha, 1, graph)
    views = drawing_view_candidates.candidates(page, sha, 1, layout, [])
    measurements = planning_component_measurements.page_evidence(page, sha, 1, layout, None)
    return sha, views, measurements


class SectionProfileTests(unittest.TestCase):
    def test_original_pilot_exports_profiles_overlay_and_current_implementation_pin(self):
        from voxel_mapper import planning_area_pilot as pilot
        doc, _ = fixture(two=True)
        data = doc.tobytes()
        doc.close()
        sha = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'source.pdf').write_bytes(data)
            config = {'version': pilot.VERSION, 'area_id': 'section-fixture',
                'application_references': ['APP/1'], 'documents': [{'file': 'source.pdf',
                    'sha256': sha, 'title': 'Synthetic sections', 'role': 'section',
                    'drawing_state': 'proposed', 'application_reference': 'APP/1'}]}
            report = pilot.run(config, lambda p: root/p, root/'output')
            self.assertEqual(report['summary']['nominal_section_profile_hypotheses'], 2)
            self.assertEqual(report['summary']['physical_section_heights_verified'], 0)
            self.assertIn(profiles.__name__, report['contract']['implementations'])
            self.assertFalse(report['world_placement_eligible'])
            self.assertEqual(report['park_world_blocks_added'], 0)
            self.assertIn('section-profiles.html', (root/'output/review.html').read_text())
            overlay = (root/'output'/report['pages'][0]['outline_overlay']['file']).read_text()
            self.assertIn('class="section_profile"', overlay)
            for name, expected in report['output_sha256'].items():
                self.assertEqual(hashlib.sha256((root/'output'/name).read_bytes()).hexdigest(), expected)

    def test_exact_source_polygon_and_section_axes_measure_spans_without_physical_height(self):
        doc, page = fixture()
        try:
            sha, views, measurements = inputs(page)
            result = profiles.page_evidence(page, sha, 1, views, measurements)
            self.assertEqual(result['summary']['nominal_section_profile_hypotheses'], 1)
            row = result['profiles'][0]
            self.assertAlmostEqual(row['horizontal_span_nominal_m'], 60*100*.0254/72)
            self.assertAlmostEqual(row['vertical_span_nominal_m'], 70*100*.0254/72)
            self.assertEqual(digest(row['geometry_pdf_native']), digest(row['source_outline']['candidate']['geometry']))
            self.assertEqual(row['source_outline']['source_record_sha256'], digest(row['source_outline']['candidate']))
            self.assertIsNone(row['physical_height_m'])
            self.assertFalse(row['physical_height_verified'])
            self.assertFalse(row['world_placement_eligible'])
            self.assertEqual(result['local_3d_components'], 0)
            self.assertEqual(result['world_geometry_additions'], 0)
            self.assertEqual(result['training_labels_generated'], 0)
            self.assertEqual(result['id'], digest({k: v for k, v in result.items() if k != 'id'}))
        finally:
            doc.close()

    def test_wide_white_run_intersects_between_caption_interval_without_clipping_source(self):
        doc, page = fixture(two=True)
        try:
            sha, views, measurements = inputs(page)
            self.assertEqual(len(views['views']), 2)
            proof = views['views'][0]['separator_evidence'][0]
            a, b = proof['between_caption_interval_pdf_points']
            x, y = proof['chosen_gap_pdf_points']
            self.assertGreaterEqual(x, a)
            self.assertLessEqual(y, b)
            self.assertTrue(any(end > b for _, end in proof['original_white_corridors_pdf_points']))
            result = profiles.page_evidence(page, sha, 1, views, measurements)
            self.assertEqual(len(result['profiles']), 2)
            for row in result['profiles']:
                self.assertTrue(shape(row['geometry_pdf_native']).equals(shape(row['source_outline']['candidate']['geometry'])))
                self.assertFalse(row['view_scope_verified'])
        finally:
            doc.close()

    def test_rotation_retains_native_polygon_spans_and_page_rotation(self):
        doc, page = fixture(rotation=90)
        try:
            sha, views, measurements = inputs(page)
            result = profiles.page_evidence(page, sha, 1, views, measurements)
            self.assertAlmostEqual(result['profiles'][0]['vertical_span_nominal_m'], 70*100*.0254/72)
            self.assertEqual(page.rotation, 90)
            self.assertEqual(result, profiles.page_evidence(page, sha, 1, views, measurements))
        finally:
            doc.close()

    def test_unknown_or_conflicting_state_and_missing_scale_do_not_supply_spans(self):
        for settings in ({'caption': 'Section A-A | 1:100'}, {'label': 'Existing Container'},
                         {'caption': 'Proposed Section A-A'}):
            doc, page = fixture(**settings)
            try:
                sha, views, measurements = inputs(page)
                self.assertEqual(profiles.page_evidence(page, sha, 1, views, measurements)['profiles'], [])
            finally:
                doc.close()

    def test_elevation_or_plan_caption_does_not_turn_vertical_span_into_section_height(self):
        for caption in ('Proposed Front Elevation | 1:100', 'Proposed Ground Floor Plan | 1:100'):
            doc, page = fixture(caption=caption)
            try:
                sha, views, measurements = inputs(page)
                self.assertEqual(profiles.page_evidence(page, sha, 1, views, measurements)['profiles'], [])
            finally:
                doc.close()

    def test_shared_or_nested_label_enclosures_are_not_individual_profile_components(self):
        for nested in (False, True):
            doc, page = fixture()
            try:
                if nested:
                    page.draw_rect((40, 20, 140, 130))
                else:
                    page.insert_text((70, 95), 'Container', fontsize=5)
                sha, views, measurements = inputs(page)
                result = profiles.page_evidence(page, sha, 1, views, measurements)
                self.assertEqual(result['profiles'], [])
                self.assertTrue(result['label_associations']['labels'])
            finally:
                doc.close()

    def test_hidden_component_label_is_withheld(self):
        doc, page = fixture()
        try:
            page.draw_rect((68, 73, 100, 82), color=None, fill=(1, 1, 1))
            sha, views, measurements = inputs(page)
            self.assertEqual(profiles.page_evidence(page, sha, 1, views, measurements)['profiles'], [])
        finally:
            doc.close()

    def test_enclosure_crossing_inferred_view_edge_is_withheld_whole(self):
        doc = pymupdf.open()
        page = doc.new_page(width=640, height=400)
        try:
            # The source continues below the caption band. Its visible label
            # does not license slicing a shortened profile at the view edge.
            page.draw_rect((10, 40, 180, 280))
            page.insert_text((70, 80), 'Container', fontsize=5)
            page.insert_text((30, 190), 'Proposed Section A-A | 1:100', fontsize=8)
            sha, views, measurements = inputs(page)
            result = profiles.page_evidence(page, sha, 1, views, measurements)
            crossing = [r for r in result['withheld'] if r['reason'] == 'unique_whole_scaled_section_scope_required']
            self.assertTrue(crossing)
            self.assertFalse({r['candidate_id'] for r in crossing} & {r['source_outline']['candidate_id'] for r in result['profiles']})
        finally:
            doc.close()

    def test_nondefault_units_crop_and_printed_paper_mismatch_block_nominal_spans(self):
        for case in ('unit', 'crop', 'paper'):
            doc, page = fixture()
            try:
                if case == 'unit':
                    doc.xref_set_key(page.xref, 'UserUnit', '2')
                elif case == 'crop':
                    page.set_cropbox(pymupdf.Rect(0, 0, 600, 350))
                else:
                    page.insert_text((300, 350), 'As indicated @A1', fontsize=8)
                sha, views, measurements = inputs(page)
                result = profiles.page_evidence(page, sha, 1, views, measurements)
                self.assertFalse(result['analysis_complete'])
                self.assertEqual(result['profiles'], [])
            finally:
                doc.close()

    def test_incomplete_outline_or_label_inventory_cannot_publish_partial_profiles(self):
        doc, page = fixture()
        try:
            sha, views, measurements = inputs(page)
            with patch.object(profiles.ordinary_surfaces, 'page_candidates', return_value=([], [], {'source_outline_inventory': {'inventory_complete': False}})):
                result = profiles.page_evidence(page, sha, 1, views, measurements)
            self.assertFalse(result['analysis_complete'])
            self.assertEqual(result['profiles'], [])
            original = profiles.planning_outline_semantics.page_candidates
            def incomplete(*args, **kwargs):
                r = original(*args, **kwargs)
                r['inventory_complete'] = False
                return r
            with patch.object(profiles.planning_outline_semantics, 'page_candidates', side_effect=incomplete):
                result = profiles.page_evidence(page, sha, 1, views, measurements)
            self.assertFalse(result['analysis_complete'])
            self.assertEqual(result['profiles'], [])
        finally:
            doc.close()

    def test_budget_exhaustion_discards_all_profiles(self):
        doc, page = fixture(two=True)
        try:
            sha, views, measurements = inputs(page)
            for options in ({'max_profiles': 1}, {'max_checks': 1}, {'max_output_bytes': 16384}):
                result = profiles.page_evidence(page, sha, 1, views, measurements, options=options)
                self.assertFalse(result['analysis_complete'], options)
                self.assertEqual(result['profiles'], [])
            for options in ({'max_profiles': True}, {'max_checks': 8193}, {'extra': 1}):
                with self.assertRaises(ValueError):
                    profiles.page_evidence(page, sha, 1, views, measurements, options=options)
        finally:
            doc.close()

    def test_changed_source_context_and_view_scope_are_rejected(self):
        doc, page = fixture()
        try:
            sha, views, measurements = inputs(page)
            for field, value in (('document_sha256', 'b'*64), ('page', 2), ('source_layout_sha256', 'stale')):
                changed = copy.deepcopy(views)
                changed[field] = value
                with self.assertRaises(ValueError):
                    profiles.page_evidence(page, sha, 1, changed, measurements)
            changed = json.loads(json.dumps(views))
            changed['views'][0]['geometry']['coordinates'][0][0] = [0, 0]
            with self.assertRaises(ValueError):
                profiles.page_evidence(page, sha, 1, changed, measurements)
            changed = copy.deepcopy(measurements)
            changed['physical_scale_verified'] = True
            with self.assertRaises(ValueError):
                profiles.page_evidence(page, sha, 1, views, changed)
        finally:
            doc.close()

    def test_cancelled_analysis_and_review_do_not_finish(self):
        doc, page = fixture()
        try:
            sha, views, measurements = inputs(page)
            with self.assertRaises(CancelledError):
                profiles.page_evidence(page, sha, 1, views, measurements, cancelled=lambda: True)
            result = profiles.page_evidence(page, sha, 1, views, measurements)
            with tempfile.TemporaryDirectory() as tmp, self.assertRaises(CancelledError):
                profiles.write_review(tmp, [result], cancelled=lambda: True)
        finally:
            doc.close()

    def test_review_deduplicates_identical_pages_rejects_stale_and_retains_explicit_holds(self):
        doc, page = fixture()
        try:
            sha, views, measurements = inputs(page)
            result = profiles.page_evidence(page, sha, 1, views, measurements)
            with tempfile.TemporaryDirectory() as tmp:
                review = profiles.write_review(tmp, [result, result])
                self.assertEqual(len(review['profiles']), 1)
                self.assertEqual(len(review['source_pages']), 1)
                self.assertEqual(review['local_3d_components'], 0)
                self.assertIn('No physical height', (Path(tmp)/'section-profiles.html').read_text())
                self.assertEqual(digest(review), digest(json.loads((Path(tmp)/'section-profiles.json').read_text())))
                changed = copy.deepcopy(result)
                changed['profiles'][0]['vertical_span_nominal_m'] = 10
                with self.assertRaises(ValueError):
                    profiles.write_review(tmp, [changed])
                changed['id'] = digest({k: v for k, v in changed.items() if k != 'id'})
                with self.assertRaises(ValueError):
                    profiles.write_review(tmp, [result, changed])
        finally:
            doc.close()
