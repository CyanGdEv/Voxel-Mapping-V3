"""Denser source-line footings and bounded track-clearance transfer members."""
import heapq
import math

from shapely.geometry import Point
from .fence_support_world import staircase_line


def infill_sources(assigned,groups,lines):
    """Sample only original brown frame edges, retaining a source point witness.

    Intermediate footing positions are inferred display density, not measured
    footing symbols. Never fill an edge whose two ends name different visits.
    """
    by_id={r['source_foot_index']:r for r in assigned};occupied=set();result=[];held=[]
    for row in assigned:
        p=row['source_post']['xy'];occupied.add((math.floor(p[0]),math.floor(p[1]),round(row['target']['station_m']/4)))
    for group in groups:
        for edge in group['source_cross_lines']:
            i,j=edge['post_indices'];a=by_id.get(i);b=by_id.get(j);index=edge['source_segment_index']
            if not a or not b or abs(a['target']['station_m']-b['target']['station_m'])>4:
                held.append({'source_segment_index':index,'reason':'unresolved_or_different_branch_endpoints'});continue
            line=lines.geoms[index]
            # Use the exact crossing witness when on this edge; outer edges
            # inherit the branch already connected through their main-row foot.
            target=min([a['target'],b['target']],key=lambda t:line.distance(Point(t['xy'])))
            for step in range(math.ceil(line.length/.1)+1):
                fraction=min(1.,step*.1/line.length);q=line.interpolate(fraction,normalized=True);x,y=math.floor(q.x),math.floor(q.y)
                token=(x,y,round(target['station_m']/4))
                if token in occupied:continue
                occupied.add(token)
                result.append({'source_post':{'xy':[q.x,q.y],'source_polygon_index':None,'symbol_family':'inferred_on_source_frame_line'},
                    'source_foot_index':f'line-{index}-{x}-{y}',
                    'target':dict(target),'native_graph_distance_m':None,'alternative_branch_margin_m':min([v for v in [a['alternative_branch_margin_m'],b['alternative_branch_margin_m']] if v is not None],default=None),
                    'infill_witness':{'source_segment_index':index,'fraction':fraction,'endpoint_source_foot_indices':[i,j],'is_measured_footing_symbol':False}})
    return result,{'inferred_line_footings':len(result),'unfilled_source_edges':held,'maximum_grid_spacing_m':1.,'sampling_step_m':.1,'infill_outside_native_brown_lines':False}


def route_member(start,end,clear,max_nodes=5000):
    """Find a monotone-height route in the original foot-to-centre plane.

    No new ground foot, excavation, shifted endpoint, or lower-deck cut. The
    portal shape is an estimate; absence of LiDAR returns is never free-space.
    """
    if end[1]<start[1] or end[1]-start[1]>32:return None
    if not clear(start) or not clear(end):return None
    plane=[(x,y) for x,_,y in staircase_line((start[0],0,start[2]),(end[0],0,end[2]))]
    goal=(len(plane)-1,end[1]);first=(0,start[1]);cost={first:0.};parent={};pending=[(0.,0.,first)];tested={};visited=0
    def valid(state):
        i,h=state;k=(plane[i][0],h,plane[i][1])
        if k not in tested:tested[k]=clear(k)
        return tested[k]
    while pending:
        _,g,state=heapq.heappop(pending)
        if g>cost[state]+1e-9:continue
        visited+=1
        if visited>max_nodes:return None
        if state==goal:
            path=[state]
            while path[-1]!=first:path.append(parent[path[-1]])
            path.reverse();return [(plane[i][0],h,plane[i][1]) for i,h in path]
        i,h=state
        for nxt in [(i-1,h),(i+1,h),(i,h+1)]:
            j,z=nxt
            if not 0<=j<len(plane) or not start[1]<=z<=end[1] or not valid(nxt):continue
            ideal=start[1]+(end[1]-start[1])*j/max(1,len(plane)-1)
            value=g+1.+.025*abs(z-ideal)
            if value>=cost.get(nxt,math.inf):continue
            cost[nxt]=value;parent[nxt]=state
            heuristic=abs(goal[0]-j)+end[1]-z
            heapq.heappush(pending,(value+heuristic,value,nxt))
    return None
