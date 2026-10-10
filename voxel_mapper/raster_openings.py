"""Review raster jamb/head support near pinned vertical traces; no physical identity."""
import hashlib
import math
import numpy as np

VERSION = 'raster-jamb-head-hypotheses-v1'


def detect(gray, top, bottom, metres_per_pixel, radius=140, endpoint_bound=2):
    gray=np.asarray(gray)
    if gray.ndim!=2 or gray.size>6000000 or gray.dtype!=np.uint8:
        raise ValueError('Bounded uint8 grayscale page required')
    if not math.isfinite(metres_per_pixel) or metres_per_pixel<=0 or not 1<=radius<=200 or not 0<=endpoint_bound<=4:
        raise ValueError('Finite scale and bounded pixel search required')
    x,y=top; bx,by=bottom
    if any(type(v) is not int for v in (x,y,bx,by)) or abs(x-bx)>1 or not 0<=x<gray.shape[1] or not 3<=y<by-6 or not y>=endpoint_bound or by>=gray.shape[0]:
        raise ValueError('Interior vertical source trace required')
    if by-y>400:
        raise ValueError('Opening height search budget exceeded')
    lo=max(0,x-radius);hi=min(gray.shape[1],x+radius+1)
    variants=[]
    for threshold in (220,235):
        occupancy=(gray[y+3:by-3,lo:hi]<threshold).mean(axis=0)
        groups=[]
        for column in np.flatnonzero(occupancy>=.8)+lo:
            if groups and column==groups[-1][-1]+1:groups[-1].append(int(column))
            else:groups.append([int(column)])
        if len(groups)>100:
            raise ValueError('Raster jamb group budget exceeded')
        pairs=[]
        for left in groups:
            for right in groups:
                if not left[-1]<x<right[0]:continue
                width=(sum(right)/len(right)-sum(left)/len(left))*metres_per_pixel
                if not .5<=width<=6:continue
                rows=[]
                for row in range(y-endpoint_bound,y+endpoint_bound+1):
                    fraction=float((gray[row,left[0]:right[-1]+1]<threshold).mean())
                    if fraction>=.9:rows.append({'row':row,'dark_fraction':fraction})
                if rows:
                    pairs.append({'left_pixel_columns':left,'right_pixel_columns':right,'head_row_support':rows,
                                  'nominal_width_m':width,'threshold':threshold})
                if len(pairs)>500:raise ValueError('Raster jamb pair budget exceeded')
        variants.append(pairs)
    results=[]
    for a in variants[0]:
        for b in variants[1]:
            if any(abs(a[k][edge]-b[k][edge])>2 for k in ('left_pixel_columns','right_pixel_columns') for edge in (0,-1)):
                continue
            left=[v for r in (a,b) for v in r['left_pixel_columns']];right=[v for r in (a,b) for v in r['right_pixel_columns']]
            results.append({'threshold_candidates':[a,b],
                            'observed_jamb_span_interval_m':[(min(right)-max(left))*metres_per_pixel,
                                                            (max(right)-min(left))*metres_per_pixel],
                            'nominal_width_interval_m':[(min(right)-max(left)-2*endpoint_bound)*metres_per_pixel,
                                                        (max(right)-min(left)+2*endpoint_bound)*metres_per_pixel],
                            'status':'unverified_raster_jamb_head_candidate','physical_opening_verified':False,
                            'height_datum_verified':False,'world_geometry_additions':0})
            if len(results)>500:raise ValueError('Raster consensus budget exceeded')
    crop=gray[y-endpoint_bound:by+1,lo:hi]
    return {'version':VERSION,'source_crop_pixels_sha256':hashlib.sha256(crop.tobytes()).hexdigest(),
            'source_crop_bbox_pixels':[lo,y-endpoint_bound,hi,by+1],
            'seed_trace_top_pixels':list(top),'seed_trace_bottom_pixels':list(bottom),
            'metres_per_pixel_nominal':metres_per_pixel,'manual_endpoint_bound_pixels':endpoint_bound,
            'recipe':{'thresholds':[220,235],'minimum_jamb_dark_fraction':.8,'minimum_head_dark_fraction':.9,
                      'maximum_threshold_edge_spread_pixels':2,'search_radius_pixels':radius,
                      'nominal_width_discovery_range_m':[.5,6]},
            'candidates':results,'world_geometry_additions':0}
