"""Terrain shoulder clearance and explicit covered-track height slots."""
import math
import numpy as np
from . import timber_track_world as timber


def fit_profile(route, controls, terrain, settings, structures=None):
    stations=np.linspace(0,route.length,math.ceil(route.length/.5)+1)
    zones=settings['covered_zones']; width=settings['shoulder_half_width_m']
    obstacles={}
    for (x,h,y),m in (structures or {}).items():
        if m=='oak_fence' or m.endswith('_wall') or m in ['stone_bricks','cobblestone','sandstone']:
            obstacles[x,y]=max(obstacles.get((x,y),-math.inf),h+(1.5 if m=='oak_fence' or m.endswith('_wall') else 1))
    desired=[];minimum=[];covered=[];probes=[]
    for s in stations:
        p,t,n=timber.frame(route,float(s))
        cells={tuple(map(math.floor,p+off*n+forward*t)) for off in np.arange(-width,width+.01,.4) for forward in [-.75,0,.75]}
        if any(q not in terrain for q in cells):raise ValueError('Track shoulder leaves available terrain')
        ground=max(terrain[q]['y']+1 for q in cells)
        footprint={tuple(map(math.floor,p+off*n+forward*t)) for off in [-2,-1,0,1,2] for forward in [-.4,0,.4]}
        obstacle=max((obstacles.get(q,-math.inf) for q in footprint),default=-math.inf)
        need=max(ground,obstacle)+settings['minimum_deck_top_over_ground_m']
        zone=next((z for z in zones if z['start_m']<=s<=z['end_m']),None)
        top=timber.height_at(float(s),controls)
        if zone and 'top_m' in zone:top=zone['top_m']
        desired.append(top);minimum.append(need);covered.append(zone)
        probes.append({'station_m':float(s),'maximum_shoulder_ground_top_m':ground,'maximum_retained_obstacle_top_m':obstacle if math.isfinite(obstacle) else None,'minimum_deck_top_m':need,
                       'covered_zone':zone['id'] if zone else None})
    fitted=np.maximum(desired,minimum)
    for i,zone in enumerate(covered):
        if zone:fitted[i]=desired[i]
    # Majorant smoothing raises outdoor neighbours of a bump rather than
    # cutting terrain. Explicit covered slots act as barriers to that raise.
    ds=stations[1]-stations[0];grade=settings['maximum_smoothing_grade']
    for _ in range(3):
        for seq in [range(1,len(fitted)),range(len(fitted)-2,-1,-1)]:
            for i in seq:
                if covered[i]:continue
                j=i-1 if isinstance(seq,range) and seq.step>0 else i+1
                fitted[i]=max(fitted[i],fitted[j]-grade*ds)
        fitted[0]=fitted[-1]=max(fitted[0],fitted[-1])
    output=[{'label':'terrain_fit','station_m':float(s),'height_m':float(h),'estimated':True} for s,h in zip(stations,fitted)]
    deviations=[]
    for c in controls:
        if c.get('estimated'):continue
        actual=timber.height_at(c['station_m'],output)
        deviations.append({'label':c.get('label','unlabelled_control'),'source_height_m':c['height_m'],'display_height_before_rounding_m':actual,
                           'difference_m':actual-c['height_m']})
    return output,{'source_level_comparison':deviations,'probes':probes,'settings':settings,
                   'outdoor_profile_never_below_shoulder_requirement':all(h+1e-8>=m for h,m,z in zip(fitted,minimum,covered) if not z),
                   'maximum_raise_over_interpolated_profile_m':float(max(h-d for h,d in zip(fitted,desired))),
                   'outdoor_terrain_excavation_allowed':False}


def check_terrain(terrain, blocks, core, samples, settings):
    """Validate actual slab undersides against untouched terrain and shoulders."""
    visits={}
    for sample in samples:
        s=sample['station_m'];zone=next((z for z in settings['covered_zones'] if z['start_m']<=s<=z['end_m']),None)
        for xy in sample['cells_xy']:visits.setdefault(tuple(xy),set()).add(zone['id'] if zone else None)
    outdoors=set();buried=[];shoulders=[]
    for (x,h,y),m in core.items():
        zones=visits.get((x,y),{None})
        if zones!={None}:continue
        outdoors.add((x,y))
        underside=h+(.5 if m.endswith('_slab_top') else 0)
        if underside<terrain[x,y]['y']+1:buried.append([x,h,y])
        # One-metre bank check catches adjacent grass faces at deck height.
        for dx,dy in [(1,0),(-1,0),(0,1),(0,-1)]:
            q=(x+dx,y+dy)
            if q in terrain and terrain[q]['y']+1>underside:shoulders.append([x,h,y,list(q)])
    if buried or shoulders:raise ValueError('Outdoor track/terrain clearance failed: '+str((buried[:4],shoulders[:4])))
    return {'outdoor_deck_columns_checked':len(outdoors),'buried_outdoor_slabs':0,'adjacent_banks_above_slab_underside':0}
