"""Automatic source-label/frame discovery inside a reviewed elevation scope.

Source rectangles can be panes, frames or other drafting objects. They never
become physical apertures or replacement meshes through this discovery stage.
"""
from collections import Counter,defaultdict
import bisect
import hashlib
import itertools
import json
import math
from pathlib import Path
import re

import pymupdf
from shapely.geometry import Polygon,box,shape,mapping

VERSION='native-opening-inventory-v1'


def identity(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def label_identity(text):
    compact=re.sub(r'\s+','',text).lower()
    match=re.fullmatch(r'([wd])\.(\d{1,3})\.(\d{1,3})',compact)
    if match:return {'canonical_id':f'{match[1]}.{match[2]}.{match[3]}','kind':'window' if match[1]=='w' else 'door'}
    match=re.fullmatch(r'archway(\d{1,3})',compact)
    if match:return {'canonical_id':'archway-'+match[1],'kind':'archway'}
    return None


def layout_links(label_bounds,frame_bounds,*,inside=False):
    x0,y0,x1,y1=label_bounds;left,top,right,bottom=frame_bounds
    height=y1-y0;cx=(x0+x1)/2;rules=[]
    if height<=0:return []
    if left<=cx<=right and 0<=y0-bottom<=4*height:rules.append('label_below_source_frame')
    if 0<=x0-right<=2*height and abs(y1-bottom)<=2*height:rules.append('label_at_lower_right')
    if inside and left<=cx<=right and top<=y0<=bottom and y1<=bottom+height:
        rules.append('label_inside_or_overlapping_bottom')
    return rules


def frame_candidates(records,scope_pixels,native_to_pixel,metres_per_pixel,*,max_checks=1000000,max_frames=2000):
    if type(max_checks) is not int or not 1<=max_checks<=1000000 or type(max_frames) is not int or not 1<=max_frames<=2000:
        raise ValueError('Bounded frame discovery budgets required')
    if len(records)>20000 or not math.isfinite(metres_per_pixel) or metres_per_pixel<=0:
        raise ValueError('Bounded finite native components required')
    source_keys={(r['document_sha256'],r['page'],r['coordinate_frame']) for r in records}
    if len(source_keys)>1 or any(k[2]!='pdf_native_points_y_up' for k in source_keys):
        raise ValueError('One original native source page required')
    if (len(scope_pixels)!=4 or len(native_to_pixel)!=6 or
            any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in [*scope_pixels,*native_to_pixel]) or
            scope_pixels[2]<=scope_pixels[0] or scope_pixels[3]<=scope_pixels[1]):
        raise ValueError('Finite ordered scope and affine transform required')
    scope=box(*scope_pixels);m=native_to_pixel
    def pixel(point):
        x,y=point;return (m[0]*x+m[2]*y+m[4],m[1]*x+m[3]*y+m[5])
    horizontal=defaultdict(list);vertical=defaultdict(list);counts=Counter();checks=0
    def charge():
        nonlocal checks
        checks+=1
        if checks>max_checks:raise OverflowError
    def withheld():return {'status':'frame_discovery_budget_withheld','frames':[],'checks':checks,'counts':dict(counts)}
    try:
        for record in records:
            charge()
            if record.get('paint_reference_truncated') or record.get('curve_approximation',{}).get('cubic_segments'):
                counts['curved_or_incomplete_paint_components']+=1;continue
            paints=record.get('paint_references',[])
            if not paints or any(not re.fullmatch(r'\s*(?:\[\s*\]\s*0(?:\.0*)?)?\s*',str(p.get('stroke_style',{}).get('dashes_pdf','unknown'))) for p in paints):
                counts['dashed_or_unknown_components']+=1;continue
            g=shape(record['geometry'])
            chains=[list(g.coords)] if g.geom_type=='LineString' else [list(g.exterior.coords),*[list(r.coords) for r in g.interiors]] if g.geom_type=='Polygon' else []
            for ring_index,chain in enumerate(chains):
                for segment_index,(a,b) in enumerate(zip(chain,chain[1:])):
                    charge();pa,pb=pixel(a),pixel(b)
                    if pa==pb:continue
                    proof={'component_id':record['id'],'ring_index':ring_index,'segment_index':segment_index,
                           'native_endpoints':[list(a),list(b)],'pixel_endpoints':[list(pa),list(pb)]}
                    if pa[0]==pb[0] and scope.bounds[0]<=pa[0]<=scope.bounds[2] and min(pa[1],pb[1])<=scope.bounds[3] and max(pa[1],pb[1])>=scope.bounds[1]:
                        vertical[pa[0]].append((min(pa[1],pb[1]),max(pa[1],pb[1]),proof))
                    if pa[1]==pb[1] and scope.bounds[1]<=pa[1]<=scope.bounds[3] and min(pa[0],pb[0])<=scope.bounds[2] and max(pa[0],pb[0])>=scope.bounds[0]:
                        horizontal[pa[1]].append((min(pa[0],pb[0]),max(pa[0],pb[0]),proof))
        # Exact union of collinear original intervals. No gap tolerance or snapping.
        def merged(values):
            out=[]
            for lo,hi,_ in sorted(values,key=lambda v:(v[0],v[1],identity(v[2]))):
                if out and lo<=out[-1][1]:out[-1][1]=max(hi,out[-1][1])
                else:out.append([lo,hi])
            return out
        vm={x:merged(rows) for x,rows in vertical.items()};hm={y:merged(rows) for y,rows in horizontal.items()}
        xs=sorted(vm);ys=sorted(hm);rectangles=set()
        min_dimension=.15/metres_per_pixel;max_dimension=5/metres_per_pixel
        for i,x0 in enumerate(xs):
            for x1 in xs[i+1:]:
                charge()
                if x1-x0>max_dimension:break
                if x1-x0<min_dimension:continue
                for a in vm[x0]:
                    for b in vm[x1]:
                        charge();lo=max(a[0],b[0],scope.bounds[1]);hi=min(a[1],b[1],scope.bounds[3])
                        if hi-lo<min_dimension:continue
                        levels=[]
                        for y in ys[bisect.bisect_left(ys,lo):bisect.bisect_right(ys,hi)]:
                            charge()
                            for c,d in hm[y]:
                                charge()
                                if c<=x0 and d>=x1:levels.append(y);break
                        for y0,y1 in itertools.combinations(levels,2):
                            charge()
                            if min_dimension<=y1-y0<=max_dimension:
                                rectangles.add((x0,y0,x1,y1))
                                if len(rectangles)>max_frames:raise OverflowError
        frames=[]
        for bounds in sorted(rectangles):
            x0,y0,x1,y1=bounds;proofs=[]
            sides=[('left',vertical[x0],y0,y1),('right',vertical[x1],y0,y1),('top',horizontal[y0],x0,x1),('bottom',horizontal[y1],x0,x1)]
            for name,rows,lo,hi in sides:
                references=[]
                for a,b,proof in rows:
                    charge();start=max(a,lo);end=min(b,hi)
                    if end<=start:continue
                    pa,pb=proof['pixel_endpoints'];axis=1 if name in ('left','right') else 0
                    fractions=sorted([(start-pa[axis])/(pb[axis]-pa[axis]),(end-pa[axis])/(pb[axis]-pa[axis])])
                    references.append({**proof,'interval_fractions':fractions})
                references.sort(key=identity);proofs.append({'side':name,'source_intervals':references})
            geometry=mapping(box(*bounds));frame={'geometry_pixels':geometry,'bounds_pixels':list(bounds),'source_side_support':proofs,
              'nominal_width_m':(x1-x0)*metres_per_pixel,'nominal_height_m':(y1-y0)*metres_per_pixel,
              'aperture_identity_verified':False,'physical_boundary_verified':False,'world_geometry_additions':0}
            frame['id']=identity(frame);frames.append(frame)
        counts.update(frames=len(frames),source_components=len(records))
        return {'status':'source_rectangle_cycles_only','frames':frames,'checks':checks,'counts':dict(counts)}
    except OverflowError:return withheld()


def associate(labels,frames,*,max_checks=1000000):
    if type(max_checks) is not int or not 1<=max_checks<=1000000 or len(labels)>500 or len(frames)>2000:
        raise ValueError('Bounded opening association required')
    counts=Counter();results=[];checks=0;duplicates=Counter(r['canonical_id'] for r in labels)
    for label in labels:
        hits=[]
        if label['glyph_screen']['status']=='raster_consistent_candidate':
            for frame in frames:
                checks+=1
                if checks>max_checks:return {'status':'opening_association_budget_withheld','labels':[],'checks':checks,'counts':{}}
                rules=layout_links(label['bounds_pixels'],frame['bounds_pixels'],inside=label['kind']=='archway')
                if rules:hits.append({'frame_id':frame['id'],'layout_rules':rules})
        # Keep nested panes and their larger cycles; containment is not physical identity.
        nested=[]
        by_id={r['id']:r for r in frames}
        for hit in hits:
            for other in hits:
                checks+=1
                if checks>max_checks:return {'status':'opening_association_budget_withheld','labels':[],'checks':checks,'counts':{}}
                if hit!=other and box(*by_id[other['frame_id']]['bounds_pixels']).covers(box(*by_id[hit['frame_id']]['bounds_pixels'])):
                    nested.append({'inner_frame_id':hit['frame_id'],'outer_frame_id':other['frame_id']})
        status=('glyph_visibility_withheld' if label['glyph_screen']['status']!='raster_consistent_candidate' else
                'repeated_source_label_identity' if duplicates[label['canonical_id']]>1 else
                'no_complete_source_rectangle' if not hits else
                'one_source_frame_layout_candidate' if len(hits)==1 else 'competing_source_frame_layout_candidates')
        counts[status]+=1
        results.append({**label,'status':status,'frame_candidates':hits,'nested_source_frames':nested,
                        'complete_aperture_verified':False,'physical_identity_verified':False,'world_geometry_additions':0})
    return {'status':'native_opening_layout_inventory_only','labels':results,'checks':checks,'counts':dict(counts)}


def reconcile_seed(seed_openings,labels):
    if len(seed_openings)>128:raise ValueError('Bounded reviewed aperture seed required')
    rows=[];points_checked=0
    for seed in seed_openings:
        points_checked+=len(seed['points_pixels'])
        if points_checked>2048 or any(len(p)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in p) for p in seed['points_pixels']):
            raise ValueError('Bounded finite seed polygon required')
        geometry=Polygon(seed['points_pixels']);claims=[]
        if not geometry.is_valid or geometry.area<=0:raise ValueError('Valid reviewed aperture polygon required')
        for label in labels:
            if label['glyph_screen']['status']!='raster_consistent_candidate':continue
            if layout_links(label['bounds_pixels'],geometry.bounds,inside=True):
                claims.append(label['canonical_id'])
        claimed=seed['id'];legacy=re.fullmatch(r'([wd])(\d+)\.(\d+)(?:-[ab])?',claimed)
        if legacy:claimed=f'{legacy[1]}.{legacy[2]}.{legacy[3]}'
        status='source_label_disagreement' if len(claims)==1 and claimed!=claims[0] else 'matching_label_layout_candidate' if claims==[claimed] else 'ambiguous_or_missing_source_label'
        rows.append({'seed_id':seed['id'],'claimed_label_id':claimed,'source_label_candidates':claims,'status':status,
                     'label_assignment_verified':False,'geometry_selection_authorized':False})
    covered={label for r in rows for label in r['source_label_candidates']}
    uniquely_covered={r['source_label_candidates'][0] for r in rows if len(r['source_label_candidates'])==1}
    return {'rows':rows,'source_labels_without_seed_trace':sorted({r['canonical_id'] for r in labels}-covered),
            'source_labels_without_unique_seed_assignment':sorted({r['canonical_id'] for r in labels}-uniquely_covered),
            'automatic_seed_rewrite':False,'world_geometry_additions':0}


def run(recipe_path,elevation_pdf,output,*,max_checks=1000000,max_frames=2000):
    recipe_path=Path(recipe_path)
    if recipe_path.stat().st_size>2*1024*1024:raise ValueError('Recipe byte budget exceeded')
    recipe_raw=recipe_path.read_bytes();recipe=json.loads(recipe_raw)
    if recipe.get('version')!='local-wing-surface-review-v1' or recipe.get('reviewed_trace_seed') is not True:
        raise ValueError('Explicit reviewed trace seed required')
    if len(recipe_raw)>2*1024*1024:raise ValueError('Recipe byte budget exceeded')
    spec=recipe['documents']['elevation'];path=Path(elevation_pdf)
    width=spec['render_width_pixels'];number=spec['page'];denominator=spec['scale_denominator']
    height=spec['render_size_pixels'][1]
    if (spec.get('state')!='existing' or type(width) is not int or not 200<=width<=4000 or
            type(height) is not int or not 200<=height<=4000 or type(number) is not int or not 1<=number<=10000 or
            type(denominator) is not int or not 1<=denominator<=1000):
        raise ValueError('Bounded existing elevation frame required')
    if path.stat().st_size>32*1024*1024:raise ValueError('Source byte budget exceeded')
    raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    if sha!=spec['sha256']:raise ValueError('Original elevation checksum mismatch')
    from .drawing_geometry import extract_page
    from .drawing_components import split_page
    from .drawing_page_tools import pixel_to_native
    from .ordinary_surfaces import label_runs
    from .glyph_visibility import screen_architectural_span
    with pymupdf.open(stream=raw,filetype='pdf') as doc:
        if number>len(doc):raise ValueError('Source page missing')
        page=doc[number-1]
        if not 0<page.rect.width or not 0<page.rect.height or page.rect.height/page.rect.width*width>4000:
            raise ValueError('Source raster dimension budget exceeded')
        normal=lambda value:re.sub(r'\s+','',value).lower()
        if not normal(spec['caption']) or normal(spec['caption']) not in normal(page.get_text()):
            raise ValueError('Reviewed view caption absent')
        pix=page.get_pixmap(matrix=pymupdf.Matrix(width/page.rect.width,width/page.rect.width))
        if [pix.width,pix.height]!=spec['render_size_pixels'] or hashlib.sha256(pix.samples).hexdigest()!=spec['render_samples_sha256']:
            raise ValueError('Reviewed elevation raster changed')
        transform=list(~pymupdf.Matrix(pixel_to_native(page,pix.width,pix.height)))
        unit=page.rect.width/width*spec['scale_denominator']*.0254/72
        trace=recipe['elevation_trace'];left,right=trace['baseline_endpoints']
        for point in [left,right,trace['ridge_point'],trace['eave_point']]:
            if len(point)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in point):
                raise ValueError('Finite reviewed profile required')
        if right[0]<=left[0] or abs(right[1]-left[1])>2:
            raise ValueError('Horizontal reviewed facade baseline required')
        scope=[min(left[0],right[0])-2,min(trace['ridge_point'][1],trace['eave_point'][1])-2,max(left[0],right[0])+2,max(left[1],right[1])+32]
        if not box(0,0,pix.width,pix.height).covers(box(*scope)):raise ValueError('Reviewed facade scope outside page')
        traces=page.get_texttrace()
        if len(traces)>10000 or sum(len(r['chars']) for r in traces)>500000:raise ValueError('Source label budget exceeded')
        labels=[];outside=0
        for row in label_runs(traces):
            text=''.join(chr(c[0]) for c in row['chars']).strip();parsed=label_identity(text)
            if not parsed:continue
            # PyMuPDF text boxes are unrotated page coordinates, not native PDF coordinates.
            rect=pymupdf.Rect(row['bbox'])*page.rotation_matrix*(width/page.rect.width)
            bounds=[rect.x0,rect.y0,rect.x1,rect.y1]
            if not box(*scope).covers(box(*bounds)):outside+=1;continue
            if len(labels)>=500:raise ValueError('Opening label budget exceeded')
            labels.append({**parsed,'text':text,'bounds_pixels':bounds,'trace_indices':row['trace_indices'],
                           'character_indices':row['character_indices'],
                           'glyph_screen':screen_architectural_span(page,row,zoom=24 if row['size']<4 else 6)})
        labels.sort(key=lambda r:(r['canonical_id'],r['bounds_pixels'],r['trace_indices']))
        parents,extraction=extract_page(page,sha,spec['page'],min_line_length_points=.25,max_candidates=10000)
        complete=extraction['status']=='unplaced_geometry_candidates'
        components=split_page(parents) if complete else []
        discovery=frame_candidates(components,scope,transform,unit,max_checks=max_checks,max_frames=max_frames) if complete else {'status':'source_extraction_incomplete','frames':[],'checks':0,'counts':{}}
        association=associate(labels,discovery['frames'],max_checks=max_checks)
        if discovery['status']!='source_rectangle_cycles_only':
            association={'status':'frame_discovery_withheld','labels':[{**r,'status':'frame_discovery_withheld',
                         'frame_candidates':[],'complete_aperture_verified':False,'world_geometry_additions':0} for r in labels],
                         'checks':0,'counts':{'frame_discovery_withheld':len(labels)}}
    if path.read_bytes()!=raw or recipe_path.read_bytes()!=recipe_raw:raise ValueError('Review inputs changed during discovery')
    used_ids={r['component_id'] for f in discovery['frames'] for s in f['source_side_support'] for r in s['source_intervals']}
    report={'version':VERSION,'document_sha256':sha,'page':spec['page'],'recipe_sha256':hashlib.sha256(recipe_raw).hexdigest(),
            'pymupdf_version':pymupdf.VersionBind,'source_components_sha256':identity(components),'extraction':extraction,
            'reviewed_scope_pixels':scope,'scope_from_reviewed_seed':True,'automatic_view_discovery':False,
            'coordinate_frame':'pinned_render_pixels_y_down','metres_per_pixel_nominal':unit,
            'native_to_pixel_matrix':transform,'source_support_components':[r for r in components if r['id'] in used_ids],
            'frames':discovery,'opening_inventory':association,'seed_label_review':reconcile_seed(recipe['openings'],labels),
            'outside_scope_labels':outside,'automatic_label_discovery':True,'automatic_aperture_reconstruction':False,
            'geometry_export_authorized':False,'world_geometry_additions':0,
            'limitations':['Reviewed facade/profile supplies discovery scope; view selection is not automatic.',
                          'Exact solid axis-aligned source rectangles only; no gap bridging, snapping or fitted hulls.',
                          'Frame cycles may be panes or drafting objects. Even one layout candidate is not a complete physical aperture.',
                          'Every competing/nested frame is retained; no nearest, largest or longest frame is selected.',
                          'Curved arch boundaries and skew/fragmented frames remain unresolved. No automatic mesh/seed replacement.',
                          'Layout gaps are search margins, not physical uncertainty or verified annotation attachment.']}
    output=Path(output);output.mkdir(parents=True,exist_ok=True);target=output/'native-opening-inventory.json'
    encoded=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode();reused=target.exists()
    if reused and target.read_bytes()!=encoded:raise ValueError('Native opening inputs/output changed; use a fresh output')
    if not reused:target.write_bytes(encoded)
    return {'version':VERSION,'status':association['status'],'inventory_path':str(target),'inventory_sha256':hashlib.sha256(encoded).hexdigest(),
            'frame_discovery_status':discovery['status'],'reused':reused,'labels':len(association['labels']),'source_frames':len(discovery['frames']),
            'association_counts':association['counts'],'seed_label_disagreements':sum(r['status']=='source_label_disagreement' for r in report['seed_label_review']['rows']),
            'source_labels_without_seed_trace':report['seed_label_review']['source_labels_without_seed_trace'],
            'automatic_aperture_reconstruction':False,'world_geometry_additions':0}
