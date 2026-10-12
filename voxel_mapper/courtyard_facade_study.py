"""Explicit west façade silhouette and provisional lobby-closure correction."""
import copy,hashlib,math
from pathlib import Path
from shapely.geometry import Polygon,box
from shapely.ops import unary_union
from shapely.affinity import translate
from .wing_shell_study import solid
from .wing_block_shapes import fit,material,occupied_halves


def validate_source(seed,path):
    import fitz
    if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=seed['source_pdf_sha256']:raise ValueError('Elevation PDF checksum changed')
    with fitz.open(path) as doc:
        page=doc[0];text=''.join(page.get_text().split())
        if ''.join(seed['caption'].split()) not in text:raise ValueError('Existing elevation caption missing')
        if page.rect.width!=2384:raise ValueError('Elevation page frame changed')
        pix=page.get_pixmap(matrix=fitz.Matrix(1800/page.rect.width,1800/page.rect.width))
        if hashlib.sha256(pix.samples).hexdigest()!=seed['source_render_samples_sha256']:raise ValueError('Elevation render changed')


def footprint(mesh):
    vertices=mesh['vertices']
    return unary_union([p for f in mesh['triangles'] if (p:=Polygon([(vertices[i][0],vertices[i][1]) for i in f])).area>1e-10])


def apply(model,cells,seed):
    if seed.get('version')!='courtyard-west-facade-study-v1' or seed.get('review_hypotheses_acknowledged') is not True:raise ValueError('Explicit façade review required')
    if seed.get('view_scale_denominator')!=50 or seed.get('raster_width')!=1800 or seed.get('page_width_points')!=2384:raise ValueError('Pinned per-view scale required')
    if not 1<=len(seed.get('openings',[]))<=32:raise ValueError('Opening budget exceeded')
    if (seed.get('floor_pixel_y'),seed.get('eave_pixel_y'),seed.get('right_anchor_pixel_x'),seed.get('facade_local_x_m'),seed.get('wall_display_thickness_m'))!=(733,564,1680,0,.4):raise ValueError('Reviewed façade frame changed')
    unit=2384/1800*50*.0254/72
    def point(p):
        if len(p)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in p) or not 392<=p[0]<=1680 or not 564<=p[1]<=733:raise ValueError('Opening outside bounded façade view')
        return ((p[0]-1680)*unit,(733-p[1])*unit)
    holes=[]
    for row in seed['openings']:
        if not 4<=len(row['pixel_ring'])<=64 or row['kind'] not in ('door','window','archway'):raise ValueError('Invalid opening trace')
        p=Polygon([point(v) for v in row['pixel_ring']])
        if not p.is_valid or p.area<=0:raise ValueError('Invalid opening polygon')
        holes.append((row,p))
    if len({r['id'] for r,p in holes})!=len(holes):raise ValueError('Duplicate source opening')
    result=copy.deepcopy(model);output=dict(cells);components=[]
    # The existing lobby trace crosses only an explicitly temporary joining cap.
    access=seed['lobby_access']
    if access['closure_component_id']!='left_junction_cap' or access['native_cells_to_clear']!=[[0,0,1],[0,1,1]] or access['source_plan_pixel_rectangle']!=[1060,274,1100,315] or access['clear_height_m']!=2.2:raise ValueError('Lobby access review changed')
    plan_unit=2*unit;lo=(1060-1059)*plan_unit;hi=(1100-1059)*plan_unit
    cap_found=False
    for c in result['components']:
        if c['id']==access['closure_component_id']:
            vertices=c['mesh']['vertices'];xs=[v[0] for v in vertices];profile=Polygon([(v[1],v[2]) for v in vertices]).convex_hull
            if not profile.is_valid or max(xs)>.500001 or min(xs)!=0:raise ValueError('Unexpected joining cap geometry')
            c['mesh']=solid(profile.difference(box(lo,0,hi,2.2)),0,min(xs),max(xs));c['evidence']='Plan-sampled doorway through provisional north joining-plane closure';cap_found=True
        components.append(c)
    if not cap_found:raise ValueError('Temporary joining cap not found')
    cleared=[]
    for p in map(tuple,access['native_cells_to_clear']):
        if output.get(p)!='stone_bricks':raise ValueError('Lobby cut would change something other than temporary masonry')
        cleared.append({'cell':list(p),'old_material':output.pop(p)})
    # Replace the earlier approximate front band, preserving every other wall/floor.
    lower=(392-1680)*unit;upper=0;strip=box(-.200001,lower,.200001,upper)
    retained=[]
    for c in components:
        if c['id'].startswith('plan_outer_wall_main_slice_'):
            mesh=c['mesh'];p=footprint(mesh).difference(strip);zs=[v[2] for v in mesh['vertices']]
            geoms=[p] if p.geom_type=='Polygon' else list(p.geoms)
            for i,part in enumerate(geoms):
                if part.area>1e-8:
                    new=copy.deepcopy(c);new['id']=c['id']+'_outside_west_'+str(i);new['mesh']=solid(part,2,min(zs),max(zs));retained.append(new)
        else:retained.append(c)
    height=(733-564)*unit
    profile=box(lower,0,upper,height).difference(unary_union([p for r,p in holes]))
    retained.append({'id':'west_courtyard_elevation_wall','role':'wall','colour':'859caf',
                     'evidence':'Existing AL08 view at 1:50; manually traced openings and junction anchor hypothesis',
                     'mesh':solid(profile,0,-.2,.2)})
    result['components']=retained
    changed=[]
    for x in (-1,0):
        for z in range(math.floor(lower),0):
            for y in range(math.ceil(height)):
                pos=(x,y,z);old=output.get(pos)
                if old and old.startswith('dark_oak'):raise ValueError('Façade edit reached roof cell')
                target=translate(profile.intersection(box(z,y,z+1,y+1)),xoff=-z,yoff=-y)
                _,name,_,_=fit(target)
                new=material(name,'stone_brick','south','north') if name!='air' else None
                if new is None:output.pop(pos,None)
                else:output[pos]=new
                if old!=new:changed.append({'cell':list(pos),'before':old,'after':new})
    # Source doors and the arch keep two full standing-air blocks in centre columns.
    passage_rows=[]
    for row,p in holes:
        if row['kind'] not in ('door','archway'):continue
        columns=[z for z in range(math.floor(p.bounds[0]),math.ceil(p.bounds[2])) if p.covers(box(z+.5,0,z+.500001,2))]
        if not columns:raise ValueError('Source doorway too narrow for standing preview')
        for z in columns:
            for x in (-1,0):
                for y in (0,1):output.pop((x,y,z),None)
        passage_rows.append({'id':row['id'],'native_front_columns':columns,'standing_front_air_verified':True})
    half=occupied_halves(output)
    if any((dx,y,2+dz) in half for dx in (0,1) for y in range(4) for dz in (0,1)):raise ValueError('Lobby standing gap remains blocked')
    region={(x,y,z) for x in (-1,0) for z in range(math.floor(lower),0) for y in range(math.ceil(height))}
    allowed=region|{tuple(r['cell']) for r in cleared}
    if any(cells.get(p)!=output.get(p) for p in set(cells)|set(output) if p not in allowed):raise ValueError('Façade edit changed unrelated native cells')
    changed=[{'cell':list(p),'before':cells.get(p),'after':output.get(p)} for p in sorted(region) if cells.get(p)!=output.get(p)]
    result['facade_study']={'source_pdf_sha256':seed['source_pdf_sha256'],'registration_class':seed['registration_class'],
                            'render_samples_sha256':seed['source_render_samples_sha256'],'openings':[dict(r,local_polygon_depth_height=list(p.exterior.coords)) for r,p in holes],
                            'withheld':seed['withheld'],'wall_height_from_view_m':height,'view_scale_denominator':50,
                            'sheet_title_scale_denominator':100,'lobby_clearance_verified':True}
    result['assumptions'].append('West facade uses a manually reviewed shared-junction anchor and raster silhouettes. Dormers, tower correspondence and physical opening registration remain unresolved.')
    audit={'west_source_openings':len(holes),'west_dormers_withheld':len(seed['withheld']),
           'west_wall_height_from_view_m':height,'lobby_cells_cleared':cleared,'lobby_standing_air_verified':True,
           'west_front_passages':passage_rows,'facade_cell_changes':changed,'source_registered_to_park':False}
    return result,output,audit
