"""Whole-area walking witnesses, scope boundaries and saved distant obstacles."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import amulet
from amulet.api.block import Block

from voxel_mapper.bedrock import export_world
from voxel_mapper.pilot_access import Scene, _read_inputs, _scene, _mapped_nodes, prepare, verify_saved
from voxel_mapper.pilot_navigation import inspect, _tree
import test_pilot_access as fixtures


class NavigationTests(unittest.TestCase):
    def test_terrain_connection_is_not_continuous_mapped_paving(self):
        scene = Scene({(x, 0): [(0, 2, 2)] for x in range(6)}, (0, 0, 5, 0))
        mapped = {(x, 0, 2): 'west' if x < 2 else 'east' for x in (0, 1, 4, 5)}
        paths = {(x, 0, 0): {'x': x, 'y': 0, 'z': 0, 'kind': 'path', 'feature': name}
                 for (x, _, _), name in mapped.items()}
        report = inspect(scene, (0, 0, 2), mapped, paths, dict(paths), 64, ['missing/bridge'])
        self.assertEqual(report['mapped_reachable_cells_any_walking'], 4)
        self.assertEqual(report['mapped_reachable_cells_on_walking_surfaces'], 2)
        self.assertEqual(len(report['walking_components']), 2)
        detour = next(route for route in report['walkthroughs'] if route['id'] == 'terrain-detour')
        self.assertEqual(detour['route_native_xyz'], [[x + .5, 65, .5] for x in range(6)])
        self.assertEqual(detour['minecraft_playtest'], 'not_performed')
        self.assertEqual(report['withheld_feature_ids_not_audited_as_geometry'], ['missing/bridge'])

    def test_full_steps_and_blocked_paving_remain_unresolved(self):
        scene = Scene({(0, 0): [(0, 2, 2)], (1, 0): [(0, 2, 2)],
                       (2, 0): [(0, 4, 4)], (3, 0): [(0, 4, 4), (6, 8, 8)]}, (0, 0, 3, 0))
        paths = {(x, 0 if x < 2 else 1, 0): {'x': x, 'y': 0 if x < 2 else 1,
                  'z': 0, 'kind': 'path', 'feature': 'paving'} for x in range(4)}
        mapped = {(x, 0, 2 if x < 2 else 4): 'paving' for x in range(3)}
        report = inspect(scene, (0, 0, 2), mapped, paths, dict(paths), 0, [])
        self.assertEqual(report['status'], 'partial_or_unresolved')
        self.assertEqual(report['mapped_reachable_cells_any_walking'], 2)
        self.assertEqual(report['features'][0]['blocked_or_unsupported_cells'], 1)
        self.assertEqual(report['adjacent_walking_surface_barriers'], 1)
        self.assertEqual(report['barrier_examples'][0]['reason'], 'step_exceeds_half_metre')

    def test_unsupported_emitted_cells_cannot_receive_an_all_reachable_status(self):
        scene = Scene({(0, 0): [(0, 2, 2)]}, (0, 0, 1, 0))
        paths = {(x, 0, 0): {'x': x, 'y': 0, 'z': 0, 'kind': 'path', 'feature': 'paving'} for x in range(2)}
        report = inspect(scene, (0, 0, 2), {(0, 0, 2): 'paving'}, paths, dict(paths), 0, [])
        self.assertEqual(report['status'], 'partial_or_unresolved')

    def test_graph_budget_rejects_instead_of_claiming_partial_work_complete(self):
        scene = Scene({(x, 0): [(0, 2, 2)] for x in range(5)}, (0, 0, 4, 0))
        with patch('voxel_mapper.pilot_navigation.MAX_SEARCH_STATES', 2):
            with self.assertRaisesRegex(ValueError, 'graph budget'):
                _tree(scene, (0, 0, 2))

    def test_equal_priority_alias_keeps_the_actual_composed_junction(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = {'x': 0, 'y': 0, 'z': 0, 'kind': 'path', 'feature': 'first'}
            second = {**first, 'feature': 'second'}
            (root / 'voxels.jsonl').write_text(json.dumps(first) + '\n' + json.dumps(second) + '\n')
            records, _, paths, bounds = _read_inputs(root, {'anchor_local_m': [0, 0]})
            self.assertEqual(_mapped_nodes(_scene(records, bounds), paths, records), {(0, 0, 2): 'first'})
            self.assertEqual(records[0, 0, 0], first)

    def test_whole_area_column_budget_is_not_expanded_by_sparse_faraway_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = [{'x': x, 'y': 0, 'z': z, 'kind': 'terrain'} for x, z in [(0, 0), (300, 300)]]
            (root / 'voxels.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
            with self.assertRaisesRegex(ValueError, 'column budget'):
                _read_inputs(root, {'anchor_local_m': [0, 0]}, whole_area=True)

    def far_loop(self, root):
        helper = fixtures.AccessWorldTests()
        quality, component, rows = helper.fixture(root, second_door=True)
        component['access_openings'][0]['id'] = 'a-first-door'
        rows = [row for row in rows if row.get('feature') != 'osm/test-path']
        rows += [dict(x=x, y=0, z=z, kind='terrain') for x in range(-5, 6) for z in range(7, 41)]
        columns = {(-1, z) for z in range(1, 36)} | {(4, z) for z in range(1, 36)} | {(x, 35) for x in range(-1, 5)}
        rows += [dict(x=x, y=2, z=z, kind='path', feature='osm/far-loop', material='stone') for x, z in sorted(columns)]
        (root / 'voxels.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
        quality['voxel_records'] = len(rows)
        return quality, component

    def test_wider_native_audit_proves_an_exterior_route_beyond_the_old_radius(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, component = self.far_loop(root)
            prepared = prepare(root, quality, component, {'policy': 'estimated_each_opening_approach_v2', 'audit_scope': 'whole_pilot'})
            world = export_world(root / 'voxels.jsonl', root, quality)
            prepared['audit_scope'] = 'component_neighbourhood'
            old = verify_saved(root / 'bedrock-world', world['vertical_offset_blocks'], world['spawn'], prepared)
            self.assertIn('other-door', old['native_readback']['unresolved_opening_ids'])
            prepared['audit_scope'] = 'whole_pilot'
            report = verify_saved(root / 'bedrock-world', world['vertical_offset_blocks'], world['spawn'], prepared)
            self.assertEqual(report['native_readback']['unresolved_opening_ids'], [])
            route = next(o for o in report['native_readback']['openings'] if o['id'] == 'other-door')['walkthrough']
            self.assertTrue(any(p[1] == 35 for p in route['route_local_x_z_half_y']))
            self.assertTrue((root / 'navigation-review.svg').is_file())
            # A saved obstruction outside the old radius must invalidate the
            # exterior witness, despite unchanged planned/input geometry.
            level = amulet.load_level(str(root / 'bedrock-world'))
            try:
                chunk = level.get_chunk(0, -3, 'minecraft:overworld')
                stone = chunk.block_palette.get_add_block(Block('universal_minecraft', 'stone'))
                chunk.blocks[1, 3 + world['vertical_offset_blocks'], (-35) % 16] = stone
                chunk.changed = True
                level.put_chunk(chunk, 'minecraft:overworld')
                level.save()
            finally:
                level.close()
            blocked = verify_saved(root / 'bedrock-world', world['vertical_offset_blocks'], world['spawn'], prepared)
            self.assertIn('other-door', blocked['native_readback']['unresolved_opening_ids'])


if __name__ == '__main__':
    unittest.main()
