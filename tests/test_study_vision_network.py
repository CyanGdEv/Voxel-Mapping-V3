"""Independent derivatives and observable joint learning for the CPU CNN."""
from concurrent.futures import CancelledError
import copy
import json
import unittest

import numpy as np

from voxel_mapper import study_vision_network as network
from voxel_mapper.building_spec import digest


def references():
    """Even-grid shapes admit exact masks through the two-pixel decoder."""
    pixels, masks, kinds = [], [], []
    for index in range(8):
        image = np.zeros((32, 32), dtype=np.float64)
        shift = 2 * (index // 2 % 2)
        if index % 2 == 0:
            image[4:28, 10 + shift:20 + shift] = 1.
            kind = 'vertical'
        else:
            image[10 + shift:20 + shift, 4:28] = 1.
            kind = 'horizontal'
        pixels.append(image)
        masks.append(image.copy())
        kinds.append(kind)
    return np.asarray(pixels), np.asarray(masks), kinds


class StudyVisionNetworkTests(unittest.TestCase):
    def test_backpropagation_matches_independent_central_differences(self):
        random = np.random.default_rng(91)
        x = random.normal(0., .35, size=(2, 32, 32))
        masks = np.zeros((2, 32, 32), dtype=np.float64)
        masks[0, 4:14, 6:18] = 1.
        masks[1, 16:28, 12:24] = 1.
        # A hole checks that negative interior pixels contribute to the mask loss.
        masks[0, 6:10, 8:14] = 0.
        targets = np.asarray([0, 1], dtype=np.int64)
        parameters = network.initialize(input_size=32, channels=2, classes=2, seed=7)
        arguments = {'class_weights': np.ones(2), 'mask_weights': {'positive': 1., 'negative': 1.}}
        loss, gradients, _ = network.loss_and_gradients(parameters, x, masks, targets, **arguments)
        self.assertTrue(np.isfinite(loss))
        self.assertEqual(set(gradients), set(parameters))
        probes = {
            'conv1_weights': [(0, 1, 0, 0), (2, 2, 0, 1)],
            'conv1_bias': [(0,), (1,)],
            'conv2_weights': [(0, 2, 0, 1), (1, 1, 1, 0)],
            'conv2_bias': [(1,)],
            'class_weights': [(0, 0), (17, 1)],
            'class_bias': [(0,)],
            'mask_weights': [(1,)],
            'mask_bias': [()],
        }
        epsilon = 1e-5
        for name, indices in probes.items():
            for index in indices:
                with self.subTest(parameter=name, index=index):
                    high = {key: np.asarray(value, dtype=np.float64).copy() for key, value in parameters.items()}
                    low = {key: np.asarray(value, dtype=np.float64).copy() for key, value in parameters.items()}
                    high[name][index] += epsilon
                    low[name][index] -= epsilon
                    plus = network.loss_and_gradients(high, x, masks, targets, **arguments)[0]
                    minus = network.loss_and_gradients(low, x, masks, targets, **arguments)[0]
                    numerical = (plus - minus) / (2 * epsilon)
                    analytic = np.asarray(gradients[name])[index]
                    self.assertAlmostEqual(float(analytic), float(numerical), delta=2e-6 + abs(numerical) * 2e-4)
        self.assertGreater(np.linalg.norm(gradients['conv1_weights']), 1e-6)
        self.assertGreater(np.linalg.norm(gradients['conv2_weights']), 1e-6)

    def test_saturated_wrong_class_keeps_true_cross_entropy_and_gradient(self):
        x = np.zeros((2, 32, 32), dtype=np.float64)
        masks = np.zeros_like(x)
        masks[:, 8:24, 8:24] = 1.
        targets = np.ones(2, dtype=np.int64)
        parameters = network.initialize(input_size=32, channels=2, classes=2, seed=5)
        parameters['class_weights'][:] = 0.
        parameters['class_bias'][:] = [80., -80.]
        loss, gradients, metrics = network.loss_and_gradients(parameters, x, masks, targets)
        self.assertAlmostEqual(metrics['class_loss'], 160., places=10)
        self.assertGreater(loss, 160.)
        epsilon = 1e-5
        high = {key: np.asarray(value).copy() for key, value in parameters.items()}
        low = {key: np.asarray(value).copy() for key, value in parameters.items()}
        high['class_bias'][1] += epsilon
        low['class_bias'][1] -= epsilon
        plus = network.loss_and_gradients(high, x, masks, targets)[0]
        minus = network.loss_and_gradients(low, x, masks, targets)[0]
        numerical = (plus - minus) / (2 * epsilon)
        self.assertAlmostEqual(float(gradients['class_bias'][1]), -1., places=12)
        self.assertAlmostEqual(float(numerical), -1., places=7)

    def test_actual_joint_learning_reconstructs_known_masks_and_classes(self):
        x, masks, kinds = references()
        model = network.fit(x, masks, kinds, epochs=65, channels=4, seed=3, batch_size=4)
        probabilities, predicted_masks = network.infer(model, x)
        classes = model['classes']
        predicted = [classes[index] for index in np.argmax(probabilities, axis=1)]
        self.assertEqual(predicted, kinds)
        np.testing.assert_allclose(probabilities.sum(axis=1), 1., atol=1e-10)
        self.assertTrue(np.isfinite(predicted_masks).all())
        binary = predicted_masks >= .5
        truth = masks >= .5
        iou = np.logical_and(binary, truth).sum(axis=(1, 2)) / np.logical_or(binary, truth).sum(axis=(1, 2))
        self.assertGreater(float(iou.min()), .85)
        self.assertGreater(float(predicted_masks[truth].mean()), .8)
        self.assertLess(float(predicted_masks[~truth].mean()), .2)
        # This is a local CNN, so distinct pixels in one crop must receive distinct scores.
        self.assertGreater(float(predicted_masks[0, 12, 14] - predicted_masks[0, 0, 0]), .7)
        restored = network.decode(json.loads(json.dumps(network.encode(model), allow_nan=False)))
        restored_classes, restored_masks = network.infer(restored, x)
        np.testing.assert_array_equal(restored_classes, probabilities)
        np.testing.assert_array_equal(restored_masks, predicted_masks)
        for mode in ('stale_parameter', 'parameter_shape', 'parameter_bound', 'architecture', 'production'):
            invalid = copy.deepcopy(model)
            if mode == 'stale_parameter':
                invalid['parameters']['conv1_weights'][0][0][0][0] += .1
            elif mode == 'parameter_shape':
                invalid['parameters']['conv2_weights'][0][0].append([0.] * 4)
            elif mode == 'parameter_bound':
                invalid['parameters']['mask_bias'] = 101.
            elif mode == 'architecture':
                invalid['architecture']['input_size'] = 1024
            else:
                invalid['production_eligible'] = True
            if mode != 'stale_parameter':
                invalid['id'] = digest({k: v for k, v in invalid.items() if k != 'id'})
            with self.subTest(checkpoint=mode), self.assertRaises(ValueError):
                network.validate(invalid)

    def test_invalid_domains_are_rejected_and_cancellation_stops_fitting(self):
        x, masks, kinds = references()
        invalid = [('nonfinite', x.copy(), masks.copy()), ('ink_range', x.copy(), masks.copy()),
            ('mask_range', x.copy(), masks.copy()), ('shape', x.copy(), masks[:, :, :-1].copy())]
        invalid[0][1][0, 0, 0] = np.nan
        invalid[1][1][0, 0, 0] = 1.5
        invalid[2][2][0, 0, 0] = -.1
        for name, images, targets in invalid:
            with self.subTest(name=name), self.assertRaises(ValueError):
                network.fit(images, targets, kinds, epochs=1, channels=4)
        parameters = network.initialize(input_size=32, channels=4, classes=2)
        parameters['conv1_weights'] = np.full((3, 3, 1, 4), np.iinfo(np.int64).min, dtype=np.int64)
        with self.assertRaises(ValueError):
            network.loss_and_gradients(parameters, x[:1], masks[:1], np.asarray([0], dtype=np.int64))
        with self.assertRaises(CancelledError):
            network.fit(x, masks, kinds, epochs=2, channels=4, cancelled=lambda: True)
        stopped = False
        def progress(value):
            nonlocal stopped
            if 'epoch' in value:
                stopped = True
        with self.assertRaises(CancelledError):
            network.fit(x, masks, kinds, epochs=3, channels=4,
                cancelled=lambda: stopped, progress=progress)
        self.assertTrue(stopped)


if __name__ == '__main__':
    unittest.main()
