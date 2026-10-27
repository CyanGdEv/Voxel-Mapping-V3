"""Synthetic runtime contracts; these fixtures supply no physical training evidence."""
from concurrent.futures import CancelledError
import json
from pathlib import Path
import tempfile
import unittest
import hashlib

import numpy as np
from PIL import Image

from voxel_mapper import study_component_learning as reader
from voxel_mapper import study_intake as intake
from voxel_mapper import study_pretrained_encoder as encoder
from voxel_mapper import study_site_transfer as learning
from voxel_mapper import study_transfer_learning as transfer
from voxel_mapper.building_spec import digest
from test_study_intake import dataset, request


def build(root, held_colour=220, reserve=True):
    a = dataset(root, 'park-a', 'a'*64, 20)
    b = dataset(root, 'park-b', 'b'*64, held_colour)
    for definition in [a, b]:
        folder = root/definition['directory']
        source = json.loads((folder/'dataset.json').read_text())
        for index, row in enumerate(source['records']):
            name = str(Path(row['input_file']).with_name('target-mask.png'))
            invert_held_mask = definition['site_id'] == 'park-b' and held_colour != 220
            Image.new('L', (32, 32), 255 if (index == 0) != invert_held_mask else 0).save(folder/name)
            pin = hashlib.sha256((folder/name).read_bytes()).hexdigest()
            row.update(target_mask_file=name, target_mask_sha256=pin)
            source['output_sha256'][name] = pin
        source['id'] = digest({k: v for k, v in source.items() if k != 'id'})
        (folder/'dataset.json').write_text(json.dumps(source))
        definition['manifest_sha256'] = hashlib.sha256((folder/'dataset.json').read_bytes()).hexdigest()
    out = root/'intake'
    manifest = intake.build(request(root, [a, b], ['park-b'] if reserve else []), out)
    manifest['dataset_kind'] = 'synthetic-site-transfer-contract'
    manifest['id'] = digest({k: v for k, v in manifest.items() if k != 'id'})
    (out/'dataset.json').write_text(json.dumps(manifest))
    return out


class StudySiteTransferTests(unittest.TestCase):
    def run_fit(self, root, held_colour=220):
        root.mkdir()
        data = build(root, held_colour)
        graph = root/'fixture.onnx'
        encoder.synthetic_encoder(graph)
        report = learning.train(data, root/'model', encoder_path=graph,
            encoder_sha256=encoder.SYNTHETIC_SHA256)
        model = transfer.load_model(root/'model'/'model.json')
        return data, report, model

    def test_held_pixels_and_masks_never_change_training_heads_or_normalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data, report, model = self.run_fit(root/'first')
            _, other_report, other = self.run_fit(root/'second', 240)
            self.assertEqual(model['parameters'], other['parameters'])
            self.assertEqual(model['normalization'], other['normalization'])
            self.assertEqual(model['training_sources'], ['a'*64])
            self.assertEqual(report['evaluation_sources'], ['b'*64])
            self.assertEqual(report['training_records'], 2)
            self.assertEqual(report['evaluation_records'], 2)
            self.assertFalse(report['production_eligible'])
            _, rows, _, _ = reader.read_dataset(data, allow_reserved_evaluation=True)
            pngs = [(data/r['input_file']).read_bytes() for r in rows if r['site_id'] == 'park-a']
            features = encoder.extract(pngs, root/'first'/'fixture.onnx', encoder.SYNTHETIC_SHA256, allow_synthetic=True)
            self.assertTrue(np.allclose(model['normalization']['mean'], features.mean(axis=0)))
            self.assertEqual(len(report['predictions']), 2)
            self.assertTrue(all('template_mask_metrics' in p for p in report['predictions']))
            self.assertEqual((root/'first'/'model'/'encoder.onnx').read_bytes(), (root/'first'/'fixture.onnx').read_bytes())
            with self.assertRaisesRegex(ValueError, 'site-isolated trainer'):
                reader.read_dataset(data)

    def test_missing_or_forged_reservation_is_rejected(self):
        for mode in ['missing', 'forged']:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                data = build(root, reserve=mode != 'missing')
                if mode == 'forged':
                    manifest = json.loads((data/'dataset.json').read_text())
                    manifest['site_reservation']['training_record_ids'] += manifest['site_reservation']['evaluation_record_ids']
                    manifest['id'] = digest({k: v for k, v in manifest.items() if k != 'id'})
                    (data/'dataset.json').write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    learning.train(data, root/'model', encoder_path=root/'absent.onnx', encoder_sha256='f'*64)
                self.assertFalse((root/'model').exists())

    def test_corrupt_sources_and_cancellation_leave_no_output(self):
        for mode in ['source', 'cancel']:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                data = build(root)
                graph = root/'fixture.onnx'
                encoder.synthetic_encoder(graph)
                if mode == 'source':
                    next((data/'datasets').rglob('input.png')).write_bytes(b'changed')
                with self.assertRaises(CancelledError if mode == 'cancel' else ValueError):
                    learning.train(data, root/'model', encoder_path=graph,
                        encoder_sha256=encoder.SYNTHETIC_SHA256, cancelled=lambda: mode == 'cancel')
                self.assertFalse((root/'model').exists())


if __name__ == '__main__':
    unittest.main()
