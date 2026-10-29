import copy
import json
from pathlib import Path
import unittest

import numpy as np

from voxel_mapper import aerial_semantic_network as net
from voxel_mapper.aerial_feature_supervision import extract, filter_ink
from voxel_mapper.desktop_memory import digest
from voxel_mapper.tight_trace_learning import LABELS, VERSION, choose_head, predict_samples, rgb_samples, spatial_split


class TightTraceTests(unittest.TestCase):
    def test_tiled_features_match_unbroken_context_at_tile_edges(self):
        rgb = np.random.default_rng(7).integers(0, 255, (180, 210, 3), dtype=np.uint8)
        xy = np.array([[0, 0], [63, 60], [64, 64], [127, 127], [209, 179]])
        tiled = rgb_samples(rgb, xy, .5, tile_size=64)
        expected = net.features(rgb, .5)[xy[:, 1], xy[:, 0]]
        np.testing.assert_allclose(tiled, expected, atol=1e-6)

    def test_holdout_has_physical_guard_and_both_classes(self):
        en = np.column_stack([np.arange(500), np.zeros(500)])
        labels = np.arange(500) % 2
        train, held, design = spatial_split(en, labels)
        self.assertFalse(np.any(train & held))
        self.assertGreaterEqual(en[held, 0].min()-en[train, 0].max(), 30)
        self.assertTrue(all(np.count_nonzero(mask & (labels == c)) >= 32 for mask in (train, held) for c in (0, 1)))
        self.assertEqual(design['guard_each_side_m'], 15)

    def test_default_feature_count_keeps_existing_fit_exact(self):
        x = np.random.default_rng(3).normal(size=(64, 31)).astype(np.float32); y = np.arange(64) % 2
        settings = {'hidden': 8, 'epochs': 2, 'batch_size': 32}
        self.assertEqual(net.fit(x, y, settings, class_count=2), net.fit(x, y, settings, class_count=2, feature_count=31))

    def test_height_feature_checkpoint_has_distinct_validated_dimensions(self):
        x = np.random.default_rng(3).normal(size=(64, 37)).astype(np.float32); y = np.arange(64) % 2
        fit = net.fit(x, y, {'hidden': 8, 'epochs': 2, 'batch_size': 32}, class_count=2, feature_count=37)
        model = {'version': VERSION, 'labels': LABELS, 'feature_count': 37, 'network': fit, 'production_eligible': False}
        model['artifact_sha256'] = digest(model)
        probability = predict_samples(x, model)
        self.assertEqual(probability.shape, (64, 2))
        np.testing.assert_allclose(probability.sum(axis=1), 1, atol=1e-6)
        with self.assertRaises(ValueError): predict_samples(x[:, :31], model)
        broken = copy.deepcopy(model); broken['network']['parameters']['b1'][0] += 1
        with self.assertRaisesRegex(ValueError, 'checksum'): predict_samples(x, broken)

    def test_clean_colour_filter_rejects_natural_red_but_keeps_new_light_ink(self):
        clean = np.full((60, 80, 3), (150, 145, 135), np.uint8)
        clean[10:14, 10:14] = (230, 60, 60)
        reference = clean.copy(); reference[35:38, 50:53] = (240, 125, 135)
        labels = np.full((60, 80), 255, np.uint8); labels[10:14, 10:14] = 11; labels[35:38, 50:53] = 11
        filtered, review = filter_ink(reference, clean, [[1, 0, 0], [0, 1, 0]], labels, {'min_rms': 18, 'neighbourhood_radius_px': 2})
        self.assertEqual(filtered[11, 11], 255)
        self.assertEqual(filtered[36, 51], 11)
        self.assertEqual(review['natural_colour_candidates_rejected'], 16)

    def test_light_red_and_red_share_paving_class_with_generic_purple_structure(self):
        definition = json.loads((Path(__file__).resolve().parents[1]/'voxel_mapper/data/tight-path-paving-aerial-legend.json').read_text())
        rgb = np.full((40, 60, 3), 70, np.uint8)
        rgb[5:8, 5:8] = (240, 35, 40); rgb[15:18, 15:18] = (240, 125, 135); rgb[25:28, 25:28] = (170, 25, 195)
        labels, _ = extract(rgb, definition)
        self.assertEqual(labels[6, 6], 11); self.assertEqual(labels[16, 16], 11); self.assertEqual(labels[26, 26], 10)
        self.assertEqual(labels[0, 0], 255)

    def test_broad_natural_colour_blob_is_not_a_thin_guide(self):
        definition = json.loads((Path(__file__).resolve().parents[1]/'voxel_mapper/data/tight-path-paving-aerial-legend.json').read_text())
        rgb = np.full((60, 80, 3), 70, np.uint8)
        rgb[5:30, 5:30] = (240, 35, 40); rgb[40:43, 5:55] = (240, 35, 40)
        labels, _ = extract(rgb, definition)
        self.assertEqual(labels[15, 15], 255); self.assertEqual(labels[41, 20], 11)

    def test_overall_gain_cannot_hide_a_canopy_regression(self):
        def score(value): return {'macro_f1': value, 'classes': [{'samples': 100, 'recall': value}, {'samples': 100, 'recall': value}]}
        scores = {'rgb': {'all_held_guides': score(.6), 'raised_or_canopy_context_held_guides': score(.5)},
                  'rgb_height': {'all_held_guides': score(.7), 'raised_or_canopy_context_held_guides': score(.4)}}
        selected, reason = choose_head(scores)
        self.assertEqual(selected, 'rgb'); self.assertIn('canopy', reason)
        scores['rgb_height']['raised_or_canopy_context_held_guides'] = score(.6)
        self.assertEqual(choose_head(scores)[0], 'rgb_height')


if __name__ == '__main__': unittest.main()
