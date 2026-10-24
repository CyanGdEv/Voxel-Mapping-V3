"""Behavior and numerical checks for the source-only global mask decoder."""
from concurrent.futures import CancelledError
import copy
import json
import unittest

import numpy as np

from voxel_mapper import study_context_network as network
from voxel_mapper.building_spec import digest


def outlined_examples():
    """White interiors require filling; a second outline denotes a real hole."""
    images, masks, labels = [], [], []
    for variant in range(6):
        left, top = 2+2*(variant % 3), 3+2*(variant % 2)
        right, bottom = 28-2*(variant % 2), 27-(variant % 3)
        for hole in (False, True):
            source, target = np.zeros((32, 32)), np.zeros((32, 32))
            target[top:bottom, left:right] = 1.
            source[top, left:right] = source[bottom-1, left:right] = 1.
            source[top:bottom, left] = source[top:bottom, right-1] = 1.
            if hole:
                target[12:20, 13:19] = 0.
                source[11:21, 12] = source[11:21, 19] = 1.
                source[11, 12:20] = source[20, 12:20] = 1.
            images.append(source); masks.append(target)
            labels.append('courtyard' if hole else 'panel')
    return np.asarray(images), np.asarray(masks), labels


def resign(value):
    value['id'] = digest({key: item for key, item in value.items() if key != 'id'})
    return value


class StudyContextNetworkTests(unittest.TestCase):
    def test_joint_gradients_reach_global_decoder_local_head_and_both_convolutions(self):
        rng = np.random.default_rng(314)
        source = rng.normal(0., .45, (2, 32, 32))
        masks = rng.uniform(.05, .95, (2, 32, 32))
        prior = rng.uniform(.15, .85, (16, 16))
        parameters = network.initialize(channels=2, classes=2, seed=7, mask_prior=prior)
        options = {'class_weights': np.asarray([.05, .09]),
            'mask_weights': {'positive': 1.7, 'negative': .6},
            'mask_prior': prior, 'regularization': 1e-4}
        targets = np.asarray([0, 1], dtype=np.int64)
        loss, gradients, metrics = network.loss_and_gradients(parameters, source, masks, targets, **options)
        self.assertTrue(np.isfinite(loss))
        self.assertTrue(all(np.isfinite(value) for value in metrics.values()))
        self.assertEqual(set(gradients), set(parameters))
        for key in parameters:
            gradient = gradients[key]
            self.assertEqual(gradient.shape, parameters[key].shape)
            self.assertTrue(np.isfinite(gradient).all(), key)
            self.assertGreater(float(np.abs(gradient).max()), 1e-10, key)
            indices = {np.unravel_index(int(np.abs(gradient).argmax()), gradient.shape),
                tuple(dimension//2 for dimension in gradient.shape)}
            for index in indices:
                original = parameters[key][index]
                epsilon = 1e-5
                parameters[key][index] = original+epsilon
                plus = network.loss_and_gradients(parameters, source, masks, targets, **options)[0]
                parameters[key][index] = original-epsilon
                minus = network.loss_and_gradients(parameters, source, masks, targets, **options)[0]
                parameters[key][index] = original
                numeric = (plus-minus)/(2*epsilon)
                with self.subTest(parameter=key, index=index):
                    np.testing.assert_allclose(gradient[index], numeric, rtol=3e-4, atol=2e-8)

    def test_default_fit_fills_outline_interiors_preserves_holes_and_follows_geometry(self):
        # This fixed synthetic task uses the declared default optimization
        # configuration. It is independent of the retained-study holdout.
        source, target, labels = outlined_examples()
        self.assertGreater(float(np.abs(source-target).mean()), .2)
        fitted = network.fit(source, target, labels)
        classes, predicted = network.infer(fitted, source)
        self.assertEqual(predicted.shape, target.shape)
        self.assertTrue(np.isfinite(predicted).all())
        self.assertTrue(((predicted >= 0.) & (predicted <= 1.)).all())
        np.testing.assert_allclose(classes.sum(axis=1), 1., atol=1e-12)
        # These pixels are blank in both source crops. The inner boundary
        # changes their meaning from filled region to excluded courtyard.
        self.assertEqual(float(source[:, 14:18, 15:17].sum()), 0.)
        self.assertGreater(float(predicted[::2, 14:18, 15:17].mean()), .65)
        self.assertLess(float(predicted[1::2, 14:18, 15:17].mean()), .35)
        # The left edge moves from x=2 to x=6 across the fixture. Shared empty
        # source pixels at x=4 must acquire different filled-region outputs.
        self.assertEqual(float(source[[0, 4], 8:11, 4].sum()), 0.)
        self.assertGreater(float(predicted[0, 8:11, 4].mean()), .6)
        self.assertLess(float(predicted[4, 8:11, 4].mean()), .4)
        self.assertLess(float(np.abs(predicted-target).mean()), .2)
        self.assertLess(fitted['training']['final_mask_loss'], fitted['training']['initial_mask_loss'])
        self.assertTrue(fitted['training']['conv_filters_updated'])

    def test_open_checkpoint_roundtrip_is_exact_and_rejects_hash_shape_and_work_tampering(self):
        source, masks, labels = outlined_examples()
        fitted = network.fit(source[:4], masks[:4], labels[:4], epochs=1)
        decoded = network.decode(json.loads(json.dumps(network.encode(fitted))))
        before, after = network.infer(fitted, source[:2]), network.infer(decoded, source[:2])
        for expected, actual in zip(before, after):
            np.testing.assert_array_equal(expected, actual)
        decoded['classes'][0] = 'changed'
        self.assertNotEqual(decoded['classes'], fitted['classes'])
        for mode in ('hash', 'parameter_shape', 'parameter_bound', 'prior_shape', 'work'):
            invalid = copy.deepcopy(fitted)
            if mode == 'hash':
                invalid['parameters']['context_weights'][0][0] += .01
            elif mode == 'parameter_shape':
                invalid['parameters']['mask_weights'].pop()
            elif mode == 'parameter_bound':
                invalid['parameters']['local_weights'][0] = 101.
            elif mode == 'prior_shape':
                invalid['mask_prior'].pop()
            else:
                invalid['work_estimate']['activation_bytes_upper_bound'] = 0
            if mode != 'hash':
                resign(invalid)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                network.validate(invalid)

    def test_invalid_pixels_supervision_callbacks_and_work_are_bounded_before_training(self):
        source, masks, labels = outlined_examples()
        for mode in ('image_nan', 'image_range', 'mask_range', 'mask_shape', 'label_count', 'epochs', 'channels'):
            images, targets, kinds = source.copy(), masks.copy(), list(labels)
            options = {'epochs': 1}
            if mode == 'image_nan': images[0, 0, 0] = np.nan
            elif mode == 'image_range': images[0, 0, 0] = 1.1
            elif mode == 'mask_range': targets[0, 0, 0] = -.01
            elif mode == 'mask_shape': targets = targets[:, :-1]
            elif mode == 'label_count': kinds.pop()
            elif mode == 'epochs': options['epochs'] = True
            else: options['channels'] = 9
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                network.fit(images, targets, kinds, **options)
        with self.assertRaises(CancelledError):
            network.fit(source, masks, labels, cancelled=lambda: True)
        with self.assertRaises(ValueError):
            network.estimate_work(2049)
        with self.assertRaises(ValueError):
            network.estimate_work(2, input_size=1024)


if __name__ == '__main__':
    unittest.main()
