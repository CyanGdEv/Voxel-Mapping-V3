import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from voxel_mapper.wicker_survey import sample_route, inspect_survey


class WickerSurveyTests(unittest.TestCase):
    def test_tree_surface_and_nodata_never_become_rail_height(self):
        route = {'route_length_m':4, 'segments':[
            {'start':(.5,1.5),'end':(4.5,1.5),'station_start_m':0,'station_end_m':4}]}
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for name, row in [('dtm',[100,100,101,101,102]),('dsm',[120,120,-9999,105,103])]:
                path = Path(directory)/(name+'.tif'); paths.append(path)
                with rasterio.open(path,'w',driver='GTiff',width=5,height=2,count=1,
                                   dtype='float32',crs=27700,transform=from_origin(0,2,1,1),nodata=-9999) as d:
                    d.write(np.array([row,row],dtype='float32'),1)
            with rasterio.open(paths[0]) as terrain, rasterio.open(paths[1]) as surface:
                samples = sample_route(route,terrain,surface)
                self.assertEqual([s['station_m'] for s in samples],[0,2,4])
                self.assertEqual(samples[0]['surface_above_ground_m'],20)
                self.assertIsNone(samples[1]['observed_surface_odn_m'])
                self.assertIsNone(samples[1]['surface_above_ground_m'])
                self.assertTrue(all(s['track_elevation_m'] is None for s in samples))
                with self.assertRaises(ValueError): sample_route(route,terrain,surface,max_samples=2)
                with self.assertRaises(ValueError): sample_route(route,terrain,surface,spacing_m=0)

    def test_composite_or_mismatched_survey_is_explicitly_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            config = {'sources':[{'id':'dtm'},{'id':'dsm'}],
                      'terrain':{'source_id':'dtm'},'surface':{'source_id':'dsm'}}
            report = inspect_survey(config,{'elements':[]},directory)
            self.assertEqual(report['status'],'unavailable')
            self.assertIn('dated',report['reason'])
            self.assertEqual(report['world_geometry_additions'],0)
            self.assertFalse(report['track_height_profile_verified'])
            self.assertEqual(json.loads((Path(directory)/'wicker-man-survey-evidence.json').read_text()),report)
