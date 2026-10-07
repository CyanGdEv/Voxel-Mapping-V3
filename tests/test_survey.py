import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from voxel_mapper.survey import BASE,select_pair,crop_pair
from voxel_mapper.acquisition import acquire_terrain,acquire_surface


def archive(kind,survey='P_1',nodata=False):
    values=np.full((10,10),12 if kind=='dtm' else 20,dtype='float32')
    if nodata:values[:]=-9999
    with MemoryFile() as memory:
        with memory.open(driver='GTiff',count=1,width=10,height=10,dtype='float32',crs='EPSG:27700',transform=from_origin(503000,168010,1,1),nodata=-9999) as raster:
            raster.write(values,1)
        payload=memory.read()
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as z:z.writestr(f'{kind.upper()}_TQ0065_{survey}_20230116_20230116.tif',payload)
    return buffer.getvalue()


class SurveyTests(unittest.TestCase):
    def test_catalogue_requires_matching_dated_advertised_pair(self):
        rows=[dict(product={'id':'national_lidar_programme_'+k},year={'id':'2023'},resolution={'id':'1'},tile={'id':'TQ0065'},uri=f'{BASE}/national_lidar_programme_{k}/2023/1/TQ0065') for k in ('dtm','dsm')]
        self.assertEqual(select_pair({'count':2,'results':rows})[0],('2023','TQ0065'))
        for data in ({'count':3,'results':rows},{'count':1,'results':rows[:1]}):
            with self.assertRaises(ValueError):select_pair(data)
        rows[0]['uri']='https://example.com/raster.zip'
        with self.assertRaises(ValueError):select_pair({'count':2,'results':rows})

    def test_crop_pair_identity_coverage_and_pipeline_surface_reuse(self):
        with tempfile.TemporaryDirectory() as d:
            output=Path(d);bbox=[503002,168002,503008,168008]
            archives={k:archive(k) for k in ('dtm','dsm')}
            report=crop_pair(archives,bbox,output,'2023','TQ0065')
            self.assertEqual(report['survey_id'],'P_1')
            with rasterio.open(output/'ea-national-dtm.tif') as raster:
                self.assertEqual(raster.shape,(6,6));self.assertEqual(raster.read(1)[0,0],12)
            for bad in (archive('dsm',survey='P_2'),archive('dsm',nodata=True)):
                with self.assertRaises(ValueError):crop_pair({**archives,'dsm':bad},bbox,output,'2023','TQ0065')
            source={'id':'ea-dtm','vertical_datum':'ODN','survey':report,'paired_surface':{'config':{'path':'paired.tif'},'source':{'id':'ea-dsm'}}}
            with patch('voxel_mapper.survey.download_latest_pair',return_value=({'path':'terrain.tif'},source)),patch('voxel_mapper.acquisition.download_ea') as composite:
                terrain,got,attempts=acquire_terrain([0,51,.001,51.001],output)
                surface,_,_=acquire_surface([0,51,.001,51.001],output,got)
                self.assertEqual(surface['path'],'paired.tif');composite.assert_not_called()
