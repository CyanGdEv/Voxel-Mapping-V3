import unittest
import numpy as np
from shapely.geometry import box,LineString
from voxel_mapper.orientation_cues import compare_cues,northing_direction


class OrientationCueTests(unittest.TestCase):
    def test_centred_line_preserves_reversal_and_nonmatching_projection(self):
        orientations=[{'matrix':[[1,0],[0,1]],'translation_m':[0,0],'rotation_degrees':0},
            {'matrix':[[-1,0],[0,-1]],'translation_m':[0,0],'rotation_degrees':180}]
        xyz=np.array([[-1,0,10],[0,0,11],[1,0,10]],float)
        r=compare_cues(box(-2,-1,2,1),box(2,-.5,3,.5),LineString([(-2,0),(2,0)]),xyz,box(4,4,5,5),orientations)
        self.assertEqual(r['source_interior_line_midpoint_offset_pdf_points'],0)
        self.assertEqual([x['projection_to_lower_envelope']['intersection_area_m2'] for x in r['orientation_comparisons']],[0,0])
        self.assertEqual(r['orientation_comparisons'][0]['high_return_line_comparisons'],r['orientation_comparisons'][1]['high_return_line_comparisons'])
        self.assertIsNone(r['selected_orientation'])
        self.assertEqual(r['accepted_checkpoints'],0)

    def test_nonfinite_returns_fail(self):
        with self.assertRaises(ValueError):compare_cues(box(0,0,1,1),box(1,0,2,1),LineString([(0,0),(1,1)]),np.full((3,3),np.nan),box(2,2,3,3),[])

    def test_northing_direction_rejects_reversal_without_accepting_position(self):
        r=northing_direction([{'northing':1500,'native_centre':[0,0]},{'northing':1550,'native_centre':[0,500]}],
            [{'matrix':[[.1,0],[0,.1]],'rotation_degrees':0},{'matrix':[[-.1,0],[0,-.1]],'rotation_degrees':180}])
        self.assertEqual([x['north_half_plane_consistent'] for x in r['orientation_comparisons']],[True,False])
        self.assertEqual(r['north_consistent_hypothesis_count'],1)
        self.assertEqual(r['accepted_checkpoints'],0)
