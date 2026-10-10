import unittest
import numpy as np
from affine import Affine
from shapely.geometry import box
from voxel_mapper.raster_landmarks import observations

class RasterLandmarkTests(unittest.TestCase):
    def test_nodata_and_nonfinite_pixels_never_supply_observations(self):
        ground=np.ma.array(np.ones((2,2))*100,mask=[[False,True],[False,False]])
        top=np.ma.array([[104.,200.],[float('nan'),102.]])
        r=observations(box(0,0,2,2),ground,top,Affine(1,0,0,0,-1,2))
        self.assertEqual(r['valid_paired_pixels'],2);self.assertEqual(r['paired_coverage_fraction'],.5)
        self.assertEqual(r['surface_above_ground_m']['median'],3)
        self.assertFalse(r['checkpoint_attachment_verified'])
    def test_empty_footprint_has_no_invented_height(self):
        r=observations(box(10,10,11,11),np.zeros((2,2)),np.zeros((2,2)),Affine.identity())
        self.assertIsNone(r['ground_odn_m']);self.assertIsNone(r['paired_coverage_fraction'])

class ElevatedRegionTests(unittest.TestCase):
    def test_missing_strip_keeps_regions_disconnected(self):
        from voxel_mapper.raster_landmarks import elevated_regions
        ground=np.ma.array(np.zeros((3,5)),mask=False);top=np.ma.array(np.ones((3,5))*4,mask=False)
        top.mask[:,2]=True
        r=elevated_regions(ground,top,Affine.identity(),min_area_m2=1)
        self.assertEqual(len(r['regions']),2);self.assertEqual(r['elevated_pixels'],12)
        self.assertFalse(r['regions'][0]['checkpoint_attachment_verified'])
    def test_region_budget_refuses_partial_evidence(self):
        from voxel_mapper.raster_landmarks import elevated_regions
        ground=np.zeros((1,3));top=np.array([[4.,0.,4.]])
        with self.assertRaises(ValueError):elevated_regions(ground,top,Affine.identity(),min_area_m2=.5,max_regions=1)
