"""Exercise the actual Arrow runtime and bounded worker without live network."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pyarrow as pa
from overturemaps import record_batch_reader
from shapely.geometry import box
from shapely import to_wkb

from voxel_mapper.overture_worker import main, record_to_feature


class OvertureWorkerTests(unittest.TestCase):
    def test_numpy_arrow_and_overture_runtime(self):
        values = np.array([1.25, 2.5], dtype=np.float64)
        np.testing.assert_array_equal(pa.array(values).to_numpy(), values)
        self.assertTrue(callable(record_batch_reader))

    def row(self):
        return {'id': 'runtime-building', 'geometry': to_wkb(box(0, 0, 1, 1))}

    def run_worker(self, root, rows, byte_limit=10000, count_limit=10):
        destination = root / 'buildings.jsonl'
        batch = pa.RecordBatch.from_pylist(rows)
        args = ['overture_worker', '2026-09-23.1', '[0,0,0.001,0.001]',
                str(destination), str(count_limit), str(byte_limit)]
        # Exercise the Windows path on Linux CI too. The explicit byte guard
        # must work without the optional Unix process limit.
        with patch.object(sys, 'argv', args), patch.dict(sys.modules, {'resource': None}), \
                patch('overturemaps.record_batch_reader', return_value=iter([batch])) as reader:
            main()
        reader.assert_called_once_with('building', bbox=[0, 0, .001, .001],
                                      release='2026-09-23.1', connect_timeout=10,
                                      request_timeout=30, stac=True)
        return destination

    def test_exact_byte_budget_includes_newline(self):
        row = self.row()
        expected = (json.dumps(record_to_feature(row)) + '\n').encode('utf-8')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination = self.run_worker(root, [row], byte_limit=len(expected))
            self.assertEqual(destination.read_bytes(), expected)
            with self.assertRaisesRegex(ValueError, 'byte budget'):
                self.run_worker(root, [row], byte_limit=len(expected) - 1)
            self.assertEqual(destination.read_bytes(), b'')

    def test_multiple_records_cannot_exceed_output_or_feature_budget(self):
        row = self.row()
        record_size = len((json.dumps(record_to_feature(row)) + '\n').encode('utf-8'))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for budgets, reason in [({'byte_limit': record_size}, 'byte budget'),
                                    ({'count_limit': 1}, 'feature budget')]:
                with self.subTest(budgets=budgets), self.assertRaisesRegex(ValueError, reason):
                    self.run_worker(root, [row, row], **budgets)
                data = (root / 'buildings.jsonl').read_bytes()
                self.assertEqual(len(data), record_size)
                self.assertEqual(len(data.splitlines()), 1)
