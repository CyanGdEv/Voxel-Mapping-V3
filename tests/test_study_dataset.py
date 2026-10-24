"""Independent source-pixel, target-mask, provenance and leakage checks."""
import copy
from concurrent.futures import CancelledError
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf
from PIL import Image

from voxel_mapper.building_spec import digest
from voxel_mapper import study_dataset as dataset


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def polygon(frame='page_points'):
    rings = [
        [[40., 35.], [100., 35.], [100., 115.], [40., 115.], [40., 35.]],
        [[60., 65.], [80., 65.], [80., 85.], [60., 85.], [60., 65.]],
    ]
    if frame == 'render_pixels':
        rings = [[[x*2, y*2] for x, y in ring] for ring in rings]
    elif frame == 'native_y_up':
        rings = [[[x, 160-y] for x, y in ring] for ring in rings]
    return {'type': 'Polygon', 'coordinates': rings}


def fixture(root, *, rotation=0, user_unit=None, frames=('page_points',)):
    repo = root/'repo'
    sources = root/'sources'
    repo.mkdir(); sources.mkdir()
    with pymupdf.open() as document:
        page = document.new_page(width=200, height=160)
        page.draw_rect(pymupdf.Rect(40, 35, 100, 115), fill=(0, 0, 0), color=None)
        page.draw_rect(pymupdf.Rect(60, 65, 80, 85), fill=(1, 1, 1), color=None)
        # This real source mark lies inside the target's hole. A training input
        # must preserve it, even though the reviewed object mask is empty here.
        page.draw_rect(pymupdf.Rect(64, 68, 68, 72), fill=(0, 0, 0), color=None)
        page.insert_text((120, 40), 'Source drawing', fontsize=8)
        if user_unit is not None:
            document.xref_set_key(page.xref, 'UserUnit', str(user_unit))
        page.set_rotation(rotation)
        data = document.tobytes()
    source_sha = hashlib.sha256(data).hexdigest()
    pdf = sources/(source_sha+'.pdf')
    pdf.write_bytes(data)
    with pymupdf.open(pdf) as document:
        page = document[0]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(400/page.rect.width, 400/page.rect.width),
            colorspace=pymupdf.csRGB, alpha=False)
        frame_pin = {'render_width_pixels': 400, 'render_size_pixels': [pix.width, pix.height],
            'render_samples_sha256': hashlib.sha256(pix.samples).hexdigest()}
    records = []
    for index, frame in enumerate(frames):
        records.append({'id': 'reviewed-object-'+str(index), 'building_id': 'building-a',
            'kind': 'wall', 'source': {'document_sha256': source_sha, 'page': 1,
                'coordinate_frame': frame, **frame_pin},
            'target_geometry': polygon(frame), 'review_refs': [],
            'evidence_level': 'reviewed_source_trace', 'source_state': 'proposed',
            'assumptions': ['Only the reviewed source-drawing polygon is labelled.']})
    review = repo/'annotations'/'review.json'
    review.parent.mkdir()
    review.write_text(json.dumps({'records': records}, indent=2), encoding='utf-8')
    review_sha = sha(review)
    for index, record in enumerate(records):
        record['review_refs'] = [{'path': 'annotations/review.json', 'sha256': review_sha,
            'pointer': '/records/'+str(index)+'/target_geometry'}]
    catalogue = {'version': 'retained-study-examples-v1', 'records': records,
        'input_sha256': {'annotations/review.json': review_sha},
        'documents': [{'document_sha256': source_sha, 'url': 'https://example.org/study.pdf'}],
        'excluded': [{'id': 'estimated-rear-wall', 'reason': 'Hypothetical closure, not a measured target.'}]}
    return repo, sources, pdf, catalogue


def export(root, *, catalogue=None, rotation=0, frames=('page_points',), user_unit=None):
    repo, sources, pdf, original = fixture(root, rotation=rotation, frames=frames, user_unit=user_unit)
    if catalogue is None:
        catalogue = original
    output = root/'export'
    result = dataset.build(catalogue, sources, output, repo_root=repo)
    return result, output, repo, sources, pdf, catalogue


def mapped_pixel(record, point):
    a, b, c, d, e, f = record['crop_to_input_matrix']
    x, y = point
    return round(a*x+c*y+e), round(b*x+d*y+f)


def assert_sample(test, image, point, expected, tolerance=2):
    x, y = point
    values = [image.getpixel((xx, yy)) for xx in range(max(0, x-1), min(image.width, x+2))
        for yy in range(max(0, y-1), min(image.height, y+2))]
    test.assertLessEqual(min(abs(value-expected) for value in values), tolerance,
        'Expected source-aligned pixel '+str((point, expected, values)))


class StudyDatasetTests(unittest.TestCase):
    def test_source_pixels_holes_and_exact_targets_survive_all_three_coordinate_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, sources, pdf, catalogue = fixture(root,
                frames=('render_pixels', 'page_points', 'native_y_up'))
            before = copy.deepcopy(catalogue)
            pdf_bytes = pdf.read_bytes()
            review = repo/'annotations/review.json'
            review_bytes = review.read_bytes()
            result = dataset.build(catalogue, sources, root/'export', repo_root=repo)
            output = root/'export'
            self.assertEqual(catalogue, before)
            self.assertEqual(pdf.read_bytes(), pdf_bytes)
            self.assertEqual(review.read_bytes(), review_bytes)
            self.assertEqual(result['summary']['source_paired_examples'], 3)
            self.assertEqual(result['summary']['source_groups'], 1)
            self.assertEqual(result['whole_building_feedback_records_generated'], 0)
            self.assertFalse(result['model_weights_updated'])
            self.assertFalse(result['world_placement_eligible'])
            self.assertEqual(result['id'], digest({k: v for k, v in result.items() if k != 'id'}))
            self.assertEqual(json.loads((output/'dataset.json').read_text()), result)
            for name, pin in result['output_sha256'].items():
                self.assertEqual(sha(output/name), pin, name)
            input_images = []
            mask_images = []
            for record in result['records']:
                self.assertTrue(record['learning_eligible'])
                self.assertFalse(record['physical_geometry_verified'])
                self.assertTrue(record['original_pdf_verified'])
                self.assertEqual(record['record_sha256'], digest({k: v for k, v in record.items() if k != 'record_sha256'}))
                target = json.loads((output/record['target_file']).read_text())
                expected = next(r for r in catalogue['records'] if r['id'] == record['id'])
                self.assertEqual(target['source_geometry'], expected['target_geometry'])
                with Image.open(output/record['input_file']) as image, Image.open(output/record['target_mask_file']) as mask:
                    self.assertEqual(image.size, (128, 128))
                    self.assertEqual(image.mode, 'L')
                    self.assertEqual(mask.size, (128, 128))
                    self.assertEqual(set(mask.getdata()), {0, 255})
                    # Unrotated source page is exactly doubled in the full raster.
                    black_object = mapped_pixel(record, (100, 90))
                    white_hole = mapped_pixel(record, (148, 156))
                    source_ink_in_hole = mapped_pixel(record, (132, 140))
                    assert_sample(self, image, black_object, 0)
                    assert_sample(self, mask, black_object, 255)
                    assert_sample(self, image, white_hole, 255)
                    assert_sample(self, mask, white_hole, 0)
                    assert_sample(self, image, source_ink_in_hole, 0)
                    assert_sample(self, mask, source_ink_in_hole, 0)
                    input_images.append(image.tobytes())
                    mask_images.append(mask.tobytes())
            self.assertEqual(len(set(input_images)), 1)
            self.assertEqual(len(set(mask_images)), 1)
            self.assertIn('reviewed-object', (output/'index.html').read_text())
            # Retained review bytes, not just their filenames, must be portable.
            copied = [p for p in output.rglob('review.json')]
            self.assertEqual(len(copied), 1)
            self.assertEqual(copied[0].read_bytes(), review_bytes)

    def test_page_and_native_coordinates_align_after_original_pdf_rotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, output, _, _, _, _ = export(Path(tmp), rotation=90,
                frames=('page_points', 'native_y_up'))
            self.assertEqual(len(result['records']), 2)
            images, masks = [], []
            for record in result['records']:
                target = json.loads((output/record['target_file']).read_text())
                ring = target['render_geometry']['coordinates'][0]
                xs, ys = zip(*ring)
                # For a 200x160 page rotated90deg and rendered400px wide:
                # displayed x=160-y, displayed y=x, scale=2.5.
                self.assertAlmostEqual(min(xs), 112.5)
                self.assertAlmostEqual(max(xs), 312.5)
                self.assertAlmostEqual(min(ys), 100.)
                self.assertAlmostEqual(max(ys), 250.)
                with Image.open(output/record['input_file']) as image, Image.open(output/record['target_mask_file']) as mask:
                    ink = mapped_pixel(record, ((160-45)*2.5, 50*2.5))
                    hole = mapped_pixel(record, ((160-78)*2.5, 74*2.5))
                    assert_sample(self, image, ink, 0)
                    assert_sample(self, mask, ink, 255)
                    assert_sample(self, image, hole, 255)
                    assert_sample(self, mask, hole, 0)
                    images.append(image.tobytes());masks.append(mask.tobytes())
            self.assertEqual(images[0], images[1])
            self.assertEqual(masks[0], masks[1])

    def test_connected_groups_close_transitive_building_and_pdf_bridges_without_variant_leakage(self):
        def row(identifier, building, source):
            return {'id': identifier, 'building_id': building, 'source': {'document_sha256': source*64}}
        records = [row('a', 'shop', '1'), row('b', 'shop', '2'),
            row('c', 'station', '2'), row('d', 'station', '3'), row('e', 'tower', '4')]
        groups = dataset.connected_groups(records)
        self.assertEqual(len(groups), 2)
        combined = next(g for g in groups if 'a' in g['record_ids'])
        self.assertEqual(combined['record_ids'], ['a', 'b', 'c', 'd'])
        self.assertEqual(combined['building_ids'], ['shop', 'station'])
        self.assertEqual(combined['source_sha256'], ['1'*64, '2'*64, '3'*64])
        self.assertEqual(combined['group_id'], digest({'building_ids': ['shop', 'station'],
            'source_sha256': ['1'*64, '2'*64, '3'*64]}))
        self.assertEqual(dataset.connected_groups(list(reversed(records))), groups)

    def test_missing_or_changed_originals_and_stale_render_pins_are_explicit_gaps(self):
        for mode in ('missing', 'changed', 'raster'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                repo, sources, pdf, catalogue = fixture(root)
                if mode == 'missing':
                    pdf.unlink()
                elif mode == 'changed':
                    pdf.write_bytes(pdf.read_bytes()+b' changed')
                else:
                    catalogue['records'][0]['source']['render_samples_sha256'] = '0'*64
                output = root/'export'
                result = dataset.build(catalogue, sources, output, repo_root=repo)
                self.assertEqual(result['records'], [])
                self.assertEqual(result['status'], 'source_paired_dataset_with_gaps')
                self.assertTrue(result['withheld'])
                self.assertEqual(list(output.glob('examples/*/input.png')), [])
                self.assertEqual(result['summary']['original_pdfs_verified'], 0)

    def test_unsupported_units_outside_targets_and_conflicting_frame_proofs_are_withheld(self):
        for mode in ('unit', 'outside', 'frame'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                repo, sources, _, catalogue = fixture(root, user_unit=2 if mode == 'unit' else None,
                    frames=('page_points', 'page_points') if mode == 'frame' else ('page_points',))
                if mode == 'outside':
                    catalogue['records'][0]['target_geometry'] = {'type': 'Polygon',
                        'coordinates': [[[190, 150], [210, 150], [210, 170], [190, 170], [190, 150]]]}
                if mode == 'frame':
                    catalogue['records'][1]['source']['render_size_pixels'] = [400, 999]
                result = dataset.build(catalogue, sources, root/'export', repo_root=repo)
                invalid = 'reviewed-object-1' if mode == 'frame' else 'reviewed-object-0'
                self.assertNotIn(invalid, {r['id'] for r in result['records']})
                self.assertTrue(any(r['id'] == invalid for r in result['withheld']))

    def test_conditional_and_illustrative_parts_never_become_supervised_examples(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, sources, _, catalogue = fixture(root, frames=('page_points',)*3)
            catalogue['records'][1]['evidence_level'] = 'conditional_assembly'
            catalogue['records'][2]['evidence_level'] = 'illustrative_display'
            result = dataset.build(catalogue, sources, root/'export', repo_root=repo)
            self.assertEqual([r['id'] for r in result['records']], ['reviewed-object-0'])
            self.assertEqual(len(result['withheld']), 2)
            self.assertEqual(result['whole_building_feedback_records_generated'], 0)
            self.assertFalse(result['model_weights_updated'])

    def test_changed_review_assets_or_invalid_pointers_fail_without_a_partial_dataset(self):
        for mode in ('review_bytes', 'pointer', 'reference_pin'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                repo, sources, _, catalogue = fixture(root)
                if mode == 'review_bytes':
                    review = repo/'annotations/review.json'
                    review.write_bytes(review.read_bytes()+b' ')
                elif mode == 'pointer':
                    catalogue['records'][0]['review_refs'][0]['pointer'] = '/missing/geometry'
                else:
                    catalogue['records'][0]['review_refs'][0]['sha256'] = 'f'*64
                with self.assertRaises((ValueError, KeyError)):
                    dataset.build(catalogue, sources, root/'export', repo_root=repo)
                self.assertFalse((root/'export').exists())
                self.assertFalse(list(root.glob('study-dataset-*')))

    def test_cancellation_before_and_during_export_cleans_staging_and_existing_outputs_survive(self):
        for mode in ('before', 'during', 'existing'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                repo, sources, _, catalogue = fixture(root)
                output = root/'export'
                if mode == 'existing':
                    output.mkdir();sentinel = output/'keep';sentinel.write_bytes(b'original')
                    with self.assertRaises(ValueError):
                        dataset.build(catalogue, sources, output, repo_root=repo)
                    self.assertEqual(sentinel.read_bytes(), b'original')
                else:
                    stopped = [mode == 'before']
                    def progress(value):
                        stopped[0] = True
                    with self.assertRaises(CancelledError):
                        dataset.build(catalogue, sources, output, repo_root=repo,
                            cancelled=lambda: stopped[0], progress=progress)
                    self.assertFalse(output.exists())
                self.assertFalse(list(root.glob('study-dataset-*')))

    def test_output_budget_failure_publishes_no_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, sources, _, catalogue = fixture(root)
            with patch.object(dataset, 'MAX_OUTPUT_BYTES', 100), self.assertRaises(ValueError):
                dataset.build(catalogue, sources, root/'export', repo_root=repo)
            self.assertFalse((root/'export').exists())
            self.assertFalse(list(root.glob('study-dataset-*')))


if __name__ == '__main__':
    unittest.main()
