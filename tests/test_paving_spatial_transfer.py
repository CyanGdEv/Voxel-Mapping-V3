import copy
import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from voxel_mapper import paving_masks as masks, paving_binary_learning as binary
from voxel_mapper import paving_spatial_transfer as spatial, imagery_capture_quality as quality
from voxel_mapper.generation_cycles import atomic_json, file_hash
from test_paving_binary_learning import fixture


class FakeEncoder:
    def __init__(self, directory): pass
    def features(self, original, crop, cache, *, cancelled=lambda: False):
        with Image.open(original) as image: rgb = np.asarray(image.convert('RGB').crop(crop))
        values = np.zeros((*rgb.shape[:2], 31), np.float32); values[:, :, :3] = rgb/255
        return values


class SpatialPavingTests(unittest.TestCase):
    def test_sampling_density_is_not_intrinsic_detail_or_whole_image_date(self):
        receipt = {'width': 512, 'height': 512, 'extent_epsg3857': [0., 0., 128., 128.],
            'point_source_metadata': [{'RESOLUTION (M)': '.5', 'DATE (YYYYMMDD)': '20250502', 'SOURCE': 'Fixture'}]}
        a = quality.audit(receipt); b = quality.audit({**receipt, 'width': 1024, 'height': 1024})
        self.assertTrue(a['export_finer_than_reported_point_source'])
        self.assertLess(b['approx_export_ground_sampling_m_xy'][0], a['approx_export_ground_sampling_m_xy'][0])
        for value in (a, b):
            self.assertFalse(value['genuine_resolution_upgrade_verified']); self.assertFalse(value['whole_image_capture_date_verified'])
            self.assertEqual(value['point_observations'][0]['point_capture_date'], '2025-05-02')
        with self.assertRaises(ValueError): quality.audit({**receipt, 'width': 0})

    def test_native_tiling_rgb_alignment_and_cache_integrity(self):
        class Session:
            calls = 0
            def run(self, _, inputs):
                self.calls += 1
                assert inputs['pixel_values'].shape == (1, 3, 512, 512)
                logits = np.zeros((1, 150, 128, 128), np.float32); logits[:, 6] = 10
                return [logits]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); rgb = np.arange(64*64*3, dtype=np.uint8).reshape(64, 64, 3)
            Image.fromarray(rgb).save(root/'source.png')
            encoder = spatial.SpatialEncoder.__new__(spatial.SpatialEncoder)
            encoder.indices = list(range(28)); encoder.mean = np.zeros((3, 1, 1), np.float32)
            encoder.std = np.ones((3, 1, 1), np.float32); encoder.session = Session()
            values = encoder.features(root/'source.png', [12, 7, 57, 61], root/'cache')
            np.testing.assert_array_equal(values[:, :, :3], rgb[7:61, 12:57].astype(np.float32)/255)
            cached = encoder.features(root/'source.png', [12, 7, 57, 61], root/'cache')
            np.testing.assert_array_equal(values, cached); self.assertEqual(encoder.session.calls, 1)
            archive = next((root/'cache').glob('*.npz')); archive.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'cache changed'): encoder.features(root/'source.png', [12, 7, 57, 61], root/'cache')

    def test_changed_backbone_is_rejected_before_runtime_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'model.onnx').write_bytes(b'wrong weights')
            with self.assertRaisesRegex(ValueError, 'Pinned SegFormer'): spatial.SpatialEncoder(root)

    def test_boundary_metric_ignores_unreviewed_edges_and_connection_metric_rejects_false_bridges(self):
        target = np.zeros((64, 64), np.uint8); target[10:50, 10:50] = 1
        exact = spatial.boundary_f1(target, target == 1); self.assertEqual(exact['f1'], 1)
        unknown = np.full((64, 64), 255, np.uint8)
        self.assertIsNone(spatial.boundary_f1(unknown, np.ones((64, 64), bool))['f1'])
        target[:] = 0; target[28:36, 5:59] = 1
        pairs = [{'id': 'route', 'a_xy': [10, 31], 'b_xy': [54, 31]}]
        prediction = target == 1; self.assertEqual(spatial.connections(target, prediction, pairs)['recalled_pairs'], 1)
        prediction[:, 31:33] = False; prediction[20:23, :] = True
        self.assertEqual(spatial.connections(target, prediction, pairs)['recalled_pairs'], 0)

    def test_reserved_masks_are_never_training_inputs(self):
        from test_paving_masks import fixture as mask_fixture
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); items, annotations = mask_fixture(root)
            masks.build(items, annotations, root/'reserved', reserved_test=True)
            self.assertTrue(masks.validate(root/'reserved')['reserved_test_only'])
            with self.assertRaisesRegex(ValueError, 'Reserved test'): binary._rows(root/'reserved', lambda: False)
            with self.assertRaisesRegex(ValueError, 'Reserved test'): spatial._read_rows(root/'reserved', FakeEncoder(''), root/'cache', fitting=True, cancelled=lambda: False)

    def test_sealed_test_can_replay_identical_inputs_but_cannot_accept_tuned_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data, _ = fixture(root); binary.train(data, root/'rgb', {'epochs': 1, 'hidden': 8})
            design = root/'design.json'; atomic_json(design, {'feature_labels': spatial.FEATURE_LABELS,
                'encoder_sha256': spatial.BACKBONE_SHA, 'tile_size': 512, 'tile_stride': 384,
                'score_threshold': .5, 'boundary_tolerance_native_pixels': 2, 'head_settings': {'epochs': 1, 'hidden': 8}})
            with patch.object(spatial, 'SpatialEncoder', FakeEncoder):
                report = spatial.train(data, root, root/'rgb', design, root/'trained', root/'cache')
                for fold in report['folds']: self.assertNotIn(fold['held_out_park'], fold['training_sites'])
                rgb = np.full((64, 64, 3), [180, 140, 110], np.uint8); rgb[:, 32:] = [42, 110, 60]
                original = root/'new-source.png'; Image.fromarray(rgb).save(original)
                receipt = root/'new-receipt.json'; atomic_json(receipt, {'width': 64, 'height': 64,
                    'extent_epsg3857': [1000000., 0., 1000064., 64.], 'image_sha256': file_hash(original)})
                annotations = root/'test-annotations.json'; atomic_json(annotations, {'version': masks.ANNOTATIONS,
                    'review_policy': masks.POLICY, 'boundary_ignore_pixels': 0, 'crops': {'newpark': [
                        {'id': 'walk', 'label': 'paving', 'outer': [[1,1],[14,1],[14,30],[1,30]], 'reason': 'Synthetic target'},
                        {'id': 'other', 'label': 'non_paving', 'outer': [[17,1],[30,1],[30,30],[17,30]], 'reason': 'Synthetic target'}]}})
                items = [{'id': 'newpark', 'site_id': 'newpark', 'source_record_id': 'newpark', 'source_file': str(original),
                    'source_sha256': file_hash(original), 'metadata_file': str(receipt), 'metadata_sha256': file_hash(receipt),
                    'crop_pixels': [16,16,48,48]}]
                masks.build(items, annotations, root/'test', reserved_test=True)
                m = masks.validate(root/'test'); seal = root/'seal.json'; value = {'sealed_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    'test_manifest_sha256': file_hash(root/'test/dataset.json'), 'test_annotation_sha256': m['annotation_sha256'],
                    'frozen_models_sha256': file_hash(root/'trained/frozen-models.json'),
                    'connection_probes': {'newpark': [{'id': 'path', 'a_xy': [4,4], 'b_xy': [10,20]}]}}
                atomic_json(seal, value); protocol = root/'protocol.json'; atomic_json(protocol, {'test_site_id': 'newpark'})
                args = [root/'test', root, root/'rgb', root/'trained', design, seal, protocol]
                first = spatial.evaluate_once(*args, root/'first', root/'cache')
                second = spatial.evaluate_once(*args, root/'second', root/'cache')
                self.assertFalse(first['deterministic_replay_of_same_sealed_inputs']); self.assertTrue(second['deterministic_replay_of_same_sealed_inputs'])
                self.assertEqual(first['results'], second['results'])
                value['connection_probes']['newpark'] = []; atomic_json(seal, value)
                with self.assertRaisesRegex(ValueError, 'already consumed'): spatial.evaluate_once(*args, root/'tuned', root/'cache')


if __name__ == '__main__': unittest.main()
