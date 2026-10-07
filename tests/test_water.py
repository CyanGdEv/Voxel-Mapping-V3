import json
import tempfile
import unittest
from pathlib import Path
import rasterio
from shapely.geometry import box
from voxel_mapper.water import surface_level
from voxel_mapper.cli import build
import test_terrain_osm as fixtures


class WaterTests(unittest.TestCase):
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
