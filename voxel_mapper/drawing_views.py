"""Native drawing/view references and nominal paper-scale evidence, never registration."""
import hashlib
import math
import re
import pymupdf
from .glyph_visibility import screen_span

VERSION='native-drawing-view-links-v1'
TITLE=re.compile(r'Elevation\s+(\d{1,2})\s+to\s+(?:the\s+)?([NS])\.?\s*(East|West)',re.I)
SCALE=re.compile(r'\s*1\s*:\s*(\d{1,5})\s*')


def text(span):
    # Co-located CAD overprints remain in the original span and glyph screen.
    seen=set();characters=[]
    for char in span['chars']:
        key=(char[0],char[1],tuple(round(v,3) for v in char[2]),tuple(round(v,3) for v in char[3]))
        if key not in seen:characters.append(chr(char[0]));seen.add(key)
    return ''.join(characters).strip()


def sheet_identity(traces):
    candidates=[]
    for index,span in enumerate(traces):
        raw=''.join(chr(c[0]) for c in span['chars']).strip()
        match=re.fullmatch(r'(?P<unit>(?P<project>\d{3,5})\s*-\s*(?P<sheet>\d{1,3}))(?:(?P=unit)){0,3}',raw)
        if not match:continue
        length=len(match['unit']);count=len(raw)//length
        if len(span['chars'])!=len(raw):continue
        maximum=0.
        for j in range(length,len(raw)):
            a=span['chars'][j][2];b=span['chars'][j%length][2]
            maximum=max(maximum,math.hypot(a[0]-b[0],a[1]-b[1]))
        if maximum>.5:continue
        candidates.append({'project':match['project'],'sheet':int(match['sheet']),'trace_index':index,
                           'overprint_count':count,'maximum_overprint_offset_points':maximum})
    identities={(r['project'],r['sheet']) for r in candidates}
    return candidates[0] if len(identities)==1 else None


def resolve_identity(traces,metadata):
    native=sheet_identity(traces)
    declared=re.fullmatch(r'(\d{3,5})\s*-\s*(\d{1,3})',str((metadata or {}).get('drawing_number','')))
    if not declared:return native
    if native and (native['project'],native['sheet'])!=(declared[1],int(declared[2])):return None
    return {**(native or {}),'project':declared[1],'sheet':int(declared[2]),
            'identity_basis':'pinned_catalogue_claim; native header candidate retained',
            'native_header_visibility_verified':False,'drawing_identity_verified':False}


def page_labels(page,groups,*,sheet_metadata=None):
    traces=page.get_texttrace()
    if len(traces)>10000 or sum(len(s['chars']) for s in traces)>500000:raise ValueError('View text budget exceeded')
    identity=resolve_identity(traces,sheet_metadata);rotation=page.rotation_matrix;views=[];screens={}
    for index,span in enumerate(traces):
        match=TITLE.fullmatch(text(span))
        if not match:continue
        box=pymupdf.Rect(span['bbox'])*rotation;center=(box.tl+box.br)*.5
        possible=[]
        for group in groups:
            gb=pymupdf.Rect(group['bbox_page_points'])*rotation
            if gb.x0<center.x<gb.x1 and 0<=center.y-gb.y1<=64:possible.append(group['id'])
        scales=[]
        for j,other in enumerate(traces):
            scale=SCALE.fullmatch(text(other))
            if not scale or other['dir']!=span['dir']:continue
            sb=pymupdf.Rect(other['bbox'])*rotation
            if abs(sb.x0-box.x0)<=1 and 0<=sb.y0-box.y1<=24:
                scales.append({'denominator':int(scale[1]),'trace_index':j,'bbox_page_points':list(other['bbox'])})
        checks=[index]+[s['trace_index'] for s in scales]+([identity['trace_index']] if identity and 'trace_index' in identity and not identity.get('identity_basis') else [])
        for j in checks:
            if j not in screens:screens[j]=screen_span(page,traces[j])
        visible=all(screens[j]['status']=='raster_consistent_candidate' for j in checks)
        record={'view_index':int(match[1]),'bearing_label_candidate':match[2].upper()+match[3][0].upper(),
                'title':text(span),'title_trace_index':index,'title_bbox_page_points':list(span['bbox']),
                'artwork_review_window_ids':possible,'scale_candidates':scales,'sheet_identity_candidate':identity,
                'glyph_screen_trace_indices':checks,'glyph_screen_status':'raster_consistent_candidate' if visible else 'withheld',
                'status':'unverified_view_label_candidate','view_identity_verified':False,'scale_verified':False,
                'bearing_world_axes_verified':False,'accepted_feature':False,'world_geometry_additions':0}
        if not visible:record['status']='withheld_view_label_visibility'
        elif len(possible)!=1:record['status']='withheld_view_artwork_assignment'
        elif len(scales)!=1 or not scales[0]['denominator']:record['status']='withheld_view_scale_assignment'
        elif not identity:record['status']='withheld_sheet_identity'
        else:
            record['view_key_candidate']=[identity['project'],identity['sheet'],record['view_index']]
            record['nominal_metres_per_pdf_point_candidate']=scales[0]['denominator']*.0254/72
        views.append(record)
        if len(views)>100:raise ValueError('View label budget exceeded')
    header=sheet_identity(traces)
    if header and header['trace_index'] not in screens:screens[header['trace_index']]=screen_span(page,traces[header['trace_index']])
    return {'version':VERSION,'views':views,'glyph_screens':screens,'sheet_identity_candidate':identity,
            'world_geometry_additions':0}


def attach_metrics(page,records,labels):
    from shapely.geometry import shape
    from shapely.affinity import affine_transform
    matrix=page.rotation_matrix
    for record in records:
        ids=record.get('raster_region_review',{}).get('artwork_review_window_ids',[])
        matches=[v for v in labels['views'] if v.get('view_key_candidate') and v['artwork_review_window_ids']==ids and len(ids)==1]
        if len(matches)!=1:continue
        view=matches[0];record['drawing_view_candidate']={k:view[k] for k in
              ('view_key_candidate','bearing_label_candidate','title_trace_index','nominal_metres_per_pdf_point_candidate','view_identity_verified','scale_verified')}
        candidate=record.get('raster_contrast_boundary_review',{})
        if candidate.get('status')!='unverified_contrast_boundary_candidate':continue
        geometry=shape(candidate['geometry'])
        display=affine_transform(geometry,[matrix.a,matrix.c,matrix.b,matrix.d,matrix.e,matrix.f])
        x0,y0,x1,y1=display.bounds;unit=view['nominal_metres_per_pdf_point_candidate']
        candidate['nominal_measurements_candidate']={'width_m':(x1-x0)*unit,'height_m':(y1-y0)*unit,
                'area_m2':geometry.area*unit*unit,'scale_verified':False,'depth_verified':False,
                'height_datum_verified':False,'limitations':['Paper scale is a drawing claim; component completeness and world registration remain unverified.']}


def page_references(page,*,sheet_metadata=None):
    """Candidate Revit-style sheet bubbles with a filled corner and outside view index.

    Exact source primitives are retained. Marker semantics, clipping and bearing
    remain candidates; no nearest numeric text or building edge is selected.
    """
    traces=page.get_texttrace();identity=resolve_identity(traces,sheet_metadata);paths=page.get_drawings()
    if len(traces)>10000 or len(paths)>100000:raise ValueError('View reference budget exceeded')
    numbers=[(i,s,int(text(s))) for i,s in enumerate(traces) if re.fullmatch(r'\d{1,3}',text(s))]
    if len(numbers)>5000:raise ValueError('View numeric budget exceeded')
    rectangles=[(i,p) for i,p in enumerate(paths) if p['type']=='f' and p.get('fill')==(0.,0.,0.)
                and p.get('fill_opacity')==1 and not p.get('layer') and len(p['items'])==1 and p['items'][0][0]=='re']
    records=[];screens={};comparisons=0
    for path_index,path in enumerate(paths):
        if path['type']!='s' or len(path['items'])!=4 or any(item[0]!='c' for item in path['items']):continue
        rect=path['rect'];radius=(rect.width+rect.height)/4
        if not 3<=radius<=40 or abs(rect.width-rect.height)>.02*radius or path.get('layer') or path.get('stroke_opacity')!=1:continue
        start=path['items'][0][1];end=path['items'][-1][-1]
        if math.hypot(start.x-end.x,start.y-end.y)>.3:continue
        center=(rect.tl+rect.br)*.5
        comparisons+=len(numbers)
        if comparisons>500000:raise ValueError('View marker comparison budget exceeded')
        inside=[(i,s,n) for i,s,n in numbers if rect.contains((pymupdf.Rect(s['bbox']).tl+pymupdf.Rect(s['bbox']).br)*.5)]
        if len(inside)!=1:continue
        sheet_index,sheet_span,sheet=inside[0];markers=[]
        for fill_index,fill in rectangles:
            comparisons+=1
            if comparisons>500000:raise ValueError('View marker comparison budget exceeded')
            box=fill['rect'];fc=(box.tl+box.br)*.5
            if not pymupdf.Rect(rect.x0-.3,rect.y0-.3,rect.x1+.3,rect.y1+.3).contains(box) or not .4*radius<=box.width<=1.1*radius or not .4*radius<=box.height<=1.1*radius:continue
            dx,dy=fc.x-center.x,fc.y-center.y
            if abs(dx)<.2*radius or abs(dy)<.2*radius:continue
            comparisons+=len(numbers)
            if comparisons>500000:raise ValueError('View marker comparison budget exceeded')
            # Only labels outside both sides of the marked corner are eligible.
            for index,span,view in numbers:
                if not 1<=view<=99 or span['dir']!=sheet_span['dir']:continue
                b=pymupdf.Rect(span['bbox']);c=(b.tl+b.br)*.5;margin=2*span['size']
                horizontal=rect.x0-margin<=c.x<rect.x0 if dx<0 else rect.x1<c.x<=rect.x1+margin
                vertical=rect.y0-margin<=c.y<rect.y0 if dy<0 else rect.y1<c.y<=rect.y1+margin
                if horizontal and vertical:markers.append((fill_index,index,view,box))
        if len(markers)!=1:continue
        fill_index,view_index,view,box=markers[0]
        indices=[sheet_index,view_index]+([identity['trace_index']] if identity and 'trace_index' in identity and not identity.get('identity_basis') else [])
        for index in indices:
            if index not in screens:screens[index]=screen_span(page,traces[index])
        visible=all(screens[i]['status']=='raster_consistent_candidate' for i in indices)
        record={'target_sheet_candidate':sheet,'target_view_candidate':view,'source_sheet_identity_candidate':identity,
                'circle_path_index':path_index,'circle_paint_seqno':path['seqno'],'circle_bbox_page_points':list(rect),
                'circle_source_beziers':[[list(v) for v in item[1:]] for item in path['items']],
                'corner_fill_path_index':fill_index,'corner_fill_bbox_page_points':list(box),
                'sheet_number_trace_index':sheet_index,'view_number_trace_index':view_index,'glyph_screen_trace_indices':indices,
                'status':'unverified_native_view_reference_candidate' if visible and identity else 'withheld_view_reference_visibility_or_identity',
                'marker_semantics_verified':False,'marker_clipping_verified':False,'physical_building_identity_verified':False,
                'accepted_feature':False,'world_geometry_additions':0}
        if visible and identity:record['target_view_key_candidate']=[identity['project'],sheet,view]
        records.append(record)
        if len(records)>500:raise ValueError('View reference count budget exceeded')
    header=sheet_identity(traces)
    if header and header['trace_index'] not in screens:screens[header['trace_index']]=screen_span(page,traces[header['trace_index']])
    return {'version':VERSION,'references':records,'glyph_screens':screens,'world_geometry_additions':0}


def cross_links(pages):
    by_key={}
    for sha,number,labels,_ in pages:
        for view in labels.get('views',[]):
            if 'view_key_candidate' in view:by_key.setdefault(tuple(view['view_key_candidate']),[]).append((sha,number,view))
    links=[]
    for sha,number,_,references in pages:
        for reference in references.get('references',[]):
            key=reference.get('target_view_key_candidate');matches=by_key.get(tuple(key),[]) if key else []
            links.append({'source_document_sha256':sha,'source_page':number,'reference':reference,
                         'target_candidates':[{'document_sha256':digest,'page':n,'view':view} for digest,n,view in matches],
                         'status':'unique_unverified_plan_elevation_reference' if len(matches)==1 else 'withheld_nonunique_or_missing_view_target',
                         'physical_building_identity_verified':False,'world_geometry_additions':0})
    return links
