"""Bounded 1:1 native-shape display sampling for a partial courtyard wing."""
from collections import Counter
import math

from shapely.geometry import LineString,Point,Polygon,box
from shapely.ops import unary_union


VERSION='wing-native-shape-review-v3'


def profiles():
    bottom=box(0,0,1,.5);top=box(0,.5,1,1)
    return [('air',Polygon()),('slab',bottom),('slab_top',top),
            ('stairs_low',unary_union([bottom,box(0,.5,.5,1)])),
            ('stairs_high',unary_union([bottom,box(.5,.5,1,1)])),
            ('stairs_low_top',unary_union([top,box(0,0,.5,.5)])),
            ('stairs_high_top',unary_union([top,box(.5,0,1,.5)])),('full',box(0,0,1,1))]


def fit(target,required=None):
    # Exact areas avoid per-triangle centroid losses and input triangulation bias.
    choices=[]
    for name,geometry in profiles():
        if required is not None and not geometry.covers(required):continue
        missing=target.difference(geometry).area;extra=geometry.difference(target).area
        choices.append((missing+extra,name,missing,extra))
    if not choices:raise ValueError('Native support cannot be represented')
    return min(choices,key=lambda r:(round(r[0],12),r[1]!='air',r[1]))


def material(name,palette,low,high):
    if name=='full':return palette+'_planks' if palette=='dark_oak' else 'stone_bricks'
    if name in ('slab','slab_top'):return palette+'_'+name
    side=low if name.startswith('stairs_low') else high
    return palette+'_stairs_'+side+('_top' if name.endswith('_top') else '')


def occupied_halves(cells):
    """Native shape occupancy in source-local voxel axes; depth becomes -MC Z."""
    result={}
    for (x,y,z),m in cells.items():
        for dx in (0,1):
            for dy in (0,1):
                for dz in (0,1):
                    include=True
                    if '_stairs_' in m:
                        direction=m.split('_stairs_')[1].removesuffix('_top')
                        high={'west':dx==0,'east':dx==1,'north':dz==1,'south':dz==0}[direction]
                        include=dy==1 or high if m.endswith('_top') else dy==0 or high
                    elif m.endswith('_slab_top'):include=dy==1
                    elif m.endswith('_slab'):include=dy==0
                    if include:result[(2*x+dx,2*y+dy,2*z+dz)]=m
    return result


def assemble(model,*,max_checks=100000):
    from shapely.affinity import translate
    if type(max_checks) is not int or not 1<=max_checks<=100000:
        raise ValueError('Bounded shape review required')
    if model.get('world_placement_eligible') or model.get('geographic_registration') is not None:
        raise ValueError('Only isolated unplaced wing reviews supported')
    length=model['width_check']['elevation_length_m'];depth=model['measurements']['depth_m']
    eaves=model['measurements']['eaves_m'];ridge=model['measurements']['ridge_m'];peak=model['roof_assembly']['ridge_depth_m']
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (length,depth,eaves,ridge,peak)) or not (2<=length<=100 and 1<=depth<=20 and 0<peak<depth and 0<eaves<ridge<=30):
        raise ValueError('Bounded measured wing profile required')
    rows=model['openings']
    if not 1<=len(rows)<=128:raise ValueError('Bounded aperture inventory required')
    holes=[]
    for r in rows:
        pts=r['local_polygon_xz']
        if len(pts)>2048 or any(len(p)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in p) for p in pts):raise ValueError('Bounded aperture polygon required')
        g=Polygon(pts)
        if not g.is_valid or g.area<=0 or not box(0,0,length,eaves).covers(g):raise ValueError('Contained aperture required')
        holes.append((r,g))
    wall=box(0,0,length,eaves).difference(unary_union([g for _,g in holes]))
    mesh=model['wall_mesh'];vertices=mesh['vertices'];triangles=mesh['triangles']
    if len(vertices)>1500 or len(triangles)>500 or any(len(v)!=3 or any(type(n) not in (int,float) or not math.isfinite(n) for n in v) or v[1]!=0 for v in vertices):raise ValueError('Bounded planar wall mesh required')
    faces=[]
    for f in triangles:
        if len(f)!=3 or any(type(i) is not int or not 0<=i<len(vertices) for i in f):raise ValueError('Valid wall triangle required')
        faces.append(Polygon([(vertices[i][0],vertices[i][2]) for i in f]))
    if abs(sum(f.area for f in faces)-wall.area)>1e-7 or unary_union(faces).symmetric_difference(wall).area>1e-7:
        raise ValueError('Wall mesh and aperture review disagree')
    expected=[[0,0,eaves],[length,0,eaves],[0,peak,ridge],[length,peak,ridge],[0,depth,eaves],[length,depth,eaves]]
    if model['roof_mesh']['vertices']!=expected or model['roof_mesh']['triangles']!=[[0,1,3],[0,3,2],[2,3,5],[2,5,4]]:
        raise ValueError('Reviewed two-slope roof mesh required')
    checks=0;cells={};missing_area=extra_area=0;clearance=[];forced_air=set()
    def charge():
        nonlocal checks
        checks+=1
        if checks>max_checks:raise ValueError('Native shape work budget exceeded; no partial output')
    for row,g in holes:
        if row['kind'] not in ('door','archway'):continue
        xmin,ymin,xmax,ymax=g.bounds
        columns=[x for x in range(math.floor(xmin),math.ceil(xmax)) if g.covers(Point(x+.5,.05))]
        if abs(ymin)>1e-7 or not columns or ymax<1.5:raise ValueError('Standing passage cannot be represented at 1:1')
        for x in columns:
            # Two native air blocks are a disclosed clearance quantization, not a changed source opening.
            if not g.covers(Point(x+.5,1.5)):raise ValueError('Passage source does not support standing clearance')
            forced_air.update((x,y,0) for y in (0,1))
        clearance.append({'id':row['id'],'columns':columns,'height_blocks':2,'source_bounds':list(g.bounds),
                          'display_clearance_quantized':True,'physical_clearance_verified':False})
    for x in range(math.ceil(length)):
        for y in range(math.ceil(eaves)):
            charge();target=translate(wall.intersection(box(x,y,x+1,y+1)),xoff=-x,yoff=-y)
            _,name,missing,extra=fit(target)
            if (x,y,0) in forced_air:name='air';missing=target.area;extra=0
            missing_area+=missing;extra_area+=extra
            if name!='air':cells[x,y,0]=material(name,'stone_brick','west','east')
    # A narrow source pier can disappear at a window, disconnecting its base.
    # Preserve a connected half-block strip outside each declared arch passage.
    # Source core intervals exclude every aperture projection over standing height.
    arch_supports=[]
    for passage in clearance:
        row=next(r for r in rows if r['id']==passage['id'])
        if row['kind']!='archway':continue
        for side,x in [('left',min(passage['columns'])-1),('right',max(passage['columns'])+1)]:
            if x<0 or x>=length:raise ValueError('Arch side support is outside reviewed facade')
            projections=[]
            for _,hole in holes:
                charge()
                overlap=hole.intersection(box(x,0,min(x+1,length),2))
                if not overlap.is_empty:
                    lo,_,hi,_=overlap.bounds
                    if hi>lo:projections.append(LineString([(lo,0),(hi,0)]))
            core=LineString([(x,0),(min(x+1,length),0)]).difference(unary_union(projections))
            if core.length<.125:raise ValueError('Arch side lacks representable continuous source masonry')
            widths=[core.intersection(LineString([(x+dx*.5,0),(min(x+(dx+1)*.5,length),0)])).length for dx in (0,1)]
            dx=max(range(2),key=lambda i:(widths[i],-i))
            required=box(dx*.5,0,(dx+1)*.5,1)
            changes=[]
            for y in (0,1):
                charge();target=translate(wall.intersection(box(x,y,x+1,y+1)),xoff=-x,yoff=-y)
                _,name,_,_=fit(target,required)
                before=cells.get((x,y,0),'air');after=material(name,'stone_brick','west','east')
                cells[x,y,0]=after
                if before!=after:changes.append({'cell':[x,y,0],'before':before,'after':after})
            arch_supports.append({'id':row['id'],'side':side,'column':x,'half_column':dx,
                                  'continuous_source_core_width_m':core.length,'native_support_width_m':.5,
                                  'display_quantization':True,'physical_pier_width_verified':False,'changes':changes})
    # Report and withhold disconnected masonry components instead of inventing thin piers.
    wall_half=occupied_halves(cells);todo=set(wall_half);groups=[]
    while todo:
        start=todo.pop();group={start};queue=[start]
        while queue:
            p=queue.pop()
            for axis in range(3):
                for step in (-1,1):
                    q=list(p);q[axis]+=step;q=tuple(q)
                    if q in todo:todo.remove(q);group.add(q);queue.append(q)
        groups.append(group)
    withheld=[]
    for group in groups:
        if any(p[1]>=2*math.floor(eaves)-1 for p in group):continue
        blocks=sorted({tuple(v//2 for v in p) for p in group})
        if any(occupied_halves({p:cells[p]}).keys()-group for p in blocks):raise ValueError('Ambiguous disconnected native block')
        withheld.append({'block_cells':blocks,'half_cells':len(group),'status':'disconnected_quantized_masonry_withheld'})
        for p in blocks:cells.pop(p)
    wall_cells=set(cells);roof_cells=set()
    wall_geometry=unary_union([box(x/2,y/2,(x+1)/2,(y+1)/2) for x,y,z in occupied_halves(cells)])
    missing_area=wall.difference(wall_geometry).area;extra_area=wall_geometry.difference(wall).area
    # Fit roof top surfaces rather than asking centroid samples to retain a thin band.
    # Native stairs provide two half-metre treads without enlarging the building scale.
    height=lambda z:eaves+(ridge-eaves)*(z/peak if z<=peak else (depth-z)/(depth-peak))
    roof_shapes={};roof_top=[];roof_proofs=[]
    for z in range(math.ceil(depth)):
        end=min(z+1,depth);stations=[z+(end-z)*.25,z+(end-z)*.75];values=[height(s) for s in stations];choices=[]
        rise=height(end)-height(z)
        for y in range(math.floor(min(values))-1,math.ceil(max(values))+1):
            for name,levels in [('slab',[.5,.5]),('slab_top',[1,1]),('stairs_low',[1,.5]),('stairs_high',[.5,1])]:
                if abs(rise)>=.5 and name!=('stairs_high' if rise>0 else 'stairs_low'):continue
                charge();errors=[y+levels[i]-values[i] for i in (0,1)]
                choices.append((sum(e*e for e in errors),name,y,levels,errors))
        _,name,y,levels,errors=min(choices,key=lambda c:(round(c[0],12),c[1],c[2]))
        roof_shapes[z,y]=material(name,'dark_oak','south','north')
        middle=z+.5
        roof_top.extend([(z,y+levels[0]),(min(middle,end),y+levels[0])])
        if end>middle:roof_top.extend([(middle,y+levels[1]),(end,y+levels[1])])
        roof_proofs.append({'depth_column':z,'height_block':y,'native_material':roof_shapes[z,y],
                            'source_sample_heights_m':values,'sample_error_m':errors})
    surface=LineString([(0,eaves),(peak,ridge),(depth,eaves)])
    roof_distance=surface.hausdorff_distance(LineString(roof_top))
    roof_bound=math.sqrt(.5**2+.5**2)
    if roof_distance>roof_bound:raise ValueError('Quantized roof surface exceeds half-cell diagonal allowance')
    shapes=[translate(dict(profiles())[next(n for n,_ in profiles() if n!='air' and material(n,'dark_oak','south','north')==m)],xoff=z,yoff=y)
            for (z,y),m in sorted(roof_shapes.items())]
    if any(a.distance(b)>1e-8 for a,b in zip(shapes,shapes[1:])):
        raise ValueError('Native roof columns leave an open profile gap')
    aliases=[]
    for x in range(math.ceil(length)):
        if min(x+1,length)-x<.5:continue
        for (z,y),m in roof_shapes.items():
            if (x,y,z) in cells:aliases.append((x,y,z));continue
            cells[x,y,z]=m;roof_cells.add((x,y,z))
    half=occupied_halves(cells)
    for support in arch_supports:
        hx=2*support['column']+support['half_column']
        if any((hx,hy,hz) not in half for hy in range(4) for hz in (0,1)):
            raise ValueError('Arch support disappeared during native assembly')
        if not any((hx,4,hz) in half for hz in (0,1)):
            raise ValueError('Arch support does not contact its head')
    arch_heads=[]
    for passage in clearance:
        row=next(r for r in rows if r['id']==passage['id'])
        if row['kind']!='archway':continue
        start=2*min(passage['columns']);end=2*(max(passage['columns'])+1)
        heights=[next((hy*.5 for hy in range(2*math.ceil(eaves)) if (hx,hy,0) in half),math.ceil(eaves))
                 for hx in range(start,end)]
        highest=max(p[1] for p in row['local_polygon_xz'])
        apex=sum(p[0] for p in row['local_polygon_xz'] if p[1]==highest)/sum(p[1]==highest for p in row['local_polygon_xz'])
        middle=min(len(heights)-1,max(0,math.floor(2*apex)-start))
        if any(a>b for a,b in zip(heights[:middle],heights[1:middle+1])) or any(a<b for a,b in zip(heights[middle:],heights[middle+1:])):
            raise ValueError('Quantized arch head reverses its source crown')
        arch_heads.append({'id':row['id'],'half_column_clearance_m':heights,'crown_profile_order_verified':True})
    if any(p in half for x,y,z in forced_air for p in [(2*x+dx,2*y+dy,2*z+dz) for dx in (0,1) for dy in (0,1) for dz in (0,1)]):
        raise ValueError('Native shape obstructs declared passage clearance')
    return cells,{'version':VERSION,'world_blocks_per_source_metre':1,'shape_resolution_m':.5,'source_mesh_changed':False,
                  'material_counts':dict(Counter(cells.values())),'wall_cells':len(wall_cells),'roof_cells':len(roof_cells),
                  'wall_profile_missing_area_m2':missing_area,'wall_profile_excess_area_m2':extra_area,
                  'disconnected_masonry_withheld':withheld,'roof_top_profile_hausdorff_m':roof_distance,
                  'roof_profile_error_bound_m':roof_bound,'roof_source_profile_within_quantization_bound':True,'roof_profile_proofs':roof_proofs,
                  'roof_adjacent_profile_contact_verified':True,
                  'roof_shell_thickness_display_m':[.5,1],'wall_roof_aliases':aliases,'passage_clearance':clearance,
                  'native_passage_air_verified':True,'glass_proxy_cells':[],'glazing_policy':'disabled_by_user','checks':checks,
                  'arch_side_supports':arch_supports,'arch_side_support_contact_verified':True,
                  'arch_head_profiles':arch_heads,
                  'limitations':['Partial facade and two-slope roof only; rear/end walls and measured construction thickness are unresolved.',
                                 'Native slabs/stairs and passage clearance quantize source silhouettes; they do not establish physical aperture accuracy.',
                                 'Glazing is disabled by user instruction; window voids remain open.',
                                 'Disconnected quantized masonry is withheld explicitly; source mesh remains unchanged.'],
                  'park_world_blocks_added':0,'world_placement_eligible':False}
