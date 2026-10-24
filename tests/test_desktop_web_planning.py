from pathlib import Path
import tempfile
import unittest

from voxel_mapper.desktop_web_planning_smoke import run


class DesktopWebPlanningTests(unittest.TestCase):
    def test_single_cached_application_becomes_analysed_drawings_and_persistent_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt=run(Path(directory)/'smoke')
            self.assertEqual(receipt['status'],'passed')
            self.assertTrue(receipt['single_application_url_to_original_analysis'])
            self.assertTrue(receipt['persistent_restart_verified'])
