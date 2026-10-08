"""Visible, explicitly provisional Oblivion track on retained mapped topology.

OSM fixes the horizontal route and covered/tunnel phase boundaries. Official
relative lift/drop dimensions constrain a height hypothesis, not surveyed ODN
levels. The map-derived route order matches station -> lift -> tunnel -> return;
exact slope transitions, station rail offset, bank, support and tunnel sections
remain assumptions. No layer tag is interpreted as metres.
"""
import math

import numpy as np
from shapely.geometry import LineString, Point, Polygon


LIFT_RISE_M = 65*.3048
DROP_M = 180*.3048


def phase_model(route, station_floor):
    if not math.isfinite(station_floor):
        raise ValueError('Finite estimated station floor required')
    segments = route['segments']
    covered = [s for s in segments if route['way_tags'][str(s['way_id'])].get('covered')=='yes']
    tunnel = [s for s in segments if route['way_tags'][str(s['way_id'])].get('tunnel')=='yes']
    if len(covered)!=1 or len(tunnel)<3:
        raise ValueError('One mapped station segment and a multi-segment tunnel required')
    station = covered[0]
    if not station['station_end_m'] < tunnel[0]['station_start_m']:
        raise ValueError('Mapped route order requires station before tunnel')
    approach = [s for s in segments if station['station_end_m']<=s['station_start_m']<tunnel[0]['station_start_m']]
    if len(approach)<4:
        raise ValueError('Lift and crest approach cannot be identified')
    lift = max(approach,key=lambda s:s['station_end_m']-s['station_start_m'])
    tunnel_run = max(tunnel,key=lambda s:s['station_end_m']-s['station_start_m'])
    drop_start = approach[-1]['station_start_m']
    bottom = tunnel_run['station_start_m']
    if not station['station_end_m']<=lift['station_start_m']<lift['station_end_m']<drop_start<bottom:
        raise ValueError('Conflicting station/lift/drop boundaries')
    # The slab is a ground-based estimate, not a rail survey. Three metres puts
    # the rails within the first-pass hollow shell, below the existing roof.
    return_segments=[s for s in segments if s['station_start_m']<station['station_start_m']]
    return_way=return_segments[0]['way_id']
    return_exit=next((s for s in return_segments if s['way_id']!=return_way),None)
    if return_exit is None:
        raise ValueError('Mapped return/brake boundary required')
    turn_end=return_exit['station_start_m']
    brake_entry=turn_end+.5*(return_exit['station_end_m']-turn_end)
    if not 0<turn_end<brake_entry<station['station_start_m']-20:
        raise ValueError('Distinct return turn/dip/brake phases required')
    rail = station_floor+3
    crest = rail+LIFT_RISE_M
    low = crest-DROP_M
    return {'return_turn_peak_m':turn_end*.42, 'return_dip_m':turn_end,
            'brake_entry_m':brake_entry, 'return_peak_odn_m':rail+8, 'return_dip_odn_m':rail-5,
            'return_peak_bank_deg':-80, 'return_profile_status':'qualitative_photo_review_with_estimated_levels',
            'return_reference_url':'https://themeparkreview.com/alton/obliv2.jpg',
            'station_start_m':station['station_start_m'], 'station_end_m':station['station_end_m'],
            'lift_start_m':lift['station_start_m'],'lift_crest_m':lift['station_end_m'],
            'holding_approach_start_m':approach[-2]['station_start_m'],
            'drop_start_m':drop_start,'drop_bottom_m':bottom,
            'tunnel_entry_m':tunnel[0]['station_start_m'], 'tunnel_exit_m':tunnel[-1]['station_end_m'],
            'tunnel_rise_start_m':tunnel_run['station_end_m'],
            'station_rail_odn_m':rail,'crest_odn_m':crest,'bottom_odn_m':low,
            'lift_rise_m':LIFT_RISE_M,'total_drop_m':DROP_M,
            'status':'estimated_phase_profile',
            'direction_basis':'Covered station followed by longest outgoing straight, then mapped tunnel; qualitative dispatch order',
            'limitations':['Return peak (+8 m above station rail), dip (-5 m) and 80 degree left bank are explicit estimates',
                           'Station rail is estimated three metres above the ground-median slab',
                           'Longest mapped outgoing straight is a lift hypothesis, not a surveyed phase boundary',
                           'Official lift/drop dimensions are relative; route slope transitions and tunnel bottom are estimated',
                           'Drop pitch is constrained by mapped horizontal segments and is not a measured 87.5 degree reconstruction']}


def height_profile(stations, model, length, exit_height):
    """Closed C1 profile; exact relative crest/drop heights, no cubic overshoot."""
    controls = [(0,exit_height),
                (model['return_turn_peak_m'],model['return_peak_odn_m']),
                (model['return_dip_m'],model['return_dip_odn_m']),
                (model['brake_entry_m'],model['station_rail_odn_m']),
                (model['lift_start_m'],model['station_rail_odn_m']),
                (model['lift_crest_m'],model['crest_odn_m']),
                (model['drop_start_m'],model['crest_odn_m']),
                (model['drop_bottom_m'],model['bottom_odn_m']),
                (model['tunnel_rise_start_m'],model['bottom_odn_m']+12),
                (length,exit_height)]
    if any(b[0]<=a[0] for a,b in zip(controls,controls[1:])):
        raise ValueError('Ordered distinct phase controls required')
    if not math.isfinite(exit_height+length) or length<=0:
        raise ValueError('Finite profile length and exit height required')
    q=np.asarray(stations,dtype=float)
    if not np.all(np.isfinite(q)) or np.any(q<0) or np.any(q>length):
        raise ValueError('Finite stations within closed route required')
    x=np.array([a for a,b in controls]); h=np.array([b for a,b in controls])
    i=np.clip(np.searchsorted(x,q,side='right')-1,0,len(x)-2)
    t=(q-x[i])/(x[i+1]-x[i])
    return h[i]+(h[i+1]-h[i])*(t*t*(3-2*t))


def bank_profile(stations, model):
    q=np.asarray(stations,dtype=float)
    peak=model['return_turn_peak_m']; end=model['return_dip_m']
    # Smooth in/out roll, peaking on the elevated return curve. Unbank before
    # the dip and rising brake approach; no roll is inferred from OSM layers.
    t=np.where(q<=peak,q/peak,(end-q)/(end-peak))
    t=np.clip(t,0,1)
    return model['return_peak_bank_deg']*(t*t*(3-2*t))


def track_frame(line, station_m, model, length, exit_height):
    a=max(0,station_m-.15); b=min(length,station_m+.15)
    pa,pb=line.interpolate(a),line.interpolate(b)
    ha,hb=height_profile([a,b],model,length,exit_height)
    forward=np.array([pb.x-pa.x,hb-ha,pb.y-pa.y],dtype=float)
    forward/=np.linalg.norm(forward)
    side=np.array([-forward[2],0,forward[0]])
    side/=np.linalg.norm(side)
    up=np.cross(side,forward)
    roll=math.radians(float(bank_profile([station_m],model)[0]))
    return math.cos(roll)*side+math.sin(roll)*up, -math.sin(roll)*side+math.cos(roll)*up


def emit_track(route, station, ground, max_records=250000):
    model=phase_model(route,station['floor_odn_m'])
    length=route['plan_length_m']
    line=LineString([route['segments'][0]['start']]+[s['end'] for s in route['segments']])
    if abs(line.length-length)>1e-5:
        raise ValueError('Profile and mapped route length differ')
    g=ground(*route['segments'][0]['start'])
    if g is None or not math.isfinite(g):
        raise ValueError('Mapped tunnel exit lacks finite ground observation')
    exit_height=g+3
    rows={}; counts={}; below=0
    station_polygon=Polygon(station['footprint']['coordinates'][0])
    def add(x,y,z,material,component):
        key=(math.floor(x),math.floor(y),math.floor(z))
        old=rows.get(key)
        if old and old['material']!='air' and material=='air':return
        rows[key]={'x':key[0],'y':key[1],'z':key[2],'material':material,
                   'kind':'structure','feature':'xsector/oblivion/'+component,
                   'source':'oblivion-estimated-reconstruction',
                   'material_origin':'estimated_reconstruction_void' if material=='air' else 'estimated_reconstruction_shell'}
        if len(rows)>max_records:raise ValueError('Oblivion voxel budget exceeded')
    # Steep drops need 3D-distance sampling; horizontal-only steps can leave
    # ten-metre holes. Subdivide until both rail rise and horizontal travel are
    # below a quarter metre, including all mapped vertices and phase controls.
    knots=sorted(set([0.,length]+[s['station_start_m'] for s in route['segments']]+
                      [model[k] for k in ('lift_start_m','lift_crest_m','drop_start_m','drop_bottom_m','tunnel_rise_start_m','return_turn_peak_m','return_dip_m','brake_entry_m')]))
    samples=[]
    def subdivide(a,b,depth=0):
        ha,hb=height_profile([a,b],model,length,exit_height)
        mid=(a+b)/2; hm=height_profile([mid],model,length,exit_height)[0]
        if depth<18 and (b-a>.2 or abs(hb-ha)>.2 or abs(hm-(ha+hb)/2)>.05):
            subdivide(a,mid,depth+1);subdivide(mid,b,depth+1)
        else:samples.append(a)
    for a,b in zip(knots,knots[1:]):subdivide(a,b)
    samples.append(length)
    heights=height_profile(samples,model,length,exit_height)
    points=[]
    for s,h in zip(samples,heights):
        p=line.interpolate(s); a=line.interpolate(max(0,s-.15));b=line.interpolate(min(length,s+.15))
        dx,dz=b.x-a.x,b.y-a.y; norm=math.hypot(dx,dz)
        if norm<1e-8:raise ValueError('Undefined track direction')
        nx,nz=-dz/norm,dx/norm
        points.append((s,p.x,h,p.y,nx,nz))
        base=ground(p.x,p.y)
        if base is None or not math.isfinite(base):raise ValueError('Complete track terrain coverage required')
        below+=h<base
        # Four metres of overhead clearance and six metres of width also carve
        # the measured terrain volume along the estimated underground course.
        for side in np.arange(-2.5,2.51,.5):
            for dy in np.arange(-1,5.01,.5):
                add(p.x+side*nx,h+dy,p.y+side*nz,'air','train_clearance')
    for s,x,h,z,nx,nz in points:
        lateral,up=track_frame(line,s,model,length,exit_height)
        for side in (-1.,1.):
            add(x+side*lateral[0],h+side*lateral[1],z+side*lateral[2],'iron_block','rails')
        add(x-up[0],h-up[1],z-up[2],'black_concrete','spine')
        if model['lift_start_m']<=s<=model['lift_crest_m']:
            add(x,h,z,'stone','lift_chain')
            add(x+2*nx,h-1,z+2*nz,'stone','lift_walkway')
    for s in np.arange(0,length,2):
        p=line.interpolate(s); h=float(height_profile([s],model,length,exit_height)[0])
        a=line.interpolate(max(0,s-.1));b=line.interpolate(min(length,s+.1));dx,dz=b.x-a.x,b.y-a.y
        norm=math.hypot(dx,dz);nx,nz=-dz/norm,dx/norm
        lateral,up=track_frame(line,s,model,length,exit_height)
        for side in np.arange(-1,1.01,.25):
            add(p.x+side*lateral[0]-up[0],h+side*lateral[1]-up[1],p.y+side*lateral[2]-up[2],'stone','cross_ties')
    for s in np.arange(0,length,8):
        p=line.interpolate(s);h=float(height_profile([s],model,length,exit_height)[0]);base=ground(p.x,p.y)
        if h-base<4 or station_polygon.covers(p):continue
        for y in range(math.floor(base),math.floor(h)-1):
            add(p.x,y,p.y,'stone','support_columns')
    for r in rows.values():counts[r['feature'].rsplit('/',1)[-1]]=counts.get(r['feature'].rsplit('/',1)[-1],0)+1
    physical=[r for r in rows.values() if r['material']!='air']
    return list(rows.values()),{'phase_model':model,'components':counts,'physical_records':len(physical),
                               'sample_count':len(samples),'below_ground_samples':int(below),
                               'sampling':'Adaptive <=0.2 metre rise/travel; mapped vertices included',
                               'appearance':'Estimated rising banked return turn, dip and brake approach; generic rail/spine/ties and simplified support columns',
                               'tunnel_section':'Estimated six metre width and six metre clearance; excavation only',
                               'height_controls_odn_m':{'exit':exit_height,'station':model['station_rail_odn_m'],
                                                        'crest':model['crest_odn_m'],'bottom':model['bottom_odn_m']}}
