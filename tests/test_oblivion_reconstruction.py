import math
import unittest

import numpy as np
from shapely.geometry import LineString, Point

from voxel_mapper.oblivion_reconstruction import DROP_M, LIFT_RISE_M, bank_profile, emit_track, height_profile, phase_model, track_frame


def mapped_route():
    xy=[(0,0),(0,-30),(30,-30),(40,-30),(50,-30),(60,-30),(85,-30),
        (85,-10),(85,-5),(85,0),(85,5),(30,5),(0,5),(0,0)]
    segments=[];s=0
    for i,(a,b) in enumerate(zip(xy,xy[1:])):
        n=s+math.dist(a,b)
        way=1 if i==0 else 5 if i<3 else 2 if i==3 else 3 if i<9 else 4
        segments.append({'start':a,'end':b,'station_start_m':s,'station_end_m':n,'way_id':way});s=n
    return {'segments':segments,'plan_length_m':s,
            'way_tags':{'1':{},'5':{},'2':{'covered':'yes'},'3':{},'4':{'tunnel':'yes'}}}


class OblivionTests(unittest.TestCase):
    def test_relative_drop_includes_underground_depth(self):
        r=mapped_route();m=phase_model(r,100)
        self.assertAlmostEqual(m['crest_odn_m']-m['station_rail_odn_m'],LIFT_RISE_M)
        self.assertAlmostEqual(m['crest_odn_m']-m['bottom_odn_m'],DROP_M)
        self.assertLess(m['bottom_odn_m'],100)
        q=[0,m['lift_start_m'],m['lift_crest_m'],m['drop_start_m'],m['drop_bottom_m'],r['plan_length_m']]
        h=height_profile(q,m,r['plan_length_m'],103)
        np.testing.assert_allclose(h,[103,103,103+LIFT_RISE_M,103+LIFT_RISE_M,103+LIFT_RISE_M-DROP_M,103])

    def test_closed_profile_never_overshoots_dimension_controls(self):
        r=mapped_route();m=phase_model(r,100)
        h=height_profile(np.linspace(0,r['plan_length_m'],1000),m,r['plan_length_m'],103)
        self.assertGreaterEqual(h.min(),m['bottom_odn_m'])
        self.assertLessEqual(h.max(),m['crest_odn_m'])
        with self.assertRaises(ValueError):height_profile([math.nan],m,r['plan_length_m'],103)

    def test_return_rises_then_dips_then_reaches_level_brakes(self):
        r=mapped_route();m=phase_model(r,100)
        q=[0,m['return_turn_peak_m'],m['return_dip_m'],m['brake_entry_m'],m['station_start_m']]
        h=height_profile(q,m,r['plan_length_m'],103)
        self.assertGreater(h[1],h[0]+5)
        self.assertLess(h[2],h[1]-10)
        self.assertGreater(h[3],h[2])
        self.assertEqual(h[3],h[4])
        roll=bank_profile(q,m)
        self.assertEqual(roll[0],0)
        self.assertEqual(roll[1],-80)
        np.testing.assert_allclose(roll[2:],0)

    def test_one_block_track_has_no_offset_or_wide_components(self):
        r=mapped_route()
        station={'floor_odn_m':100,'footprint':{'type':'Polygon','coordinates':[[[40,-35],[50,-35],[50,-25],[40,-25],[40,-35]]]}}
        rows,report=emit_track(r,station,lambda x,z:100)
        line=LineString([r['segments'][0]['start']]+[s['end'] for s in r['segments']])
        self.assertEqual(report['track_width_blocks'],1)
        self.assertFalse(set(report['components']) & {'spine','cross_ties','lift_walkway'})
        for row in rows:
            if row['material']=='air':continue
            distance=line.distance(Point(row['x']+.5,row['z']+.5))
            self.assertLessEqual(distance,math.sqrt(.5)+1e-6,'Physical track expanded sideways beyond centreline cells')

    def test_rails_follow_orthogonal_pitch_and_roll_frame(self):
        r=mapped_route();m=phase_model(r,100)
        line=LineString([r['segments'][0]['start']]+[s['end'] for s in r['segments']])
        for station in (m['return_turn_peak_m']/2,m['return_turn_peak_m'],m['lift_start_m']+5):
            lateral,up=track_frame(line,station,m,r['plan_length_m'],103)
            self.assertAlmostEqual(np.linalg.norm(lateral),1)
            self.assertAlmostEqual(np.linalg.norm(up),1)
            self.assertAlmostEqual(float(np.dot(lateral,up)),0)
        lateral,up=track_frame(line,m['return_turn_peak_m'],m,r['plan_length_m'],103)
        self.assertLess(lateral[1],-.95)

    def test_missing_tunnel_tags_cannot_silently_emit_above_ground_drop(self):
        r=mapped_route();r['way_tags']['4']={}
        with self.assertRaises(ValueError):phase_model(r,100)

    def test_visible_rails_and_excavation_are_emitted_and_connected(self):
        station={'floor_odn_m':100,'footprint':{'type':'Polygon','coordinates':[[[40,-35],[50,-35],[50,-25],[40,-25],[40,-35]]]}}
        rows,report=emit_track(mapped_route(),station,lambda x,z:100)
        self.assertGreater(report['components']['rails'],100)
        self.assertGreater(report['components']['support_columns'],0)
        self.assertGreater(report['below_ground_samples'],0)
        self.assertTrue(any(r['material']=='air' and r['y']<100 for r in rows))
        track={(r['x'],r['y'],r['z']) for r in rows if r['feature'].rsplit('/',1)[-1] in ('rails','spine','cross_ties','lift_chain')}
        remaining=set(track); stack=[remaining.pop()]
        while stack:
            x,y,z=stack.pop()
            for dx in (-1,0,1):
                for dy in (-1,0,1):
                    for dz in (-1,0,1):
                        p=(x+dx,y+dy,z+dz)
                        if p in remaining:remaining.remove(p);stack.append(p)
        self.assertFalse(remaining,'Steep drop or curve left disconnected track voxels')
        with self.assertRaises(ValueError):emit_track(mapped_route(),station,lambda x,z:None)


if __name__=='__main__':unittest.main()
