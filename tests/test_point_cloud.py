import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import laspy
import numpy as np
from pyproj import CRS
from voxel_mapper.point_cloud import select_cloud, crop_archive, acquire_point_cloud
from voxel_mapper.point_cloud import building_returns
from voxel_mapper.point_cloud import is_bng
from shapely.geometry import box,mapping
from voxel_mapper.survey import BASE


class PointCloudTests(unittest.TestCase):
    def test_actual_ea_scale_rounding_without_accepting_different_projection(self):
        wkt=CRS.from_epsg(27700).to_wkt().replace('0.9996012717','0.999601272')
        self.assertTrue(is_bng(CRS.from_wkt(wkt)))
        self.assertFalse(is_bng(CRS.from_wkt(wkt.replace('0.999601272','0.9996'))))
        self.assertFalse(is_bng(CRS.from_epsg(4326)))
    def test_only_supported_classified_building_cells_without_extrusion(self):
        class Ground:
            def sample(self,x,z):return 12
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);header=laspy.LasHeader(point_format=6,version='1.4')
            header.add_crs(CRS.from_epsg(27700));cloud=laspy.LasData(header)
            cloud.x=[.1,.2,.3,.4,.5,.6,.7];cloud.y=[.1,.2,.3,.4,.5,.6,.7]
            cloud.z=[13,13,14,14,15,15,16];cloud.classification=[6,6,5,5,6,6,6]
            cloud.withheld=[0,0,0,0,1,1,0];path=root/'crop.las';cloud.write(path)
            config={'path':str(path),'source_id':'survey'}
            feature={'id':'building','properties':{'kind':'building'},'geometry':mapping(box(0,0,1,1))}
            rows,evidence=building_returns(config,[feature],CRS.from_epsg(27700),Ground(),1)
            self.assertEqual([(r['x'],r['y'],r['z']) for r in rows],[(0,13,0)])
            self.assertEqual(rows[0]['observed_returns'],2)
            self.assertEqual(evidence['single_return_cells_omitted'],1)
            duplicate=copy.deepcopy(feature);duplicate['id']='overlap'
            rows,evidence=building_returns(config,[feature,duplicate],CRS.from_epsg(27700),Ground(),1)
            self.assertEqual(rows,[])
            self.assertGreater(evidence['ambiguous_footprint_points'],0)

    def selection(self):
        source={'url':BASE+'/national_lidar_programme_dtm/2023/1/TQ0065',
                'survey':{'survey_id':'P_12756','survey_start':'20230116','survey_end':'20230116'}}
        entry={'product':{'id':'national_lidar_programme_point_cloud'},'year':{'id':'2023'},
               'resolution':{'id':'1'},'tile':{'id':'TQ0065'},
               'uri':BASE+'/national_lidar_programme_point_cloud/2023/1/TQ0065'}
        return {'count':1,'results':[entry]},source

    def archive(self,root,filename,crs=27700):
        header=laspy.LasHeader(point_format=6,version='1.4')
        header.scales=np.array([.01,.01,.01]);header.add_crs(CRS.from_epsg(crs))
        cloud=laspy.LasData(header)
        cloud.x=[-1,.1,.8,2];cloud.y=[-1,.1,.8,2];cloud.z=[12,13,14,15]
        cloud.classification=[2,1,6,5]
        laz=root/'fixture.laz';cloud.write(laz)
        archive=root/'fixture.zip'
        with zipfile.ZipFile(archive,'w') as z:z.write(laz,filename)
        return archive

    def test_unique_advertised_matching_survey(self):
        catalogue,source=self.selection()
        selection=select_cloud(catalogue,source)
        self.assertEqual(selection['filename'],'TQ0065_P_12756_20230116_20230116.laz')
        bad=copy.deepcopy(catalogue);bad['results'][0]['uri']='https://example.org/other'
        with self.assertRaisesRegex(ValueError,'URI'):select_cloud(bad,source)
        bad=copy.deepcopy(catalogue);bad['count']=2
        with self.assertRaisesRegex(ValueError,'Incomplete'):select_cloud(bad,source)

    def test_real_laz_chunk_crop_preserves_xyz_and_classifications(self):
        catalogue,source=self.selection();selection=select_cloud(catalogue,source)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);archive=self.archive(root,selection['filename'])
            path,evidence=crop_archive(archive,selection,(0,0,1,1),root)
            crop=laspy.read(path)
            self.assertEqual(list(crop.z),[13,14]);self.assertEqual(list(crop.classification),[1,6])
            self.assertEqual(evidence['retained_points'],2)
            self.assertEqual(evidence['classifications'],{1:1,6:1})
            self.assertEqual(crop.header.parse_crs().to_epsg(),27700)

    def test_wrong_crs_and_resource_limits_remove_partial_crop(self):
        catalogue,source=self.selection();selection=select_cloud(catalogue,source)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);archive=self.archive(root,selection['filename'],crs=4326)
            with self.assertRaisesRegex(ValueError,'EPSG:27700'):
                crop_archive(archive,selection,(0,0,1,1),root)
            archive=self.archive(root,selection['filename'])
            with self.assertRaisesRegex(ValueError,'scan budget'):
                crop_archive(archive,selection,(0,0,1,1),root,max_scan_points=1)
            with self.assertRaisesRegex(ValueError,'retained-point budget'):
                crop_archive(archive,selection,(0,0,1,1),root,max_retained_points=1)
            self.assertFalse((root/'ea-point-cloud.las').exists())

    def test_missing_dated_source_never_downloads_unmatched_cloud(self):
        with tempfile.TemporaryDirectory() as d,patch('voxel_mapper.point_cloud.requests.get') as network:
            config,source,evidence=acquire_point_cloud([0,0,1,1],Path(d),{'vertical_datum':'ODN'})
            self.assertIsNone(config);self.assertIsNone(source)
            self.assertEqual(evidence['status'],'not_supported');network.assert_not_called()
