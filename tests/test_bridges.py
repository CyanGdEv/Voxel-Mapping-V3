import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from pyproj import CRS,Transformer
from rasterio.transform import from_origin
from shapely.geometry import LineString,box,mapping
from shapely.ops import transform

from voxel_mapper.bridges import reconstruct_bridge
from voxel_mapper.cli import build
from voxel_mapper.bedrock import export_world
import amulet


class Samples:
    def __init__(self,fn,source='dtm',datum='ODN',resolution=1):
        self.fn=fn
        self.config={'source_id':source,'vertical_datum':datum,'resolution_m':resolution}
    def sample(self,x,z):return self.fn(x,z)


def ground(x,z):
    return 10-max(0,min(x,10-x,3))


class BridgeTests(unittest.TestCase):
    line=LineString([(0,0),(10,0)])
    footprint=line.buffer(1,cap_style=2)

    def reconstruct(self,base=None,surface=None,**kwargs):
        return reconstruct_bridge(self.line,self.footprint,1,base or Samples(ground),
            surface or Samples(lambda x,z:10,'dsm'),width_m=2,**kwargs)

    def test_complete_flat_deck_preserves_gap_and_absolute_height(self):
        rows,report=self.reconstruct()
        self.assertEqual(report['status'],'accepted_unverified')
        self.assertEqual(len(rows),20)
        self.assertEqual(set(rows.values()),{(10,11)})
        self.assertEqual(report['maximum_clearance_m'],3)
        self.assertEqual(report['endpoint_max_error_m'],0)
        self.assertEqual(report['assumed_deck_thickness_blocks'],1)

    def test_missing_coverage_and_nonfinite_samples_reject_whole_span(self):
        for missing in (None,float('nan'),float('inf')):
            rows,report=self.reconstruct(surface=Samples(lambda x,z:missing if 4<x<6 else 10,'dsm'))
            self.assertIsNone(rows)
            self.assertIn('finite',report['reason'])

    def test_grounded_path_or_endpoint_disconnection_not_promoted_to_bridge(self):
        for base in (Samples(lambda x,z:10),Samples(lambda x,z:7)):
            rows,report=self.reconstruct(base=base)
            self.assertIsNone(rows)
            self.assertTrue('clearance' in report['reason'] or 'endpoint' in report['reason'])
        rows,report=self.reconstruct(base=Samples(lambda x,z:8 if x<0 else ground(x,z)))
        self.assertIsNone(rows);self.assertIn('Approach',report['reason'])

    def test_rails_spikes_and_steep_grade_are_rejected(self):
        for fn in (lambda x,z:12 if abs(z)>.5 else 10,
                   lambda x,z:12 if 4.5<x<5.5 else 10,
                   lambda x,z:10+x):
            rows,report=self.reconstruct(surface=Samples(fn,'dsm'))
            self.assertIsNone(rows)
            self.assertTrue('variation' in report['reason'] or 'slope' in report['reason'])

    def test_datum_coarse_sampling_and_budget_fail_closed(self):
        for surface in (Samples(lambda x,z:10,'dsm','other'),Samples(lambda x,z:10,'dsm',resolution=30)):
            rows,report=self.reconstruct(surface=surface)
            self.assertIsNone(rows)
        rows,report=self.reconstruct(max_checks=1)
        self.assertIsNone(rows);self.assertEqual(report['checks'],0)
        self.assertIn('budget',report['reason'])

    def test_column_outlier_not_visible_on_transects_is_not_interpolated(self):
        rows,report=self.reconstruct(surface=Samples(lambda x,z:12 if x==4.5 and z==.5 else 10,'dsm'))
        self.assertIsNone(rows);self.assertIn('Column',report['reason'])

    def test_build_emits_only_deck_blocks_and_records_source_and_quality(self):
        bounds=[-.0002,-.0002,.0002,.0002]
        crs=CRS.from_proj4('+proj=aeqd +lat_0=0 +lon_0=0 +datum=WGS84 +units=m')
        inverse=Transformer.from_crs(crs,4326,always_xy=True)
        geo=transform(inverse.transform,self.line)
        feature={'id':'osm/way/bridge','type':'Feature','geometry':mapping(geo),
            'properties':{'kind':'path','source_id':'osm','highway':'footway','bridge':'yes','layer':'1','width':'2','surface':'wood'}}
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name,fn in [('dtm',ground),('dsm',lambda x,z:10)]:
                values=np.array([[fn(-30+c+.5,30-r-.5) for c in range(60)] for r in range(60)],dtype='float32')
                with rasterio.open(root/(name+'.tif'),'w',driver='GTiff',width=60,height=60,count=1,dtype='float32',crs=crs,transform=from_origin(-30,30,1,1)) as dst:dst.write(values,1)
            config={'bbox':bounds,'voxel_size_m':1,'sources':[{'id':s,'url':'https://example.org/'+s,'license':'CC0'} for s in ('dtm','dsm','osm')],
                'terrain':{'path':str(root/'dtm.tif'),'source_id':'dtm','units':'m','vertical_datum':'ODN'},
                'surface':{'path':str(root/'dsm.tif'),'source_id':'dsm','units':'m','vertical_datum':'ODN'}}
            report=build(config,{'features':[feature]},root/'out')
            records=[json.loads(s) for s in (root/'out/voxels.jsonl').read_text().splitlines()]
            deck=[r for r in records if r.get('feature')=='osm/way/bridge']
            self.assertTrue(deck)
            self.assertEqual({r['y'] for r in deck},{10})
            self.assertEqual({r['elevation_source'] for r in deck},{'dsm'})
            self.assertEqual({r['geometry_method'] for r in deck},{'bridge_surface_candidate'})
            self.assertEqual({r['material'] for r in deck},{'oak_planks'})
            self.assertEqual(report['bridge_profiles'][0]['status'],'accepted_unverified')
            metadata=export_world(root/'out/voxels.jsonl',root/'out',report)
            world=amulet.load_level(str(root/'out/bedrock-world'))
            try:
                offset=metadata['vertical_offset_blocks']
                self.assertEqual(world.get_block(5,10+offset,0,'minecraft:overworld').base_name,'planks')
                self.assertEqual(world.get_block(5,9+offset,0,'minecraft:overworld').base_name,'air')
                self.assertEqual(world.get_block(5,8+offset,0,'minecraft:overworld').base_name,'air')
            finally:world.close()
            feature['properties']['surface']='gravel'
            stable=build(config,{'features':[feature]},root/'stable')
            self.assertEqual(stable['transport_profiles'][0]['material'],'stone')
            feature['properties']['surface']='wood'
            feature['properties']['layer']='2'
            rejected=build(config,{'features':[feature]},root/'stacked')
            self.assertEqual(rejected['bridge_profiles'][0]['status'],'rejected')
            self.assertEqual(rejected['features'],0)
            feature['properties']['layer']='1'
            config['boundary_geojson']=mapping(transform(inverse.transform,box(2,-5,12,5)))
            clipped=build(config,{'features':[feature]},root/'clipped')
            self.assertIn('boundary',clipped['bridge_profiles'][0]['reason'])

    def test_unsupported_span_width_empty_footprint_and_resolution_rejected(self):
        from shapely.geometry import Polygon
        for line,footprint,width,resolution in (
            (LineString([(0,0),(2,0)]),self.footprint,2,1),
            (LineString([(0,0),(10,0),(0,0)]),self.footprint,2,1),
            (self.line,self.footprint,25,1),
            (self.line,Polygon(),2,1),
            (self.line,self.footprint.union(box(20,0,21,1)),2,1),
            (self.line,self.footprint,2,2)):
            rows,report=reconstruct_bridge(line,footprint,resolution,Samples(ground),
                Samples(lambda x,z:10,'dsm'),width_m=width)
            self.assertIsNone(rows)
            self.assertEqual(report['status'],'rejected')
