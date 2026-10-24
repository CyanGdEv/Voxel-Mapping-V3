"""Actual bounded CPU ONNX inference and immutable encoder identities."""
from concurrent.futures import CancelledError
import copy
import hashlib
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from voxel_mapper import study_pretrained_encoder as encoder


def color_png(color=(255, 0, 0), *, size=(32, 32), mode='RGB', format='PNG'):
    image = Image.new(mode, size, color)
    stream = BytesIO(); image.save(stream, format=format)
    return stream.getvalue()


class StudyPretrainedEncoderTests(unittest.TestCase):
    def test_portable_provenance_preprocessing_and_attribution_are_pinned(self):
        metadata = encoder._registry()[encoder.PRETRAINED_SHA256]
        validated = encoder.validate_info(metadata)
        self.assertEqual(validated, metadata)
        assets = encoder.attribution_assets(metadata)
        for name, key in (('LICENSE', 'license_sha256'), ('UPSTREAM-README.md', 'readme_sha256')):
            self.assertEqual(hashlib.sha256(assets[name]).hexdigest(), metadata['provenance'][key])
        self.assertIn(metadata['sha256'].encode(), assets['encoder-MODIFICATIONS.txt'])
        self.assertIn('Apache License', encoder.license_text(metadata))
        for field in ('provenance', 'preprocessing', 'provider', 'output_shape'):
            invalid = copy.deepcopy(metadata)
            if field == 'provenance': invalid[field]['source_sha256'] = '0'*64
            elif field == 'preprocessing': invalid[field]['mean'][0] = .1
            elif field == 'provider': invalid[field] = 'CUDAExecutionProvider'
            else: invalid[field] = ['batch', 1000]
            with self.subTest(field=field), self.assertRaises(ValueError): encoder.validate_info(invalid)

    def test_real_cpu_runtime_extracts_expected_rgb_features_and_batches_at_most_four(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = encoder.synthetic_encoder(Path(temporary)/'fixture.onnx')
            info = encoder.encoder_info(fixture['path'], fixture['sha256'], allow_synthetic=True)
            self.assertEqual(info['provider'], 'CPUExecutionProvider')
            self.assertTrue(info['synthetic'])
            self.assertEqual(info['feature_count'], 3)
            self.assertEqual(info['input_shape'][1:], [3, 224, 224])
            colors = [(255, 0, 0), (0, 0, 255), (255, 255, 255)]*3
            calls, progress = [], []
            create_session = encoder._session
            class SessionSpy:
                def __init__(self, session): self.session = session
                def run(self, outputs, feeds):
                    calls.append(feeds['input'].shape[0])
                    return self.session.run(outputs, feeds)
            def actual_session(*arguments):
                session, version = create_session(*arguments)
                return SessionSpy(session), version
            with patch.object(encoder, '_session', side_effect=actual_session):
                actual = encoder.extract([color_png(color) for color in colors], fixture['path'],
                    fixture['sha256'], allow_synthetic=True, progress=progress.append)
            expected = (np.asarray(colors, dtype=np.float64)/255.-[.485, .456, .406])/[.229, .224, .225]
            self.assertEqual(actual.dtype, np.float32)
            np.testing.assert_allclose(actual, expected, rtol=3e-4, atol=4e-4)
            self.assertEqual(calls, [4, 4, 1])
            self.assertEqual([value['completed'] for value in progress], [4, 8, 9])
            transparent = encoder.extract([color_png((0, 0, 0, 0), mode='RGBA')],
                fixture['path'], fixture['sha256'], allow_synthetic=True)
            np.testing.assert_allclose(transparent[0], expected[2], rtol=3e-4, atol=4e-4)
            self.assertEqual(hashlib.sha256(Path(fixture['path']).read_bytes()).hexdigest(), fixture['sha256'])

    def test_only_exact_registered_bytes_and_explicit_synthetic_eligibility_are_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'fixture.onnx'; fixture = encoder.synthetic_encoder(path)
            with self.assertRaisesRegex(ValueError, 'Synthetic'):
                encoder.encoder_info(path, fixture['sha256'])
            with self.assertRaises(ValueError): encoder.encoder_info(path, '0'*64, allow_synthetic=True)
            with self.assertRaises(ValueError): encoder.encoder_info(path, encoder.PRETRAINED_SHA256)
            raw = bytearray(path.read_bytes()); raw[-1] ^= 1; path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                encoder.encoder_info(path, fixture['sha256'], allow_synthetic=True)
            with self.assertRaises(FileExistsError): encoder.synthetic_encoder(path)
            oversized = Path(temporary)/'oversized.onnx'
            with oversized.open('wb') as stream: stream.truncate(encoder.MAX_MODEL_BYTES+1)
            with self.assertRaisesRegex(ValueError, 'Bounded'):
                encoder.encoder_info(oversized, fixture['sha256'], allow_synthetic=True)

    def test_source_pixels_are_bounded_and_cancellation_stops_actual_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = encoder.synthetic_encoder(Path(temporary)/'fixture.onnx')
            def extract(images, **options):
                return encoder.extract(images, fixture['path'], fixture['sha256'], allow_synthetic=True, **options)
            for raw in (b'not a PNG', color_png(size=(257, 32)), color_png(format='JPEG'), b'x'*1_000_001):
                with self.subTest(bytes=len(raw)), self.assertRaises(ValueError): extract([raw])
            for images in (np.zeros((1, 32, 32)), [color_png()]*2049, [object()]):
                with self.assertRaises(ValueError): extract(images)
            path = Path(temporary)/'oversized.png'
            with path.open('wb') as stream: stream.truncate(1_000_001)
            with patch.object(Path, 'open', side_effect=AssertionError('Unbounded source read')):
                with self.assertRaisesRegex(ValueError, 'Bounded'): encoder._source_tensor(path)
            with self.assertRaises(CancelledError): extract([color_png()], cancelled=lambda: True)
            stop, completed = False, []
            def progress(value):
                nonlocal stop
                completed.append(value['completed']); stop = True
            with self.assertRaises(CancelledError):
                extract([color_png()]*9, cancelled=lambda: stop, progress=progress)
            self.assertEqual(completed, [4])


if __name__ == '__main__':
    unittest.main()
