import unittest
import numpy as np
from voxel_mapper.raster_opening_scan import scan


class OpeningScanTests(unittest.TestCase):
    def frame(self):
        gray=np.full((160,240),255,dtype=np.uint8)
        gray[30:125,40:43]=80;gray[30:125,170:173]=80;gray[30:33,40:173]=80
        return gray

    def test_unseeded_frame_threshold_consensus_and_no_physical_claim(self):
        gray=self.frame();before=gray.copy();r=scan(gray)
        self.assertEqual(r['status'],'jamb_head_correspondence_candidates_only')
        self.assertTrue(r['candidates']);self.assertTrue(np.array_equal(gray,before))
        self.assertTrue(any(c['bounds_pixels'][0]==43 and c['bounds_pixels'][2]==170 for c in r['candidates']))
        self.assertFalse(r['physical_opening_verified'])
        self.assertTrue(all(c['opening_type'] is None for c in r['candidates']))
        self.assertEqual(r,scan(gray))

    def test_no_head_no_frame_and_threshold_disagreement(self):
        gray=self.frame();gray[30:33,43:170]=255
        self.assertEqual(scan(gray)['candidates'],[])
        gray=self.frame();gray[30:125,40:43]=228
        self.assertEqual(scan(gray)['candidates'],[])
        self.assertEqual(scan(np.full((160,240),255,dtype=np.uint8))['candidates'],[])

    def test_budget_discards_all_candidates_and_crop_edge_is_not_jamb(self):
        gray=self.frame()
        r=scan(gray,max_checks=1);self.assertEqual(r['status'],'scan_budget_withheld')
        self.assertEqual(r['candidates'],[])
        r=scan(gray,max_groups=1);self.assertEqual(r['candidates'],[])
        gray[:125,40:43]=80;self.assertEqual(scan(gray)['candidates'],[])
        for options in ({'min_width':True},{'max_checks':100001}):
            with self.assertRaises(ValueError):scan(self.frame(),**options)
        with self.assertRaises(ValueError):scan(np.ones((10,10),dtype=float))


if __name__=='__main__':unittest.main()
