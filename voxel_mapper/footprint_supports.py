"""Individual brown-footprint to centreline connections, with crossing evidence."""
import heapq
import json
import math
from pathlib import Path

import laspy
import numpy as np
from shapely.affinity import affine_transform
from shapely.geometry import LineString,shape

from .generation_cycles import file_hash
from .point_cloud import is_bng
from .fence_support_world import staircase_line,deck_intervals

ARCHIVE_SHA='0da1c50d0df63f6dd7b49dca29286180eabf20261530fb8afe05645cf0235b1e'
REFERENCE_CROP_SHA='78524af74e857a866fa6cc68bf8970600fbfc5ad0917dd4d0def1530760b0584'


def source_targets(route,groups,isolated,lines,margin=.75):
    """Follow native cross-line edges, never average two crossing branches."""
    posts=sorted([p for g in groups for p in g['posts']]+isolated,key=lambda p:p['source_polygon_index'])
    graph=[{} for _ in posts];seeds=[];coords=np.asarray(route.coords);lengths=np.linalg.norm(np.diff(coords,axis=0),axis=1);starts=np.r_[0,np.cumsum(lengths)]
    for g in groups:
        for edge in g['source_cross_lines']:
            i,j=edge['post_indices'];a=np.asarray(posts[i]['xy']);b=np.asarray(posts[j]['xy']);distance=float(np.linalg.norm(b-a))
            graph[i][j]=graph[j][i]=distance
            chord=lines.geoms[edge['source_segment_index']];v=np.asarray(chord.coords[-1])-np.asarray(chord.coords[0]);v=v/np.linalg.norm(v)
            for k,(u,w) in enumerate(zip(coords,coords[1:])):
                if not lengths[k] or abs(np.dot(v,(w-u)/lengths[k]))>.65:continue
                segment=LineString([u,w]);q=chord.intersection(segment)
                if q.is_empty or q.geom_type!='Point':continue
                station=float(starts[k]+segment.project(q));xy=list(q.coords[0])
                if any(abs(station-s['station_m'])<.2 and edge['source_segment_index']==s['source_segment_index'] for s in seeds):continue
                seeds.append({'station_m':station,'xy':xy,'source_segment_index':edge['source_segment_index'],'seed_feet':[i,j]})
    distances=[[] for _ in posts]
    for seed in seeds:
        todo=[(math.dist(posts[i]['xy'],seed['xy']),i) for i in seed['seed_feet']];heapq.heapify(todo);seen={}
        while todo:
            cost,i=heapq.heappop(todo)
            if i in seen or cost>12:continue
            seen[i]=cost;distances[i].append((cost,seed))
            for j,d in graph[i].items():
                if j not in seen:heapq.heappush(todo,(cost+d,j))
    assigned=[];held=[]
    for index,(post,choices) in enumerate(zip(posts,distances)):
        base={'source_post':post,'source_foot_index':index}
        if not choices:held.append({**base,'reason':'no_native_cross_line_to_centre'});continue
        choices.sort(key=lambda r:(r[0],r[1]['station_m']));cost,target=choices[0]
        alternative=next(((d,s) for d,s in choices[1:] if abs(s['station_m']-target['station_m'])>8),None)
        if alternative and alternative[0]-cost<margin:
            held.append({**base,'reason':'ambiguous_source_crossing_branch','candidates':[target,alternative[1]],'graph_distance_margin_m':alternative[0]-cost});continue
        assigned.append({**base,'target':target,'native_graph_distance_m':cost,'alternative_branch_margin_m':None if alternative is None else alternative[0]-cost})
    return assigned,held,{'source_footprints':len(posts),'native_cross_line_intersections':len(seeds),'assigned_footprints':len(assigned),'unresolved_footprints':len(held),'group_station_averaging_used':False}


def load_cloud(path,receipt,affine):
    receipt=json.loads(Path(receipt).read_text())
    if receipt.get('archive_sha256')!=ARCHIVE_SHA or receipt.get('survey_id')!='P_10682' or receipt.get('survey_date')!='2022-01-05':raise ValueError('Pinned January 2022 survey required')
    if receipt.get('reference_crop_sha256')!=REFERENCE_CROP_SHA or file_hash(Path(path).with_name('reference-crop.las'))!=REFERENCE_CROP_SHA:raise ValueError('Prior dated raw crop must reproduce exactly')
    if file_hash(path)!=receipt['sha256']:raise ValueError('LiDAR crop bytes do not match receipt')
    cloud=laspy.read(path)
    if not is_bng(cloud.header.parse_crs()) or len(cloud)!=receipt['retained_points'] or len(cloud)>1_000_000:raise ValueError('Bounded native BNG crop required')
    eligible=(~np.asarray(cloud.withheld,dtype=bool))&(~np.asarray(cloud.synthetic,dtype=bool))&(np.asarray(cloud.classification)!=7)
    xyz=np.column_stack([cloud.x,cloud.y,cloud.z]);classes=np.asarray(cloud.classification)
    A,B,C,D,E,N=affine;matrix=np.array([[A,B],[C,D]]);local=(xyz[:,:2]-[E,N])@np.linalg.inv(matrix).T
    bounds=receipt['bounds'];actual=[float(min(cloud.x)),float(min(cloud.y)),float(max(cloud.x)),float(max(cloud.y))]
    if any(actual[i]<bounds[i]-1e-6 for i in [0,1]) or any(actual[i]>bounds[i]+1e-6 for i in [2,3]):raise ValueError('LiDAR crop exceeds declared bounds')
    return local[eligible],xyz[eligible,2],classes[eligible],receipt


def cloud_probe(xy,top,cloud,radius=2.):
    local,heights,classes,_=cloud;mask=np.sum((local-np.asarray(xy))**2,axis=1)<=radius**2;z=heights[mask];c=classes[mask]
    return {'radius_m':radius,'returns':len(z),'height_range_odn_m':None if not len(z) else [float(min(z)),float(max(z))],
        'returns_near_display_deck':int(np.count_nonzero(abs(z-top)<=1.5)),
        'nonvegetation_returns_near_display_deck':int(np.count_nonzero((abs(z-top)<=1.5)&np.isin(c,[1,6]))),
        'classes':{str(int(k)):int(n) for k,n in zip(*np.unique(c,return_counts=True))},'semantic_track_identity_verified':False}


def obstruction(path,terrain,old,protected,foot,target):
    """A whole member is withheld if it would cut a lower deck or its clearance."""
    bearing=target if isinstance(target,set) else {target}
    for x,h,y in path:
        if (x,y) not in terrain:return 'outside_terrain'
        if h<=terrain[x,y]['y']:return 'terrain_intersection'
        if (x,h,y) in old:return 'retained_geometry_or_lower_track'
        if (x,h,y) in protected or (x,h+1,y) in protected:return 'lower_track_or_walking_clearance'
        # Fences have a 1.5-block collision height. The intended bearing may
        # touch its own deck; neighbouring roofs/track remain protected.
        if (x,h+1,y) in old and (x,h+1,y) not in bearing:return 'fence_top_hits_retained_geometry'
    return None


def build(route,groups,terrain,old,head,samples,keys,track,profile):
    data=json.loads(Path(profile['markings_path']).read_text());u=profile['metres_per_pdf_point']
    lines=affine_transform(shape(next(r['geometry_pdf_native'] for r in data['records'] if r['role']=='support_boundaries')),[u,0,0,u,0,0])
    assigned,held,source=source_targets(route,groups,profile['isolated_symbols'],lines)
    density=None
    if profile.get('dense_footprint'):
        from .dense_footprint_supports import infill_sources,route_member
        extra,density=infill_sources(assigned,groups,lines)
        assigned=assigned+extra
    cloud=load_cloud(profile['cloud_path'],profile['cloud_receipt'],profile['nominal_to_bng'])
    intervals=deck_intervals(track);protected=set(head)
    for (x,y),parts in intervals.items():
        for lo,hi in parts:protected.update((x,h,y) for h in range(math.ceil(hi),math.ceil(hi)+3))
    paved={xy for xy,r in terrain.items() if r['material'] not in ['grass_block','brown_wool','blue_wool','orange_wool','purple_wool','yellow_wool']}
    walk={(x,h,y) for x,y in paved for h in range(terrain[x,y]['y']+1,terrain[x,y]['y']+4)}
    support={};built=[];crossings=[]
    stacked=[xy for xy,parts in intervals.items() if len(parts)>1]
    sample_stations=np.asarray([r['station_m'] for r in samples])
    for row in assigned:
        x,y=map(math.floor,row['source_post']['xy']);target=row['target'];station=target['station_m'];index=int(np.argmin(abs(sample_stations-station)));deck=tuple(keys[index]);dx,dh,dy=deck
        # Select the final, solid-step underside of this exact branch's centre
        # key. No minimum over unrelated deck intervals at the same XY.
        top=dh+(.5 if track[deck].endswith('_slab') else 1)
        own=[(lo,hi) for lo,hi in intervals[dx,dy] if lo<=dh<hi or abs(hi-top)<1e-6];under=min(lo for lo,hi in own);end=(dx,math.floor(under)-1,dy)
        receipt={**row,'start_cell_xyz':None,'end_cell_xyz':list(end),'target_centre_deck_key':list(deck),'target_sample_station_m':samples[index]['station_m'],'deck_underside_m':under,'deck_top_m':top}
        if (x,y) not in terrain:held.append({**receipt,'reason':'outside_terrain'});continue
        start=(x,terrain[x,y]['y']+1,y);receipt['start_cell_xyz']=list(start)
        if end[1]<start[1]:held.append({**receipt,'reason':'ground_borne_or_low_clearance'});continue
        if math.dist([dx,dy],target['xy'])>1.5:raise ValueError('Selected raster endpoint is not on this source branch')
        path=staircase_line(start,end);local_walk=walk
        if (x,y) in paved:
            boundary=any((x+a,y+b) in terrain and (x+a,y+b) not in paved for a,b in [(1,0),(-1,0),(0,1),(0,-1)])
            if boundary:local_walk=walk-{(x,h,y) for h in range(start[1],start[1]+4)}
        # A fence's upper collision half may meet this branch's own underside
        # across its full width, including the lower half of a thickened step.
        # This exception never allows occupying an existing deck cell.
        bearing=set()
        for near in range(max(0,index-8),min(len(samples),index+9)):
            for xx,yy in samples[near]['cells_xy']:
                for lo,hi in intervals.get((xx,yy),[]):
                    if abs(hi-samples[near]['running_top_m'])<=.75:bearing.add((xx,math.floor(lo),yy))
        reason=obstruction(path,terrain,old,protected|local_walk,start,bearing)
        direct_reason=reason
        if reason and density is not None:
            checks=protected|local_walk
            recovered=route_member(start,end,lambda k:obstruction([k],terrain,old,checks,start,bearing) is None)
            if recovered is not None:
                path=recovered;reason=None
                receipt['transfer_route']={'direct_obstruction':direct_reason,'shape_is_estimated':True,'new_ground_feet':0,'vertical_height_never_decreases':True}
        lower=[{'underside_m':lo,'top_m':hi} for lo,hi in intervals[dx,dy] if hi<under]
        nearby=[list(xy) for xy in stacked if any((xx-xy[0])**2+(yy-xy[1])**2<=4 for xx,_,yy in path)]
        if lower or nearby:
            receipt['lower_deck_intervals_at_target']=lower;receipt['nearby_stacked_columns']=nearby
            receipt['lidar']=cloud_probe(target['xy'],top,cloud);crossings.append({**receipt,'decision':reason or 'built'})
        if reason:held.append({**receipt,'reason':reason});continue
        support.update({k:'dark_oak_fence' for k in path});receipt['member_cells']=[list(k) for k in path];built.append(receipt)
    if len(built)<8:raise ValueError('Insufficient unambiguous footprint-to-centre members')
    if len(support)>profile['max_added_blocks']:raise ValueError('Support budget exceeded')
    # Audit *all* stacked raster columns, not just targets that survived.
    overlap=[]
    for xy,parts in intervals.items():
        if len(parts)>1:overlap.append({'source_cell_xy':list(xy),'deck_intervals_m':parts,'lidar':cloud_probe([xy[0]+.5,xy[1]+.5],max(hi for lo,hi in parts),cloud)})
    receipt=cloud[3]
    return support,{'constructed_supports':built,'withheld_supports':held,'source_assignment':source,'added_support_cells':len(support),
        **({'density':density,'transfer_routes_constructed':sum('transfer_route' in r for r in built)} if density is not None else {}),
        'style':'dark oak fences only; dense original brown frame-line starts to branch-specific centres, with clearance-aware transfer paths' if density is not None else 'dark oak fences only; original brown footprint to corresponding centreline underside; no crossbeams or decorative lattice',
        'crossing_member_checks':crossings,'overlap_lidar_checks':overlap,
        'lidar':{'crop_sha256':receipt['sha256'],'crop_receipt_sha256':file_hash(profile['cloud_receipt']),'archive_sha256':ARCHIVE_SHA,'survey_id':'P_10682','survey_date':'2022-01-05','retained_points':receipt['retained_points'],'bounds_bng':receipt['bounds'],'role':'dated height-band and crossing context; does not identify hidden timber or change track levels','independent_registration_verified':False},
        'engineering_dimensions_verified':False,'all_members_start_on_source_footprint':True,'all_members_end_on_assigned_centreline':True,'support_materials':['dark_oak_fence']}
