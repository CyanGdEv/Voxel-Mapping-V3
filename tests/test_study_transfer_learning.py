"""Frozen real-runtime features, independently checked ridge heads and folds."""
from concurrent.futures import CancelledError
import copy
from io import BytesIO
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from voxel_mapper import study_pretrained_encoder as encoder
from voxel_mapper import study_transfer_learning as learning
from voxel_mapper.building_spec import digest
from test_study_context_learning import outline_fixture, outline_png, pixels
from test_study_vision_learning import replace_asset, save_manifest, seal_record, sha


def color_fixture(root, groups=3, per_group=4):
    manifest = outline_fixture(root, groups=groups, per_group=per_group)
    for index, row in enumerate(manifest['records']):
        with Image.open(root/row['input_file']) as image:
            ink = np.asarray(image) == 0
        rgb = np.full((32, 32, 3), 255, dtype=np.uint8)
        level = 185+10*(index//per_group)
        rgb[ink] = (level, 20, 35) if row['kind'] == 'door' else (35, 20, level)
        stream = BytesIO(); Image.fromarray(rgb).save(stream, format='PNG')
        raw = stream.getvalue(); (root/row['input_file']).write_bytes(raw)
        row['input_sha256'] = manifest['output_sha256'][row['input_file']] = sha(raw)
        seal_record(row)
    save_manifest(root, manifest)
    return manifest


class StudyTransferLearningTests(unittest.TestCase):
    def train(self, data, output, fixture, **options):
        return learning.train(data, output, encoder_path=fixture['path'],
            encoder_sha256=fixture['sha256'], input_size=32, **options)

    def test_fitted_heads_satisfy_independent_weighted_ridge_normal_equations(self):
        rng = np.random.default_rng(923)
        features = rng.normal(size=(7, 3))*[.05, 2., .7]+[1., -3., .2]
        masks = rng.uniform(0., 1., (7, 32, 32))
        labels = ['door']*4+['window']*3
        normalization, parameters, training, classes = learning._fit(features, masks, labels,
            ridge_alpha=100., cancelled=lambda: False)
        mean, scale = features.mean(axis=0), np.maximum(features.std(axis=0), .1)
        np.testing.assert_allclose(normalization['mean'], mean, atol=1e-12, rtol=0)
        np.testing.assert_allclose(normalization['scale'], scale, atol=1e-12, rtol=0)
        source = (features-mean)/scale
        target = np.eye(2)[[classes.index(label) for label in labels]]
        counts = {label: labels.count(label) for label in classes}
        weights = np.asarray([len(labels)/(len(classes)*counts[label]) for label in labels])
        mask_target = masks.reshape(7, 16, 2, 16, 2).mean(axis=(2, 4)).reshape(7, 256)
        for prefix, expected, row_weights in (('class', target, weights),
                ('mask', mask_target, np.ones(7))):
            coefficient = np.asarray(parameters[prefix+'_weights'])
            bias = np.asarray(parameters[prefix+'_bias'])
            residual = (source@coefficient+bias-expected)*row_weights[:, None]
            # Stationarity of the strictly convex ridge objective is an
            # independent check; it does not reproduce the dual solver.
            np.testing.assert_allclose(source.T@residual+100.*coefficient, 0., atol=2e-10, rtol=0)
            np.testing.assert_allclose(residual.sum(axis=0), 0., atol=2e-10, rtol=0)
            self.assertGreater(float(np.abs(coefficient).max()), 1e-5)
        self.assertFalse(training['encoder_weights_updated'])
        self.assertTrue(training['head_weights_updated'])
        self.assertLess(training['final_loss'], training['initial_loss'])

    def test_actual_encoder_features_are_fitted_once_and_fold_statistics_and_templates_are_training_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); data = root/'data'; manifest = color_fixture(data)
            fixture = encoder.synthetic_encoder(root/'encoder.onnx')
            encoder_before = Path(fixture['path']).read_bytes()
            dataset_before = {path.relative_to(data).as_posix(): sha(path.read_bytes())
                for path in data.rglob('*') if path.is_file()}
            fitted = []
            fit = learning._fit
            def capture_fit(*arguments, **options):
                value = fit(*arguments, **options); fitted.append(value); return value
            with patch.object(learning, '_fit', side_effect=capture_fit), \
                    patch.object(encoder, 'extract', wraps=encoder.extract) as extract:
                report = self.train(data, root/'output', fixture)
            self.assertEqual(extract.call_count, 1)
            self.assertEqual(report['status'], 'exploratory_pretrained_transfer_trained')
            balanced = report['group_balanced_evaluation']
            self.assertEqual(balanced['source_groups'], 3)
            self.assertEqual(balanced['records'], 12)
            gallery = (root/'output/index.html').read_text()
            self.assertIn('Equal-group evaluation (3 source groups)', gallery)
            self.assertIn('soft mask IoU', gallery)
            self.assertIn('training-only template binary IoU', gallery)
            for warning in learning.context._balanced_warnings(balanced):
                self.assertLess(gallery.index(warning), gallery.index('<p>Frozen-encoder head class accuracy:'))
            self.assertFalse(report['production_eligible'])
            self.assertFalse(report['automatic_promotion'])
            self.assertFalse(report['geometry_generated'])
            self.assertFalse(report['physical_acceptance'])
            self.assertEqual(Path(fixture['path']).read_bytes(), encoder_before)
            self.assertEqual((root/'output/encoder.onnx').read_bytes(), encoder_before)
            self.assertEqual({path.relative_to(data).as_posix(): sha(path.read_bytes())
                for path in data.rglob('*') if path.is_file()}, dataset_before)
            for relative, pin in report['output_sha256'].items():
                self.assertEqual(sha((root/'output'/relative).read_bytes()), pin)
            evaluation = report['cross_source_evaluation']
            rows = sorted(manifest['records'], key=lambda row: row['id'])
            features = encoder.extract([(data/row['input_file']).read_bytes() for row in rows],
                fixture['path'], fixture['sha256'], allow_synthetic=True).astype(np.float64)
            means = {}
            for fold in evaluation['folds']:
                for training, held in (('training_sources', 'evaluation_sources'),
                        ('training_buildings', 'evaluation_buildings'),
                        ('training_record_ids', 'evaluation_record_ids')):
                    self.assertFalse(set(fold[training]) & set(fold[held]))
                indices = [index for index, row in enumerate(rows) if row['id'] in fold['training_record_ids']]
                normalization = fitted[fold['id']][0]
                np.testing.assert_allclose(normalization['mean'], features[indices].mean(axis=0), atol=1e-12, rtol=0)
                np.testing.assert_allclose(normalization['scale'], np.maximum(features[indices].std(axis=0), .1), atol=1e-12, rtol=0)
                expected = np.mean([pixels(data/rows[index]['target_mask_file']) for index in indices], axis=0)
                self.assertEqual(fold['normalization_sha256'], digest(normalization))
                self.assertEqual(fold['mean_mask_baseline_sha256'], digest(expected.tolist()))
                means[fold['id']] = expected
            for prediction in evaluation['predictions']:
                np.testing.assert_allclose(pixels(root/'output'/prediction['baseline_mask_file']),
                    means[prediction['fold_id']], atol=.5/255.+1e-12, rtol=0)
            model = learning.load_model(root/'output/model.json')
            self.assertFalse(model['training']['encoder_weights_updated'])
            self.assertTrue(model['training']['head_weights_updated'])
            source = (data/rows[0]['input_file']).read_bytes()
            original = learning.predict(model, source, encoder_path=fixture['path'], encoder_sha256=fixture['sha256'])
            self.assertEqual(original['kind'], rows[0]['kind'])
            alternate = learning.predict(model, (data/rows[-1]['input_file']).read_bytes(),
                encoder_path=fixture['path'], encoder_sha256=fixture['sha256'])
            self.assertGreater(float(np.abs(np.asarray(original['mask_probabilities'])
                -np.asarray(alternate['mask_probabilities'])).mean()), 1e-6)
            learning.save_model(model, root/'copy.json')
            self.assertEqual(learning.load_model(root/'copy.json'), model)
            shutil.rmtree(data); Path(fixture['path']).unlink()
            bundled = root/'output/encoder.onnx'
            self.assertEqual(learning.predict(learning.load_model(root/'copy.json'), source,
                encoder_path=bundled, encoder_sha256=fixture['sha256']), original)

    def test_held_out_pixels_masks_labels_and_roles_cannot_change_fitted_fold(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); data = root/'data'; manifest = color_fixture(data)
            fixture = encoder.synthetic_encoder(root/'encoder.onnx')
            held = manifest['groups'][0]['group_id']
            before_report = self.train(data, root/'first', fixture)['cross_source_evaluation']
            before = next(fold for fold in before_report['folds'] if fold['held_out_group_ids'] == [held])
            for row in manifest['records']:
                if row['group_id'] != held: continue
                replace_asset(data, manifest, row, 'input_file', outline_png(row['kind'], inverted=True))
                replace_asset(data, manifest, row, 'target_mask_file', outline_png(row['kind'], mask=True, inverted=True))
                row['kind'] = 'unseen_class'; row['target_role'] = 'changed_role'; seal_record(row)
            save_manifest(data, manifest)
            after_report = self.train(data, root/'second', fixture)['cross_source_evaluation']
            after = next(fold for fold in after_report['folds'] if fold['held_out_group_ids'] == [held])
            for key in ('normalization_sha256', 'parameters_sha256', 'mean_mask_baseline_sha256', 'majority_baseline_kind'):
                self.assertEqual(before[key], after[key], key)
            self.assertEqual(after['unknown_class_records'], 4)
            old = {row['record_id']: row for row in before_report['predictions']}
            changed = [row for row in after_report['predictions'] if row['group_id'] == held]
            self.assertTrue(all(row['unknown_held_out_class'] for row in changed))
            self.assertTrue(all(row['baseline_mask_sha256'] == old[row['record_id']]['baseline_mask_sha256'] for row in changed))
            self.assertTrue(any(row['mask_prediction_sha256'] != old[row['record_id']]['mask_prediction_sha256'] for row in changed))

    def test_synthetic_encoder_cannot_train_a_real_dataset_and_checkpoint_fields_are_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); data = root/'data'; manifest = color_fixture(data, groups=1, per_group=2)
            fixture = encoder.synthetic_encoder(root/'encoder.onnx')
            self.train(data, root/'valid', fixture)
            model = learning.load_model(root/'valid/model.json')
            for mode in ('coefficient', 'shape', 'dimension', 'normalization', 'encoder_updated',
                    'promotion', 'encoder_hash', 'hash'):
                invalid = copy.deepcopy(model)
                if mode == 'coefficient': invalid['parameters']['mask_weights'][0][0] = 1e100
                elif mode == 'shape': invalid['parameters']['class_weights'].pop()
                elif mode == 'dimension': invalid['architecture']['feature_count'] = 1_000_000
                elif mode == 'normalization': invalid['normalization']['scale'][0] = 0.
                elif mode == 'encoder_updated': invalid['training']['encoder_weights_updated'] = True
                elif mode == 'promotion': invalid['automatic_promotion'] = True
                elif mode == 'encoder_hash': invalid['encoder_sha256'] = '0'*64
                else: invalid['parameters']['class_bias'][0] += .01
                if mode != 'hash':
                    invalid['artifact_sha256'] = digest({key: value for key, value in invalid.items() if key != 'artifact_sha256'})
                with self.subTest(mode=mode), self.assertRaises(ValueError): learning.validate_model(invalid)
            oversized = root/'oversized-model.json'
            with oversized.open('wb') as stream: stream.truncate(learning.MAX_MODEL_BYTES+1)
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('Unbounded checkpoint read')):
                with self.assertRaisesRegex(ValueError, 'Bounded'): learning.load_model(oversized)
            manifest['dataset_kind'] = 'reviewed_source_traces'
            for row in manifest['records']:
                row['evidence_level'] = 'reviewed_source_trace'; seal_record(row)
            save_manifest(data, manifest)
            with self.assertRaisesRegex(ValueError, 'Synthetic'):
                self.train(data, root/'invalid', fixture)
            self.assertFalse((root/'invalid').exists())

    def test_cancellation_encoder_and_dataset_changes_and_output_race_never_publish_partial_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); data = root/'data'; manifest = color_fixture(data, groups=2, per_group=2)
            fixture = encoder.synthetic_encoder(root/'encoder.onnx')
            with self.assertRaises(CancelledError): self.train(data, root/'early', fixture, cancelled=lambda: True)
            stop = False
            def stop_after_features(value):
                nonlocal stop
                if value.get('progress', 0.) > 0: stop = True
            with self.assertRaises(CancelledError):
                self.train(data, root/'during', fixture, cancelled=lambda: stop, progress=stop_after_features)
            for mode in ('encoder', 'dataset', 'race'):
                target = Path(fixture['path']) if mode == 'encoder' else data/manifest['records'][0]['target_mask_file']
                raw = target.read_bytes(); changed = False
                def mutate(value):
                    nonlocal changed
                    if value.get('progress', 0.) >= .9 and not changed:
                        changed = True
                        if mode == 'race':
                            (root/'race').mkdir(); (root/'race/sentinel').write_text('keep')
                        else: target.write_bytes(raw+b'changed')
                with self.subTest(mode=mode), self.assertRaises(ValueError):
                    self.train(data, root/mode, fixture, progress=mutate)
                self.assertTrue(changed, mode)
                if mode == 'race': self.assertEqual((root/'race/sentinel').read_text(), 'keep')
                else:
                    self.assertFalse((root/mode).exists()); target.write_bytes(raw)
            with self.assertRaises(ValueError): self.train(data, root/'race', fixture)
            self.assertEqual(sorted(path.name for path in root.iterdir()), ['data', 'encoder.onnx', 'race'])


if __name__ == '__main__':
    unittest.main()
