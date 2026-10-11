"""Replace a courtyard study's wooden stair roofs with half-height slab courses."""
import copy
import math
from collections import defaultdict,Counter
from shapely.geometry import Polygon,box,Point
from shapely.ops import unary_union
from .wing_shell_study import solid
from .wing_block_shapes import occupied_halves


def convert(model,cells):
    source_roofs=[c for c in model['components'] if c['id']=='roof_shell' or c['id'].startswith('roof_') and not c['id'].startswith('roof_join_cap_')]
    triangles=[];polygons=[]
    for c in source_roofs:
        vertices=c['mesh']['vertices']
        for f in c['mesh']['triangles']:
            v=[vertices[i] for i in f];p=Polygon([(a[0],a[1]) for a in v])
            if p.area>1e-10:triangles.append((v,p));polygons.append(p)
    coverage=unary_union(polygons)
    wood={p:m for p,m in cells.items() if m.startswith('dark_oak')}
    if not wood:raise ValueError('Existing wooden roof cells required')
    old_columns={(x,z) for x,y,z in wood};tops={};cap_adjustments=[]
    protected={p:m for p,m in cells.items() if p not in wood}
    for x,z in sorted(old_columns):
        point=Point(x+.5,z+.5)
        if not coverage.covers(point):
            clipped=coverage.intersection(box(x,z,x+1,z+1))
            if clipped.is_empty:raise ValueError('Roof column outside source geometry')
            point=clipped.representative_point()
        px,pz=point.coords[0];heights=[]
        for v,p in triangles:
            if not p.buffer(1e-8).covers(point):continue
            a,b,c=v;den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
            u=((b[1]-c[1])*(px-c[0])+(c[0]-b[0])*(pz-c[1]))/den
            w=((c[1]-a[1])*(px-c[0])+(a[0]-c[0])*(pz-c[1]))/den
            heights.append(u*a[2]+w*b[2]+(1-u-w)*c[2])
        if not heights:raise ValueError('Roof surface sample missing')
        source=max(heights);top=math.floor(source*2+.5)
        if abs(top/2-source)>.25000001:raise ValueError('Roof top exceeded half-height rounding error')
        target=top
        for _ in range(16):
            if (x,(top-1)//2,z) not in protected:break
            top=2*((top-1)//2+1)+1
        else:raise ValueError('Roof cap collision budget exceeded')
        if top!=target:cap_adjustments.append({'column':[x,z],'target_top_m':target/2,'raised_top_m':top/2})
        tops[x,z]=top
    output=dict(protected);roof={};blocked=[]
    for (x,z),top in tops.items():
        neighbours=[tops[q] for q in ((x-1,z),(x+1,z),(x,z-1),(x,z+1)) if q in tops]
        # Fill the vertical riser beneath higher slab courses, preserving walls.
        start=min([top,*neighbours])-1
        layers=defaultdict(set)
        for half in range(start,top):layers[half//2].add(half%2)
        for y,halves in layers.items():
            p=(x,y,z)
            if p in output:
                blocked.append(p);continue
            m='dark_oak_planks' if len(halves)==2 else 'dark_oak_slab_top' if 1 in halves else 'dark_oak_slab'
            roof[p]=m;output[p]=m
    # A retained stone bottom slab cannot share its empty half with wood.
    # Raise the neighbouring wooden edge course where necessary to seal it.
    repairs=[]
    for (x,z),top in sorted(tops.items()):
        for q in ((x+1,z),(x,z+1)):
            if q not in tops:continue
            threshold=min(top,tops[q])-1
            def levels(column):
                a,b=column;result=set()
                for (cx,y,cz),m in output.items():
                    if (cx,cz)!=(a,b):continue
                    halves=(1,) if m.endswith('_top') else (0,) if m.endswith('_slab') else (0,1)
                    result.update(2*y+h for h in halves if 2*y+h>=threshold)
                return result
            aa,bb=levels((x,z)),levels(q)
            if aa&bb:continue
            if not aa or not bb:raise ValueError('Missing roof support interval '+str(((x,z),q,top,tops[q],aa,bb)))
            lower=(x,z) if max(aa)<min(bb) else q
            low,high=(aa,bb) if lower==(x,z) else (bb,aa)
            if max(low)>=min(high):raise ValueError('Unresolved interleaved roof gap')
            for half in range(max(low)+1,min(high)+1):
                p=(lower[0],half//2,lower[1]);old=output.get(p)
                if old and not old.startswith('dark_oak'):raise ValueError('Roof seal would alter retained masonry')
                existing={1} if old and old.endswith('_top') else {0} if old and old.endswith('_slab') else {0,1} if old else set()
                existing.add(half%2)
                m='dark_oak_planks' if len(existing)==2 else 'dark_oak_slab_top' if 1 in existing else 'dark_oak_slab'
                output[p]=roof[p]=m;repairs.append({'cell':list(p),'added_half':half%2})
    if any(output.get(p)!=m for p,m in cells.items() if p not in wood):raise ValueError('Roof conversion changed non-roof cells')
    if any(m.startswith('dark_oak_stairs') for m in output.values()):raise ValueError('Wooden roof stairs remain')
    occupancy=occupied_halves(output)
    for row in model.get('slab_conversion_passages',[]):
        for x,z in row['native_columns']:
            if any((2*x+dx,y,2*z+dz) in occupancy for dx in (0,1) for dz in (0,1) for y in range(4)):
                raise ValueError('Slab roof blocks passage')
    result=copy.deepcopy(model)
    roof_ids={c['id'] for c in source_roofs}
    result['components']=[c for c in result['components'] if c['id'] not in roof_ids]
    bands=defaultdict(list)
    for (x,y,z),m in roof.items():
        lo=y+.5 if m.endswith('_top') else y
        hi=y+1 if m=='dark_oak_planks' or m.endswith('_top') else y+.5
        for half in range(round(lo*2),round(hi*2)):bands[half].append((x,z))
    for half,columns in sorted(bands.items()):
        # Exact row runs avoid tangent holes in slab-course unions. Individual
        # rectangular solids remain watertight without a fragile boolean mesh.
        rows=defaultdict(list)
        for x,z in columns:rows[z].append(x)
        profiles=[]
        for z,xs in sorted(rows.items()):
            xs=sorted(set(xs));start=last=xs[0]
            for x in xs[1:]:
                if x!=last+1:profiles.append(box(start,z,last+1,z+1));start=x
                last=x
            profiles.append(box(start,z,last+1,z+1))
        for i,p in enumerate(profiles):
            result['components'].append({'id':f'slab_roof_course_{half}_{i}','role':'roof','colour':'775338',
                                         'evidence':'native half-height slab course and supporting roof riser',
                                         'mesh':solid(p,2,half/2,(half+1)/2)})
    result['native_roof_style']='slabs';result['status']='full_courtyard_ground_floor_slab_roof_hypothesis'
    result['assumptions'].append('Roofs use bottom/top slab courses and plank risers. Edge courses are raised where required to preserve and seal retained masonry; source heights remain provisional.')
    audit={'roof_style':'slabs','old_roof_cells':len(wood),'roof_columns':len(tops),'new_roof_cells':len(roof),
           'roof_material_counts':dict(Counter(roof.values())),'non_roof_cells_unchanged':True,
           'wooden_roof_stairs_remaining':0,'sampled_target_top_rounding_bound_m':.25,
           'masonry_edge_seal_repairs':repairs,
           'caps_raised_above_retained_masonry':cap_adjustments,
           'retained_wall_collisions':len(blocked),'standing_passages_verified':True}
    return result,output,audit
