"""Independent collision, route and saved-world failure cases; synthetic site only."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import amulet
from amulet.api.block import Block
from shapely.geometry import box, mapping

from voxel_mapper.bedrock import export_world, material_block
from voxel_mapper.pilot_access import Scene, collision, prepare, verify_saved, _walkthrough, _shortest_path


class CollisionTests(unittest.TestCase):
    def test_walkthrough_keeps_half_steps_and_centres_negative_native_coordinates(self):
        scene = Scene({(-2, -3): [(0, 2, 2)], (-1, -3): [(0, 3, 3)],
                       (0, -3): [(0, 4, 4)], (1, -3): [(0, 4, 4)]}, (-3, -4, 4, 1))
        route = _walkthrough(scene, (-2, -3, 2), {(0, -3, 4)}, {(0, -3)},
                             box(0, -4, 4, 0), 4, 64)
        self.assertEqual(route['status'], 'native_route_ready')
        self.assertEqual(route['route_native_xyz'],
                         [[-1.5, 65, 3.5], [-.5, 65.5, 3.5], [.5, 66, 3.5], [1.5, 66, 3.5]])
        self.assertEqual(route['doorway_index'], 2)
        self.assertEqual(route['horizontal_length_m'], 3)
        self.assertEqual(route['minecraft_playtest'], 'not_performed')

    def test_witness_search_respects_obstructions_and_its_work_budget(self):
        scene = Scene({(x, 0): [(0, 2, 2)] for x in range(5)}, (0, 0, 4, 0))
        self.assertEqual(_shortest_path(scene, [(0, 0, 2)], lambda p: p[0] == 4,
                                        lambda p: p[0] != 2), [])
        with patch('voxel_mapper.pilot_access.MAX_SEARCH_STATES', 2):
            with self.assertRaisesRegex(ValueError, 'witness search budget'):
                _shortest_path(scene, [(0, 0, 2)], lambda p: p[0] == 4)

    def test_slabs_have_distinct_bearing_heights_and_leave_correct_half_air(self):
        self.assertEqual(collision(material_block('stone_slab')), (0, 1, 1))
        self.assertEqual(collision(material_block('stone_slab_top')), (1, 2, 2))
        self.assertEqual(collision(material_block('stone')), (0, 2, 2))
        self.assertIsNone(collision(material_block('air')))

    def test_unsupported_shapes_never_become_walkable_bearings(self):
        for material in ('water', 'oak_fence', 'spruce_trapdoor_north', 'stone_stairs_north', 'iron_bars'):
            with self.subTest(material=material):
                self.assertIsNone(collision(material_block(material))[2])
        self.assertEqual(collision(material_block('oak_fence'))[1], 3)
        self.assertIsNone(collision(Block('universal_minecraft', 'unknown_block'))[2])

    def test_half_steps_pass_but_full_steps_and_low_swept_headroom_fail(self):
        scene = Scene({(0, 0): [(0, 2, 2)], (1, 0): [(0, 3, 3)],
                       (2, 0): [(0, 5, 5)]}, (-1, -1, 3, 1))
        self.assertTrue(scene.standing((0, 0, 2)))
        self.assertTrue(scene.transition((0, 0, 2), (1, 0, 3)))
        self.assertFalse(scene.transition((1, 0, 3), (2, 0, 5)))
        # Exactly two metres at the lower standing position, but not during ascent.
        low = Scene({(0, 0): [(0, 2, 2), (6, 8, 8)], (1, 0): [(0, 3, 3)]}, (-1, -1, 2, 1))
        self.assertTrue(low.standing((0, 0, 2)))
        self.assertFalse(low.transition((0, 0, 2), (1, 0, 3)))


class AccessWorldTests(unittest.TestCase):
    def fixture(self, root, *, path=True, door=True, roof=False, terrain_hole=False, second_door=False):
        rows = [dict(x=x, y=0, z=z, kind='terrain') for x in range(-5, 6) for z in range(-3, 7)
                if not terrain_hole or x != -2]
        building = []
        for x in range(4):
            for z in range(4):
                building += [(x, y, z) for y in (1, 2)]
                if x in (0, 3) or z in (0, 3):
                    if (door and (x, z) == (0, 1)) or (second_door and (x, z) == (3, 1)):
                        continue
                    building += [(x, y, z) for y in (3, 4, 5)]
        if roof:
            building += [(x, 4, z) for x in range(4) for z in range(4)]
        rows += [dict(x=x, y=y, z=z, kind='building', feature='review/test', material='spruce_planks',
                      material_origin='estimated_reconstruction_shell', accepted_physical_geometry=False)
                 for x, y, z in building]
        if path:
            rows.append(dict(x=-4, y=0, z=1, kind='path', feature='osm/test-path', material='stone',
                             material_origin='mapped_transport_surface'))
        (root / 'voxels.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
        (root / 'features-local.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'id': 'review/test', 'geometry': mapping(box(0, 0, 4, 4)), 'properties': {}}]}))
        quality = {'voxel_size_m': 1, 'voxel_records': len(rows), 'quality_status': 'provisional_component_review'}
        component = {'anchor_local_m': [0, 0], 'feature_id': 'review/test', 'floor_elevation_m': 3,
                     'access_openings': [{'id': 'test-door', 'columns_local_xz': [[0, 1]], 'declared_height_m': 2}]}
        if second_door:
            component['access_openings'].append({'id': 'other-door', 'columns_local_xz': [[3, 1]], 'declared_height_m': 2})
        return quality, component, rows

    def build(self, root, quality, component, settings=True, callback=None):
        prepared = prepare(root, quality, component, settings)
        check = callback or (lambda path, offset, spawn: verify_saved(path, offset, spawn, prepared))
        world = export_world(root / 'voxels.jsonl', root, quality, post_export_check=check)
        return prepared, world

    def test_path_to_interior_survives_native_export_and_embeds_access_findings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, component, original = self.fixture(root)
            prepared, world = self.build(root, quality, component)
            report = prepared['report']
            self.assertEqual(report['before']['mapped_path_reachable_opening_columns'], 0)
            self.assertEqual(report['status'], 'route_verified')
            self.assertTrue(report['native_readback']['route_verified'])
            self.assertTrue(report['native_readback']['spawn_on_mapped_path'])
            self.assertTrue(report['native_readback']['openings'][0]['reachable_from_spawn'])
            self.assertEqual(world['spawn'], [-4, 65, -1])
            after = [json.loads(line) for line in (root / 'voxels.jsonl').read_text().splitlines()]
            self.assertEqual(after[:len(original)], original)
            added = after[len(original):]
            self.assertTrue(added)
            self.assertTrue(any(row['material'] == 'stone_slab' for row in added))
            self.assertTrue(all(row['x'] < 0 and not row['accepted_physical_geometry'] for row in added))
            self.assertEqual(report['terrain_excavation_cells'], 0)
            self.assertEqual(report['source_geometry_cells_modified'], 0)
            self.assertEqual(report['training_labels_generated'], 0)
            with zipfile.ZipFile(root / 'park.mcworld') as archive:
                embedded = json.loads(archive.read('voxel-quality-report.json'))
                self.assertEqual(embedded['access_review'], report)
            self.assertEqual(json.loads((root / 'access-review.json').read_text()), report)
            witness = report['native_readback']['openings'][0]['walkthrough']
            self.assertEqual(witness['status'], 'native_route_ready')
            self.assertEqual(witness['route_native_xyz'][0], [-3.5, 65, -.5])
            self.assertEqual(witness['route_native_xyz'][-1], [1.5, 67, -.5])
            self.assertEqual(witness['route_native_xyz'][witness['doorway_index']], [.5, 67, -.5])


    def test_audit_only_adds_no_geometry_and_still_sets_supported_spawn(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, component, original = self.fixture(root)
            before = (root / 'voxels.jsonl').read_bytes()
            prepared, _ = self.build(root, quality, component, settings=None)
            self.assertEqual((root / 'voxels.jsonl').read_bytes(), before)
            self.assertFalse(prepared['report']['native_readback']['route_verified'])
            self.assertTrue(prepared['report']['native_readback']['spawn_supported'])
            self.assertEqual(quality['voxel_records'], len(original))

    def test_missing_path_blocked_door_and_low_roof_stay_unresolved(self):
        for fault in ('path', 'door', 'roof'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                kwargs = {fault: fault == 'roof'}
                quality, component, _ = self.fixture(root, **kwargs)
                prepared, _ = self.build(root, quality, component)
                report = prepared['report']
                self.assertEqual(report['approach']['status'], 'withheld_no_bounded_route')
                self.assertEqual(report['approach']['added_voxel_records'], 0)
                self.assertEqual(report['status'], 'access_unresolved')
                self.assertEqual(report['native_readback']['unresolved_opening_ids'], ['test-door'])

    def test_approach_cannot_bridge_missing_terrain_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, component, _ = self.fixture(root, terrain_hole=True)
            prepared, _ = self.build(root, quality, component)
            self.assertEqual(prepared['report']['approach']['status'], 'withheld_no_bounded_route')

    def test_lower_voxel_budget_rejects_before_adding_any_geometry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, component, _ = self.fixture(root)
            before = (root / 'voxels.jsonl').read_bytes()
            with self.assertRaisesRegex(ValueError, 'voxel budget'):
                prepare(root, quality, component, True, max_voxels=quality['voxel_records'])
            self.assertEqual((root / 'voxels.jsonl').read_bytes(), before)

    def test_actual_saved_obstruction_rejects_route_and_removes_failed_world(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, component, _ = self.fixture(root)
            prepared = prepare(root, quality, component, True)
            def corrupt_and_check(path, offset, spawn):
                level = amulet.load_level(str(path))
                try:
                    chunk = level.get_chunk(0, -1, 'minecraft:overworld')
                    stone = chunk.block_palette.get_add_block(Block('universal_minecraft', 'stone'))
                    chunk.blocks[0, 3 + offset, 15] = stone  # Door at local (0, 3, 1).
                    chunk.changed = True
                    level.put_chunk(chunk, 'minecraft:overworld')
                    level.save()
                finally:
                    level.close()
                verify_saved(path, offset, spawn, prepared)
            with self.assertRaisesRegex(ValueError, 'route is blocked'):
                export_world(root / 'voxels.jsonl', root, quality, post_export_check=corrupt_and_check)
            self.assertFalse((root / 'park.mcworld').exists())
            self.assertFalse((root / 'bedrock-world').exists())

    def test_saved_spawn_metadata_is_checked_instead_of_trusting_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, component, _ = self.fixture(root)
            prepared, world = self.build(root, quality, component)
            wrong = [world['spawn'][0] + 1, *world['spawn'][1:]]
            with self.assertRaisesRegex(ValueError, 'spawn differs'):
                verify_saved(root / 'bedrock-world', world['vertical_offset_blocks'], wrong, prepared)

    def test_actual_saved_head_obstruction_rejects_supported_spawn(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, component, _ = self.fixture(root)
            prepared, world = self.build(root, quality, component)
            spawn = world['spawn']
            level = amulet.load_level(str(root / 'bedrock-world'))
            try:
                chunk = level.get_chunk(spawn[0] // 16, spawn[2] // 16, 'minecraft:overworld')
                stone = chunk.block_palette.get_add_block(Block('universal_minecraft', 'stone'))
                chunk.blocks[spawn[0] % 16, spawn[1] + 1, spawn[2] % 16] = stone
                chunk.changed = True
                level.put_chunk(chunk, 'minecraft:overworld')
                level.save()
            finally:
                level.close()
            with self.assertRaisesRegex(ValueError, 'spawn lacks bearing support or two metres'):
                verify_saved(root / 'bedrock-world', world['vertical_offset_blocks'], spawn, prepared)

    def test_audit_recognises_existing_access_without_building(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, component, rows = self.fixture(root)
            # Existing full-height path meets the floor without any height change.
            rows = [row for row in rows if row.get('feature') != 'osm/test-path']
            rows += [dict(x=x, y=2, z=1, kind='path', feature='osm/test-path', material='stone')
                     for x in (-4, -3, -2, -1)]
            (root / 'voxels.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
            quality['voxel_records'] = len(rows)
            prepared, _ = self.build(root, quality, component, settings=None)
            self.assertEqual(prepared['report']['status'], 'existing_access_verified')
            self.assertTrue(prepared['report']['native_readback']['interior_connected_to_path_and_spawn'])
            self.assertEqual(prepared['report']['approach']['added_voxel_records'], 0)

    def test_reaching_second_door_via_interior_does_not_prove_exterior_approach(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, component, _ = self.fixture(root, second_door=True)
            prepared, _ = self.build(root, quality, component)
            report = prepared['report']['native_readback']
            other = next(o for o in report['openings'] if o['id'] == 'other-door')
            self.assertTrue(other['reachable_from_mapped_path'])
            self.assertTrue(other['reachable_from_spawn'])
            self.assertFalse(other['exterior_route_from_mapped_path'])
            self.assertEqual(report['unresolved_opening_ids'], ['other-door'])

    def test_two_mapped_islands_cannot_make_an_interior_detour_a_spawn_walkthrough(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, component, rows = self.fixture(root, second_door=True)
            # Two separate elevated mapped approaches meet the same floor. Their
            # only connection to one another runs through the building interior.
            rows = [row for row in rows if row.get('feature') != 'osm/test-path']
            rows += [dict(x=x, y=2, z=1, kind='path', feature='osm/island', material='stone')
                     for x in (-4, -3, -2, -1, 4, 5)]
            (root / 'voxels.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
            quality['voxel_records'] = len(rows)
            prepared, _ = self.build(root, quality, component, settings=None)
            report = prepared['report']['native_readback']
            other = next(o for o in report['openings'] if o['id'] == 'other-door')
            self.assertTrue(other['reachable_from_spawn'])
            self.assertTrue(other['exterior_route_from_mapped_path'])
            self.assertEqual(other['walkthrough']['status'], 'unresolved')
            self.assertEqual(other['walkthrough']['route_native_xyz'], [])
            self.assertIn('other-door', report['unresolved_opening_ids'])
            first = next(o for o in report['openings'] if o['id'] == 'test-door')
            self.assertEqual(first['walkthrough']['status'], 'native_route_ready')

    def test_explicit_per_opening_policy_builds_and_verifies_both_external_routes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, component, _ = self.fixture(root, second_door=True)
            prepared, _ = self.build(root, quality, component, settings={'policy': 'estimated_each_opening_approach_v2'})
            report = prepared['report']
            self.assertEqual(report['status'], 'route_verified')
            self.assertEqual(len(report['approach']['decisions']), 2)
            self.assertEqual(report['native_readback']['verified_approach_routes'], 2)
            self.assertEqual(report['native_readback']['unresolved_opening_ids'], [])
            self.assertTrue(all(o['exterior_route_from_mapped_path'] for o in report['native_readback']['openings']))

    def test_source_width_below_player_clearance_never_becomes_accepted_passage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, component, _ = self.fixture(root)
            component['access_openings'][0]['declared_width_m'] = .4
            prepared, _ = self.build(root, quality, component, settings={'policy': 'estimated_each_opening_approach_v2'})
            opening = prepared['report']['native_readback']['openings'][0]
            self.assertFalse(opening['source_player_clearance'])
            self.assertFalse(opening['exterior_route_from_mapped_path'])
            self.assertEqual(prepared['report']['status'], 'access_unresolved')

    def test_per_opening_search_uses_a_shared_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, component, _ = self.fixture(root, second_door=True)
            with patch('voxel_mapper.pilot_access.MAX_APPROACH_SEARCH_STATES', 1):
                # Inspect planning only: the independent audit has its own graph budget.
                prepared = prepare(root, quality, component, {'policy': 'estimated_each_opening_approach_v2'})
            self.assertLessEqual(prepared['report']['approach']['search_states'], 1)
            self.assertFalse(prepared['routes'])

    def test_overridden_mapped_path_column_cannot_be_covered_by_a_new_step(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, component, rows = self.fixture(root)
            rows += [dict(x=-1, y=0, z=1, kind='path', feature='osm/overridden', material='stone'),
                     dict(x=-1, y=0, z=1, kind='road', feature='synthetic/road', material='black_concrete',
                          material_origin='accepted_planning_paving')]
            (root / 'voxels.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
            quality['voxel_records'] = len(rows)
            prepared, _ = self.build(root, quality, component, settings={'policy': 'estimated_each_opening_approach_v2'})
            self.assertEqual(prepared['report']['approach']['status'], 'withheld_no_bounded_route')
            self.assertEqual(prepared['report']['approach']['added_voxel_records'], 0)

    def test_obstructed_nonprimary_saved_route_rejects_the_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, component, _ = self.fixture(root, second_door=True)
            prepared = prepare(root, quality, component, {'policy': 'estimated_each_opening_approach_v2'})
            self.assertEqual(len(prepared['routes']), 2)
            def corrupt_and_check(path, offset, spawn):
                x, z, feet = prepared['routes'][1][0]
                level = amulet.load_level(str(path))
                try:
                    chunk = level.get_chunk(x // 16, -z // 16, 'minecraft:overworld')
                    stone = chunk.block_palette.get_add_block(Block('universal_minecraft', 'stone'))
                    chunk.blocks[x % 16, feet // 2 + offset, -z % 16] = stone
                    chunk.changed = True
                    level.put_chunk(chunk, 'minecraft:overworld')
                    level.save()
                finally:
                    level.close()
                verify_saved(path, offset, spawn, prepared)
            with self.assertRaisesRegex(ValueError, 'route is blocked'):
                export_world(root / 'voxels.jsonl', root, quality, post_export_check=corrupt_and_check)
            self.assertFalse((root / 'park.mcworld').exists())

    def test_replay_preserves_voxel_hash_and_route_decisions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = []
            for name in ('first', 'second'):
                directory = root / name
                directory.mkdir()
                quality, component, _ = self.fixture(directory)
                prepared, _ = self.build(directory, quality, component)
                results.append((quality['sha256'], prepared['report']))
            self.assertEqual(results[0], results[1])
