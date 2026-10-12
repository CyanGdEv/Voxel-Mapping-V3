"""Building-neutral, evidence-linked local geometry; never asserts park placement."""
import copy
import hashlib
import json
import math
import re
from collections import Counter

VERSION = 'building-spec-v1'
FRAME = 'local_xyz_metres_z_up'
ROLES = {'wall', 'partition', 'floor', 'ground', 'roof', 'tower', 'detail'}
MAX_COMPONENTS = 4096
MAX_VERTICES = 250000
MAX_TRIANGLES = 500000


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 10000:
        raise ValueError('Finite bounded metre coordinates required')
    return value


def _mesh(mesh):
    vertices, triangles = mesh.get('vertices'), mesh.get('triangles')
    if not isinstance(vertices, list) or not 3 <= len(vertices) <= MAX_VERTICES:
        raise ValueError('Bounded mesh vertices required')
    if not isinstance(triangles, list) or not 1 <= len(triangles) <= MAX_TRIANGLES:
        raise ValueError('Bounded mesh triangles required')
    for v in vertices:
        if not isinstance(v, list) or len(v) != 3:
            raise ValueError('XYZ vertices required')
        for coordinate in v:
            _number(coordinate)
    edges = Counter()
    for t in triangles:
        if not isinstance(t, list) or len(t) != 3 or any(type(i) is not int or not 0 <= i < len(vertices) for i in t) or len(set(t)) != 3:
            raise ValueError('Valid triangle indices required')
        a, b, c = [vertices[i] for i in t]
        u, v = [b[i]-a[i] for i in range(3)], [c[i]-a[i] for i in range(3)]
        cross = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
        if sum(x*x for x in cross) <= 1e-20:
            raise ValueError('Degenerate mesh triangle')
        edges.update((t[i], t[(i+1) % 3]) for i in range(3))
    closed = all(n == 1 and edges.get((b, a)) == 1 for (a, b), n in edges.items())
    if mesh.get('watertight') is True and not closed:
        raise ValueError('Claimed closed mesh has open or misoriented edges')
    result = copy.deepcopy(mesh)
    result['watertight'] = closed
    return result


def _geometry(geometry):
    kind = geometry.get('kind')
    if kind == 'mesh':
        return _mesh(geometry['mesh'])
    if kind != 'extrusion':
        raise ValueError('Supported component geometry is mesh or extrusion')
    from shapely.geometry import Polygon
    from .wing_shell_study import solid
    rings = [geometry['profile'], *geometry.get('holes', [])]
    if not 1 <= len(rings) <= 128 or sum(len(r) for r in rings) > 4096:
        raise ValueError('Profile ring budget exceeded')
    for ring in rings:
        if not isinstance(ring, list) or len(ring) < 3:
            raise ValueError('Polygon ring required')
        for p in ring:
            if not isinstance(p, list) or len(p) != 2:
                raise ValueError('Two-coordinate profile points required')
            for x in p:
                _number(x)
    axis = geometry['axis']
    lo, hi = map(_number, geometry['interval_m'])
    return solid(Polygon(rings[0], rings[1:]), axis, lo, hi)


def build(spec):
    if spec.get('version') != VERSION or spec.get('coordinate_frame') != FRAME:
        raise ValueError('Versioned local metre building specification required')
    if not isinstance(spec.get('building_id'), str) or not spec['building_id']:
        raise ValueError('Stable building identity required')
    sources = spec.get('sources')
    if not isinstance(sources, list) or not 1 <= len(sources) <= 1024:
        raise ValueError('Bounded source inventory required')
    source_map = {}
    for source in sources:
        identifier = source.get('id')
        if not isinstance(identifier, str) or not identifier or identifier in source_map:
            raise ValueError('Unique source identity required')
        if not re.fullmatch('[0-9a-f]{64}', source.get('sha256', '')) or source.get('state') not in ('existing', 'proposed', 'unknown'):
            raise ValueError('Pinned source and explicit drawing state required')
        source_map[identifier] = source
    states = {source['state'] for source in sources}
    if len(states) != 1:
        raise ValueError('Existing and proposed sources must remain separate')
    components = spec.get('components')
    if not isinstance(components, list) or not 1 <= len(components) <= MAX_COMPONENTS:
        raise ValueError('Bounded component inventory required')
    assumptions = spec.get('assumptions')
    if not isinstance(assumptions, list) or any(not isinstance(a, str) or not a for a in assumptions):
        raise ValueError('Explicit assumption list required')
    output, ids, total_vertices, total_triangles = [], set(), 0, 0
    for component in components:
        identifier = component.get('id')
        if not isinstance(identifier, str) or not identifier or identifier in ids or component.get('role') not in ROLES:
            raise ValueError('Unique component identity and supported role required')
        ids.add(identifier)
        evidence = component.get('evidence', {})
        refs = evidence.get('source_ids')
        if not isinstance(refs, list) or not refs or any(s not in source_map for s in refs):
            raise ValueError('Each component must link to declared sources')
        if evidence.get('class') not in ('reviewed', 'inferred') or not evidence.get('description'):
            raise ValueError('Reviewed or inferred evidence description required')
        if evidence['class'] == 'inferred' and not assumptions:
            raise ValueError('Inferred geometry requires explicit assumptions')
        colour = component.get('colour', '859caf')
        if not isinstance(colour, str) or not re.fullmatch('[0-9a-fA-F]{6}', colour):
            raise ValueError('Six-digit colour required')
        mesh = _geometry(component['geometry'])
        total_vertices += len(mesh['vertices']); total_triangles += len(mesh['triangles'])
        if total_vertices > MAX_VERTICES or total_triangles > MAX_TRIANGLES:
            raise ValueError('Whole-building geometry budget exceeded')
        output.append({'id': identifier, 'role': component['role'], 'colour': colour,
                       'evidence': copy.deepcopy(evidence), 'mesh': mesh})
    return {'version': VERSION, 'building_id': spec['building_id'], 'spec_sha256': digest(spec),
            'status': 'local_data_driven_building_preview', 'source_state': next(iter(states)), 'components': output,
            'assumptions': copy.deepcopy(assumptions), 'sources': copy.deepcopy(sources),
            'world_placement_eligible': False, 'park_world_blocks_added': 0,
            'surveyed_complete_structure': False, 'assembly_boolean_union': False}


def from_study(model, building_id, source_sha256, *, display_floor=False):
    """Retain existing component coordinates/triangles without reinterpreting them."""
    states = {model.get('source_state')} if model.get('source_state') else set()
    states.update(s.get('state') for s in model.get('sources', []))
    states.update(v.get('specification', {}).get('state') for v in model.get('source_frames', {}).values())
    states.update(model[k].get('source_state') for k in ('wall_mesh', 'roof_mesh', 'projection_mesh') if isinstance(model.get(k), dict))
    states.discard(None)
    if len(states) > 1:
        raise ValueError('Mixed source states in parent study')
    state = next(iter(states)) if states else 'unknown'
    if type(display_floor) is not bool:raise ValueError('Explicit boolean display floor mode required')
    sources = [{'id': 'parent_study', 'sha256': source_sha256, 'state': state}]
    assumptions = model.get('assumptions') or ['Retained study assembly; source identity, complete inventory and park placement remain unresolved.']
    rows = model.get('components')
    if rows is None:
        rows = [{'id': key, 'role': 'roof' if key in ('roof_mesh','projection_mesh') else 'wall',
                 'mesh': model[key]} for key in ('wall_mesh', 'roof_mesh', 'projection_mesh') if key in model]
    spec = {'version': VERSION, 'coordinate_frame': FRAME, 'building_id': building_id,
            'sources': sources, 'assumptions': assumptions, 'components': []}
    for row in rows:
        role = row.get('role')
        if role not in ROLES:
            role = 'roof' if row['id'].startswith('roof') else 'partition' if row['id'].startswith('interior_partition') else 'detail'
        spec['components'].append({'id': row['id'], 'role': role, 'colour': row.get('colour', '775338' if role == 'roof' else '859caf'),
            'evidence': {'class': 'inferred', 'source_ids': ['parent_study'],
                         'description': str(row.get('evidence', model.get('assembly_hypothesis', 'Retained parent study')))},
            'geometry': {'kind': 'mesh', 'mesh': copy.deepcopy(row['mesh'])}})
    if display_floor:
        outline=model.get('outer_wall_base_outline')
        if not isinstance(outline,list) or not 3<=len(outline)<=4096 or any(len(p)!=3 or p[2]!=0 for p in outline):
            raise ValueError('Level drawn-floor-zero outline required for display floor')
        spec['assumptions']=list(spec['assumptions'])+['Display floor follows the retained outline at drawn floor zero; thickness/material and surveyed datum are unverified.']
        spec['components'].append({'id':'drawn_zero_display_floor','role':'floor',
            'evidence':{'class':'inferred','source_ids':['parent_study'],'description':'Retained base outline at drawn floor zero; one-metre display floor below zero'},
            'geometry':{'kind':'extrusion','axis':2,'interval_m':[-1,0],'profile':[p[:2] for p in outline]}})
        spec['floor_reference']={'kind':'drawn_local_zero','elevation_m':0,'surveyed_datum_verified':False}
    # Retained native passage/window constraints remain explicit display air.
    from itertools import product
    air=set()
    for x,z,h in model.get('roof_window_void_halves',[]):
        air.update((2*x+dx,h,2*z+dz) for dx,dz in product((0,1),repeat=2))
    for passage in model.get('slab_conversion_passages',[]):
        for x,z in passage.get('native_columns',[]):
            air.update((2*x+dx,h,2*z+dz) for dx,dz in product((0,1),repeat=2) for h in range(4))
    from shapely.geometry import Polygon,Point,LineString
    for opening in model.get('openings',[]):
        if 'local_polygon_xz' not in opening:continue
        polygon=Polygon(opening['local_polygon_xz']);lo,bottom,hi,top=polygon.bounds
        if not polygon.is_valid or (hi-lo)*(top-bottom)*4>100000:raise ValueError('Bounded opening guard required')
        for x in range(math.floor(2*lo),math.ceil(2*hi)):
            for h in range(math.floor(2*bottom),math.ceil(2*top)):
                if polygon.covers(Point((x+.5)/2,(h+.5)/2)):
                    air.update((x,h,z) for z in (0,1))
    for opening in model.get('opening_base_segments',[]):
        a,b=opening['endpoints'];height=opening['height_metres']
        if len(a)!=3 or len(b)!=3 or abs(a[2]-b[2])>1e-7 or type(height) not in (int,float) or not math.isfinite(height) or not 0<height<=30:
            raise ValueError('Bounded level base opening required')
        strip=LineString([a[:2],b[:2]]).buffer(.5,cap_style=2)
        lo,back,hi,front=strip.bounds
        if (hi-lo)*(front-back)>10000:raise ValueError('Opening guard area budget exceeded')
        columns=[(x,z) for x in range(math.floor(lo),math.ceil(hi)) for z in range(math.floor(back),math.ceil(front)) if strip.covers(Point(x+.5,z+.5))]
        if not columns:columns=[(math.floor((a[0]+b[0])/2),math.floor((a[1]+b[1])/2))]
        for x,z in columns:
            air.update((2*x+dx,h,2*z+dz) for dx,dz in product((0,1),repeat=2) for h in range(math.ceil(a[2]*2),math.floor((a[2]+height)*2)))
    if len(air)>100000:raise ValueError('Native air-guard budget exceeded')
    if air:spec['native_air_halves']=[list(p) for p in sorted(air)]
    build(spec)
    return spec
