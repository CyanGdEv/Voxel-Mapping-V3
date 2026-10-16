"""Estimated paving joins: native geometry, protected edges and honest partial results."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import amulet
from shapely.geometry import box, mapping

from voxel_mapper.bedrock import export_world, material_block
from voxel_mapper.pilot_access import (Scene, PATH_STEP_FEATURE, _read_inputs, _scene,
                                       _mapped_nodes, collision)
from voxel_mapper.pilot_navigation import inspect
from voxel_mapper.pilot_path_steps import append, verify

SETTINGS = {'policy': 'estimated_half_slab_joins_v1', 'max_slabs': 128}


class PathStepTests(unittest.TestCase):
    def fixture(self, root, heights=(0, 0, 1, 1), extra=()):
        rows = [dict(x=x, y=y, z=0, kind='terrain', material='grass_block') for x, y in enumerate(heights)]
        rows += [dict(x=x, y=y, z=0, kind='path', feature='osm/paving', material='stone')
                 for x, y in enumerate(heights)]
        rows += list(extra)
        (root / 'voxels.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
        footprint = box(20, 20, 24, 24)
        (root / 'features-local.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'id': 'review/building', 'geometry': mapping(footprint), 'properties': {}}]}))
        quality = {'voxel_size_m': 1, 'voxel_records': len(rows), 'spawn_local_xyz_m': [0, heights[0] + 1, 0]}
        access = {'component': {'anchor_local_m': [0, 0]}, 'footprint': footprint,
                  'audit_scope': 'whole_pilot', 'routes': []}
        return quality, access

    def test_native_slab_joins_a_full_step_and_retains_all_source_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, access = self.fixture(root)
            original = (root / 'voxels.jsonl').read_bytes()
            prepared = append(root, quality, access, SETTINGS)
            world = export_world(root / 'voxels.jsonl', root, quality,
                post_export_check=lambda p, off, spawn: self.native_check(root, p, off, spawn, access, prepared))
            report = prepared['report']
            self.assertEqual(report['status'], 'native_joins_verified')
            self.assertEqual(report['added_slab_records'], 1)
            self.assertEqual(report['before']['walking_surface_components'], 2)
            self.assertEqual(report['native_after']['walking_surface_components'], 1)
            self.assertEqual(report['native_after']['mapped_reachable_cells_on_walking_surfaces'], 4)
            self.assertEqual(report['native_after']['mapped_cells_with_estimated_display_slabs'], 1)
            self.assertEqual(report['native_after']['adjacent_walking_surface_barriers'], 0)
            self.assertTrue((root / 'voxels.jsonl').read_bytes().startswith(original))
            self.assertEqual(report['joins'][0]['mapped_source_cell'],
                             {'feature': 'osm/paving', 'x': 1, 'y': 0, 'z': 0})
            self.assertEqual(report['terrain_excavation_cells'], 0)
            self.assertEqual(report['original_native_blocks_replaced'], 0)
            self.assertFalse(report['accepted_physical_geometry'])
            self.assertEqual(report['training_labels_generated'], 0)
            self.assertEqual(report['minecraft_playtest'], 'not_performed')
            self.assertEqual(world['spawn'], [0, 65, 0])
            with zipfile.ZipFile(root / 'park.mcworld') as archive:
                embedded = json.loads(archive.read('voxel-quality-report.json'))
                self.assertEqual(embedded['path_steps_review'], report)

    def native_check(self, root, world, offset, spawn, access, prepared, *, fault=None):
        records, _, paths, bounds = _read_inputs(root, access['component'], whole_area=True)
        level = amulet.load_level(str(world))
        columns = {}
        try:
            if fault:
                # Corrupt the actual saved DB after export's composition check.
                x, y, z = prepared['report']['joins'][0]['block_local_xyz']
                y += 1 if fault == 'roof' else 0
                chunk = level.get_chunk(x // 16, (-z) // 16, 'minecraft:overworld')
                index = chunk.block_palette.get_add_block(material_block('stone'))
                chunk.blocks[x % 16, y + offset, (-z) % 16] = index
                chunk.changed = True
                level.put_chunk(chunk, 'minecraft:overworld')
                level.save()
            for x, z in sorted({(x, z) for x, _, z in records}):
                for y in range(-2, 9):
                    block = level.get_block(x, y + offset, -z, 'minecraft:overworld')
                    form = collision(block)
                    if form:
                        lo, hi, bearing = form
                        columns.setdefault((x, z), []).append((2 * y + lo, 2 * y + hi,
                            None if bearing is None else 2 * y + bearing))
        finally:
            level.close()
        scene = Scene(columns, bounds)
        mapped = _mapped_nodes(scene, paths, records)
        navigation = inspect(scene, (spawn[0], -spawn[2], 2 * (spawn[1] - offset)),
                             mapped, paths, records, offset, [])
        verify(root, scene, mapped, records, offset, navigation, prepared)

    def test_saved_wrong_slab_or_head_obstruction_rejects_and_removes_world(self):
        for fault in ('full_block', 'roof'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                quality, access = self.fixture(root)
                prepared = append(root, quality, access, SETTINGS)
                with self.assertRaisesRegex(ValueError, 'Saved path step'):
                    export_world(root / 'voxels.jsonl', root, quality,
                        post_export_check=lambda p, off, spawn: self.native_check(
                            root, p, off, spawn, access, prepared, fault=fault))
                self.assertFalse((root / 'park.mcworld').exists())
                self.assertFalse((root / 'bedrock-world').exists())

    def test_bad_source_lineage_cannot_reclassify_a_slab_as_mapped_paving(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, access = self.fixture(root)
            append(root, quality, access, SETTINGS)
            records, _, paths, bounds = _read_inputs(root, access['component'], whole_area=True)
            records[1, 1, 0]['mapped_source_cell']['feature'] = 'different/source'
            mapped = _mapped_nodes(_scene(records, bounds), paths, records)
            self.assertEqual(len(mapped), 3)
            report = inspect(_scene(records, bounds), (0, 0, 2), mapped, paths, records, 64, [])
            self.assertEqual(report['mapped_cells_with_estimated_display_slabs'], 0)
            self.assertEqual(report['features'][0]['blocked_or_unsupported_cells'], 1)
            self.assertEqual(report['status'], 'partial_or_unresolved')

    def test_existing_half_slab_connection_cannot_be_cut_by_raising_paving(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, access = self.fixture(root, (-1, 0, 1, 1), [
                dict(x=0, y=0, z=0, kind='steps', feature='review/approach', material='stone_slab')])
            quality['spawn_local_xyz_m'] = [3, 2, 0]
            prepared = append(root, quality, access, SETTINGS)
            self.assertEqual(prepared['report']['added_slab_records'], 0)
            records, _, _, bounds = _read_inputs(root, access['component'], whole_area=True)
            self.assertTrue(_scene(records, bounds).transition((0, 0, 1), (1, 0, 2)))

    def test_building_guard_spawn_and_approaches_are_protected(self):
        for protected in ('building', 'spawn', 'approach'):
            with self.subTest(protected=protected), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                quality, access = self.fixture(root)
                if protected == 'building':
                    access['footprint'] = box(2, -2, 4, 2)
                elif protected == 'spawn':
                    quality['spawn_local_xyz_m'] = [1, 1, 0]
                else:
                    access['routes'] = [[(1, 0, 2), (0, 0, 2)]]
                original = (root / 'voxels.jsonl').read_bytes()
                report = append(root, quality, access, SETTINGS)['report']
                self.assertEqual(report['added_slab_records'], 0)
                self.assertEqual((root / 'voxels.jsonl').read_bytes(), original)

    def test_low_swept_roof_and_occupied_cells_do_not_receive_joins(self):
        for y in (1, 3):
            with self.subTest(y=y), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                quality, access = self.fixture(root, extra=[
                    dict(x=1, y=y, z=0, kind='structure', feature='osm/obstacle', material='stone')])
                report = append(root, quality, access, SETTINGS)['report']
                self.assertEqual(report['added_slab_records'], 0)
                self.assertGreater(report['planned_after']['walking_surface_components'], 1)

    def test_ungrounded_upper_path_cannot_receive_an_inferred_bridge_connection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, access = self.fixture(root, (0, 0, 1))
            rows = [json.loads(line) for line in (root / 'voxels.jsonl').read_text().splitlines()]
            next(row for row in rows if row['kind'] == 'terrain' and row['x'] == 2)['y'] = 0
            (root / 'voxels.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
            report = append(root, quality, access, SETTINGS)['report']
            self.assertEqual(report['added_slab_records'], 0)
            self.assertEqual(report['planned_after']['adjacent_walking_surface_barriers'], 1)

    def test_consecutive_metre_rises_remain_explicitly_partial(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, access = self.fixture(root, (0, 1, 2, 3))
            report = append(root, quality, access, SETTINGS)['report']
            self.assertEqual(report['added_slab_records'], 0)
            self.assertEqual(report['planned_after']['mapped_supported_cells'], 4)
            self.assertGreater(report['planned_after']['walking_surface_components'], 1)
            self.assertGreater(report['planned_after']['adjacent_walking_surface_barriers'], 0)

    def test_join_cannot_enlarge_a_full_step_gap_to_adjacent_grass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, access = self.fixture(root, extra=[
                dict(x=1, y=-1, z=1, kind='terrain', material='grass_block')])
            report = append(root, quality, access, SETTINGS)['report']
            self.assertEqual(report['added_slab_records'], 0)
            self.assertEqual(report['planned_after']['adjacent_walking_surface_barriers'], 1)

    def test_explicit_slab_limit_keeps_remaining_gaps_in_the_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quality, access = self.fixture(root, (0, 0, 1, 1, 2, 2))
            report = append(root, quality, access, {**SETTINGS, 'max_slabs': 1})['report']
            self.assertEqual(report['added_slab_records'], 1)
            self.assertEqual(report['stop_reason'], 'slab_limit')
            self.assertEqual(report['planned_after']['walking_surface_components'], 2)

    def test_voxel_and_candidate_budgets_fail_before_writing_geometry(self):
        for budget in ('voxels', 'candidates'):
            with self.subTest(budget=budget), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                quality, access = self.fixture(root)
                original = (root / 'voxels.jsonl').read_bytes()
                with patch('voxel_mapper.pilot_path_steps.MAX_CANDIDATES', 0 if budget == 'candidates' else 4096):
                    with self.assertRaisesRegex(ValueError, 'budget'):
                        append(root, quality, access, SETTINGS,
                               max_voxels=quality['voxel_records'] if budget == 'voxels' else 1_000_000)
                self.assertEqual((root / 'voxels.jsonl').read_bytes(), original)
                self.assertNotIn('path_steps_review', quality)

    def test_replay_is_identical_and_a_second_application_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshots = []
            for name in ('one', 'two'):
                output = root / name
                output.mkdir()
                quality, access = self.fixture(output, (0, 0, 1, 1, 2, 2))
                append(output, quality, access, SETTINGS)
                snapshots.append(((output / 'voxels.jsonl').read_bytes(), (output / 'path-steps-review.json').read_bytes()))
                with self.assertRaisesRegex(ValueError, 'applied once'):
                    append(output, quality, access, SETTINGS)
            self.assertEqual(*snapshots)


if __name__ == '__main__':
    unittest.main()
