import json
import tempfile
import unittest
from pathlib import Path
import rasterio
import shutil
import amulet
from voxel_mapper.bedrock import export_world
from shapely.geometry import box
from voxel_mapper.water import surface_level
from voxel_mapper.cli import build
import test_terrain_osm as fixtures


class WaterTests(unittest.TestCase):
    def test_measured_bed_has_water_volume_and_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            config,features=fixtures.TerrainTests().fixture(root)
            features['features'][0]['properties']['kind']='water'
            bed=root/'bed.tif'
            shutil.copyfile(config['terrain']['path'],bed)
            with rasterio.open(bed,'r+') as raster:
                values=raster.read(1); values[:]=21.5; raster.write(values,1)
            config['sources'].append({'id':'survey-bed','url':'https://example.org/bed','license':'CC0'})
            config['bathymetry']={'path':str(bed),'source_id':'survey-bed','units':'m',
                'vertical_datum':'test-datum','elevation_type':'bed_elevation'}
            report=build(config,features,root/'out')
            rows=[json.loads(line) for line in (root/'out/voxels.jsonl').read_text().splitlines()]
            beds=[r for r in rows if r['kind']=='lakebed']; self.assertTrue(beds)
            self.assertEqual({r['y'] for r in beds},{21})
            waters=[r for r in rows if r['kind']=='water']
            self.assertEqual({r['y'] for r in waters},{22,23,24,25})
            self.assertEqual({r['elevation_source'] for r in beds},{'survey-bed'})
            self.assertEqual(report['water_profiles'][0]['measured_bed_columns'],len(beds))
            metadata=export_world(root/'out/voxels.jsonl',root/'out',report)
            world=amulet.load_level(str(root/'out/bedrock-world'))
            try:
                r=beds[0]; x,z=r['x'],-r['z']; offset=metadata['vertical_offset_blocks']
                self.assertEqual(world.get_block(x,21+offset,z,'minecraft:overworld').base_name,'stone')
                for y in range(22,26):
                    self.assertEqual(world.get_block(x,y+offset,z,'minecraft:overworld').base_name,'water')
            finally:
                world.close()
            config['bathymetry']['vertical_datum']='different'
            with self.assertRaisesRegex(ValueError,'datum'):
                build(config,features,root/'bad-datum')
            config['bathymetry']['vertical_datum']='test-datum'
            config['bathymetry']['elevation_type']='depth'
            with self.assertRaisesRegex(ValueError,'absolute'):
                build(config,features,root/'depth')
            config['bathymetry']['elevation_type']='bed_elevation'
            with rasterio.open(bed,'r+') as raster:
                values=raster.read(1);values[:]=30;values[7,:]=-9999;raster.write(values,1)
            fallback=build(config,features,root/'invalid-bed')
            profile=fallback['water_profiles'][0]
            self.assertGreater(profile['missing_bed_columns'],0)
            self.assertGreater(profile['invalid_bed_columns'],0)
            self.assertEqual(profile['measured_bed_columns'],0)
            fallback_rows=[json.loads(line) for line in (root/'invalid-bed/voxels.jsonl').read_text().splitlines()]
            self.assertFalse(any(r['kind']=='lakebed' for r in fallback_rows))
            self.assertEqual({r['y'] for r in fallback_rows if r['kind']=='water'},{25})

    def test_context_keeps_water_outside_park_outline(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            config,features=fixtures.TerrainTests().fixture(root)
            features['features'][0]['properties']['kind']='water'
            config['boundary_geojson']={'type':'Polygon','coordinates':[[[0,0],[.0001,0],[.0001,.0001],[0,.0001],[0,0]]]}
            config['terrain']['emit_surface']=False
            with rasterio.open(config['terrain']['path'],'r+') as raster:
                values=raster.read(1); values[:]=25; raster.write(values,1)
            clipped=build(config,features,root/'clipped')
            config['clip_to_boundary']=False
            context=build(config,features,root/'context')
            self.assertGreater(context['voxel_records'],clipped['voxel_records'])

    def test_level_requires_consistent_evidence(self):
        class Flat:
            def sample(self,x,z):
                return 12.7
        self.assertEqual(surface_level(box(0,0,10,10),Flat())[0],12.7)
        self.assertIsNone(surface_level(box(0,0,10,10),None)[0])
        class Slope:
            def sample(self,x,z):
                return x
        self.assertIsNone(surface_level(box(0,0,10,10),Slope())[0])

    def test_water_is_one_level_and_not_grass_bathymetry(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            config,features = fixtures.TerrainTests().fixture(root)
            with rasterio.open(config['terrain']['path'],'r+') as raster:
                values=raster.read(1); values[:]=25.7; raster.write(values,1)
            feature=features['features'][0]
            feature['properties']['kind']='water'
            report=build(config,features,root/'out')
            rows=[json.loads(line) for line in (root/'out/voxels.jsonl').read_text().splitlines()]
            water=[r for r in rows if r['kind']=='water']
            self.assertTrue(water)
            self.assertEqual({r['y'] for r in water},{25})
            columns={(r['x'],r['z']) for r in water}
            self.assertFalse(any((r['x'],r['z']) in columns for r in rows if r['kind']=='terrain'))
            self.assertIn('Lakebed depth unavailable',str(report['issues']))
