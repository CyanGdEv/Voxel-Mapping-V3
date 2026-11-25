import tempfile
import unittest
import zipfile
import json
from unittest.mock import patch
from pathlib import Path

import laspy
import numpy as np
import rasterio
from pyproj import CRS
from voxel_mapper.point_cloud import ground_intensity_grid
from tools.acquire_lidar_training import cached_archive_matches, main as acquire_main


class GroundIntensityTests(unittest.TestCase):
    def test_changed_archive_does_not_overwrite_retained_evidence(self):
        from voxel_mapper.survey import BASE
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cache = root/'cache'; cache.mkdir()
            output = root/'output'; output.mkdir()
            (output/'ea-national-dtm.tif').write_bytes(b'accepted evidence')
            previous = {'bounds_bng':[0,0,2,1], 'archives':{}}
            (output/'lidar-evidence.json').write_text(json.dumps(previous))
            rows = []
            for kind in ('dtm','dsm','point_cloud'):
                product = 'national_lidar_programme_'+kind
                rows.append({'product':{'id':product},'year':{'id':'2022'},'resolution':{'id':'1'},
                             'tile':{'id':'SK0540'},'uri':f'{BASE}/{product}/2022/1/SK0540'})
                name = ('SK0540_P_1_20220105_20220105.laz' if kind=='point_cloud'
                        else f'{kind.upper()}_SK0540_P_1_20220105_20220105.tif')
                with zipfile.ZipFile(cache/(product+'.zip'),'w') as z:
                    z.writestr(name,b'new archive')
            catalogue = root/'catalogue.json'
            catalogue.write_text(json.dumps({'count':3,'results':rows}))
            argv = ['acquire','--native-bounds','0','0','2','1','--output',str(output),
                    '--cache',str(cache),'--catalogue',str(catalogue),'--park-id','test']
            with patch('sys.argv',argv), self.assertRaisesRegex(ValueError,'archive changed'):
                acquire_main()
            self.assertEqual((output/'ea-national-dtm.tif').read_bytes(),b'accepted evidence')
            self.assertFalse((output/'national-survey-catalogue.json').exists())

    def test_archive_cache_identity_does_not_cross_year_or_tile(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'legacy.zip'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('DTM_SK0540_P_10682_20220105_20220105.tif',b'header identity only')
            self.assertTrue(cached_archive_matches(path,'2022','SK0540'))
            self.assertFalse(cached_archive_matches(path,'2023','SK0540'))
            self.assertFalse(cached_archive_matches(path,'2022','TQ0065'))
            self.assertFalse(cached_archive_matches(path.with_suffix('.missing'),'2022','SK0540'))

    def test_raw_ground_mean_and_unknown_cells(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            header = laspy.LasHeader(point_format=3, version='1.2')
            header.add_crs(CRS.from_epsg(27700))
            points = laspy.LasData(header)
            points.x = [.2,.4,1.2]
            points.y = [.5,.5,.5]
            points.z = [10,10,20]
            points.classification = np.array([2,2,5],np.uint8)
            points.intensity = np.array([10000,30000,65535],np.uint16)
            points.write(root/'points.las')
            report = ground_intensity_grid(root/'points.las',[0,0,2,1],root/'intensity.tif')
            self.assertEqual(report['ground_returns'],2)
            self.assertEqual(report['observed_cells'],1)
            self.assertEqual(report['encoding'],'raw_las_uint16')
            with rasterio.open(root/'intensity.tif') as src:
                self.assertEqual(src.crs.to_epsg(),27700)
                self.assertEqual(src.read(1)[0,0],20000)
                self.assertTrue(src.read(1,masked=True).mask[0,1])
            with self.assertRaises(ValueError):
                ground_intensity_grid(root/'points.las',[0,0,2.5,1],root/'bad.tif')
