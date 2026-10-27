"""Conditional floor-led preshow revision, retaining exact source outlines."""
from collections import deque
import copy
import json
import math
from pathlib import Path
import numpy as np
from shapely.geometry import Polygon,LineString,Point,shape,mapping
from shapely.ops import unary_union
from .generation_cycles import file_hash
from .planning_station_preshow_world import grid_cells
from .station_access import paving_approach


def layout_revision(parts,access,review_path):
    from . import basement_alignment
    review_path=Path(review_path)
    if review_path.stat().st_size>100000:raise ValueError('Bounded aligned source review required')
    if file_hash(review_path)!='06251b04075645c552bcc87f7a8df501ca0bbec80afd955b2b2c1df0e3300035':raise ValueError('Pinned original alignment receipt required')
    r=json.loads(review_path.read_text())
    if r['implementation_sha256']!=file_hash(basement_alignment.__file__) or r['profile_sha256']!=file_hash(basement_alignment.PROFILE):raise ValueError('Current basement alignment source replay required')
    if r['fit']['heldout_residual_m']>.1 or r['fit']['scale']!=1 or r['accepted_training_labels']!=0:raise ValueError('Conditional rigid drawing alignment required')
    profile=json.loads(basement_alignment.PROFILE.read_text())
    if r['retained_world_input_sha256']!=profile['world_pins']:raise ValueError('Pinned retained alignment world required')
    a,b,c,d,e,f=access['drawing_correspondence']['affine'];matrix=np.array([[a,b],[c,d]]);translation=np.array([e,f])
    furniture=np.asarray(r['floor_reduction_normalization']['roof_to_floor_matrix_row_convention'])
    native=lambda pts:(np.column_stack([np.asarray(pts)[:,0],2384-np.asarray(pts)[:,1]])-furniture[2])@np.linalg.inv(furniture[:2])*(100*.0254/72)
    place=lambda pts:np.asarray(pts)@matrix.T+translation
    limits={'preshow_low':[923.99853515625,1242.6202392578125,1100.3978271484375,1459.2197265625],
            'preshow_tower':[927.4779052734375,1073.300048828125,1096.91845703125,1242.6202392578125]}
    legacy_tower=next(p for p in parts if p['id']=='preshow_tower')['source_plan_centre_m'][1]
    source_walls={}
    for part in parts:
        name=part['id']
        if name=='station':continue
        x,y,X,Y=limits[name];corners=native([[x,Y],[x,y],[X,y],[X,Y]]);centre=corners.mean(0);local=corners-centre;model=part['model']
        part['source_plan_centre_m']=centre.tolist();model['outer_wall_base_outline']=[[*p,0] for p in local]
        lo=local.min(0);hi=local.max(0)
        def door(label,ends):return {'id':label,'endpoints':[[*p,0] for p in ends],'width_metres':float(np.linalg.norm(ends[1]-ends[0])),'height_metres':2.3,'status':'source-side aperture; voxel headroom provisional'}
        # Passage follows the shared floor-plan joint, not a gap between roofs.
        if name=='preshow_low':
            entrance=native([[1045.6787109375,1459.2197265625],[1091.2777099609375,1459.2197265625]])-centre
            model['opening_base_segments']=[door('z-/source-floor-entrance',entrance),door('z+/preshow-passage',np.array([[-1.5,hi[1]],[1.5,hi[1]]]))]
        else:
            shift=legacy_tower-centre[1]
            model['opening_base_segments']=[door('z-/preshow-passage',np.array([[-1.5,lo[1]],[1.5,lo[1]]])),door('x-/station-interface',np.array([[lo[0],shift-.9],[lo[0],shift+.9]]))]
        source_walls[name]=mapping(Polygon(place(corners)))
        part['source_outline']={'source_sha256':profile['sources']['floor'],'role':'normalized upper-floor exterior extents','raw_pdf_bounds':limits[name],
            'original_roof_plan_envelope':copy.deepcopy(part['source_outline']),'roof_recentring_is_display_hypothesis':True}
    features={x['id']:shape(x['geometry']) for x in r['features_nominal_local']}
    # The reviewed outer edge is closed against the source building exterior.
    # These three closing sections are architectural extent references, not
    # newly invented queue centre lines or internal lanes.
    pts=list(features['queue-outer-edge'].coords)
    pts.extend(place(native([[1100.3978271484375,1242.6202392578125],[1100.3978271484375,1459.2197265625],[924.5982666015625,1459.2197265625]])).tolist())
    queue=Polygon(pts)
    if not queue.is_valid or not 10<queue.area<150:raise ValueError('Valid source-sided queue envelope required')
    queue=unary_union([queue,features['queue-closed-walkway']]).buffer(1e-7).buffer(-1e-7)
    return {'station_interface_source_y':legacy_tower,'outer':features['basement-outer-envelope'],
        'inner':features['basement-inner-envelope'],'queue':queue,'source_walls':source_walls,
        'gaps':[features['undercroft-side-gap'],features['undercroft-end-gap']],
        'review':r,'review_sha256':file_hash(review_path),'floor_raw_extents':limits}


def lower_openings(revision,boundary,bottom,structures):
    air=set();receipts=[]
    for i,line in enumerate(revision['gaps']):
        vector=np.asarray(line.coords[-1])-np.asarray(line.coords[0]);unit=vector/line.length
        cells={k for k in boundary if line.distance(Point(k[0]+.5,k[1]+.5))<1 and 0<=np.dot(np.asarray(k)+.5-np.asarray(line.coords[0]),unit)<=line.length}
        if not cells:raise ValueError('Aligned basement gap has no raster opening')
        for x,y in cells:
            for h in [bottom,bottom+1]:structures.pop((x,h,y),None);air.add((x,h,y))
        receipts.append({'id':i,'columns_xy':[list(k) for k in sorted(cells)],'source_gap_geometry':mapping(line),'headroom_blocks':2,'vertical_opening_height_verified':False,'external_lower_access_verified':False})
    return air,receipts


def queue_deck(revision,terrain,structures,upper,protected,top):
    """Preserve source polygon; report every voxel alias with existing shop."""
    polygon=revision['queue'];requested=grid_cells(polygon);added={};alias=[];accepted=set()
    def clear(k):
        if k not in terrain or k in protected or terrain[k]['y']>=top:return False
        if any((k[0],h,k[1]) in structures for h in [top,top+1]):return False
        return k in upper or all((k[0],h,k[1]) not in structures for h in range(terrain[k]['y']+1,top))
    def install(k):
        if k not in upper:
            for h in range(terrain[k]['y']+1,top):added[k[0],h,k[1]]='stone_bricks'
        accepted.add(k)
    for k in sorted(requested):
        if clear(k):install(k)
        else:alias.append({'source_cell_xy':list(k),'reason':'preserved building/facade/ground voxel alias; exact source polygon retained'})
    all_floor=upper|accepted
    seed=next(iter(upper));seen={seed};pending=[seed]
    def flood():
        while pending:
            x,y=pending.pop()
            for q in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)]:
                if q in all_floor and q not in seen and clear(q):seen.add(q);pending.append(q)
    # Start in a clear part of the source deck, not a wall column.
    seed=next(k for k in sorted(upper) if clear(k));seen={seed};pending=[seed];flood()
    candidates=grid_cells(polygon.buffer(.75))|upper
    connectors=set()
    for target in sorted(accepted-seen):
        if target in seen:continue
        parents={target:None};queue=deque([target]);end=None
        while queue and len(parents)<2048:
            k=queue.popleft()
            if k in seen:end=k;break
            for q in [(k[0]-1,k[1]),(k[0]+1,k[1]),(k[0],k[1]-1),(k[0],k[1]+1)]:
                if q in candidates and q not in parents and clear(q):parents[q]=k;queue.append(q)
        if end is None:raise ValueError('Source queue raster cannot connect around retained shop aliases')
        while end is not None:
            if end not in all_floor:install(end);all_floor.add(end);connectors.add(end)
            end=parents[end]
        pending=list(seen);flood()
    return added,accepted,{'source_polygon_nominal_local':mapping(polygon),'source_area_m2':polygon.area,'requested_centre_cells':len(requested),'paving_columns':len(accepted),
        'preserved_geometry_aliases':alias,'bounded_cardinal_connector_columns':[list(k) for k in sorted(connectors)],
        'maximum_connector_distance_from_source_m':max((polygon.distance(Point(k[0]+.5,k[1]+.5)) for k in connectors),default=0),
        'source_closing_edges_role':'three closing sections use adjacent building exterior extents; queue outer edge and separate closed walkway retained',
        'queue_level_verified':False,'display_walking_top_m':top,'internal_queue_lanes_reconstructed':False}


def ground_connection(queue_columns,upper,terrain,structures,protected,top,paving,cancelled):
    candidates=[k for k in sorted(queue_columns) if any(q not in upper for q in [(k[0]-1,k[1]),(k[0]+1,k[1]),(k[0],k[1]-1),(k[0],k[1]+1)]) and k not in protected]
    for k in candidates:
        if cancelled():
            from concurrent.futures import CancelledError
            raise CancelledError('Queue access cancelled')
        added,report=paving_approach({'id':'estimated-queue-to-ground','columns_xy':[k]},top,terrain,structures,protected,upper,paving,cancelled=cancelled)
        if report.get('ground_to_upper_floor_connected'):return added,report
    raise ValueError('No half-step source-queue deck connection to retained paving')


def side_fences(columns,upper,terrain,structures,protected,top,route):
    """Oak rails on outside columns, preserving both ends and every walkway."""
    route={tuple(r['source_cell_xy']) for r in route.get('surfaces',[])}
    neighbors={q for x,y in columns for q in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)] if q not in upper|protected|route}
    added={};skipped=0
    for x,y in sorted(neighbors):
        if (x,y) not in terrain or terrain[x,y]['y']>=top:continue
        if any(abs(x-a)+abs(y-b)<=1 for a,b in route):continue
        proposal={(x,h,y):'stone_bricks' for h in range(terrain[x,y]['y']+1,top)};proposal[x,top,y]='oak_fence'
        if any(k in structures for k in proposal):skipped+=1;continue
        added.update(proposal)
    return added,{'oak_fence_columns':sum(m=='oak_fence' for m in added.values()),'preserved_geometry_rail_gaps':skipped,'rail_policy':'narrow source queue uses oak fences; exact rail specification unverified'}


def circulation_check(upper,queue_columns,structures,top,start_columns,flight):
    clear={k for k in upper if all((k[0],h,k[1]) not in structures for h in [top,top+1])}
    starts=clear&start_columns
    if not starts:raise ValueError('Preshow circulation lacks a clear interior start')
    seen={min(starts)};pending=list(seen)
    while pending:
        x,y=pending.pop()
        for q in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)]:
            if q in clear and q not in seen:seen.add(q);pending.append(q)
    if not queue_columns<=seen:raise ValueError('Some generated queue cells are disconnected from the preshow')
    gate=tuple(flight['ordered_route_xy'][0])
    if gate not in seen:raise ValueError('Queue ground approach is disconnected from the preshow')
    return {'all_queue_cells_connected_to_preshow':True,'queue_columns_checked':len(queue_columns),'queue_ground_gate_connected':True,
        'connected_upper_floor_columns':len(seen),'isolated_non_queue_clear_upper_columns':[list(k) for k in sorted(clear-seen)],'two_block_headroom_checked':True,'minecraft_gameplay_tested':False}
