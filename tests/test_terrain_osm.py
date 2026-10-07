import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_origin
from voxel_mapper.cli import build, parse_osm


class TerrainTests(unittest.TestCase):
    def fixture(self, root, nodata=False):
        path = root / 'terrain.tif'
        values = np.full((12,12), 25, dtype='float32')
        if nodata:
            values[:] = -9999
        with rasterio.open(path, 'w', driver='GTiff', width=12, height=12, count=1,
                           dtype='float32', crs='EPSG:4326', transform=from_origin(0,.0012,.0001,.0001), nodata=-9999) as dst:
            dst.write(values, 1)
        config = {'bbox': [0,0,.001,.001], 'sources': [{'id':'dem', 'url':'https://example.org', 'license':'CC0'}],
                  'terrain': {'path':str(path), 'source_id':'dem', 'units':'m', 'vertical_datum':'test-datum'}}
        feature = {'type':'Feature','id':'path', 'geometry':{'type':'Polygon','coordinates':[[[.0004,.0004],[.0006,.0004],[.0006,.0006],[.0004,.0006],[.0004,.0004]]]},
                   'properties':{'source_id':'dem','height_m':1,'kind':'path'}}
        return config, {'features':[feature]}

    def test_terrain_positions_features_and_surface(self):
        with tempfile.TemporaryDirectory() as d:
            config, features = self.fixture(Path(d))
            report = build(config, features, Path(d)/'out')
            records = [json.loads(s) for s in (Path(d)/'out/voxels.jsonl').read_text().splitlines()]
            self.assertEqual({r['y'] for r in records}, {25})
            self.assertEqual({r['kind'] for r in records}, {'terrain','path'})
            self.assertEqual(report['issues'], [])
            self.assertEqual(report['terrain']['missing_requests'], 0)

    def test_nodata_is_not_flat_ground(self):
        with tempfile.TemporaryDirectory() as d:
            config, features = self.fixture(Path(d), True)
            report = build(config, features, Path(d)/'out')
            self.assertEqual(report['voxel_records'], 0)
            self.assertTrue(any(i['reason']=='terrain coverage/nodata gaps' for i in report['issues']))

    def test_bridge_needs_measured_elevation(self):
        with tempfile.TemporaryDirectory() as d:
            config, features = self.fixture(Path(d))
            features['features'][0]['properties']['bridge'] = 'yes'
            report = build(config, features, Path(d)/'out')
            self.assertEqual(report['features'], 0)
            self.assertTrue(any('elevated/tunnel' in str(i['reason']) for i in report['issues']))

    def test_vertical_datum_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            config, features = self.fixture(Path(d))
            features['features'][0]['properties']['base_elevation_m'] = 30
            with self.assertRaisesRegex(ValueError, 'vertical datum'):
                build(config, features, Path(d)/'out')

    def test_measured_bridge_stays_above_ground(self):
        with tempfile.TemporaryDirectory() as d:
            config, features = self.fixture(Path(d))
            properties = features['features'][0]['properties']
            properties.update(bridge='yes', base_elevation_m=35, vertical_datum='test-datum')
            report = build(config, features, Path(d)/'out')
            records = [json.loads(s) for s in (Path(d)/'out/voxels.jsonl').read_text().splitlines()]
            self.assertEqual({r['y'] for r in records if r.get('feature') == 'path'}, {35})
            self.assertEqual(report['issues'], [])

    def test_scan_budget_bounds_nodata_work(self):
        with tempfile.TemporaryDirectory() as d:
            config, features = self.fixture(Path(d), True)
            config['max_column_checks'] = 2
            with self.assertRaisesRegex(ValueError, 'scan budget'):
                build(config, features, Path(d)/'out')
            self.assertFalse((Path(d)/'out/voxels.jsonl').exists())


class MultipolygonTests(unittest.TestCase):
    def test_attraction_extent_does_not_override_physical_building_or_path(self):
        points=[{'lon':x,'lat':y} for x,y in [(0,0),(1,0),(1,1),(0,0)]]
        elements=[{'type':'way','id':i,'tags':tags,'geometry':points} for i,tags in enumerate([
            {'attraction':'roller_coaster'}, {'attraction':'dome','building':'yes'},
            {'attraction':'queue','highway':'footway'}])]
        collection,skipped=parse_osm({'elements':elements})
        self.assertEqual([f['properties']['kind'] for f in collection['features']],['building','path'])
        self.assertEqual(collection['features'][0]['geometry']['type'],'Polygon')
        self.assertEqual(len(skipped),1)

    def test_cached_attraction_outline_is_not_extruded(self):
        with tempfile.TemporaryDirectory() as d:
            config,features=TerrainTests().fixture(Path(d))
            features['features'][0]['properties']['kind']='attraction'
            report=build(config,features,Path(d)/'out')
            self.assertEqual(report['features'],0)
            records=[json.loads(s) for s in (Path(d)/'out/voxels.jsonl').read_text().splitlines()]
            self.assertEqual({r['kind'] for r in records},{'terrain'})
            self.assertTrue(any('attraction extent' in i['reason'] for i in report['issues']))

    def test_split_rings_and_courtyard(self):
        def member(ref, role, coords):
            return {'type':'way','ref':ref,'role':role,'geometry':[{'lon':x,'lat':y} for x,y in coords]}
        relation = {'type':'relation','id':1,'tags':{'building':'yes','type':'multipolygon'}, 'members':[
            member(2,'outer',[(0,0),(4,0),(4,4)]), member(3,'outer',[(4,4),(0,4),(0,0)]),
            member(4,'inner',[(1,1),(2,1),(2,2),(1,2),(1,1)])]}
        collection, skipped = parse_osm({'elements':[relation]})
        from shapely.geometry import shape
        geometry = shape(collection['features'][0]['geometry'])
        self.assertEqual(geometry.area,15)
        self.assertEqual(len(geometry.interiors),1)
        self.assertEqual(skipped,[])

    def test_unclosed_relation_reported(self):
        collection, skipped = parse_osm({'elements':[{'type':'relation','id':1,'tags':{'building':'yes'},'members':[
            {'type':'way','ref':2,'role':'outer','geometry':[{'lon':0,'lat':0},{'lon':1,'lat':0}]}]}]})
        self.assertEqual(collection['features'],[])
        self.assertTrue(skipped)
