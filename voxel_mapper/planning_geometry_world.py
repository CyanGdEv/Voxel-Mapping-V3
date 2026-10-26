"""Explorable prototype from current paving and user-styled rock boundaries."""
from collections import Counter
from concurrent.futures import CancelledError
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile
import time

from shapely.geometry import Point,LineString,shape,box
from shapely.affinity import affine_transform
from shapely.ops import unary_union,nearest_points

from . import planning_area_layout,planning_hatch_regions,planning_gap_boundaries,paving_palette
from .building_spec import digest
from .generation_cycles import atomic_json

VERSION='planning-geometry-world-preview-v1'
STYLE_PATH=Path(__file__).with_name('data')/'rock-boundary-reference.json'
LIMITS={'max_platform_cells':65536,'max_span_m':512,'max_world_writes':300000,
        'max_width_checks':20000,'max_marking_steps':1000000,'max_sampling_checks':2000000,'max_points':200000,'max_boundary_cells':20000}


def file_hash(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def style():
    value=json.loads(STYLE_PATH.read_text())
    if (value.get('version')!='user-rock-reference-v1' or value.get('origin')!='user_reference_image'
            or value.get('full_blocks')!=['stone','stone_bricks','cobblestone']
            or value.get('slabs')!=['stone_slab','stone_brick_slab']
            or value.get('stairs')!=['stone_brick_stairs'] or value.get('posts')!=['cobblestone_wall']
            or value.get('minimum_height_blocks')!=.5 or value.get('maximum_height_blocks')!=2
            or value.get('gap_side_centre_distance_m')!=.85 or value.get('source_measurement') is not False
            or value.get('narrow_path_width_blocks')!=4 or value.get('narrow_path_boundary')!='oak_fence'
            or value.get('narrow_path_rule_origin')!='user_instruction' or value.get('max_fence_connector_distance_m')!=1.5):
        raise ValueError('Supported user rock reference preset required')
    return value


def validate(config):
    keys={'version','layout_path','layout_sha256','paving_path','paving_sha256','gaps_path','gaps_sha256'}
    optional={'buildings_path','buildings_sha256','markings_path','markings_sha256'}
    if (not isinstance(config,dict) or not keys<=set(config) or set(config)-keys-optional or config.get('version')!=VERSION
            or any((n+'_path' in config)!=(n+'_sha256' in config) for n in ('buildings','markings'))):
        raise ValueError('Pinned current geometry world request required')
    import re
    for name in tuple(n for n in ('layout','paving','gaps','buildings','markings') if n+'_path' in config):
        if (not isinstance(config[name+'_path'],str) or not 1<=len(config[name+'_path'])<=4096
                or not re.fullmatch('[a-f0-9]{64}',str(config[name+'_sha256']))):raise ValueError('Bounded pinned geometry input required')
    return config


def read_inputs(config):
    validate(config);data={}
    for name in tuple(n for n in ('layout','paving','gaps','buildings','markings') if n+'_path' in config):
        path=Path(config[name+'_path'])
        if not path.is_file() or path.stat().st_size>16000000:
            raise ValueError('Pinned '+name+' geometry missing or changed')
        raw=path.read_bytes()
        if len(raw)>16000000 or hashlib.sha256(raw).hexdigest()!=config[name+'_sha256']:
            raise ValueError('Pinned '+name+' geometry missing or changed')
        def invalid(value):raise ValueError('Finite geometry input required')
        data[name]=json.loads(raw.decode('utf-8'),parse_constant=invalid)
    layout,paving,gaps=(data[n] for n in ('layout','paving','gaps'))
    planning_area_layout.validate_layout(layout)
    if (not layout.get('analysis_complete') or not layout.get('shared_frame')
            or paving.get('version')!=planning_hatch_regions.VERSION or not paving.get('analysis_complete')
            or gaps.get('version')!=planning_gap_boundaries.VERSION or not gaps.get('analysis_complete')
            or any(x.get('document_sha256')!=layout['document_sha256'] or x.get('page')!=layout['page'] for x in (paving,gaps))):
        raise ValueError('Complete current geometry in one source page required')
    overrides={r['id']:r['explicit_override'] for r in gaps['records'] if r.get('explicit_override')}
    expected=planning_gap_boundaries.review(paving,layout,source_claims=gaps.get('source_building_claims',[]),overrides=overrides)
    if (not expected['analysis_complete'] or expected['records']!=gaps['records']
            or expected['source_paving_review_sha256']!=gaps.get('source_paving_review_sha256')
            or expected['source_layout_sha256']!=gaps.get('source_layout_sha256')
            or expected['policy_sha256']!=gaps.get('policy_sha256')):
        raise ValueError('Current source-derived gap boundaries and saved policy required')
    if 'buildings' in data:
        from .planning_building_boundaries import review
        expected=review(paving,layout,source_claims=gaps.get('source_building_claims',[]))
        if not expected['analysis_complete'] or data['buildings']!=expected:
            raise ValueError('Current source-derived building boundaries required')
    if 'markings' in data:
        from .planning_plan_markings import validate_review
        validate_review(data['markings'],layout['document_sha256'],layout['page'])
    return data


def rock_column(x,z,facing):
    """Deterministic 0.5–2 block silhouette selected from the user's sample."""
    grain=((x*73856093)^(z*19349663))&0xffffffff
    full=('stone','stone_bricks','cobblestone')[(grain//101)%3]
    choice=grain%100
    if choice<25:return [(1,('stone_slab','stone_brick_slab')[(grain//7)%2])]
    if choice<45:return [(1,'stone_brick_stairs_'+facing+('_top' if (grain//11)%4==0 else ''))]
    if choice<52:return [(1,'cobblestone_wall')]
    if choice<83:return [(1,full)]
    return [(1,full),(2,('stone_slab','stone_brick_slab')[(grain//7)%2] if choice<95 else ('stone','cobblestone')[(grain//13)%2])]



def local_path_width(paving,inside_gap,boundary_point,gap=None):
    """First continuous paving cross-section along a gap's outward normal."""
    directions=[];px,py=boundary_point.x,boundary_point.y
    if gap is not None:
        coordinates=list(gap.exterior.coords);best=float('inf');edges=[]
        for a,b in zip(coordinates,coordinates[1:]):
            dx=b[0]-a[0];dy=b[1]-a[1];square=dx*dx+dy*dy
            if square==0:continue
            t=max(0.,min(1.,((px-a[0])*dx+(py-a[1])*dy)/square))
            distance=(px-a[0]-t*dx)**2+(py-a[1]-t*dy)**2
            if distance<best-1e-12:best=distance;edges=[(dx,dy)]
            elif abs(distance-best)<=1e-12:edges.append((dx,dy))
        for dx,dy in edges:
            length=math.hypot(dx,dy)
            for nx,ny in ((-dy/length,dx/length),(dy/length,-dx/length)):
                if paving.covers(Point(px+nx*1e-5,py+ny*1e-5)):directions.append((nx,ny))
    if not directions:
        dx=px-inside_gap.x;dy=py-inside_gap.y;length=math.hypot(dx,dy)
        if length<1e-8:return None
        directions=[(dx/length,dy/length)]
    widths=[]
    for dx,dy in directions:
        ray=LineString([(px-dx*1e-7,py-dy*1e-7),
                        (px+dx*1024,py+dy*1024)])
        cut=paving.intersection(ray);parts=list(cut.geoms) if hasattr(cut,'geoms') else [cut]
        for part in parts:
            if part.geom_type!='LineString' or part.length==0:continue
            ts=[(p[0]-px)*dx+(p[1]-py)*dy for p in part.coords]
            low,high=min(ts),max(ts)
            if low<=1e-6 and high>1e-6:widths.append(4. if abs(high-4.)<1e-6 else high)
    return min(widths) if widths else None


def rasterize(data,*,cancelled=lambda:False,limits=None):
    caps={**LIMITS,**(limits or {})}
    if any(k not in LIMITS or type(v) is not int or not 1<=v<=LIMITS[k] for k,v in caps.items()):raise ValueError('Lower-only geometry world limits required')
    def check():
        if cancelled():raise CancelledError('Geometry world generation cancelled')
    layout,paving,gaps=(data[n] for n in ('layout','paving','gaps'));preset=style()
    affine=layout['shared_frame']['native_to_nominal_local_affine']
    if len(affine)!=6 or not all(math.isfinite(v) for v in affine):raise ValueError('Nominal source transform required')
    points=checks=0
    def transform(value):
        nonlocal points
        g=shape(value)
        if g.is_empty or not g.is_valid or g.has_z:raise ValueError('Valid current source geometry required')
        def count(v):
            if v.geom_type=='Polygon':return len(v.exterior.coords)+sum(len(r.coords) for r in v.interiors)
            if hasattr(v,'geoms'):return sum(count(p) for p in v.geoms)
            return len(v.coords)
        points+=count(g)
        if points>caps['max_points']:raise ValueError('Geometry point budget exceeded')
        return affine_transform(g,affine)
    finishes=[(transform(r['geometry_pdf_native']),r['surface']) for r in layout['candidates'] if r['role']=='surface' and r.get('surface')]
    marker_rows=data['buildings']['records'] if 'buildings' in data else [r for r in layout['candidates'] if r['role']=='building']
    buildings=[transform(r['geometry_pdf_native']) for r in marker_rows]
    # Explicit labelled white building fills protect rock placement, without
    # inventing additional building heights or turning text masks into builds.
    for claim in gaps.get('source_building_claims',[]):
        label=shape(claim['label_geometry_pdf_native'])
        for row in paving['records']:
            if (row.get('paint_kind')=='solid' and row.get('fill_opacity')==1
                    and row.get('solid_colour_components') in ([1.,1.,1.],[1.])
                    and shape(row['geometry']).covers(label)):
                g=transform(row['geometry'])
                if not any(g.equals(b) for b in buildings):buildings.append(g)
    paths=[]
    for row in paving['records']:
        if not row.get('legend_claim'):continue
        g=transform(row['geometry']);materials=[m for f,m in finishes if g.covers(f)]
        surface=paving_palette.polygon_surface(materials)
        if surface is None:raise ValueError('Conflicting explicit paving finishes')
        paths.append((row['id'],g,surface,bool(materials),row['legend_claim']['printed_state']))
    if not paths:raise ValueError('Current paving geometry required')
    a=math.floor(min(g.bounds[0] for _,g,_,_,_ in paths))-4;b=math.floor(min(g.bounds[1] for _,g,_,_,_ in paths))-4
    c=math.ceil(max(g.bounds[2] for _,g,_,_,_ in paths))+4;d=math.ceil(max(g.bounds[3] for _,g,_,_,_ in paths))+4
    for g in buildings:
        a=min(a,math.floor(g.bounds[0])-4);b=min(b,math.floor(g.bounds[1])-4);c=max(c,math.ceil(g.bounds[2])+4);d=max(d,math.ceil(g.bounds[3])+4)
    platform=(c-a)*(d-b)
    if platform>caps['max_platform_cells'] or max(c-a,d-b)>caps['max_span_m']:raise ValueError('Complete geometry platform budget exceeded')
    ground={};ranks={};owners={};candidate_counts={identifier:0 for identifier,_,_,_,_ in paths}
    def cells(g):
        nonlocal checks
        x0,z0,x1,z1=g.bounds
        work=(math.ceil(x1)-math.floor(x0))*(math.ceil(z1)-math.floor(z0));checks+=work
        if checks>caps['max_sampling_checks']:raise ValueError('Geometry sampling budget exceeded')
        for x in range(math.floor(x0),math.ceil(x1)):
            check()
            for z in range(math.floor(z0),math.ceil(z1)):yield x,z,Point(x+.5,z+.5)
    for identifier,g,surface,explicit,state in paths:
        for x,z,q in cells(g):
            if not g.covers(q):continue
            key=(x,z);rank=(int(explicit),int(state=='new'));material=paving_palette.palette_block(surface,x,z)
            if key in ranks and rank==ranks[key] and ground[key]!=material:raise ValueError('Equal-authority paving material conflict')
            if key not in ranks or rank>ranks[key]:ground[key]=material;ranks[key]=rank
            owners.setdefault(key,set()).add(identifier);candidate_counts[identifier]+=1
    paving_cells=set(ground);markers=set()
    # A supplied building review marks boundaries only and preserves all paving.
    building_marker_counts={}
    for row in marker_rows:
        g=affine_transform(shape(row['geometry_pdf_native']),affine);count=0
        for x,z,q in cells(g):
            if not g.covers(q):continue
            if 'buildings' in data and (g.boundary.distance(q)>.85 or (x,z) in paving_cells):continue
            ground[(x,z)]='light_blue_concrete' if 'buildings' in data else 'yellow_concrete'
            markers.add((x,z));paving_cells.discard((x,z));count+=1
        building_marker_counts[row['id']]=count
    rocks={};boundary_counts={};protected=unary_union(buildings);paving_union=unary_union([g for _,g,_,_,_ in paths]);widths={};width_checks=0;cell_owners={};gap_sources={}
    for row in gaps['records']:
        check()
        if not row.get('is_boundary') or row['boundary_kind']!='rock':continue
        value=row.get('assumed_rock_geometry_pdf_native') if row['assumed'] else row['boundary_geometry_pdf_native']
        if not value:continue
        line=transform(value);island=transform(row['gap_geometry_pdf_native']);count=0
        gap_sources[row['id']]=(line,island)
        envelope=line.buffer(preset['gap_side_centre_distance_m']).intersection(island)
        for x,z,q in cells(envelope):
            if (x,z) in paving_cells or (x,z) in markers or not island.covers(q) or protected.covers(q):continue
            if line.distance(q)>preset['gap_side_centre_distance_m']:continue
            nearest=nearest_points(q,line)[1];dx=nearest.x-q.x;dz=-(nearest.y-q.y)
            facing=('east' if dx>=0 else 'west') if abs(dx)>=abs(dz) else ('south' if dz>=0 else 'north')
            width_checks+=1
            if width_checks>caps['max_width_checks']:raise ValueError('Boundary width probe budget exceeded')
            width=local_path_width(paving_union,q,nearest,island);widths[(x,z)]=width
            column=[(1,'oak_fence')] if width is not None and width<4 else rock_column(x,z,facing)
            if (x,z) in rocks and rocks[(x,z)]!=column:raise ValueError('Conflicting rock profiles at one cell')
            rocks[(x,z)]=column;cell_owners.setdefault((x,z),set()).add(row['id']);count+=1
            if len(rocks)>caps['max_boundary_cells']:raise ValueError('Boundary cell budget exceeded')
        boundary_counts[row['id']]=count
    # Four-neighbour oak connections need grass-side stair steps at diagonals.
    fence_cells=sorted(key for key,column in rocks.items() if column==[(1,'oak_fence')])
    connectors=0;unresolved_diagonals=0
    def linked(key):
        column=rocks.get(key,[])
        return bool(column) and column[0][1] in ('oak_fence','stone','stone_bricks','cobblestone')
    for x,z in fence_cells:
        for dx,dz in ((1,1),(1,-1)):
            other=(x+dx,z+dz)
            if rocks.get(other)!=[(1,'oak_fence')]:continue
            bridges=((x+dx,z),(x,z+dz))
            if any(linked(key) for key in bridges):continue
            common=cell_owners[(x,z)]&cell_owners[other];choices=[]
            for key in bridges:
                if key in rocks or key in paving_cells or key in markers:continue
                q=Point(key[0]+.5,key[1]+.5)
                if protected.covers(q):continue
                for identifier in sorted(common):
                    line,island=gap_sources[identifier]
                    distance=line.distance(q)
                    if not island.covers(q) or distance>preset['max_fence_connector_distance_m']:continue
                    check();width_checks+=1
                    if width_checks>caps['max_width_checks']:raise ValueError('Boundary width probe budget exceeded')
                    width=local_path_width(paving_union,q,nearest_points(q,line)[1],island)
                    if width is not None and width<4:choices.append((distance,key,identifier,width))
            if choices:
                _,key,identifier,width=min(choices);rocks[key]=[(1,'oak_fence')];widths[key]=width
                cell_owners[key]={identifier};boundary_counts[identifier]+=1;connectors+=1
                if len(rocks)>caps['max_boundary_cells']:raise ValueError('Boundary cell budget exceeded')
            else:unresolved_diagonals+=1
    plan_markers={};plan_marking_report=None
    if 'markings' in data:
        from .planning_plan_markings import rasterize as rasterize_markings
        plan_markers,plan_marking_report=rasterize_markings(data['markings'],transform,[a,b,c,d],
            cancelled=cancelled,max_steps=caps['max_marking_steps'],max_cells=caps['max_boundary_cells'])
        plan_marking_report.update(paving_cells_covered_by_markings=len(set(plan_markers)&paving_cells),
            building_marker_cells_covered=len(set(plan_markers)&markers),
            assumed_edging_columns_replaced=len(set(plan_markers)&set(rocks)))
        for key,record in plan_markers.items():
            ground[key]=record['material']
            if key in rocks:
                del rocks[key];widths.pop(key,None)
                for identifier in cell_owners.get(key,[]):boundary_counts[identifier]-=1
    if set(rocks)&(paving_cells|markers):raise ValueError('Rock cells obstruct sampled paving or building markers')
    rock_blocks=sum(len(v) for v in rocks.values());attempts=4*platform+len(ground)+rock_blocks
    if attempts>caps['max_world_writes']:raise ValueError('Geometry world native write budget exceeded')
    check()
    return {'bounds':[a,b,c,d],'platform_cells':platform,'ground':ground,'paving':paving_cells,'markers':markers,
        'rocks':rocks,'rock_blocks':sum(sum(m!='oak_fence' for _,m in col) for col in rocks.values()),
        'boundary_blocks':rock_blocks,'widths':widths,'width_checks':width_checks,
        'plan_markers':plan_markers,'plan_marking_report':plan_marking_report,
        'building_marker_counts':building_marker_counts,'building_marker_mode':'2d_boundary_only' if 'buildings' in data else 'filled_footprint',
        'fence_grid_connectors':connectors,'unresolved_fence_diagonals':unresolved_diagonals,'native_write_attempts':attempts,'sampling_checks':checks,'source_points':points,
        'paving_region_cells':candidate_counts,'boundary_cells':boundary_counts,'limits':caps,'style':preset}


def _saved_check(path,offset,sampled,cancelled):
    from amulet.level.formats.leveldb_world import LevelDBFormat
    from .bedrock import material_block
    wrapper=LevelDBFormat(str(path));wrapper.open();a,b,c,d=sampled['bounds'];checked=0;rock_count=0
    cache={}
    def expected(material):
        if material not in cache:cache[material]=material_block(material)
        return cache[material]
    try:
        for cx in range(a//16,(c-1)//16+1):
            for depth_chunk in range(b//16,(d-1)//16+1):
                if cancelled():raise CancelledError('Saved geometry world check cancelled')
                chunk=wrapper.load_chunk(cx,-depth_chunk-1,'minecraft:overworld')
                for x in range(max(a,cx*16),min(c,(cx+1)*16)):
                    for depth in range(max(b,depth_chunk*16),min(d,(depth_chunk+1)*16)):
                        z=-depth-1;column=dict(sampled['rocks'].get((x,depth),[]))
                        for y in range(4):
                            material=sampled['ground'].get((x,depth),'grass_block') if y==0 else column.get(y,'air')
                            actual=chunk.block_palette[int(chunk.blocks[x%16,offset+y,z%16])];wanted=expected(material)
                            if actual.namespaced_name!=wanted.namespaced_name or any(actual.properties.get(k)!=v for k,v in wanted.properties.items()):
                                raise ValueError('Saved geometry world surface/profile mismatch')
                            if y in column:rock_count+=1
                        checked+=1
                del chunk
    finally:wrapper.close()
    if checked!=sampled['platform_cells'] or rock_count!=sampled['boundary_blocks']:raise ValueError('Incomplete saved geometry coverage')
    return {'complete_platform_verified':True,'saved_boundary_blocks_verified':rock_count,'saved_rock_blocks_verified':sampled['rock_blocks'],
        'saved_fence_blocks_verified':sum(col==[(1,'oak_fence')] for col in sampled['rocks'].values()),'paving_headroom_verified':True,
        'native_block_states_verified':True,'decoded_chunk_cache_limit':1,'platform_cells_verified':checked}


def run(config,output,*,cancelled=lambda:False,progress=lambda value:None):
    output=Path(output)
    if output.exists():raise ValueError('Fresh geometry world output required')
    started=time.monotonic();data=read_inputs(config);sampled=rasterize(data,cancelled=cancelled)
    from . import bedrock
    from .planning_world_preview import _spawn_check,_verify_archive
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='geometry-world-',dir=output.parent) as temporary:
        root=Path(temporary)/'result';root.mkdir();voxel=root/'voxels.jsonl';a,b,c,d=sampled['bounds']
        with voxel.open('w') as stream:
            for x in range(a,c):
                if cancelled():raise CancelledError('Geometry world generation cancelled')
                for depth in range(b,d):
                    records=[{'x':x,'y':0,'z':depth+1,'kind':'terrain','material':'grass_block'}]
                    if (x,depth) in sampled['ground']:records.append({'x':x,'y':0,'z':depth+1,'kind':'path','material':sampled['ground'][(x,depth)]})
                    records.extend({'x':x,'y':y,'z':depth+1,'kind':'structure','material':m} for y,m in sampled['rocks'].get((x,depth),[]))
                    for record in records:stream.write(json.dumps(record,sort_keys=True)+'\n')
        report={'version':VERSION,'status':'current_geometry_prototype_exported','voxel_size_m':1,'model_blocks_per_source_metre':1,
            'crs':None,'vertical_datum':'STUDY_ZERO','geographic_registration':None,
            'horizontal_transform':{'minecraft_x':'nominal source-local X','minecraft_z':'negative nominal source-local Y'},
            'spawn_local_xyz_m':[a+1,1,b+2],'source_document_sha256':data['paving']['document_sha256'],'source_page':data['paving']['page'],
            'source_pins':{n:config[n+'_sha256'] for n in data},'rock_style':sampled['style'],
            'rock_style_sha256':digest(sampled['style']),'platform_bounds_source_local_xy':sampled['bounds'],
            'platform_cells':sampled['platform_cells'],'native_write_attempts':sampled['native_write_attempts'],
            'plan_markings':sampled['plan_marking_report'],
            'paving_display_cells':len(sampled['paving']-set(sampled['plan_markers'])),
            'plan_marking_cells':len(sampled['plan_markers']),
            'paving_cells':len(sampled['paving']),'building_marker_cells':len(sampled['markers']),
            'building_boundary_candidates':len(sampled['building_marker_counts']),'building_boundary_marker_cells':sampled['building_marker_counts'],
            'building_marker_mode':sampled['building_marker_mode'],
            'boundary_columns':len(sampled['rocks']),'rock_columns':sum(col!=[(1,'oak_fence')] for col in sampled['rocks'].values()),
            'fence_columns':sum(col==[(1,'oak_fence')] for col in sampled['rocks'].values()),
            'rock_blocks':sampled['rock_blocks'],'boundary_blocks':sampled['boundary_blocks'],
            'narrow_path_width_rule':{'threshold_blocks':4,'strictly_less_than':True,'material':'oak_fence',
                'basis':'first continuous source paving cross-section at boundary; one block per nominal metre'},
            'fence_grid_connectors':sampled['fence_grid_connectors'],'unresolved_fence_diagonals':sampled['unresolved_fence_diagonals'],
            'width_probes':sampled['width_checks'],'unresolved_width_cells':sum(v is None for v in sampled['widths'].values()),
            'unresolved_width_policy':'retain the saved rock boundary default',
            'boundary_material_counts':dict(Counter(m for column in sampled['rocks'].values() for _,m in column)),
            'paving_region_display_cells':sampled['paving_region_cells'],'boundary_display_cells':sampled['boundary_cells'],
            'submetre_paving_regions_not_sampled':[k for k,v in sampled['paving_region_cells'].items() if v==0],
            'boundaries_without_placed_edging_cells':[k for k,v in sampled['boundary_cells'].items() if v==0],
            'boundary_omission_basis':'no eligible one-metre gap-side sample after paving and building protection',
            'geometry_cropped_or_rescaled':False,'building_heights_reconstructed':0,'reconstructed_buildings':0,
            'boundary_dimensions_basis':'user reference prototype preset; source gap dimensions unchanged',
            'rock_paving_cell_overlap':0,'physical_registration_verified':False,'minecraft_import_tested':False,'player_movement_verified':False,
            'finished_levels_verified':False,'ground_datum_verified':False,'world_placement_eligible':False,
            'training_labels_generated':0,'model_weights_updated':False,'park_world_blocks_added':0,'limits':sampled['limits'],
            'sampling_checks':sampled['sampling_checks'],'source_points':sampled['source_points'],
            'implementation_sha256':file_hash(__file__) if Path(__file__).is_file() else None}
        def saved_check(path,offset,spawn):
            report['native_vertical_offset_blocks']=offset
            report['spawn_validation']=_spawn_check(path,spawn);report['saved_geometry_validation']=_saved_check(path,offset,sampled,cancelled)
            (path/'PROTOTYPE-README.txt').write_text('Wicker current-geometry prototype: flat nominal scale, paving, user-reference rock edging and oak fences on paths under four blocks wide.\nColoured ground cells mark 2D building proposals, not reconstructed buildings. Ground levels and park registration remain unresolved.\n')
        progress({'progress':.25,'message':'Writing complete paving and reference-style rock edging'})
        world=bedrock.export_world(voxel,root,report,name='Wicker paving and rock boundary prototype',max_blocks=LIMITS['max_world_writes'],ground_depth=3,post_export_check=saved_check)
        report['archive_validation']=_verify_archive(root/world['file'],root/'bedrock-world',world,cancelled)
        shutil.move(root/world['file'],root/'wicker-geometry.mcworld');world['file']='wicker-geometry.mcworld'
        report.update(file=world['file'],world=world,preview_worlds_exported=1,worlds=[{'file':world['file'],'world':world,'audit_file':'quality-report.json','reconstructed_buildings':0}],elapsed_seconds=round(time.monotonic()-started,3))
        for name in data:shutil.copyfile(config[name+'_path'],root/('source-'+name+'.json'))
        portable={**config}
        for name in data:portable[name+'_path']='source-'+name+'.json'
        atomic_json(root/'generation-request.json',portable)
        atomic_json(root/'rock-reference-style.json',sampled['style'])
        atomic_json(root/'boundary-cells.json',[{'source_cell_xz':[x,z],'minecraft_xz':[x,-z-1],
            'local_paving_width_m':sampled['widths'][(x,z)],'columns_above_ground':column,
            'boundary_material_kind':'oak_fence' if column==[(1,'oak_fence')] else 'rock'}
            for (x,z),column in sorted(sampled['rocks'].items())])
        if sampled['plan_markers']:
            atomic_json(root/'plan-marking-cells.json',[{'source_cell_xz':[x,z],'minecraft_xz':[x,-z-1],**record}
                for (x,z),record in sorted(sampled['plan_markers'].items())])
        _previews(root,sampled)
        shutil.rmtree(root/'bedrock-world')
        (root/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Wicker geometry prototype</title><h1>Current geometry world</h1><p><a download href="wicker-geometry.mcworld">Download Minecraft Bedrock world</a></p><p>Current paving and low irregular stone/cobblestone edging, using the user reference. Paths under four blocks wide use oak fences. Flat nominal ground; coloured markers show 2D building proposals without invented heights. Rock shape is a prototype style, not measured source detail. When present, orange wool marks the reviewed ride alignment, blue wool is a one-block side guide and brown wool marks drawn support frames. Games and toilet wall lines are ground-level 2D markers.</p><p><a href="quality-report.json">Saved-world checks</a></p><img style="max-width:100%" src="world-overview.png"><img style="max-width:100%" src="rock-style-detail.png">')
        for name in data:
            if file_hash(config[name+'_path'])!=config[name+'_sha256']:raise ValueError('Geometry input changed during export')
        report['output_sha256']={p.relative_to(root).as_posix():file_hash(p) for p in sorted(root.rglob('*')) if p.is_file()}
        atomic_json(root/'quality-report.json',report)
        if cancelled():raise CancelledError('Geometry world generation cancelled')
        if output.exists():raise ValueError('Fresh geometry world output required')
        root.rename(output)
    progress({'progress':1.,'message':'Current geometry world ready to download'});return report


def _previews(root,sampled):
    from .rock_world_render import render_previews
    render_previews(root,sampled)


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description='Generate a world from current paving and rock boundaries')
    parser.add_argument('--config',required=True);parser.add_argument('--output',required=True);args=parser.parse_args(argv)
    path=Path(args.config).resolve()
    if path.stat().st_size>16384:raise ValueError('Bounded geometry world request required')
    config=json.loads(path.read_text())
    for name in tuple(n for n in ('layout','paving','gaps','buildings','markings') if n+'_path' in config):config[name+'_path']=str((path.parent/config[name+'_path']).resolve())
    result=run(config,args.output);print(json.dumps({'file':result['file'],'rock_blocks':result['rock_blocks']}))


if __name__=='__main__':main()
