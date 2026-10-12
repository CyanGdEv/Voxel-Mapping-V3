import json
import unittest
from unittest.mock import patch

from tests import test_area_reconstruction as source_fixtures
from voxel_mapper.area_cycles import prepare, run_local, validate_bundle


class AutomaticAreaTests(unittest.TestCase):
    setUp = source_fixtures.AreaSourceTests.setUp
    tearDown = source_fixtures.AreaSourceTests.tearDown

    def test_full_pass_skips_blockers_and_does_not_repeat_finished_scan(self):
        self.config['areas'][0]['application_references'] = []
        self.job.write_text(json.dumps(self.config))
        state = run_local(self.job, 3)
        self.assertEqual(state['status'], 'completed_with_blockers')
        self.assertEqual(state['cursor'], 2)
        self.assertEqual(state['published_cycles'], 0)
        self.assertEqual(state['areas']['a']['status'], 'awaiting_applications')
        self.assertEqual(state['areas']['b']['status'], 'awaiting_reconstruction')
        with patch('voxel_mapper.area_cycles.run', side_effect=AssertionError('Unexpected rescan')):
            self.assertEqual(prepare(self.job), state)

    def test_one_area_error_does_not_prevent_later_source_scan(self):
        from voxel_mapper.area_reconstruction import run
        def fail_first(*args):
            if args[-1] == 'a':
                raise ValueError('Area source failure')
            return run(*args)
        with patch('voxel_mapper.area_cycles.run', side_effect=fail_first):
            state = prepare(self.job)
        self.assertEqual(state['areas']['a']['status'], 'area_error')
        self.assertEqual(state['areas']['b']['status'], 'awaiting_reconstruction')
        self.assertEqual(state['published_cycles'], 0)

    def test_checkpoint_rejects_changed_inputs_before_running_an_area(self):
        prepare(self.job)
        self.config['areas'].reverse()
        self.job.write_text(json.dumps(self.config))
        with self.assertRaisesRegex(ValueError, 'inputs changed'):
            prepare(self.job)

    def test_actions_bundle_rejects_external_paths(self):
        validate_bundle(self.job, self.root)
        self.config['source_directories'] = ['/outside/sources']
        self.job.write_text(json.dumps(self.config))
        with self.assertRaisesRegex(ValueError, 'Nonportable'):
            validate_bundle(self.job, self.root)


if __name__ == '__main__':
    unittest.main()
