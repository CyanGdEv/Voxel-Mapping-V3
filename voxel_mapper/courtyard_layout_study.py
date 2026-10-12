"""Whole ground-floor courtyard study from explicit, source-pinned raster traces.

Retains the preceding north-range study. New sampled centre-lines, roof joins,
vertical dimensions and native one-metre discretisation remain hypotheses.
"""
import hashlib
import json
import math

from shapely.geometry import Polygon, LineString, box
from shapely.ops import unary_union
from .wing_shell_study import solid
from .wing_block_shapes import occupied_halves

VERSION = 'courtyard-plan-layout-study-v1'


def validate_source(seed, plan_path):
    import fitz
    from pathlib import Path
    if hashlib.sha256(Path(plan_path).read_bytes()).hexdigest() != seed['plan_pdf_sha256']:
        raise ValueError('Plan PDF checksum changed')
    with fitz.open(plan_path) as doc:
        page = doc[0]
        if page.rect.width != seed['source_page_width_points']:
            raise ValueError('Source page dimensions changed')
        caption = ''.join(page.get_text().split())
        if "GroundFloorPlan'asexisting'" not in caption:
            raise ValueError('Existing ground-floor caption required')
        pix = page.get_pixmap(matrix=fitz.Matrix(1800 / page.rect.width, 1800 / page.rect.width))
        if (pix.width, pix.height) != (1800, 1272) or hashlib.sha256(pix.samples).hexdigest() != seed['plan_render_samples_sha256']:
            raise ValueError('Source plan render changed')


def build(north_model, north_cells, seed):
    if seed.get('version') != VERSION or seed.get('hypotheses_acknowledged') is not True:
        raise ValueError('Explicit courtyard hypothesis seed required')
    digest = hashlib.sha256((json.dumps(north_model, sort_keys=True, indent=2) + '\n').encode()).hexdigest()
    if digest != seed.get('north_model_sha256'):
        raise ValueError('Retained north model changed')
    controls = {'wall_thickness_m': (.1, .5), 'wall_height_m': (2.5, 8),
                'partition_height_m': (2, 3), 'ridge_height_m': (3, 12),
                'door_height_m': (2, 3), 'window_sill_m': (.5, 2),
                'window_head_m': (1.5, 3), 'roof_thickness_m': (.1, .5)}
    for key, (lo, hi) in controls.items():
        value = seed.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi:
            raise ValueError('Invalid bounded display dimension: ' + key)
    if not seed['window_sill_m'] < seed['window_head_m'] < seed['wall_height_m']:
        raise ValueError('Window heights must be ordered')
    if seed.get('raster_width') != 1800 or seed.get('source_scale_denominator') != 100 or seed.get('source_page_width_points') != 2384:
        raise ValueError('Pinned plan scale required')
    for key, limit in [('footprints',16), ('external_walls',512), ('partitions',512), ('openings',128), ('rooms',100)]:
        if not isinstance(seed.get(key), list) or not 1 <= len(seed[key]) <= limit:
            raise ValueError('Trace budget exceeded: ' + key)
    unit = 2384 / 1800 * 100 * .0254 / 72
    origin = seed['origin_pixel']
    if origin != [1059,305]:
        raise ValueError('Retained north coordinate frame required')
    def local(p):
        if len(p) != 2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in p) or not 0 <= p[0] <= 1800 or not 0 <= p[1] <= 1272:
            raise ValueError('Finite in-page trace required')
        return ((p[1]-origin[1])*unit, (p[0]-origin[0])*unit)
    def polygon(ring):
        if not 3 <= len(ring) <= 256:
            raise ValueError('Bounded polygon trace required')
        p = Polygon([local(v) for v in ring])
        if not p.is_valid or p.area <= .01:
            raise ValueError('Invalid traced polygon')
        return p
    footprints = {r['id']:polygon(r['pixel_ring']) for r in seed['footprints']}
    if len(footprints) != len(seed['footprints']) or 'north_range' not in footprints:
        raise ValueError('Unique named ranges required')
    envelope = unary_union(list(footprints.values()))
    courtyard = polygon([[415,305],[1059,305],[1059,991],[415,991]])
    if envelope.intersection(courtyard).area > 1e-8:
        raise ValueError('Building footprint intrudes into protected courtyard')
    thickness = seed['wall_thickness_m']
    def walls(rows):
        for r in rows:
            if len(r) != 2:
                raise ValueError('Two-point wall centre-lines required')
        return unary_union([LineString([local(v) for v in r]).buffer(thickness/2,cap_style=2) for r in rows])
    outer, partitions = walls(seed['external_walls']), walls(seed['partitions'])
    openings = [(r,polygon(r['pixel_ring'])) for r in seed['openings']]
    if len({r['id'] for r,_ in openings}) != len(openings) or any(r['kind'] not in ('door','passage','window') for r,_ in openings):
        raise ValueError('Unique bounded opening inventory required')
    doors = unary_union([p for r,p in openings if r['kind'] != 'window'])
    windows = unary_union([p for r,p in openings if r['kind'] == 'window'])
    components = json.loads(json.dumps(north_model['components']))
    for c in components:
        c['retained_north_component'] = True
        c['role'] = 'roof' if c['id']=='roof_shell' else 'floor' if c['id']=='floor' else 'wall'
    def add(profile,lo,hi,name,role,colour):
        if profile.is_empty:return
        geoms = [profile] if profile.geom_type=='Polygon' else list(profile.geoms)
        for i,p in enumerate(geoms):
            if p.area < 1e-8:continue
            if p.geom_type != 'Polygon':raise ValueError('Polygon-only wall assembly required')
            components.append({'id':name+'_'+str(i),'role':role,'colour':colour,
                               'evidence':seed['trace_class'],'mesh':solid(p,2,lo,hi)})
    h = seed['wall_height_m']; dh = seed['door_height_m']; sill = seed['window_sill_m']; head = seed['window_head_m']
    annex_zone=unary_union([p.buffer(thickness) for id,p in footprints.items() if 'annex' in id])
    wall_regions=[(outer.difference(annex_zone),h,'main')]
    for row in seed['footprints']:
        if 'annex' in row['id']:
            eh=row['roof_eave_m']
            if type(eh) not in (int,float) or not math.isfinite(eh) or not 2<=eh<h:
                raise ValueError('Bounded annex eaves required')
            wall_regions.append((outer.intersection(footprints[row['id']].buffer(thickness)),eh,row['id']))
    # Each horizontal slice has the same source footprint; opening heights are hypotheses.
    for region,rh,name in wall_regions:
        levels = sorted({0,sill,head,dh,rh})
        for i,(lo,hi) in enumerate(zip(levels,levels[1:])):
            mask = unary_union(([doors] if lo < dh else []) + ([windows] if sill <= lo < head else []))
            add(region.difference(mask),lo,hi,'plan_outer_wall_'+name+'_slice_'+str(i),'wall','c1a16d')
    add(partitions.difference(doors),0,seed['partition_height_m'],'plan_room_partition','partition','719c85')
    for id,p in footprints.items():
        if id!='north_range':add(p,-.25,0,'plan_floor_'+id,'floor','c7c4bd')
    add(courtyard,-.25,0,'courtyard_ground','ground','aab999')
    cells = dict(north_cells); original = dict(north_cells)
    # The interior courtyard is protected above ground, including from sampled wall spill.
    xmin,ymin,xmax,ymax = envelope.bounds
    ranges = (range(math.floor(xmin)-1,math.ceil(xmax)+1),range(math.floor(ymin)-1,math.ceil(ymax)+1))
    def put(p,m):
        if p not in original:cells[p]=m
    def intersects(poly,x,z,threshold=.08):
        return poly.intersection(box(x,z,x+1,z+1)).area > threshold
    native_wall_slices=[]
    for y in range(math.ceil(h)):
        low=y+.5
        shape=unary_union([region for region,rh,_ in wall_regions if low<rh])
        if low<dh:shape=shape.difference(doors)
        if sill<=low<head:shape=shape.difference(windows)
        native_wall_slices.append(shape)
    for x in ranges[0]:
        for z in ranges[1]:
            if intersects(envelope,x,z):put((x,-1,z),'stone_bricks')
            for y in range(math.ceil(h)):
                # Preserve every previous north cell; new solids are display sampling.
                shape=native_wall_slices[y]
                if intersects(shape,x,z):put((x,y,z),'stone_bricks')
            if intersects(partitions.difference(doors),x,z):
                for y in range(math.ceil(seed['partition_height_m'])):
                    put((x,y,z),'stone_brick_slab' if y+1>seed['partition_height_m'] else 'stone_bricks')
    # Reserve one native column along narrow doorways; exact meshes keep sampled widths.
    clearance = []
    for row,p in openings:
        if row['kind']=='window':continue
        cx,cz=p.centroid.coords[0];a,b,c,d=p.bounds
        if c-a > d-b:reserved=[(x,math.floor(cz)) for x in range(math.floor(a),math.ceil(c))]
        else:reserved=[(math.floor(cx),z) for z in range(math.floor(b),math.ceil(d))]
        for x,z in reserved:
            for y in (0,1):
                if (x,y,z) not in original:cells.pop((x,y,z),None)
        clearance.append({'id':row['id'],'kind':row['kind'],'native_columns':reserved,
                          'native_width_rule':'minimum one metre; horizontal sampling hypothesis'})
    roof_columns = {}
    for row in seed['footprints']:
        if row['id']=='north_range':continue
        p = footprints[row['id']];a,b,c,d=p.bounds
        eh,rh=row['roof_eave_m'],row['roof_ridge_m']
        if not all(type(v) in (int,float) and math.isfinite(v) for v in (eh,rh)) or not 2 <= eh < rh <=12:
            raise ValueError('Bounded hypothetical roof heights required')
        if row['ridge_axis'] not in ('pixel_x','pixel_y'):raise ValueError('Roof ridge axis required')
        # Pixel-y corresponds to local X; pixel-x corresponds to local depth Y.
        axis = 0 if row['ridge_axis']=='pixel_y' else 1
        cross_lo,cross_hi = (b,d) if axis==0 else (a,c)
        peak=(cross_lo+cross_hi)/2; rt=seed['roof_thickness_m']
        profile=Polygon([(cross_lo,eh),(peak,rh),(cross_hi,eh),(cross_hi,eh-rt),(peak,rh-rt),(cross_lo,eh-rt)])
        mesh=solid(profile,axis,a if axis==0 else b,c if axis==0 else d)
        components.append({'id':'roof_'+row['id'],'role':'roof','colour':'775338','evidence':'assumed symmetric pitch and overlapping roof joins','mesh':mesh})
        gable=Polygon([(cross_lo,eh),(cross_hi,eh),(peak,rh)])
        ends=(a,c) if axis==0 else (b,d)
        for side,pos in enumerate(ends):
            lo=pos if side==0 else pos-thickness
            components.append({'id':'roof_join_cap_'+row['id']+'_'+str(side),'role':'roof',
                               'colour':'c1a16d','evidence':'provisional roof joining-plane closure',
                               'mesh':solid(gable,axis,lo,lo+thickness)})
        for x in range(math.floor(a),math.ceil(c)):
            for z in range(math.floor(b),math.ceil(d)):
                if not intersects(p,x,z):continue
                cross=z+.5 if axis==0 else x+.5
                roof_h=eh+(rh-eh)*max(0,1-abs(cross-peak)/((cross_hi-cross_lo)/2))
                y=math.floor(roof_h)
                along=x if axis==0 else z
                if along in (math.floor(ends[0]),math.ceil(ends[1])-1):
                    for gy in range(math.ceil(eh),y):put((x,gy,z),'stone_bricks')
                # Dominant roof surface resolves native overlaps as a display rule.
                direction=('north' if cross<peak else 'south') if axis==0 else ('east' if cross<peak else 'west')
                if (x,z) not in roof_columns or y>roof_columns[x,z][0]:
                    roof_columns[x,z]=(y,'dark_oak_stairs_'+direction)
    for (x,z),(y,material) in roof_columns.items():
        put((x,y,z),material)
    half=occupied_halves(cells)
    for row in clearance:
        row['standing_air_verified'] = all((2*x+dx,hy,2*z+dz) not in half for x,z in row['native_columns'] for dx in (0,1) for dz in (0,1) for hy in range(4))
        if row['kind']=='passage' and not row['standing_air_verified']:
            raise ValueError('Blocked full-range passage: '+row['id'])
    if any(cells.get(p)!=m for p,m in original.items()):raise ValueError('Retained north cells changed')
    if any('glass' in m for m in cells.values()):raise ValueError('Glazing is not permitted')
    rooms=[]
    for row in seed['rooms']:
        p=polygon(row['pixel_ring'])
        if p.difference(envelope).area>1e-7:raise ValueError('Room outside drawn building footprint')
        rooms.append(dict(row,local_ring_xy_m=list(p.exterior.coords),approximate_floor_area_m2=p.area))
    if len({r['id'] for r in rooms})!=len(rooms):raise ValueError('Duplicate room identity')
    audit={'version':VERSION,'retained_north_cells':len(original),'north_cells_unchanged':True,
           'surface_cells':len(cells),'added_cells':len(cells)-len(original),'rooms_in_layout':len(rooms),
           'range_ids':list(footprints),'source_plan_sha256':seed['plan_pdf_sha256'],
           'plan_pixel_metres':unit,'source_trace_class':seed['trace_class'],
           'courtyard_area_m2':courtyard.area,'passages_and_doors':clearance,
           'standing_passages_verified':all(r['standing_air_verified'] for r in clearance if r['kind']=='passage'),
           'doorways_with_retained_obstruction':[r['id'] for r in clearance if not r['standing_air_verified']],
           'glazing_cells':0,'all_component_solids_watertight':all(c['mesh']['watertight'] for c in components),
           'native_roof_join_rule':'highest new sampled roof surface; retained north cells take precedence',
           'assembly_boolean_union':False,'surveyed_complete_structure':False,'park_world_blocks_added':0}
    model={'version':VERSION,'status':'full_courtyard_ground_floor_layout_hypothesis',
           'components':components,'rooms':rooms,'courtyard_ring_xy_m':list(courtyard.exterior.coords),
           'footprints':{k:list(p.exterior.coords) for k,p in footprints.items()},
           'source_pdf_sha256':seed['plan_pdf_sha256'],'north_model_sha256':digest,
           'seed_sha256':hashlib.sha256(json.dumps(seed,sort_keys=True).encode()).hexdigest(),
           'assumptions':seed['limitations'],'surveyed_complete_structure':False,
           'full_ground_floor_layout_preview':True,'world_placement_eligible':False,
           'geographic_registration':None,'assembly_boolean_union':False,'park_world_blocks_added':0}
    return model,cells,audit
