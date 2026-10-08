import math
import unittest
import numpy as np
from voxel_mapper.smiler_reconstruction import emit_lifts, lift_paths, sample_path


def reviewed_route():
    segments=[{'way_id':0,'start':[0,0],'end':[1,0],'station_start_m':i,'station_end_m':i+1} for i in range(119)]
    for i in range(52,60):
        segments[i]={'way_id':1074706894,'start':[i-55,0],'end':[i-54,0],
                     'station_start_m':i*10,'station_end_m':(i+1)*10}
    segments[55]['end']=[30,0]
    for i in range(56,60):segments[i]['start']=[30+i-56,0];segments[i]['end']=[31+i-56,0]
    for i in range(113,119):
        segments[i]={'way_id':597823137,'start':[35+i-113,20],'end':[36+i-113,20],
                     'station_start_m':i*10,'station_end_m':(i+1)*10}
    segments[113]['start']=[0,20]
    return {'segments':segments}


class SmilerLiftTests(unittest.TestCase):
    def test_vertical_span_is_not_lost_in_horizontal_sampling(self):
        points=sample_path([[2,100,3],[2,130,3]])
        self.assertEqual({(math.floor(p[0]),math.floor(p[2])) for p in points},{(2,3)})
        self.assertEqual({math.floor(p[1]) for p in points},set(range(100,131)))
        self.assertLessEqual(max(math.dist(a,b) for a,b in zip(points,points[1:])),.200001)
        with self.assertRaises(ValueError):sample_path([[0,math.nan,0],[0,10,0]])

    def test_both_lifts_have_common_estimated_crest_and_real_vertical_path(self):
        paths,model=lift_paths(reviewed_route(),168)
        self.assertEqual(model['crest_odn_m'],196)
        self.assertEqual(model['vertical_lift_angle_deg'],90)
        foot,crest=paths[1]['points_xyz_m'][1:3]
        self.assertEqual(foot[0::2],crest[0::2])
        self.assertEqual(crest[1]-foot[1],30)

    def test_changed_mapping_is_rejected_before_overlay(self):
        r=reviewed_route();r['segments'][55]['way_id']=123
        with self.assertRaises(ValueError):lift_paths(r,168)

    def test_missing_terrain_and_budget_do_not_emit_incomplete_lifts(self):
        with self.assertRaises(ValueError):emit_lifts(reviewed_route(),168,lambda x,z:None)
        with self.assertRaises(ValueError):emit_lifts(reviewed_route(),168,lambda x,z:165,max_records=10)

    def test_visible_lifts_have_clearance_and_explicit_partial_status(self):
        rows,r=emit_lifts(reviewed_route(),168,lambda x,z:170)
        self.assertEqual(r['status'],'partial_track_lifts_only')
        self.assertGreater(r['components']['inclined_lift_and_approach'],30)
        self.assertGreater(r['components']['vertical_lift_and_approach'],30)
        self.assertGreater(r['below_ground_samples'],0)
        self.assertTrue(any(row['material']=='air' and row['y']<170 for row in rows))
        self.assertEqual(len(rows),len({(row['x'],row['y'],row['z']) for row in rows}))
        indexed={(r['x'],r['y'],r['z']):r for r in rows}
        self.assertEqual(indexed[37,196,20]['material'],'black_concrete','Tower brace replaced crest track')


if __name__=='__main__':unittest.main()
