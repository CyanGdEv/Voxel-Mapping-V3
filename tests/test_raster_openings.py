import unittest
import numpy as np
from voxel_mapper.raster_openings import detect


class RasterOpeningTests(unittest.TestCase):
    def artwork(self):
        a=np.full((100,100),255,dtype=np.uint8)
        a[10:51,20:23]=180;a[10:51,80:83]=180;a[10,20:83]=180
        return a

    def review(self,a,**kwargs):
        return detect(a,[50,10],[50,50],kwargs.get('scale',.05),radius=60)

    def test_jamb_head_consensus_retains_source_crop_and_sampling_intervals(self):
        a=self.artwork();copy=a.copy();r=self.review(a)
        self.assertEqual(len(r['candidates']),1);c=r['candidates'][0]
        self.assertEqual([v['threshold'] for v in c['threshold_candidates']],[220,235])
        self.assertAlmostEqual(c['observed_jamb_span_interval_m'][0],2.9)
        self.assertAlmostEqual(c['nominal_width_interval_m'][0],2.7)
        self.assertFalse(c['physical_opening_verified'])
        np.testing.assert_array_equal(a,copy)
        self.assertEqual(self.review(a),r)

    def test_missing_jamb_or_head_is_withheld(self):
        for missing in ('jamb','head'):
            a=self.artwork()
            if missing=='jamb':a[:,80:83]=255
            else:a[8:13,:]=255
            self.assertEqual(self.review(a)['candidates'],[])

    def test_threshold_disagreement_cannot_become_width(self):
        a=self.artwork();a[11:51,80:83]=230
        self.assertEqual(self.review(a)['candidates'],[])

    def test_broken_jamb_does_not_pass_full_height_support(self):
        a=self.artwork();a[20:40,80:83]=255
        self.assertEqual(self.review(a)['candidates'],[])

    def test_multiple_supported_pairs_remain_candidates(self):
        a=self.artwork();a[10:51,10:13]=180;a[10,10:83]=180
        self.assertEqual(len(self.review(a)['candidates']),2)

    def test_nonfinite_and_outside_or_oversized_inputs_are_refused(self):
        a=self.artwork()
        with self.assertRaises(ValueError):self.review(a,scale=float('nan'))
        with self.assertRaises(ValueError):detect(a,[50,10],[50,101],.05)
        with self.assertRaises(ValueError):detect(a.astype(float),[50,10],[50,50],.05)
        with self.assertRaises(ValueError):detect(np.zeros((3000,3000),dtype=np.uint8),[50,10],[50,50],.05)
