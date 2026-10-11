"""Complete rectangle cycles and source-supported plan junction diagnostics."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

from shapely.affinity import affine_transform
from shapely.geometry import LineString,Point,Polygon,box,mapping
from shapely.geometry import shape
from shapely.ops import unary_union

from .native_opening_inventory import frame_candidates,run as inventory

VERSION='wing-outline-review-v1'


def compare(openings,frames,*,max_checks=256000):
    if type(max_checks) is not int or not 1<=max_checks<=256000 or len(openings)>128 or len(frames)>2000:
        raise ValueError('Bounded outline comparison required')
    rows=[];checks=0
    for opening in openings:
        if len(opening['points_pixels'])>2048 or any(len(p)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in p) for p in opening['points_pixels']):
            raise ValueError('Bounded finite opening required')
        seed=Polygon(opening['points_pixels'])
        if not seed.is_valid or seed.area<=0:raise ValueError('Valid reviewed opening required')
        nearby=box(seed.bounds[0]-24,seed.bounds[1]-24,seed.bounds[2]+24,seed.bounds[3]+24);hits=[]
        for frame in sorted(frames,key=lambda f:f['id']):
            checks+=1
            if checks>max_checks:return {'status':'outline_comparison_budget_withheld','rows':[],'checks':checks}
            g=shape(frame['geometry_pixels'])
            if g.geom_type!='Polygon' or not g.is_valid or g.interiors:raise ValueError('Valid single-ring cycle required')
            if not nearby.intersects(g):continue
            iou=g.intersection(seed).area/g.union(seed).area
            if iou<.15:continue
            hits.append({'frame_id':frame['id'],'iou_with_reviewed_trace':iou,
                         'boundary_hausdorff_pixels':g.boundary.hausdorff_distance(seed.boundary),
                         'status':'drawing_cycle_review_only','physical_aperture_verified':False})
        rows.append({'seed_id':opening['id'],'candidates':hits,'status':'competing_source_cycles' if len(hits)>1 else
                     'one_source_cycle' if hits else 'no_nearby_source_cycle','mesh_update_authorized':False})
    return {'status':'source_cycle_comparison_only','rows':rows,'checks':checks,
            'limitations':['Discovery neighbourhood and IoU retain alternatives; neither is physical aperture evidence.',
                           'No largest, nearest or best-IoU cycle is selected. Panes, casing and full outlines remain competing.']}


def junctions(records,matrix,trace,*,max_checks=200000):
    if type(max_checks) is not int or not 1<=max_checks<=200000 or len(records)>20000:
        raise ValueError('Bounded junction work required')
    if len(matrix)!=6 or any(type(v) not in (int,float) or not math.isfinite(v) for v in matrix):
        raise ValueError('Finite source matrix required')
    a,b=trace['facade_endpoints'];rear=trace['rear_point']
    if any(len(p)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in p) for p in [a,b,rear]):
        raise ValueError('Finite plan review traces required')
    dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
    if length==0:raise ValueError('Distinct facade endpoints required')
    # Perpendicular depth comes from the reviewed rear point, never a fitted width.
    along=((rear[0]-a[0])*dx+(rear[1]-a[1])*dy)/length**2
    depth=[rear[i]-(a[i]+along*(b[i]-a[i])) for i in (0,1)]
    if math.hypot(*depth)==0:raise ValueError('Distinct rear datum required')
    keys={(r['document_sha256'],r['page'],r['coordinate_frame']) for r in records}
    if len(keys)>1 or any(k[2]!='pdf_native_points_y_up' for k in keys):raise ValueError('One original source page required')
    transform=[matrix[0],matrix[2],matrix[1],matrix[3],matrix[4],matrix[5]];checks=0;rows=[]
    for name,start in [('start',a),('end',b)]:
        target=LineString([start,[start[i]+depth[i] for i in (0,1)]]);near=target.buffer(2);proofs=[];supported=[]
        for r in sorted(records,key=lambda r:r['id']):
            checks+=1
            if checks>max_checks:return {'status':'junction_budget_withheld','rows':[],'checks':checks,'mesh_update_authorized':False}
            if r.get('paint_reference_truncated') or r.get('curve_approximation',{}).get('cubic_segments'):continue
            paints=r.get('paint_references',[])
            if not paints or any(not re.fullmatch(r'\s*(?:\[\s*\]\s*0(?:\.0*)?)?\s*',str(p.get('stroke_style',{}).get('dashes_pdf','unknown'))) for p in paints):continue
            native=shape(r['geometry']);g=affine_transform(native,transform)
            if g.geom_type not in ('LineString','Polygon') or not g.is_valid or not near.intersects(g):continue
            chains=[list(g.coords)] if g.geom_type=='LineString' else [list(g.exterior.coords),*[list(r.coords) for r in g.interiors]]
            originals=[list(native.coords)] if native.geom_type=='LineString' else [list(native.exterior.coords),*[list(r.coords) for r in native.interiors]]
            for ring,(chain,original) in enumerate(zip(chains,originals)):
                for index,(p,q) in enumerate(zip(chain,chain[1:])):
                    checks+=1
                    if checks>max_checks:return {'status':'junction_budget_withheld','rows':[],'checks':checks,'mesh_update_authorized':False}
                    source=LineString([p,q]);overlap=target.intersection(source.buffer(2,cap_style=2))
                    if overlap.length<=1e-6:continue
                    pieces=list(overlap.geoms) if hasattr(overlap,'geoms') else [overlap]
                    intervals=[]
                    for piece in pieces:
                        if piece.geom_type=='LineString' and piece.length>1e-6:
                            intervals.append(sorted([target.project(Point(piece.coords[0]),normalized=True),target.project(Point(piece.coords[-1]),normalized=True)]));supported.append(piece)
                    if intervals:proofs.append({'source_candidate_id':r['id'],'ring_index':ring,'segment_index':index,
                                               'native_endpoints':[list(original[index]),list(original[index+1])],
                                               'pixel_endpoints':[list(p),list(q)],'review_trace_proximity_intervals':intervals})
        coverage=unary_union(supported) if supported else LineString()
        rows.append({'end':name,'reviewed_cross_section_pixels':list(target.coords),'proximity_fraction':coverage.length/target.length,
                     'unsupported_review_trace':mapping(target.difference(coverage)),
                     'source_segment_proofs':proofs,'status':'junction_requires_source_and_elevation_review',
                     'end_wall_exterior_identity_verified':False,'end_wall_height_verified':False,'mesh_update_authorized':False})
    return {'status':'plan_junction_proximity_only','rows':rows,'checks':checks,'proximity_bound_pixels':2,
            'source_coordinates_changed':False,'mesh_update_authorized':False,
            'limitations':['Proximity to a reviewed cross section does not join source lines or prove an exterior end wall.',
                           'Neighbouring wing junctions, openings and vertical profiles require separate evidence.']}


def run(recipe_path,paths,output):
    import pymupdf
    from .drawing_geometry import extract_page
    from .drawing_components import split_page
    from .drawing_page_tools import native_to_render_pixels
    output=Path(output);recipe_path=Path(recipe_path);raw=recipe_path.read_bytes()
    if len(raw)>2*1024*1024:raise ValueError('Recipe byte budget exceeded')
    recipe=json.loads(raw);inv=inventory(recipe_path,paths['elevation'],output/'inventory')
    view=json.loads(Path(inv['inventory_path']).read_text());records={};matrices={};extractions={};source_bytes={}
    for key in ('elevation','plan'):
        path=Path(paths[key]);spec=recipe['documents'][key]
        if spec.get('state')!='existing' or type(spec['page']) is not int or not 1<=spec['page']<=10000:
            raise ValueError('Existing reviewed source page required')
        if path.stat().st_size>32*1024*1024:raise ValueError('Source byte budget exceeded')
        source_bytes[key]=path.read_bytes()
        if hashlib.sha256(source_bytes[key]).hexdigest()!=spec['sha256']:raise ValueError('Source checksum mismatch')
        with pymupdf.open(stream=source_bytes[key],filetype='pdf') as doc:
            page=doc[spec['page']-1];matrices[key]=native_to_render_pixels(page,spec['render_width_pixels'])
            width=spec['render_width_pixels']
            if page.rect.height/page.rect.width*width>4000:raise ValueError('Source render budget exceeded')
            pix=page.get_pixmap(matrix=pymupdf.Matrix(width/page.rect.width,width/page.rect.width))
            if [pix.width,pix.height]!=spec['render_size_pixels'] or hashlib.sha256(pix.samples).hexdigest()!=spec['render_samples_sha256']:
                raise ValueError('Reviewed source raster changed')
            normal=lambda s:re.sub(r'\s+','',s).lower()
            if not normal(spec['caption']) or normal(spec['caption']) not in normal(page.get_text()):raise ValueError('Reviewed source caption absent')
            parents,extractions[key]=extract_page(page,spec['sha256'],spec['page'],min_line_length_points=.25,max_candidates=10000,isolate_open_stroked_subpaths=True)
        records[key]=split_page(parents) if extractions[key]['status']=='unplaced_geometry_candidates' else []
    frames=frame_candidates(records['elevation'],view['reviewed_scope_pixels'],matrices['elevation'],view['metres_per_pixel_nominal'])
    comparison=compare(recipe['openings'],frames['frames']) if frames['status']=='source_rectangle_cycles_only' and extractions['elevation']['status']=='unplaced_geometry_candidates' else {'status':'source_cycle_extraction_withheld','rows':[]}
    ends=junctions(records['plan'],matrices['plan'],recipe['plan_trace']) if extractions['plan']['status']=='unplaced_geometry_candidates' else {'status':'source_extraction_withheld','rows':[]}
    used={p['component_id'] for f in frames['frames'] for side in f['source_side_support'] for p in side['source_intervals']}
    plan_used={p['source_candidate_id'] for row in ends['rows'] for p in row['source_segment_proofs']}
    report={'version':VERSION,'recipe_sha256':hashlib.sha256(raw).hexdigest(),'source_pdf_sha256':{k:recipe['documents'][k]['sha256'] for k in source_bytes},
            'native_to_render_matrices':matrices,'extraction':extractions,'source_cycles':frames,'opening_review':comparison,'junction_review':ends,
            'source_components':{'elevation':[r for r in records['elevation'] if r['id'] in used],'plan':[r for r in records['plan'] if r['id'] in plan_used]},
            'mesh_update_authorized':False,'world_geometry_additions':0}
    if raw!=recipe_path.read_bytes() or any(data!=Path(paths[k]).read_bytes() for k,data in source_bytes.items()):raise ValueError('Outline inputs changed during run')
    encoded=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode()
    if len(encoded)>32*1024*1024:raise ValueError('Outline output byte budget exceeded')
    target=output/'wing-outline-review.json';reused=target.exists()
    if reused and target.read_bytes()!=encoded:raise ValueError('Outline receipt changed; use fresh output')
    if not reused:target.write_bytes(encoded)
    return {'version':VERSION,'outline_path':str(target),'outline_sha256':hashlib.sha256(encoded).hexdigest(),'reused':reused,
            'source_cycle_count':len(frames['frames']),'opening_statuses':dict(Counter(r['status'] for r in comparison['rows'])),
            'junction_status':ends['status'],'mesh_update_authorized':False,'world_geometry_additions':0}
