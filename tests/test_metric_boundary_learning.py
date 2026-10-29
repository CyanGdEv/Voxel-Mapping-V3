from pathlib import Path
import json
import tempfile
import unittest

import numpy as np

from voxel_mapper import metric_boundary_learning as metric
from voxel_mapper import aerial_marker_correction as correction
from voxel_mapper.metric_boundary_experiment import validate_split, prepare


def reference(**kw):
    return {'id': 'edge', 'class': 0, 'outside_class': 2, 'point_xy': [64, 64],
            'normal_xy': [1, 0], 'uncertainty_m': .3, **kw}


def settings():
    return {'steps': 40, 'batch': 128, 'seed': 137, 'hidden': [32, 16],
            'learning_rate': .01, 'weight_decay': .001, 'cir_dropout': .25,
            'interior_per_class_per_source': 200, 'boundary_draw_fraction': .35,
            'hard_error_multiplier': 3., 'maximum_training_samples': 120000}


class MetricBoundaryTests(unittest.TestCase):
    def test_same_physical_displacement_at_different_pixel_sampling(self):
        grid = np.full((256, 256), 2, np.uint8)
        grid[:, :100] = 0
        results = []
        for spacing in (.08, .2, .5):
            r = reference(point_xy=[99.5 - 1 / spacing, 128])
            results.append(metric.measure(grid, r, spacing))
        for r in results:
            self.assertAlmostEqual(r['signed_offset_m'], 1., delta=.025)
            self.assertEqual(r['search_cap_m'], 4.)

    def test_missing_edges_use_the_same_metre_penalty(self):
        grid = np.zeros((256, 256), np.uint8)
        for spacing in (.08, .5):
            r = metric.measure(grid, reference(point_xy=[128, 128]), spacing)
            self.assertTrue(r['missing_marker'])
            self.assertEqual(r['capped_error_m'], 4.)
            self.assertAlmostEqual(r['uncertainty_excess_m'], 3.7)
        self.assertEqual(metric.summarise([r])['missing_markers'], 1)

    def test_anisotropic_normal_is_perpendicular_in_physical_space(self):
        _, direction = metric.metric_direction(reference(normal_xy=[1, 1]), (128, 128), [.2, .4])
        physical = direction * np.array([.2, .4])
        tangent = np.array([-.2, .4])
        self.assertAlmostEqual(float(np.dot(physical, tangent)), 0.)
        self.assertAlmostEqual(float(np.linalg.norm(physical)), 1.)

    def test_explicit_opposite_class_and_probe_uncertainty(self):
        grid = np.ones((256, 256), np.uint8)
        grid[:, :128] = 0
        a = metric.measure(grid, reference(point_xy=[127.5, 128]), .2)
        self.assertFalse(a['inside_outside_probes_correct'])
        b = metric.measure(grid, reference(point_xy=[127.5, 128], outside_class=None, uncertainty_m=.8), .2)
        self.assertTrue(b['inside_outside_probes_correct'])
        self.assertFalse(b['probe_evaluable_beyond_reference_uncertainty'])

    def test_uncertainty_excess_does_not_claim_sub_reference_precision(self):
        grid = np.full((256, 256), 2, np.uint8)
        grid[:, :128] = 0
        r = metric.measure(grid, reference(point_xy=[126, 128], uncertainty_m=.4), .2)
        self.assertGreater(r['capped_error_m'], 0)
        self.assertEqual(r['uncertainty_excess_m'], 0)

    def test_unknown_bands_cover_the_recorded_physical_uncertainty(self):
        r = reference(point_xy=[128, 128], uncertainty_m=.4)
        sl, band = metric.reference_band(r, (256, 256), .1)
        self.assertEqual(band[128 - sl[0].start, 130 - sl[1].start], 255)
        self.assertEqual(band[128 - sl[0].start, 120 - sl[1].start], 0)
        self.assertEqual(band[128 - sl[0].start, 136 - sl[1].start], 2)

    def test_check_guard_uses_physical_xy_distances(self):
        r = reference(point_xy=[100, 100], role='calibration_check')
        guard = metric.guard((256, 256), [r], [.2, .4])
        self.assertFalse(guard[100, 119])
        self.assertTrue(guard[100, 121])
        self.assertFalse(guard[109, 100])
        self.assertTrue(guard[111, 100])

    def test_fit_samples_respect_metric_guard_and_fresh_roles(self):
        f = np.zeros((256, 256, 27), np.float32)
        target = np.zeros((256, 256), np.uint8)
        refs = [reference(point_xy=[60, 60], role='calibration_fit'),
                reference(id='check', point_xy=[180, 180], role='calibration_check')]
        s = metric.sample_source(f, target, refs, target, .2, settings())
        yx = s['coordinates_yx']
        self.assertTrue((np.square((yx - [180, 180]) * .2).sum(1) > 16).all())
        refs[0]['role'] = 'fresh_check'
        with self.assertRaisesRegex(ValueError, 'development'):
            metric.sample_source(f, target, refs, target, .2, settings())

    def test_invalid_metric_inputs_or_incomplete_transects_are_rejected(self):
        grid = np.zeros((128, 128), np.uint8)
        for spacing in (0, float('nan'), [-.1, .2]):
            with self.assertRaises(ValueError):
                metric.measure(grid, reference(), spacing)
        with self.assertRaisesRegex(ValueError, 'Complete'):
            metric.measure(grid, reference(point_xy=[4, 64]), .2)
        with self.assertRaisesRegex(ValueError, 'uncertainty'):
            metric.measure(grid, reference(uncertainty_m=None), .2)


class MixedSourceFitTests(unittest.TestCase):
    def test_real_balanced_fit_and_safe_checkpoint_reload(self):
        y = np.tile(np.arange(4, dtype=np.int64), 100)
        x = np.zeros((400, 27), np.float32)
        x[:, 10:14] = .25
        x[:, 0] = y / 3
        x[:, 1] = y % 2
        x[200:, 26] = 1
        samples = []
        for sl in (slice(0, 200), slice(200, 400)):
            samples.append({'x': x[sl], 'y': y[sl], 'weight': np.ones(200, np.float32),
                            'boundary': np.arange(200) % 7 == 0,
                            'report': {'evaluation_only': False}})
        model, training = metric.fit(samples, settings())
        self.assertGreater(training['parameter_change_l2'], 0)
        self.assertLess(training['history'][-1]['loss'], training['history'][0]['loss'])
        self.assertEqual(training['boundary_draws'], round(128 * .35) * 40)
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'model'
            correction.save(model, folder, training, {'sources': 'pinned'}, {'rgb_only': .5, 'rgb_cir': .25})
            loaded, meta = correction.load(folder)
            a = correction.residuals(model, x.reshape(20, 20, 27))
            b = correction.residuals(loaded, x.reshape(20, 20, 27))
            self.assertTrue(np.array_equal(a, b))
            self.assertFalse(meta['production_eligible'])

    def test_fresh_samples_cannot_fit(self):
        with self.assertRaises(ValueError):
            metric.fit([{'report': {'evaluation_only': True}}], settings())

    def test_class_regression_rejects_a_candidate_even_if_macro_improves(self):
        limits = {'maximum_source_macro_iou_regression': .005, 'maximum_source_present_class_iou_regression': .01}
        rows = [{'role': 'calibration_check', 'group': 'rgb_only', 'alpha': alpha,
                 'worst_source_macro_iou_delta': macro, 'worst_source_present_class_iou_delta': cls,
                 'errors': {'uncertainty_excess_mean_m': error, 'capped_mean_error_m': error + .3}}
                for alpha, macro, cls, error in [(0., 0., 0., 1.), (.25, .1, -.2, .1), (.5, .05, -.005, .4)]]
        self.assertEqual(metric.select(rows, 'rgb_only', limits)['alpha'], .5)
        rows[2]['worst_source_macro_iou_delta'] = -.02
        self.assertEqual(metric.select(rows, 'rgb_only', limits)['alpha'], 0.)
        rows[1]['role'] = 'fresh_check'
        with self.assertRaisesRegex(ValueError, 'Fresh'):
            metric.select(rows, 'rgb_only', limits)

    def test_all_records_from_fresh_park_must_stay_excluded(self):
        sources = {'dev': {'site_id': 'UK-a', 'role': 'development'},
                   'new-a': {'site_id': 'UK-b', 'role': 'fresh_check'},
                   'new-b': {'site_id': 'NL-c', 'role': 'fresh_check'}}
        refs = {'dev': [reference(role='calibration_fit')], 'new-a': [], 'new-b': []}
        protocol = {'fresh_sites': {'UK-b': {}, 'NL-c': {}}, 'excluded_consumed_sites': ['old-check'], 'fitting_sources': ['dev']}
        validate_split(sources, refs, protocol)
        sources['new-b']['site_id'] = 'UK-a'
        with self.assertRaisesRegex(ValueError, 'Whole'):
            validate_split(sources, refs, protocol)

    def test_preseal_fresh_prediction_is_blocked_before_source_loading(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, 'seal'):
                prepare({'id': 'new', 'role': 'fresh_check'}, temp, None, None)

    def test_stale_seal_cannot_predict_a_different_fresh_reservation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'sources.json').write_text('{}')
            (root / 'checkpoint-seal.json').write_text(json.dumps({'sources_sha256': 'stale'}))
            with self.assertRaisesRegex(ValueError, 'reservation'):
                prepare({'id': 'new', 'role': 'fresh_check'}, root, None, None)

    def test_no_boundary_checks_cannot_silently_select_settings(self):
        row = {'role': 'calibration_check', 'group': 'rgb_only',
               'errors': {'uncertainty_excess_mean_m': None, 'capped_mean_error_m': None}}
        with self.assertRaisesRegex(ValueError, 'Observed'):
            metric.select([row], 'rgb_only', {})


if __name__ == '__main__':
    unittest.main()
