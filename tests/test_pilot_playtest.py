"""Gameplay instructions remain bound to a world and cannot become evidence."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from voxel_mapper.pilot_playtest import write


class PlaytestTests(unittest.TestCase):
    def fixture(self, root):
        # Instruction generation only: this is not a Minecraft archive fixture.
        data = b'world-byte-binding-fixture'
        (root / 'park.mcworld').write_bytes(data)
        route = {'status': 'native_route_ready', 'doorway_index': 1, 'horizontal_length_m': 2,
                 'route_local_x_z_half_y': [[-1, 1, 4], [0, 1, 5], [1, 1, 5]],
                 'route_native_xyz': [[-.5, 66, -.5], [.5, 66.5, -.5], [1.5, 66.5, -.5]]}
        world = {'file': 'park.mcworld', 'sha256': hashlib.sha256(data).hexdigest(),
                 'target_version': [1, 21, 130], 'spawn': [-1, 66, -1]}
        return {'world': world, 'review_component': {'status': 'estimated'}, 'generation_errors': 3,
                'access_review': {'native_readback': {
                    'unresolved_opening_ids': ['blocked-door'],
                    'openings': [{'id': 'door', 'walkthrough': route},
                                 {'id': 'blocked-door', 'walkthrough': {**route, 'status': 'unresolved',
                                     'doorway_index': None, 'horizontal_length_m': None,
                                     'route_local_x_z_half_y': [], 'route_native_xyz': []}}]}}}

    def test_guide_and_empty_form_separate_native_routes_from_human_outcomes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = self.fixture(root)
            summary = write(root, report)
            guide = (root / 'playtest-guide.md').read_text()
            form = json.loads((root / 'playtest-results.json').read_text())
            routes = json.loads((root / 'playtest-routes.json').read_text())
            self.assertEqual(summary['ready_entrance_routes'], 1)
            self.assertEqual(summary['unresolved_entrance_routes'], 1)
            self.assertIn('/tp @s -0.5 66 -0.5', guide)
            self.assertIn('| 1 | 0.5 | 66.5 | -0.5 | Entrance crossing |', guide)
            self.assertIn('Unresolved by native checks', guide)
            self.assertIn('Reported generation errors: 3', guide)
            self.assertIn(report['world']['sha256'], guide)
            self.assertEqual(form['world'], routes['world'])
            self.assertTrue(all(check['outcome'] == 'not_run' for check in form['checks']))
            self.assertTrue(all(value is None for value in form['observer'].values()))
            self.assertEqual(form['status'], 'awaiting_minecraft_playtest')
            self.assertEqual(form['training_labels_generated'], 0)
            self.assertFalse(form['accepted_physical_geometry'])

    def test_changed_world_cannot_receive_instructions_bound_to_its_old_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = self.fixture(root)
            (root / 'park.mcworld').write_bytes(b'different-world')
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                write(root, report)
            self.assertFalse((root / 'playtest-results.json').exists())


if __name__ == '__main__':
    unittest.main()
