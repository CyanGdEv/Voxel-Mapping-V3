"""Conditional station/preshow extension preserving the corrected shop world."""
import argparse
from collections import deque,Counter
from concurrent.futures import CancelledError
import heapq
import json
import math
from pathlib import Path
import shutil
import tempfile

import numpy as np
from shapely.affinity import affine_transform
from shapely.geometry import Polygon,LineString,Point,box,mapping,shape
from shapely.ops import unary_union

from .generation_cycles import atomic_json,file_hash
from . import planning_wall_shell as shop,planning_geometry_world as geometry_world
from . import wicker_building_models as templates
from .drawing_page_tools import pixel_to_native
from .shop_shell import boundary_columns,leak_audit
from .shop_slabs import occupied_halves

PROFILE=Path(__file__).parent/'data/wicker-station-preshow.json'
UNIT=100*.0254/72


def grid_cells(g,limit=2048):
    a,b,c,d=g.bounds
    if (math.ceil(c)-math.floor(a))*(math.ceil(d)-math.floor(b))>limit:raise ValueError('Footprint sampling budget exceeded')
    return {(x,y) for x in range(math.floor(a),math.ceil(c)) for y in range(math.floor(b),math.ceil(d)) if g.covers(Point(x+.5,y+.5))}


def verify_sources(directory,evidence_directory,profile):
    import hashlib,pymupdf
    directory=Path(directory);evidence_directory=Path(evidence_directory)
    for name,sha in profile['sources'].items():
        path=directory/(sha+'.pdf')
        if path.stat().st_size>24_000_000 or file_hash(path)!=sha:raise ValueError('Pinned original '+name+' PDF required')
    for n,sha in profile['review_input_sha256'].items():
        if file_hash(evidence_directory/n)!=sha:raise ValueError('Pinned architectural review required')
    pdf=directory/(profile['sources']['elevations']+'.pdf');heights={}
    with pymupdf.open(pdf) as doc:
        if len(doc)!=1 or doc[0].rotation!=90:raise ValueError('Single original rotated elevation required')
        p=doc[0];pix=p.get_pixmap(matrix=pymupdf.Matrix(1888/p.rect.width,1888/p.rect.width));frame=profile['elevation_frame']
        if [pix.width,pix.height]!=frame['render_size_pixels'] or hashlib.sha256(pix.samples).hexdigest()!=frame['render_samples_sha256']:raise ValueError('Source elevation render changed')
        matrix=pymupdf.Matrix(pixel_to_native(p,pix.width,pix.height));mpp=math.hypot(matrix.c,matrix.d)*UNIT
        for name,r in profile['height_traces'].items():
            datum=r['datum_y_display_points']*pix.height/p.rect.height
            if not 0<r['ridge_pixel'][1]<r['eave_pixel'][1]<datum<pix.height:raise ValueError('Invalid source height ordering')
            heights[name]={'eave_m':(datum-r['eave_pixel'][1])*mpp,'ridge_m':(datum-r['ridge_pixel'][1])*mpp,
                'reference_label':r['datum_label'],'datum_y_pixel':datum,'view':r['view'],'sampling_two_endpoint_bound_m':4*mpp,
                'physical_reference_role_verified':False}
    with pymupdf.open(directory/(profile['sources']['basement']+'.pdf')) as doc:
        text=' '.join(doc[0].get_text().split())
        if '+178.00' not in text or '+181.250' not in text:raise ValueError('Separate undercroft/inspection source labels required')
    review=json.loads((evidence_directory/'wicker-architectural-outline-review.json').read_text())
    parts=templates.station_parts(review)
    with pymupdf.open(directory/(profile['sources']['roof']+'.pdf')) as doc:
        page=doc[0];paths=page.get_drawings()
        for part in parts:
            if part['id']=='station':continue
            source=part['source_outline'];points=[]
            for index in source['source_boundary_drawing_indices']:
                for item in paths[index]['items']:
                    if item[0]=='l':points.extend([list(item[1]),list(item[2])])
            xy=np.asarray(points);observed=[xy[:,0].min(),xy[:,1].min(),xy[:,0].max(),xy[:,1].max()]
            if not np.allclose(observed,source['raw_pdf_bounds'],atol=.02,rtol=0):raise ValueError('Preshow original roof strokes changed')
    from PIL import Image,ImageDraw
    image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples);draw=ImageDraw.Draw(image)
    for name,r in profile['height_traces'].items():
        ridge=r['ridge_pixel'];eave=r['eave_pixel'];draw.line([tuple(ridge),tuple(eave)],fill='#d0298e',width=3);draw.text(tuple(ridge),name,fill='#9c105d')
    return parts,heights,image


def build_component(model,centre,matrix,translation,top,limits,cancelled=lambda:False):
    """Sample source-local gable/pyramid as half-step slabs in the placed grid."""
    outline=np.asarray(model['outer_wall_base_outline'])[:,:2];centre=np.asarray(centre);world=lambda pts:(np.asarray(pts)+centre)@matrix.T+translation
    wall=Polygon(world(outline));dims=model['dimensions'];w=dims['roof_width_m'];length=dims['roof_length_m'];eave=dims['eave_m'];ridge=dims['ridge_m']
    roof=Polygon(world([[-w/2,-length/2],[-w/2,length/2],[w/2,length/2],[w/2,-length/2]]));a,b,c,d=roof.bounds
    if (math.ceil(c)-math.floor(a))*(math.ceil(d)-math.floor(b))>limits['roof_sampling_cells']:raise ValueError('Roof sampling budget exceeded')
    raw={}
    for x in range(math.floor(a),math.ceil(c)):
        if cancelled():raise CancelledError('Component raster cancelled')
        for y in range(math.floor(b),math.ceil(d)):
            if roof.intersection(box(x,y,x+1,y+1)).area<1e-9:continue
            local=(np.array([x+.5,y+.5])-translation)@matrix-centre
            run=abs(local[0])/(w/2)
            if dims['roof_form']=='pyramid':run=max(run,abs(local[1])/(length/2))
            raw[x,y]=round(2*(eave+(ridge-eave)*(1-min(1,run))))-1
    half=dict(raw);pending=[(h,x,y) for (x,y),h in half.items()];heapq.heapify(pending)
    while pending:
        h,x,y=heapq.heappop(pending)
        if half[x,y]!=h:continue
        for q in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)]:
            if q in half and half[q]>h+1:half[q]=h+1;heapq.heappush(pending,(h+1,*q))
    if max(raw[k]-h for k,h in half.items())>2:raise ValueError('Roof display smoothing exceeds one metre')
    boundary=boundary_columns([[*p,0] for p in list(wall.exterior.coords)[:-1]],1)
    if not boundary<=set(half):raise ValueError('Source wall lacks overhead roof')
    doors={};openings=[]
    for opening in model['opening_base_segments']:
        points=world(np.asarray(opening['endpoints'])[:,:2]);line=LineString(points);vector=(points[1]-points[0])/line.length
        columns={k for k in boundary if 0<=np.dot(np.asarray([k[0]+.5,k[1]+.5])-points[0],vector)<=line.length and line.distance(Point(k[0]+.5,k[1]+.5))<1}
        if not columns:columns={min(boundary,key=lambda k:line.centroid.distance(Point(k[0]+.5,k[1]+.5)))}
        head=math.floor(opening['height_metres'])
        if head<2:raise ValueError('Two-block portal headroom required')
        for k in columns:doors[k]=max(head,doors.get(k,0))
        openings.append({'id':opening['id'],'geometry_nominal_local':mapping(line),'headroom_blocks':head,'columns_xy':[list(k) for k in sorted(columns)],'source_role':'review aperture; exact dimensions unverified'})
    cells={};aliases=0
    for (x,y),h in half.items():cells[x,h//2,y]='oak_slab_top' if h%2 else 'oak_slab'
    for x,y in boundary:
        h=half[x,y]
        for z in range(doors.get((x,y),0),h//2):cells[x,z,y]='spruce_planks'
        if h%2:cells[x,h//2,y]='spruce_planks';aliases+=1
    for (x,y),head in doors.items():
        for z in range(head):cells.pop((x,z,y),None)
    cx,cy=map(math.floor,wall.centroid.coords[0]);occupied=occupied_halves({(x-cx,h,y-cy):m for (x,h,y),m in cells.items()})
    half_boundary={(2*(x-cx)+dx,2*(y-cy)+dy) for x,y in boundary for dx in (0,1) for dy in (0,1)}
    half_doors={(2*(x-cx)+dx,2*(y-cy)+dy):2*h for (x,y),h in doors.items() for dx in (0,1) for dy in (0,1)}
    closure=leak_audit(occupied,half_boundary,half_doors,[[x-cx,y-cy,0] for x,y in list(wall.exterior.coords)[:-1]],2)
    if closure['interior_reached_from_exterior']:raise ValueError('Slab-shaped component leaks with portals sealed')
    placed={(x,h+top,y):m for (x,h,y),m in cells.items()}
    return placed,wall,boundary,openings,{'roof_form':dims['roof_form'],'dimensions':dims,'roof_slab_blocks':sum(m.startswith('oak_slab') for m in cells.values()),'full_roof_blocks':0,'wall_blocks':sum(m=='spruce_planks' for m in cells.values()),'wall_slab_aliases':aliases,'maximum_smoothing_m':max(raw[k]-h for k,h in half.items())/2,'native_slab_shape_air_flood':closure}


def entry_flight(opening,direction,top,terrain,structures,protected,upper):
    """Estimated bounded half-step approach; never overwrite an existing object."""
    line=shape(opening['geometry_nominal_local']);centre=np.asarray(line.centroid.coords[0]);direction=np.asarray(direction);direction=direction/np.linalg.norm(direction);attempts=[]
    for run in [4,5,6,7,8]:
        end=centre+run*direction;end_key=tuple(map(math.floor,end))
        if end_key not in terrain or end_key in protected|upper:continue
        foot=terrain[end_key]['y']+1
        if foot>top or top-foot>run*.75:continue
        axis=LineString([end,centre-.6*direction]);g=axis.buffer(.75,cap_style=2);columns=grid_cells(g,256);added={};surfaces={};valid=True
        for x,y in sorted(columns):
            if (x,y) not in terrain or (x,y) in protected:valid=False;break
            surface=round(2*(foot+(top-foot)*axis.project(Point(x+.5,y+.5))/axis.length))/2
            surface=top if (x,y) in upper else max(surface,terrain[x,y]['y']+1);surfaces[x,y]=surface
            base=math.ceil(surface)-1;material='stone_brick_slab' if surface%1 else 'stone_bricks'
            if (x,y) not in upper:
                for h in range(terrain[x,y]['y']+1,base+1):
                    key=x,h,y;wanted=material if h==base else 'stone_bricks'
                    if key in structures and structures[key]!=wanted:valid=False;break
                    added[key]=wanted
            for h in [math.ceil(surface),math.ceil(surface)+1]:
                if (x,h,y) in structures:valid=False;break
            if not valid:break
        if valid:
            rises=[abs(h-surfaces[q]) for k,h in surfaces.items() for q in [(k[0]+1,k[1]),(k[0],k[1]+1)] if q in surfaces]
            if max(rises,default=0)>1:valid=False
            connected=set();front=[min(surfaces)]
            while front:
                k=front.pop()
                if k in connected:continue
                connected.add(k)
                front.extend(q for q in [(k[0]-1,k[1]),(k[0]+1,k[1]),(k[0],k[1]-1),(k[0],k[1]+1)] if q in surfaces and q not in connected and abs(surfaces[k]-surfaces[q])<=1)
            if len(connected)!=len(surfaces) or not any(k in upper and surfaces[k]==top for k in surfaces) or not any(surfaces[k]==terrain[k]['y']+1 for k in surfaces):valid=False
        if valid:
            rails=0;rail_gaps=0
            possible={q for x,y in columns for q in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)] if q not in columns|upper|protected and q in terrain}
            for x,y in sorted(possible):
                q=Point(x+.5,y+.5);along=axis.project(q)
                if not 1<along<axis.length-1 or axis.distance(q)>1.65:continue
                adjacent=[surfaces[k] for k in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)] if k in surfaces]
                if not adjacent:continue
                rail=math.ceil(max(adjacent));proposal={(x,h,y):'stone_bricks' for h in range(terrain[x,y]['y']+1,rail)};proposal[x,rail,y]='oak_fence'
                if any(k in structures or k in added for k in proposal) or (x,rail+1,y) in structures:rail_gaps+=1;continue
                added.update(proposal);rails+=1
            return added,{'status':'estimated_half_step_entry_flight','ground_to_upper_floor_connected':True,'oak_fence_rail_columns':rails,'rail_gaps_due_to_preserved_geometry':rail_gaps,'rail_policy':'oak fences for a path narrower than four blocks','source_opening_id':opening['id'],'run_m':run,'width_m':1.5,'columns':len(surfaces),
                'maximum_neighbour_rise_m':max(rises,default=0),'surfaces':[{'source_cell_xy':list(k),'walking_top_m':h} for k,h in sorted(surfaces.items())],
                'source_stair_dimensions_verified':False,'headroom_policy':'two whole air cells above rounded-up walking surface','attempts_rejected':attempts}
        attempts.append({'run_m':run,'reason':'existing object / terrain / clearance conflict'})
    return {},{'status':'withheld_no_collision_free_entry_flight','source_stair_dimensions_verified':False,'attempts_rejected':attempts}


def upper_connectivity(columns,structures,heights,top,seeds):
    clear={k for k in columns if all((k[0],h,k[1]) not in structures and heights[k]<h for h in [top,top+1])}
    if any(not (set(s)&clear) for s in seeds):raise ValueError('Each component must have a clear upper-floor interior')
    first=min(set(seeds[0])&clear);seen={first};queue=deque([first])
    while queue:
        x,y=queue.popleft()
        for k in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)]:
            if k in clear and k not in seen:seen.add(k);queue.append(k)
    if any(not (set(s)&seen) for s in seeds):raise ValueError('Preshow-to-station upper floor is disconnected')
    return {'all_three_component_interiors_connected':True,'clear_upper_floor_columns':len(clear),'connected_upper_floor_columns':len(seen),'two_block_headroom_checked':True,'gameplay_tested':False}


def run(config,base_directory,geographic_directory,pdf_directory,evidence_directory,output,*,allow_provisional=False,cancelled=lambda:False):
    if allow_provisional is not True:raise ValueError('Explicit provisional station/preshow review opt-in required')
    if cancelled():raise CancelledError('Station review cancelled')
    output=Path(output);base_directory=Path(base_directory);geographic_directory=Path(geographic_directory)
    if output.exists():raise ValueError('Fresh station/preshow output required')
    profile=json.loads(PROFILE.read_text());base=json.loads((base_directory/'quality-report.json').read_text())
    for name,relative in [('world',base['world']['file']),('voxels','voxels.jsonl'),('report','quality-report.json')]:
        if file_hash(base_directory/relative)!=profile['base_pins'][name]:raise ValueError('Pinned corrected-shop input required')
    if base['implementation_sha256']!=file_hash(shop.__file__):raise ValueError('Current corrected-shop implementation required')
    for name,relative in [('terrain','terrain-samples.json'),('voxels','voxels.jsonl')]:
        if file_hash(geographic_directory/relative)!=profile['geographic_pins'][name]:raise ValueError('Pinned geographic baseline required')
    parts,height_review,source_image=verify_sources(pdf_directory,evidence_directory,profile)
    data=geometry_world.read_inputs(config['geometry_request']);sampled=geometry_world.rasterize(data,cancelled=cancelled)
    if base['planning_source_pins']!={n:config['geometry_request'][n+'_sha256'] for n in data}:raise ValueError('Planning inputs differ from corrected-shop base')
    rows=[json.loads(line) for line in (base_directory/'voxels.jsonl').read_text().splitlines()]
    terrain={};old_structures={}
    for r in rows:
        key=r['x'],r['z']-1
        if r['kind']=='terrain':terrain[key]=dict(r)
        else:old_structures[r['x'],r['y'],r['z']-1]=dict(r)
    base_heights={k:r['y'] for k,r in terrain.items()}
    raw_terrain={(r['x'],r['z']-1):r for r in map(json.loads,(geographic_directory/'voxels.jsonl').read_text().splitlines()) if r['kind']=='terrain'}
    if set(terrain)!=set(raw_terrain) or len(terrain)>65536:raise ValueError('Complete bounded baseline terrain required')
    source_access=json.loads((base_directory/'source-access-review/access-review.json').read_text());a,b,c,d,e,f=source_access['drawing_correspondence']['affine'];matrix=np.array([[a,b],[c,d]]);translation=np.array([e,f])
    if not np.allclose(matrix.T@matrix,np.eye(2),atol=1e-8) or np.linalg.det(matrix)<0:raise ValueError('Existing rigid placement required')
    top=profile['display_floor_top_m'];bottom=profile['undercroft_floor_top_m'];limits=profile['limits'];new={};walls={};boundaries={};portals={};part_reports=[]
    tower=next(p for p in parts if p['id']=='preshow_tower');station=next(p for p in parts if p['id']=='station')
    for part in parts:
        name=part['id'];model=part['model'];dims=model['dimensions'];dims.update(eave_m=height_review[name]['eave_m'],ridge_m=height_review[name]['ridge_m'])
        centring_shift=[0.0,0.0]
        if name=='station':
            # Centre the separately traced wall role under the actual roof.
            oldwall=shape(next(r['wall_geometry_nominal_local'] for r in source_access['building_outline_role_comparisons'] if r['building']=='Station'))
            centring_shift=(np.asarray(part['source_plan_centre_m'])@matrix.T+translation-np.asarray(oldwall.centroid.coords[0])).tolist()
            local=(np.asarray(oldwall.exterior.coords)[:-1]-np.asarray(oldwall.centroid.coords[0]))@matrix
            model['outer_wall_base_outline']=[[*p,0] for p in local]
            door=next(o for o in model['opening_base_segments'] if o['id'].startswith('x+'))
            centre=tower['source_plan_centre_m'][1]-part['source_plan_centre_m'][1];normal=max(p[0] for p in local)
            door['endpoints']=[[normal,centre-.9,0],[normal,centre+.9,0]];door['width_metres']=1.8;door['id']='x+/preshow-interface'
        if name=='preshow_tower':
            door=next(o for o in model['opening_base_segments'] if o['id'].startswith('x-'));normal=door['endpoints'][0][0]
            door['endpoints']=[[normal,-.9,0],[normal,.9,0]];door['width_metres']=1.8;door['id']='x-/station-interface'
        blocks,wall,boundary,openings,quality=build_component(model,part['source_plan_centre_m'],matrix,translation,top,limits,cancelled)
        walls[name]=wall;boundaries[name]=boundary;portals[name]=openings
        # Higher preshow tower is merged last; portal air is carved afterwards.
        part_reports.append({'id':name,'wall_trace_centring_shift_m':centring_shift,'upper_floor_quantization_error_m':top-profile['printed_levels_m']['station_landscape_ffl' if name=='station' else 'preshow_upper'],'source_plan_centre_m':part['source_plan_centre_m'],'wall_geometry_nominal_local':mapping(wall),'source_outline':part['source_outline'],'height_review':height_review[name],'openings':openings,**quality})
        for k,v in blocks.items():
            if k not in new or name=='preshow_tower':new[k]=v
    connections=[]
    for left,right,prefix_l,prefix_r,width in [('preshow_low','preshow_tower','z+','z-',3),('preshow_tower','station','x-','x+',1.8)]:
        la=shape(next(p for p in portals[left] if p['id'].startswith(prefix_l))['geometry_nominal_local']);lb=shape(next(p for p in portals[right] if p['id'].startswith(prefix_r))['geometry_nominal_local'])
        corridor=LineString([la.centroid,lb.centroid]).buffer(width/2,cap_style=3);connections.append(corridor)
    upper_geometry=unary_union(list(walls.values())+connections);upper=grid_cells(upper_geometry)|set().union(*boundaries.values())
    preshow_geometry=unary_union([walls['preshow_low'],walls['preshow_tower'],connections[0]]);preshow=grid_cells(preshow_geometry)
    if len(upper)>limits['new_floor_cells'] or not upper<=set(terrain):raise ValueError('Complete new floor coverage required')
    protected_shop={(r['source_xyz'][0],r['source_xyz'][2]) for r in json.loads((base_directory/'shell-blocks.json').read_text())}
    protected_shop|={tuple(r['source_cell_xy']) for r in json.loads((base_directory/'floor-cells.json').read_text()) if r['labels']==['Shop']}
    if upper&protected_shop:raise ValueError('New station/preshow overlaps corrected shop')
    old_station={tuple(r['source_cell_xy']) for r in json.loads((base_directory/'floor-cells.json').read_text()) if r['labels']==['Station']}
    retired_plinths=0
    for row in json.loads((base_directory/'floor-cells.json').read_text()):
        if row['labels']!=['Station']:continue
        x,y=row['source_cell_xy']
        for h in range(row['original_terrain_block_odn_m']+1,row['base_odn_block_m']):
            key=x,h,y
            if key in old_structures:
                if old_structures[key]['material']!='stone_bricks':raise ValueError('Old station plinth identity conflict')
                old_structures.pop(key);retired_plinths+=1
    for k in old_station-upper:terrain[k]=dict(raw_terrain[k])
    superseded=[]
    for k in sorted(upper&set(sampled['rocks'])):
        if k in protected_shop:raise ValueError('New footprint conflicts with protected shop')
        superseded.append({'source_cell_xy':list(k),'original_inferred_column':sampled['rocks'][k]})
    if len(superseded)>limits['inferred_edging_columns_superseded']:raise ValueError('Too many inferred boundary conflicts')
    for r in superseded:
        x,y=r['source_cell_xy']
        for level,material in r['original_inferred_column']:
            p=x,terrain[x,y]['y']+level,y
            if p in old_structures and old_structures[p]['material']==material:old_structures.pop(p)
    # Hollow preshow undercroft; station support remains an estimated plinth.
    lower_boundary=set()
    for polygon in ([preshow_geometry] if preshow_geometry.geom_type=='Polygon' else preshow_geometry.geoms):lower_boundary|=boundary_columns([[*p,0] for p in list(polygon.exterior.coords)[:-1]],1)
    preshow|=lower_boundary
    for k in upper|preshow:
        x,y=k;original=terrain[k]['y'];lower=bottom-1 if k in preshow else top-1
        if original-lower>limits['excavation_depth_blocks']:raise ValueError('Excavation budget exceeded')
        material=terrain[k]['material'];terrain[k]={'x':x,'y':lower,'z':y+1,'kind':'terrain','material':'stone_bricks' if k in preshow else material if material!='grass_block' else 'stone_bricks'}
        if k in preshow:new[x,top-1,y]=material if material.endswith('_wool') else 'stone_bricks'
        else:
            for h in range(original+1,top-1):new[x,h,y]='stone_bricks'
    for x,y in lower_boundary:
        for h in range(bottom,top-1):new[x,h,y]='stone_bricks'
    portal_air=set()
    for openings in portals.values():
        for p in openings:
            for x,y in p['columns_xy']:
                portal_air.update((x,h,y) for h in range(top,top+p['headroom_blocks']))
    for corridor in connections:
        for x,y in grid_cells(corridor):
            upper.add((x,y));new[x,top-1,y]='stone_bricks'
            portal_air.update((x,h,y) for h in [top,top+1])
    for p in portal_air:new.pop(p,None)
    if any(p in old_structures for p in portal_air):raise ValueError('Portal collides with preserved existing structure')
    if any(k in old_structures and old_structures[k]['material']!=m for k,m in new.items()):raise ValueError('New structure collides with preserved geometry')
    if len(new)>limits['new_structure_blocks']:raise ValueError('Structure block budget exceeded')
    heights={k:r['y'] for k,r in terrain.items()};all_structures={k:r['material'] for k,r in old_structures.items()};all_structures.update(new)
    connectivity=upper_connectivity(upper,all_structures,heights,top,[grid_cells(walls[n].buffer(-.9)) for n in ['preshow_low','preshow_tower','station']])
    basement_air={(x,h,y) for x,y in preshow-lower_boundary for h in range(bottom,top-1)}
    if any(p in all_structures for p in basement_air):raise ValueError('Provisional undercroft interior is obstructed')
    main_entry=next(o for o in portals['preshow_low'] if o['id'].startswith('z-'))
    flight,flight_report=entry_flight(main_entry,-matrix[:,1],top,terrain,all_structures,protected_shop,upper)
    new.update(flight);all_structures.update(flight)
    if len(new)>limits['new_structure_blocks']:raise ValueError('Access additions exceed structure budget')
    flight_head_air={(k['source_cell_xy'][0],h,k['source_cell_xy'][1]) for k in flight_report.get('surfaces',[]) for h in [math.ceil(k['walking_top_m']),math.ceil(k['walking_top_m'])+1]}

    # Original shop entry thresholds stay at their corrected elevation.
    old_shop_cells=json.loads((base_directory/'shell-blocks.json').read_text())
    if any(all_structures.get(tuple(r['source_xyz']))!=r['material'] for r in old_shop_cells):raise ValueError('Corrected shop geometry changed')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='station-preshow-',dir=output.parent) as temp:
        root=Path(temp)/'result';root.mkdir();voxel=root/'voxels.jsonl'
        with voxel.open('w') as stream:
            for r in terrain.values():stream.write(json.dumps(r)+'\n')
            for (x,h,y),material in sorted(all_structures.items()):stream.write(json.dumps({'x':x,'y':h,'z':y+1,'kind':'structure','material':material})+'\n')
        report={'version':'conditional-station-preshow-world-v1','status':'station_and_preshow_exterior_with_provisional_undercroft','voxel_size_m':1,'model_blocks_per_source_metre':1,
            'crs':'EPSG:27700','vertical_datum':'ODN','alignment':base['alignment'],'horizontal_transform':base['horizontal_transform'],'spawn_local_xyz_m':base['spawn_local_xyz_m'],
            'parts':part_reports,'upper_floor_top_m':top,'undercroft_floor_top_m':bottom,'station_inspection_level_m':181.25,'inspection_floor_reconstructed':False,
            'source_levels':profile['printed_levels_m'],'source_floor_datum_verified':False,'source_station_passenger_floor_role_verified':False,
            'upper_floor_columns':len(upper),'undercroft_columns':len(preshow),'undercroft_geometry_nominal_local':mapping(preshow_geometry),'upper_connection_geometries_nominal_local':[mapping(g) for g in connections],
            'retired_old_station_plinth_blocks':retired_plinths,'hollow_undercroft_air_cells':len(basement_air),'entry_flight':flight_report,'upper_connectivity':connectivity,'source_inferred_boundaries_superseded':superseded,
            'new_structure_blocks':len(new),'preserved_shop_blocks':len(old_shop_cells),'source_shop_world_sha256':base['world']['sha256'],'source_base_world_unchanged':True,
            'datum_assumption':'printed levels treated as ODN only for this conditional prototype; upper floors rounded up to whole-block walking top',
            'sources':base['sources'],'source_pdf_sha256':profile['sources'],'planning_source_pins':base['planning_source_pins'],'source_pins':base['source_pins'],
            'production_placement_eligible':False,'physical_registration_verified':False,'accepted_training_labels':0,'minecraft_import_tested':False,
            'implementation_sha256':file_hash(__file__),'profile_sha256':file_hash(PROFILE),'source_base_implementation_sha256':file_hash(shop.__file__),
            'template_implementation_sha256':file_hash(templates.__file__),'limitations':profile['limitations']}
        from . import bedrock
        from .planning_world_preview import _spawn_check,_verify_archive
        old_openings=base['shop_shell']['openings'];old_top=next(r['preview_floor_top_odn_assumption_m'] for r in base['floor_plates'] if r['labels']==['Shop'])
        kept_edging={k:column for k,column in sampled['rocks'].items() if all((k[0],base_heights[k]+level,k[1]) in old_structures and old_structures[k[0],base_heights[k]+level,k[1]]['material']==material for level,material in column)}
        samples={'bounds':sampled['bounds'],'platform_cells':len(terrain),'ground':{k:r['material'] for k,r in terrain.items()},'rocks':kept_edging,'boundary_blocks':sum(map(len,kept_edging.values()))}
        def check(path,offset,spawn):
            if offset!=base['world']['vertical_offset_blocks']:raise ValueError('World offset changed; shop would move in Minecraft')
            report['spawn_validation']=_spawn_check(path,spawn)
            report['saved_geometry_validation']=shop.saved_check(path,offset,samples,heights,all_structures,old_openings,old_top,cancelled)
            report['native_portal_validation']=_native_air(path,offset,portal_air)
            report['native_undercroft_validation']=_native_air(path,offset,basement_air)
            report['native_entry_flight_validation']=_native_air(path,offset,flight_head_air)
            report['native_entry_surface_validation']=_native_surfaces(path,offset,flight_report.get('surfaces',[]))
            atomic_json(path/'planning-geographic-alignment.json',{**base['alignment'],'minecraft_cell_centre_to_source_xy':'[Minecraft X + 0.5, -(Minecraft Z + 0.5)]','vertical_offset_blocks':offset})
            atomic_json(path/'STATION-PRESHOW-ASSUMPTIONS.json',{k:report[k] for k in ['datum_assumption','source_levels','limitations','inspection_floor_reconstructed']})
        world=bedrock.export_world(voxel,root,report,name='Wicker STATION and PRESHOW - corrected shop retained',max_blocks=1_000_000,ground_depth=3,foundation_mode='chunk',post_export_check=check)
        report['world']=world;report['archive_validation']=_verify_archive(root/world['file'],root/'bedrock-world',world,cancelled)
        shutil.move(root/world['file'],root/'wicker-station-preshow.mcworld');report['world']['file']='wicker-station-preshow.mcworld';shutil.rmtree(root/'bedrock-world')
        source_image.save(root/'source-height-traces.png');_preview(root,voxel,top)
        from PIL import Image,ImageDraw
        image=Image.open(root/'building-shell-preview.png');draw=ImageDraw.Draw(image);draw.rectangle((0,0,image.width,58),fill='#f9f7ee');draw.text((20,14),'STATION + PRESHOW: gabled station / lower gable / pyramid tower; corrected shop retained',fill='black');draw.text((20,34),'Native slab roofs; hollow provisional undercroft. Source datum / exact entrances / basement details unresolved.',fill='black');image.save(root/'building-shell-preview.png')
        atomic_json(root/'quality-report.json',report);atomic_json(root/'new-structure-blocks.json',[{'source_xyz':list(k),'material':v} for k,v in sorted(new.items())]);atomic_json(root/'portal-air.json',[list(p) for p in sorted(portal_air)])
        (root/'index.html').write_text('<!doctype html><meta charset="utf-8"><h1>Conditional station and preshow world</h1><a href="wicker-station-preshow.mcworld">Download world</a><p>Corrected shop retained. Source-relative manual roof traces, slab roofs, provisional upper connections and hollow undercroft. Exact basement walls/openings and external access remain unresolved.</p><img style="max-width:100%" src="building-shell-preview.png">')
        for name,relative in [('world',base['world']['file']),('voxels','voxels.jsonl'),('report','quality-report.json')]:
            if file_hash(base_directory/relative)!=profile['base_pins'][name]:raise ValueError('Corrected shop input changed during export')
        shutil.move(root,output)
    return report


def _preview(root,voxel,floor_top):
    """Schematic native-shaped blocks, with oak thatch-proxy slab colours."""
    from PIL import Image,ImageDraw,ImageColor
    from .rock_world_render import colour,_boxes
    rows=[json.loads(line) for line in voxel.read_text().splitlines()]
    occupied={(r['x'],r['z']-1,r['y']):r['material'] for r in rows if 65<=r['x']<=140 and 95<=r['z']-1<=151}
    def project(p):
        x,y,h=p;return ((x-y)*9,(x+y)*4.5-(h-floor_top)*11)
    all_points=[project((x+dx,y+dy,h+dh)) for x,y,h in occupied for dx,dy,dh in [(0,0,0),(1,1,1)]]
    xmin=min(p[0] for p in all_points);ymin=min(p[1] for p in all_points);width=math.ceil(max(p[0] for p in all_points)-xmin)+90;height=math.ceil(max(p[1] for p in all_points)-ymin)+145
    image=Image.new('RGB',(width,height),'#f9f7ee');draw=ImageDraw.Draw(image);faces=[]
    palette={'spruce_planks':'#8b6747','dark_oak_slab':'#493520','dark_oak_slab_top':'#493520','oak_slab':'#b18a50','oak_slab_top':'#b18a50','grass_block':'#83a65c','stone_bricks':'#9c9e9a'}
    for (x,y,h),material in occupied.items():
        paint='#46321f' if material=='dark_oak_fence' else '#9b7953' if material.startswith('spruce_trapdoor_') else palette.get(material,colour(material));rgb=ImageColor.getrgb(paint)
        if material.endswith('_slab_top'):bounds=[(0,.5,0,1,1,1)]
        elif material.startswith('spruce_trapdoor_'):
            direction=material.removeprefix('spruce_trapdoor_');t=3/16
            bounds=[{'north':(0,0,0,1,1,t),'south':(0,0,1-t,1,1,1),'east':(0,0,0,t,1,1),'west':(1-t,0,0,1,1,1)}[direction]]
        else:
            neighbours=[(dx,dy) for dx,dy in [(1,0),(-1,0),(0,1),(0,-1)] if occupied.get((x+dx,y+dy,h)) in ['oak_fence','dark_oak_fence']]
            bounds=_boxes('oak_fence' if material=='dark_oak_fence' else material,neighbours)
        for x0,h0,y0,x1,h1,y1 in bounds:
            corners=[(x+x0,y+y0,h+h0),(x+x1,y+y0,h+h0),(x+x1,y+y1,h+h0),(x+x0,y+y1,h+h0),(x+x0,y+y0,h+h1),(x+x1,y+y0,h+h1),(x+x1,y+y1,h+h1),(x+x0,y+y1,h+h1)]
            for neighbour,indices,shade in [((x+1,y,h),[1,2,6,5],.75),((x,y+1,h),[2,3,7,6],.58),((x,y,h+1),[4,5,6,7],1)]:
                if bounds==[(0,0,0,1,1,1)] and neighbour in occupied:
                    other=occupied[neighbour]
                    if _boxes(other)==[(0,0,0,1,1,1)] and not other.startswith('spruce_trapdoor_') and other!='dark_oak_fence' and not other.endswith('_slab_top'):continue
                vertices=[corners[i] for i in indices];depth=sum(a+b+.82*c for a,b,c in vertices)/4;points=[(project(v)[0]-xmin+40,project(v)[1]-ymin+82) for v in vertices];faces.append((depth,points,tuple(round(v*shade) for v in rgb)))
    for _,points,rgb in sorted(faces,key=lambda f:f[0]):draw.polygon(points,fill=rgb,outline=tuple(max(0,v-12) for v in rgb))
    draw.text((20,height-28),'Schematic native block shapes; oak slabs are illustrative thatch proxies. Ground and access remain provisional.',fill='black')
    image.save(root/'building-shell-preview.png')


def _native_surfaces(path,offset,surfaces):
    from amulet.level.formats.leveldb_world import LevelDBFormat
    from amulet_nbt import StringTag
    wrapper=LevelDBFormat(str(path));wrapper.open();groups={};count=0
    for r in surfaces:
        x,y=r['source_cell_xy'];groups.setdefault((x//16,(-y-1)//16),[]).append(r)
    try:
        for (cx,cz),rows in groups.items():
            chunk=wrapper.load_chunk(cx,cz,'minecraft:overworld')
            for r in rows:
                x,y=r['source_cell_xy'];top=r['walking_top_m'];base=math.ceil(top)-1
                actual=chunk.block_palette[int(chunk.blocks[x%16,base+offset,(-y-1)%16])]
                if top%1:
                    if actual.base_name!='slab' or actual.properties.get('type')!=StringTag('bottom'):raise ValueError('Saved half-step surface is not a native bottom slab')
                elif actual.base_name in ['air','water','fence','trapdoor','stairs','wall'] or (actual.base_name=='slab' and actual.properties.get('type')!=StringTag('top')):raise ValueError('Saved whole-step surface does not reach planned walking height')
                count+=1
    finally:wrapper.close()
    return {'actual_native_walking_surfaces_verified':count,'half_step_block_states_checked':True,'minecraft_import_tested':False}


def _native_air(path,offset,points):
    from amulet.level.formats.leveldb_world import LevelDBFormat
    wrapper=LevelDBFormat(str(path));wrapper.open();groups={};count=0
    for x,h,y in points:groups.setdefault((x//16,(-y-1)//16),[]).append((x,h,y))
    try:
        for (cx,cz),cells in groups.items():
            chunk=wrapper.load_chunk(cx,cz,'minecraft:overworld')
            for x,h,y in cells:
                block=chunk.block_palette[int(chunk.blocks[x%16,h+offset,(-y-1)%16])]
                if block.base_name!='air':raise ValueError('Saved compound portal is obstructed')
                count+=1
    finally:wrapper.close()
    return {'compound_portal_air_cells_verified':count,'minecraft_import_tested':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for n in ['config','base-directory','geographic-directory','pdf-directory','evidence-directory','output']:parser.add_argument('--'+n,required=True)
    parser.add_argument('--allow-provisional',action='store_true');args=parser.parse_args(argv);p=Path(args.config).resolve()
    if p.stat().st_size>32768:raise ValueError('Bounded request required')
    config=json.loads(p.read_text())
    for n in ['layout','paving','gaps','buildings','markings','expansion']:config['geometry_request'][n+'_path']=str((p.parent/config['geometry_request'][n+'_path']).resolve())
    r=run(config,args.base_directory,args.geographic_directory,args.pdf_directory,args.evidence_directory,args.output,allow_provisional=args.allow_provisional)
    print(json.dumps({'new_structure_blocks':r['new_structure_blocks'],'world_sha256':r['world']['sha256']}))


if __name__=='__main__':main()
