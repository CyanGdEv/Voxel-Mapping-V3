import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from voxel_mapper import paving_masks as paving
from voxel_mapper.desktop_memory import digest
from voxel_mapper.generation_cycles import atomic_json, file_hash


def rectangle(left, top, right, bottom):
    return [[left, top], [right, top], [right, bottom], [left, bottom]]


def trace(identifier, label, outer, **kwargs):
    return {'id': identifier, 'label': label, 'outer': outer, 'reason': 'Synthetic test trace', **kwargs}


def fixture(root):
    rgb = np.arange(64*64*3, dtype=np.uint8).reshape(64, 64, 3)
    original = root/'source.png'; Image.fromarray(rgb).save(original)
    metadata = root/'receipt.json'
    atomic_json(metadata, {'width': 64, 'height': 64, 'image_sha256': file_hash(original),
        'extent_epsg3857': [100., 200., 228., 328.], 'attribution': 'Synthetic fixture'})
    annotations = root/'annotations.json'
    atomic_json(annotations, {'version': paving.ANNOTATIONS, 'review_policy': paving.POLICY,
        'boundary_ignore_pixels': 1, 'crops': {'crop': [
            trace('walk', 'paving', rectangle(2, 2, 29, 29), holes=[rectangle(10, 10, 20, 20)]),
            trace('grass', 'non_paving', rectangle(12, 12, 18, 18)),
            trace('canopy', 'unknown', rectangle(23, 5, 27, 10))]}})
    items = [{'id': 'crop', 'site_id': 'park', 'source_record_id': 'source',
        'source_file': str(original), 'source_sha256': file_hash(original),
        'metadata_file': str(metadata), 'metadata_sha256': file_hash(metadata),
        'crop_pixels': [16, 16, 48, 48]}]
    return items, annotations


def reseal(path, manifest):
    manifest['id'] = digest({k: v for k, v in manifest.items() if k != 'id'})
    atomic_json(path, manifest)


class PavingMaskTests(unittest.TestCase):
    def test_holes_are_unknown_until_explicitly_traced_negative(self):
        traces = [trace('walk', 'paving', rectangle(2, 2, 29, 29), holes=[rectangle(9, 9, 22, 22)])]
        labels, reasons = paving.rasterize(traces, (32, 32))
        self.assertEqual(labels[5, 5], 1); self.assertEqual(labels[15, 15], 255)
        self.assertEqual(labels[0, 0], 255); self.assertEqual(labels[2, 5], 255)
        self.assertEqual(reasons[15, 15], paving.REASONS['not_reviewed'])
        traces.append(trace('grass', 'non_paving', rectangle(11, 11, 20, 20)))
        labels, _ = paving.rasterize(traces, (32, 32))
        self.assertEqual(labels[15, 15], 0); self.assertEqual(labels[10, 10], 255)

    def test_disagreement_unknown_and_nodata_never_become_training_labels(self):
        traces = [trace('walk', 'paving', rectangle(1, 1, 30, 30)),
            trace('roof', 'non_paving', rectangle(8, 8, 18, 18)),
            trace('canopy', 'unknown', rectangle(20, 20, 28, 28))]
        opaque = np.ones((32, 32), bool); opaque[4, 4] = False
        labels, reasons = paving.rasterize(traces, (32, 32), opaque=opaque)
        self.assertEqual(labels[12, 12], 255); self.assertEqual(reasons[12, 12], paving.REASONS['conflicting_traces'])
        self.assertEqual(labels[24, 24], 255); self.assertEqual(reasons[24, 24], paving.REASONS['explicit_unknown'])
        self.assertEqual(labels[4, 4], 255); self.assertEqual(reasons[4, 4], paving.REASONS['source_nodata'])

    def test_invalid_rings_and_unsafe_trace_ids_are_rejected(self):
        for points in ([[0, 0], [30, 30], [0, 30], [30, 0]], rectangle(-1, 0, 10, 10)):
            with self.assertRaises(ValueError): paving.rasterize([trace('bad', 'paving', points)], (32, 32))
        with self.assertRaises(ValueError):
            paving.rasterize([trace('outside', 'paving', rectangle(2, 2, 10, 10), holes=[rectangle(20, 20, 25, 25)])], (32, 32))
        with self.assertRaises(ValueError): paving.rasterize([trace('../bad', 'paving', rectangle(1, 1, 30, 30))], (32, 32))
        with self.assertRaises(ValueError): paving.rasterize([trace('x', 'paving', rectangle(1, 1, 30, 30))], (32, 32), boundary_pixels=5)

    def test_native_crop_georeference_and_relative_dataset_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); items, ann = fixture(root); manifest = paving.build(items, ann, root/'dataset')
            row = manifest['records'][0]
            self.assertEqual(row['image_size'], [32, 32]); self.assertEqual(row['extent_epsg3857'], [132., 232., 196., 296.])
            self.assertEqual(row['split_group'], 'park'); self.assertFalse(manifest['human_labels_verified'])
            loaded = paving.validate(os.path.relpath(root/'dataset', Path.cwd()))
            self.assertEqual(loaded['id'], manifest['id']); self.assertTrue((root/'dataset/index.html').is_file())

    def test_resealed_mask_cannot_replace_literal_trace_supervision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); items, ann = fixture(root); manifest = paving.build(items, ann, root/'dataset')
            row = manifest['records'][0]; mask = root/'dataset'/row['mask_file']
            values = np.asarray(Image.open(mask)).copy(); values[5, 5] = 0; Image.fromarray(values).save(mask)
            row['mask_sha256'] = file_hash(mask); reseal(root/'dataset/dataset.json', manifest)
            with self.assertRaisesRegex(ValueError, 'differs from original crop/traces'): paving.validate(root/'dataset')

    def test_resealed_source_resize_or_relabelled_review_policy_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); items, ann = fixture(root); manifest = paving.build(items, ann, root/'dataset')
            original = copy.deepcopy(manifest); row = manifest['records'][0]; image = root/'dataset'/row['image_file']
            values = np.asarray(Image.open(image)).copy(); values[5, 5, 0] ^= 255; Image.fromarray(values).save(image)
            row['image_sha256'] = file_hash(image); reseal(root/'dataset/dataset.json', manifest)
            with self.assertRaisesRegex(ValueError, 'image differs'): paving.validate(root/'dataset')
            original['human_labels_verified'] = True; reseal(root/'dataset/dataset.json', original)
            with self.assertRaisesRegex(ValueError, 'research paving-mask policy'): paving.validate(root/'dataset')

    def test_original_hash_and_out_of_image_crops_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); items, ann = fixture(root); items[0]['source_sha256'] = '0'*64
            with self.assertRaisesRegex(ValueError, 'source or metadata changed'): paving.build(items, ann, root/'bad-source')
            items, ann = fixture(root); items[0]['crop_pixels'] = [16, 16, 80, 48]
            with self.assertRaisesRegex(ValueError, 'crop rectangle'): paving.build(items, ann, root/'bad-crop')

    def test_identical_original_cannot_be_split_across_parks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); items, ann = fixture(root); second = {**items[0], 'id': 'copy', 'site_id': 'another-park'}
            a = json.loads(ann.read_text()); a['crops']['copy'] = a['crops']['crop']; atomic_json(ann, a)
            with self.assertRaisesRegex(ValueError, 'cross park split groups'): paving.build([*items, second], ann, root/'bad-split')

    def test_distinct_originals_with_overlapping_crops_cannot_cross_park_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); items, ann = fixture(root)
            original = root/'second.png'; Image.new('RGB', (64, 64), (200, 200, 200)).save(original)
            metadata = root/'second-receipt.json'; receipt = json.loads((root/'receipt.json').read_text())
            receipt['image_sha256'] = file_hash(original); atomic_json(metadata, receipt)
            second = {**items[0], 'id': 'copy', 'site_id': 'another-park', 'source_file': str(original),
                'source_sha256': file_hash(original), 'metadata_file': str(metadata), 'metadata_sha256': file_hash(metadata)}
            a = json.loads(ann.read_text()); a['crops']['copy'] = a['crops']['crop']; atomic_json(ann, a)
            with self.assertRaisesRegex(ValueError, 'Overlapping imagery'): paving.build([*items, second], ann, root/'bad-split')

    def test_cli_resolves_sources_against_the_request_file(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); items, ann = fixture(root); request = root/'requests'; request.mkdir()
            for item in items:
                item['source_file'] = '../source.png'; item['metadata_file'] = '../receipt.json'
            atomic_json(request/'sources.json', items)
            with contextlib.redirect_stdout(io.StringIO()):
                paving.main(['build', '--sources', str(request/'sources.json'), '--annotations', str(ann), '--output', str(root/'dataset')])
            self.assertEqual(paving.validate(root/'dataset')['records'][0]['source_sha256'], file_hash(root/'source.png'))

    def test_binary_masks_are_not_silently_accepted_as_five_class_targets(self):
        from voxel_mapper.aerial_semantic_learning import read_dataset
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); items, ann = fixture(root); paving.build(items, ann, root/'dataset')
            with self.assertRaisesRegex(ValueError, 'provisional aerial semantic'): read_dataset(root/'dataset')


if __name__ == '__main__':
    unittest.main()
