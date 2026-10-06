import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

import numpy as np
import rasterio
import amulet
from rasterio.transform import from_origin
from shapely.geometry import box, Polygon

from voxel_mapper.buildings import reconstruct_building
from voxel_mapper.acquisition import acquire_surface, ensure_ea_grid
from voxel_mapper.bedrock import export_world
from voxel_mapper.cli import build


class Samples:
    def __init__(self, function, source):
        self.function = function
        self.config = {'source_id':source}
    def sample(self,x,z):
        return self.function(int(x),int(z))


class BuildingTests(unittest.TestCase):
    def profile(self, surface, geometry=None, **kwargs):
        return reconstruct_building(geometry or box(0,0,10,10),1,
            Samples(lambda x,z:10,'ground'),Samples(surface,'surface'),**kwargs)

    def test_gabled_roof_retains_height_profile(self):
        rows, report = self.profile(lambda x,z:15+min(x,9-x))
        self.assertEqual(report['status'],'accepted_unverified')
        self.assertEqual(rows[(0,0)],(10,15))
        self.assertEqual(rows[(4,0)],(10,19))
        self.assertEqual(rows[(9,0)],(10,15))
        self.assertEqual(report['foundation_method'],'terrain_10th_percentile_estimate')

    def test_courtyard_is_not_filled(self):
        geometry=Polygon([(0,0),(10,0),(10,10),(0,10)],holes=[[(3,3),(7,3),(7,7),(3,7)]])
        rows, report = self.profile(lambda x,z:16,geometry=geometry)
        self.assertEqual(len(rows),84)
        self.assertNotIn((4,4),rows)

    def test_isolated_spike_is_omitted(self):
        rows, report = self.profile(lambda x,z:50 if (x,z)==(5,5) else 16)
        self.assertEqual(report['isolated_outlier_columns'],1)
        self.assertEqual(report['status'],'accepted_unverified')
        self.assertNotIn((5,5),rows)

    def test_nodata_rejects_roof_instead_of_inventing_height(self):
        rows, report = self.profile(lambda x,z:None if x<5 else 16)
        self.assertIsNone(rows)
        self.assertEqual(report['usable_coverage_fraction'],.5)

    def test_declared_height_conflict_rejects_obsolete_surface(self):
        rows, report = self.profile(lambda x,z:16,declared_height=30)
        self.assertIsNone(rows)
        self.assertIn('conflicts',report['reason'])

    def test_rough_canopy_is_not_accepted_as_a_roof(self):
        rows, report = self.profile(lambda x,z:16+3*((x+z)%2))
        self.assertIsNone(rows)
        self.assertEqual(report['status'],'rejected')

    def test_sampling_budget_bounds_large_footprints(self):
        rows, report = self.profile(lambda x,z:16,max_checks=1)
        self.assertIsNone(rows)
        self.assertEqual(report['checks'],0)

    def test_no_surface_download_for_incompatible_ground_datum(self):
        with tempfile.TemporaryDirectory() as d, patch('voxel_mapper.acquisition.download_ea') as download:
            surface, source, attempts = acquire_surface([0,0,.001,.001],Path(d),{'id':'mapzen'})
        self.assertIsNone(surface)
        download.assert_not_called()
        self.assertEqual(attempts[0]['status'],'not_supported')

    def test_grid_outage_is_reported_without_claiming_grid_accuracy(self):
        import requests
        with tempfile.TemporaryDirectory() as d, patch('voxel_mapper.acquisition.requests.get', side_effect=requests.Timeout('unavailable')):
            result = ensure_ea_grid(Path(d))
        self.assertEqual(result['status'],'unavailable')
        self.assertIn('unavailable',result['reason'])

    def test_surface_download_is_automatic_for_matched_ground(self):
        terrain_source={'id':'ea-dtm','vertical_datum':'ODN'}
        with tempfile.TemporaryDirectory() as d, patch('voxel_mapper.acquisition.download_ea',return_value=({'source_id':'ea-dsm'},{'id':'ea-dsm'})) as download:
            surface,source,attempts=acquire_surface([0,51,.001,51.001],Path(d),terrain_source)
            self.assertTrue(download.call_args.kwargs['surface'])
            self.assertEqual(surface['source_id'],'ea-dsm')
            self.assertEqual(attempts[0]['status'],'downloaded')

    def test_actual_raster_profile_controls_voxel_roof_and_flat_foundation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            transform=from_origin(0,.0012,.0001,.0001)
            for name,data in [('ground',np.full((12,12),10,dtype='float32')),('surface',np.tile(np.arange(12,dtype='float32')+15,(12,1)))]:
                with rasterio.open(root/(name+'.tif'),'w',driver='GTiff',width=12,height=12,count=1,dtype='float32',crs='EPSG:4326',transform=transform) as dst:
                    dst.write(data,1)
            config={'bbox':[0,0,.001,.001], 'sources':[{'id':s,'url':'https://example.org','license':'CC0'} for s in ['ground','surface','osm']],
                    'terrain':{'path':str(root/'ground.tif'),'source_id':'ground','units':'m','vertical_datum':'test','emit_surface':False},
                    'surface':{'path':str(root/'surface.tif'),'source_id':'surface','units':'m','vertical_datum':'test'}}
            feature={'type':'Feature','id':'building','properties':{'kind':'building','source_id':'osm'},'geometry':{'type':'Polygon','coordinates':[[[.0002,.0002],[.0008,.0002],[.0008,.0008],[.0002,.0008],[.0002,.0002]]]}}
            report=build(config,{'features':[feature]},root/'out')
            self.assertEqual(report['building_profiles'][0]['status'],'accepted_unverified')
            voxels=[json.loads(line) for line in (root/'out/voxels.jsonl').read_text().splitlines()]
            roofs=[v for v in voxels if v['kind']=='roof']
            self.assertGreater(len({v['y'] for v in roofs}),1)
            self.assertEqual({v['roof_source'] for v in roofs},{'surface'})
            self.assertEqual(min(v['y'] for v in voxels),10)
            self.assertFalse(any('height assumed' in str(i['reason']) for i in report['issues']))
            metadata=export_world(root/'out/voxels.jsonl',root/'out',report,'Roof fixture')
            world=amulet.load_level(str(root/'out/bedrock-world'))
            try:
                for roof in roofs:
                    x,y,z=roof['x'],roof['y']+metadata['vertical_offset_blocks'],-roof['z']
                    self.assertEqual(world.get_block(x,y,z,'minecraft:overworld').base_name,'stone')
                    self.assertEqual(world.get_block(x,y+1,z,'minecraft:overworld').base_name,'air')
            finally:
                world.close()
            config['surface']['vertical_datum']='different'
            with self.assertRaisesRegex(ValueError,'vertical datum'):
                build(config,{'features':[feature]},root/'bad')
