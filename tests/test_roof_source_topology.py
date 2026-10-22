import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from voxel_mapper import roof_source_topology as topology
from voxel_mapper import source_gradient_gables as gradient
from voxel_mapper.generation_cycles import atomic_json
from tests import test_source_gradient_gables as parent_tests


class RoofSourceTopologyTests(unittest.TestCase):
    def inventory(self, tails=5.):
        segments = [('r', [[50., 0.], [50., 100.]]),
            ('a', [[0., 0.], [0., 100. + tails]]), ('b', [[100., 100. + tails], [100., 0.]]),
            ('c', [[0., 0.], [50., 0.]]), ('d', [[50., 0.], [100., 0.]]),
            ('e', [[0., 100.], [100., 100.]])]
        return {'view_id': 'roof', 'document_sha256': 'pdf', 'page': 1,
            'nominal_metres_per_pdf_point': .1, 'source_components': [
                {'id': key, 'geometry': {'type': 'LineString', 'coordinates': points},
                    'rendering_status': 'supported_straight_unclipped_polyline',
                    'curve_approximation': {'cubic_segments': 0}} for key, points in segments]}

    def target(self, inventory):
        result = topology.connected_candidates(inventory, lambda: None)
        return next(c for c in result['candidates'] if c['ridge_source_id'] == 'r')

    def fixture(self, root):
        args = parent_tests.SourceGradientTests().fixture(root)
        result = gradient.build(*args)
        return (Path(result['directory']), *args[:-1], root / 'topology')

    def test_half_and_whole_caps_preserve_original_tails_and_input(self):
        inv = self.inventory(); before = copy.deepcopy(inv); row = self.target(inv)
        self.assertEqual(inv, before)
        self.assertEqual(row['nominal_ridge_length_m'], 10.)
        self.assertEqual(row['nominal_rail_lengths_m'], [10.5, 10.5])
        self.assertTrue(all(t['nominal_source_tails_m'] == [0., .5] for t in row['source_rail_tails']))
        self.assertIsNone(row['complete_roof_mesh']); self.assertFalse(row['physical_roof_roles_verified'])
        self.assertEqual(len(row['source_junctions']), 2)

    def test_near_junction_is_measured_without_snapping_and_large_gap_fails(self):
        inv = self.inventory(); inv['source_components'][3]['geometry']['coordinates'][0][0] = .2
        row = self.target(inv)
        self.assertAlmostEqual(max(a['cap_to_rail_gap_pdf_points'] for j in row['source_junctions']
            for r in j['rail_contacts'] for a in r['alternatives']), .2)
        inv['source_components'][3]['geometry']['coordinates'][0][0] = .3
        with self.assertRaises(StopIteration): self.target(inv)

    def test_missing_unrelated_or_curved_cap_cannot_close_template(self):
        for mode in ('missing', 'shifted', 'curved'):
            inv = self.inventory()
            if mode == 'missing': inv['source_components'].pop()
            elif mode == 'shifted': inv['source_components'][-1]['geometry']['coordinates'] = [[0., 110.], [100., 110.]]
            else: inv['source_components'][-1]['curve_approximation']['cubic_segments'] = 1
            with self.assertRaises(StopIteration): self.target(inv)

    def test_native_identity_order_and_competing_hatching_are_retained(self):
        inv = self.inventory(0.)
        inv['source_components'][3]['geometry']['coordinates'] = [[0., 0.], [100., 0.]]
        alternate = copy.deepcopy(inv['source_components'][0]); alternate['id'] = 'competing-hatch'
        alternate['geometry']['coordinates'] = [[51., 0.], [51., 100.]]
        inv['source_components'].append(alternate)
        original = topology.connected_candidates(inv, lambda: None)
        inv['source_components'].reverse()
        self.assertEqual(original, topology.connected_candidates(inv, lambda: None))
        self.assertGreater(len(original['candidates']), 1)
        self.assertTrue(all(c['near_balanced_gable_template_assumed'] for c in original['candidates']))

    def test_invalid_units_duplicate_ids_and_component_bounds(self):
        for scale in (0., float('nan'), -1.):
            inv = self.inventory(); inv['nominal_metres_per_pdf_point'] = scale
            with self.assertRaises(ValueError): topology.connected_candidates(inv, lambda: None)
        inv = self.inventory(); inv['source_components'].append(inv['source_components'][0])
        with self.assertRaises(ValueError): topology.connected_candidates(inv, lambda: None)
        inv['source_components'] *= 600
        with self.assertRaises(OverflowError): topology.connected_candidates(inv, lambda: None)

    def test_relative_positions_keep_both_signs_end_anchors_and_all_failures(self):
        inv = self.inventory(); top = topology.connected_candidates(inv, lambda: None)
        pair = {'id': 'pair', 'status': 'conditional_partial_gable_source_support', 'inferred_ridge_pixel': [50., 20.]}
        source = {'projection_contexts': [{'id': 'context', 'roof_view_id': 'roof', 'elevation_view_id': 'elevation',
            'source_view_horizontal_axis_in_roof_pdf': [1., 0.]}], 'views': [{'view_id': 'elevation',
            'variants': [{'anchor_reviews': [{'pairs': [pair]}]}]}]}
        gable = {'plan_reviews': [{'source_view_id': 'roof', 'source_axis_pdf_native': [1., 0.],
            'lines': [{'source_component_id': 'original-anchor', 'along_interval_nominal_m': [0., 10.]}]}]}
        profile = {'profiles': [{'view_id': 'elevation', 'nominal_metres_per_source_pixel': .1,
            'variants': [{'threshold': v, 'source_upper_span_pixels': [0, 120]} for v in (220, 235)]}]}
        result = topology.relative_positions([top], source, gable, profile, lambda: None)
        self.assertEqual(len(result), len(top['candidates']) * 8)
        self.assertEqual({c['source_axis_sign_hypothesis'] for c in result}, {1, -1})
        self.assertEqual({c['status'] for c in result}, {'relative_source_position_agrees', 'relative_source_position_disagrees'})
        self.assertTrue(all(c['profile_thresholds_with_identical_original_span'] == [220, 235] for c in result))
        pair['status'] = 'partial_gable_source_check_held'
        self.assertEqual(topology.relative_positions([top], source, gable, profile, lambda: None), [])

    def test_complete_replay_preserves_parent_and_physical_holds(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.fixture(Path(temp)); before = (args[0] / 'source-gradient-gables.json').read_bytes()
            result = topology.build(*args)
            self.assertEqual(result, topology.build(*args))
            self.assertEqual(before, (args[0] / 'source-gradient-gables.json').read_bytes())
            self.assertEqual(result['new_roof_models'], []); self.assertEqual(result['world_blocks'], 0)
            self.assertFalse(result['prior_source_holds_overridden'])

    def test_early_and_late_overflow_discard_all_partial_results(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.fixture(Path(temp)); result = topology.build(*args, max_checks=1)
            self.assertEqual(result['status'], 'roof_source_topology_budget_withheld')
            with patch.object(topology, 'relative_positions', side_effect=OverflowError('late')):
                result = topology.build(*args)
            self.assertEqual(result['topologies'], []); self.assertEqual(result['position_checks'], [])
        for bad in (0, True, 100001):
            with self.assertRaises(ValueError): topology.build(*([''] * 9), max_checks=bad)

    def test_parent_and_cached_tampering_are_rejected(self):
        for mode in ('parent', 'cache'):
            with tempfile.TemporaryDirectory() as temp:
                args = self.fixture(Path(temp))
                if mode == 'parent':
                    path = args[0] / 'source-gradient-gables.json'; data = json.loads(path.read_text())
                    data['projection_contexts'] = ['tampered']; atomic_json(path, data)
                else:
                    result = topology.build(*args); atomic_json(Path(result['directory']) / 'roof-source-topology.json', {})
                with self.assertRaises(ValueError): topology.build(*args)

    def test_independent_original_source_audit(self):
        from scripts.audit_roof_source_topology import audit
        with tempfile.TemporaryDirectory() as temp:
            args = self.fixture(Path(temp)); result = topology.build(*args)
            checked = audit(result['directory'], *args[:-1], Path(temp) / 'audit.json')
            self.assertEqual(checked['status'], 'passed')
            self.assertGreater(checked['checked']['original_pdf_strokes'], 0)

    def test_parent_change_during_position_pass_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.fixture(Path(temp)); original = topology.relative_positions
            def changed(*values):
                result = original(*values)
                path = args[3] / 'facade-profile.json'
                path.write_text(path.read_text() + '\n')
                return result
            with patch.object(topology, 'relative_positions', side_effect=changed):
                with self.assertRaisesRegex(ValueError, 'during build'): topology.build(*args)
