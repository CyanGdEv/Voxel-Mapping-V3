"""AL08 dormer fronts with explicitly provisional depth and shed-roof joins."""
import copy,math
from shapely.geometry import Polygon,box
from shapely.ops import unary_union
from shapely.affinity import translate
from .wing_shell_study import solid
from .wing_block_shapes import fit,material


def projected(mesh,axes):
    v=mesh['vertices']
    return unary_union([p for f in mesh['triangles'] if (p:=Polygon([(v[i][axes[0]],v[i][axes[1]]) for i in f])).area>1e-10])


def apply(model,cells,seed):
    if seed.get('version')!='courtyard-west-dormer-study-v1' or seed.get('review_hypotheses_acknowledged') is not True:raise ValueError('Explicit dormer hypothesis required')
    if model.get('facade_study',{}).get('source_pdf_sha256')!=seed.get('source_pdf_sha256'):raise ValueError('Dormers must use the reviewed existing facade source')
    if seed.get('depth_measured') is not False:raise ValueError('Dormer depth must remain an explicit hypothesis')
    for name,lo,hi in [('depth_display_m',.5,1.5),('front_overhang_display_m',.1,.25),('cheek_thickness_display_m',.1,.25),('roof_vertical_thickness_display_m',.1,.5)]:
        value=seed.get(name)
        if type(value) not in (int,float) or not math.isfinite(value) or not lo<=value<=hi:raise ValueError('Bounded dormer display dimension required')
    if len(seed.get('dormers',[]))!=2 or {r['id'] for r in seed['dormers']}!={'w2.12','w2.13'}:raise ValueError('Two reviewed AL08 dormers required')
    result=copy.deepcopy(model);output=dict(cells);unit=2384/1800*50*.0254/72
    roof=next((c for c in result['components'] if c['id']=='roof_west_range'),None)
    wall=next((c for c in result['components'] if c['id']=='west_courtyard_elevation_wall'),None)
    if not roof or not wall:raise ValueError('Source west roof and reviewed facade required')
    roof_profile=projected(roof['mesh'],(0,2));wall_profile=projected(wall['mesh'],(1,2))
    vertices=roof['mesh']['vertices'];ymin=min(v[1] for v in vertices);ymax=max(v[1] for v in vertices)
    depth=seed['depth_display_m'];overhang=seed['front_overhang_display_m'];thickness=seed['cheek_thickness_display_m'];rt=seed['roof_vertical_thickness_display_m']
    eave=max(z for x,z in roof_profile.exterior.coords if abs(x)<1e-7)
    def roof_height(x):
        line=roof_profile.intersection(box(x-1e-7,-100,x+1e-7,100))
        if line.is_empty:raise ValueError('Dormer rear misses source roof')
        return line.bounds[3]
    back=roof_height(-depth);eaves=model['facade_study']['wall_height_from_view_m']
    rows=[];voids=[];minimums=[];cut_intervals=[];front_scope=set()
    for r in seed['dormers']:
        a,b,c,d=r['outer_pixels'];wa,wb,wc,wd=r['window_pixels']
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in (a,b,c,d,wa,wb,wc,wd)) or not (1100<=a<wa<wc<c<=1450 and 530<=b<wb<wd<d<=595):raise ValueError('Dormer silhouette outside reviewed view')
        lo=(a-1680)*unit;hi=(c-1680)*unit;head=(733-b)*unit
        opening=box((wa-1680)*unit,(733-wd)*unit,(wc-1680)*unit,(733-wb)*unit)
        if not ymin<lo<hi<ymax or not eave<head<back:raise ValueError('Dormer front cannot join source roof at assumed depth')
        wall_profile=wall_profile.union(box(lo,eaves,hi,head)).difference(opening)
        cut_intervals.append((lo,hi))
        # The cheek is the wedge between the existing roof and the shed cap.
        cheek=Polygon([(0,eave),(0,head),(-depth,back)])
        for side,(ll,hh) in enumerate(((lo,lo+thickness),(hi-thickness,hi))):
            result['components'].append({'id':r['id']+'_dormer_cheek_'+str(side),'role':'wall','colour':'859caf',
                                         'evidence':'source front; assumed cheek thickness and dormer depth',
                                         'mesh':solid(cheek,1,ll,hh)})
        shed=Polygon([(-depth,back),(overhang,head), (overhang,head-rt),(-depth,back-rt)])
        result['components'].append({'id':'roof_dormer_'+r['id'],'role':'roof','colour':'775338',
                                     'evidence':'source front cap height; assumed shed-roof depth and rear junction',
                                     'mesh':solid(shed,1,lo,hi)})
        cols=[z for z in range(math.floor(opening.bounds[0]),math.ceil(opening.bounds[2])) if opening.bounds[0]<=z+.5<=opening.bounds[2]]
        if not cols:raise ValueError('Dormer has no native window centre column')
        for z in range(math.floor(lo),math.ceil(hi)):
            if min(z+1,hi)-max(z,lo)<.2:continue
            for x in (-1,0):
                for y in (3,4):front_scope.add((x,y,z))
                # Register the additional overhang columns for slab conversion.
                output.setdefault((x,math.ceil(back),z),'dark_oak_slab')
        for z in cols:
            for x in (-1,0):
                half_lo=math.ceil(opening.bounds[1]*2);half_hi=math.ceil(opening.bounds[3]*2)
                voids.extend([[x,z,h] for h in range(half_lo,half_hi)])
                minimums.append({'column':[x,z],'minimum_cap_bottom_m':half_hi/2})
        rows.append({'id':r['id'],'source_outer_pixels':r['outer_pixels'],'source_window_pixels':r['window_pixels'],
                     'front_outer_depth_height_m':[lo,hi,eaves,head],'window_depth_height_m':list(opening.bounds),
                     'native_window_columns':cols,'depth_display_m':depth,'depth_measured':False})
    wall['mesh']=solid(wall_profile,0,-.2,.2)
    for pos in front_scope:
        x,y,z=pos;target=translate(wall_profile.intersection(box(z,y,z+1,y+1)),xoff=-z,yoff=-y)
        if target.geom_type not in ('Polygon','MultiPolygon'):
            target=unary_union([p for p in getattr(target,'geoms',[]) if p.geom_type in ('Polygon','MultiPolygon') and p.area>0])
            if target.is_empty:target=Polygon()
        _,name,_,_=fit(target)
        # Opening cells are intentionally recut; unrelated model cells remain intact.
        if name=='air':output.pop(pos,None)
        else:output[pos]=material(name,'stone_brick','south','north')
    result['components'].remove(roof)
    boundaries=sorted({ymin,ymax,*[v for pair in cut_intervals for v in pair]})
    for i,(lo,hi) in enumerate(zip(boundaries,boundaries[1:])):
        profile=roof_profile
        if any(a<(lo+hi)/2<b for a,b in cut_intervals):profile=profile.difference(box(-depth,-100,1,100))
        if not profile.is_empty:
            result['components'].append({'id':'roof_west_segment_'+str(i),'role':'roof','colour':'775338',
                                         'evidence':'original roof band split only at provisional dormer junctions',
                                         'mesh':solid(profile,1,lo,hi)})
    result['roof_window_void_halves']=voids;result['roof_minimum_cap_bottoms']=minimums
    result['dormer_study']={'source_pdf_sha256':seed['source_pdf_sha256'],'dormers':rows,'depth_measured':False}
    result['facade_study']['withheld']=[]
    result['assumptions'].append('West dormer fronts are sampled from AL08; depth, cheek construction and shed-roof rear connections are explicit display hypotheses.')
    audit={'dormers_built':2,'depth_measured':False,'window_void_column_halves':len(voids),
           'source_window_ids':[r['id'] for r in rows],'native_window_columns':[r['native_window_columns'] for r in rows],
           'west_dormers_withheld':0}
    return result,output,audit
