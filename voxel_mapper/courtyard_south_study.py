"""Source-reviewed south frontage, split roofs and explicit tower/depth hypotheses."""
import copy,hashlib,math
from pathlib import Path
from shapely.geometry import Polygon,box,Point
from shapely.ops import unary_union
from shapely.affinity import translate
from .wing_shell_study import solid
from .wing_block_shapes import fit,material,occupied_halves
from .courtyard_facade_study import footprint


def validate_source(seed,path):
    import fitz
    if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=seed['source_pdf_sha256']:raise ValueError('South PDF checksum changed')
    with fitz.open(path) as doc:
        page=doc[0]
        if ''.join(seed['caption'].split()) not in ''.join(page.get_text().split()):raise ValueError('Existing south caption required')
        pix=page.get_pixmap(matrix=fitz.Matrix(1800/page.rect.width,1800/page.rect.width))
        if page.rect.width!=2384 or hashlib.sha256(pix.samples).hexdigest()!=seed['source_render_samples_sha256']:raise ValueError('South source frame changed')


def apply(model,cells,seed):
    if seed.get('version')!='courtyard-south-assembly-study-v1' or seed.get('hypotheses_acknowledged') is not True or seed.get('depths_measured') is not False:raise ValueError('Explicit south depth/assembly hypothesis required')
    if (seed.get('view_scale_denominator'),seed.get('floor_reference_pixel_y'),seed.get('left_anchor_pixel_x'),seed.get('left_anchor_plan_pixel_y'),seed.get('front_plan_pixel_x'),seed.get('rear_plan_pixel_x'))!=(50,558,165,991,415,222):raise ValueError('Reviewed south view frame required')
    for key,lo,hi in [('wall_thickness_m',.1,.5),('curtain_setback_m',.5,3),('canopy_overhang_m',.1,1.5),('tower_depth_m',1.5,3),('roof_vertical_thickness_m',.1,.5)]:
        v=seed.get(key)
        if type(v) not in (int,float) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError('Bounded south display dimension required')
    if len(seed.get('front_sections',[]))!=3 or len(seed.get('towers',[]))!=2 or not 1<=len(seed.get('openings',[]))<=32 or len(seed.get('curtain_slits',[]))!=3:raise ValueError('Bounded source south inventory required')
    if seed.get('tower_setback_from_rear_m')!=0 or {r['id'] for r in seed['front_sections']}!={'main','arch','low'} or not 1<=len(seed['curtain']['crest_intervals'])<=16:raise ValueError('Reviewed south assembly identities required')
    unit=2384/1800*50*.0254/72;pu=2*unit;length=(991-305)*pu;front=(415-1059)*pu;rear=(222-1059)*pu
    wall=seed['wall_thickness_m'];rt=seed['roof_vertical_thickness_m'];setback=seed['curtain_setback_m'];overhang=seed['canopy_overhang_m']
    def xx(u):
        if type(u) not in (int,float) or not math.isfinite(u) or not 165<=u<=1546:raise ValueError('South x trace outside reviewed view')
        return length-(u-165)*unit
    def hh(v):
        if type(v) not in (int,float) or not math.isfinite(v) or not 100<=v<=558:raise ValueError('South height outside reviewed view')
        return (558-v)*unit
    def region(interval):
        a,b=map(xx,interval)
        if a<=b:raise ValueError('Source south direction/interval changed')
        return max(0,b),min(length,a)
    def opening(row):
        if not 4<=len(row['pixel_ring'])<=64:raise ValueError('Opening vertex budget exceeded')
        p=Polygon([(xx(a),hh(b)) for a,b in row['pixel_ring']])
        if not p.is_valid or p.area<=0:raise ValueError('Invalid south opening')
        return p
    openings=[(r,opening(r)) for r in seed['openings']]
    if len({r['id'] for r,p in openings})!=len(openings) or any(r['kind'] not in ('window','door','archway') for r,p in openings):raise ValueError('Unique south source openings required')
    result=copy.deepcopy(model);output=dict(cells);components=[];section_rows=[];roof_sources=[];roof_candidates=[];blocked_roof_columns=set()
    sections=[]
    for r in seed['front_sections']:
        lo,hi=region(r['pixel_x']);sections.append((r,lo,hi,hh(r['wall_top_pixel_y'])))
    if abs(sum(hi-lo for r,lo,hi,h in sections)-length)>1e-7:raise ValueError('South sections must cover the existing frontage exactly')
    ordered=sorted((lo,hi) for r,lo,hi,h in sections)
    if any(abs(a[1]-b[0])>1e-7 for a,b in zip(ordered,ordered[1:])):raise ValueError('South section overlap or gap')
    profile=unary_union([box(lo,0,hi,h) for r,lo,hi,h in sections]).difference(unary_union([p for r,p in openings]))
    strip=box(0,front-wall/2-1e-6,length,front+wall/2+1e-6)
    for c in result['components']:
        if c['id']=='roof_south_range' or c['id'].startswith('roof_join_cap_south_range_'):continue
        if c['id'].startswith('plan_outer_wall_main_slice_'):
            p=footprint(c['mesh']).difference(strip);zs=[v[2] for v in c['mesh']['vertices']]
            for i,g in enumerate([p] if p.geom_type=='Polygon' else getattr(p,'geoms',[])):
                if g.geom_type=='Polygon' and g.area>1e-8:
                    new=copy.deepcopy(c);new['id']=c['id']+'_outside_south_'+str(i);new['mesh']=solid(g,2,min(zs),max(zs));components.append(new)
        else:components.append(c)
    def add(id,p,axis,lo,hi,role='wall',colour='859caf',evidence='source frontage; depth and construction are display hypotheses'):
        if p.is_empty:return
        for i,g in enumerate([p] if p.geom_type=='Polygon' else p.geoms):
            if g.geom_type=='Polygon' and g.area>1e-8:
                components.append({'id':id+'_'+str(i),'role':role,'colour':colour,'evidence':evidence,'mesh':solid(g,axis,lo,hi)})
    add('south_courtyard_elevation_wall',profile,1,front-wall/2,front+wall/2)
    # Remove only the old upper joining caps in this range; rebuild them at the
    # split source roof levels. Ground walls, room partitions and floors survive.
    for x in (0,math.ceil(length)-1):
        for z in range(math.floor(rear),math.ceil(front)):
            for y in range(4,7):
                if output.get((x,y,z))=='stone_bricks':output.pop((x,y,z))
    def area_only(p):
        if p.geom_type in ('Polygon','MultiPolygon'):return p
        return unary_union([g for g in getattr(p,'geoms',[]) if g.geom_type in ('Polygon','MultiPolygon') and g.area>0])
    def put_profile(p,axis,fixed,minimum,maximum,replace=True):
        a,b,c,d=p.bounds
        for along in range(math.floor(a),math.ceil(c)):
            for y in range(math.floor(b),math.ceil(d)):
                target=area_only(translate(p.intersection(box(along,y,along+1,y+1)),xoff=-along,yoff=-y))
                _,name,_,_=fit(target)
                sides=('west','east') if axis==1 else ('south','north')
                m=material(name,'stone_brick',*sides) if name!='air' else None
                for coord in fixed:
                    pos=(along,y,coord) if axis==1 else (coord,y,along)
                    if minimum<=along+.5<=maximum:
                        if not replace and pos in output and not output[pos].startswith('dark_oak'):continue
                        if m is None:
                            if replace:output.pop(pos,None)
                        else:output[pos]=m
    front_columns=[math.floor(front),math.floor(front)+1]
    put_profile(profile,1,front_columns,0,length)
    old_eave=3.9733749
    for r,lo,hi,h in sections:
        if r['id']!='low':
            eave=hh(r['roof_eave_pixel_y']);ridge=hh(r['roof_ridge_pixel_y']);back_plane=rear;front_plane=front
        else:
            if r.get('hidden_roof_measured') is not False:raise ValueError('Hidden south roof must remain a hypothesis')
            eave=r['hidden_roof_eave_display_m'];ridge=r['hidden_roof_ridge_display_m'];back_plane=rear;front_plane=front-setback
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in (eave,ridge)):raise ValueError('Finite hidden-roof display heights required')
        if not 2<=eave<ridge<=10:raise ValueError('Ordered south roof heights required')
        peak=(back_plane+front_plane)/2
        rp=Polygon([(back_plane,eave),(peak,ridge),(front_plane,eave),(front_plane,eave-rt),(peak,ridge-rt),(back_plane,eave-rt)])
        add('roof_south_'+r['id'],rp,0,lo,hi,'roof','775338');roof_sources.append((lo,hi,back_plane,front_plane,eave,ridge))
        roof_candidates.append((box(lo,back_plane,hi,front_plane),False))
        if eave>old_eave:
            upper=box(lo,old_eave,hi,eave)
            add('south_rear_upper_closure_'+r['id'],upper,1,rear-wall/2,rear+wall/2,evidence='provisional unreviewed rear upper closure')
            put_profile(box(lo,3,hi,eave),1,[math.floor(rear),math.floor(rear)+1],lo,hi,replace=False)
        gable=Polygon([(back_plane,eave),(front_plane,eave),(peak,ridge)])
        for side,x in enumerate((lo,hi)):
            start=x if side==0 else x-wall
            add('roof_join_cap_south_'+r['id']+'_'+str(side),gable,0,start,start+wall,'roof')
            xxcol=math.floor(x) if side==0 else math.ceil(x)-1
            put_profile(gable,0,[xxcol],back_plane,front_plane,replace=False)
        section_rows.append({'id':r['id'],'local_frontage_m':[lo,hi],'front_wall_top_m':h,'roof_eave_m':eave,'roof_ridge_m':ridge,'roof_depth_measured':False})
        if r['id']=='low':
            fh=hh(r['canopy_front_pixel_y']);bh=hh(r['canopy_back_pixel_y']);back=front-setback;lip=front+overhang
            canopy=Polygon([(back,bh),(lip,fh),(lip,fh-rt),(back,bh-rt)])
            add('roof_south_canopy',canopy,0,lo,hi,'roof','775338');roof_candidates.append((box(lo,back,hi,lip),False))
    # Source-visible curtain is separated from the low storefront/canopy by a
    # bounded setback hypothesis. Ornamental slit silhouettes stay in the mesh;
    # they are deliberately not certified as one-metre native apertures.
    cr=seed['curtain'];clo,chi=region(cr['pixel_x']);valley=hh(cr['valley_pixel_y']);crest=hh(cr['crest_pixel_y'])
    if not 0<valley<crest<10:raise ValueError('Ordered curtain parapet heights required')
    curtain=box(clo,0,chi,valley)
    for interval in cr['crest_intervals']:
        a,b=region(interval);curtain=curtain.union(box(a,valley,b,crest))
    slits=[(r,opening(r)) for r in seed['curtain_slits']]
    curtain_plane=front-setback
    add('south_curtain_wall',curtain.difference(unary_union([p for r,p in slits])),1,curtain_plane-wall/2,curtain_plane+wall/2)
    put_profile(curtain,1,[math.floor(curtain_plane),math.floor(curtain_plane)+1],clo,chi)
    for x in range(math.floor(clo),math.ceil(chi)):
        for z in (math.floor(curtain_plane),math.floor(curtain_plane)+1):
            if any((x,y,z) in output and not output[x,y,z].startswith('dark_oak') for y in range(4,math.ceil(crest))):blocked_roof_columns.add((x,z))
    tower_rows=[]
    for r in seed['towers']:
        lo,hi=region(r['pixel_x']);shaft=hh(r['shaft_top_pixel_y']);crest=hh(r['crest_pixel_y']);td=seed['tower_depth_m'];outer=box(lo,rear,hi,rear+td);inside=outer.buffer(-wall)
        if inside.is_empty or not 8<=shaft<crest<=12:raise ValueError('Bounded hollow south tower required')
        add(r['id']+'_shaft',outer.difference(inside),2,0,shaft)
        parapet=outer.difference(inside)
        # Four corner merlons follow the two-edge/source-centre gap silhouette.
        merlon=min(.8,(hi-lo)/3)
        blocks=unary_union([box(a,b,a+merlon,b+merlon) for a in (lo,hi-merlon) for b in (rear,rear+td-merlon)])
        add(r['id']+'_merlons',blocks,2,shaft,crest)
        add('roof_'+r['id'],inside,2,shaft-rt,shaft,'roof','775338');roof_candidates.append((inside,True))
        for x in range(math.floor(lo),math.ceil(hi)):
            for z in range(math.floor(rear),math.ceil(rear+td)):
                cell=box(x,z,x+1,z+1)
                centre=Point(x+.5,z+.5)
                if parapet.intersection(cell).area>.05 and not inside.covers(centre):
                    blocked_roof_columns.add((x,z))
                    for y in range(math.ceil(shaft)):output[x,y,z]='stone_brick_slab' if shaft-y<.75 else 'stone_bricks'
                if blocks.intersection(cell).area>.05 and not inside.covers(centre):
                    blocked_roof_columns.add((x,z))
                    for y in range(math.floor(shaft),math.ceil(crest)):output[x,y,z]='stone_brick_slab' if crest-y<.75 else 'stone_bricks'
        tower_rows.append({'id':r['id'],'local_footprint':list(outer.exterior.coords),'shaft_top_m':shaft,'crest_m':crest,'depth_measured':False})
    # Register roof coverage columns, including the new canopy overhang. Their
    # elevations are resampled from exact component surfaces by slab conversion.
    for pos in list(output):
        if (pos[0],pos[2]) in blocked_roof_columns and output[pos].startswith('dark_oak'):output.pop(pos)
    for p,interior_only in roof_candidates:
        a,b,c,d=p.bounds
        for x in range(math.floor(a),math.ceil(c)):
            for z in range(math.floor(b),math.ceil(d)):
                if (x,z) not in blocked_roof_columns and p.intersection(box(x,z,x+1,z+1)).area>.08 and (not interior_only or p.covers(Point(x+.5,z+.5))):
                    output.setdefault((x,12,z),'dark_oak_slab')
    passages=[]
    for r,p in openings:
        if r['kind'] not in ('door','archway'):continue
        lo,_,hi,_=p.bounds;cols=[x for x in range(math.floor(lo),math.ceil(hi)) if lo<=x+.5<=hi]
        if not cols:raise ValueError('South passage needs a native centre column')
        for x in cols:
            for z in front_columns:
                for y in (0,1):output.pop((x,y,z),None)
        passages.append({'id':r['id'],'native_frontage_columns':cols,'standing_front_air_verified':True})
    arch=next(p for r,p in openings if r['kind']=='archway');archcols=[x for x in range(math.floor(arch.bounds[0]),math.ceil(arch.bounds[2])) if arch.bounds[0]<=x+.5<=arch.bounds[2]]
    occ=occupied_halves(output)
    for x in archcols:
        for z in range(math.floor(rear),math.floor(front)+2):
            if any((2*x+dx,h,2*z+dz) in occ for dx in (0,1) for dz in (0,1) for h in range(4)):raise ValueError('South arch through-depth passage obstructed')
    result['components']=components
    result['require_roof_masonry_contact']=True
    result['south_study']={'source_pdf_sha256':seed['source_pdf_sha256'],'source_render_samples_sha256':seed['source_render_samples_sha256'],'sections':section_rows,'towers':tower_rows,'curtain_plane_m':curtain_plane,'front_plane_m':front,'source_openings':[dict(r,local_polygon_frontage_height=list(p.exterior.coords)) for r,p in openings],'curtain_slits_native_withheld':[r['id'] for r,p in slits],'depths_measured':False,'floor_reference_is_survey_datum':False,'corner_towers_withheld':seed['corner_towers_withheld']}
    result['assumptions'].append('South frontage heights and openings are raster-sampled AL07 silhouettes. Tower depth, curtain setback, hidden right roof and roof joins are explicit hypotheses. Source floor reference does not establish a level survey datum.')
    result.setdefault('slab_conversion_passages',[]).extend({'native_columns':[(x,z) for z in range(math.floor(rear),math.floor(front)+2)]} for x in archcols)
    audit={'south_openings':len(openings),'south_roof_sections':3,'canopy_built':True,'small_arch_towers':2,'curtain_slits_native_withheld':3,'depths_measured':False,'source_arch_native_columns':archcols,'source_arch_through_depth_air_verified':True,'front_passages':passages,'corner_towers_reconstructed':False}
    return result,output,audit
