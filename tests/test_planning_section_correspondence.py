import copy
from concurrent.futures import CancelledError
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf

from voxel_mapper import architectural_graph, architectural_view_layout, drawing_view_candidates
from voxel_mapper import ordinary_surfaces, planning_component_footprints, planning_component_measurements
from voxel_mapper import planning_outline_semantics, planning_section_profiles
from voxel_mapper import planning_section_correspondence as correspondence
from voxel_mapper.building_spec import digest
from voxel_mapper.drawing_page_tools import native_inverse


def source(page, *, floor=False):
    sha = hashlib.sha256(page.parent.tobytes()).hexdigest()
    graph = architectural_graph.build([])
    graph.update(document_sha256=sha, page=1)
    layout = architectural_view_layout.review(page, sha, 1, graph)
    components = None
    if floor:
        _, _, report = ordinary_surfaces.page_candidates(page, sha, 1)
        inventory = report['source_outline_inventory']
        labels = planning_outline_semantics.page_candidates(page, sha, 1, inventory)
        components = planning_component_footprints.page_candidates(page, sha, 1, inventory, labels)
    measurements = planning_component_measurements.page_evidence(page, sha, 1, layout, components)
    views = drawing_view_candidates.candidates(page, sha, 1, layout, [])
    profiles = planning_section_profiles.page_evidence(page, sha, 1, views, measurements)
    references = correspondence.page_references(page, sha, 1, measurements)
    return {'document_sha256': sha, 'page': 1, 'component_footprints': components,
        'component_measurements': measurements, 'section_profiles': profiles, 'drawing_references': references}


def fixture(*, rivals=2, rotation=0, hidden=False, extra_index=False, ellipse=False,
            reference=True, series='TEST', state='Proposed', mismatch=False):
    floor = pymupdf.open()
    page = floor.new_page(width=900, height=700)
    for i in range(rivals):
        page.draw_rect((100, 100+120*i, 300, (170 if not mismatch or i == 0 else 195)+120*i))
        page.insert_text((150, 140+120*i), 'Container', fontsize=8)
    page.insert_text((70, 500), state+' Ground Floor Plan | 1:100', fontsize=10)
    page.insert_text((70, 650), series+'-AA-BB-CC-DR-A-0201', fontsize=8)
    if reference:
        page.draw_oval((613, 333, 647, 367 if not ellipse else 359))
        page.insert_text((619, 353), '0301', fontsize=8)
        page.insert_text((657, 353), '4', fontsize=8)
        if extra_index:
            page.insert_text((626, 322), '2', fontsize=8)
        if hidden:
            page.draw_rect((618, 344, 640, 356), color=None, fill=(1, 1, 1))
    page.set_rotation(rotation)
    section = pymupdf.open()
    other = section.new_page(width=900, height=700)
    other.draw_rect((60, 40, 130, 110))
    other.insert_text((70, 80), 'Container', fontsize=6)
    other.insert_text((30, 190), 'Proposed Section A-A | 1:100', fontsize=10)
    other.insert_text((70, 650), 'TEST-AA-BB-CC-DR-A-0301', fontsize=8)
    return floor, section


class SectionCorrespondenceTests(unittest.TestCase):
    def sources(self, **kwargs):
        floor, section = fixture(**kwargs)
        self.addCleanup(floor.close)
        self.addCleanup(section.close)
        return source(floor[0], floor=True), source(section[0]), floor[0]

    def test_original_circle_and_four_digit_sheet_preserve_leading_zero_and_exact_cubics(self):
        plan, _, page = self.sources()
        references = plan['drawing_references']
        self.assertTrue(references['analysis_complete'])
        self.assertEqual(len(references['markers']), 1)
        marker = references['markers'][0]
        self.assertEqual(marker['target_sheet_candidate'], '0301')
        self.assertEqual(marker['target_view_index_candidate'], 4)
        path = page.get_drawings()[marker['circle_path_index']]
        expected = [[list(p*native_inverse(page)) for p in item[1:]] for item in path['items']]
        self.assertEqual(marker['circle_source_beziers_pdf_native'], expected)
        self.assertFalse(marker['marker_clipping_verified'])
        self.assertFalse(marker['section_cut_identity_verified'])
        self.assertEqual(references['world_geometry_additions'], 0)

    def test_rotation_retains_original_native_marker_and_restores_rotation(self):
        plan, section, page = self.sources(rotation=90)
        marker = plan['drawing_references']['markers'][0]
        self.assertEqual(marker['target_view_index_candidate'], 4)
        self.assertEqual(page.rotation, 90)
        self.assertEqual(plan['drawing_references'], correspondence.page_references(
            page, plan['document_sha256'], 1, plan['component_measurements']))
        self.assertEqual(correspondence.review_pages([plan, section])['summary']['section_plan_context_pairs'], 2)

    def test_two_outside_numbers_remain_ambiguous_without_nearest_or_smaller_index_choice(self):
        plan, _, _ = self.sources(extra_index=True)
        marker = plan['drawing_references']['markers'][0]
        self.assertEqual(len(marker['outside_view_index_candidates']), 2)
        self.assertIsNone(marker['target_view_index_candidate'])
        self.assertEqual(marker['status'], 'withheld_reference_index_or_visibility')

    def test_hidden_sheet_number_cannot_supply_an_index(self):
        plan, _, _ = self.sources(hidden=True)
        marker = plan['drawing_references']['markers'][0]
        self.assertIsNone(marker['target_view_index_candidate'])
        self.assertEqual(marker['status'], 'withheld_reference_index_or_visibility')

    def test_ellipse_is_not_a_circle_reference(self):
        plan, _, _ = self.sources(ellipse=True)
        self.assertEqual(plan['drawing_references']['markers'], [])

    def test_rival_components_and_width_mismatch_remain_without_assigning_height(self):
        plan, section, _ = self.sources(mismatch=True)
        before = copy.deepcopy([plan, section])
        review = correspondence.review_pages([plan, section])
        self.assertEqual(review['summary']['section_plan_context_pairs'], 2)
        self.assertEqual(review['summary']['profiles_with_multiple_plan_candidates'], 1)
        row = review['profiles'][0]
        self.assertIsNone(row['selected_component_id'])
        checks = [c['nominal_width_comparisons'][0]['span_within_tolerance'] for c in row['plan_candidates']]
        self.assertIn([True, False], checks)
        self.assertIn([False, False], checks)
        self.assertTrue(all(len(c['sheet_marker_candidate_ids']) == 1 for c in row['plan_candidates']))
        self.assertFalse(review['physical_height_verified'])
        self.assertIsNone(review['physical_height_m'])
        self.assertEqual(review['local_3d_components'], 0)
        self.assertEqual(review['training_labels_generated'], 0)
        self.assertFalse(review['model_weights_updated'])
        self.assertEqual([plan, section], before)

    def test_one_size_compatible_candidate_still_requires_section_cut_identity(self):
        plan, section, _ = self.sources(rivals=1)
        review = correspondence.review_pages([plan, section])
        self.assertEqual(review['summary']['section_plan_context_pairs'], 1)
        self.assertEqual(review['summary']['profiles_with_multiple_plan_candidates'], 0)
        self.assertIsNone(review['profiles'][0]['selected_component_id'])
        self.assertFalse(review['profiles'][0]['plan_candidates'][0]['section_cut_link_supported'])

    def test_other_series_different_state_or_missing_reference_cannot_create_context_pair(self):
        for kwargs in ({'series': 'OTHER'}, {'state': 'Existing'}, {'reference': False}):
            with self.subTest(kwargs=kwargs):
                plan, section, _ = self.sources(**kwargs)
                self.assertEqual(correspondence.review_pages([plan, section])['summary']['section_plan_context_pairs'], 0)

    def test_duplicate_source_pages_collapse_and_conflicting_or_stale_evidence_rejected(self):
        plan, section, page = self.sources()
        expected = correspondence.review_pages([plan, section])
        self.assertEqual(expected, correspondence.review_pages([plan, section, plan]))
        for key in ('component_measurements', 'section_profiles', 'drawing_references', 'component_footprints'):
            changed = copy.deepcopy(plan)
            changed[key]['version'] = 'stale'
            with self.subTest(key=key), self.assertRaises(ValueError):
                correspondence.review_pages([changed, section])
        changed = copy.deepcopy(plan)
        changed['drawing_references']['checks'] += 1
        with self.assertRaises(ValueError):
            correspondence.review_pages([plan, changed])
        with self.assertRaises(ValueError):
            correspondence.page_references(page, 'f'*64, 1, plan['component_measurements'])

    def test_incomplete_component_source_is_recorded_and_cannot_supply_pairs(self):
        plan, section, _ = self.sources()
        plan['component_footprints']['analysis_complete'] = False
        measurements = plan['component_measurements']
        measurements['source_components_sha256'] = digest(plan['component_footprints'])
        measurements['id'] = digest({k: v for k, v in measurements.items() if k != 'id'})
        for key in ('section_profiles', 'drawing_references'):
            pack = plan[key]
            pack['source_measurements_sha256'] = digest(measurements)
            pack['id'] = digest({k: v for k, v in pack.items() if k != 'id'})
        review = correspondence.review_pages([plan, section])
        self.assertEqual(review['summary']['section_plan_context_pairs'], 0)
        self.assertFalse(review['source_pages'][plan['document_sha256']+':1']['components_complete'])

    def test_marker_work_count_and_output_budgets_withhold_all_partial_candidates(self):
        plan, _, page = self.sources()
        for options in ({'max_checks': 1},):
            result = correspondence.page_references(page, plan['document_sha256'], 1,
                plan['component_measurements'], options=options)
            self.assertFalse(result['analysis_complete'])
            self.assertEqual(result['markers'], [])
        with patch.object(correspondence.glyph_visibility, 'screen_architectural_span',
                return_value={'status': 'raster_consistent_candidate', 'large_receipt': 'x'*17000}):
            result = correspondence.page_references(page, plan['document_sha256'], 1,
                plan['component_measurements'], options={'max_output_bytes': 16384})
            self.assertFalse(result['analysis_complete'])
            self.assertEqual(result['markers'], [])
        page.draw_circle((730, 350), 17)
        page.insert_text((719, 353), '0301', fontsize=8)
        page.insert_text((757, 353), '2', fontsize=8)
        fresh = source(page, floor=True)
        result = correspondence.page_references(page, fresh['document_sha256'], 1,
            fresh['component_measurements'], options={'max_markers': 1})
        self.assertFalse(result['analysis_complete'])
        self.assertEqual(result['markers'], [])

    def test_review_budgets_clear_all_rivals_and_reference_markers(self):
        plan, section, _ = self.sources()
        for options in ({'max_checks': 1}, {'max_output_bytes': 16384}):
            if 'max_output_bytes' in options:
                markers = plan['drawing_references']
                markers['markers'][0]['sheet_number_evidence']['large_receipt'] = 'x'*17000
                markers['id'] = digest({k: v for k, v in markers.items() if k != 'id'})
            review = correspondence.review_pages([plan, section], **options)
            self.assertFalse(review['analysis_complete'])
            self.assertEqual(review['profiles'], [])
            self.assertEqual(review['source_reference_markers'], [])
            self.assertEqual(review['summary']['section_plan_context_pairs'], 0)
        for options in ({'tolerance_m': .251}, {'max_checks': True}, {'max_output_bytes': 16383}):
            with self.assertRaises(ValueError):
                correspondence.review_pages([plan, section], **options)

    def test_cancellation_propagates_and_writer_requires_current_self_hash(self):
        plan, section, page = self.sources()
        with self.assertRaises(CancelledError):
            correspondence.page_references(page, plan['document_sha256'], 1,
                plan['component_measurements'], cancelled=lambda: True)
        with self.assertRaises(CancelledError):
            correspondence.review_pages([plan, section], cancelled=lambda: True)
        review = correspondence.review_pages([plan, section])
        with tempfile.TemporaryDirectory() as tmp:
            correspondence.write_review(tmp, review)
            self.assertIn('Numeric reference indices', (Path(tmp)/'section-correspondence.html').read_text())
            self.assertEqual(digest(json.loads((Path(tmp)/'section-correspondence.json').read_text())), digest(review))
            review['physical_height_m'] = 3
            with self.assertRaises(ValueError):
                correspondence.write_review(tmp, review)

    def test_original_pilot_exports_reference_overlay_and_correspondence_review_with_source_pins(self):
        from voxel_mapper import planning_area_pilot as pilot
        floor, section = fixture()
        self.addCleanup(floor.close)
        self.addCleanup(section.close)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            documents = []
            for name, doc, role in (('floor', floor, 'floor-plan'), ('section', section, 'section')):
                data = doc.tobytes()
                (root/(name+'.pdf')).write_bytes(data)
                documents.append({'file': name+'.pdf', 'sha256': hashlib.sha256(data).hexdigest(),
                    'title': name, 'role': role, 'drawing_state': 'proposed', 'application_reference': 'APP/1'})
            result = pilot.run({'version': pilot.VERSION, 'area_id': 'section-context',
                'application_references': ['APP/1'], 'documents': documents}, lambda p: root/p, root/'output')
            self.assertEqual(result['summary']['section_plan_context_pairs'], 2)
            self.assertEqual(result['summary']['source_sheet_reference_markers'], 1)
            self.assertIn(correspondence.__name__, result['contract']['implementations'])
            self.assertIn('section-correspondence.html', (root/'output/review.html').read_text())
            overlay = (root/'output'/result['pages'][0]['outline_overlay']['file']).read_text()
            self.assertIn('class="sheet_reference"', overlay)
            for name, pin in result['output_sha256'].items():
                self.assertEqual(hashlib.sha256((root/'output'/name).read_bytes()).hexdigest(), pin)


if __name__ == '__main__':
    unittest.main()
