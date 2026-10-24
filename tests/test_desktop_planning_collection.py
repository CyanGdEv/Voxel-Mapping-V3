from pathlib import Path
import tempfile
import unittest

from voxel_mapper.desktop_planning_collection_smoke import run


class DesktopPlanningCollectionTests(unittest.TestCase):
    def test_actual_worker_collects_multiple_batches_and_restarts_without_reanalysis(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt=run(Path(directory)/'smoke')
            self.assertEqual(receipt['status'],'passed')
            self.assertTrue(receipt['multiple_automatic_batches_verified'])
            self.assertTrue(receipt['restart_without_reanalysis_verified'])
            self.assertEqual(receipt['network_bytes'],0)
