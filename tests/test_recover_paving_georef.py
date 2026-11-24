import unittest
import numpy as np
from voxel_mapper.recover_paving_georef import rotation_to_original
try:
    import affine
except ImportError:
    affine=None

@unittest.skipIf(affine is None,"requires GIS affine dependency")
class RotationGeoref(unittest.TestCase):
    def test_pixel_centres_for_all_rotations(self):
        original=np.arange(15).reshape(3,5)
        for k in range(4):
            rotated=np.rot90(original,k)
            tf=rotation_to_original(k,5,3)
            for y,x in np.ndindex(rotated.shape):
                sx,sy=tf*(x+.5,y+.5)
                self.assertEqual(rotated[y,x],original[int(sy),int(sx)])
