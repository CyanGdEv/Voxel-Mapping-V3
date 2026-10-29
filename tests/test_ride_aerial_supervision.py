import unittest
from unittest.mock import Mock

import numpy as np
import cv2

from voxel_mapper.ride_aerial_supervision import LEGEND, crossing_candidates, extract, project_pixels, register


class RideAerialSupervisionTests(unittest.TestCase):
    def reference(self):
        rgb = np.full((64, 64, 3), (70, 90, 60), np.uint8)
        rgb[5:55, 16:19] = (255, 215, 0)
        rgb[30:33, 5:60] = (235, 10, 240)
        return rgb

    def test_explicit_image_legend_and_positive_only_labels(self):
        labels, summary = extract(self.reference(), LEGEND)
        self.assertEqual(labels[5, 16], 1)
        self.assertEqual(labels[30, 5], 2)
        self.assertEqual(labels[0, 0], 255)
        self.assertEqual(set(np.unique(labels)), {1, 2, 255})
        self.assertGreater(summary['monorail']['annotated_pixels'], 100)

    def test_purple_building_legend_cannot_be_silently_reused(self):
        with self.assertRaises(ValueError):
            extract(self.reference(), {'yellow': 'monorail', 'purple': 'building_boundary'})

    def test_single_jpeg_specks_are_not_trace_targets(self):
        rgb = self.reference(); rgb[1, 1] = (255, 215, 0)
        labels, summary = extract(rgb, LEGEND)
        self.assertEqual(labels[1, 1], 255)
        self.assertEqual(summary['monorail']['isolated_single_pixels_rejected'], 1)

    def test_projected_crossing_is_not_a_connected_junction_or_height(self):
        labels, _ = extract(self.reference(), LEGEND)
        crossings = crossing_candidates(labels)
        self.assertEqual(len(crossings), 1)
        self.assertFalse(crossings[0]['connected'])
        self.assertIsNone(crossings[0]['height_odn_m'])
        self.assertEqual(crossings[0]['height_order'], 'unresolved')

    def test_one_class_cannot_create_an_image_edge_crossing(self):
        labels = np.full((32, 32), 255, np.uint8); labels[1, 1:20] = 2
        self.assertEqual(crossing_candidates(labels), [])

    def test_pixel_centres_use_true_extent_and_north_up_rows(self):
        project = Mock(); project.transform.side_effect = lambda x, y: (x, y)
        # Mercator origin projects to longitude/latitude zero.
        points = project_pixels([[.5, .5]], (2, 2), [-100, -100, 100, 100], project)
        np.testing.assert_allclose(points[0], [0, 0], atol=1e-10)

    def test_registration_recovers_rotated_clean_texture_without_user_ink(self):
        rng = np.random.default_rng(41)
        grey = rng.integers(15, 235, (256, 256), dtype=np.uint8)
        base = np.repeat(grey[:, :, None], 3, axis=2)
        expected = np.array([[0., -1., 290.], [1., 0., 25.]])
        clean = cv2.warpAffine(base, expected, (320, 320))
        reference = base.copy()
        reference[30:180, 70:74] = (255, 215, 0)
        reference[120:124, 30:220] = (235, 10, 240)
        labels, _ = extract(reference, LEGEND)
        matrix, review = register(reference, clean, labels)
        # SIFT localisation can move by a half pixel under a quarter turn.
        np.testing.assert_allclose(matrix, expected, atol=.75)
        self.assertGreater(review['inliers'], 24)
        self.assertFalse(review['physical_registration_verified'])


if __name__ == '__main__': unittest.main()
