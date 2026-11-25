import struct
import unittest
import numpy as np

from tools.extract_bedrock_heightmap import extract
from voxel_mapper.world_registration import orientation_scores, refine_translation


class WorldRegistrationTests(unittest.TestCase):
    def test_native_metadata_axes_and_missing_chunks(self):
        values = np.arange(256,dtype="<u2").reshape(16,16)
        key = struct.pack("<iiB", -1,2,43)
        heightmap,origin,count = extract([(key,values.tobytes()),
                                         (struct.pack("<iiB",1,2,43),values.tobytes())])
        self.assertEqual(origin,[-16,32])
        self.assertEqual(count,2)
        self.assertEqual(heightmap[10,5],values[10,5])
        self.assertTrue(np.isnan(heightmap[:,16:32]).all())
        with self.assertRaises(ValueError):
            extract([(key,b"short")])
        with self.assertRaises(ValueError):
            extract([(key,values.tobytes())], max_pixels=10)

    def test_translation_offset_orientation_and_disjoint_validation(self):
        rng = np.random.default_rng(41)
        reference = rng.normal(170,5,(80,120))
        world = np.rint(reference[21:53,35:83]-98)
        valid = np.ones(world.shape,dtype=bool)
        matches = orientation_scores(world, reference, valid, step=1)
        self.assertEqual(matches[0]["orientation"],"identity")
        self.assertEqual(matches[0]["reference_pixel_offset"],[35,21])
        # Simulated structures must not pull the robust terrain datum upward.
        world[::8,::8] += 12
        result = refine_translation(world,reference,valid,[37,19],
                                    [0,0,24,32],[[24,0,48,32]],radius=3,step=1)
        self.assertEqual(result["best"]["reference_pixel_offset"],[35,21])
        self.assertAlmostEqual(result["best"]["reference_minus_heightmap_m"],98,delta=.1)
        self.assertLess(result["validation"][0]["median_absolute_residual_m"],.4)
        self.assertEqual(result["world_blocks_changed"],0)
        with self.assertRaisesRegex(ValueError,"overlap"):
            refine_translation(world,reference,valid,[35,21],[0,0,24,32],[[20,0,48,32]])
        with self.assertRaises(ValueError):
            orientation_scores(np.ones((16,16)),reference,np.ones((16,16),bool),step=1)
