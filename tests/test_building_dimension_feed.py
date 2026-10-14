"""Synthetic dimension evidence never qualifies real geometry or learning labels."""
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shapely.geometry import box, mapping

from voxel_mapper.building_dimension_feed import compare, prepare, VERSION
from tests import test_building_plan_audit as plan_fixture
from tests import test_building_facade_feed as facade_fixture


class DimensionFeedTests(unittest.TestCase):
    def inputs(self):
        candidate = {'id': 'candidate-a', 'boundary_gap_ids': [], 'dimension_review': {
            'raw_nominal_extent_dimensions_m': [10, 5],
            'inverse_layout_extent_candidates_m': [11, 5.5]}}
        hypotheses = {'status': 'mixed_source_enclosure_hypotheses_only',
                      'document_sha256': 'a'*64, 'page': 1, 'candidates': [candidate]}
        region = {'id': 'region-a', 'coordinate_frame': 'pdf_native_points_y_up',
                  'display_geometry': mapping(box(0, 0, 100, 20)),
                  'nominal_metres_per_pdf_point_candidate': .1,
                  'source_record_sha256': 'b'*64, 'document_sha256': 'c'*64,
                  'page': 2, 'view_key_candidate': ['2967', 26, 1],
                  'component_class_candidate': 'wall_face'}
        return hypotheses, [region]

    def test_all_channels_matches_and_conflicts_keep_exact_sources_without_selection(self):
        hypotheses, regions = self.inputs(); before = copy.deepcopy((hypotheses, regions))
        report = compare(hypotheses, regions)
        self.assertEqual(len(report['comparisons']), 4)
        self.assertEqual([r['status'] for r in report['comparisons']].count('within_diagnostic_window'), 1)
        raw = report['comparisons'][0]
        self.assertEqual(raw['region_width_m'], 10)
        self.assertEqual(raw['plan_document_sha256'], 'a'*64)
        self.assertEqual(raw['elevation_page'], 2)
        self.assertFalse(raw['physical_correspondence_verified'])
        self.assertEqual((hypotheses, regions), before)
        self.assertIsNone(report['selected_physical_footprint_id'])
        self.assertEqual(report['training_labels_generated'], 0)
        self.assertEqual(report, compare(hypotheses, regions))

    def test_competing_candidates_regions_and_gap_dependencies_remain_explicit(self):
        hypotheses, regions = self.inputs()
        alternative = copy.deepcopy(hypotheses['candidates'][0])
        alternative.update(id='candidate-b', boundary_gap_ids=['gap-1'])
        hypotheses['candidates'].append(alternative)
        regions.append({**regions[0], 'id': 'region-b', 'component_class_candidate': 'roof_surface'})
        report = compare(hypotheses, regions)
        self.assertEqual(len(report['comparisons']), 16)
        matches = [r for r in report['comparisons'] if r['status'] == 'within_diagnostic_window']
        self.assertEqual(len(matches), 4)
        self.assertEqual(matches[-1]['candidate_boundary_gap_ids'], ['gap-1'])
        self.assertEqual(matches[-1]['component_class_candidate'], 'roof_surface')
        self.assertIsNone(report['selected_physical_footprint_id'])
        reordered = copy.deepcopy(hypotheses); reordered['candidates'].reverse()
        self.assertEqual(report['comparisons'], compare(reordered, list(reversed(regions)))['comparisons'])

    def test_budget_discards_partial_comparisons_and_missing_scale_stays_missing(self):
        hypotheses, regions = self.inputs()
        report = compare(hypotheses, regions, options={'max_comparisons': 1})
        self.assertEqual(report['status'], 'withheld_comparison_budget')
        self.assertEqual(report['comparisons'], [])
        hypotheses['candidates'][0].pop('dimension_review')
        self.assertEqual(compare(hypotheses, regions)['comparisons'], [])
        hypotheses['status'] = 'hypothesis_budget_withheld'
        self.assertEqual(compare(hypotheses, regions)['status'], 'withheld_incomplete_footprint_hypotheses')

    def test_invalid_scale_geometry_identity_and_options_are_rejected(self):
        for mutate in [lambda h,r:r.append(copy.deepcopy(r[0])),
                       lambda h,r:h['candidates'].append(copy.deepcopy(h['candidates'][0])),
                       lambda h,r:r[0].update(nominal_metres_per_pdf_point_candidate=float('nan')),
                       lambda h,r:r[0].update(coordinate_frame='pixels'),
                       lambda h,r:r[0].update(display_geometry=mapping(box(0,0,0,0))),
                       lambda h,r:h['candidates'][0]['dimension_review'].update(raw_nominal_extent_dimensions_m=[float('nan'),1])]:
            h,r = self.inputs(); mutate(h,r)
            with self.assertRaises(ValueError): compare(h,r)
        for options in [{'tolerance_m': 1}, {'max_comparisons': True}, {'unknown': 1}]:
            with self.assertRaises(ValueError): compare(*self.inputs(), options=options)

    def request(self, root):
        audit = plan_fixture.PlanAuditTests().sources(root)
        sha, feed = facade_fixture.FacadeFeedTests().source(root)
        return sha, {'version': VERSION,
                     'footprint': {'version': 'source-footprint-hypotheses-v1', 'plan_audit': audit},
                     'facade_feed': feed}

    def test_cli_recomputes_source_feeds_ignores_manual_widths_and_preserves_failure_gate(self):
        from voxel_mapper.building_pipeline import main
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); sha, config = self.request(root)
            (root/'request.json').write_text(json.dumps(config))
            before = copy.deepcopy(config)
            fixture = facade_fixture.FacadeFeedTests()
            with patch('voxel_mapper.building_facade_feed.drawing_faces.run', side_effect=fixture.fake_faces(sha)), \
                 patch('voxel_mapper.building_facade_feed.plan_elevation_edges.run', return_value={'results': []}):
                with redirect_stdout(io.StringIO()):
                    main(['compare-source-dimensions', '--config', str(root/'request.json'), '--output', str(root/'out')])
                again = prepare(config, lambda p: root/p, root/'again')
            report = json.loads((root/'out/comparisons.json').read_text())
            self.assertTrue(report['comparisons'])
            self.assertEqual(report, again)
            self.assertFalse(report['manual_width_targets_used'])
            self.assertEqual(report['park_world_blocks_added'], 0)
            self.assertEqual(config, before)
            queue = json.loads((root/'out/review-queue.json').read_text())
            self.assertIsNone(queue['outcome'])
            self.assertEqual(len(queue['original_source_sha256']), 3)
            with self.assertRaises(ValueError): prepare(config, lambda p: root/p, root/'out')
            (root/'plan.pdf').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'checksum'): prepare(config, lambda p: root/p, root/'changed')
            self.assertFalse((root/'changed').exists())

    def test_changed_original_after_comparison_prevents_final_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); sha,config=self.request(root); fixture=facade_fixture.FacadeFeedTests()
            real_compare=compare
            def mutate(*args, **kwargs):
                report=real_compare(*args, **kwargs)
                (root/'source.pdf').write_bytes(b'changed')
                return report
            with patch('voxel_mapper.building_facade_feed.drawing_faces.run', side_effect=fixture.fake_faces(sha)), \
                 patch('voxel_mapper.building_facade_feed.plan_elevation_edges.run', return_value={'results': []}), \
                 patch('voxel_mapper.building_dimension_feed.compare', side_effect=mutate):
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    prepare(config, lambda p: root/p, root/'out')
            self.assertFalse((root/'out').exists())
            self.assertTrue((root/'out.partial').exists())
