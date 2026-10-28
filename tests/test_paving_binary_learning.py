import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from voxel_mapper import paving_binary_learning as learning, paving_masks as masks, aerial_semantic_network as net
from voxel_mapper.desktop_memory import digest
from voxel_mapper.generation_cycles import atomic_json, file_hash


def fixture(root):
    rng = np.random.default_rng(10); items = []; crops = {}
    for i in range(3):
        name = 'park'+str(i); rgb = np.empty((64, 64, 3), np.uint8)
        rgb[:, :32] = np.clip([160, 145, 120]+rng.integers(-5, 6, (64, 32, 3)), 0, 255)
        rgb[:, 32:] = np.clip([50, 100, 60]+rng.integers(-5, 6, (64, 32, 3)), 0, 255)
        source = root/(name+'.png'); Image.fromarray(rgb).save(source)
        meta = root/(name+'.json'); atomic_json(meta, {'width': 64, 'height': 64,
            'image_sha256': file_hash(source), 'extent_epsg3857': [i*1000., 0., i*1000.+64., 64.]})
        items.append({'id': name, 'site_id': name, 'source_record_id': name,
            'source_file': str(source), 'source_sha256': file_hash(source),
            'metadata_file': str(meta), 'metadata_sha256': file_hash(meta), 'crop_pixels': [0, 0, 64, 64]})
        crops[name] = [{'id': 'walk', 'label': 'paving', 'outer': [[2, 2], [29, 2], [29, 61], [2, 61]], 'reason': 'Synthetic paving'},
            {'id': 'other', 'label': 'non_paving', 'outer': [[34, 2], [61, 2], [61, 61], [34, 61]], 'reason': 'Synthetic negative'}]
    ann = root/'annotations.json'; atomic_json(ann, {'version': masks.ANNOTATIONS, 'review_policy': masks.POLICY,
        'boundary_ignore_pixels': 1, 'crops': crops})
    masks.build(items, ann, root/'dataset')
    return root/'dataset', items


class BinaryPavingTests(unittest.TestCase):
    def test_binary_head_learns_without_changing_five_class_default(self):
        rng = np.random.default_rng(7); x = rng.normal(size=(100, 31)).astype(np.float32)
        y = np.tile(np.arange(2), 50); x[:, 0] = y*5
        fit = net.fit(x, y, {'epochs': 8, 'hidden': 8}, class_count=2)
        self.assertEqual(np.asarray(fit['parameters']['w2']).shape, (8, 2))
        self.assertGreater(fit['weight_change_l2'], 0)
        self.assertLess(fit['loss_history'][-1]['weighted_cross_entropy'], fit['loss_history'][0]['weighted_cross_entropy'])
        five = np.tile(np.arange(5), 20)
        self.assertEqual(net.fit(x, five, {'epochs': 1, 'hidden': 8}), net.fit(x, five, {'epochs': 1, 'hidden': 8}, class_count=5))
        with self.assertRaises(ValueError): net.fit(x, y, class_count=3)

    def test_rgb_samples_match_source_pixels_ignore_unknown_and_hold_out_whole_parks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data, _ = fixture(root)
            report = learning.train(data, root/'trained', {'epochs': 2, 'hidden': 8})
            manifest = masks.validate(data); rows = {r['id']: r for r in manifest['records']}
            with (root/'trained/rgb-samples.csv').open() as stream: samples = list(csv.DictReader(stream))
            self.assertEqual(len(samples), report['samples']); self.assertEqual(report['sampled_unknown_pixels'], 0)
            self.assertEqual(report['always_paving_reference']['paving_iou'], .5)
            self.assertEqual(report['always_paving_reference']['paving_recall'], 1.)
            self.assertEqual({int(s['label']) for s in samples}, {0, 1})
            for sample in samples[::max(1, len(samples)//15)]:
                row = rows[sample['crop_id']]; x = int(sample['crop_x']); y = int(sample['crop_y'])
                rgb = np.asarray(Image.open(data/row['image_file'])); mask = np.asarray(Image.open(data/row['mask_file']))
                self.assertEqual([int(sample[k]) for k in ('r', 'g', 'b')], rgb[y, x].tolist())
                self.assertEqual(int(sample['label']), int(mask[y, x]))
            for fold in report['folds']:
                for mode in learning.MODES:
                    self.assertNotIn(fold['held_out_park'], fold['scores'][mode]['training_site_ids'])
                    preview = root/'trained/folds'/fold['held_out_park']/mode/fold['held_out_record_ids'][0]/'report.json'
                    self.assertFalse(json.loads(preview.read_text())['source_in_training'])

    def test_rgb_only_prediction_cannot_read_context_or_five_class_targets(self):
        from voxel_mapper.aerial_semantic_learning import load_model
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data, _ = fixture(root); learning.train(data, root/'trained', {'epochs': 1, 'hidden': 8})
            path = root/'trained/models/rgb_only/model.json'; model = json.loads(path.read_text())
            x = np.zeros((4, 31), np.float32); x[:, :3] = [.4, .5, .6]
            changed = x.copy(); changed[:, 3:] = np.arange(28)[None, :]*100
            np.testing.assert_array_equal(learning.probabilities(x, model), learning.probabilities(changed, model))
            with self.assertRaises(ValueError): load_model(path)
            model['production_eligible'] = True; model['artifact_sha256'] = digest({k: v for k, v in model.items() if k != 'artifact_sha256'})
            with self.assertRaises(ValueError): learning.validate_model(model)

    def test_pinned_prediction_uses_only_source_and_saved_model_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data, items = fixture(root); learning.train(data, root/'trained', {'epochs': 1, 'hidden': 8})
            source = items[0]; receipt = json.loads(Path(source['metadata_file']).read_text()); model = root/'trained/folds/park0/rgb_context/model.json'
            result = learning.predict(source['source_file'], receipt, model, root/'prediction', model_sha256=file_hash(model))
            self.assertFalse(result['source_in_training']); self.assertEqual(sum(result['pixel_counts'].values()), 4096)
            with self.assertRaises(ValueError): learning.predict(source['source_file'], receipt, model, root/'bad', model_sha256='0'*64)
            with self.assertRaises(net.CancelledError): learning.train(data, root/'cancelled', cancelled=lambda: True)

    def test_desktop_worker_trains_predicts_and_remembers_both_models(self):
        from voxel_mapper.desktop_runtime import DesktopRuntime
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data, items = fixture(root); request = root/'train.json'
            atomic_json(request, {'version': 'desktop-paving-binary-training-v1', 'dataset_directory': 'dataset', 'settings': {'epochs': 1, 'hidden': 8}})
            runtime = DesktopRuntime(root/'desktop', workers=1, memory_budget_mb=2048)
            try:
                jid = runtime.submit('train_paving_binary', request); runtime._futures[jid].result(timeout=50)
                job = runtime.store.job(jid); self.assertEqual(job['status'], 'completed', job.get('error'))
                self.assertIn('paving_binary_checkpoint', runtime.store.context(50000)); self.assertTrue(job['result']['model_weights_updated'])
                source = root/'demo'; source.mkdir(); import shutil
                shutil.copy2(items[0]['source_file'], source/'source-image.bin'); shutil.copy2(items[0]['metadata_file'], source/'imagery-receipt.json')
                model = job['result']['models']['rgb_only']; request = root/'predict.json'
                atomic_json(request, {'version': 'desktop-paving-binary-prediction-v1', 'aerial_directory': 'demo', 'model_file': model['file'], 'model_sha256': model['sha256']})
                pid = runtime.submit('predict_paving_binary', request); runtime._futures[pid].result(timeout=30)
                prediction = runtime.store.job(pid); self.assertEqual(prediction['status'], 'completed', prediction.get('error'))
                self.assertTrue(prediction['result']['source_in_training'])
            finally: runtime.close(wait=True)


if __name__ == '__main__':
    unittest.main()
