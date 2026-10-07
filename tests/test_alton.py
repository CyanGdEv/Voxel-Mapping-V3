import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from voxel_mapper.alton import acquire_alton, download_pdf
from voxel_mapper.alton_registration import fit_axis_labels


class AltonTests(unittest.TestCase):
    def labels(self):
        return [{'axis': axis, 'position': i*100, 'value': base+i*20}
                for axis, base in [('E', 407500), ('N', 343000)] for i in range(4)]

    def test_alignment_is_bounded_hypothesis_never_verified_geometry(self):
        report = fit_axis_labels(self.labels(), [-1.91, 52.97, -1.86, 53.01])
        self.assertEqual(report['status'], 'native_label_alignment_hypothesis')
        self.assertFalse(report['registration_verified'])
        self.assertEqual(report['world_geometry_additions'], 0)
        self.assertAlmostEqual(report['axes']['E']['slope'], .2)
        self.assertEqual(fit_axis_labels(self.labels(), [-.52, 51.4, -.5, 51.42])['status'], 'unavailable')

    def test_bad_label_is_rejected_by_withheld_checks(self):
        labels = self.labels()
        labels[1]['value'] += 5
        self.assertEqual(fit_axis_labels(labels, [-1.91, 52.97, -1.86, 53.01])['status'], 'unavailable')

    def test_shifted_border_label_is_excluded_without_relaxing_residual(self):
        labels = [{'axis': axis, 'position': i*100, 'value': base+i*20}
                  for axis, base in [('E', 407500), ('N', 343000)] for i in range(7)]
        labels[6]['position'] -= 6
        report = fit_axis_labels(labels, [-1.91, 52.97, -1.86, 53.01])
        self.assertEqual(report['status'], 'native_label_alignment_hypothesis')
        self.assertEqual(len(report['axes']['E']['excluded_label_origins']), 1)
        self.assertLess(report['axes']['E']['max_withheld_error_nominal_m'], .01)

    def test_unexpected_host_is_rejected_before_network(self):
        with patch('requests.Session') as session:
            with self.assertRaises(ValueError):
                download_pdf(session, 'https://other.example/plan.pdf')
            session.get.assert_not_called()

    def test_cache_hash_mismatch_is_not_inspected_or_promoted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalogue = json.loads((Path(__file__).parents[1]/'voxel_mapper/data/alton-planning-catalogue.json').read_text())
            path = root/catalogue['entries'][0]['file']
            path.parent.mkdir(parents=True)
            path.write_bytes(b'%PDF-corrupted')
            with patch('voxel_mapper.council.inspect_pdf') as inspect:
                result = acquire_alton(root, cache=root, max_documents=1)
            inspect.assert_not_called()
            self.assertIn('checksum mismatch', result['failures'][0]['reason'])
            self.assertEqual(result['geometry_records'], [])
            self.assertEqual(result['status'], 'partial')
