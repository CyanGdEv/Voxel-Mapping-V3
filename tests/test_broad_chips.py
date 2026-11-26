import unittest
import numpy as np
from affine import Affine
from tools.prepare_registered_broad_chips import conservative_labels, merge_labels, validation_bounds


class BroadChipsTests(unittest.TestCase):
    def test_unknowns_remain_in_coverage_denominator_and_edges_ignored(self):
        source = np.full((20,20),9,np.uint8)
        source[8:10,8:10] = 255
        source[8,8] = 9
        result = conservative_labels(source,Affine(.5,0,0,0,-.5,10),
                                     Affine(1,0,0,0,-1,10),(10,10),np.ones((10,10),bool))
        self.assertEqual(result[4,4],255)
        self.assertEqual(result[4,5],255)
        self.assertEqual(result[0,0],255)
        self.assertEqual(result[2,2],9)
        with self.assertRaises(ValueError):
            conservative_labels(np.full((20,20),7,np.uint8),Affine.identity(),Affine.identity(),(10,10),np.ones((10,10),bool))

    def test_conflicting_labels_never_revived_by_shared_source_votes(self):
        current = np.array([[1,255]],np.uint8)
        incoming = np.array([[9,1]],np.uint8)
        conflict = np.zeros(current.shape,bool)
        merge_labels(current,incoming,conflict)
        np.testing.assert_array_equal(current,[[255,1]])
        merge_labels(current,incoming,conflict)
        np.testing.assert_array_equal(current,[[255,1]])
        self.assertTrue(conflict[0,0])

    def test_margin_preserves_inference_tile_phase_and_rejects_clipped_origin(self):
        x,y = np.array([100,150]),np.array([90,130])
        tight = validation_bounds(x,y,(400,400),0)
        padded = validation_bounds(x,y,(400,400),64)
        self.assertEqual(padded,(36,26,215,195))
        for px,py in zip(x,y):
            self.assertEqual(((px-tight[0])%64,(py-tight[1])%64),
                             ((px-padded[0])%64,(py-padded[1])%64))
        for margin in (-64,32):
            with self.assertRaises(ValueError):validation_bounds(x,y,(400,400),margin)
        with self.assertRaises(ValueError):validation_bounds(np.array([10]),y,(400,400),64)
