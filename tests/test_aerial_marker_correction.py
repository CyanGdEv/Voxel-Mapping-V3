from pathlib import Path
import tempfile
import unittest

import numpy as np

from voxel_mapper import aerial_marker_errors as errors
from voxel_mapper import aerial_marker_correction as correction
from voxel_mapper import layered_surface_learning as base


def reference(**values):
    return {'id': 'visible-edge', 'class': 0, 'outside_class': 2,
            'point_xy': [64., 64.], 'normal_xy': [1., 0.],
            'uncertainty_px': 5, **values}


def settings():
    return {'steps': 40, 'batch': 128, 'seed': 137, 'hidden': [32, 16],
            'learning_rate': .01, 'weight_decay': .001, 'cir_dropout': .25,
            'interior_per_class_per_source': 300,
            'boundary_band_half_normal_px': 20, 'boundary_band_half_tangent_px': 3,
            'boundary_unknown_half_width_px': 3}


class MarkerMeasurementTests(unittest.TestCase):
    def test_signed_displacement_and_missing_edges_are_both_counted(self):
        grid = np.full((128, 128), 2, np.uint8)
        grid[:, :74] = 0
        measured = errors.measure(grid, reference())
        self.assertFalse(measured['missing_marker'])
        self.assertAlmostEqual(measured['signed_offset_m'], .76, delta=.04)
        missing = errors.measure(np.zeros_like(grid), reference())
        summary = errors.summarise([measured, missing])
        self.assertEqual(summary['missing_markers'], 1)
        self.assertEqual(summary['coverage'], .5)
        self.assertAlmostEqual(summary['capped_mean_error_m'], (measured['absolute_error_m'] + 3.2) / 2)
        self.assertEqual(missing['reference_uncertainty_m'], .4)

    def test_wrong_direction_edge_does_not_count_as_correct_marker(self):
        grid = np.zeros((128, 128), np.uint8)
        grid[:, :74] = 2
        result = errors.measure(grid, reference())
        self.assertTrue(result['missing_marker'])
        self.assertEqual(result['capped_error_m'], 3.2)
        summary = errors.summarise([result])
        self.assertIsNone(summary['detected_median_absolute_error_m'])
        self.assertEqual(summary['localized_markers'], 0)

    def test_explicit_opposite_surface_must_match_the_probe(self):
        grid = np.full((128, 128), 1, np.uint8)
        grid[:, :64] = 0
        self.assertFalse(errors.measure(grid, reference())['inside_outside_probes_correct'])
        self.assertTrue(errors.measure(grid, reference(outside_class=None))['inside_outside_probes_correct'])

    def test_invalid_normal_and_incomplete_transect_are_rejected(self):
        grid = np.zeros((128, 128), np.uint8)
        for bad in (reference(normal_xy=[0, 0]), reference(normal_xy=[float('nan'), 1]),
                    reference(point_xy=[10, 10]), reference(outside_class=0)):
            with self.assertRaises(ValueError):
                errors.measure(grid, bad)

    def test_source_gradient_is_independent_of_any_model_prediction(self):
        rgb = np.zeros((128, 128, 3), np.uint8)
        rgb[:, 65:] = 220
        r = errors.snap_source_edge(rgb, None, reference(point_xy=[61, 64]))
        self.assertAlmostEqual(r['point_xy'][0], 64.5, delta=1.)
        self.assertEqual(r['guide_point_xy'], [61, 64])
        self.assertFalse(r['independent_human_review'])

    def test_uncertain_band_and_unknown_opposite_side_are_not_labels(self):
        sl, band = errors.reference_band(reference(), (128, 128))
        self.assertEqual(band[64 - sl[0].start, 64 - sl[1].start], 255)
        self.assertEqual(band[64 - sl[0].start, 54 - sl[1].start], 0)
        self.assertEqual(band[64 - sl[0].start, 74 - sl[1].start], 2)
        sl, band = errors.reference_band(reference(outside_class=None), (128, 128))
        self.assertEqual(band[64 - sl[0].start, 74 - sl[1].start], 255)

    def test_guard_excludes_all_pixels_near_check_points(self):
        shape = (256, 256)
        refs = [reference(id='fit', point_xy=[80, 80], role='calibration_fit'),
                reference(id='check', point_xy=[190, 190], role='calibration_check')]
        target = np.zeros(shape, np.uint8)
        feature = np.zeros((*shape, len(correction.FEATURES)), np.float32)
        sample = correction.sample_source(feature, target, refs, target, settings())
        yx = sample['coordinates_yx']
        self.assertTrue((((yx[:, 0] - 190) ** 2 + (yx[:, 1] - 190) ** 2) > 50 ** 2).all())
        self.assertEqual(sample['report']['check_guard_m'], 4.)
        refs[0]['role'] = 'fresh_check'
        with self.assertRaisesRegex(ValueError, 'Fresh-check'):
            correction.sample_source(feature, target, refs, target, settings())


class MarkerCorrectionTests(unittest.TestCase):
    def test_optional_base_probabilities_preserve_existing_predictions(self):
        import torch
        torch.set_num_threads(2)
        torch.manual_seed(3)
        model = base.architecture(3)
        feature = np.random.default_rng(1).random((32, 48, 3), dtype=np.float32)
        before = base.predict(model, feature)
        after = base.predict(model, feature, return_probabilities=True)
        for a, b in zip(before, after[:3]):
            self.assertTrue(np.array_equal(a, b))
        self.assertTrue(np.allclose(after[3].sum(2), 1, atol=1e-6))
        self.assertTrue(np.array_equal(after[0], after[3].argmax(2)))

    def test_zero_initialized_residual_preserves_the_baseline(self):
        shape = (24, 24)
        p = np.random.default_rng(2).random((*shape, 4), dtype=np.float32)
        p /= p.sum(2, keepdims=True)
        rgb = np.zeros((*shape, 3), np.uint8)
        height = np.zeros((*shape, 4), np.float32)
        features = correction.descriptors(rgb, None, height, p)
        self.assertEqual(features.shape[2], 27)
        self.assertFalse(features[:, :, 26].any())
        self.assertFalse(features[:, :, 3:6].any())
        residual = correction.residuals(correction.architecture(), features)
        self.assertFalse(residual.any())
        out = correction.corrected_probabilities(p, residual, rgb, None, 1., 0.)
        self.assertTrue(np.allclose(out, p, atol=1e-6))

    def test_invalid_probabilities_or_nonmatching_source_are_rejected(self):
        p = np.full((16, 16, 4), .25, np.float32)
        with self.assertRaises(ValueError):
            correction.validate_probabilities(p * 2)
        p[0, 0, 0] = float('nan')
        with self.assertRaises(ValueError):
            correction.validate_probabilities(p)
        p[:] = .25
        with self.assertRaises(ValueError):
            correction.descriptors(np.zeros((16, 16, 3), np.uint8), None, np.zeros((15, 16, 4)), p)

    def test_real_fit_learns_colour_and_reloads_exactly(self):
        y = np.tile(np.arange(4, dtype=np.int64), 100)
        x = np.zeros((len(y), 27), np.float32)
        x[:, 10:14] = .25
        x[:, 0] = y / 3
        x[:, 1] = y % 2
        sample = {'x': x, 'y': y, 'weight': np.ones(len(y), np.float32),
                  'report': {'evaluation_only': False}}
        model, training = correction.fit([sample], settings())
        self.assertGreater(training['parameter_change_l2'], 0)
        self.assertLess(training['history'][-1]['loss'], training['history'][0]['loss'])
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'checkpoint'
            correction.save(model, folder, training, {'source': 'pinned'}, {'alpha': 1., 'smoothing': 0.})
            loaded, meta = correction.load(folder)
            a = correction.residuals(model, x.reshape(20, 20, 27))
            b = correction.residuals(loaded, x.reshape(20, 20, 27))
            self.assertTrue(np.array_equal(a, b))
            self.assertFalse(meta['production_eligible'])
            (folder / 'weights.safetensors').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'pinned'):
                correction.load(folder)

    def test_reserved_samples_cannot_fit_or_select(self):
        sample = {'report': {'evaluation_only': True}}
        with self.assertRaises(ValueError):
            correction.fit([sample], settings())
        with self.assertRaisesRegex(ValueError, 'calibration'):
            correction.choose([{'role': 'fresh_check'}], 1.)

    def test_selection_rejects_regression_and_requires_real_boundary_improvement(self):
        rows = [{'role': 'calibration_check', 'alpha': a, 'smoothing': 0.,
                 'macro_iou_delta': delta, 'errors': {'capped_mean_error_m': error}}
                for a, delta, error in [(.25, -.2, .1), (.5, -.01, .3), (.75, .1, 2.)]]
        self.assertEqual(correction.choose(rows, 1.)['alpha'], .5)
        self.assertIsNone(correction.choose(rows, .05))

    def test_source_aware_smoothing_preserves_a_strong_colour_boundary(self):
        rgb = np.zeros((32, 32, 3), np.uint8)
        rgb[:, 16:] = 255
        p = np.full((32, 32, 4), .01, np.float32)
        p[:, :16, 0] = .97
        p[:, 16:, 2] = .97
        q = correction.corrected_probabilities(p, np.zeros_like(p), rgb, None, .5, 1.)
        self.assertTrue(np.array_equal(q.argmax(2), p.argmax(2)))
        self.assertTrue(np.allclose(q.sum(2), 1, atol=1e-6))


if __name__ == '__main__':
    unittest.main()
