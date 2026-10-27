"""Isolated conditional wall-based floors and source-height shop shell preview."""
from concurrent.futures import CancelledError
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile

import numpy as np
from shapely.affinity import affine_transform
from shapely.geometry import Point,Polygon,LineString,box,shape,mapping

from . import planning_building_access as access,planning_floor_preview as floor
from . import planning_geo_preview as geo,planning_geometry_world as geometry_world,planning_surface_audit as audit
from .drawing_page_tools import pixel_to_native
from .generation_cycles import atomic_json,file_hash
from .horizontal_grid import OSTN15Transform

PROFILE=Path(__file__).parent/'data/wicker-wall-shell.json'


def ordered_rigid(source,target):
    """Retain source corner identities; disallow scaling and reflection."""
    x=np.asarray(source,dtype=float);y=np.asarray(target,dtype=float)
    if x.shape!=(4,2) or y.shape!=(4,2) or not np.isfinite(x).all() or not np.isfinite(y).all() or min(Polygon(x).area,Polygon(y).area)<=0:
        raise ValueError('Finite nondegenerate ordered four-corner footprints required')
    u,_,vt=np.linalg.svd((x-x.mean(0)).T@(y-y.mean(0)));r=u@vt;t=y.mean(0)-x.mean(0)@r
    error=float(np.max(np.linalg.norm(x@r+t-y,axis=1)))
    if np.linalg.det(r)<0 or error>1e-6:raise ValueError('Ordered shop correspondence would reflect or stretch source geometry')
    return r,t,error


def verify_shop_sources(pdf_directory,evidence_directory,profile):
    """Verify retained model and replay the elevation height measurements."""
    import pymupdf
    evidence_directory=Path(evidence_directory);inputs={}
    for n,sha in profile['review_input_sha256'].items():
        p=evidence_directory/n
        if p.stat().st_size>2_000_000 or file_hash(p)!=sha:raise ValueError('Pinned shop review input required')
        inputs[n]=json.loads(p.read_text())
    model=inputs['wicker-shop-wall-model.json'];annotations=inputs['wicker-shop-vertical-annotations.json'];roof=inputs['wicker-shop-elevation-annotations.json']
    sha=profile['shop_elevation_sha256'];pdf=Path(pdf_directory)/(sha+'.pdf')
    if pdf.stat().st_size>24_000_000 or file_hash(pdf)!=sha:raise ValueError('Original proposed shop elevation PDF required')
    with pymupdf.open(pdf) as doc:
        if len(doc)!=1 or doc[0].rotation!=90:raise ValueError('Reviewed rotated shop elevation sheet required')
        page=doc[0];pix=page.get_pixmap(matrix=pymupdf.Matrix(1888/page.rect.width,1888/page.rect.width))
        for a in [annotations,roof]:
            if a['source_sha256']!=sha or [pix.width,pix.height]!=a['render_size_pixels'] or hashlib.sha256(pix.samples).hexdigest()!=a['render_samples_sha256']:raise ValueError('Shop elevation render changed')
        matrix=pymupdf.Matrix(pixel_to_native(page,pix.width,pix.height));unit=100*.0254/72
        mpp=math.hypot(matrix.c,matrix.d)*unit;heights={}
        for key,row in annotations['vertical_traces'].items():
            top,bottom=row['top_pixel'],row['bottom_pixel']
            if not 0<=top[1]<bottom[1]<pix.height:raise ValueError('Invalid reviewed vertical trace')
            value=(bottom[1]-top[1])*mpp
            if abs(value-model['vertical_measurements'][key]['height_metres'])>1e-9:raise ValueError('Shop wall height replay differs')
            heights[key]=value
        first=roof['views'][0]['points_pixels'];last=roof['views'][3]['points_pixels'];mx=math.hypot(matrix.a,matrix.b)*unit
        length=abs(first['roof_right'][0]-first['roof_left'][0])*mx
        width=abs(last['roof_right'][0]-last['roof_left'][0])*mx
        eave=abs(first['floor'][1]-first['eave'][1])*mpp;ridge=abs(first['floor'][1]-first['ridge'][1])*mpp
        vertices=np.asarray(model['roof_mesh']['vertices'])
        if not np.allclose([np.ptp(vertices[:,0]),np.ptp(vertices[:,1]),vertices[:,2].min(),vertices[:,2].max()],[length,width,eave,ridge],atol=1e-9,rtol=0):raise ValueError('Shop roof dimensions fail original elevation replay')
        for o in model['opening_base_segments']:
            if abs(o['height_metres']-heights[o['height_trace']])>1e-9:raise ValueError('Opening height does not match source trace')
    guide=inputs['wicker-shop-projection-model.json']
    if guide['projection_input_wall_sha256']!=profile['review_input_sha256']['wicker-shop-wall-model.json']:raise ValueError('Study guide wall model mismatch')
    for source,frame in guide['projection_review']['source_frames'].items():
        original=Path(pdf_directory)/(source+'.pdf')
        if original.stat().st_size>24_000_000 or file_hash(original)!=source:raise ValueError('Study canopy original PDF changed')
        with pymupdf.open(original) as doc:
            if len(doc)!=1:raise ValueError('Single original study sheet required')
            page=doc[0];render=page.get_pixmap(matrix=pymupdf.Matrix(1888/page.rect.width,1888/page.rect.width))
            if [render.width,render.height]!=frame['render_size_pixels'] or hashlib.sha256(render.samples).hexdigest()!=frame['render_samples_sha256']:raise ValueError('Retained study canopy render changed')
    for view,trace in guide['projection_review']['elevation_traces'].items():
        points=trace['manual_points_pixels'];floor_y=points['floor'][1]
        for key,value in trace['heights_above_drawn_floor_metres'].items():
            if abs((floor_y-points[key][1])*mpp-value)>1e-9:raise ValueError('Study canopy height trace failed source replay')
    model['projection_surfaces']=guide['projection_surfaces'];model['projection_review']=guide['projection_review']
    return model,{'guide_model_sha256':profile['review_input_sha256']['wicker-shop-projection-model.json'],'source_pdf_sha256':sha,'vertical_traces_replayed':len(heights),'roof_dimensions_m':[length,width],'eave_above_drawn_floor_m':eave,'ridge_above_drawn_floor_m':ridge,'as_built_verified':False}


def shop_shell(model,wall_geometry,floor_top,*,cancelled=lambda:False):
    """Conservative one-block display shell; heights remain source-relative."""
    from .shop_shell import boundary_columns,leak_audit
    if type(floor_top) is not int:raise ValueError('Integer conditional walking floor top required')
    outline=np.asarray(model['outer_wall_base_outline'])[:,:2];target=np.asarray(wall_geometry.exterior.coords)[:-1]
    rotation,translation,error=ordered_rigid(outline,target)
    vertices=np.asarray(model['roof_mesh']['vertices']);roof_shape=Polygon([[-np.ptp(vertices[:,0])/2,-np.ptp(vertices[:,1])/2],[np.ptp(vertices[:,0])/2,-np.ptp(vertices[:,1])/2],[np.ptp(vertices[:,0])/2,np.ptp(vertices[:,1])/2],[-np.ptp(vertices[:,0])/2,np.ptp(vertices[:,1])/2]])
    roof_shape=affine_transform(roof_shape,[rotation[0,0],rotation[1,0],rotation[0,1],rotation[1,1],*translation])
    boundary=boundary_columns([[*p,0] for p in target],1);xmin,ymin,xmax,ymax=roof_shape.bounds
    if (math.ceil(xmax)-math.floor(xmin))*(math.ceil(ymax)-math.floor(ymin))>2048:raise ValueError('Shop roof sampling budget exceeded')
    half_width=np.ptp(vertices[:,1])/2;eave=vertices[:,2].min();ridge=vertices[:,2].max();roof_heights={}
    for x in range(math.floor(xmin),math.ceil(xmax)):
        if cancelled():raise CancelledError('Shop shell cancelled')
        for y in range(math.floor(ymin),math.ceil(ymax)):
            if roof_shape.intersection(box(x,y,x+1,y+1)).area<1e-9:continue
            local=(np.array([x+.5,y+.5])-translation)@rotation.T
            roof_heights[x,y]=math.floor(eave+(ridge-eave)*(1-min(1,abs(local[1])/half_width)))
    if not boundary<=set(roof_heights):raise ValueError('Wall boundary lacks main roof coverage')
    doors={};opening_reviews=[]
    for opening in model['opening_base_segments']:
        pts=np.asarray(opening['endpoints'])[:,:2]@rotation+translation;line=LineString(pts);length=line.length
        if not 0<opening['height_metres']<eave:raise ValueError('Opening height must fit below roof eave')
        axis=(pts[1]-pts[0])/length
        cols={k for k in boundary if 0<=np.dot(np.array([k[0]+.5,k[1]+.5])-pts[0],axis)<=length and line.distance(Point(k[0]+.5,k[1]+.5))<=1}
        # A sub-metre source door may alias away: one-column display is explicit.
        snapped=False
        if not cols:
            cols={min(boundary,key=lambda k:Point(k[0]+.5,k[1]+.5).distance(line.centroid))};snapped=True
        head=math.floor(opening['height_metres'])
        if head<2:raise ValueError('Opening has less than two full headroom blocks')
        for k in cols:doors[k]=max(doors.get(k,0),head)
        opening_reviews.append({'id':opening['id'],'geometry_nominal_local':mapping(line),'source_width_m':length,'source_height_above_floor_m':opening['height_metres'],
            'display_clearance_blocks':head,'display_columns_xy':[list(k) for k in sorted(cols)],'submetre_opening_snapped_to_column':snapped,'full_width_physical_clearance_verified':False,'external_access_verified':False})
    roofs=set();walls=set();risers=0
    for (x,y),h in roof_heights.items():
        low=min([h]+[roof_heights[q] for q in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)] if q in roof_heights])
        if h-low>2:raise ValueError('Unbounded roof step')
        roofs.update((x,z,y) for z in range(low,h+1));risers+=h-low
    bottoms={}
    for x,z,y in roofs:bottoms[x,y]=min(bottoms.get((x,y),z),z)
    for x,y in boundary:
        for z in range(doors.get((x,y),0),bottoms[x,y]):walls.add((x,z,y))
    # The audit uses floor-relative heights and an arbitrary integer XY origin.
    cx,cy=map(math.floor,wall_geometry.centroid.coords[0]);shifted={(x-cx,z,y-cy) for x,z,y in roofs|walls}
    closure=leak_audit(shifted,{(x-cx,y-cy) for x,y in boundary},{(x-cx,y-cy):h for (x,y),h in doors.items()},[[x-cx,y-cy,0] for x,y in target],1)
    if closure['interior_reached_from_exterior']:raise ValueError('Shop shell leaks with openings temporarily sealed')
    if any((x,z,y) in walls|roofs for (x,y),h in doors.items() for z in range(h)):raise ValueError('Shop doorway obstructed')
    # Sample the exposed roof at half-metre height increments, then limit each
    # four-neighbour step to one half-block. This avoids metre-high timber bands.
    import heapq
    half_heights={};source_surfaces={}
    for x,y in roof_heights:
        local=(np.array([x+.5,y+.5])-translation)@rotation.T
        surface=eave+(ridge-eave)*(1-min(1,abs(local[1])/half_width))
        source_surfaces[x,y]=surface
        half_heights[x,y]=round(2*surface)-1
    raw_half_heights=dict(half_heights)
    pending=[(h,x,y) for (x,y),h in half_heights.items()];heapq.heapify(pending)
    while pending:
        h,x,y=heapq.heappop(pending)
        if half_heights[x,y]!=h:continue
        for q in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)]:
            if q in half_heights and half_heights[q]>h+1:
                half_heights[q]=h+1;heapq.heappush(pending,(h+1,*q))
    if max(raw_half_heights[k]-h for k,h in half_heights.items())>1:raise ValueError('Roof smoothing exceeds one half-block')
    relative={};roof_slabs={};wall_aliases=0
    for (x,y),h in half_heights.items():
        roof_slabs[x,h//2,y]='dark_oak_slab_top' if h%2 else 'dark_oak_slab'
    for x,y in boundary:
        h=half_heights[x,y];base=h//2
        for z in range(doors.get((x,y),0),base):relative[x,z,y]='spruce_planks'
        # A whole-block timber gable top cannot share a cell with a different
        # material top slab. Keep that boundary cell as wall, not a roof band.
        if h%2:
            relative[x,base,y]='spruce_planks';roof_slabs.pop((x,base,y));wall_aliases+=1
    relative.update(roof_slabs)
    from .shop_slabs import occupied_halves
    halves=occupied_halves({(x-cx,z,y-cy):m for (x,z,y),m in relative.items()})
    half_boundary={(2*(x-cx)+dx,2*(y-cy)+dy) for x,y in boundary for dx in (0,1) for dy in (0,1)}
    half_doors={(2*(x-cx)+dx,2*(y-cy)+dy):2*h for (x,y),h in doors.items() for dx in (0,1) for dy in (0,1)}
    native_closure=leak_audit(halves,half_boundary,half_doors,[[x-cx,y-cy,0] for x,y in target],2)
    if native_closure['interior_reached_from_exterior']:raise ValueError('Native slab-shaped shop shell leaks with openings sealed')
    blocks={(x,z+floor_top,y):m for (x,z,y),m in relative.items()}
    return blocks,boundary,{'wall_blocks':sum(m=='spruce_planks' for m in relative.values()),'roof_blocks':len(roof_slabs),'roof_slab_blocks':len(roof_slabs),'roof_full_blocks':0,
        'roof_bottom_slabs':sum(m=='dark_oak_slab' for m in roof_slabs.values()),'roof_top_slabs':sum(m=='dark_oak_slab_top' for m in roof_slabs.values()),
        'timber_fascia_blocks':0,'gable_wall_slab_alias_cells':wall_aliases,'roof_half_step_smoothing_cells':sum(raw_half_heights[k]!=h for k,h in half_heights.items()),
        'maximum_roof_smoothing_m':max(raw_half_heights[k]-h for k,h in half_heights.items())/2,
        'roof_exposed_surface_minus_source_range_m':[min((h+1)/2-source_surfaces[k] for k,h in half_heights.items()),max((h+1)/2-source_surfaces[k] for k,h in half_heights.items())],
        'estimated_roof_riser_blocks':0,'ordered_corner_max_residual_m':error,
        'source_plan_to_current_local_row_rotation':rotation.tolist(),'source_plan_to_current_local_translation_m':translation.tolist(),
        'openings':opening_reviews,'previous_full_cell_envelope_air_flood':closure,'native_slab_shape_air_flood':native_closure,
        'roof_materials':['dark_oak_slab','dark_oak_slab_top'],'roof_slab_half':'source-profile bottom/top steps','roof_thickness_m':0.5,
        'display_rule':'half-metre exposed roof samples; at most half-metre neighbour steps; no full roof layer or metre-high fascia bands; full timber at gable/slab boundary aliases',
        'source_wall_roof_centring_hypothesis_retained':True,'physical_thickness_verified':False,'reconstructed_as_built':False}



def fit_shop_approaches(wall,openings,heights,floor_targets,ground,rocks,plan_markers,floor_top):
    """Bounded provisional cut/landing fit; preserve source XY and materials."""
    protected=set(rocks)|{k for k,r in plan_markers.items() if r['role']!='queue_area'}
    collar=wall.buffer(1);changes={};landings=[];material_changes=[]
    def adjust(k,base):
        old=heights[k]
        if abs(old-base)>1:raise ValueError('Shop approach change exceeds one block')
        if old!=base:changes[k]={'source_cell_xy':list(k),'old_ground_block_m':old,'new_ground_block_m':base};heights[k]=base
    for k,h in sorted(heights.items()):
        if k in floor_targets or k in protected:continue
        point=Point(k[0]+.5,k[1]+.5)
        if collar.covers(point) and not wall.covers(point) and h>=floor_top:adjust(k,floor_top-1)
    for opening in openings:
        line=shape(opening['geometry_nominal_local']);candidates=set()
        for x,y in opening['display_columns_xy']:
            for k in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)]:
                if k not in heights or k in floor_targets or k in protected:continue
                point=Point(k[0]+.5,k[1]+.5)
                if not wall.covers(point) and line.distance(point)<1.5:candidates.add(k)
        if not candidates:raise ValueError('Shop opening lacks an unblocked exterior landing sample')
        for k in sorted(candidates):
            adjust(k,floor_top-1)
            if k not in ground:material_changes.append({'source_cell_xy':list(k),'old_default_material':'grass_block','new_material':'stone_bricks'})
            ground.setdefault(k,'stone_bricks')
        landings.append({'opening_id':opening['id'],'source_cells_xy':[list(k) for k in sorted(candidates)],'walking_top_m':floor_top,'threshold_step_blocks':0,'finished_grade_verified':False})
    return {'status':'provisional one-block entrance and exterior-ground fit','changes':list(changes.values()),'landing_material_changes':material_changes,'openings':landings,
        'maximum_cut_or_fill_blocks':max([0]+[abs(r['old_ground_block_m']-r['new_ground_block_m']) for r in changes.values()]),
        'source_finished_grades_verified':False,'survey_datum_verified':False}


def study_guide_features(model,wall_geometry,shell,terrain,edging,floor_top):
    """Carry the retained study canopy and decorative palette into the placed grid."""
    outline=np.asarray(model['outer_wall_base_outline'])[:,:2];target=np.asarray(wall_geometry.exterior.coords)[:-1]
    rotation,translation,_=ordered_rigid(outline,target);result=dict(shell);canopy=[];details=[]
    if 'projection_surfaces' not in model:raise ValueError('Retained shop study canopy required')
    surface=next(s for s in model['projection_surfaces'] if s['role']=='canopy-roof')
    vertices=np.asarray(surface['vertices']);footprint=Polygon(vertices[:,:2]@rotation+translation)
    a,b,c,d=footprint.bounds
    if (math.ceil(c)-math.floor(a))*(math.ceil(d)-math.floor(b))>128:raise ValueError('Study canopy budget exceeded')
    # The retained canopy plane slopes in its source X direction.
    gradient=(vertices[2,2]-vertices[0,2])/(vertices[2,0]-vertices[0,0])
    for x in range(math.floor(a),math.ceil(c)):
        for y in range(math.floor(b),math.ceil(d)):
            if footprint.intersection(box(x,y,x+1,y+1)).area<1e-9:continue
            local=(np.asarray([x+.5,y+.5])-translation)@rotation.T
            local_x=max(vertices[:,0].min(),min(vertices[:,0].max(),local[0]))
            height=vertices[0,2]+gradient*(local_x-vertices[0,0]);half=round(2*height)-1
            h=floor_top+half//2;p=x,h,y
            if (x,y) not in terrain:raise ValueError('Canopy leaves retained world')
            if p in result:continue
            if h<floor_top+2 or h<=terrain[x,y]:raise ValueError('Canopy obstructs two-block doorway headroom or terrain')
            if any(h==terrain[x,y]+level for level,_ in edging.get((x,y),[])):raise ValueError('Canopy conflicts with retained edging')
            result[p]='dark_oak_slab_top' if half%2 else 'dark_oak_slab'
            canopy.append({'source_xyz':list(p),'material':result[p]})
    if not canopy:raise ValueError('Retained canopy did not produce a placed sample')
    # The old study used source-illustrative posts every three metres, with
    # opened spruce panels between. Cardinal attachment is re-evaluated here.
    lines=[LineString([a,b]) for a,b in zip(target,np.roll(target,-1,axis=0))]
    door_lines=[]
    for opening in model['opening_base_segments']:
        pts=np.asarray(opening['endpoints'])[:,:2]@rotation+translation;door_lines.append(LineString(pts))
    boundary=set((x,y) for x,h,y in shell if h==floor_top and shell[x,h,y]=='spruce_planks')
    for x,y in sorted(boundary):
        q=Point(x+.5,y+.5);edge=min(range(4),key=lambda i:lines[i].distance(q));line=lines[edge]
        tangent=np.asarray(line.coords[1])-np.asarray(line.coords[0]);normal=np.array([-tangent[1],tangent[0]])
        middle=np.asarray(line.interpolate(.5,normalized=True).coords[0])
        if np.dot(normal,middle-np.asarray(wall_geometry.centroid.coords[0]))<0:normal=-normal
        dx,dy=(int(np.sign(normal[0])),0) if abs(normal[0])>=abs(normal[1]) else (0,int(np.sign(normal[1])))
        exterior=(x+dx,y+dy)
        if exterior not in terrain or wall_geometry.covers(Point(exterior[0]+.5,exterior[1]+.5)):continue
        if any(l.distance(Point(exterior[0]+.5,exterior[1]+.5))<1.25 for l in door_lines):continue
        post=int(line.project(q))%3==0
        facing=('east' if dx>0 else 'west') if dx else ('north' if dy>0 else 'south')
        for height in (range(3) if post else (1,)):
            p=(exterior[0],floor_top+height,exterior[1]);anchor=(x,floor_top+height,y)
            if result.get(anchor)!='spruce_planks' or p in result or p[1]<=terrain[exterior]:continue
            if any(p[1]==terrain[exterior]+level for level,_ in edging.get(exterior,[])):continue
            material='dark_oak_fence' if post else 'spruce_trapdoor_'+facing
            if post and (p[0],p[1]+1,p[2]) in result:continue
            result[p]=material;details.append({'source_xyz':list(p),'wall_anchor_source_xyz':list(anchor),'material':material,'source_edge':edge})
    if len(details)>256:raise ValueError('Study facade-detail budget exceeded')
    return result,{'guide':'retained Wicker Shop wall-detail/slab study','canopy_slab_blocks':len(canopy),'canopy_blocks':canopy,
        'canopy_height_choice':model['projection_review']['height_choice'],
        'canopy_NE_minus_SE_front_height_m':model['projection_review']['front_height_NE_minus_SE_metres'],
        'facade_detail_blocks':len(details),'facade_details':details,'decorative_spacing_m':3,'decoration_dimensions_source_verified':False,
        'roof_or_ground_source_geometry_modified':False,'physical_canopy_identity_verified':False}


def resolve_inferred_fences(sampled,targets,gap_policy):
    """Source wall traces supersede only the user-default inferred oak edging."""
    conflicts=set(sampled['rocks'])&set(targets)
    if not conflicts:return []
    if gap_policy.get('policy_origin')!='user_instruction' or gap_policy.get('explicit_claims_override_default') is not True:
        raise ValueError('An explicit source-over-default edging policy is required')
    if len(conflicts)>8 or any(sampled['rocks'][k]!=[(1,'oak_fence')] for k in conflicts):
        raise ValueError('Wall preview may supersede at most eight inferred oak fence columns; other edging conflicts require review')
    changes=[{'source_cell_xy':list(k),'removed_inferred_column':sampled['rocks'][k],
              'reason':'proposed architectural wall/floor display takes priority over default gap-inferred narrow-path edging; conditional preview only'} for k in sorted(conflicts)]
    for k in conflicts:del sampled['rocks'][k]
    sampled['boundary_blocks']=sum(len(v) for v in sampled['rocks'].values())
    return changes


def saved_check(path,offset,sampled,heights,structures,openings,floor_top,cancelled,landing_columns=()):
    from amulet.level.formats.leveldb_world import LevelDBFormat
    from .bedrock import material_block
    wrapper=LevelDBFormat(str(path));wrapper.open();a,b,c,d=sampled['bounds'];checked=0;cache={};door_samples=0
    try:
        for cx in range(a//16,(c-1)//16+1):
            for cy in range(b//16,(d-1)//16+1):
                if cancelled():raise CancelledError('Shell world verification cancelled')
                chunk=wrapper.load_chunk(cx,-cy-1,'minecraft:overworld')
                def check(x,h,y,name):
                    if name not in cache:cache[name]=material_block(name)
                    actual=chunk.block_palette[int(chunk.blocks[x%16,(h+offset),(-y-1)%16])];expected=cache[name]
                    if actual.namespaced_name!=expected.namespaced_name or any(actual.properties.get(k)!=v for k,v in expected.properties.items()):raise ValueError('Saved shell/surface/air state mismatch')
                for x in range(max(a,cx*16),min(c,(cx+1)*16)):
                    for y in range(max(b,cy*16),min(d,(cy+1)*16)):
                        h=heights[x,y];edging=dict(sampled['rocks'].get((x,y),[]))
                        for level in range(4):
                            name=structures.get((x,h+level,y),sampled['ground'].get((x,y),'grass_block') if level==0 else edging.get(level,'air'))
                            check(x,h+level,y,name)
                        checked+=1
                for opening in openings:
                    for x,y in opening['display_columns_xy']:
                        if x//16==cx and y//16==cy:
                            for z in range(opening['display_clearance_blocks']):check(x,floor_top+z,y,'air');door_samples+=1
                for x,y in landing_columns:
                    if x//16==cx and y//16==cy:
                        if heights[x,y]+1!=floor_top:raise ValueError('Saved landing is not at the threshold level')
                        for z in (floor_top,floor_top+1):check(x,z,y,'air')
                del chunk
    finally:wrapper.close()
    if checked!=sampled['platform_cells']:raise ValueError('Incomplete terrain/shell readback')
    return {'surface_columns_verified':checked,'surface_plus_three_levels_verified':True,'source_edging_blocks':sampled['boundary_blocks'],
        'doorway_air_samples_verified':door_samples,'level_entry_landing_columns_verified':len(landing_columns),'all_written_shell_and_bearing_blocks_verified_by_native_writer':True,
        'all_unwritten_chunk_air_verified_by_native_writer':True,'headroom_scope':'source shop opening display columns; external connections remain unverified','decoded_chunk_cache_limit':1}


def run(config,base_directory,floor_preview_directory,pdf_directory,evidence_directory,output,*,assume_plan_ffl_odn=False,cancelled=lambda:False):
    if assume_plan_ffl_odn is not True:raise ValueError('Explicit conditional FFL-as-ODN assumption required')
    if cancelled():raise CancelledError('Wall shell preview cancelled')
    output=Path(output);base_directory=Path(base_directory);floor_preview_directory=Path(floor_preview_directory)
    if output.exists():raise ValueError('Fresh wall/shell output required')
    profile=json.loads(PROFILE.read_text());base=json.loads((base_directory/'quality-report.json').read_text());prior=json.loads((floor_preview_directory/'quality-report.json').read_text())
    baseworld=base_directory/base['world']['file'];priorworld=floor_preview_directory/prior['world']['file']
    if file_hash(baseworld)!=base['world']['sha256'] or file_hash(priorworld)!=prior['world']['sha256']:raise ValueError('Pinned original worlds required')
    if base['planning_source_pins']!=prior['planning_source_pins']:raise ValueError('Original worlds use different planning sources')
    if base['implementation_sha256']!=file_hash(geo.__file__):raise ValueError('Current pinned geographic base required')
    for n in ['osm','dtm','grid']:
        if file_hash(config[n+'_path'])!=config[n+'_sha256'] or base['source_pins'][n]!=config[n+'_sha256']:raise ValueError('Geographic source pin mismatch')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='wall-shell-',dir=output.parent) as temp:
        root=Path(temp)/'result';root.mkdir()
        source_review=access.run(config,floor_preview_directory,pdf_directory,evidence_directory,root/'source-access-review',cancelled=cancelled)
        model,height_review=verify_shop_sources(pdf_directory,evidence_directory,profile)
        data=geometry_world.read_inputs(config['geometry_request']);sampled=geometry_world.rasterize(data,cancelled=cancelled)
        project=OSTN15Transform('EPSG:4326','EPSG:27700',{'method':'ostn15-bng-v1','path':config['grid_path'],'sha256':config['grid_sha256']})
        placement,_=geo.alignment(data,json.loads(Path(config['osm_path']).read_text()),project)
        if placement!=base['alignment'] or placement!=prior['alignment']:raise ValueError('Existing map correspondence changed')
        heights,terrain=geo.terrain_heights(sampled,placement['nominal_local_xy_to_bng_en_affine'],config['dtm_path'],cancelled=cancelled)
        saved={tuple(r['source_cell_xy']):r['surface_odn_block_m'] for r in json.loads((base_directory/'terrain-samples.json').read_text())}
        if heights!=saved:raise ValueError('Terrain differs from saved geographic baseline')
        original_heights=dict(heights);old_ground=dict(sampled['ground'])
        walls={r['building']:shape(r['wall_geometry_nominal_local']) for r in source_review['building_outline_role_comparisons']}
        literal_claims=audit.floor_claims(Path(pdf_directory)/(data['layout']['document_sha256']+'.pdf'),data['layout']['document_sha256'],data['buildings'],geo.profile()['source_metres_per_native_point'])
        expected={c['source_building_ids'][0]:c['printed_level_m'] for c in literal_claims if len(c['source_building_ids'])==1}
        if any(expected.get(r['source_building_id'])!=r['source_ffl_m'] for r in prior['floor_plates']):raise ValueError('Retained floor levels differ from original source annotations')
        claims=[];buildings={'records':[]}
        for row in prior['floor_plates']:
            if len(row['labels'])!=1:raise ValueError('One building label per floor claim required')
            label=row['labels'][0];identifier=row['source_building_id']
            buildings['records'].append({'id':identifier,'geometry_pdf_native':mapping(walls[label])})
            claims.append({'source_building_ids':[identifier],'printed_level_m':row['source_ffl_m'],'building_labels':[label]})
        floors,floor_report=floor.floor_cells(claims,buildings,heights,1)
        for r in floor_report:r['footprint_source_role']='proposed external wall trace, not roof envelope'
        old_floor_cells={tuple(r['source_cell_xy']) for r in json.loads((floor_preview_directory/'floor-cells.json').read_text())}
        if sorted(walls)!=['Maintenance','Shop','Station'] or len(floor_report)!=3:raise ValueError('Exactly three reviewed wall-based floor plates required')
        shop_row=next(r for r in floor_report if r['labels']==['Shop'])
        previous_shop_top=shop_row['preview_floor_top_odn_assumption_m'];shop_top=math.ceil(shop_row['source_ffl_m'])
        shop_row.update(preview_floor_top_odn_assumption_m=shop_top,quantization_error_m=shop_top-shop_row['source_ffl_m'],quantization_policy='shop walking surface rounded up to the full-block terrain surface; printed FFL datum remains conditional',prior_preview_floor_top_m=previous_shop_top)
        for r in floors.values():
            if r['labels']==['Shop']:r['base_odn_block_m']=shop_top-1
        shell,boundary,shell_report=shop_shell(model,walls['Shop'],shop_top,cancelled=cancelled)
        if len(shell)>profile['limits']['shell_blocks']:raise ValueError('Shop shell block budget exceeded')
        edging_changes=resolve_inferred_fences(sampled,set(floors)|boundary,data['gaps']['policy'])
        floor_targets={k:r['base_odn_block_m'] for k,r in floors.items()}
        for k in boundary:
            if k in floor_targets and floor_targets[k]!=shop_top-1:raise ValueError('Shop boundary conflicts with another floor')
            floor_targets[k]=shop_top-1
        path=audit.walkable_cells(sampled)-set(floor_targets)
        before=audit.path_steps(path,heights,placement['nominal_local_xy_to_bng_en_affine']);grading=floor.grade_paths(path,heights,cancelled=cancelled)
        heights.update(grading);heights.update(floor_targets)
        for k in floor_targets:sampled['ground'].setdefault(k,'stone_bricks')
        approach_report=fit_shop_approaches(walls['Shop'],shell_report['openings'],heights,floor_targets,sampled['ground'],sampled['rocks'],sampled['plan_markers'],shop_top)
        approach_cells={tuple(k) for r in approach_report['openings'] for k in r['source_cells_xy']}
        path|=approach_cells
        shell,guide_report=study_guide_features(model,walls['Shop'],shell,heights,sampled['rocks'],shop_top)
        if len(shell)>profile['limits']['shell_blocks']:raise ValueError('Study-guided shop exceeds block budget')
        structures={};bearing_blocks=0
        for (x,y),h in floor_targets.items():
            for z in range(original_heights[x,y]+1,h):structures[x,z,y]='stone_bricks';bearing_blocks+=1
        if bearing_blocks>profile['limits']['bearing_blocks']:raise ValueError('Bearing fill budget exceeded')
        for k,v in shell.items():
            x,h,y=k
            if (x,y) not in heights:raise ValueError('Shop shell leaves retained world bounds')
            if h<=heights[x,y]:raise ValueError('Shop shell intersects current ground')
            if any(h==heights[x,y]+level for level,_ in sampled['rocks'].get((x,y),[])):raise ValueError('Shop shell intersects source edging')
            structures[k]=v
        for opening in shell_report['openings']:
            for x,y in opening['display_columns_xy']:
                if heights[x,y]!=shop_top-1:raise ValueError('Opening lacks level floor/bearing support')
        after=audit.path_steps(path,heights,placement['nominal_local_xy_to_bng_en_affine'])
        if after['multi_block_step_pairs']:raise ValueError('Path grading retains a multi-block step')
        combined=audit.path_steps(path|set(floors),heights,placement['nominal_local_xy_to_bng_en_affine'])
        perimeter=[r for r in combined['hotspots'] if sum(tuple(k) in floors for k in r['source_cells_xy'])==1]
        spawn=sampled['retained_spawn_local_xyz_m'];spawn_key=math.floor(spawn[0]),math.floor(spawn[2])-1
        report={'version':'conditional-wall-based-floor-and-ground-fitted-shop-v4','status':'conditional_source_height_shop_shell','voxel_size_m':1,'model_blocks_per_source_metre':1,'crs':'EPSG:27700','vertical_datum':'ODN',
            'spawn_local_xyz_m':[spawn[0],heights[spawn_key]+1,spawn[2]],'alignment':placement,'horizontal_transform':base['horizontal_transform'],
            'source_terrain':terrain,'source_floor_datum_verified':False,'datum_assumption':'Printed FFL assumed ODN only for this isolated study; same whole-block floor quantization as prior preview.',
            'floor_cells':len(floors),'floor_plates':floor_report,'source_landscape_pdf_sha256':data['layout']['document_sha256'],
            'prior_roof_plate_cells_removed':len(old_floor_cells-set(floors)),'wall_trace_cells_outside_prior_roof_plates':len(set(floors)-old_floor_cells),'shop_boundary_bearing_columns':len(boundary),'additional_boundary_bearing_columns':len(boundary-set(floors)),
            'inferred_fence_columns_superseded':edging_changes,'remaining_source_edging_blocks':sampled['boundary_blocks'],
            'provisional_bearing_fill_blocks':bearing_blocks,'foundation_design_verified':False,'source_shop_height_replay':height_review,'shop_shell':shell_report,'shop_study_guide':guide_report,'shop_ground_fit':approach_report,'shop_floor_lift_from_prior_preview_blocks':shop_top-previous_shop_top,
            'conditional_shell_buildings':1,'reconstructed_as_built_buildings':0,'station_and_maintenance_shells_added':False,'maintenance_sloping_floor_reconstructed':False,
            'path_cells_changed':len(grading),'path_steps_before':before,'path_steps_after':after,'floor_perimeter_multi_block_steps':perimeter,'floor_perimeter_multi_block_step_pairs':len(perimeter),
            'building_access_verified':False,'production_placement_eligible':False,'physical_registration_verified':False,'training_labels_generated':0,'minecraft_import_tested':False,
            'original_ground_feature_materials_preserved':len(old_ground),'original_plan_marking_cells_preserved':len(sampled['plan_markers']),
            'baseline_geographic_world_sha256':base['world']['sha256'],'prior_floor_preview_sha256':prior['world']['sha256'],'original_worlds_unchanged':True,
            'geographic_implementation_sha256':file_hash(geo.__file__),'floor_implementation_sha256':file_hash(floor.__file__),'access_implementation_sha256':file_hash(access.__file__),
            'implementation_sha256':file_hash(__file__),'profile_sha256':file_hash(PROFILE),'review_input_sha256':profile['review_input_sha256'],'source_pins':base['source_pins'],
            'planning_source_pins':prior['planning_source_pins'],'sources':base['sources'],'palette_is_illustrative':True,'limitations':profile['limitations']}
        voxel=root/'voxels.jsonl';a,b,c,d=sampled['bounds']
        with voxel.open('w') as stream:
            for x in range(a,c):
                if cancelled():raise CancelledError('Wall shell export cancelled')
                for y in range(b,d):
                    stream.write(json.dumps({'x':x,'y':heights[x,y],'z':y+1,'kind':'terrain','material':sampled['ground'].get((x,y),'grass_block')})+'\n')
                    for level,material in sampled['rocks'].get((x,y),[]):stream.write(json.dumps({'x':x,'y':heights[x,y]+level,'z':y+1,'kind':'structure','material':material})+'\n')
            for (x,h,y),material in sorted(structures.items()):stream.write(json.dumps({'x':x,'y':h,'z':y+1,'kind':'structure','material':material})+'\n')
        from . import bedrock
        from .planning_world_preview import _spawn_check,_verify_archive
        def check(path,offset,native_spawn):
            report['spawn_validation']=_spawn_check(path,native_spawn)
            report['saved_geometry_validation']=saved_check(path,offset,sampled,heights,structures,shell_report['openings'],shop_top,cancelled,landing_columns=approach_cells)
            atomic_json(path/'planning-geographic-alignment.json',{**placement,'minecraft_cell_centre_to_source_xy':'[Minecraft X + 0.5, -(Minecraft Z + 0.5)]','vertical_offset_blocks':offset})
            atomic_json(path/'CONDITIONAL-WALL-SHELL-ASSUMPTIONS.json',{k:report[k] for k in ['datum_assumption','source_floor_datum_verified','building_access_verified','limitations','conditional_shell_buildings']})
        world=bedrock.export_world(voxel,root,report,name='Wicker SHOP GROUND FIX - study guided slab roof',max_blocks=profile['limits']['world_blocks'],ground_depth=3,foundation_mode='chunk',post_export_check=check)
        report['world']=world;report['archive_validation']=_verify_archive(root/world['file'],root/'bedrock-world',world,cancelled)
        shutil.move(root/world['file'],root/'wicker-wall-based-floors-and-shop-shell.mcworld');report['world']['file']='wicker-wall-based-floors-and-shop-shell.mcworld';shutil.rmtree(root/'bedrock-world')
        atomic_json(root/'floor-cells.json',[{'source_cell_xy':list(k),'original_terrain_block_odn_m':original_heights[k],**r} for k,r in sorted(floors.items())])
        atomic_json(root/'shell-blocks.json',[{'source_xyz':[x,h,y],'material':v} for (x,h,y),v in sorted(shell.items())])
        atomic_json(root/'path-grading-changes.json',[{'source_cell_xy':list(k),'original_block_m':original_heights[k],'proposed_block_m':v} for k,v in sorted(grading.items())])
        floor._plan_overview(root,sampled,floors,grading);_preview(root,voxel,shop_top)
        if file_hash(baseworld)!=base['world']['sha256'] or file_hash(priorworld)!=prior['world']['sha256']:raise ValueError('Original world changed')
        verify_shop_sources(pdf_directory,evidence_directory,profile);geometry_world.read_inputs(config['geometry_request'])
        for n in ['osm','dtm','grid']:
            if file_hash(config[n+'_path'])!=config[n+'_sha256']:raise ValueError('Geographic source changed during export')
        atomic_json(root/'quality-report.json',report)
        (root/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Conditional wall-based floors and shop shell</title><h1>Wall-based floors and one conditional shop shell</h1><p><a href="wicker-wall-based-floors-and-shop-shell.mcworld">Download world</a>. All three floor footprints follow proposed external wall traces. The shop includes a slab roof, retained-study canopy and illustrative timber facade details. Floor datum, bearing fills, voxel closure and materials remain conditional; access connections are unresolved.</p><img style="max-width:100%" src="building-shell-preview.png"><p><a href="quality-report.json">Validation and assumptions</a></p>')
        shutil.move(root,output)
    return report


def _preview(root,voxel,floor_top):
    from PIL import Image,ImageDraw,ImageColor
    from .rock_world_render import colour
    rows=[json.loads(line) for line in voxel.read_text().splitlines()]
    rows=[r for r in rows if 65<=r['x']<=140 and 95<=r['z']-1<=151]
    occupied={(r['x'],r['z']-1,r['y']):r['material'] for r in rows}
    def project(p):
        x,y,h=p;return ((x-y)*9,(x+y)*4.5-(h-floor_top)*11)
    all_points=[project((x+dx,y+dy,h+dh)) for x,y,h in occupied for dx,dy,dh in [(0,0,0),(1,1,1)]]
    xmin=min(p[0] for p in all_points);ymin=min(p[1] for p in all_points)
    width=math.ceil(max(p[0] for p in all_points)-xmin)+90;height=math.ceil(max(p[1] for p in all_points)-ymin)+145
    image=Image.new('RGB',(width,height),'#f9f7ee');draw=ImageDraw.Draw(image);faces=[]
    palette={'spruce_planks':'#8b6747','dark_oak_planks':'#493520','dark_oak_slab':'#493520','dark_oak_slab_top':'#493520','grass_block':'#83a65c','stone_bricks':'#9c9e9a'}
    from .rock_world_render import _boxes
    for (x,y,h),material in occupied.items():
        paint='#46321f' if material=='dark_oak_fence' else '#9b7953' if material.startswith('spruce_trapdoor_') else palette.get(material,colour(material))
        rgb=ImageColor.getrgb(paint)
        if material=='dark_oak_slab_top':bounds=[(0,.5,0,1,1,1)]
        elif material.startswith('spruce_trapdoor_'):
            direction=material.removeprefix('spruce_trapdoor_');t=3/16
            bounds=[{'north':(0,0,0,1,1,t),'south':(0,0,1-t,1,1,1),'east':(0,0,0,t,1,1),'west':(1-t,0,0,1,1,1)}[direction]]
        else:
            neighbours=[(dx,dy) for dx,dy in [(1,0),(-1,0),(0,1),(0,-1)] if occupied.get((x+dx,y+dy,h)) in ['oak_fence','dark_oak_fence']]
            bounds=_boxes('oak_fence' if material=='dark_oak_fence' else material,neighbours)
        for x0,h0,y0,x1,h1,y1 in bounds:
            corners=[(x+x0,y+y0,h+h0),(x+x1,y+y0,h+h0),(x+x1,y+y1,h+h0),(x+x0,y+y1,h+h0),
                     (x+x0,y+y0,h+h1),(x+x1,y+y0,h+h1),(x+x1,y+y1,h+h1),(x+x0,y+y1,h+h1)]
            for neighbour,indices,shade in [((x+1,y,h),[1,2,6,5],.75),((x,y+1,h),[2,3,7,6],.58),((x,y,h+1),[4,5,6,7],1)]:
                if bounds==[(0,0,0,1,1,1)] and neighbour in occupied:
                    other=occupied[neighbour]
                    if _boxes(other)==[(0,0,0,1,1,1)] and not other.startswith('spruce_trapdoor_') and other!='dark_oak_fence' and not other.endswith('_slab_top'):continue
                vertices=[corners[i] for i in indices];depth=sum(a+b+.82*c for a,b,c in vertices)/4
                points=[(project(v)[0]-xmin+40,project(v)[1]-ymin+82) for v in vertices]
                faces.append((depth,points,tuple(round(v*shade) for v in rgb)))
    for _,points,rgb in sorted(faces,key=lambda f:f[0]):draw.polygon(points,fill=rgb,outline=tuple(max(0,v-12) for v in rgb))
    draw.text((20,14),'ACTUAL GENERATED BLOCKS: SLAB ROOF shop shell and wall-based floor studies',fill='black')
    draw.text((20,34),'Illustrative timber palette; floor datum and access unresolved. Station / maintenance shells omitted.',fill='black')
    draw.text((20,height-28),'Isometric voxel preview in plan XY (Minecraft Z is reflected). Study canopy / facade details included; interiors and bunding omitted.',fill='black')
    image.save(root/'building-shell-preview.png')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['config','base-directory','floor-preview-directory','pdf-directory','evidence-directory','output']:parser.add_argument('--'+name,required=True)
    parser.add_argument('--assume-plan-ffl-odn',action='store_true');args=parser.parse_args(argv);p=Path(args.config).resolve()
    if p.stat().st_size>32768:raise ValueError('Bounded request required')
    config=json.loads(p.read_text())
    for n in ['osm','dtm','grid']:config[n+'_path']=str((p.parent/config[n+'_path']).resolve())
    for n in ['layout','paving','gaps','buildings','markings','expansion']:config['geometry_request'][n+'_path']=str((p.parent/config['geometry_request'][n+'_path']).resolve())
    r=run(config,args.base_directory,args.floor_preview_directory,args.pdf_directory,args.evidence_directory,args.output,assume_plan_ffl_odn=args.assume_plan_ffl_odn)
    print(json.dumps({'floor_cells':r['floor_cells'],'shell_buildings':r['conditional_shell_buildings'],'world_sha256':r['world']['sha256']}))


if __name__=='__main__':main()
