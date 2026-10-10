import json
import tempfile
import unittest
from pathlib import Path

from voxel_mapper.wickerman import annotation_evidence, acceptance_report, REQUIREMENTS, report_page_indices, ride_specifications, path_specifications, inspect_drawings
from voxel_mapper.alton_discovery import merge_discovered, document_role


class WickerManTests(unittest.TestCase):
    def test_late_report_page_supplies_ride_specifications_without_as_built_claim(self):
        text = ('proposed ride track has a spot height of 201m AOD. '
                'The ride structure, sound tunnels and screens would be dark\nstained timber.')
        class Page:
            def __init__(self, text):
                self.text = text
            def get_text(self, mode):
                return self.text
        pages = [Page('Path wall materials') for _ in range(23)]
        pages[22] = Page(text)
        indices, budget = report_page_indices(pages)
        self.assertIn(22, indices)
        specifications = ride_specifications(text)
        self.assertEqual(specifications[0]['material'], 'dark_stained_timber')
        self.assertEqual(specifications[1]['printed_level_m'], 201)
        self.assertIsNone(specifications[1]['datum_realization'])
        self.assertFalse(specifications[0]['as_built_verified'])
        indices, budget = report_page_indices(pages, scan_pages=10)
        self.assertNotIn(22, indices)
        self.assertEqual(budget['native_text_pages_unscanned'], 13)

    def test_path_application_is_report_and_late_material_pages_are_selected(self):
        title = '03224 S73 application SW8 path proposals 22-02-17'
        self.assertEqual(document_role(title)[0], 'context-report')
        class Page:
            def __init__(self, text): self.text = text
            def get_text(self, mode): return self.text
        pages = [Page('cover'), Page('intro'), Page('Path materials'),
                 Page('List of Drawings')]
        indices, _ = report_page_indices(pages)
        self.assertEqual(indices, [0, 1, 2, 3])

    def test_scoped_pavement_and_grading_requirements_do_not_invent_palette(self):
        text = ('The path is proposed to be made of pavement blocks to the north of the '
                'DPW (a minimum of 1m away from the DPW). The ground surrounding the '
                'DPW is proposed to be graded down to 1:3 to reveal the wall.')
        specs = path_specifications(text)
        self.assertEqual(specs[0]['minimum_wall_setback_m'], 1)
        self.assertIsNone(specs[0]['block_type'])
        self.assertFalse(specs[0]['geometry_verified'])
        self.assertEqual(specs[1]['slope_horizontal'], 3)
        self.assertEqual(path_specifications('Existing pavement blocks elsewhere'), [])

    def test_late_drawing_pages_are_preserved_with_explicit_budget(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('Optional planning PDF dependency unavailable')
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = fitz.open()
            for index in range(4):
                page = pdf.new_page()
                page.insert_text((30, 30), 'Sound Tunnel' if index == 3 else 'cover')
                page.draw_rect(fitz.Rect(40, 40, 100, 100))
            path = root/'drawing.pdf'
            pdf.save(path)
            pdf.close()
            doc = {'applicationReference': 'SMD/2016/0315', 'title': 'Sections',
                   'url': 'https://example.test/source', 'role': 'elevations',
                   'local_pdf': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            result = inspect_drawings([doc], root)
            row = result['documents'][0]
            self.assertEqual(len(row['pages']), 4)
            self.assertTrue(row['inspection_complete'])
            self.assertEqual(len(row['pages'][3]['categories']['sound_tunnels']), 1)
            self.assertTrue((root/row['pages'][3]['vector_file']).exists())
            row = inspect_drawings([doc], root, max_drawing_pages=3)['documents'][0]
            self.assertFalse(row['inspection_complete'])
            self.assertEqual(row['omitted_pages'], 1)

    def test_track_levels_are_retained_without_datum_or_georegistration_claim(self):
        line = {'text': 'HP1 - 201.0', 'bbox': [1, 2, 3, 4]}
        categories, levels = annotation_evidence([line, {'text': 'Sound Tunnel', 'bbox': [5, 6, 7, 8]}])
        self.assertEqual(levels[0]['printed_level'], 201)
        self.assertIsNone(levels[0]['vertical_datum'])
        self.assertEqual(levels[0]['status'], 'unregistered_annotation')
        self.assertEqual(categories['sound_tunnels'][0]['bbox'], [5, 6, 7, 8])

    def test_annotation_dense_plan_and_exported_baseline_cannot_pass(self):
        categories = {key: [{'text': 'candidate'}] * 100 for key in REQUIREMENTS}
        evidence = {'documents': [{'pages': [{'categories': categories}]}]}
        with tempfile.TemporaryDirectory() as directory:
            voxels = Path(directory)/'voxels.jsonl'
            voxels.write_text(json.dumps({'feature': 'osm/way/1'})+'\n')
            result = acceptance_report(evidence, {'world': {'chunks': 100}}, voxels)
        self.assertEqual(result['status'], 'failed_missing_planning_geometry')
        self.assertTrue(result['baseline_world_exported'])
        self.assertEqual(result['planning_features_with_emitted_blocks'], 0)

    def test_unrendered_or_unaccepted_components_cannot_satisfy_test(self):
        evidence = {'documents': []}
        quality = {'planning_geometry_decisions': [{'id': 'track', 'status': 'accepted_verified_adapter_record'}],
                   'planning_component_checks': [{'category': 'ride_layout', 'feature_id': 'planning/track', 'geometry_check': 'passed'},
                                                 {'category': 'sound_tunnels', 'feature_id': 'planning/fake', 'geometry_check': 'passed'}]}
        with tempfile.TemporaryDirectory() as directory:
            voxels = Path(directory)/'voxels.jsonl'
            voxels.write_text(json.dumps({'feature': 'planning/fake'})+'\n')
            result = acceptance_report(evidence, quality, voxels)
        self.assertTrue(all(c['status'] == 'missing_world_geometry' for c in result['checks']))

    def test_discovery_corrects_cached_roles_without_losing_hash(self):
        recovered = [{'url': 'u', 'role': 'access-plan', 'sha256': 'observed-hash', 'file': 'plan.pdf',
                      'title': '373-95-7B Site Plan Proposed showing Woodland path', 'applicationReference': 'a'}]
        current = {'url': 'u', 'role': 'site-plan', 'state': 'proposed', 'priority': 10, 'discovery_source': 'page'}
        row = merge_discovered(recovered, {'documents': [current]})[0]
        self.assertEqual(row['role'], 'site-plan')
        self.assertEqual(row['sha256'], 'observed-hash')
        self.assertEqual(document_role('2967-21 GF Plan P1 FINAL')[0], 'floor-plan')
        self.assertEqual(document_role('Landscape and Visual Impact Assessment - New Ride Part 1')[0], 'context-report')
