"""Recover outer footing rows and keep timber/diagonal member planes separate."""
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from shapely.geometry import shape
from shapely.affinity import affine_transform
from shapely.ops import polygonize
from .generation_cycles import file_hash
from .timber_track_world import frame
from .fence_support_world import staircase_line,deck_intervals,conflict,add_caps,FENCES,validate_connected


def footing_groups(route,lines,posts):
    pts=np.asarray([p['xy'] for p in posts]);adj=[set() for _ in posts];edges=[]
    for index,seg in enumerate(lines.geoms):
        a,b=map(np.asarray,seg.coords);length=np.linalg.norm(b-a)
        if not .6<=length<=10:continue
        da=np.linalg.norm(pts-a,axis=1);db=np.linalg.norm(pts-b,axis=1);i=int(np.argmin(da));j=int(np.argmin(db))
        if i==j or da[i]>.4 or db[j]>.4:continue
        primary=i if posts[i]['symbol_family']=='main_row' else j if posts[j]['symbol_family']=='main_row' else None
        if primary is None:continue
        _,tan,_=frame(route,posts[primary]['station_m']);v=pts[j]-pts[i]
        if abs(np.dot(v/np.linalg.norm(v),tan))>.6:continue
        adj[i].add(j);adj[j].add(i);edges.append({'source_segment_index':index,'post_indices':[i,j]})
    seen=set();groups=[];isolated=[]
    for i in range(len(posts)):
        if i in seen:continue
        seen.add(i);pending=[i];members=[]
        while pending:
            q=pending.pop();members.append(q)
            for j in adj[q]-seen:seen.add(j);pending.append(j)
        if len(members)==1:isolated.append(posts[i]);continue
        rows=[posts[j] for j in members];primary=[r for r in rows if r['symbol_family']=='main_row']
        station=float(np.median([r['station_m'] for r in primary]));groups.append({'station_m':station,'posts':rows,'source_cross_lines':[e for e in edges if e['post_indices'][0] in members and e['post_indices'][1] in members]})
    return sorted(groups,key=lambda g:g['station_m']),isolated


def source_frames(markings,pdf,profile,cancelled):
    if file_hash(markings)!=profile['markings_sha256'] or file_hash(pdf)!=profile['source_pdf_sha256']:raise ValueError('Pinned original source required')
    data=json.loads(Path(markings).read_text());u=profile['metres_per_pdf_point'];affine=[u,0,0,u,0,0]
    route=affine_transform(shape(next(r['geometry_pdf_native'] for r in data['records'] if r['role']=='track_centre')),affine)
    lines=affine_transform(shape(next(r['geometry_pdf_native'] for r in data['records'] if r['role']=='support_boundaries')),affine);posts=[]
    for index,g in enumerate(polygonize(lines)):
        if cancelled():raise RuntimeError('Footing audit cancelled')
        circle=4*math.pi*g.area/(g.length*g.length)
        family='main_row' if .27<=g.area<=.31 and circle>=.8 else 'outer_brace' if .09<=g.area<=.14 and circle>=.6 else None
        if not family:continue
        q=g.centroid;station=route.project(q);mid,_,n=frame(route,station);offset=float(np.dot(np.asarray(q.coords[0])-mid,n))
        if not .65<=abs(offset)<=9:continue
        posts.append({'source_polygon_index':index,'xy':list(q.coords[0]),'station_m':station,'offset_m':offset,'symbol_family':family,'symbol_area_m2':g.area,'geometry_sha256':hashlib.sha256(g.normalize().wkb).hexdigest()})
    groups,isolated=footing_groups(route,lines,posts)
    return route,groups,{'source_centre_length_m':route.length,'main_row_symbols':sum(p['symbol_family']=='main_row' for p in posts),'outer_brace_symbols':sum(p['symbol_family']=='outer_brace' for p in posts),'source_footing_marks':len(posts),'source_cross_line_groups':len(groups),'unresolved_isolated_symbols':isolated,'symbol_size_is_physical_footing_size':False}


def offset_axis(vector):
    return (1 if vector[0]>=0 else -1,0) if abs(vector[0])>=abs(vector[1]) else (0,1 if vector[1]>=0 else -1)


def separated_brace(a,b,offset):
    """A diagonal occupies a parallel plane, with gate endpoints as separators."""
    dx,dy=offset;a=(a[0]+dx,a[1],a[2]+dy);b=(b[0]+dx,b[1],b[2]+dy)
    blocks={k:'nether_brick_fence' for k in staircase_line(a,b)}
    facing='north' if dx else 'east'
    blocks[a]=blocks[b]='spruce_fence_gate_'+facing
    return blocks


def build(route,groups,terrain,old,head,samples,keys,track,profile):
    intervals=deck_intervals(track);support={};accepted=[];held=[];walk=set();brace_holds=[];straight={};diagonal_batches=[];caps={}
    paved={xy for xy,r in terrain.items() if r['material'] not in ['grass_block','brown_wool','blue_wool','orange_wool','purple_wool','yellow_wool']}
    for x,y in paved:walk.update((x,h,y) for h in range(terrain[x,y]['y']+1,terrain[x,y]['y']+4))
    for group in groups:
        # Native cross-lines can join auxiliary feet to a main row on a nearby
        # branch. Use the main-row station and retain all original foot XYs.
        _,tangent,normal=frame(route,group['station_m']);axis=offset_axis(tangent)
        raw=list(dict.fromkeys(tuple(map(math.floor,p['xy'])) for p in group['posts']))
        if len(raw)<2:held.append({'source_group':group,'reason':'voxel_alias'});continue
        order=sorted(raw,key=lambda xy:np.dot(xy,normal));a,b=order[0],order[-1]
        span=staircase_line((a[0],0,a[1]),(b[0],0,b[1]));i=min(range(len(samples)),key=lambda i:abs(samples[i]['station_m']-group['station_m']))
        centre=tuple(keys[i]);top=centre[1]+(.5 if track[centre].endswith('_slab') else 1)
        joins=[(lo,(x,y),hi) for x,_,y in span for lo,hi in intervals.get((x,y),[]) if abs(hi-top)<=1.5]
        if not joins:held.append({'source_group':group,'reason':'source_span_misses_deck'});continue
        underside,join,join_top=min(joins);beam=math.floor(underside)-1;active=[];skipped=[];local_walk=set(walk)
        for xy in order:
            if xy not in terrain:skipped.append({'xy':list(xy),'reason':'outside_terrain'});continue
            base=terrain[xy]['y']+1
            if base>beam:skipped.append({'xy':list(xy),'reason':'ground_borne_or_low_clearance'});continue
            if beam-base>32:skipped.append({'xy':list(xy),'reason':'height_budget'});continue
            # A source footing on a raster paving boundary need not be deleted
            # merely because the metre cell includes paving. Its own post is
            # permitted; neighbouring pedestrian columns remain protected.
            if xy in paved:
                boundary=any((xy[0]+dx,xy[1]+dy) in terrain and (xy[0]+dx,xy[1]+dy) not in paved for dx,dy in [(1,0),(-1,0),(0,1),(0,-1)])
                if not boundary:skipped.append({'xy':list(xy),'reason':'interior_paving'});continue
                local_walk.difference_update((xy[0],h,xy[1]) for h in range(base,base+4))
            post={(xy[0],h,xy[1]):'spruce_fence' for h in range(base,beam+1)}
            reason=conflict(post,terrain,old,head,local_walk)
            if reason:skipped.append({'xy':list(xy),'reason':reason});continue
            active.append((xy,base))
        if len(active)<2:held.append({'source_group':group,'reason':'insufficient_feasible_source_legs','skipped_legs':skipped});continue
        aa=active[0][0];bb=active[-1][0]
        span=staircase_line((aa[0],0,aa[1]),(bb[0],0,bb[1]))
        touching=[(lo,(x,y),hi) for x,_,y in span for lo,hi in intervals.get((x,y),[]) if abs(hi-top)<=1.5 and lo<=beam+1.5]
        if not touching:held.append({'source_group':group,'reason':'incomplete_bearing_join','skipped_legs':skipped});continue
        underside,join,join_top=min(touching)
        proposal={};low=max(base for xy,base in active);levels=sorted(set(list(range(low,beam,3))+[beam]));omitted_levels=[]
        for h in levels:
            line={(x,h,y):'oak_fence' for x,_,y in span}
            reason=conflict(line,terrain,old,head,local_walk)
            if reason:
                if h==beam:break
                omitted_levels.append({'height':h,'reason':reason});continue
            proposal.update(line)
        else:reason=None
        if reason:held.append({'source_group':group,'reason':'bearing_beam_'+reason});continue
        for (x,y),base in active:
            for h in range(base,beam+1):proposal[x,h,y]='spruce_fence'
        used_levels=[h for h in levels if h not in [o['height'] for o in omitted_levels]]
        receipt={'source_pair':group,'post_cells_xy':[list(xy) for xy,base in active],'base_heights':[base for xy,base in active],'beam_height':beam,'crossmember_levels':used_levels,'join_cell_xy':list(join),'deck_underside_m':underside,'deck_top_m':join_top,'skipped_legs':skipped,'omitted_crossmembers':omitted_levels,'offset_brace_planes':[]}
        for k,m in proposal.items():
            if k not in straight or m=='spruce_fence':straight[k]=m
        for (pa,_),(pb,_) in zip(active,active[1:]):
            for low,high in zip(used_levels,used_levels[1:]):
                if high-low<2:continue
                for aa,bb in [((pa[0],low,pa[1]),(pb[0],high,pb[1])),((pa[0],high,pa[1]),(pb[0],low,pb[1]))]:
                    brace=separated_brace(aa,bb,axis);reason=conflict(brace,terrain,old,head,local_walk)
                    if reason or any(k in proposal and proposal[k] in ['oak_fence','spruce_fence'] for k in brace):brace_holds.append({'station_m':group['station_m'],'reason':reason or 'straight_member_plane'});continue
                    diagonal_batches.append(brace);proposal.update(brace);receipt['offset_brace_planes'].append({'offset_xy':list(axis),'from':list(aa),'to':list(bb)})
        add_caps(proposal,receipt,terrain,old,head,local_walk)
        caps.update({k:m for k,m in proposal.items() if 'trapdoor' in m})
        # Split-plane gates touch the original upright plane at brace ends.
        # Missing low crossmembers may leave multiple individually grounded
        # components; every component must still attach to a source foot.
        pending=set(proposal);feet={(x,base,y) for (x,y),base in active}
        while pending:
            todo=[next(iter(pending))];seen={todo[0]};pending.remove(todo[0])
            while todo:
                x,h,y=todo.pop()
                for k in [(x-1,h,y),(x+1,h,y),(x,h-1,y),(x,h+1,y),(x,h,y-1),(x,h,y+1)]:
                    if k in pending:pending.remove(k);seen.add(k);todo.append(k)
            if not seen&feet:raise ValueError('A separated brace component has no grounded source post')
        for k,m in proposal.items():
            if k not in support or ('trapdoor' in support[k] and m in FENCES):support[k]=m
        accepted.append(receipt)
    links=[];held_links=[]
    for a,b in zip(accepted,accepted[1:]):
        sa=a['source_pair']['station_m'];sb=b['source_pair']['station_m']
        if sb-sa>6:continue
        for side in [0,-1]:
            p=a['post_cells_xy'][side];q=b['post_cells_xy'][side];ha,hb=a['beam_height'],b['beam_height']
            if math.dist(p,q)>8 or abs(ha-hb)>4:continue
            _,_,n=frame(route,(sa+sb)/2);offset=offset_axis(n if side==-1 else -n)
            rail={k:'oak_fence' for k in staircase_line((p[0],ha,p[1]),(q[0],hb,q[1]))};reason=conflict(rail,terrain,old,head,walk)
            if reason:held_links.append({'from_station_m':sa,'to_station_m':sb,'reason':reason});continue
            for k,m in rail.items():
                support.setdefault(k,m)
                if k not in straight:straight[k]=m
            lowa=max(a['base_heights'][side],ha-3);lowb=max(b['base_heights'][side],hb-3);braces=0
            if ha-lowa>=2 and hb-lowb>=2:
                for aa,bb in [((p[0],lowa,p[1]),(q[0],hb,q[1])),((p[0],ha,p[1]),(q[0],lowb,q[1]))]:
                    brace=separated_brace(aa,bb,offset);reason=conflict(brace,terrain,old,head,walk)
                    if reason or any(k in support and support[k] in ['oak_fence','spruce_fence'] for k in brace):continue
                    diagonal_batches.append(brace)
                    for k,m in brace.items():support.setdefault(k,m)
                    braces+=1
            links.append({'from_station_m':sa,'to_station_m':sb,'side':side,'separate_diagonals':braces})
    # Resolve all curves globally: a diagonal from an earlier frame must not
    # occupy a later source upright. Reject an entire conflicting brace, not
    # individual voxels that would leave a broken diagonal.
    support,plane_review=compose_planes(straight,diagonal_batches,caps)
    if len(accepted)<8:raise ValueError('Insufficient grounded source frames')
    if len(support)>profile['max_added_blocks']:raise ValueError('Support budget exceeded')
    return support,{'member_plane_validation':plane_review,'constructed_bents':accepted,'withheld_bents':held,'longitudinal_links':links,'withheld_links':held_links,'withheld_diagonal_members':brace_holds,'added_support_cells':len(support),'source_legs_constructed':sum(len(r['post_cells_xy']) for r in accepted),'style':'dense multi-row spruce uprights, oak horizontal members, separate nether-brick diagonal planes and oriented gate joints','engineering_dimensions_verified':False,'diagonals_are_voxel_stair_steps':True}


def compose_planes(straight,diagonals,caps):
    result=dict(straight);held=0;placed=0
    for brace in diagonals:
        if set(brace)&straight.keys():held+=1;continue
        for k,m in brace.items():result.setdefault(k,m)
        placed+=1
    for k,m in caps.items():result.setdefault(k,m)
    if any(result[k]!=m for k,m in straight.items()):raise ValueError('A diagonal overwrote a straight member')
    return result,{'straight_member_cells':len(straight),'diagonal_members_placed':placed,
                   'diagonal_members_held_for_global_separation':held,'straight_diagonal_cell_overlap':0}
