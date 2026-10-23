"""Portable visual-review inputs preserve source lineage and unresolved status."""
from concurrent.futures import CancelledError
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from voxel_mapper.building_spec import build
from voxel_mapper.desktop_review_presets import prepare_demo, prepare_wicker


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


class ReviewPresetTests(unittest.TestCase):
    def fixture(self, root):
        demo = prepare_demo(root/'seed')
        batch = read(demo['batch_path'])
        spec = batch['buildings'][0]['candidates'][0]['spec']
        model = build(spec)
        source = demo['verified_source_sha256'][0]
        model['source_pdf_sha256'] = {'elevation': source}
        model_path = root/'model.json'
        model_path.write_text(json.dumps(model), encoding='utf-8')
        pin = hashlib.sha256(model_path.read_bytes()).hexdigest()
        return demo, model_path, pin, model

    def test_demo_source_and_spec_can_be_loaded_and_bound_without_labels(self):
        from voxel_mapper.desktop_review import load_session, bind_source
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = prepare_demo(root/'demo')
            self.assertEqual(report['dataset_kind'], 'synthetic')
            self.assertEqual(report['training_labels_generated'], 0)
            self.assertFalse(report['physical_acceptance'])
            session = load_session(report['queue_path'])
            bound = bind_source(session, report['source_paths'][0])
            self.assertEqual(len(bound['resolved_sources']), 1)
            row = session['records'][0]
            self.assertIsNone(row['outcome'])
            self.assertTrue(all(not gate for gate in row['candidate']['gates'].values()))
            geometry = build(row['candidate']['spec'])
            self.assertEqual(len(geometry['components']), 1)
            self.assertFalse(geometry['world_placement_eligible'])
            self.assertFalse(list((root/'demo').rglob('*feedback*')))

    def test_missing_originals_keep_real_preset_provisional(self):
        from voxel_mapper.desktop_review import load_session
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            demo, model_path, pin, model = self.fixture(root)
            with patch('voxel_mapper.desktop_review_presets._pinned_model', return_value=(model_path, pin, model)):
                report = prepare_wicker(root/'review')
            self.assertEqual(report['status'], 'review_prepared_missing_sources')
            self.assertEqual(report['missing_source_sha256'], demo['verified_source_sha256'])
            self.assertEqual(report['source_paths'], [])
            row = load_session(report['queue_path'])['records'][0]
            self.assertEqual(row['features']['source_coverage'], 0)
            self.assertFalse(row['candidate']['gates']['identity_verified'])
            self.assertFalse(row['candidate']['gates']['source_verified'])
            self.assertIsNone(row['outcome'])

    def test_selected_source_names_are_unimportant_and_cache_is_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            demo, model_path, pin, model = self.fixture(root)
            retained = root/'retained'
            retained.mkdir()
            original = Path(demo['source_paths'][0])
            (retained/'my drawing.pdf').write_bytes(original.read_bytes())
            (retained/'irrelevant.pdf').write_bytes(b'%PDF-unrelated')
            with patch('voxel_mapper.desktop_review_presets._pinned_model', return_value=(model_path, pin, model)):
                report = prepare_wicker(root/'review', cache_directory=retained)
            self.assertEqual(report['status'], 'review_prepared')
            self.assertEqual(report['verified_source_sha256'], demo['verified_source_sha256'])
            self.assertEqual(report['missing_source_sha256'], [])
            self.assertEqual(Path(report['source_paths'][0]).read_bytes(), original.read_bytes())
            row = read(report['queue_path'])['records'][0]
            self.assertEqual(row['features']['source_coverage'], 1)
            self.assertEqual(report['training_labels_generated'], 0)
            self.assertFalse(report['physical_acceptance'])

    def test_changed_or_wrong_original_never_supplies_source_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            demo, model_path, pin, model = self.fixture(root)
            retained = root/'retained'
            retained.mkdir()
            (retained/(demo['verified_source_sha256'][0]+'.pdf')).write_bytes(b'%PDF-changed')
            with patch('voxel_mapper.desktop_review_presets._pinned_model', return_value=(model_path, pin, model)):
                report = prepare_wicker(root/'review', evidence_directory=retained)
            self.assertEqual(report['verified_source_sha256'], [])
            self.assertEqual(read(report['queue_path'])['records'][0]['features']['source_coverage'], 0)

    def test_model_must_match_pinned_bundled_bytes(self):
        from voxel_mapper.desktop_review_presets import MODEL_PATH, _pinned_model
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root/MODEL_PATH
            path.parent.mkdir(parents=True)
            path.write_text('{}', encoding='utf-8')
            manifest = {'presets': [{'files': [{'path': MODEL_PATH, 'sha256': 'a'*64, 'external': False}]}]}
            with patch('voxel_mapper.desktop_area.bundle', return_value=(root, manifest)):
                with self.assertRaisesRegex(ValueError, 'missing or changed'):
                    _pinned_model()

    def test_original_source_lineage_can_come_from_directly_pinned_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            demo, model_path, _, model = self.fixture(root)
            model.pop('source_pdf_sha256')
            diagnostic = {'source_sha256': demo['verified_source_sha256'][0],
                          'normalized_minus_elevation_metres': [.1, .05]}
            path = root/'diagnostic.json'
            path.write_text(json.dumps(diagnostic), encoding='utf-8')
            diagnostic_pin = hashlib.sha256(path.read_bytes()).hexdigest()
            model['input_sha256'] = {path.name: diagnostic_pin}
            model_path.write_text(json.dumps(model), encoding='utf-8')
            model_pin = hashlib.sha256(model_path.read_bytes()).hexdigest()
            manifest = {'presets': [{'files': [{'path': path.name, 'sha256': diagnostic_pin, 'external': False}]}]}
            with patch('voxel_mapper.desktop_review_presets._pinned_model', return_value=(model_path, model_pin, model)), \
                    patch('voxel_mapper.desktop_area.bundle', return_value=(root, manifest)):
                report = prepare_wicker(root/'review', evidence_directory=Path(demo['source_paths'][0]).parent)
                self.assertEqual(report['verified_source_sha256'], demo['verified_source_sha256'])
                self.assertEqual(read(report['queue_path'])['records'][0]['features']['source_coverage'], 1)
                staged = read(root/'review'/'source-feed-config.json')['buildings'][0]['diagnostics']
                self.assertEqual(staged[0]['sha256'], diagnostic_pin)
                path.write_text('{}', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'diagnostic changed'):
                    prepare_wicker(root/'changed')
                self.assertFalse((root/'changed').exists())

    def test_cancellation_and_existing_output_do_not_rewrite_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(CancelledError):
                prepare_wicker(root/'cancelled', cancelled=lambda: True)
            self.assertFalse((root/'cancelled').exists())
            prepare_demo(root/'demo')
            before = (root/'demo'/'review-preset-report.json').read_bytes()
            with self.assertRaisesRegex(ValueError, 'fresh'):
                prepare_demo(root/'demo')
            self.assertEqual(before, (root/'demo'/'review-preset-report.json').read_bytes())
            with self.assertRaisesRegex(ValueError, 'fresh'):
                prepare_wicker(root/'demo')


if __name__ == '__main__':
    unittest.main()
