import unittest
from shapely.geometry import box
from voxel_mapper.mutiny_bay_review import compare_envelopes

class ReviewTests(unittest.TestCase):
    def test_perfect_fit_still_requires_independent_objects(self):
        r=compare_envelopes(box(0,0,100,80),box(1000,2000,1010,2008),.1)
        self.assertTrue(r['printed_scale_gate_passed'])
        self.assertFalse(r['registration_verified'])
        self.assertEqual(r['world_geometry_additions'],0)
        self.assertEqual(r['independent_control_objects'],1)

    def test_size_mismatch_cannot_be_silently_stretched(self):
        r=compare_envelopes(box(0,0,100,80),box(1000,2000,1020,2016),.1)
        self.assertFalse(r['printed_scale_gate_passed'])
        self.assertAlmostEqual(r['fit_scale_difference_fraction'],1)

    def test_invalid_scale_is_rejected(self):
        for scale in (0, -1, float('nan')):
            with self.assertRaises(ValueError):
                compare_envelopes(box(0,0,10,10),box(0,0,1,1),scale)
