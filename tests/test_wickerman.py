import json
import tempfile
import unittest
from pathlib import Path

from voxel_mapper.wickerman import annotation_evidence, acceptance_report, REQUIREMENTS, report_page_indices, ride_specifications
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
        pages = [Page('cover') for _ in range(23)]
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
