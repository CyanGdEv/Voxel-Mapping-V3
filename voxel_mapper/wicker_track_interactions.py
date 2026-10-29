"""Bounded source-track revision and three-dimensional sculpture passages."""
from collections import Counter,defaultdict,deque
from copy import deepcopy
import json
import math
from pathlib import Path

import numpy as np
from shapely.affinity import affine_transform
from shapely.geometry import LineString,shape

from .generation_cycles import file_hash
from .timber_track_world import height_at
from .full_track_world import sample_route
from .steep_track_world import thicken,surface_top
from .fence_support_world import deck_intervals,staircase_line
from .footprint_supports import obstruction
from .dense_footprint_supports import route_member


DECK={'oak_planks','spruce_planks','oak_slab','spruce_slab','oak_slab_top','spruce_slab_top'}


def source_map(path):
    return {tuple(r['source_xyz']):r['material'] for r in json.loads(Path(path).read_text())}


def _raster(l,solid,head,changed):
    """Use exactly the inverse raster convention of ParkLayers._detail.

    Track/support receipts store nominal Y; exported voxel rows store Z=Y+1.
    The extra cell must also be applied to passage/sample positions.
    """
    from .alton_aligned_world import WICKER_AFFINE
    a,b,d,e,tx,ty=WICKER_AFFINE;inverse=np.linalg.inv([[a,b],[d,e]])
    current={(cx*16+x,y,cz*16+z):m for (cx,cz),rows in l.detail.items() for x,y,z,m in rows}
    clear={(cx*16+x,y,cz*16+z) for (cx,cz),rows in l.clear.items() for x,y,z in rows}
    old=current.copy();old_clear=clear.copy()
    columns=defaultdict(list);air=defaultdict(list)
    for (x,y,z),m in solid.items():columns[x,z+1].append((y,m))
    for x,y,z in head:air[x,z+1].append(y)
    # The original detail bbox includes terrain around every changed member.
    source_cols={(x,z+1) for x,z in changed}
    en=np.asarray([[a*x+b*z+tx,d*x+e*z+ty] for x,z in source_cols])
    x0=max(0,math.floor(en[:,0].min()-l.e0)-3);x1=min(l.width,math.ceil(en[:,0].max()-l.e0)+4)
    z0=max(-l.height,math.floor(l.n0-en[:,1].max())-3);z1=min(0,math.ceil(l.n0-en[:,1].min())+4)
    mapping=defaultdict(list)
    for x in range(x0,x1):
        for z in range(z0,z1):
            p=inverse@np.array([l.e0+x+.5-tx,l.n0-z-.5-ty]);col=tuple(map(math.floor,p))
            if col not in source_cols:continue
            mapping[col].append((x,z))
            for key in [k for k in current if k[0]==x and k[2]==z]:current.pop(key)
            clear.difference_update(k for k in tuple(clear) if k[0]==x and k[2]==z)
            for y,m in columns.get(col,()):current[x,y+l.offset,z]=m
            for y in air.get(col,()):clear.add((x,y+l.offset,z))
    grouped=defaultdict(list);grouped_air=defaultdict(list)
    for (x,y,z),m in current.items():grouped[x//16,z//16].append((x%16,y,z%16,m))
    for x,y,z in clear:grouped_air[x//16,z//16].append((x%16,y,z%16))
    l.detail=dict(grouped);l.clear=dict(grouped_air)
    # Complete source-column lookup, including unchanged track columns.
    for x,z in {(k[0],k[2]) for k in current}:
        p=inverse@np.array([l.e0+x+.5-tx,l.n0-z-.5-ty]);col=tuple(map(math.floor,p))
        if (x,z) not in mapping[col]:mapping[col].append((x,z))
    delta={k for k in set(old)|set(current) if old.get(k)!=current.get(k)}
    l.track_interaction_allowed_changes=delta|(old_clear^clear)
    l.parent_wicker_detail=old;l.parent_wicker_clear=old_clear
    return mapping,delta,old_clear^clear


def revise_track(l,settings,markings,pdf):
    """Change one explicitly estimated crest, keeping printed controls and XY."""
    q=deepcopy(l.wicker_quality);parent_rows=deepcopy(q['fence_supports']['constructed_supports'])
    samples=json.loads((l.wicker/'track-samples.json').read_text())
    for name,expected in settings['base_pins'].items():
        if file_hash(l.wicker/name)!=expected:raise ValueError('Track interaction parent changed: '+name)
    if file_hash(markings)!=q['planning_source_pins']['markings'] or file_hash(pdf)!=q['fence_supports']['source_pdf_sha256']:
        raise ValueError('Pinned original planning geometry required')
    data=json.loads(Path(markings).read_text());unit=settings['metres_per_pdf_point']
    line=affine_transform(shape(next(r['geometry_pdf_native'] for r in data['records'] if r['role']=='track_centre')),[unit,0,0,unit,0,0])
    route=LineString(list(line.coords)+[line.coords[0]])
    if abs(route.length-samples[-1]['station_m'])>1e-8:raise ValueError('Saved source station frame changed')
    voxels=[json.loads(s) for s in (l.wicker/'voxels.jsonl').read_text().splitlines()]
    terrain={(r['x'],r['z']-1):r for r in voxels if r['kind']=='terrain'}
    all_solid={(r['x'],r['y'],r['z']-1):r['material'] for r in voxels if r['kind']=='structure'}
    old_track=source_map(l.wicker/'track-blocks.json');old_support=source_map(l.wicker/'support-blocks.json')
    architecture={k:m for k,m in all_solid.items() if k not in old_track and k not in old_support}
    steep=json.loads((Path(__file__).with_name('data')/'wicker-steep-track-deck.json').read_text())
    controls=q['full_track']['controls'];changed_controls=deepcopy(controls)
    target=next(c for c in changed_controls if c['label']==settings['estimated_control_label'])
    if not target.get('estimated') or target['height_m']!=settings['parent_control_top_m']:
        raise ValueError('Only the declared estimated crest may change')
    target['height_m']=settings['revised_control_top_m']
    old_dense=[{'station_m':s['station_m'],'height_m':s['running_top_m']} for s in samples]
    pre,_,head,replayed,topology=sample_route(route,old_dense,clearance_blocks=2)
    if not np.array_equal([s['cells_xy'] for s in replayed],[s['cells_xy'] for s in samples]):
        raise ValueError('Saved source sample XY differs from original plan')
    replay,_,_,_=thicken(pre,{**architecture,**pre},terrain,head,replayed,topology['centre_sample_keys'],steep)
    if replay!=old_track or head!=set(map(tuple,json.loads((l.wicker/'running-clearance-air.json').read_text()))):
        raise ValueError('Parent track must replay exactly before any revision')
    dense=[{'station_m':s['station_m'],'height_m':round(2*(s['running_top_m']+
        height_at(s['station_m'],changed_controls)-height_at(s['station_m'],controls)))/2} for s in samples]
    pre,_,head,new_samples,topology=sample_route(route,dense,clearance_blocks=2)
    track,core,_,steep_review=thicken(pre,{**architecture,**pre},terrain,head,new_samples,topology['centre_sample_keys'],steep)
    changed_track={k for k in set(old_track)|set(track) if old_track.get(k)!=track.get(k)}
    intervals=deck_intervals(track);changed_xy={(k[0],k[2]) for k in changed_track}
    for (x,y,z),m in core.items():
        if (x,z) in changed_xy:
            underside=y+(.5 if m.endswith('_slab_top') else 0)
            if underside<terrain[x,z]['y']+1:raise ValueError('Revised track would enter terrain')
    gaps=[b[0]-a[1] for xy in changed_xy for a,b in zip(intervals.get(xy,()),intervals.get(xy,())[1:])]
    if gaps and min(gaps)<settings['minimum_stacked_gap_m']-1e-8:raise ValueError('Revised crossing has insufficient deck separation')
    protected=set(head)
    for (x,z),parts in intervals.items():
        for lo,hi in parts:protected.update((x,y,z) for y in range(math.ceil(hi),math.ceil(hi)+3))
    stationary={**architecture,**track};support={};members=[];held=[];retargeted=rerouted=0
    stations=np.asarray([s['station_m'] for s in new_samples]);keys=topology['centre_sample_keys']
    for row in parent_rows:
        r=deepcopy(row);i=int(np.argmin(abs(stations-r['target_sample_station_m'])));deck=tuple(keys[i]);dx,dy,dz=deck
        top=surface_top(deck,track[deck]);own=[p for p in intervals[dx,dz] if abs(p[1]-top)<1e-6 or p[0]<=dy<p[1]]
        under=min(p[0] for p in own);end=(dx,math.floor(under)-1,dz);start=tuple(r['start_cell_xyz'])
        bearing=set()
        for j in range(max(0,i-8),min(len(new_samples),i+9)):
            for x,z in new_samples[j]['cells_xy']:
                for lo,hi in intervals.get((x,z),()):
                    if abs(hi-new_samples[j]['running_top_m'])<=.75:bearing.add((x,math.floor(lo),z))
        changed_end=end!=tuple(r['end_cell_xyz']);path=[tuple(k) for k in r['member_cells']]
        reason=obstruction(path,terrain,stationary,protected,start,bearing)
        if changed_end or reason:
            path=staircase_line(start,end)
            reason='below_source_footing' if end[1]<start[1] else obstruction(path,terrain,stationary,protected,start,bearing)
            if reason and end[1]>=start[1]:
                recovered=route_member(start,end,lambda k:obstruction([k],terrain,stationary,protected,start,bearing) is None)
                if recovered is not None:path=recovered;reason=None;rerouted+=1
            if reason:
                held.append({'source_foot_index':r['source_foot_index'],'source_post':r['source_post'],
                    'target':r['target'],'reason':reason,'revised_end_cell_xyz':list(end)});continue
            retargeted+=int(changed_end)
        r.update(end_cell_xyz=list(end),target_centre_deck_key=list(deck),deck_top_m=top,deck_underside_m=under,
                 member_cells=[list(k) for k in path])
        members.append(r);support.update({k:'dark_oak_fence' for k in path})
    solid={**architecture,**track,**support}
    changed={k for k in set(all_solid)|set(solid) if all_solid.get(k)!=solid.get(k)}
    old_head=set(map(tuple,json.loads((l.wicker/'running-clearance-air.json').read_text())))
    cols={(x,z) for x,y,z in changed|head|old_head if (x,y,z) in changed or (x,y,z) in head^old_head}
    mapping,native_delta,air_delta=_raster(l,solid,head,cols)
    native_track={};native_samples=[]
    for key,m in track.items():
        x,y,z=key
        for xx,zz in mapping.get((x,z+1),()):native_track[xx,y+l.offset,zz]=m
    from .alton_aligned_world import WICKER_AFFINE
    a,b,d,e,tx,ty=WICKER_AFFINE
    aliases=0;native_intervals=deck_intervals(native_track)
    for index,(s,key) in enumerate(zip(new_samples,keys)):
        x,y,z=key;columns=mapping.get((x,z+1),())
        if not columns:
            # A rotated metre raster can omit a nominal centre column. Follow
            # adjacent samples of this same station branch, never a crossing.
            columns=[c for j in range(max(0,index-4),min(len(keys),index+5))
                if abs(surface_top(tuple(keys[j]),core[tuple(keys[j])])-surface_top(tuple(key),core[tuple(key)]))<=.5
                for c in mapping.get((keys[j][0],keys[j][2]+1),())]
            aliases+=1
        if not columns:raise ValueError('Source centre deck missing from native raster')
        wanted=np.array([a*(x+.5)+b*(z+1.5)+tx-l.e0,l.n0-(d*(x+.5)+e*(z+1.5)+ty)])
        xx,zz=min(columns,key=lambda c:np.linalg.norm(np.array(c)+.5-wanted))
        desired_top=surface_top(tuple(key),core[tuple(key)])+l.offset
        physical_top=min(native_intervals[xx,zz],key=lambda p:abs(p[1]-desired_top))[1]
        if abs(physical_top-desired_top)>1:raise ValueError('Native route alias exceeds height budget')
        n=np.asarray(s['normal']);normal=np.array([a*n[0]+b*n[1],-(d*n[0]+e*n[1])]);normal/=np.linalg.norm(normal)
        native_samples.append({'station_m':s['station_m'],'xyz':[xx+.5,physical_top,zz+.5],
            'normal_xz':normal.tolist(),'deck_cell_xyz':[xx,math.ceil(physical_top)-1,zz]})
    l.revised_wicker_samples=new_samples;l.wicker_track_native_decks=native_track;l.wicker_native_samples=native_samples
    l.parent_wicker_supports=parent_rows;l.wicker_quality=q
    q['fence_supports']['constructed_supports']=members
    q['fence_supports']['withheld_supports'].extend(held)
    q['fence_supports']['added_support_cells']=len(support)
    q['full_track']['effective_display_controls']=changed_controls
    q['full_track']['topology']=topology
    record={'id':'wicker-track-interactions','parent_exact_replay':True,'source_xy_samples_unchanged':True,
        'printed_height_controls_changed':False,'estimated_control_label':target['label'],
        'old_estimated_top_m':settings['parent_control_top_m'],'revised_estimated_top_m':target['height_m'],
        'minimum_stacked_deck_gap_m':min(gaps) if gaps else None,'retargeted_existing_supports':retargeted,
        'rerouted_existing_supports':rerouted,'newly_withheld_supports':held,'constructed_supports':len(members),
        'native_detail_states_changed':len(native_delta),'native_reserved_air_states_changed':len(air_delta),
        'source_to_exported_voxel_y_offset':1,'native_centre_aliases_using_same_branch_neighbours':aliases,
        'source_markings_sha256':file_hash(markings),'source_pdf_sha256':file_hash(pdf),
        'no_new_ground_footprints':True,'physical_as_built_accuracy_verified':False,
        'interpretation':'Only the unprinted crossing estimate is reduced; existing terrain-fit offsets and every printed control are retained. LiDAR supplies dated height context, not identified rail truth.'}
    l.audit['wicker_track_interactions']=record
    q['version']='wicker-interaction-adjusted-detail-v1'
    q['parent_world']=q.pop('world',None)
    q['interaction_revision']=record
    l.audit['geometry']['wicker_detail']['retained_blocks']=sum(map(len,l.detail.values()))
    return record


def anchor_opening_frames(scene,proposed,intersects):
    """Connect clipped framing without placing timber in a reserved passage."""
    result=dict(proposed);l=scene.l
    reserved=set(getattr(scene,'old_air',()))|set(scene.air)
    retained={}
    for (cx,cz),rows in getattr(l,'detail',{}).items():
        for x,y,z,m in rows:retained[cx*16+x,y,cz*16+z]=m
    retained.update(getattr(scene,'blocks',{}))
    def wooden(m):return any(t in m for t in ('planks','log','fence','slab','trapdoor','stairs'))
    def usable(k):
        x,y,z=k
        return (k not in reserved and k not in getattr(scene,'old_solid',()) and
                not intersects(k) and (not hasattr(l,'ground') or
                (0<=x<l.width and -l.height<=z<0 and y>l.ground[z+l.height,x])))
    moved=0
    for key,m in list(result.items()):
        if m!='campfire':continue
        pad=(key[0],key[1]-1,key[2])
        if wooden(retained.get(pad,result.get(pad,''))) and (pad in retained or usable(pad)):continue
        # Raising an emitter one cell leaves its timber pad above the opening.
        # Neither the pad nor the new emitter may enter a reserved volume.
        for rise in range(1,4):
            fire=(key[0],key[1]+rise,key[2]);pad=(fire[0],fire[1]-1,fire[2])
            if usable(pad) and usable(fire) and fire not in result:
                result.pop(key);result[pad]='spruce_planks';result[fire]='campfire';moved+=1;break
        else:raise ValueError('No clear timber pad for a shoulder emitter')
    model={k for k in result if usable(k)}
    bounds=np.asarray(list(model));low=bounds.min(0)-1;high=bounds.max(0)+1
    context={k for k,m in retained.items() if wooden(m) and np.all(np.asarray(k)>=low) and np.all(np.asarray(k)<=high)}
    occupied=model|context;neighbours=((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1))
    def adjacent(k):
        for delta in neighbours:yield tuple(a+b for a,b in zip(k,delta))
    remaining=set(occupied);parts=[]
    while remaining:
        part={remaining.pop()};queue=deque(part)
        while queue:
            for k in adjacent(queue.popleft()):
                if k in remaining:remaining.remove(k);part.add(k);queue.append(k)
        if part&model:parts.append(part)
    parts.sort(key=lambda part:len(part&model),reverse=True);root=set(parts[0]);added=0
    for part in parts[1:]:
        starts=sorted(k for k in part if result.get(k)!='campfire')
        queue=deque(starts);previous={k:None for k in starts};depth={k:0 for k in starts};finish=None
        while queue and finish is None:
            current=queue.popleft()
            for k in adjacent(current):
                if k in root:previous[k]=current;finish=k;break
                if k in previous or depth[current]>=6 or not usable(k):continue
                if np.any(np.asarray(k)<low) or np.any(np.asarray(k)>high):continue
                previous[k]=current;depth[k]=depth[current]+1;queue.append(k)
        if finish is None:raise ValueError('Opening frame cannot connect without obstructing a passage')
        path=[];current=finish
        while current is not None:path.append(current);current=previous[current]
        for k in path:
            if k not in occupied:result[k]='spruce_planks';occupied.add(k);added+=1
        root.update(part);root.update(path)
    return result,{'connecting_frame_cells':added,'raised_shoulder_emitters':moved}


def fit_figure(scene,proposed,profile):
    """Open the complete deck-width swept volume, preserving each route visit."""
    l=scene.l;settings=profile['track_interactions'];height=settings['opening_clear_height_m'];half=settings['opening_half_width_m']
    visits=[]
    for low,high in settings['figure_station_windows_m']:
        visits.append([s for s in l.wicker_native_samples if low<=s['station_m']<=high])
    samples=[s for v in visits for s in v];centres=np.array([s['xyz'] for s in samples]);normals=np.array([s['normal_xz'] for s in samples])
    tangents=np.column_stack([-normals[:,1],normals[:,0]])
    def intersects(key,material='spruce_planks'):
        x,y,z=key;dy0=.5 if material.endswith('_slab_top') else 0
        dy1=.5 if material.endswith('_slab') else 1.5 if material.endswith('_fence') else 1
        delta=np.array([x+.5,z+.5])-centres[:,[0,2]]
        along=abs(np.sum(delta*tangents,axis=1));across=abs(np.sum(delta*normals,axis=1))
        return bool(np.any((along<=.65+.5*np.abs(tangents).sum(1))&
            (across<=half+.5*np.abs(normals).sum(1))&(y+dy1>centres[:,1]+.01)&(y+dy0<centres[:,1]+height-.01)))
    l.wicker_aperture_intersects=intersects
    removed={k:m for k,m in proposed.items() if intersects(k,m)}
    result={k:m for k,m in proposed.items() if k not in removed};frames={};records=[]
    p=profile['big_bob'];front=np.asarray(p['front_bng_direction']);side=np.array([-front[1],front[0]])
    sections=np.asarray(p['body_sections_height_half_width_half_depth_m'])
    def inside(s):
        x,y,z=s['xyz'];en=np.array([l.e0+x,l.n0-z]);delta=en-np.asarray(p['body_center_bng_en']);u,v=delta@side,delta@front
        h=y-l.offset-p['base_odn_m']+1
        if not 0<h<sections[-1,0]:return False
        ru=np.interp(h,sections[:,0],sections[:,1]);rv=np.interp(h,sections[:,0],sections[:,2])
        return (abs(u)/ru)**3+(abs(v)/rv)**3<=1
    for number,visit in enumerate(visits,1):
        interior=[s for s in visit if inside(s)]
        if not interior:raise ValueError('Track visit does not enter the sculpture torso: '+str(number))
        portals=[]
        for s in (interior[0],interior[-1]):
            centre=np.asarray(s['xyz']);n=np.asarray(s['normal_xz'])
            local=[v['xyz'][1] for v in visit if np.linalg.norm(np.asarray(v['xyz'])[[0,2]]-centre[[0,2]])<=1.5]
            top=math.ceil(max(local,default=centre[1])+height-1e-8)
            a=np.array([centre[0]-n[0]*(half+1),top,centre[2]-n[1]*(half+1)])
            b=np.array([centre[0]+n[0]*(half+1),top,centre[2]+n[1]*(half+1)])
            for point in np.linspace(a,b,max(3,math.ceil(np.linalg.norm(b-a)*8))):frames[tuple(map(math.floor,point))]='spruce_planks'
            for sign in (-1,1):
                x,z=np.floor(centre[[0,2]]+sign*n*(half+1)).astype(int)
                for y in range(math.floor(centre[1])-1,top+1):frames[int(x),y,int(z)]='oak_planks'
            portals.append({'xyz':centre.tolist(),'floor_odn_m':centre[1]-l.offset,'lintel_underside_odn_m':top-l.offset})
        records.append({'visit':number,'station_range_m':[interior[0]['station_m'],interior[-1]['station_m']],
            'running_top_odn_range_m':[min(s['xyz'][1]-l.offset for s in interior),max(s['xyz'][1]-l.offset for s in interior)],'portals':portals})
    for key,m in frames.items():
        if not intersects(key,m):result.setdefault(key,m)
    # Interior whole cells are reserved explicitly; partial top cells are tested
    # geometrically so a slab can provide the correct half-block ceiling.
    air=set()
    for s in samples:
        x,y,z=s['xyz']
        for xx in range(math.floor(x-half-1),math.ceil(x+half+1)):
            for zz in range(math.floor(z-half-1),math.ceil(z+half+1)):
                for yy in range(math.ceil(y),math.ceil(y+height)):
                    key=(xx,yy,zz)
                    if intersects(key):air.add(key)
    for key in air:scene.clearance(*key)
    # The production scene can withhold additional cells for retained geometry.
    # Join the surviving frame, rather than accepting floating lintel fragments.
    framing={}
    if hasattr(scene,'old_solid'):
        result,framing=anchor_opening_frames(scene,result,intersects)
    l.wicker_figure_proposal=set(result)|set(proposed)|air
    scene.records.append({'id':'wicker-figure-passages','role':'three_separate_swept_track_openings',
        'opening_full_width_m':half*2,'opening_clear_height_m':height,'withheld_model_cells':len(removed),
        'portal_frame_proposals':len(frames),'visits':records,'banking_measured':False,**framing,
        'opening_shape_is_source_assisted':True,'source_sample_frame_matches_exported_track':True})
    return result
