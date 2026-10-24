from pathlib import Path
import tempfile
import unittest

from voxel_mapper.desktop_web_smoke import run


class DesktopWebTests(unittest.TestCase):
    def test_actual_worker_retains_cited_sources_across_restart_without_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt=run(Path(directory)/'smoke')
            self.assertEqual(receipt['status'],'passed')
            self.assertTrue(receipt['offline_worker_verified'])
            self.assertTrue(receipt['persistent_restart_verified'])
