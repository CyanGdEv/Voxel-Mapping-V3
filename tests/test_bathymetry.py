import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import rasterio
from shapely.geometry import box, mapping
from voxel_mapper.bathymetry import candidates, crop_archive, acquire_bathymetry


def archive(files):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        for name,content in files.items():z.writestr(name,content)
    return stream.getvalue()


def ascii_grid(values):
    return 'ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 0.5\nNODATA_value -9999\n'+values


class BathymetryTests(unittest.TestCase):
    def catalogue(self, bounds=(0,0,1,1)):
        d={'type':'FeatureCollection','crs':{'properties':{'name':'urn:ogc:def:crs:EPSG::27700'}},
           'features':[{'geometry':mapping(box(*bounds)),'properties':{'year':'2020','os_ref_5k':'TQ0065',
               'resolution':.5,'srvy_type':'RIVERINE MULTIBEAM','filename':'tq0065_20200101mb.asc'}}]}
        return archive({'index.geojson':json.dumps(d)})

    def test_index_intersection_is_not_raster_coverage(self):
        selected=candidates(self.catalogue(),(0,0,1,1))[0]
        self.assertIn('/bathymetry_riverine_multibeam/2020/0.5/TQ0065',selected['url'])
        with tempfile.TemporaryDirectory() as d:
            payload=archive({selected['files'][0]:ascii_grid('-9999 -9999\n-9999 -9999\n')})
            with self.assertRaisesRegex(ValueError,'No finite'):
                crop_archive(payload,selected,(0,0,1,1),Path(d))
            self.assertFalse((Path(d)/'ea-bathymetry.tif').exists())

    def test_nonintersecting_and_boundary_only_tiles_not_selected(self):
        self.assertEqual(candidates(self.catalogue(),(1,0,2,1)),[])
        self.assertEqual(candidates(self.catalogue(),(2,2,3,3)),[])

    def test_absolute_elevations_and_nodata_preserved(self):
        selected=candidates(self.catalogue(),(0,0,1,1))[0]
        with tempfile.TemporaryDirectory() as d:
            payload=archive({selected['files'][0]:ascii_grid('4 -9999\n5 6\n')})
            path,evidence=crop_archive(payload,selected,(0,0,1,1),Path(d))
            with rasterio.open(path) as ds:
                self.assertEqual(ds.crs.to_epsg(),27700)
                self.assertEqual(ds.res,(.5,.5))
                self.assertEqual(ds.read(1).tolist(),[[4,-9999],[5,6]])
            self.assertEqual(evidence['finite_pixels'],3)

    def test_missing_advertised_file_rejected(self):
        selected=candidates(self.catalogue(),(0,0,1,1))[0]
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'missing'):
                crop_archive(archive({}),selected,(0,0,1,1),Path(d))

    def test_crop_resource_budget(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'pixel budget'):
                crop_archive(archive({}),{'files':[]},(0,0,100,100),Path(d),max_pixels=4)

    def test_other_vertical_datum_skips_network(self):
        with tempfile.TemporaryDirectory() as d,patch('voxel_mapper.bathymetry.download') as network:
            config,source,evidence=acquire_bathymetry([0,0,1,1],Path(d),{'vertical_datum':'unknown'})
            self.assertIsNone(config);self.assertIsNone(source)
            self.assertEqual(evidence['status'],'not_supported');network.assert_not_called()

    def test_automatic_provider_returns_only_measured_absolute_bed_configuration(self):
        transform=SimpleNamespace(accuracy=0,transform_bounds=lambda *args,**kwargs:(0,0,1,1))
        group=SimpleNamespace(best_available=True,transformers=[transform])
        raster=archive({'tq0065_20200101mb.asc':ascii_grid('4 -9999\n5 6\n')})
        with tempfile.TemporaryDirectory() as d,patch('voxel_mapper.bathymetry.ensure_ea_grid'),patch(
                'voxel_mapper.bathymetry.TransformerGroup',return_value=group),patch(
                'voxel_mapper.bathymetry.download',side_effect=[self.catalogue(),raster]):
            config,source,evidence=acquire_bathymetry([0,0,1,1],Path(d),{'vertical_datum':'ODN'})
            self.assertEqual(config['elevation_type'],'bed_elevation')
            self.assertEqual(config['vertical_datum'],'ODN')
            self.assertEqual(source['license'],'OGL-UK-3.0')
            self.assertEqual(source['finite_coverage_fraction'],.75)
            self.assertEqual(evidence['status'],'downloaded')

    def test_download_failure_is_reported_without_flat_depth_fallback(self):
        import requests
        transform=SimpleNamespace(accuracy=0,transform_bounds=lambda *args,**kwargs:(0,0,1,1))
        with tempfile.TemporaryDirectory() as d,patch('voxel_mapper.bathymetry.ensure_ea_grid'),patch(
                'voxel_mapper.bathymetry.TransformerGroup',return_value=SimpleNamespace(best_available=True,transformers=[transform])),patch(
                'voxel_mapper.bathymetry.download',side_effect=requests.Timeout('fixture timeout')):
            config,source,evidence=acquire_bathymetry([0,0,1,1],Path(d),{'vertical_datum':'ODN'})
            self.assertIsNone(config);self.assertIsNone(source)
            self.assertIn('timeout',evidence['reason'])
