"""Pinned source-only context learning and honest source-disjoint artifacts."""
from concurrent.futures import CancelledError
import copy
from io import BytesIO
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from voxel_mapper import study_context_learning as learning
from voxel_mapper.building_spec import digest
from test_study_vision_learning import fixture, replace_asset, save_manifest, seal_record, sha


def outline_png(kind, variant=0, *, mask=False, inverted=False, size=(32, 32)):
    image = Image.new('L', size, 0 if mask else 255)
    draw = ImageDraw.Draw(image)
    bounds = (2+2*(variant % 3), 3+2*(variant % 2),
        27-2*(variant % 2), 26-(variant % 3))
    if mask:
        draw.rectangle(bounds, fill=255)
        if kind == 'window': draw.rectangle((13, 12, 18, 19), fill=0)
    else:
        draw.rectangle(bounds, outline=0, width=1)
        if kind == 'window': draw.rectangle((12, 11, 19, 20), outline=0, width=1)
    if inverted: image = ImageOps.invert(image)
    stream = BytesIO(); image.save(stream, format='PNG')
    return stream.getvalue()


def outline_fixture(root, groups=3, per_group=4, *, one_class_per_group=False):
    manifest = fixture(root, groups=groups, per_group=per_group,
        one_class_per_group=one_class_per_group)
    for index, row in enumerate(manifest['records']):
        row['target_role'] = 'filled_region_with_hole' if row['kind'] == 'window' else 'filled_region'
        row['target_geometry'] = {'type': 'Polygon'}
        for field, is_mask in (('input_file', False), ('target_mask_file', True)):
            raw = outline_png(row['kind'], index//2, mask=is_mask)
            (root / row[field]).write_bytes(raw)
            manifest['output_sha256'][row[field]] = sha(raw)
            row['target_mask_sha256' if is_mask else 'input_sha256'] = sha(raw)
        seal_record(row)
    save_manifest(root, manifest)
    return manifest


def pixels(path, *, source=False):
    with Image.open(path) as image:
        value = np.asarray(image, dtype=np.float64)/255.
    return 1.-value if source else value


class StudyContextLearningTests(unittest.TestCase):
    def train(self, data, output, **options):
        return learning.train(data, output, epochs=options.pop('epochs', 1),
            channels=4, input_size=32, **options)

    def test_equal_group_summary_exposes_large_group_advantage_and_omits_unassessed_binary_groups(self):
        def scores(iou, *, thin=False):
            return {'soft_iou': iou, 'soft_dice': 2*iou/(1+iou),
                'binary_iou': None if thin else iou,
                'binary_dice': None if thin else 2*iou/(1+iou),
                'support_iou': iou, 'support_dice': 2*iou/(1+iou), 'thin_target': thin}
        predictions = []
        for group, count, measured, template, correct in (
                ('large', 9, .9, .5, True), ('small', 1, 0., .8, False)):
            for index in range(count):
                predictions.append({'record_id': group+str(index), 'group_id': group,
                    'expected_kind': 'door', 'predicted_kind': 'door' if correct else 'window',
                    'majority_baseline_kind': 'door', 'image16_baseline_kind': 'door',
                    'mask_metrics': scores(measured), 'mean_mask_baseline_metrics': scores(template)})
        record_mean = np.mean([row['mask_metrics']['soft_iou'] for row in predictions])
        template_mean = np.mean([row['mean_mask_baseline_metrics']['soft_iou'] for row in predictions])
        self.assertAlmostEqual(record_mean, .81)
        self.assertAlmostEqual(template_mean, .53)
        balanced = learning._balanced_evaluation(predictions, ['door', 'window'])
        self.assertEqual(balanced['source_groups'], 2)
        self.assertEqual(balanced['records'], 10)
        self.assertEqual([group['records'] for group in balanced['groups']], [9, 1])
        self.assertAlmostEqual(balanced['metrics']['accuracy'], .5)
        self.assertAlmostEqual(balanced['mask_metrics']['mean_soft_iou'], .45)
        self.assertAlmostEqual(balanced['mean_mask_baseline_metrics']['mean_soft_iou'], .65)
        self.assertEqual(balanced['groups_beating_template_soft_iou'], 1)
        self.assertEqual(balanced['groups_below_template_soft_iou'], 1)
        self.assertEqual(balanced['groups_tied_template_soft_iou'], 0)
        predictions.append({'record_id': 'thin', 'group_id': 'thin', 'expected_kind': 'door',
            'predicted_kind': 'door', 'majority_baseline_kind': 'door', 'image16_baseline_kind': 'door',
            'mask_metrics': scores(.65, thin=True), 'mean_mask_baseline_metrics': scores(.65, thin=True)})
        with_thin = learning._balanced_evaluation(predictions, ['door', 'window'])
        self.assertEqual(with_thin['mask_metrics']['assessed_groups']['soft_iou'], 3)
        self.assertEqual(with_thin['mask_metrics']['assessed_groups']['binary_iou'], 2)
        self.assertEqual(with_thin['mean_mask_baseline_metrics']['assessed_groups']['binary_iou'], 2)
        self.assertAlmostEqual(with_thin['mask_metrics']['mean_binary_iou'], .45)
        self.assertAlmostEqual(with_thin['mean_mask_baseline_metrics']['mean_binary_iou'], .65)
        self.assertEqual(with_thin['groups_tied_template_soft_iou'], 1)
        self.assertEqual(with_thin['groups_with_assessed_binary_iou_comparison'], 2)

    def test_gallery_warns_immediately_when_equal_group_binary_loses_despite_soft_win(self):
        balanced = {'source_groups': 2, 'metrics': {'accuracy': .2},
            'mask_metrics': {'mean_soft_iou': .6, 'mean_binary_iou': .3},
            'mean_mask_baseline_metrics': {'mean_soft_iou': .5, 'mean_binary_iou': .4}}
        warnings = learning._balanced_warnings(balanced)
        self.assertEqual(len(warnings), 1)
        self.assertIn('Equal-group binary mask IoU is below', warnings[0])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = {'cross_source_evaluation': {'predictions': [], 'per_geometry_role_mask_metrics': {}},
                'quality_warnings': [], 'group_balanced_evaluation': balanced}
            learning._write_gallery(root, report, [], np.empty((0, 32, 32)), np.empty((0, 32, 32)))
            gallery = (root/'index.html').read_text()
            self.assertIn('soft mask IoU 60.0%', gallery)
            self.assertIn('binary mask IoU 30.0%', gallery)
            self.assertIn('template binary IoU 40.0%', gallery)
            self.assertLess(gallery.index(warnings[0]), gallery.index('<p>Context class accuracy:'))

    def test_artifacts_use_independent_training_means_and_standalone_source_only_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); data = root/'data'; manifest = outline_fixture(data)
            original = {path.relative_to(data).as_posix(): sha(path.read_bytes())
                for path in data.rglob('*') if path.is_file()}
            output = root/'output'
            fitted_networks = []
            fit = learning._network().fit
            def capture_fit(*arguments, **options):
                fitted = fit(*arguments, **options)
                fitted_networks.append(fitted)
                return fitted
            with patch.object(learning._network(), 'fit', side_effect=capture_fit):
                report = self.train(data, output, epochs=2)
            self.assertEqual(report['status'], 'exploratory_component_context_trained')
            self.assertEqual(report['group_balanced_evaluation']['source_groups'], 3)
            gallery = (output/'index.html').read_text()
            self.assertIn('Equal-group evaluation (3 source groups)', gallery)
            self.assertIn('training-only template binary IoU', gallery)
            for warning in learning._balanced_warnings(report['group_balanced_evaluation']):
                self.assertLess(gallery.index(warning), gallery.index('<p>Context class accuracy:'))
            for key in ('production_eligible', 'automatic_promotion', 'geometry_generated', 'physical_acceptance'):
                self.assertIs(report[key], False, key)
            self.assertEqual(report['park_world_blocks_added'], 0)
            self.assertEqual(report['training_labels_generated'], 0)
            self.assertEqual({path.relative_to(data).as_posix(): sha(path.read_bytes())
                for path in data.rglob('*') if path.is_file()}, original)
            self.assertEqual(report['artifact_sha256'],
                digest({key: value for key, value in report.items() if key != 'artifact_sha256'}))
            for name, pin in report['output_sha256'].items():
                self.assertEqual(sha((output/name).read_bytes()), pin)
            evaluation = report['cross_source_evaluation']
            self.assertEqual(evaluation['source_groups'], 3)
            self.assertEqual(len(evaluation['predictions']), 12)
            self.assertEqual(set(evaluation['per_class_mask_metrics']), {'door', 'window'})
            self.assertEqual(set(evaluation['per_geometry_role_mask_metrics']),
                {'filled_region', 'filled_region_with_hole'})
            fold_means = {}
            for fold in evaluation['folds']:
                for train_key, evaluation_key in (('training_sources', 'evaluation_sources'),
                        ('training_buildings', 'evaluation_buildings'),
                        ('training_record_ids', 'evaluation_record_ids'),
                        ('training_group_ids', 'held_out_group_ids')):
                    self.assertFalse(set(fold[train_key]) & set(fold[evaluation_key]))
                training_rows = [row for row in manifest['records'] if row['id'] in fold['training_record_ids']]
                values = np.asarray([pixels(data/row['input_file'], source=True) for row in training_rows])
                targets = np.asarray([pixels(data/row['target_mask_file']) for row in training_rows])
                expected_normalization = {'mean': float(values.mean()), 'scale': max(.1, float(values.std()))}
                expected_template = targets.mean(axis=0)
                expected_prior = np.clip(targets.reshape(-1, 16, 2, 16, 2).mean(axis=(2, 4)).mean(axis=0), .05, .95)
                actual_network = fitted_networks[fold['id']]
                for key, expected in expected_normalization.items():
                    np.testing.assert_allclose(actual_network['normalization'][key], expected, atol=1e-14, rtol=0)
                np.testing.assert_allclose(actual_network['mask_prior'], expected_prior, atol=1e-14, rtol=0)
                self.assertEqual(fold['normalization_sha256'], digest(actual_network['normalization']))
                self.assertEqual(fold['mean_mask_baseline_sha256'], digest(expected_template.tolist()))
                self.assertEqual(fold['mask_prior_sha256'], digest(actual_network['mask_prior']))
                fold_means[fold['id']] = expected_template
            for prediction in evaluation['predictions']:
                saved = pixels(output/prediction['baseline_mask_file'])
                np.testing.assert_allclose(saved, fold_means[prediction['fold_id']], atol=.5/255.+1e-12, rtol=0)
                self.assertEqual(sha((output/prediction['mask_prediction_file']).read_bytes()),
                    prediction['mask_prediction_sha256'])
            model = learning.load_model(output/'model.json')
            source = (data/manifest['records'][0]['input_file']).read_bytes()
            predicted = learning.predict(model, source)
            changed = learning.predict(model, outline_png('window', inverted=True))
            self.assertEqual(predicted['input_sha256'], sha(source))
            self.assertEqual(predicted['mask_size'], [32, 32])
            self.assertGreater(float(np.abs(np.asarray(predicted['mask_probabilities'])
                -np.asarray(changed['mask_probabilities'])).mean()), 1e-6)
            learning.save_model(model, root/'copy.json')
            reloaded = learning.load_model(root/'copy.json')
            self.assertEqual(reloaded, model)
            shutil.rmtree(data)
            self.assertEqual(learning.predict(reloaded, source), predicted)
            with self.assertRaises(ValueError): learning.save_model(model, root/'copy.json')

    def test_held_out_image_mask_and_label_changes_cannot_change_fitted_fold_or_baselines(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); data = root/'data'; manifest = outline_fixture(data)
            held = manifest['groups'][0]['group_id']
            first = self.train(data, root/'first')['cross_source_evaluation']
            before = next(fold for fold in first['folds'] if fold['held_out_group_ids'] == [held])
            for row in manifest['records']:
                if row['group_id'] != held: continue
                replace_asset(data, manifest, row, 'input_file', outline_png(row['kind'], inverted=True))
                replace_asset(data, manifest, row, 'target_mask_file', outline_png(row['kind'], mask=True, inverted=True))
                row['kind'] = 'unseen_held_out_class'
                row['target_role'] = 'changed_audit_role'
                seal_record(row)
            save_manifest(data, manifest)
            second = self.train(data, root/'second')['cross_source_evaluation']
            after = next(fold for fold in second['folds'] if fold['held_out_group_ids'] == [held])
            for key in ('normalization_sha256', 'parameters_sha256', 'mask_prior_sha256',
                    'mean_mask_baseline_sha256', 'majority_baseline_kind',
                    'image16_baseline_normalization_sha256', 'image16_baseline_parameters_sha256'):
                self.assertEqual(before[key], after[key], key)
            self.assertEqual(after['unknown_class_records'], 4)
            self.assertEqual(len(second['unknown_class_cases']), 4)
            by_id = {row['record_id']: row for row in first['predictions']}
            held_predictions = [row for row in second['predictions'] if row['group_id'] == held]
            self.assertTrue(all(row['unknown_held_out_class'] for row in held_predictions))
            self.assertTrue(all(row['baseline_mask_sha256'] == by_id[row['record_id']]['baseline_mask_sha256']
                for row in held_predictions))
            self.assertTrue(any(row['mask_prediction_sha256'] != by_id[row['record_id']]['mask_prediction_sha256']
                for row in held_predictions))

    def test_labels_masks_and_geometry_metadata_never_enter_source_features(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary)/'data'; manifest = outline_fixture(data)
            _, rows, source, target, old_features, _ = learning.read_dataset(data, input_size=32)
            self.assertGreater(float(np.abs(source-target).mean()), .2)
            for row in manifest['records']:
                replace_asset(data, manifest, row, 'target_mask_file', outline_png(row['kind'], mask=True, inverted=True))
                row['kind'] = 'different_label'
                row['target_role'] = 'different_role'
                row['target_geometry'] = {'type': 'Changed', 'coordinates': [[12345, 67890]]}
                seal_record(row)
            save_manifest(data, manifest)
            _, changed_rows, changed_source, changed_target, changed_features, _ = learning.read_dataset(data, input_size=32)
            self.assertEqual([row['id'] for row in rows], [row['id'] for row in changed_rows])
            np.testing.assert_array_equal(changed_source, source)
            np.testing.assert_array_equal(changed_features, old_features)
            self.assertGreater(float(np.abs(changed_target-target).mean()), .5)

    def test_resigned_invalid_supervision_and_changed_hashes_never_publish(self):
        for mode in ('source_hash', 'mask_hash', 'record_hash', 'mask_shape', 'mask_path', 'shared_building'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); data = root/'data'; manifest = outline_fixture(data, groups=2, per_group=2)
                row = manifest['records'][0]
                if mode in ('source_hash', 'mask_hash'):
                    field = 'input_file' if mode == 'source_hash' else 'target_mask_file'
                    (data/row[field]).write_bytes(b'changed pinned asset')
                elif mode == 'record_hash':
                    row['kind'] = 'changed'; save_manifest(data, manifest)
                elif mode == 'mask_shape':
                    replace_asset(data, manifest, row, 'target_mask_file', outline_png(row['kind'], mask=True, size=(31, 32)))
                elif mode == 'mask_path':
                    row['target_mask_file'] = '../outside.png'
                    manifest['output_sha256']['../outside.png'] = '0'*64
                    seal_record(row); save_manifest(data, manifest)
                else:
                    row['building_id'] = manifest['records'][-1]['building_id']
                    seal_record(row); save_manifest(data, manifest)
                with self.assertRaises(ValueError): self.train(data, root/'output')
                self.assertFalse((root/'output').exists())

    def test_cancellation_snapshot_change_and_output_race_leave_only_fresh_complete_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); data = root/'data'; manifest = outline_fixture(data, groups=2, per_group=2)
            with self.assertRaises(CancelledError): self.train(data, root/'early', cancelled=lambda: True)
            stop = False
            def cancel_epoch(value):
                nonlocal stop
                if 'epoch' in value: stop = True
            with self.assertRaises(CancelledError):
                self.train(data, root/'during', cancelled=lambda: stop, progress=cancel_epoch)
            target = data/manifest['records'][0]['target_mask_file']; raw = target.read_bytes()
            changed = False
            def change_snapshot(value):
                nonlocal changed
                if value.get('progress', 0.) >= .9 and not changed:
                    changed = True; target.write_bytes(raw+b'changed')
            with self.assertRaisesRegex(ValueError, 'changed'):
                self.train(data, root/'changed', progress=change_snapshot)
            self.assertTrue(changed); target.write_bytes(raw)
            raced = False
            def create_output(value):
                nonlocal raced
                if value.get('progress', 0.) >= .9 and not raced:
                    raced = True; (root/'race').mkdir(); (root/'race/sentinel').write_text('keep')
            with self.assertRaisesRegex(ValueError, 'Fresh'):
                self.train(data, root/'race', progress=create_output)
            self.assertTrue(raced)
            self.assertEqual((root/'race/sentinel').read_text(), 'keep')
            with self.assertRaises(ValueError): self.train(data, root/'race')
            self.assertEqual(sorted(path.name for path in root.iterdir()), ['data', 'race'])

    def test_settings_work_and_checkpoint_lineage_are_revalidated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); data = root/'data'; outline_fixture(data, groups=1, per_group=2)
            with patch.object(learning._network(), 'fit', side_effect=AssertionError('Work rejected before fit')):
                with patch.object(learning, 'MAX_FORWARD_WORK', 1):
                    with self.assertRaisesRegex(ValueError, 'work budget'): self.train(data, root/'work')
            report = self.train(data, root/'valid')
            self.assertEqual(report['cross_source_evaluation']['status'], 'unassessed_single_source_group')
            self.assertIsNone(report['cross_source_evaluation']['metrics'])
            self.assertEqual(report['cross_source_evaluation']['predictions'], [])
            model = learning.load_model(root/'valid/model.json')
            for mode in ('input_size', 'prior_lineage', 'record_lineage', 'promotion', 'parameter_hash'):
                invalid = copy.deepcopy(model)
                if mode == 'input_size': invalid['input_size'] = 64
                elif mode == 'prior_lineage': invalid['training_mask_prior_sha256'] = '0'*64
                elif mode == 'record_lineage': invalid['training_record_ids'].pop()
                elif mode == 'promotion': invalid['automatic_promotion'] = True
                else: invalid['network']['parameters']['context_weights'][0][0] += .1
                invalid['artifact_sha256'] = digest({key: value for key, value in invalid.items() if key != 'artifact_sha256'})
                with self.subTest(mode=mode), self.assertRaises(ValueError): learning.validate_model(invalid)
            oversized = root/'oversized.png'
            with oversized.open('wb') as stream: stream.truncate(1_000_001)
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('Unbounded read')):
                with self.assertRaisesRegex(ValueError, 'Bounded PNG'): learning.predict(model, oversized)
            for options in ({'epochs': True}, {'epochs': 101}, {'channels': 1}, {'input_size': 16}):
                with self.subTest(options=options), self.assertRaises(ValueError):
                    learning.train(data, root/'invalid', **options)
            self.assertFalse((root/'work').exists())
            self.assertFalse((root/'invalid').exists())


if __name__ == '__main__':
    unittest.main()
