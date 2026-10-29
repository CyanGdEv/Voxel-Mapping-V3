"""Bounded support bays from adjacent registered brown-footing assignments.

Separate track stations stay separate at crossings. This does not bridge a
whole ride footprint, join XY-nearest tracks, or extend timber above its deck.
"""
from collections import Counter,defaultdict
import math

import numpy as np
from shapely import contains_xy
from shapely.geometry import Polygon


def support_bay_caps(l,settings):
    from .alton_aligned_world import WICKER_AFFINE
    a,b,d,e,tx,ty=WICKER_AFFINE
    caps=np.full(l.ground.shape,-32768,np.int16)
    groups=defaultdict(list);held=Counter();accepted=[]
    for row in l.wicker_quality['fence_supports']['constructed_supports']:
        family=row['source_post']['symbol_family'];offset=row['source_post'].get('offset_m',0)
        bank=int(np.sign(offset))
        groups[family,bank].append(row)
    def world(point):
        x,z=point;z+=1 # Match nominal source Y to the exported voxel row.
        return (a*x+b*z+tx-l.e0,l.n0-(d*x+e*z+ty))
    for rows in groups.values():
        rows=sorted(rows,key=lambda row:(row['target_sample_station_m'],str(row['source_foot_index'])))
        for left,right in zip(rows,rows[1:]):
            gap=right['target_sample_station_m']-left['target_sample_station_m']
            if gap>settings['maximum_adjacent_station_gap_m']:held['station_gap']+=1;continue
            f0=np.asarray(left['source_post']['xy']);f1=np.asarray(right['source_post']['xy'])
            if np.linalg.norm(f1-f0)>settings['maximum_adjacent_footing_gap_m']:held['footing_gap']+=1;continue
            polygon=Polygon([world(f0),world(f1),world(right['target']['xy']),world(left['target']['xy'])])
            if not polygon.is_valid or polygon.area<.05:held['degenerate_or_crossed_bay']+=1;continue
            # The fence's full 1.5 m collision height stays below both decks.
            cap=math.floor(min(left['deck_underside_m'],right['deck_underside_m'])+l.offset-1.5)
            x0,z0,x1,z1=polygon.bounds
            xs=np.arange(max(0,math.floor(x0)),min(l.width,math.ceil(x1)))
            zs=np.arange(max(-l.height,math.floor(z0)),min(0,math.ceil(z1)))
            if not len(xs) or not len(zs):continue
            xx,zz=np.meshgrid(xs,zs);inside=contains_xy(polygon,xx+.5,zz+.5)
            rr,cc=zz[inside]+l.height,xx[inside]
            caps[rr,cc]=np.maximum(caps[rr,cc],cap)
            accepted.append({'station_range_m':[left['target_sample_station_m'],right['target_sample_station_m']],
                'source_feet':[left['source_foot_index'],right['source_foot_index']],
                'maximum_fence_base_native_y':cap,'native_footprint_ring':list(polygon.exterior.coords)})
    l.ride_support_bay_caps=caps
    return {'version':'registered-wicker-support-bays-v1','bays':len(accepted),'columns':int((caps>-32768).sum()),
        'maximum_adjacent_station_gap_m':settings['maximum_adjacent_station_gap_m'],
        'maximum_adjacent_footing_gap_m':settings['maximum_adjacent_footing_gap_m'],
        'withheld_pairs':dict(held),'source_to_exported_voxel_row_offset':1,
        'source_feet_and_track_assignments_relocated':False,'crossing_tracks_joined_by_xy':False,
        'interpretation':'Only adjacent brown-footing-to-assigned-track bays, capped below both deck undersides; no global footprint hull.'}
