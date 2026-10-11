"""Original PDF viewport declarations; no inferred frames or scale application."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
from io import BytesIO
from pypdf.errors import PdfReadError
from pypdf import PdfReader
from pypdf.generic import ArrayObject,DictionaryObject
from shapely.geometry import box,shape,mapping
from shapely.strtree import STRtree
from .architectural_graph import VERSION as GRAPH_VERSION
from .architectural_view_layout import VERSION as LAYOUT_VERSION

VERSION='architectural-source-viewports-v1'


def caption_name(text):
    value=re.sub(r'\s+','',text.lower())
    return re.sub(r"(?:['’]as(?:existing|proposed)['’])?(?:\|1:\d{1,5})?$",'',value)


def review(path,sha,number,graph,layout,*,max_checks=100000):
    if type(max_checks) is not int or not 1<=max_checks<=100000:raise ValueError('Bounded viewport checks required')
    if (graph['version']!=GRAPH_VERSION or graph['status']!='source_drawing_topology_only'
            or layout['version']!=LAYOUT_VERSION or graph['document_sha256']!=sha or layout['document_sha256']!=sha
            or graph['page']!=number or layout['page']!=number
            or graph.get('coordinate_frame')!='pdf_native_points_y_up' or layout.get('coordinate_frame')!='pdf_native_points_y_up'
            or layout['source_graph_sha256']!=hashlib.sha256(json.dumps(graph,sort_keys=True).encode()).hexdigest()):
        raise ValueError('Same current source graph and caption layout required')
    def unavailable(reason):return {'version':VERSION,'document_sha256':sha,'page':number,
        'coordinate_frame':'pdf_native_points_y_up','source_graph_sha256':layout['source_graph_sha256'],
        'source_layout_sha256':hashlib.sha256(json.dumps(layout,sort_keys=True).encode()).hexdigest(),
        'status':reason,'viewports':[],'checks':0,'max_checks':max_checks,
        'counts':{'viewport_declarations':0,'named_caption_candidates':0},'view_scope_verified':False,
        'scale_application_verified':False,'world_geometry_additions':0}
    path=Path(path)
    if path.stat().st_size>32*1024*1024:
        with path.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=sha:raise ValueError('Original PDF checksum mismatch')
        return unavailable('source_metadata_byte_budget_withheld')
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=sha:raise ValueError('Original PDF checksum mismatch')
    try:
        reader=PdfReader(BytesIO(data),strict=True)
        if len(reader.pages)>10000:return unavailable('source_metadata_page_budget_withheld')
        if type(number) is not int or not 1<=number<=len(reader.pages):raise ValueError('Bounded source page required')
        page=reader.pages[number-1]
    except PdfReadError:return unavailable('source_metadata_parser_withheld')
    if float(page.get('/UserUnit',1))!=1:return unavailable('nondefault_source_user_units_withheld')
    def resolved(value):
        try:return value.get_object() if value is not None else None
        except (PdfReadError,RecursionError):return None
    raw=page.get('/VP');declared=resolved(raw) if raw is not None else []
    if raw is not None and not isinstance(declared,ArrayObject):return unavailable('unsupported_source_viewport_encoding')
    if len(declared)>128:return unavailable('source_viewport_declaration_budget_withheld')
    crop=box(float(page.cropbox.left),float(page.cropbox.bottom),float(page.cropbox.right),float(page.cropbox.top))
    captions=layout['view_captions'];labels=[shape(r['label_geometry']) for r in captions];label_index=STRtree(labels)
    components=graph['source_components'];geometries=[shape(r['geometry']) for r in components];component_index=STRtree(geometries)
    records=[];checks=0;counts=Counter()
    for ordinal,value in enumerate(declared):
        obj=resolved(value);row={'viewport_index':ordinal,'viewport_object_reference':
            {'idnum':value.idnum,'generation':value.generation} if hasattr(value,'idnum') else None,
            'source_declared_boundary_supported':False,'source_named_caption_supported':False,
            'view_scope_verified':False,'scale_application_verified':False,'physical_identity_verified':False,
            'containing_caption_ids':[],'intersecting_caption_ids':[],'component_membership':[]}
        records.append(row)
        if not isinstance(obj,DictionaryObject) or resolved(obj.get('/Type'))!='/Viewport':row['status']='unsupported_viewport_dictionary';continue
        bbox=obj.get('/BBox');bbox=resolved(bbox)
        try:
            coords=[float(v) for v in bbox] if isinstance(bbox,ArrayObject) and len(bbox)==4 else []
        except (TypeError,ValueError):coords=[]
        name=str(resolved(obj.get('/Name')) or '')
        if len(name)>512:row['status']='viewport_name_budget_withheld';continue
        row.update(name=name,measure_dictionary_present='/Measure' in obj)
        if len(coords)!=4 or not all(math.isfinite(v) for v in coords) or coords[2]<=coords[0] or coords[3]<=coords[1]:
            row['status']='invalid_source_viewport_bbox';continue
        region=box(*coords)
        row.update(bbox_pdf_native=coords,geometry=mapping(region))
        if not crop.covers(region):row['status']='viewport_outside_native_crop';continue
        row['source_declared_boundary_supported']=True
        for k in label_index.query(region,predicate='intersects'):
            checks+=1
            if checks>max_checks:break
            k=int(k);row['intersecting_caption_ids'].append(captions[k]['id'])
            if region.contains(labels[k]):row['containing_caption_ids'].append(captions[k]['id'])
        if checks>max_checks:break
        row['containing_caption_ids'].sort();row['intersecting_caption_ids'].sort()
        if len(row['intersecting_caption_ids'])!=1 or row['intersecting_caption_ids']!=row['containing_caption_ids']:
            row['status']='missing_competing_or_boundary_crossing_caption'
        else:
            candidate=next(r for r in captions if r['id']==row['containing_caption_ids'][0])
            if candidate['glyph_screen']['status']!='raster_consistent_candidate':row['status']='caption_visibility_withheld'
            elif not row['name'] or caption_name(row['name'])!=caption_name(candidate['text']):row['status']='viewport_name_caption_mismatch'
            else:row.update(status='source_named_viewport_candidate',source_named_caption_supported=True,
                caption_id=candidate['id'],printed_caption_claim=candidate['printed_claim'])
        for k in component_index.query(region,predicate='intersects'):
            checks+=1
            if checks>max_checks:break
            k=int(k);row['component_membership'].append({'component_id':components[k]['id'],
                'status':'whole_component_inside_source_viewport' if region.covers(geometries[k]) else 'source_viewport_boundary_crossing',
                'physical_identity_verified':False})
        if checks>max_checks:break
        row['component_membership'].sort(key=lambda r:r['component_id'])
    exhausted=checks>max_checks
    # Overlapping/repeated viewport declarations cannot select a caption target.
    multiplicity=Counter(i for r in records for i in r['intersecting_caption_ids'])
    for row in records:
        if row['source_named_caption_supported'] and multiplicity[row['caption_id']]!=1:
            row.update(status='competing_source_viewport_declarations',source_named_caption_supported=False)
        if exhausted:row.update(status='viewport_budget_withheld',source_named_caption_supported=False,component_membership=[])
        counts[row['status']]+=1
    if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('Source PDF changed during viewport review')
    return {'version':VERSION,'document_sha256':sha,'page':number,'coordinate_frame':'pdf_native_points_y_up',
        'source_graph_sha256':layout['source_graph_sha256'],
        'source_layout_sha256':hashlib.sha256(json.dumps(layout,sort_keys=True).encode()).hexdigest(),
        'status':'viewport_budget_withheld' if exhausted else 'source_viewport_review_only' if records else 'no_source_viewport_declarations',
        'viewports':records,'checks':checks,'max_checks':max_checks,
        'counts':{**dict(counts),'viewport_declarations':len(declared),'named_caption_candidates':sum(r['source_named_caption_supported'] for r in records)},
        'view_scope_verified':False,'scale_application_verified':False,'world_geometry_additions':0,
        'limitations':['A declared PDF viewport supplies a source rectangle, not verified physical drawing-view semantics.',
            'Exact names and whole visible captions are correspondence evidence only; duplicate declarations remain competing.',
            'Crossing source components are retained whole. No crop, scale, physical dimension or coordinate control is applied.',
            'Printed frames, caption bands and page borders are not substituted for missing viewport metadata.']}
