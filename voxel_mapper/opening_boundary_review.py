"""Compare complete source outlines to reviewed aperture traces without fitting them."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

from shapely.affinity import affine_transform
from shapely.geometry import Point,Polygon,box,mapping,shape
from shapely.strtree import STRtree
from shapely.ops import unary_union

VERSION='opening-boundary-review-v1'


def compare(openings,records,matrix,scope,sampling_bound,*,max_checks=100000):
    if (type(max_checks) is not int or not 1<=max_checks<=100000 or len(openings)>128 or len(records)>20000 or
            len(matrix)!=6 or len(scope)!=4 or not 0<sampling_bound<=4 or
            any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in [*matrix,*scope,sampling_bound])):
        raise ValueError('Bounded finite aperture review required')
    if scope[2]<=scope[0] or scope[3]<=scope[1]:raise ValueError('Ordered source scope required')
    source={(r['document_sha256'],r['page'],r['coordinate_frame']) for r in records}
    if len(source)>1 or any(k[2]!='pdf_native_points_y_up' for k in source):raise ValueError('One native source page required')
    transform=[matrix[0],matrix[2],matrix[1],matrix[3],matrix[4],matrix[5]]
    candidates=[];checks=0;counts=Counter()
    def charge():
        nonlocal checks
        checks+=1
        if checks>max_checks:raise OverflowError
    try:
        for record in sorted(records,key=lambda r:r['id']):
            charge()
            if record['geometry']['type']!='Polygon':continue
            g=affine_transform(shape(record['geometry']),transform)
            if not g.is_valid or g.is_empty or not box(*scope).covers(g):continue
            paints=record.get('paint_references',[])
            solid=bool(paints) and not record.get('paint_reference_truncated') and all(
                re.fullmatch(r'\s*(?:\[\s*\]\s*0(?:\.0*)?)?\s*',str(p.get('stroke_style',{}).get('dashes_pdf','unknown'))) for p in paints)
            error=record.get('curve_approximation',{}).get('chord_error_bound_pdf_points',0)
            # Largest singular value bounds affine propagation of curve approximation.
            a,b,c,d=matrix[:4];frobenius=a*a+b*b+c*c+d*d;det=a*d-b*c
            stretch=math.sqrt((frobenius+math.sqrt(max(0,frobenius*frobenius-4*det*det)))/2)
            if not isinstance(error,(int,float)) or not math.isfinite(error) or error<0:raise ValueError('Finite source curve bound required')
            candidates.append((record,g,solid,error*stretch))
        lines=[]
        for record in sorted(records,key=lambda r:r['id']):
            charge()
            if record['geometry']['type']!='LineString' or record.get('paint_reference_truncated'):continue
            paints=record.get('paint_references',[])
            if not paints or any(not re.fullmatch(r'\s*(?:\[\s*\]\s*0(?:\.0*)?)?\s*',str(p.get('stroke_style',{}).get('dashes_pdf','unknown'))) for p in paints):continue
            if record.get('curve_approximation',{}).get('cubic_segments'):continue
            g=affine_transform(shape(record['geometry']),transform)
            lines.append((record,g))
        rows=[];points=0
        for opening in openings:
            points+=len(opening['points_pixels'])
            if points>2048 or any(len(p)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in p) for p in opening['points_pixels']):
                raise ValueError('Bounded finite reviewed trace required')
            seed=Polygon(opening['points_pixels'])
            if not seed.is_valid or seed.area<=0:raise ValueError('Valid reviewed aperture required')
            hits=[]
            for record,g,solid,error in candidates:
                charge()
                if not seed.buffer(12).intersects(g):continue
                distance=seed.boundary.hausdorff_distance(g.exterior)
                iou=seed.intersection(g).area/seed.union(g).area
                # Every nearby candidate stays in the audit, including panes and frame bands.
                eligible=solid and not g.interiors and iou>=.85 and distance+error<=sampling_bound
                hits.append({'source_candidate_id':record['id'],'geometry_pixels':mapping(g),
                    'source_geometry_sha256':hashlib.sha256(json.dumps(record['geometry'],sort_keys=True).encode()).hexdigest(),
                    'source_holes':len(g.interiors),'solid_source_paint':solid,'iou_with_reviewed_trace':iou,
                    'boundary_hausdorff_pixels':distance,'curve_error_bound_pixels':error,
                    'boundary_plus_curve_bound_pixels':distance+error,'within_reviewed_sampling_bound':eligible,
                    'candidate_kind':record.get('extraction_kind','unknown'),
                    'physical_aperture_verified':False})
            support=[];nearby=[];endpoints=[]
            discovery_margin=seed.boundary.buffer(12)
            for record,g in lines:
                charge()
                for index in (0,len(g.coords)-1):
                    point=Point(g.coords[index])
                    if discovery_margin.covers(point):
                        endpoints.append({'source_candidate_id':record['id'],'vertex_index':index,
                            'native_point':list(shape(record['geometry']).coords[index]),'pixel_point':list(g.coords[index])})
                if not g.intersects(seed.boundary.buffer(sampling_bound)):continue
                nearby.append(g)
                support.append({'source_candidate_id':record['id'],'geometry_pixels':mapping(g),
                                'source_geometry_sha256':hashlib.sha256(json.dumps(record['geometry'],sort_keys=True).encode()).hexdigest()})
            gaps=[];exact_joins=0;endpoint_points=[Point(e['pixel_point']) for e in endpoints]
            endpoint_index=STRtree(endpoint_points)
            for i,point in enumerate(endpoint_points):
                for j in endpoint_index.query(point.buffer(sampling_bound)):
                    j=int(j)
                    if j<=i or endpoints[i]['source_candidate_id']==endpoints[j]['source_candidate_id']:continue
                    charge();distance=point.distance(endpoint_points[j])
                    if distance==0:exact_joins+=1
                    elif distance<=sampling_bound:
                        gaps.append({'endpoints':[endpoints[i],endpoints[j]],'distance_pixels':distance,
                                     'source_gap_repaired':False,'physical_connection_verified':False})
            proximity=unary_union([g.buffer(sampling_bound) for g in nearby])
            supported=seed.boundary.intersection(proximity);unsupported=seed.boundary.difference(proximity)
            proximity_review={'sampling_bound_pixels':sampling_bound,'reviewed_perimeter_pixels':seed.length,
                'near_source_length_pixels':supported.length,'near_source_fraction':supported.length/seed.length,
                'unsupported_reviewed_trace':mapping(unsupported),'original_source_lines':support,
                'interpretation':'Distance-to-reviewed-trace evidence only; buffer never joins source linework or closes an aperture.'}
            qualifying=[h for h in hits if h['within_reviewed_sampling_bound']]
            status='unique_review_trace_refinement_candidate' if len(qualifying)==1 else 'competing_review_trace_refinements' if qualifying else 'no_complete_outline_within_trace_bound'
            counts[status]+=1
            rows.append({'seed_id':opening['id'],'status':status,'candidates':hits,
                         'trace_proximity_review':proximity_review,'endpoint_gap_candidates':gaps,'exact_source_endpoint_joins':exact_joins,'refinement_candidate_id':qualifying[0]['source_candidate_id'] if len(qualifying)==1 else None,
                         'physical_aperture_verified':False,'world_geometry_additions':0})
        return {'status':'reviewed_trace_comparison_only','rows':rows,'checks':checks,'counts':dict(counts),
                'sampling_bound_pixels':sampling_bound,'geometry_export_authorized':False,'world_geometry_additions':0}
    except OverflowError:
        return {'status':'boundary_comparison_budget_withheld','rows':[],'checks':checks,'counts':{},
                'geometry_export_authorized':False,'world_geometry_additions':0}


def run(recipe_path,source_pdf,inventory_summary,output):
    from .drawing_geometry import extract_page
    from .linework_boundaries import recover_page
    import pymupdf
    recipe_path=Path(recipe_path);source_pdf=Path(source_pdf)
    if recipe_path.stat().st_size>2*1024*1024 or source_pdf.stat().st_size>32*1024*1024:raise ValueError('Source byte budget exceeded')
    recipe_raw=recipe_path.read_bytes();raw=source_pdf.read_bytes();recipe=json.loads(recipe_raw)
    inventory_raw=Path(inventory_summary['inventory_path']).read_bytes()
    if len(inventory_raw)>32*1024*1024 or hashlib.sha256(inventory_raw).hexdigest()!=inventory_summary['inventory_sha256']:
        raise ValueError('Validated native opening inventory required')
    inventory=json.loads(inventory_raw)
    if (inventory['document_sha256']!=hashlib.sha256(raw).hexdigest() or
            inventory['recipe_sha256']!=hashlib.sha256(recipe_raw).hexdigest()):raise ValueError('Opening review source pins changed')
    if recipe.get('reviewed_trace_seed') is not True or recipe.get('version')!='local-wing-surface-review-v1':raise ValueError('Reviewed trace seed required')
    with pymupdf.open(stream=raw,filetype='pdf') as doc:
        parents,extraction=extract_page(doc[inventory['page']-1],inventory['document_sha256'],inventory['page'],min_line_length_points=.25,max_candidates=10000)
        records,recovery=recover_page(parents,recovery_options={'max_face_provenance':2048}) if extraction['status']=='unplaced_geometry_candidates' else ([],{'status':'source_extraction_incomplete'})
    if inventory['frames']['status']=='source_rectangle_cycles_only':
        a,b,c,d,e,f=inventory['native_to_pixel_matrix'];det=a*d-b*c
        if not math.isfinite(det) or det==0:raise ValueError('Invertible source transform required')
        inverse=[d/det,-c/det,-b/det,a/det,(c*f-d*e)/det,(b*e-a*f)/det]
        supports={r['id']:r for r in inventory['source_support_components']}
        for frame in inventory['frames']['frames']:
            source_ids={p['component_id'] for side in frame['source_side_support'] for p in side['source_intervals']}
            records.append({'id':frame['id'],'document_sha256':inventory['document_sha256'],'page':inventory['page'],
                'coordinate_frame':'pdf_native_points_y_up','geometry':mapping(affine_transform(shape(frame['geometry_pixels']),inverse)),
                'extraction_kind':'source_rectangle_cycles','paint_references':[p for key in sorted(source_ids) for p in supports[key]['paint_references']],
                'curve_approximation':{'chord_error_bound_pdf_points':0},'source_side_support':frame['source_side_support']})
    complete=recovery['status'] in ('enclosed_faces_only','no_eligible_linework') and not any(
        recovery.get('counts',{}).get(k,0) for k in ('provenance_budget_deferred','combined_page_budget_deferred','face_vertex_budget'))
    comparison=compare(recipe['openings'],records,inventory['native_to_pixel_matrix'],inventory['reviewed_scope_pixels'],recipe['endpoint_sampling_bound_pixels']) if complete else {
        'status':'source_boundary_recovery_withheld','rows':[],'counts':{},'geometry_export_authorized':False,'world_geometry_additions':0}
    used={c['source_candidate_id'] for row in comparison['rows'] for c in [*row['candidates'],*row['trace_proximity_review']['original_source_lines'],*[e for gap in row['endpoint_gap_candidates'] for e in gap['endpoints']]]}
    report={'version':VERSION,'inventory_sha256':inventory_summary['inventory_sha256'],'document_sha256':inventory['document_sha256'],
            'recipe_sha256':inventory['recipe_sha256'],'extraction':extraction,'recovery':recovery,'comparison':comparison,
            'source_candidates':[r for r in records if r['id'] in used],
            'limitations':['Existing reviewed trace and view scope are required; physical identity remains provisional.',
                          'All nearby complete outlines retained. Panes, holes and competing boundaries are not silently selected.',
                          'Sampling bound is a trace comparison rule, not physical accuracy. No fitted scale, snapping or repaired gaps.',
                          'Closed native curves retain approximation bounds; open curved paths are not joined into faces.',
                          'No automatic mesh replacement, newly carved boarded window, or geographic placement.'],
            'world_geometry_additions':0}
    if raw!=source_pdf.read_bytes() or recipe_raw!=recipe_path.read_bytes() or inventory_raw!=Path(inventory_summary['inventory_path']).read_bytes():raise ValueError('Opening review inputs changed during run')
    encoded=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode();output=Path(output);output.mkdir(parents=True,exist_ok=True);target=output/'opening-boundary-review.json'
    reused=target.exists()
    if reused and target.read_bytes()!=encoded:raise ValueError('Boundary review changed; use fresh output')
    if not reused:target.write_bytes(encoded)
    return {'version':VERSION,'status':comparison['status'],'review_path':str(target),'review_sha256':hashlib.sha256(encoded).hexdigest(),
            'reused':reused,'counts':comparison['counts'],'world_geometry_additions':0,'geometry_export_authorized':False}
