"""Synthetic source-binding contracts; no physical ride labels are asserted."""
from concurrent.futures import CancelledError
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf

from voxel_mapper import ride_training as ride
from voxel_mapper import study_component_learning as reader
from voxel_mapper.building_spec import digest


def fixture(root):
    sources = root/'sources'
    sources.mkdir()
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=120, height=100)
        page.draw_polyline([(20, 40), (40, 40), (50, 30)], color=(.5, .3, .1))
        page.draw_rect(pymupdf.Rect(10, 70, 20, 80), color=(.5, .3, .1))
        page.draw_line((15, 75), (40, 40), color=(.5, .3, .1))
        raw = pdf.tobytes()
    sha = hashlib.sha256(raw).hexdigest()
    (sources/(sha+'.pdf')).write_bytes(raw)
    markings = {'coordinate_frame': 'pdf_native_points_y_up', 'document_sha256': sha, 'page': 1,
        'records': [{'role': 'track_centre', 'geometry_pdf_native': {'type': 'LineString', 'coordinates': [[20,60],[40,60],[50,70]]}},
            {'role': 'support_boundaries', 'geometry_pdf_native': {'type': 'MultiLineString', 'coordinates': [
                [[10,20],[20,20]], [[20,20],[20,30]], [[20,30],[10,30]], [[10,30],[10,20]], [[15,25],[40,60]]]}}]}
    path = root/'markings.json'
    path.write_text(json.dumps(markings))
    selectors = [{'type': 'centreline_span', 'start_vertex': 0, 'end_vertex': 2},
        {'type': 'support_symbol', 'index': 0}, {'type': 'support_line', 'index': 4}]
    review = {'version': ride.VERSION, 'coordinate_frame': 'pdf_native_points_y_up', 'ride_id': 'fixture-coaster',
        'site_id': 'fixture-park', 'review_basis': 'Synthetic source contract only',
        'source': {'document_sha256': sha, 'page': 1, 'markings_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'state': 'proposed', 'render_width_pixels': 400, 'url': 'https://example.org/fixture.pdf', 'rights_advisory': 'Synthetic test source'},
        'records': [{'id': 'component-'+str(i), 'selector': s, 'geometry_sha256': digest(g),
            'review_status': 'reviewed_source_selection', 'physical_geometry_verified': False,
            'trace_uncertainty_pdf_points': 1.} for i,(s,g) in enumerate(zip(selectors,ride.source_geometry(markings,selectors)))]}
    review_path = root/'review.json'
    review_path.write_text(json.dumps(review))
    return review_path, path, sources, review


class RideTrainingTests(unittest.TestCase):
    def test_training_accepts_only_ride_components_and_keeps_dataset_groups(self):
        manifest = {'dataset_kind': 'multi_source_reviewed_study_intake'}
        rows = [{'kind': 'ride_structure_trace', 'building_id': 'ride-carousel'}]
        with patch.object(reader, 'read_dataset', return_value=(manifest, rows, None, 'a'*64)), \
                patch('voxel_mapper.study_transfer_learning.train', return_value={'checked': True}) as fit:
            result = ride.train('dataset', 'output', encoder_path='encoder', encoder_sha256='b'*64)
            self.assertEqual(result, {'checked': True})
            self.assertEqual(fit.call_args.args, ('dataset', 'output'))
            rows[0]['kind'] = 'building'
            with self.assertRaisesRegex(ValueError, 'ride-only'):
                ride.train('dataset', 'other', encoder_path='encoder', encoder_sha256='b'*64)
            self.assertEqual(fit.call_count, 1)

    def test_original_native_pairs_remain_one_ride_group_and_track_stays_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rp, mp, sources, _ = fixture(root)
            result = ride.build(rp, mp, sources, root/'dataset')
            _, rows, _, _ = reader.read_dataset(root/'dataset')
            self.assertEqual(len(rows), 3)
            self.assertEqual(len(result['groups']), 1)
            track = next(r for r in rows if r['kind'] == 'ride_track_centreline')
            self.assertEqual(track['target_geometry']['coordinates'], [[20,60],[40,60],[50,70]])
            scope = result['ride_learning_scope']
            self.assertIsNone(scope['held_ride_accuracy'])
            self.assertEqual(scope['verified_3d_support_targets'], 0)
            self.assertEqual(scope['metric_height_targets'], 0)
            self.assertFalse(scope['world_variants_are_training_targets'])
            self.assertTrue(all(r['original_pdf_verified'] for r in rows))
            self.assertTrue(all(not r['physical_geometry_verified'] for r in rows))

    def test_generated_unreviewed_forged_and_outside_targets_fail_atomically(self):
        for mode in ['generated', 'unreviewed', 'forged', 'outside', 'physical']:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                rp, mp, sources, review = fixture(root)
                row = review['records'][0]
                if mode == 'generated': row['selector'] = {'type': 'generated_support_member'}
                elif mode == 'unreviewed': row['review_status'] = 'unreviewed'
                elif mode == 'forged': row['geometry_sha256'] = 'f'*64
                elif mode == 'outside': row['selector']['end_vertex'] = 9
                else: row['physical_geometry_verified'] = True
                rp.write_text(json.dumps(review))
                with self.assertRaises(ValueError): ride.build(rp, mp, sources, root/'dataset')
                self.assertFalse((root/'dataset').exists())

    def test_changed_source_or_markings_are_not_used(self):
        for mode in ['pdf', 'markings']:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                rp, mp, sources, _ = fixture(root)
                path = next(sources.glob('*.pdf')) if mode == 'pdf' else mp
                path.write_bytes(path.read_bytes()+b' ')
                with self.assertRaises(ValueError): ride.build(rp, mp, sources, root/'dataset')
                self.assertFalse((root/'dataset').exists())

    def test_cancellation_and_fresh_output_are_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rp, mp, sources, _ = fixture(root)
            with self.assertRaises(CancelledError):
                ride.build(rp, mp, sources, root/'dataset', cancelled=lambda: True)
            self.assertFalse((root/'dataset').exists())
            (root/'dataset').mkdir()
            with self.assertRaisesRegex(ValueError, 'Fresh'):
                ride.build(rp, mp, sources, root/'dataset')


if __name__ == '__main__':
    unittest.main()
