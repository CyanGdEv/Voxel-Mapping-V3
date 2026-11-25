import copy
import hashlib
import tempfile
from pathlib import Path
import unittest
import numpy as np
import laspy
from pyproj import CRS
from voxel_mapper.point_cloud import summarize_cell_returns
from voxel_mapper.ground_surface import direct_ground_support,assess_lawn_column


class CellReturnTests(unittest.TestCase):
    def fixture(self,path, *, duplicate=False, obstacle=False, flagged=False, clustered=False, invalid_return=False):
        header=laspy.LasHeader(point_format=6,version='1.4');header.scales=[.01,.01,.01];header.add_crs(CRS.from_epsg(27700))
        data=laspy.LasData(header)
        xy=[(.25,.25),(.75,.25),(.25,.75),(.75,.75)]
        if clustered:xy=[(.49,.49),(.51,.49),(.49,.51),(.51,.51)]
        if duplicate:xy=[xy[0]]*4
        if obstacle:xy.append((.5,.5))
        data.x=[1000+x for x,z in xy];data.y=[2000-z for x,z in xy];data.z=[192]*len(xy)
        data.classification=[2]*len(xy);data.return_number=[1]*len(xy);data.number_of_returns=[1]*len(xy)
        if obstacle:data.classification[-1]=6;data.z[-1]=194
        if flagged:data.withheld=[True]+[False]*(len(xy)-1)
        if invalid_return:data.number_of_returns[0]=0
        data.write(path)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_flags_duplicates_buildings_and_clustered_returns_cannot_establish_clear_ground(self):
        with tempfile.TemporaryDirectory() as td:
            for options in [{},{'duplicate':True},{'obstacle':True},{'flagged':True},{'clustered':True},{'invalid_return':True}]:
                path=Path(td)/'fixture.las';checksum=self.fixture(path,**options)
                r=summarize_cell_returns(path,[{'x':0,'z':0}],[1,0,1000,0,-1,2000],expected_sha256=checksum)
                self.assertEqual(r['cells'][0]['observed_clear_ground'],not options)
            with self.assertRaises(ValueError):summarize_cell_returns(path,[{'x':0,'z':0}],[1,0,1000,0,-1,2000],expected_sha256='wrong')
            with self.assertRaises(ValueError):summarize_cell_returns(path,[{'x':0,'z':0}],[1,0,1000,0,-1,2000],expected_sha256=checksum,max_scan_points=1)

    def test_direct_support_preserves_unknown_raster_and_material_boundaries(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'fixture.las';checksum=self.fixture(path)
            p=summarize_cell_returns(path,[{'x':0,'z':0}],[1,0,1000,0,-1,2000],expected_sha256=checksum)['cells'][0]
        self.assertTrue(direct_ground_support(p))
        cell={'x':0,'z':0,'label':1,'safe_interior':True,'supported_storage':True,'block_entities':False,
              'dtm':192.,'dsm':191.99,'native_top_y':95,'native_profile':{'92':'minecraft:dirt_with_roots',
              '93':'minecraft:stone_bricks','94':'minecraft:air','95':'minecraft:deepslate_tiles','96':'minecraft:air'}}
        original=copy.deepcopy(cell)
        self.assertEqual(assess_lawn_column(cell,surface_offset_m=98)['status'],'withheld')
        r=assess_lawn_column(cell,surface_offset_m=98,point_evidence=p)
        self.assertEqual(r['status'],'candidate');self.assertEqual(r['height_evidence_basis'],'classified_cell_returns')
        self.assertIsNone(r['before_dsm_residual_m']);self.assertEqual(cell,original)
        for change in [{'dtm':194.},{'dsm':194.},{'safe_interior':False},{'native_profile':{**cell['native_profile'],'94':'minecraft:oak_leaves'}}]:
            self.assertEqual(assess_lawn_column({**cell,**change},surface_offset_m=98,point_evidence=p)['status'],'withheld')
        self.assertEqual(assess_lawn_column(cell,surface_offset_m=98,point_evidence={**p,'x':99})['status'],'withheld')
        positive={**cell,'dsm':192.02}
        self.assertEqual(assess_lawn_column(positive,surface_offset_m=98)['status'],'candidate')
        low_vegetation={**p,'class_counts':{2:3,4:1},'ground_returns':3,'first_ground_returns':3,'all_z_max':192.10}
        self.assertEqual(assess_lawn_column(positive,surface_offset_m=98,point_evidence=low_vegetation)['height_evidence_basis'],'raster_pair')
        blocked={**p,'class_counts':{2:4,6:1},'unique_returns':5,'all_z_max':194.}
        self.assertEqual(assess_lawn_column(positive,surface_offset_m=98,point_evidence=blocked)['status'],'withheld')
        self.assertEqual(assess_lawn_column(positive,surface_offset_m=98,point_evidence={**p,'all_z_max':193.})['status'],'withheld')
        for key,value in [('first_ground_quadrants',[0,1]),('first_ground_x_span_m',.02),('ground_z_median',float('nan'))]:
            self.assertFalse(direct_ground_support({**p,key:value}))
