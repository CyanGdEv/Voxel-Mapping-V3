"""Source-disjoint, pinned supervision and atomic research vision artifacts."""
from concurrent.futures import CancelledError
import copy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from voxel_mapper import study_vision_learning as learning
from voxel_mapper.building_spec import digest


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def shape_png(kind, shift=0, *, mask=False, inverted=False, size=(32, 32), mode='L'):
    image = Image.new('L', size, 0 if mask else 255)
    draw = ImageDraw.Draw(image)
    bounds = ((11 + shift, 3, 20 + shift, 28) if kind == 'door'
        else (3, 11 + shift, 28, 20 + shift))
    draw.rectangle(bounds, fill=255 if mask else 0)
    if inverted:
        from PIL import ImageOps
        image = ImageOps.invert(image)
    if mode != 'L':
        image = image.convert(mode)
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def seal_record(row):
    row['record_sha256'] = digest({k: v for k, v in row.items() if k != 'record_sha256'})


def save_manifest(root, manifest):
    manifest['id'] = digest({k: v for k, v in manifest.items() if k != 'id'})
    (root / 'dataset.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


def fixture(root, groups=3, per_group=4, *, one_class_per_group=False):
    """Known bars with measured pixel masks; no planning extraction is simulated."""
    root.mkdir()
    records, inventory, files = [], [], {}
    for group in range(groups):
        building, source = f'synthetic-building-{group}', sha(f'pdf-{group}'.encode())
        identity = {'building_ids': [building], 'source_sha256': [source]}
        gid = digest(identity)
        record_ids = []
        for index in range(per_group):
            kind = ('door' if group % 2 == 0 else 'window') if one_class_per_group else ('door' if index % 2 == 0 else 'window')
            rid = digest([group, index])
            record_ids.append(rid)
            directory = root / 'examples' / rid
            directory.mkdir(parents=True)
            image = shape_png(kind, (group + index) % 3 - 1)
            mask = shape_png(kind, (group + index) % 3 - 1, mask=True)
            image_name = f'examples/{rid}/input.png'
            mask_name = f'examples/{rid}/target-mask.png'
            (root / image_name).write_bytes(image)
            (root / mask_name).write_bytes(mask)
            files[image_name], files[mask_name] = sha(image), sha(mask)
            row = {'id': rid, 'building_id': building, 'kind': kind,
                'source': {'document_sha256': source, 'page': 1},
                'input_file': image_name, 'input_sha256': sha(image),
                'target_mask_file': mask_name, 'target_mask_sha256': sha(mask),
                'learning_eligible': True, 'evidence_level': 'synthetic_measured_mask',
                'group_id': gid}
            seal_record(row)
            records.append(row)
        inventory.append({'group_id': gid, **identity, 'record_ids': sorted(record_ids)})
    manifest = {'version': 'retained-study-dataset-v1', 'dataset_kind': 'synthetic_measured_masks',
        'records': records, 'groups': sorted(inventory, key=lambda g: g['group_id']),
        'output_sha256': files}
    save_manifest(root, manifest)
    return manifest


def replace_asset(root, manifest, row, field, raw):
    relative = row[field]
    (root / relative).write_bytes(raw)
    pin = sha(raw)
    manifest['output_sha256'][relative] = pin
    row['input_sha256' if field == 'input_file' else 'target_mask_sha256'] = pin
    seal_record(row)
    save_manifest(root, manifest)


class StudyVisionLearningTests(unittest.TestCase):
    def train(self, data, output, **options):
        return learning.train(data, output, epochs=options.pop('epochs', 3),
            channels=4, input_size=32, **options)

    def test_mask_scores_preserve_soft_coverage_and_do_not_reward_erasing_thin_targets(self):
        target = np.zeros((32, 32), dtype=np.float64)
        target[8:24, 15] = .25
        identical = learning._mask_metrics(target, target.copy())
        erased = learning._mask_metrics(target, np.zeros_like(target))
        self.assertEqual(identical['soft_iou'], 1.)
        self.assertEqual(identical['soft_dice'], 1.)
        self.assertEqual(erased['soft_iou'], 0.)
        self.assertEqual(erased['soft_dice'], 0.)
        self.assertIsNone(erased['binary_iou'])
        self.assertIsNone(erased['binary_dice'])
        self.assertEqual(erased['support_iou'], 0.)
        self.assertTrue(erased['thin_target'])

    def test_masks_change_supervision_and_prediction_needs_no_dataset_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = root / 'data'; manifest = fixture(data, groups=1)
            raw = (data / manifest['records'][0]['input_file']).read_bytes()
            self.train(data, root / 'first', epochs=8)
            first_model = learning.load_model(root / 'first/model.json')
            before = learning.predict(first_model, raw)
            for row in manifest['records']:
                replace_asset(data, manifest, row, 'target_mask_file',
                    shape_png(row['kind'], mask=True, inverted=True))
            self.train(data, root / 'second', epochs=8)
            second_model = learning.load_model(root / 'second/model.json')
            after = learning.predict(second_model, raw)
            self.assertEqual(before['input_sha256'], after['input_sha256'])
            self.assertGreater(float(np.abs(np.asarray(before['mask_probabilities'])
                - np.asarray(after['mask_probabilities'])).mean()), 1e-4)
            import shutil
            shutil.rmtree(data)
            self.assertEqual(learning.predict(first_model, raw), before)
            learning.save_model(first_model, root / 'copy.json')
            self.assertEqual(learning.load_model(root / 'copy.json'), first_model)
            with self.assertRaises(ValueError):
                learning.save_model(first_model, root / 'copy.json')

    def test_saved_outputs_match_training_only_templates_and_reload_is_standalone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = root / 'data'; manifest = fixture(data)
            source_before = {p.relative_to(data).as_posix(): sha(p.read_bytes()) for p in data.rglob('*') if p.is_file()}
            output = root / 'output'
            report = self.train(data, output, epochs=4)
            self.assertEqual({p.relative_to(data).as_posix(): sha(p.read_bytes()) for p in data.rglob('*') if p.is_file()}, source_before)
            self.assertEqual(report['status'], 'exploratory_component_vision_trained')
            self.assertTrue(report['model_weights_updated'])
            self.assertTrue(report['mask_predictions_generated'])
            self.assertFalse(report['production_eligible'])
            self.assertFalse(report['geometry_generated'])
            self.assertFalse(report['physical_acceptance'])
            self.assertEqual(report['park_world_blocks_added'], 0)
            self.assertEqual(report['training_labels_generated'], 0)
            model = learning.load_model(output / 'model.json')
            self.assertLess(model['training']['final_loss'], model['training']['initial_loss'])
            self.assertTrue(model['training']['conv_filters_updated'])
            evaluation = report['cross_source_evaluation']
            self.assertEqual(evaluation['source_groups'], 3)
            self.assertEqual(len(evaluation['predictions']), 12)
            self.assertEqual(evaluation['majority_baseline_metrics']['accuracy'], .5)
            self.assertEqual(evaluation['mask_metrics']['records'], 12)
            for relative, pin in report['output_sha256'].items():
                self.assertEqual(sha((output / relative).read_bytes()), pin)
            for fold in evaluation['folds']:
                source_pixels = []
                for row in manifest['records']:
                    if row['id'] in fold['training_record_ids']:
                        with Image.open(data / row['input_file']) as image:
                            source_pixels.append(1. - np.asarray(image, dtype=np.float64) / 255.)
                values = np.asarray(source_pixels)
                expected_normalization = {'mean': float(values.mean()), 'scale': max(.1, float(values.std()))}
                self.assertEqual(fold['normalization_sha256'], digest(expected_normalization))
            by_id = {row['id']: row for row in manifest['records']}
            for prediction in evaluation['predictions']:
                row = by_id[prediction['record_id']]
                training_masks = []
                for train_row in manifest['records']:
                    if train_row['group_id'] != row['group_id']:
                        with Image.open(data / train_row['target_mask_file']) as image:
                            training_masks.append(np.asarray(image, dtype=np.float64) / 255.)
                independently_computed = np.mean(training_masks, axis=0)
                with Image.open(output / prediction['baseline_mask_file']) as image:
                    saved = np.asarray(image, dtype=np.float64) / 255.
                np.testing.assert_allclose(saved, independently_computed, atol=.5 / 255. + 1e-10)
                self.assertEqual(sha((output / prediction['mask_prediction_file']).read_bytes()),
                    prediction['mask_prediction_sha256'])
            prediction = learning.predict(model, shape_png('door'))
            self.assertEqual(prediction['mask_size'], [32, 32])
            probabilities = np.asarray(prediction['mask_probabilities'])
            self.assertEqual(probabilities.shape, (32, 32))
            self.assertTrue(np.isfinite(probabilities).all())
            self.assertTrue(((probabilities >= 0) & (probabilities <= 1)).all())
            self.assertAlmostEqual(sum(prediction['probabilities'].values()), 1.)
            self.assertEqual(prediction['input_sha256'], sha(shape_png('door')))

    def test_source_held_out_perturbation_cannot_change_train_statistics_or_baselines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = root / 'data'; manifest = fixture(data)
            held = manifest['groups'][0]['group_id']
            first = self.train(data, root / 'first')
            before = next(f for f in first['cross_source_evaluation']['folds'] if f['held_out_group_ids'] == [held])
            for row in manifest['records']:
                if row['group_id'] == held:
                    replace_asset(data, manifest, row, 'input_file', shape_png(row['kind'], inverted=True))
                    replace_asset(data, manifest, row, 'target_mask_file', shape_png(row['kind'], mask=True, inverted=True))
            second = self.train(data, root / 'second')
            after = next(f for f in second['cross_source_evaluation']['folds'] if f['held_out_group_ids'] == [held])
            for field in ('normalization_sha256', 'parameters_sha256', 'mean_mask_baseline_sha256', 'image16_baseline_normalization_sha256', 'image16_baseline_parameters_sha256'):
                self.assertEqual(before[field], after[field], field)
            for fold in first['cross_source_evaluation']['folds']:
                self.assertFalse(set(fold['training_sources']) & set(fold['evaluation_sources']))
                self.assertFalse(set(fold['training_buildings']) & set(fold['evaluation_buildings']))
                self.assertFalse(set(fold['training_record_ids']) & set(fold['evaluation_record_ids']))

    def test_changed_or_resigned_invalid_supervision_never_publishes(self):
        modes = ('stale_image', 'stale_mask', 'stale_record', 'mask_hash',
            'mask_shape', 'mask_alpha', 'mask_oversize', 'source_oversize', 'mask_path', 'group_leakage', 'manifest_hash')
        for mode in modes:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); data = root / 'data'; manifest = fixture(data, groups=2, per_group=2)
                row = manifest['records'][0]
                if mode in ('stale_image', 'stale_mask'):
                    field = 'input_file' if mode == 'stale_image' else 'target_mask_file'
                    (data / row[field]).write_bytes(b'not the pinned pixels')
                elif mode == 'stale_record':
                    row['kind'] = 'changed_label'
                    save_manifest(data, manifest)
                elif mode == 'mask_hash':
                    row['target_mask_sha256'] = '0' * 64
                    seal_record(row); save_manifest(data, manifest)
                elif mode in ('mask_shape', 'mask_alpha', 'mask_oversize'):
                    raw = shape_png('door', mask=True,
                        size=(31, 32) if mode == 'mask_shape' else (257, 32) if mode == 'mask_oversize' else (32, 32),
                        mode='RGBA' if mode == 'mask_alpha' else 'L')
                    replace_asset(data, manifest, row, 'target_mask_file', raw)
                elif mode == 'source_oversize':
                    replace_asset(data, manifest, row, 'input_file', shape_png('door', size=(257, 32)))
                elif mode == 'mask_path':
                    row['target_mask_file'] = '../outside.png'
                    manifest['output_sha256']['../outside.png'] = '0' * 64
                    seal_record(row); save_manifest(data, manifest)
                elif mode == 'group_leakage':
                    row['building_id'] = manifest['records'][-1]['building_id']
                    seal_record(row); save_manifest(data, manifest)
                else:
                    manifest['id'] = '0' * 64
                    (data / 'dataset.json').write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    self.train(data, root / 'output', epochs=1)
                self.assertFalse((root / 'output').exists())

    def test_checkpoint_revalidation_prediction_bounds_and_unassessed_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture(root / 'one', groups=1)
            report = self.train(root / 'one', root / 'one-output', epochs=1)
            evaluation = report['cross_source_evaluation']
            self.assertEqual(evaluation['status'], 'unassessed_single_source_group')
            self.assertIsNone(evaluation['metrics'])
            self.assertIsNone(evaluation['mask_metrics'])
            self.assertEqual(evaluation['predictions'], [])
            model = learning.load_model(root / 'one-output/model.json')
            for mode in ('parameter', 'production', 'network_dimensions', 'input_size', 'missing_lineage'):
                invalid = copy.deepcopy(model)
                if mode == 'parameter':
                    invalid['network']['parameters']['conv1_weights'][0][0][0][0] += .1
                elif mode == 'production':
                    invalid['production_eligible'] = True
                elif mode == 'network_dimensions':
                    invalid['network']['architecture']['channels'] = 1000000
                    invalid['network']['id'] = digest({k: v for k, v in invalid['network'].items() if k != 'id'})
                elif mode == 'input_size':
                    invalid['input_size'] = 64
                else:
                    invalid['training_sources'] = []
                invalid['artifact_sha256'] = digest({k: v for k, v in invalid.items() if k != 'artifact_sha256'})
                with self.subTest(mode=mode), self.assertRaises(ValueError):
                    learning.validate_model(invalid)
            oversized = root / 'oversized.png'
            with oversized.open('wb') as stream:
                stream.truncate(1_000_001)
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('Unbounded image read')):
                with self.assertRaisesRegex(ValueError, 'Bounded PNG'):
                    learning.predict(model, oversized)
            fixture(root / 'two', groups=2, per_group=2, one_class_per_group=True)
            unknown = self.train(root / 'two', root / 'two-output', epochs=1)['cross_source_evaluation']
            self.assertEqual(unknown['metrics']['records'], 4)
            self.assertEqual(unknown['metrics']['accuracy'], 0.)
            self.assertEqual(sum(f['unknown_class_records'] for f in unknown['folds']), 4)
            self.assertTrue(all(p['unknown_held_out_class'] for p in unknown['predictions']))

    def test_snapshot_revalidation_and_cancellation_preserve_fresh_and_existing_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = root / 'data'; manifest = fixture(data, groups=2, per_group=2)
            with self.assertRaises(CancelledError):
                self.train(data, root / 'cancelled', cancelled=lambda: True)
            stop = False
            def cancel_after_epoch(value):
                nonlocal stop
                if 'epoch' in value:
                    stop = True
            with self.assertRaises(CancelledError):
                self.train(data, root / 'midcancelled', progress=cancel_after_epoch, cancelled=lambda: stop)
            target_path = data / manifest['records'][0]['target_mask_file']
            original_target = target_path.read_bytes()
            changed = False
            def change_source(value):
                nonlocal changed
                if value.get('progress', 0) >= .9 and not changed:
                    changed = True
                    path = data / manifest['records'][0]['target_mask_file']
                    path.write_bytes(path.read_bytes() + b'changed')
            with self.assertRaisesRegex(ValueError, 'changed'):
                self.train(data, root / 'changed', epochs=1, progress=change_source)
            self.assertTrue(changed)
            target_path.write_bytes(original_target)
            for name in ('cancelled', 'midcancelled', 'changed'):
                self.assertFalse((root / name).exists())
            (root / 'existing').mkdir()
            (root / 'existing/sentinel').write_text('keep')
            with self.assertRaises(ValueError):
                self.train(data, root / 'existing', epochs=1)
            self.assertEqual((root / 'existing/sentinel').read_text(), 'keep')
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['data', 'existing'])


if __name__ == '__main__':
    unittest.main()
