import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch, Mock

import amulet

from voxel_mapper.acquisition import resolve_location, acquire_terrain
from voxel_mapper.bedrock import export_world
from voxel_mapper.pipeline import run_auto
import test_terrain_osm as fixtures


class BedrockTests(unittest.TestCase):
    def test_world_scale_orientation_composition_and_package(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            records = [dict(x=x,y=100,z=z,kind='terrain') for x,z in [(-1,-1),(0,0),(100,0),(0,100)]]
            records += [dict(x=0,y=100,z=0,kind='building'), dict(x=0,y=101,z=0,kind='building')]
            path = root/'voxels.jsonl'
            path.write_text('\n'.join(json.dumps(r) for r in records))
            metadata = export_world(path,root,{'voxel_size_m':1,'sources':[]})
            with zipfile.ZipFile(root/'park.mcworld') as archive:
                self.assertIn('level.dat',archive.namelist())
                self.assertIn('levelname.txt',archive.namelist())
                self.assertIn('voxel-quality-report.json',archive.namelist())
                self.assertIn('ATTRIBUTION.txt',archive.namelist())
                self.assertTrue(any(n.startswith('db/') for n in archive.namelist()))
            self.assertEqual(metadata['blocks_per_metre'],1)
            self.assertEqual(metadata['vertical_offset_blocks'],-36)
            world = amulet.load_level(str(root/'bedrock-world'))
            try:
                def block(x,y,z):
                    return world.get_block(x,y,z,'minecraft:overworld').base_name
                self.assertEqual(block(100,64,0),'grass_block')
                self.assertEqual(block(0,64,-100),'grass_block')
                self.assertEqual(block(0,64,0),'stone_bricks')
                self.assertEqual(block(0,65,0),'stone_bricks')
                self.assertEqual(block(0,63,0),'dirt')
            finally:
                world.close()

    def test_vertical_overflow_is_rejected_without_rescale(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);path=root/'voxels.jsonl'
            path.write_text('\n'.join(json.dumps(dict(x=0,y=y,z=0,kind='building')) for y in [0,300]))
            with self.assertRaisesRegex(ValueError,'vertical range'):
                export_world(path,root,{'voxel_size_m':1})
            self.assertFalse((root/'park.mcworld').exists())

    def test_world_budget_cleans_failed_export(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);path=root/'voxels.jsonl'
            path.write_text(json.dumps(dict(x=0,y=0,z=0,kind='terrain')))
            with self.assertRaisesRegex(ValueError,'budget'):
                export_world(path,root,{'voxel_size_m':1},max_blocks=1)
            self.assertFalse((root/'park.mcworld').exists())


class AutomaticTests(unittest.TestCase):
    def test_ambiguous_geocoding_is_not_silently_selected(self):
        response=Mock();response.json.return_value=[{'type':'theme_park'},{'type':'theme_park'}]
        with tempfile.TemporaryDirectory() as d, patch('voxel_mapper.acquisition.requests.get',return_value=response):
            with self.assertRaisesRegex(ValueError,'ambiguous'):
                resolve_location('Park',Path(d))

    def test_automatic_fallback_retains_unavailability(self):
        with tempfile.TemporaryDirectory() as d, patch('voxel_mapper.acquisition.download_ea',side_effect=ValueError('nodata')), patch('voxel_mapper.acquisition.download_global',return_value=({'path':'auto.tif'},{'id':'mapzen'})):
            terrain,source,attempts=acquire_terrain([0,51,.001,51.001],Path(d))
            self.assertEqual(source['id'],'mapzen')
            self.assertEqual(attempts[0]['status'],'unavailable')
            self.assertIn('nodata',attempts[0]['reason'])

    def test_location_to_real_world_without_user_data_files(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            config,collection=fixtures.TerrainTests().fixture(root)
            source={'id':'dem','url':'https://example.org','license':'CC0','resolution_m':1}
            result={'display_name':'Fixture Park'}
            with patch('voxel_mapper.pipeline.resolve_location',return_value=(config['bbox'],result)), patch('voxel_mapper.pipeline.acquire_terrain',return_value=(config['terrain'],source,[])), patch('voxel_mapper.pipeline.fetch_osm',return_value=(collection,{'elements':[]},[])):
                report=run_auto(root/'out',location='Fixture Park')
            self.assertTrue((root/'out/park.mcworld').exists())
            self.assertEqual(report['world']['blocks_per_metre'],1)
            self.assertEqual(report['quality_status'],'draft_unverified')
            self.assertEqual(json.loads((root/'out/acquisition.json').read_text())['status'],'completed_draft')
            self.assertTrue(report['issues'])
