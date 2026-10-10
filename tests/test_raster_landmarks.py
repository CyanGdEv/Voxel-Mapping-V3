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
