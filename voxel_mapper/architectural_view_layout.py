"""Caption-scoped layout hypotheses; never verified view extents or paper scales."""
from collections import Counter
import hashlib
import json
import math
import re
import pymupdf
from shapely.geometry import Polygon,shape,mapping
from shapely.strtree import STRtree
from .drawing_geometry import native_inverse
from .ordinary_surfaces import label_runs
from .glyph_visibility import screen_architectural_span
from .elevation_interpretation import caption
from .architectural_graph import VERSION as GRAPH_VERSION

VERSION='architectural-caption-layout-v1'


def view_claim(text):
    elevation=caption(text)
    if elevation:return {**elevation,'view_kind':'elevation' if elevation['kind']=='view_caption' else 'sheet_title'}
    value=re.sub(r'\s+','',text.lower())
    plan=re.fullmatch(r'(?:(existing|proposed))?((?:ground|first|second)?floor|roof)plan(?:[\'’]as(existing|proposed)[\'’])?(?:\|1:(\d{1,5}))?',value)
    key=re.fullmatch(r'keyplan(?:\((ground|first|second)floor\))?(?:\|1:(\d{1,5}))?',value)
    section=re.fullmatch(r'section([a-z]{1,2})[-–](\1)(?:[\'’]as(existing|proposed)[\'’])?(?:\|1:(\d{1,5}))?',value)
    if plan:kind='plan';state=plan[3] or plan[1] or 'unspecified';denominator=plan[4]
    elif key:kind='key_plan';state='unspecified';denominator=key[2]
    elif section:kind='section';state=section[3] or 'unspecified';denominator=section[4]
    else:return None
    scale=int(denominator) if denominator else None
    if scale is not None and not 1<=scale<=10000:return None
    return {'kind':'view_caption','view_kind':kind,'printed_state':state,'printed_scale_denominator':scale,
        'plan_level_or_form':plan[2] if plan else None}


def review(page,sha,number,graph,*,max_assignments=100000):
    if type(max_assignments) is not int or not 1<=max_assignments<=100000:raise ValueError('Bounded view layout assignments required')
    if graph['version']!=GRAPH_VERSION or graph['status']!='source_drawing_topology_only':raise ValueError('Complete current source graph required')
    if graph['document_sha256']!=sha or graph['page']!=number or graph['coordinate_frame']!='pdf_native_points_y_up':raise ValueError('Same native source graph page required')
    traces=page.get_texttrace()
    if len(traces)>10000 or sum(len(r['chars']) for r in traces)>500000:raise ValueError('View layout text budget exceeded')
    inverse=native_inverse(page);views=[];scales=[];titles=[];windows=[]
    def retained(run):
        r=pymupdf.Rect(run['bbox']);points=[pymupdf.Point(x,y)*inverse for x,y in [(r.x0,r.y0),(r.x1,r.y0),(r.x1,r.y1),(r.x0,r.y1)]]
        origin=pymupdf.Point(0,0)*inverse;direction=pymupdf.Point(*run['dir'])*inverse
        vector=(direction.x-origin.x,direction.y-origin.y);length=math.hypot(*vector)
        if length==0:raise ValueError('Nondegenerate caption reading direction required')
        return {'text':''.join(chr(c[0]) for c in run['chars']).strip(),'label_geometry':mapping(Polygon([(p.x,p.y) for p in points])),
            'reading_direction_pdf_native':[v/length for v in vector],'trace_indices':run['trace_indices'],
            'character_indices':run['character_indices'],'glyph_screen':screen_architectural_span(page,run,zoom=24 if run['size']<4 else 6)}
    for run in label_runs(traces):
        text=''.join(chr(c[0]) for c in run['chars']).strip();claim=view_claim(text)
        scale=re.fullmatch(r'(?:scale\s*)?1\s*:\s*(\d{1,5})(?:\s*@\s*A[0-4])?',text,re.I)
        if claim:
            if len(views)+len(titles)>=128:raise ValueError('View-caption budget exceeded')
            row={**retained(run),'printed_claim':claim}
            row['id']=hashlib.sha256(json.dumps([VERSION,sha,number,row],sort_keys=True).encode()).hexdigest()
            row.update(view_scope_verified=False,scale_application_verified=False,physical_identity_verified=False,
                layout_candidate_status='glyph_screen_withheld' if row['glyph_screen']['status']!='raster_consistent_candidate' else
                    'inline_scale_layout_candidate' if claim.get('printed_scale_denominator') is not None else 'unscaled_caption_scope_withheld')
            (titles if claim['kind']=='sheet_title' else views).append(row)
        if scale and 1<=int(scale[1])<=10000:
            if len(scales)>=128:raise ValueError('Page scale-claim budget exceeded')
            scales.append({**retained(run),'printed_denominator':int(scale[1]),'view_assignment_verified':False})
    page_denominators=sorted({s['printed_denominator'] for s in scales})
    for row in views:
        denominator=row['printed_claim'].get('printed_scale_denominator')
        row['page_scale_claim_denominators']=page_denominators
        row['scale_scope_status']='no_inline_scale' if denominator is None else (
            'page_view_claim_difference' if page_denominators and set(page_denominators)!={denominator} else
            'agreeing_printed_claims_only' if page_denominators else 'inline_caption_claim_only')
    rotation=page.rotation
    try:
        page.set_rotation(0);r=page.rect
        corners=[pymupdf.Point(p)*inverse for p in (r.tl,r.tr,r.br,r.bl)]
        frame=Polygon([(p.x,p.y) for p in corners])
    finally:page.set_rotation(rotation)
    def projection(g,axis):return [sum(p[k]*axis[k] for k in (0,1)) for p in g.exterior.coords]
    for row in views:
        if row['layout_candidate_status']!='inline_scale_layout_candidate':continue
        u=row['reading_direction_pdf_native'];n=(-u[1],u[0]);label=shape(row['label_geometry']);lower=max(projection(label,n))
        higher=[]
        for other in views:
            v=other['reading_direction_pdf_native']
            if sum(u[k]*v[k] for k in (0,1))<1-1e-7:continue
            start=min(projection(shape(other['label_geometry']),n))
            if start>lower:higher.append(start)
        upper=min(higher) if higher else max(projection(frame,n));along=projection(frame,u)
        if upper<=lower:continue
        def point(a,b):return (u[0]*a+n[0]*b,u[1]*a+n[1]*b)
        window=Polygon([point(min(along),lower),point(max(along),lower),point(max(along),upper),point(min(along),upper)]).intersection(frame)
        if window.is_empty or window.geom_type!='Polygon' or not window.is_valid:continue
        windows.append({'id':row['id'],'caption_id':row['id'],'geometry':mapping(window),
            'basis':'caption_row_band_hypothesis','view_scope_verified':False,'scale_application_verified':False})
    checks=0;membership=[];groups=[];counts=Counter();index=STRtree([shape(w['geometry']) for w in windows])
    for component in graph['source_components'] if windows else []:
        g=shape(component['geometry']);contained=[];crossing=[];checks+=1
        if checks>max_assignments:break
        for k in index.query(g,predicate='intersects'):
            checks+=1
            if checks>max_assignments:break
            k=int(k);zone=shape(windows[k]['geometry'])
            if zone.covers(g):contained.append(windows[k]['id'])
            elif not zone.intersection(g).is_empty:crossing.append(windows[k]['id'])
        if checks>max_assignments:break
        status='one_layout_window_candidate' if len(contained)==1 and not crossing else 'ambiguous_or_crossing_windows' if contained or crossing else 'outside_layout_windows'
        membership.append({'component_id':component['id'],'candidate_window_ids':sorted(contained),'crossing_window_ids':sorted(crossing),
            'status':status,'view_scope_verified':False});counts[status]+=1
    if checks<=max_assignments:
        by_component={r['component_id']:set(r['candidate_window_ids']) if r['status']=='one_layout_window_candidate' else set() for r in membership}
        edge_component={e['id']:e['component_id'] for e in graph['edges']}
        for group in graph['connected_subgraphs'] if windows else []:
            checks+=1
            if checks>max_assignments:break
            ids={edge_component[e] for e in group['edge_ids']};common=set.intersection(*(by_component.get(i,set()) for i in ids)) if ids else set()
            groups.append({'source_subgraph_id':group['id'],'candidate_window_ids':sorted(common),'view_scope_verified':False})
    exhausted=checks>max_assignments
    if exhausted:membership=[];groups=[];counts=Counter()
    return {'version':VERSION,'document_sha256':sha,'page':number,'coordinate_frame':'pdf_native_points_y_up',
        'source_graph_sha256':hashlib.sha256(json.dumps(graph,sort_keys=True).encode()).hexdigest(),
        'status':'layout_assignment_budget_withheld' if exhausted else 'caption_layout_hypotheses_only',
        'view_captions':views,'sheet_titles':titles,'page_scale_claims':scales,'candidate_windows':windows,
        'component_membership':membership,'subgraph_membership':groups,'checks':checks,'max_assignments':max_assignments,
        'counts':{**dict(counts),'view_captions':len(views),'candidate_windows':len(windows),'scoped_subgraph_candidates':sum(len(g['candidate_window_ids'])==1 for g in groups)},
        'view_scope_verified':False,'scale_application_verified':False,'world_geometry_additions':0,
        'limitations':['Caption row bands are layout hypotheses, not source-defined view boundaries.',
            'Bands can include notes, legends or title blocks. Whole source components are never clipped or reassigned across a band.',
            'Inline caption scale/state remain per-view claims; standalone page scales and sheet titles are not inherited.',
            'Duplicate, hidden and competing captions remain explicit. No physical geometry, measurement or registration is authorized.']}
