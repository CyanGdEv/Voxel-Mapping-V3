"""Bounded retained-outline investigation under frozen held-out map fits."""
from collections import Counter
import numpy as np
from shapely.affinity import affine_transform
from shapely.geometry import shape
from shapely.strtree import STRtree
from .mapped_sheet_placement import placed

VERSION='osm-outline-review-v2'


def metrics(left,right):
    return {'intersection_over_union':left.intersection(right).area/left.union(right).area,
            'boundary_error_m':left.boundary.hausdorff_distance(right.boundary),
            'centroid_error_m':left.centroid.distance(right.centroid),
            'hole_topology_equal':len(left.interiors)==len(right.interiors)}


def source_trace(record,geometry):
    if record is None:return {'status':'source_trace_unavailable','physical_outline_completeness_verified':False}
    exact=shape(record['geometry']).equals(geometry)
    windows=record.get('regional_window_references',[])+record.get('targeted_window_references',[])
    margins=[]
    for window in windows:
        x0,y0,x1,y1=window['region_native_points'];a,b,c,d=geometry.bounds
        margins.append(min(a-x0,b-y0,x1-c,y1-d))
    native=record.get('extraction_kind')=='drawing_geometry'
    return {'status':'native_closed_boundary_retained' if exact and native and not record.get('paint_reference_truncated')
            else 'derived_boundary_retained' if exact and record.get('line_parent_references') else 'source_trace_requires_review',
        'candidate_id':record['id'],'extraction_kind':record.get('extraction_kind'),
        'extraction_contract':record.get('extraction_contract'),
        'paint_ordinals':[p['ordinal'] for p in record.get('paint_references',[])],
        'paint_reference_truncated':bool(record.get('paint_reference_truncated')),
        'line_parent_ids':[p['candidate_id'] for p in record.get('line_parent_references',[])],
        'regional_boundary_margins_pdf_points':margins,'curve_approximation':record.get('curve_approximation'),
        'physical_outline_completeness_verified':False}


def review(objects,refs,checks,sources,*,max_failed=64,max_neighbors=128):
    if (type(max_failed) is not int or not 1<=max_failed<=64 or type(max_neighbors) is not int or not 1<=max_neighbors<=128
            or len(objects)>20000 or len(refs)>5000 or len(sources)>30000 or len(checks['hypotheses'])>12):
        raise ValueError('Bounded outline review inventory required')
    by_id={o['candidate_id']:o for o in objects};ref_ids={r['id']:r for r in refs}
    if len(by_id)!=len(objects) or len(ref_ids)!=len(refs):raise ValueError('Unique outline review IDs required')
    source_ids={}
    for source in sources:source_ids.setdefault(source['id'],source)
    local_index=STRtree([o['geometry'] for o in objects]);ref_index=STRtree([r['geometry'] for r in refs])
    failed=[(i,row) for i,h in enumerate(checks['hypotheses']) for row in h['held_out_checks'] if not row['passed']]
    results=[]
    for hypothesis_index,row in failed[:max_failed]:
        o=by_id[row['candidate_id']];r=ref_ids[row['reference_id']]
        fit=row['held_out_fit'];matrix=np.asarray(fit['matrix']);translation=np.asarray(fit['translation_m'])
        inverse=np.linalg.inv(matrix);offset=-inverse@translation
        reference=r['geometry'];polygon=placed(o['geometry'],fit)
        local_window=affine_transform(reference.buffer(10),[inverse[0,0],inverse[0,1],inverse[1,0],inverse[1,1],*offset])
        local_hits=sorted(int(i) for i in local_index.query(local_window,predicate='intersects'))
        map_hits=sorted(int(i) for i in ref_index.query(polygon.buffer(10),predicate='intersects'))
        result={'hypothesis_index':hypothesis_index,'candidate_id':o['candidate_id'],'reference_id':r['id'],
            'status':'no_compatible_retained_alternative','source_trace':source_trace(source_ids.get(o['candidate_id']),o['geometry']),
            'osm_element_metadata':r.get('source_metadata',{}),'source_date_difference_verified':False,
            'held_out_fit_unchanged':True,'nearby_source_outlines':len(local_hits),'nearby_map_outlines':len(map_hits),
            'alternative_source_outlines':[],'alternative_map_outlines':[],
            'failed_thresholds':row['failed_thresholds'],'physical_identity_verified':False,'registration_verified':False}
        if len(local_hits)>max_neighbors or len(map_hits)>max_neighbors:
            result['status']='neighbor_budget_withheld';results.append(result);continue
        scale_ok=row['relative_printed_scale_error']<=checks['scale_tolerance']
        def compatible(m):
            return scale_ok and m['intersection_over_union']>=checks['min_iou'] and m['boundary_error_m']<=checks['tolerance_m'] and m['hole_topology_equal']
        for i in local_hits:
            alternate=objects[i]
            if alternate['candidate_id']==o['candidate_id'] or alternate['geometry'].geom_type!='Polygon':continue
            m=metrics(placed(alternate['geometry'],fit),reference)
            if compatible(m):result['alternative_source_outlines'].append({'candidate_id':alternate['candidate_id'],
                'already_used_in_held_out_fit':alternate['candidate_id'] in row['fit_landmark_ids'],
                'metrics':m,'source_trace':source_trace(source_ids.get(alternate['candidate_id']),alternate['geometry']),
                'physical_identity_verified':False})
        for i in map_hits:
            alternate=refs[i]
            if alternate['id']==r['id'] or alternate['geometry'].geom_type!='Polygon':continue
            m=metrics(polygon,alternate['geometry'])
            if compatible(m):result['alternative_map_outlines'].append({'reference_id':alternate['id'],'metrics':m,
                'physical_identity_verified':False})
        for key in ('alternative_source_outlines','alternative_map_outlines'):
            result[key].sort(key=lambda x:(x['metrics']['boundary_error_m'],-x['metrics']['intersection_over_union'],x.get('candidate_id',x.get('reference_id'))))
            result[key+'_count']=len(result[key]);result[key]=result[key][:3]
        n=result['alternative_source_outlines_count']+result['alternative_map_outlines_count']
        if n:result['status']='alternative_outline_hint' if n==1 else 'ambiguous_alternative_outline_hints'
        results.append(result)
    return {'version':VERSION,'status':'retained_outline_investigation_only','failed_checks':len(failed),
        'reviewed_failed_checks':len(results),'deferred_failed_checks':max(0,len(failed)-max_failed),
        'review_statuses':dict(Counter(r['status'] for r in results)),'reviews':results,
        'geometry_replacements':0,'world_geometry_additions':0,'registration_verified':False,
        'limitations':['Retained closed primitives do not establish complete physical object identity.',
            'Alternative outlines are investigation hints under an unchanged held-out transform; none replace a match.',
            'OSM edit timestamps do not establish the physical observation date; source-date change remains unresolved.']}
