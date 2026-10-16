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

VERSION='architectural-caption-layout-v3'


def view_claim(text):
    if not isinstance(text,str) or len(text)>500:return None
    elevation=caption(text)
    if elevation:return {**elevation,'view_kind':'elevation' if elevation['kind']=='view_caption' else 'sheet_title'}
    value=re.sub(r'\s+','',text.lower())
    numbered=re.fullmatch(r'elevation([1-9]\d{0,2})tothe([ns])\.?(east|west)(?:[\'’]as(existing|proposed)[\'’])?(?:\|1:(\d{1,5}))?',value)
    if numbered:
        denominator=int(numbered[5]) if numbered[5] else None
        if denominator is not None and not 1<=denominator<=10000:return None
        return {'kind':'view_caption','view_kind':'elevation','view_number':int(numbered[1]),
            'direction':{'n':'north','s':'south'}[numbered[2]]+numbered[3],
            'printed_state':numbered[4] or 'unspecified','printed_scale_denominator':denominator,
            'numbered_reference_verified':False}
    plan=re.fullmatch(r'(?:\d{1,3}\.)?(?:overall)?(?:(existing|proposed))?((?:ground|first|second)?floor|roof)plan(?:[\'’]as(existing|proposed)[\'’])?(?:\|1:(\d{1,5}))?',value)
    key=re.fullmatch(r'keyplan(?:\((ground|first|second)floor\))?(?:\|1:(\d{1,5}))?',value)
    section=re.fullmatch(r'section([a-z]{1,2})[-–](\1)(?:[\'’]as(existing|proposed)[\'’])?(?:\|1:(\d{1,5}))?',value)
    if plan:kind='plan';state=plan[3] or plan[1] or 'unspecified';denominator=plan[4]
    elif key:kind='key_plan';state='unspecified';denominator=key[2]
    elif section:kind='section';state=section[3] or 'unspecified';denominator=section[4]
    else:
        # Exact ordinary captions only. A title's existing/proposed claim stays
        # attached to that caption; surrounding prose and catalogue state do not.
        ordinary=re.fullmatch(r"(?:(existing|proposed)\s+)?(site|block|location|(?:ground|first|second)\s+floor|roof)\s+plan(?:\s+(?:as\s+)?(existing|proposed))?(?:\s+showing\s+([A-Za-z][A-Za-z0-9 -]{0,79}))?(?:\s*\|\s*1\s*:\s*(\d{1,5}))?",text.strip(),re.I)
        cardinal=re.fullmatch(r"(?:(existing|proposed)\s+)?(north(?:[ -]?(?:east|west))?|south(?:[ -]?(?:east|west))?|east|west)\s+elevation(?:\s+(?:as\s+)?(existing|proposed))?(?:\s*\|\s*1\s*:\s*(\d{1,5}))?",text.strip(),re.I)
        match=ordinary or cardinal
        if not match:return None
        if match[1] and match[3] and match[1].lower()!=match[3].lower():return None
        scale_text=match[5] if ordinary else match[4]
        scale=int(scale_text) if scale_text else None
        if scale is not None and not 1<=scale<=10000:return None
        sheet_title=bool(ordinary and match[2].lower() in ('site','block','location'))
        return {'kind':'sheet_title' if sheet_title else 'view_caption',
            'view_kind':'sheet_title' if sheet_title else 'plan' if ordinary else 'elevation',
            'plan_level_or_form':re.sub(r'\s+','',match[2].lower()) if ordinary else None,
            'caption_subject':match[4] if ordinary else None,
            'direction':None if ordinary else re.sub(r'[ -]','',match[2].lower()),
            'printed_state':(match[3] or match[1] or 'unspecified').lower(),
            'printed_scale_denominator':scale}
    scale=int(denominator) if denominator else None
    if scale is not None and not 1<=scale<=10000:return None
    prefix=re.match(r'^(\d{1,3})\.',value) if plan else None
    overall_title=bool(plan and value.startswith('overall'))
    return {'kind':'sheet_title' if overall_title else 'view_caption',
        'view_kind':'sheet_title' if overall_title else kind,
        'printed_state':state,'printed_scale_denominator':scale,
        'plan_level_or_form':plan[2] if plan else None,
        **({'view_number':int(prefix[1]),'numbered_reference_verified':False} if prefix else {})}


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
    runs=list(label_runs(traces))
    from .caption_fragments import collect
    joined,fragment_status,fragment_contexts=collect(page,runs,view_claim,retained)
    grouped={json.dumps(key) for context in fragment_contexts for key in context['fragment_keys']}
    def add_caption(evidence,claim):
        if len(views)+len(titles)>=128:raise ValueError('View-caption budget exceeded')
        row={**evidence,'printed_claim':claim}
        row['id']=hashlib.sha256(json.dumps([VERSION,sha,number,row],sort_keys=True).encode()).hexdigest()
        row.update(view_scope_verified=False,scale_application_verified=False,physical_identity_verified=False,
            layout_candidate_status='glyph_screen_withheld' if row['glyph_screen']['status']!='raster_consistent_candidate' else
                'inline_scale_layout_candidate' if claim.get('printed_scale_denominator') is not None else 'unscaled_caption_scope_withheld')
        (titles if claim['kind']=='sheet_title' else views).append(row)
    for run in runs:
        text=''.join(chr(c[0]) for c in run['chars']).strip();claim=view_claim(text)
        scale=re.fullmatch(r'(?:scale\s*)?1\s*:\s*(\d{1,5})(?:\s*@\s*A[0-4])?',text,re.I)
        if claim and json.dumps([run['trace_indices'],run['character_indices']]) not in grouped:
            add_caption(retained(run),claim)
        if scale and 1<=int(scale[1])<=10000:
            if len(scales)>=128:raise ValueError('Page scale-claim budget exceeded')
            scales.append({**retained(run),'printed_denominator':int(scale[1]),'view_assignment_verified':False})
    for evidence,claim in joined:add_caption(evidence,claim)
    if fragment_status=='caption_fragment_budget_withheld':
        for row in views+titles:
            row['glyph_screen']={'status':'withheld','reason':'Complete caption fragment context budget required',
                'original_screen':row['glyph_screen']}
            row['layout_candidate_status']='glyph_screen_withheld'
    page_denominators=sorted({s['printed_denominator'] for s in scales})
    for row in views:
        denominator=row['printed_claim'].get('printed_scale_denominator')
        row['page_scale_claim_denominators']=page_denominators
        row['scale_scope_status']='no_inline_scale' if denominator is None else (
            'page_view_claim_difference' if page_denominators and set(page_denominators)!={denominator} else
            'agreeing_printed_claims_only' if page_denominators else 'inline_caption_claim_only')
        # Revit prints the per-view ratio on a separate line beneath the
        # caption. Keep local geometric correspondence as a hypothesis; a
        # nearby scale must never silently replace the inline printed claim.
        u=row['reading_direction_pdf_native'];n=(-u[1],u[0]);label=shape(row['label_geometry'])
        def extent(g,axis):return [sum(p[k]*axis[k] for k in (0,1)) for p in g.exterior.coords]
        a=extent(label,u);b=extent(label,n);height=max(b)-min(b);candidates=[]
        if row['glyph_screen']['status']=='raster_consistent_candidate':
            for scale in scales:
                if scale['glyph_screen']['status']!='raster_consistent_candidate':continue
                if sum(u[k]*scale['reading_direction_pdf_native'][k] for k in (0,1))<1-1e-7:continue
                g=shape(scale['label_geometry']);sa=extent(g,u);sb=extent(g,n)
                gap=min(b)-max(sb)
                if 0<=gap<=2*height and abs(min(a)-min(sa))<=height:
                    candidates.append(scale)
        row['adjacent_scale_candidates']=candidates
        row['adjacent_scale_assignment_verified']=False
        row['adjacent_scale_status']='one_adjacent_printed_scale_candidate' if len(candidates)==1 else (
            'ambiguous_adjacent_printed_scales' if candidates else 'no_supported_adjacent_scale')
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
        'caption_fragment_status':fragment_status,
        'native_fragment_line_contexts':fragment_contexts,
        'component_membership':membership,'subgraph_membership':groups,'checks':checks,'max_assignments':max_assignments,
        'counts':{**dict(counts),'view_captions':len(views),'candidate_windows':len(windows),'scoped_subgraph_candidates':sum(len(g['candidate_window_ids'])==1 for g in groups)},
        'view_scope_verified':False,'scale_application_verified':False,'world_geometry_additions':0,
        'limitations':['Caption row bands are layout hypotheses, not source-defined view boundaries.',
            'Bands can include notes, legends or title blocks. Whole source components are never clipped or reassigned across a band.',
            'Inline caption scale/state remain per-view claims; standalone page scales and sheet titles are not inherited.',
            'Duplicate, hidden and competing captions remain explicit. No physical geometry, measurement or registration is authorized.']}
