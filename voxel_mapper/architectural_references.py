"""Printed object-reference correspondences; never coordinate controls or height bindings."""
from collections import defaultdict
import hashlib
import json
import re
import pymupdf
from shapely.geometry import Polygon,shape,mapping
from shapely.strtree import STRtree
from .drawing_geometry import native_inverse
from .ordinary_surfaces import label_runs
from .glyph_visibility import screen_architectural_span
from .elevation_interpretation import caption

VERSION='architectural-source-references-v2'


def reference(text):
    if not isinstance(text,str) or len(text)>128:return None
    value=re.sub(r'\s+','',text.lower())
    if re.fullmatch(r'archway[1-9]\d{0,2}',value):return 'archway:'+value[7:]
    match=re.fullmatch(r'([wd])\.(\d{1,3})\.(\d{1,3})',value)
    if match:return ':'.join(match.groups())
    return None


def review_page(page,sha,number,polygons):
    traces=page.get_texttrace()
    if len(traces)>10000 or sum(len(r['chars']) for r in traces)>500000:raise ValueError('Architectural reference text budget exceeded')
    if len(polygons)>20000 or any(r['document_sha256']!=sha or r['page']!=number
            or r.get('coordinate_frame')!='pdf_native_points_y_up' for r in polygons):
        raise ValueError('Source-bound architectural reference geometry required')
    runs=list(label_runs(traces));codes=[];views=[];refs=[];inverse=native_inverse(page)
    def retained(run):
        rect=pymupdf.Rect(run['bbox'])
        points=[pymupdf.Point(x,y)*inverse for x,y in [(rect.x0,rect.y0),(rect.x1,rect.y0),(rect.x1,rect.y1),(rect.x0,rect.y1)]]
        return {'text':''.join(chr(c[0]) for c in run['chars']).strip(),
            'label_geometry':mapping(Polygon([(p.x,p.y) for p in points])),
            'trace_indices':run['trace_indices'],'character_indices':run['character_indices'],
            'glyph_screen':screen_architectural_span(page,run,zoom=24 if run['size']<4 else 6)}
    for run in runs:
        text=''.join(chr(c[0]) for c in run['chars']).strip()
        project=re.fullmatch(r'(\d{3,6})\s+([A-Z]{1,4})',text)
        if project:
            if len(codes)>=32:raise ValueError('Architectural project-code budget exceeded')
            codes.append({**retained(run),'project_code':project[1]+':'+project[2]})
        value=re.sub(r'\s+','',text.lower());elevation=caption(text)
        plan=re.fullmatch(r'(?:(existing|proposed))?(?:(ground|first|second)floor|roof)plan(?:[\'’]as(existing|proposed)[\'’])?(?:\|1:\d{1,5})?',value)
        if elevation or plan:
            if len(views)>=32:raise ValueError('Architectural view-claim budget exceeded')
            views.append({**retained(run),'view_kind':'elevation' if elevation else 'plan',
                'printed_state':elevation['printed_state'] if elevation else plan[3] or plan[1] or 'unspecified'})
        identifier=reference(text)
        if identifier:
            if len(refs)>=500:raise ValueError('Architectural object-reference budget exceeded')
            refs.append({**retained(run),'reference_id':identifier})
    geometries=[shape(r['geometry']) for r in polygons];ids=[r['id'] for r in polygons]
    if len(set(ids))!=len(ids) or any(g.is_empty or not g.is_valid for g in geometries):raise ValueError('Unique valid reference enclosures required')
    index=STRtree(geometries)
    for row in refs:
        row.update(containing_candidate_ids=[],physical_identity_verified=False,coordinate_control_verified=False)
        if row['glyph_screen']['status']=='raster_consistent_candidate':
            label=shape(row['label_geometry'])
            row['containing_candidate_ids']=sorted(ids[int(i)] for i in index.query(label,predicate='intersects') if geometries[int(i)].contains(label))
            row['enclosure_status']='unique_complete_enclosure' if len(row['containing_candidate_ids'])==1 else 'ambiguous_or_missing_enclosure'
        else:row['enclosure_status']='glyph_screen_withheld'
    visible_views=[r for r in views if r['glyph_screen']['status']=='raster_consistent_candidate']
    kinds={r['view_kind'] for r in views};states={r['printed_state'] for r in views if r['printed_state']!='unspecified'}
    visible_kinds={r['view_kind'] for r in visible_views}
    visible_states={r['printed_state'] for r in visible_views if r['printed_state']!='unspecified'}
    values={r['project_code'] for r in codes};visible_codes={r['project_code'] for r in codes if r['glyph_screen']['status']=='raster_consistent_candidate'}
    project_code=next(iter(values)) if len(values)==1 and values<=visible_codes else None
    return {'version':VERSION,'document_sha256':sha,'page':number,'project_code_claims':codes,'view_claims':views,
        'project_code':project_code,'view_kind':next(iter(kinds)) if len(kinds)==1 and kinds<=visible_kinds else 'unspecified_or_mixed',
        'printed_state':next(iter(states)) if len(states)==1 and states<=visible_states else 'unspecified_or_conflicting',
        'reference_occurrences':refs,'source_polygon_records_sha256':hashlib.sha256(json.dumps(polygons,sort_keys=True).encode()).hexdigest(),
        'project_scope_verified':False,'physical_identity_verified':False,'coordinate_alignment_verified':False,
        'height_application_verified':False,'world_geometry_additions':0}


def link_pages(pages,*,max_occurrences=100000):
    if type(max_occurrences) is not int or not 1<=max_occurrences<=100000 or len(pages)>10000:
        raise ValueError('Bounded architectural reference linking required')
    groups=defaultdict(list);count=0
    if len({(p['document_sha256'],p['page']) for p in pages})!=len(pages):raise ValueError('Distinct source reference pages required')
    for page in pages:
        if page['version']!=VERSION:raise ValueError('Current architectural reference version required')
        occurrences=page['reference_occurrences'];count+=len(occurrences)
        if count>max_occurrences:return {'version':VERSION,'status':'reference_budget_withheld','links':[],
            'occurrences_examined':count,'world_geometry_additions':0}
        if (not page['project_code'] or page['view_kind'] not in ('plan','elevation')
                or page['printed_state'] not in ('existing','proposed')):continue
        for i,row in enumerate(occurrences):
            key=(page['project_code'],page['printed_state'],row['reference_id'])
            groups[key].append({'document_sha256':page['document_sha256'],'page':page['page'],'view_kind':page['view_kind'],
                'occurrence_index':i,'glyph_screen_status':row['glyph_screen']['status'],
                'containing_candidate_ids':row['containing_candidate_ids'],
                'source_end_connection_indices':row.get('source_end_connection_indices',[]),
                'complete_source_cycle_candidates':row.get('complete_source_cycle_candidates',0)})
    links=[]
    for (project,state,identifier),occurrences in sorted(groups.items()):
        visible=[r for r in occurrences if r['glyph_screen_status']=='raster_consistent_candidate']
        if not all(any(r['view_kind']==kind for r in visible) for kind in ('plan','elevation')):continue
        multiplicity=len({(r['document_sha256'],r['page']) for r in occurrences})<len(occurrences)
        links.append({'project_code':project,'printed_state':state,'reference_id':identifier,'occurrences':occurrences,
            'status':'shared_printed_object_reference_candidates','repeated_occurrences_present':multiplicity,
            'project_scope_verified':False,'physical_identity_verified':False,'coordinate_alignment_verified':False,
            'height_application_verified':False,'world_geometry_additions':0})
    return {'version':VERSION,'status':'printed_reference_correspondences_only','links':links,'occurrences_examined':count,
        'coordinate_alignment_verified':False,'height_application_verified':False,'world_geometry_additions':0,
        'limitations':['Matching printed project codes and object IDs is a correspondence candidate, not verified common project scope.',
            'Repeated/hidden/key-plan occurrences are retained; none is selected as a coordinate control.',
            'Existing and proposed states do not cross-link; physical geometry, view scopes and vertical datum remain unresolved.']}
