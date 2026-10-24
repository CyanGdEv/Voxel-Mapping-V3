from pathlib import Path
import tempfile
import unittest

from voxel_mapper.desktop_app import JOB_KINDS
from voxel_mapper.desktop_runtime import DesktopRuntime, HEAVY, _wait, write_json
from test_planning_area_pilot import fixture


class DesktopPlanningPilotTests(unittest.TestCase):
    def test_managed_worker_persists_source_pack_without_training_or_geometry_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sources=root/'originals';sources.mkdir();config=fixture(sources)
            config['source_directory']='originals';write_json(root/'pilot.json',config)
            runtime=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
            try:
                jid=runtime.submit('planning_source_pilot',root/'pilot.json')
                job=_wait(runtime,jid,timeout=60)
                runtime._futures[jid].result(timeout=10)
                self.assertEqual(job['status'],'completed',job)
                result=job['result'];output=Path(job['output_directory'])
                self.assertEqual(result['summary']['completed_pages'],1)
                self.assertTrue((output/'review.html').is_file())
                self.assertIsNone(result['summary']['geometric_accuracy'])
                self.assertEqual(result['park_world_blocks_added'],0)
                self.assertFalse(result['world_placement_eligible'])
                self.assertEqual(runtime.store.summary()['feedback_records'],0)
                self.assertEqual(runtime.store.summary()['checkpoints'],0)
                self.assertIn('planning_source_pilot',HEAVY)
                self.assertIn('planning_source_pilot',dict(JOB_KINDS).values())
            finally:runtime.close(wait=True)
            reopened=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
            try:
                saved=reopened.store.job(jid)
                self.assertEqual(saved['status'],'completed')
                self.assertEqual(saved['result']['summary'],result['summary'])
            finally:reopened.close(wait=True)
