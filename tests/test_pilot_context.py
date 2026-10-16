"""Source-bound buffer vegetation must preserve the core and export natively."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import amulet
import rasterio
from shapely.geometry import box
from shapely.ops import transform
from pyproj import CRS, Transformer

from voxel_mapper.cli import build
from voxel_mapper.pilot_context import prepare, append
from voxel_mapper.bedrock import export_world, material_block
from voxel_mapper.terrain import Terrain
import test_terrain_osm as fixtures


class ContextTests(unittest.TestCase):
    def fixture(self, root):
        config, _ = fixtures.TerrainTests().fixture(root)
        config.update(local_origin_wgs84=[.0005, .0005], max_voxels=100_000)
        config['sources'] += [
            {'id': 'osm', 'kind': 'osm', 'url': 'https://example.test/osm', 'license': 'CC0'},
            {'id': 'dsm', 'kind': 'surface', 'url': 'https://example.test/dsm', 'license': 'CC0'}]
        surface = root / 'surface.tif'
        surface.write_bytes(Path(config['terrain']['path']).read_bytes())
        with rasterio.open(surface, 'r+') as raster:
            values = raster.read(1)
            values[:] = 37
            raster.write(values, 1)
        core = copy.deepcopy(config)
        core['bbox'] = [.00045, .00045, .00055, .00055]
        raw = {'elements': [{'id': 1, 'type': 'way', 'tags': {'natural': 'wood'},
                'geometry': [{'lon': x, 'lat': y} for x, y in
                             [(0, 0), (.001, 0), (.001, .001), (0, .001), (0, 0)]]}]}
        (root / 'core.json').write_text(json.dumps(core))
        (root / 'osm.json').write_text(json.dumps(raw))
        def pin(path):
            return {'file': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        settings = {'policy': 'mapped-woodland-buffer-v1', 'osm_source_id': 'osm',
                    'surface_source_id': 'dsm', 'core_config': pin(root / 'core.json'),
                    'raw_osm': pin(root / 'osm.json'), 'surface': pin(surface), 'max_trees': 8, 'max_cells': 10_000}
        def asset(descriptor, directory, role):
            path = Path(directory) / descriptor['file']
            if hashlib.sha256(path.read_bytes()).hexdigest() != descriptor['sha256']:
                raise ValueError('Changed asset ' + role)
            return path
        return config, settings, asset

    def test_mapped_canopy_is_confined_to_buffer_and_keeps_existing_voxels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, settings, asset = self.fixture(root)
            prepared = prepare(settings, asset, lambda p: json.loads(p.read_text()), root, config)
            output = root / 'scene'
            quality = build(config, {'features': []}, output)
            before = (output / 'voxels.jsonl').read_bytes()
            count = quality['voxel_records']
            report = append(output, quality, config, prepared)
            self.assertGreater(report['tree_count'], 0)
            self.assertLessEqual(report['tree_count'], 8)
            self.assertFalse(report['core_geometry_modified'])
            self.assertFalse((output / '.context-snapshot').exists())
            after = (output / 'voxels.jsonl').read_bytes()
            self.assertTrue(after.startswith(before))
            rows = [json.loads(line) for line in after[len(before):].decode().splitlines()]
            self.assertEqual(quality['voxel_records'], count + len(rows))
            project = Transformer.from_crs(4326, CRS.from_wkt(quality['crs']), always_xy=True).transform
            core = transform(project, box(*prepared['core_bbox'])).buffer(2)
            for row in rows:
                self.assertTrue(core.disjoint(box(row['x'], row['z'], row['x'] + 1, row['z'] + 1)))
                self.assertFalse(row['accepted_physical_geometry'])
            world = export_world(output / 'voxels.jsonl', output, quality)
            level = amulet.load_level(str(output / 'bedrock-world'))
            try:
                sample = next(row for row in rows if row['material'].endswith('_fence'))
                self.assertEqual(level.get_block(sample['x'], sample['y'] + world['vertical_offset_blocks'],
                                                 -sample['z'], 'minecraft:overworld'), material_block(sample['material']))
            finally:
                level.close()

    def test_changed_origin_bad_sources_and_unbounded_settings_fail(self):
        for fault in ('origin', 'source', 'tree_budget', 'cell_budget', 'asset'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                config, settings, asset = self.fixture(root)
                if fault == 'origin': config['local_origin_wgs84'] = [.0006, .0005]
                if fault == 'source': settings['surface_source_id'] = 'osm'
                if fault == 'tree_budget': settings['max_trees'] = 129
                if fault == 'cell_budget': settings['max_cells'] = True
                if fault == 'asset': (root / 'osm.json').write_text('{}')
                with self.assertRaises(ValueError):
                    prepare(settings, asset, lambda p: json.loads(p.read_text()), root, config)

    def test_surface_uses_same_pinned_horizontal_operation_as_ground(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, settings, asset = self.fixture(root)
            prepared = prepare(settings, asset, lambda p: json.loads(p.read_text()), root, config)
            quality = build(config, {'features': []}, root / 'scene')
            # Inspect constructor input while retaining real sampling. The BNG
            # grid cannot apply to this synthetic WGS84 raster fixture.
            operation = {'method': 'sentinel-pinned-grid-for-constructor-test'}
            config['terrain']['horizontal_operation'] = operation
            observed = []
            def terrain(spec, *args):
                observed.append(copy.deepcopy(spec))
                without_grid = {k: v for k, v in spec.items() if k != 'horizontal_operation'}
                return Terrain(without_grid, *args)
            with patch('voxel_mapper.park_foliage.Terrain', side_effect=terrain):
                append(root / 'scene', quality, config, prepared)
            self.assertEqual(len(observed), 2)
            self.assertEqual(observed[0]['horizontal_operation'], operation)
            self.assertEqual(observed[1]['horizontal_operation'], operation)
            self.assertEqual(observed[1]['source_id'], 'dsm')


if __name__ == '__main__':
    unittest.main()
