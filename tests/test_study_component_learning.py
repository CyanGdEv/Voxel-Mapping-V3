"""Actual source-image learning, separated source folds and immutable inputs."""
from concurrent.futures import CancelledError
import copy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from voxel_mapper import study_component_learning as learning
from voxel_mapper.building_spec import digest


def png(kind, shift=0, *, inverted=False, width=32):
    image = Image.new('L', (width, 32), 255)
    draw = ImageDraw.Draw(image)
    if kind == 'door':
        draw.rectangle((11+shift, 2, 18+shift, 29), fill=0)
    else:
        draw.rectangle((2, 11+shift, 29, 18+shift), fill=0)
    if inverted:
        from PIL import ImageOps
        image = ImageOps.invert(image)
    stream = BytesIO(); image.save(stream, format='PNG')
    return stream.getvalue()


def seal(manifest):
    manifest['id'] = digest({k: v for k, v in manifest.items() if k != 'id'})
    return manifest


def write_manifest(root, manifest):
    seal(manifest)
    (root/'dataset.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


def fixture(root, groups=3, per_group=6, *, one_class_per_group=False):
    root.mkdir()
    records, files, inventory = [], {}, []
    for group in range(groups):
        building = 'synthetic-building-'+str(group)
        source = chr(97+group)*64
        identifier = digest({'building_ids': [building], 'source_sha256': [source]})
        ids = []
        for index in range(per_group):
            kind = ('door' if group % 2 == 0 else 'window') if one_class_per_group else ('door' if index % 2 == 0 else 'window')
            rid = digest([group, index]); ids.append(rid)
            relative = 'examples/'+rid+'/input.png'
            path = root/relative; path.parent.mkdir(parents=True)
            raw = png(kind, (group+index) % 3-1)
            path.write_bytes(raw); pin = learning._sha(raw); files[relative] = pin
            mask = path.parent/'target.png'; mask.write_bytes(png(kind, inverted=True))
            files[mask.relative_to(root).as_posix()] = learning._sha(mask.read_bytes())
            records.append({'id': rid, 'building_id': building, 'kind': kind,
                'source': {'document_sha256': source, 'page': 1}, 'input_file': relative,
                'input_sha256': pin, 'target_mask_file': mask.relative_to(root).as_posix(),
                'evidence_level': 'synthetic_fixture', 'learning_eligible': True, 'group_id': identifier})
        inventory.append({'group_id': identifier, 'building_ids': [building],
            'source_sha256': [source], 'record_ids': sorted(ids)})
    manifest = {'version': learning.DATASET_VERSION, 'dataset_kind': 'synthetic_fixture',
        'records': records, 'groups': sorted(inventory, key=lambda v: v['group_id']), 'output_sha256': files}
    write_manifest(root, manifest)
    return manifest


def update_file(root, manifest, relative, raw, *, source_record=None):
    (root/relative).write_bytes(raw)
    manifest['output_sha256'][relative] = learning._sha(raw)
    if source_record is not None:
        source_record['input_sha256'] = learning._sha(raw)
    write_manifest(root, manifest)


class StudyComponentLearningTests(unittest.TestCase):
    def test_actual_pixels_learn_visually_distinct_types_on_source_disjoint_folds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = root/'data'; fixture(data)
            report = learning.train(data, root/'output', epochs=60, hidden_units=8)
            evaluation = report['cross_source_evaluation']
            self.assertEqual(evaluation['status'], 'assessed_leave_one_group_out')
            self.assertEqual(evaluation['source_groups'], 3)
            self.assertEqual(len(evaluation['predictions']), 18)
            self.assertGreater(evaluation['metrics']['accuracy'], .95)
            self.assertGreater(evaluation['metrics']['macro_f1'], .95)
            self.assertEqual(evaluation['baseline_metrics']['accuracy'], .5)
            self.assertFalse(report['production_eligible'])
            self.assertFalse(report['geometry_generated'])
            self.assertTrue(report['model_weights_updated'])
            self.assertEqual(report['training_labels_generated'], 0)
            self.assertEqual(report['dataset_kind'], 'synthetic_fixture')
            model = learning.load_model(root/'output/model.json')
            self.assertLess(model['training']['final_loss'], model['training']['initial_loss']*.05)
            self.assertEqual(len(model['parameters']['hidden_weights']), 256)
            for fold in evaluation['folds']:
                self.assertFalse(set(fold['training_sources']) & set(fold['evaluation_sources']))
                self.assertFalse(set(fold['training_buildings']) & set(fold['evaluation_buildings']))
            predicted = learning.predict(model, png('door'))
            self.assertEqual(predicted['kind'], 'door')
            self.assertAlmostEqual(sum(predicted['probabilities'].values()), 1.)
            self.assertEqual(predicted['input_sha256'], learning._sha(png('door')))
            learning.save_model(model, root/'copy.json')
            self.assertEqual(learning.load_model(root/'copy.json'), model)
            with self.assertRaises(ValueError):
                learning.save_model(model, root/'copy.json')
            from voxel_mapper.neural_learning import validate_model as validate_building_ranker
            with self.assertRaises(ValueError):
                validate_building_ranker(model)

    def test_target_geometry_and_masks_never_enter_training_features(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = root/'data'; manifest = fixture(data, groups=2)
            first = learning.train(data, root/'first', epochs=20, hidden_units=8)
            first_model = learning.load_model(root/'first/model.json')
            for row in manifest['records']:
                update_file(data, manifest, row['target_mask_file'], png(row['kind']))
                row['target_geometry'] = {'arbitrary': [999, 7, 3]}
            write_manifest(data, manifest)
            second = learning.train(data, root/'second', epochs=20, hidden_units=8)
            second_model = learning.load_model(root/'second/model.json')
            self.assertEqual(first_model['parameters'], second_model['parameters'])
            self.assertEqual(first_model['input_normalization'], second_model['input_normalization'])
            self.assertNotEqual(first['dataset_id'], second['dataset_id'])
            self.assertEqual(first['cross_source_evaluation']['metrics'], second['cross_source_evaluation']['metrics'])

    def test_held_out_images_do_not_change_fit_normalization_or_weights(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = root/'data'; manifest = fixture(data, groups=3)
            held = manifest['groups'][0]['group_id']
            first = learning.train(data, root/'first', epochs=20, hidden_units=8)
            before = next(f for f in first['cross_source_evaluation']['folds'] if f['held_out_group_ids'] == [held])
            for row in manifest['records']:
                if row['group_id'] == held:
                    update_file(data, manifest, row['input_file'], png(row['kind'], inverted=True), source_record=row)
            second = learning.train(data, root/'second', epochs=20, hidden_units=8)
            after = next(f for f in second['cross_source_evaluation']['folds'] if f['held_out_group_ids'] == [held])
            self.assertEqual(before['normalization_sha256'], after['normalization_sha256'])
            self.assertEqual(before['parameters_sha256'], after['parameters_sha256'])

    def test_forged_group_or_reused_source_cannot_cross_evaluation(self):
        for mode in ('record_group', 'source', 'building'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); data = root/'data'; manifest = fixture(data)
                if mode == 'record_group':
                    manifest['records'][0]['group_id'] = 'f'*64
                elif mode == 'source':
                    manifest['records'][-1]['source']['document_sha256'] = manifest['records'][0]['source']['document_sha256']
                else:
                    manifest['records'][-1]['building_id'] = manifest['records'][0]['building_id']
                write_manifest(data, manifest)
                with self.assertRaisesRegex(ValueError, 'group|leakage'):
                    learning.train(data, root/'output', epochs=1)
                self.assertFalse((root/'output').exists())

    def test_resigned_manifest_cannot_hide_a_stale_record_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = root/'data'; manifest = fixture(data, groups=2)
            row = manifest['records'][0]
            row['record_sha256'] = digest(row)
            write_manifest(data, manifest)
            learning.read_dataset(data)
            row['kind'] = 'changed_semantic_label'
            write_manifest(data, manifest)
            with self.assertRaisesRegex(ValueError, 'record proof changed'):
                learning.train(data, root/'output', epochs=1)
            self.assertFalse((root/'output').exists())

    def test_changed_source_or_target_asset_is_rejected_without_output(self):
        for field in ('input_file', 'target_mask_file'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); data = root/'data'; manifest = fixture(data)
                (data/manifest['records'][0][field]).write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'changed'):
                    learning.train(data, root/'output', epochs=1)
                self.assertFalse((root/'output').exists())

    def test_source_changes_during_fit_are_caught_before_atomic_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = root/'data'; manifest = fixture(data)
            changed = False
            def progress(value):
                nonlocal changed
                if value.get('progress', 0) >= .9 and not changed:
                    changed = True
                    path = data/manifest['records'][0]['input_file']
                    path.write_bytes(path.read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError, 'changed'):
                learning.train(data, root/'output', epochs=2, progress=progress)
            self.assertFalse((root/'output').exists())
            self.assertFalse(list(root.glob('component-image-training-*')))

    def test_single_group_is_explicitly_unassessed_and_unknown_classes_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture(root/'one', groups=1)
            report = learning.train(root/'one', root/'one-output', epochs=2)
            self.assertEqual(report['cross_source_evaluation']['status'], 'unassessed_single_source_group')
            self.assertIsNone(report['cross_source_evaluation']['metrics'])
            self.assertEqual(report['cross_source_evaluation']['predictions'], [])
            fixture(root/'two', groups=2, one_class_per_group=True)
            report = learning.train(root/'two', root/'two-output', epochs=2)
            self.assertEqual(report['cross_source_evaluation']['metrics']['accuracy'], 0.)
            self.assertTrue(all(f['unknown_class_records'] == 6 for f in report['cross_source_evaluation']['folds']))
            self.assertFalse(report['production_eligible'])

    def test_deterministic_weights_and_checkpoint_tampering_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture(root/'data', groups=2)
            first = learning.train(root/'data', root/'first', epochs=5, hidden_units=8)
            second = learning.train(root/'data', root/'second', epochs=5, hidden_units=8)
            self.assertEqual(first, second)
            model = learning.load_model(root/'first/model.json')
            for mode in ('parameter', 'production', 'oversized'):
                bad = copy.deepcopy(model)
                if mode == 'parameter':
                    bad['parameters']['hidden_weights'][0][0] += .1
                elif mode == 'production':
                    bad['production_eligible'] = True
                    bad['artifact_sha256'] = digest({k: v for k, v in bad.items() if k != 'artifact_sha256'})
                else:
                    bad['architecture']['hidden_units'] = 1000000
                    bad['artifact_sha256'] = digest({k: v for k, v in bad.items() if k != 'artifact_sha256'})
                with self.subTest(mode=mode), self.assertRaises(ValueError):
                    learning.validate_model(bad)

    def test_cancellation_and_existing_output_preserve_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture(root/'data')
            with self.assertRaises(CancelledError):
                learning.train(root/'data', root/'cancelled', cancelled=lambda: True)
            cancelled = False
            def progress(value):
                nonlocal cancelled
                if 'epoch' in value:
                    cancelled = True
            with self.assertRaises(CancelledError):
                learning.train(root/'data', root/'midcancelled', epochs=2,
                    progress=progress, cancelled=lambda: cancelled)
            self.assertFalse((root/'midcancelled').exists())
            self.assertFalse((root/'cancelled').exists())
            (root/'output').mkdir(); sentinel = root/'output/sentinel'; sentinel.write_text('keep')
            with self.assertRaises(ValueError):
                learning.train(root/'data', root/'output', epochs=1)
            self.assertEqual(sentinel.read_text(), 'keep')

    def test_prediction_rejects_large_image_path_before_reading_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture(root/'data', groups=1)
            learning.train(root/'data', root/'output', epochs=1)
            model = learning.load_model(root/'output/model.json')
            image = root/'oversized.png'
            with image.open('wb') as stream:
                stream.truncate(learning.MAX_IMAGE_BYTES+1)
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('Unbounded image read')):
                with self.assertRaisesRegex(ValueError, 'Bounded PNG'):
                    learning.predict(model, image)

    def test_bounded_decoding_and_display_hypothesis_refusal(self):
        for mode in ('oversized', 'hypothesis', 'path_escape', 'manifest_hash'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); data = root/'data'; manifest = fixture(data)
                row = manifest['records'][0]
                if mode == 'oversized':
                    update_file(data, manifest, row['input_file'], png('door', width=257), source_record=row)
                elif mode == 'hypothesis':
                    row['evidence_level'] = 'illustrative_display_geometry'
                    write_manifest(data, manifest)
                elif mode == 'path_escape':
                    manifest['output_sha256']['../outside.png'] = '0'*64
                    write_manifest(data, manifest)
                else:
                    (data/'dataset.json').write_text(json.dumps({**manifest, 'id': '0'*64}))
                with self.assertRaises(ValueError):
                    learning.train(data, root/'output', epochs=1)
                self.assertFalse((root/'output').exists())


if __name__ == '__main__':
    unittest.main()
