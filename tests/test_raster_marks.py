import tempfile
from pathlib import Path
import unittest
import numpy as np
from PIL import Image
from voxel_mapper.raster_marks import crosshair_at,inspect_grid_marks


class RasterMarkTests(unittest.TestCase):
    def fixture(self,root,shift=(0,0),omit=(),move=None):
        raster=np.full((380,380),255,dtype=np.uint8)
        for x in (80,220):
            for y in (80,220):
                if (x,y) in omit:continue
                dx,dy=shift
                if move and (x,y)==(220,220):dx+=move
                px,py=x+dx,y+dy
                raster[py,px-15:px+16]=0;raster[py-15:py+16,px]=0
        path=root/'marks.png';Image.fromarray(raster).save(path)
        labels=[{'axis':'E','value':500000,'pixel_position':80},
                {'axis':'E','value':500050,'pixel_position':220},
                {'axis':'N','value':168100,'pixel_position':80},
                {'axis':'N','value':168050,'pixel_position':220}]
        return path,labels

    def test_complete_stroke_fit_is_not_geographic_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            image,labels=self.fixture(Path(directory),shift=(-5,5))
            result=inspect_grid_marks(image,labels)
        self.assertEqual(result['status'],'internally_consistent_grid_marks_unverified')
        self.assertEqual(result['complete_mark_count'],4)
        self.assertLess(result['max_withheld_error_coordinate_units'],1e-6)
        self.assertEqual(result['geographic_registration'],'not_established')
        self.assertFalse(result['controls_exported']);self.assertNotIn('controls',result)

    def test_missing_mark_is_not_interpolated(self):
        with tempfile.TemporaryDirectory() as directory:
            image,labels=self.fixture(Path(directory),omit=((220,220),))
            result=inspect_grid_marks(image,labels)
        self.assertEqual(result['complete_mark_count'],3)
        self.assertEqual(result['status'],'insufficient_grid_marks')

    def test_partial_stroke_text_t_and_thick_plus_are_withheld(self):
        for kind in ('vertical','T','thick'):
            mask=np.zeros((100,100),dtype=bool)
            mask[35:66,50]=True
            if kind=='T':mask[35,35:66]=True
            if kind=='thick':mask[46:55,35:66]=True;mask[35:66,46:55]=True
            point,_=crosshair_at(mask,(50,50));self.assertIsNone(point,kind)

    def test_shifted_single_mark_rejects_inconsistent_fit(self):
        with tempfile.TemporaryDirectory() as directory:
            image,labels=self.fixture(Path(directory),move=6)
            result=inspect_grid_marks(image,labels)
        self.assertEqual(result['status'],'rejected_grid_mark_fit')

    def test_constant_offset_can_survive_and_remains_unverified(self):
        with tempfile.TemporaryDirectory() as directory:
            image,labels=self.fixture(Path(directory),shift=(8,8))
            result=inspect_grid_marks(image,labels,reuse_allowed=True)
        self.assertTrue(result['controls_exported'])
        self.assertEqual(result['independent_accuracy'],'not_verified')
        self.assertEqual(result['world_geometry_additions'],0)

    def test_budget_and_nonfinite_coordinates_rejected(self):
        with self.assertRaises(ValueError):inspect_grid_marks('missing.png',[{}]*65)
        with self.assertRaises(ValueError):crosshair_at(np.zeros((100,100)),(float('nan'),50))
        with self.assertRaises(ValueError):crosshair_at(np.zeros((100,100)),(50,50),radius=13)
        with tempfile.TemporaryDirectory() as directory:
            image,labels=self.fixture(Path(directory));labels[1]['value']+=30_000
            self.assertEqual(inspect_grid_marks(image,labels)['status'],'rejected_control_extent')
