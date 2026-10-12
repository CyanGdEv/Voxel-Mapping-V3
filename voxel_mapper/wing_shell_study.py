"""Explicit hypothetical closure of an isolated reviewed wing, never accepted geometry."""
from collections import Counter
import hashlib
import json
import math
from shapely import constrained_delaunay_triangles
from shapely.geometry import Polygon,box,Point
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from shapely.affinity import translate
from .wing_block_shapes import assemble,fit,material,occupied_halves

VERSION='wing-shell-hypothesis-study-v1'


def solid(profile,axis,lo,hi):
    """Extrude a polygon with holes; validate closed oriented edges and volume."""
    if type(axis) is not int or axis not in (0,1,2) or any(type(v) not in (int,float) or not math.isfinite(v) for v in (lo,hi)):
        raise ValueError('Finite solid extrusion axes required')
    profile=orient(profile,sign=1)
    if profile.geom_type!='Polygon' or not profile.is_valid or not lo<hi:
        raise ValueError('Valid bounded solid profile required')
    if sum(len(r.coords) for r in [profile.exterior,*profile.interiors])>4096:
        raise ValueError('Solid profile vertex budget exceeded')
    axes=[i for i in range(3) if i!=axis];vertices=[];indices={};faces=[]
    def vertex(p,t):
        v=[0.,0.,0.];v[axis]=t;v[axes[0]]=p[0];v[axes[1]]=p[1];v=tuple(v)
        if v not in indices:indices[v]=len(vertices);vertices.append(list(v))
        return indices[v]
    for tri in constrained_delaunay_triangles(profile).geoms:
        pts=list(orient(tri,sign=1).exterior.coords)[:-1]
        faces.append([vertex(p,lo) for p in reversed(pts)])
        faces.append([vertex(p,hi) for p in pts])
    for ring in [profile.exterior,*profile.interiors]:
        coords=list(ring.coords)
        for a,b in zip(coords,coords[1:]):
            ai,bi,at,bt=vertex(a,lo),vertex(b,lo),vertex(a,hi),vertex(b,hi)
            faces.extend([[ai,bi,bt],[ai,bt,at]])
    if axis==1:faces=[list(reversed(f)) for f in faces]
    edges=Counter((f[i],f[(i+1)%3]) for f in faces for i in range(3))
    if any(count!=1 or edges.get((b,a))!=1 for (a,b),count in edges.items()):
        raise ValueError('Solid mesh has an open or misoriented edge')
    def determinant(a,b,c):
        return a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0])
    volume=sum(determinant(*[vertices[i] for i in f]) for f in faces)/6
    expected=profile.area*(hi-lo)
    if abs(volume-expected)>1e-6:raise ValueError('Solid mesh volume disagrees with profile')
    return {'vertices':vertices,'triangles':faces,'watertight':True,'volume_m3':volume}


def build(parent,seed):
    encoded=(json.dumps(parent,sort_keys=True,indent=2)+'\n').encode()
    if seed.get('version')!=VERSION or seed.get('review_hypotheses_acknowledged') is not True or seed.get('parent_model_sha256')!=hashlib.sha256(encoded).hexdigest():
        raise ValueError('Explicit source-model-pinned shell hypothesis seed required')
    thickness=seed.get('wall_display_thickness_m');roof_thickness=seed.get('roof_vertical_display_thickness_m');floor_thickness=seed.get('floor_display_thickness_m')
    if any(type(v) not in (int,float) or not math.isfinite(v) or not .1<=v<=.5 for v in (thickness,roof_thickness,floor_thickness)):
        raise ValueError('Bounded display thickness required')
    cells,front_audit=assemble(parent)
    length=parent['width_check']['elevation_length_m'];depth=parent['measurements']['depth_m']
    eaves=parent['measurements']['eaves_m'];ridge=parent['measurements']['ridge_m'];peak=parent['roof_assembly']['ridge_depth_m']
    arches=[r for r in parent['openings'] if r['kind']=='archway']
    if len(arches)!=1:raise ValueError('Single reviewed arch passage required for this shell study')
    arch=Polygon(arches[0]['local_polygon_xz']);front=box(0,0,length,eaves).difference(unary_union([Polygon(r['local_polygon_xz']) for r in parent['openings']]))
    rear=box(0,0,length,eaves).difference(arch)
    gable=Polygon([(0,0),(depth,0),(depth,eaves),(peak,ridge),(0,eaves)])
    roof=Polygon([(0,eaves),(peak,ridge),(depth,eaves),(depth,eaves-roof_thickness),(peak,ridge-roof_thickness),(0,eaves-roof_thickness)])
    components=[{'id':'courtyard_wall','evidence':'reviewed front silhouette; assumed inward thickness','mesh':solid(front,1,0,thickness)},
                {'id':'rear_wall','evidence':'hypothetical rear closure; only arch is provisionally projected through','mesh':solid(rear,1,depth-thickness,depth)},
                {'id':'left_junction_cap','evidence':'temporary joining-plane closure; not an exposed surveyed gable','mesh':solid(gable,0,0,thickness)},
                {'id':'right_junction_cap','evidence':'temporary joining-plane closure; not an exposed surveyed gable','mesh':solid(gable,0,length-thickness,length)},
                {'id':'roof_shell','evidence':'reviewed slope hypothesis; assumed vertical thickness','mesh':solid(roof,0,0,length)},
                {'id':'floor','evidence':'drawn floor zero; assumed floor slab and footprint closure','mesh':solid(box(0,0,length,depth),2,-floor_thickness,0)}]
    assumptions=['Rear opening inventory is unresolved; absence of additional rear apertures is a temporary display closure.',
                 'Front arch is projected through the depth as a passage hypothesis; rear arch correspondence remains unverified.',
                 'End caps close joining planes temporarily; neighbouring wings and roof junctions are not reconstructed.',
                 'Wall, roof and floor thicknesses and materials are display choices, not measured construction.',
                 'Room partitions, upper floors, stairs, annexes and neighbouring ranges remain outside this core-shell study.',
                 'Individual solids are closed; overlapping assembly components are not a boolean-unioned manifold.']
    nx=sum(min(x+1,length)-x>=.5 for x in range(math.ceil(length)));nz=math.ceil(depth)
    if nx<3 or nz<3:raise ValueError('Shell native grid needs at least three frontage/depth cells')
    original=dict(cells);additions={};rear_z=nz-1
    def add(p,m,part):
        if p in cells:return
        cells[p]=m;additions[p]=part
    passage=next(r for r in front_audit['passage_clearance'] if r['id']==arches[0]['id'])
    for x in range(nx):
        for y in range(math.ceil(eaves)):
            if x in passage['columns'] and y in (0,1):continue
            target=translate(rear.intersection(box(x,y,x+1,y+1)),xoff=-x,yoff=-y)
            _,name,_,_=fit(target)
            if name!='air':add((x,y,rear_z),material(name,'stone_brick','west','east'),'rear_wall')
    for x in (0,nx-1):
        for z in range(1,nz-1):
            roofs=[y for (rx,y,rz),m in original.items() if rx==x and rz==z and m.startswith('dark_oak')]
            if len(roofs)!=1:raise ValueError('Continuous native roof column required for junction cap')
            for y in range(roofs[0]):add((x,y,z),'stone_bricks','left_junction_cap' if x==0 else 'right_junction_cap')
    for x in range(nx):
        for z in range(nz):add((x,-1,z),'stone_bricks','floor')
    half=occupied_halves(cells)
    for x in passage['columns']:
        for z in range(nz):
            if any((2*x+dx,hy,2*z+dz) in half for dx in (0,1) for hy in range(4) for dz in (0,1)):
                raise ValueError('Shell blocks standing arch passage')
    if any(cells[p]!=m for p,m in original.items()):raise ValueError('Shell overwrote retained front/roof geometry')
    model={'version':VERSION,'status':'provisional_core_shell_with_explicit_hypotheses','parent_model_sha256':seed['parent_model_sha256'],
           'closure_seed_sha256':hashlib.sha256(json.dumps(seed,sort_keys=True).encode()).hexdigest(),
           'source_pdf_sha256':parent['source_pdf_sha256'],'measurements':parent['measurements'],'components':components,
           'thicknesses_m':{'wall':thickness,'roof_vertical':roof_thickness,'floor':floor_thickness},'assumptions':assumptions,
           'front_openings':parent['openings'],'rear_arch_profile':list(arch.exterior.coords),
           'surveyed_complete_structure':False,'complete_core_shell_preview':True,'assembly_boolean_union':False,
           'full_complex_reconstructed':False,'world_placement_eligible':False,'geographic_registration':None,'park_world_blocks_added':0}
    audit={'front_audit':front_audit,'retained_surface_cells':len(original),'added_cells':len(additions),'total_surface_cells':len(cells),
           'additions_by_part':dict(Counter(additions.values())),'native_grid':[nx,nz],
           'added_cell_records':[{'cell':list(p),'part':part,'material':cells[p],'evidence_class':'explicit_closure_hypothesis'} for p,part in sorted(additions.items())],
           'arch_standing_air_verified_through_depth':True,'arch_columns':passage['columns'],
           'original_front_roof_cells_unchanged':True,'glazing_cells':0,'assumptions':assumptions,
           'exact_components_watertight':True,'assembly_boolean_union':False,'park_world_blocks_added':0}
    return model,cells,audit
