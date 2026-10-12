"""Bounded building-neutral native surface previews with slab roofs and air guards."""
import math
from collections import Counter,defaultdict
from itertools import product
from pathlib import Path
from shapely.geometry import Polygon,Point
from .building_spec import build,digest
from .wing_block_shapes import occupied_halves
from .generation_cycles import atomic_json

VERSION='building-native-surface-v2'


def _shapes(palette):
    names=['full','slab','slab_top']
    result=[('air',set())]
    for name in names:
        material=('stone_bricks' if palette=='stone_brick' else 'dark_oak_planks') if name=='full' else palette+'_'+name
        halves=set(occupied_halves({(0,0,0):material}))
        result.append((material,halves))
    return result


def compile_spec(spec,*,max_checks=2000000):
    if type(max_checks) is not int or not 1<=max_checks<=2000000:
        raise ValueError('Bounded native sampling work required')
    model=build(spec)
    vertices=[v for c in model['components'] for v in c['mesh']['vertices']]
    lo=[min(v[i] for v in vertices) for i in range(3)];hi=[max(v[i] for v in vertices) for i in range(3)]
    if hi[0]-lo[0]>256 or hi[1]-lo[1]>256 or hi[2]-lo[2]>128:
        raise ValueError('Building exceeds isolated native preview extent budget')
    air=spec.get('native_air_halves',[])
    if not isinstance(air,list) or len(air)>100000 or any(not isinstance(p,list) or len(p)!=3 or any(type(v) is not int or abs(v)>20002 for v in p) for p in air):
        raise ValueError('Bounded integer native air guards required')
    protected={tuple(p) for p in air};stone=set();full_block_cells=set();roof_surfaces=[];checks=0;rows=[]
    def charge():
        nonlocal checks
        checks+=1
        if checks>max_checks:raise ValueError('Native sampling work budget exceeded; no partial geometry')
    # Extrusion holes supply their own void evidence. Preserve their native
    # alias column through the declared interval rather than filling the hole.
    for component in spec['components']:
        geometry=component['geometry']
        if geometry['kind']!='extrusion':continue
        axis=geometry['axis'];other=[i for i in range(3) if i!=axis]
        low,high=geometry['interval_m']
        for ring in geometry.get('holes',[]):
            polygon=Polygon(ring);a,b,c,d=polygon.bounds
            for u in range(math.floor(2*a),math.ceil(2*c)):
                for v in range(math.floor(2*b),math.ceil(2*d)):
                    charge()
                    if not polygon.covers(Point((u+.5)/2,(v+.5)/2)):continue
                    for depth in range(2*math.floor(low),2*math.ceil(high)):
                        point=[0,0,0];point[other[0]]=u;point[other[1]]=v;point[axis]=depth
                        protected.add((point[0],point[2],point[1]))
                        if len(protected)>100000:raise ValueError('Derived air-guard budget exceeded')
    guard_groups=defaultdict(set)
    for x,y,z in protected:guard_groups[x//2,y//2,z//2].add((x%2,y%2,z%2))
    for component in model['components']:
        mesh=component['mesh'];roof=component['role']=='roof';sampled=set();count=0;roof_tops={};roof_bottoms={}
        height=max(v[2] for v in mesh['vertices'])-min(v[2] for v in mesh['vertices'])
        slab_eligible=component['role']=='detail' and height<.75
        for indices in mesh['triangles']:
            # Geometry XYZ is frontage/depth/height; native XYZ is frontage/height/depth.
            points=[(mesh['vertices'][i][0],mesh['vertices'][i][2],mesh['vertices'][i][1]) for i in indices]
            a,b,c=points;u=[b[i]-a[i] for i in range(3)];v=[c[i]-a[i] for i in range(3)]
            normal=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
            axis=1 if roof else max(range(3),key=lambda i:abs(normal[i]))
            if abs(normal[axis])<1e-12:continue
            other=[i for i in range(3) if i!=axis]
            polygon=Polygon([[p[i] for i in other] for p in points]);xmin,ymin,xmax,ymax=polygon.bounds
            scale=1 if roof else 2
            for first in range(math.floor(xmin*scale),math.ceil(xmax*scale)):
                for second in range(math.floor(ymin*scale),math.ceil(ymax*scale)):
                    charge();point=Point((first+.5)/scale,(second+.5)/scale)
                    if not polygon.covers(point):continue
                    sample=[0.,0.,0.];sample[other[0]],sample[other[1]]=point.coords[0]
                    sample[axis]=a[axis]-sum(normal[i]*(sample[i]-a[i]) for i in other)/normal[axis]
                    if roof:
                        column=(first,second);roof_tops[column]=max(roof_tops.get(column,-math.inf),sample[1])
                        roof_bottoms[column]=min(roof_bottoms.get(column,math.inf),sample[1])
                        sampled.add(column)
                    else:
                        half=list(math.floor(q*2+1e-9) for q in sample)
                        if axis==1 and (component['role'] in ('floor','ground') or normal[1]>0):
                            half[1]=math.floor(sample[1]*2+.5)-1
                        half=tuple(half);stone.add(half);sampled.add(half)
                        if not slab_eligible:full_block_cells.add(tuple(v//2 for v in half))
                    count+=1
        if roof:roof_surfaces.append((roof_tops,roof_bottoms,mesh['watertight']))
        rows.append({'id':component['id'],'role':component['role'],'vertical_extent_m':height,
                     'non_roof_slab_eligible':slab_eligible,'samples':len(sampled),'unrepresented_at_native_resolution':not bool(sampled)})
    groups=defaultdict(set)
    for x,y,z in stone:
        groups[x//2,y//2,z//2].add((x%2,y%2,z%2))
    cells={};missing=extra=0;guarded_cells=0;full_blocks_withheld_for_air=0
    stone_shapes=_shapes('stone_brick')
    for position,target in sorted(groups.items()):
        forbidden=guard_groups.get(position,set())
        if position in full_block_cells:
            material,shape=next((m,s) for m,s in stone_shapes if m=='stone_bricks')
            if shape&forbidden:
                material,shape='air',set();full_blocks_withheld_for_air+=1
        else:
            choices=[(len(target-shape)+len(shape-target),material,shape) for material,shape in stone_shapes if not shape&forbidden]
            _,material,shape=min(choices,key=lambda r:(r[0],len(target-r[2]),r[1]))
        missing+=len(target-shape);extra+=len(shape-target);guarded_cells+=bool(forbidden)
        if material!='air':cells[position]=material
    # Quantize the source roof top at metre-column centres, then bridge only
    # neighbouring roof courses. Masonry and declared air always take precedence.
    roof_halves=defaultdict(set);blocked_roof=set();rounding=[]
    for roof_tops,roof_bottoms,closed in roof_surfaces:
        tops={column:math.floor(height*2+.5) for column,height in roof_tops.items()}
        for (x,z),top in sorted(tops.items()):
            rounding.append(abs(top/2-roof_tops[x,z]))
            adjacent=[tops[q] for q in ((x-1,z),(x+1,z),(x,z-1),(x,z+1)) if q in tops]
            start=min([top,*adjacent])-1
            if closed:start=min(start,math.floor(roof_bottoms[x,z]*2+.5))
            if top-start>16:raise ValueError('Roof course gap exceeds bounded riser policy')
            for y in range(start,top):
                position=(x,y//2,z)
                occupied={(2*x+dx,y,2*z+dz) for dx,dz in product((0,1),repeat=2)}
                if occupied&protected or position in cells:
                    blocked_roof.add(position);continue
                roof_halves[position].add(y%2)
    for position,halves in sorted(roof_halves.items()):
        cells[position]='dark_oak_planks' if len(halves)==2 else 'dark_oak_slab_top' if 1 in halves else 'dark_oak_slab'
    if set(occupied_halves(cells))&protected:raise ValueError('Native output obstructed declared air')
    if not cells:raise ValueError('No representable native building geometry')
    return cells,{'version':VERSION,'spec_sha256':digest(spec),'source_mesh_unchanged':True,
                  'component_sampling':rows,'sampling_checks':checks,'surface_cells':len(cells),
                  'material_counts':dict(sorted(Counter(cells.values()).items())),
                  'source_surface_halves_missing':missing,'extra_native_halves':extra,
                  'protected_air_halves':len(protected),'guarded_surface_cells':guarded_cells,
                  'protected_air_verified':True,'blocked_roof_cells':len(blocked_roof),
                  'block_policy':'Full blocks for walls, partitions, floors, ground and towers; slabs for roofs or detail vertical extent strictly below 0.75 m.',
                  'non_roof_stairs':0,'full_blocks_withheld_for_air':full_blocks_withheld_for_air,
                  'max_roof_top_rounding_error_m':max(rounding,default=0),
                  'wooden_roof_stairs':0,'glazing_cells':0,'world_placement_eligible':False,'park_world_blocks_added':0,
                  'limitations':['Surface sampling, not solid-volume filling or complete-building inference.',
                      'One-block horizontal/half-height display shapes alias thin or sub-half-metre details.',
                      'Roof risers are display joins; masonry collisions and air guards can withhold courses.',
                      'Watertight assembly, connected roof support and in-game movement are not certified.']}


def export_preview(spec,output,*,world=False,max_checks=2000000):
    cells,audit=compile_spec(spec,max_checks=max_checks)
    root=Path(output)
    if root.exists():raise ValueError('Fresh native preview directory required')
    root.mkdir(parents=True)
    rows=[{'x':x,'y':y,'z':z,'kind':'structure','material':material,'feature':spec['building_id']} for (x,y,z),material in sorted(cells.items())]
    if world:
        minx,maxx=min(p[0] for p in cells)-3,max(p[0] for p in cells)+4
        minz,maxz=min(p[2] for p in cells)-3,max(p[2] for p in cells)+4
        ground=min(p[1] for p in cells)-1
        if (maxx-minx)*(maxz-minz)>100000:raise ValueError('Isolated platform budget exceeded')
        rows.extend({'x':x,'y':ground,'z':z,'kind':'terrain','material':'grass_block'} for x in range(minx,maxx) for z in range(minz,maxz))
    voxel=root/'voxels.jsonl'
    import json
    voxel.write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in rows))
    report={'voxel_size_m':1,'model_blocks_per_source_metre':1,'crs':None,'vertical_datum':'STUDY_ZERO',
            'geographic_registration':None,'world_placement_eligible':False,'park_world_blocks_added':0,
            'native_audit':audit,'limitations':audit['limitations']}
    if world:
        from .bedrock import export_world
        report['world']=export_world(voxel,root,report,name='Data-driven building surface preview',ground_depth=4)
    atomic_json(root/'quality-report.json',report)
    return report
