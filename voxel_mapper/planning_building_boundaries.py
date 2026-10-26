"""Label-supported 2D building outlines from original source fills and layouts."""
from concurrent.futures import CancelledError
from html import escape
import json
import math
import re

import pymupdf
from shapely.geometry import shape,mapping,box

from . import planning_hatch_regions,planning_area_layout,planning_gap_boundaries
from .building_spec import digest

VERSION='planning-building-boundaries-v1'
LIMITS={'max_fills':512,'max_labels':128,'max_points':100000,'max_checks':100000,'max_output_bytes':8000000}


def review(paving,layout=None,*,source_claims=None,native_page_bounds=None,options=None,cancelled=lambda:False):
    """Retain exact source contours; never select a nearest/smallest enclosure."""
    options={} if options is None else options
    if not isinstance(options,dict) or set(options)-set(LIMITS):raise ValueError('Known building boundary limits required')
    limits={**LIMITS,**options}
    if any(type(v) is not int or not 1<=v<=LIMITS[k] for k,v in limits.items()):raise ValueError('Lower-only building boundary limits required')
    if not isinstance(paving,dict) or paving.get('version')!=planning_hatch_regions.VERSION or paving.get('coordinate_frame')!='pdf_native_points_y_up':
        raise ValueError('Original native source fill review required')
    sha=paving.get('document_sha256');number=paving.get('page')
    if not re.fullmatch('[a-f0-9]{64}',str(sha)) or type(number) is not int or number<1:raise ValueError('Same-page source identity required')
    if layout is not None and layout.get('source_context'):
        bounds=layout['source_context']['native_page_bounds']
        if native_page_bounds is not None and native_page_bounds!=bounds:raise ValueError('Original page frame differs from layout')
        native_page_bounds=bounds
    if native_page_bounds is not None and (len(native_page_bounds)!=4 or not all(math.isfinite(v) for v in native_page_bounds) or native_page_bounds[0]>=native_page_bounds[2] or native_page_bounds[1]>=native_page_bounds[3]):raise ValueError('Finite original page frame required')
    claims=[] if source_claims is None else source_claims
    result={'version':VERSION,'document_sha256':sha,'page':number,'coordinate_frame':'pdf_native_points_y_up',
        'analysis_complete':True,'status':'building_boundary_review','records':[],'label_decisions':[],
        'source_paving_sha256':digest(paving),'source_layout_sha256':digest(layout) if layout is not None else None,
        'source_claims_sha256':digest(claims),'native_page_bounds':native_page_bounds,'limits':limits,'physical_identity_verified':False,
        'later_overpaint_visibility_verified':False,'height_reconstruction_eligible':False,
        'world_placement_eligible':False,'training_labels_generated':0,'model_weights_updated':False,
        'limitations':['Source outlines are 2D review proposals, not verified exterior walls or roof lines.',
            'Only visible literal labels in one unambiguous source fill supply additional building hints.',
            'Equal source contours merge; competing enclosures remain withheld.',
            'No heights, snapping, gap repair, training truth or surveyed placement are inferred.']}
    def check():
        if cancelled():raise CancelledError('Building boundary review cancelled')
    def finish(reason=None):
        if reason:result.update(analysis_complete=False,status='building_boundaries_withheld',reason=reason,records=[])
        result['summary']={'building_boundary_candidates':len(result['records']),
            'additional_labelled_fill_boundaries':sum(r['source_layout_candidate_ids']==[] for r in result['records']),
            'unresolved_fill_labels':sum(r['status']!='unique_source_fill' for r in result['label_decisions']),
            'duplicate_source_paints_grouped':sum(max(0,len(r['source_fills'])-1) for r in result['records'])}
        if len(json.dumps(result,allow_nan=False).encode())>limits['max_output_bytes']:
            result.update(analysis_complete=False,status='building_boundaries_withheld',reason='Building review output budget exceeded',records=[],label_decisions=[],summary={'building_boundary_candidates':0,'additional_labelled_fill_boundaries':0,'unresolved_fill_labels':len(claims),'duplicate_source_paints_grouped':0})
        check();return result
    check()
    if not paving.get('analysis_complete'):return finish('Complete source fills required')
    if len(paving.get('records',[]))>limits['max_fills'] or len(claims)>limits['max_labels']:return finish('Building source count budget exceeded')
    points=checks=0;groups=[]
    def polygon(value):
        nonlocal points
        g=shape(value)
        if g.geom_type not in ('Polygon','MultiPolygon') or g.is_empty or not g.is_valid or g.has_z or not all(math.isfinite(v) for v in g.bounds):raise ValueError('Finite source polygons required')
        parts=list(g.geoms) if g.geom_type=='MultiPolygon' else [g]
        points+=sum(len(p.exterior.coords)+sum(len(r.coords) for r in p.interiors) for p in parts)
        if points>limits['max_points']:raise ValueError('Building point budget exceeded')
        return g
    def compare():
        nonlocal checks
        check();checks+=1
        if checks>limits['max_checks']:raise ValueError('Building comparison budget exceeded')
    def add(g,*,candidate=None,fill=None,label=None):
        group=None
        for prior in groups:
            compare()
            if g.equals(prior['geometry']):group=prior;break
        if group is None:
            group={'geometry':g,'candidates':[],'fills':[],'labels':[]};groups.append(group)
        for key,value in (('candidates',candidate),('fills',fill),('labels',label)):
            if value is not None and value not in group[key]:group[key].append(value)
    try:
        if layout is not None:
            if layout.get('document_sha256')!=sha or layout.get('page')!=number:raise ValueError('Same-page source layout required')
            planning_area_layout.validate_layout(layout)
            if layout.get('analysis_complete'):
                for row in layout['candidates']:
                    if row['role']=='building':add(polygon(row['geometry_pdf_native']),candidate=row['id'])
        fills=[]
        masks={r['paint_operation_index'] for r in paving.get('legend_backplates',[])}
        for row in paving.get('records',[]):
            check()
            if (row.get('paint_kind')=='solid' and row.get('fill_opacity')==1
                    and row.get('solid_colour_space') in ('/DeviceRGB','/DeviceGray')
                    and row.get('solid_colour_components') in ([1.,1.,1.],[1.])
                    and row.get('paint_operation_index') not in masks
                    and row.get('status')!='source_text_background_fill_withheld'):
                g=polygon(row['geometry'])
                if native_page_bounds is not None and g.covers(box(*native_page_bounds)):continue
                fills.append((row,g))
        for claim in claims:
            check()
            if (claim.get('document_sha256')!=sha or claim.get('page')!=number or claim.get('role')!='building'
                    or claim.get('glyph_screen',{}).get('status')!='raster_consistent_candidate'):
                raise ValueError('Same-page visible building label proof required')
            label=polygon(claim['label_geometry_pdf_native']);matches=[]
            for row,g in fills:
                compare()
                if g.covers(label):matches.append((row,g))
            unique=[]
            for row,g in matches:
                equal=False
                for prior in unique:
                    compare()
                    if g.equals(prior):equal=True;break
                if not equal:unique.append(g)
            decision={'label_id':claim['id'],'text':claim['text'],'label_geometry_pdf_native':claim['label_geometry_pdf_native'],
                'status':'unique_source_fill' if len(unique)==1 and unique[0].geom_type=='Polygon' else 'ambiguous_source_fills' if unique else 'no_closed_source_fill',
                'distinct_source_contours':len(unique),'source_fill_ids':[r['id'] for r,_ in matches]}
            result['label_decisions'].append(decision)
            if decision['status']!='unique_source_fill':continue
            for row,g in matches:
                add(g,fill={'id':row['id'],'paint_operation_index':row['paint_operation_index'],'source_record_sha256':digest(row)},label=claim)
        for group in groups:
            g=group['geometry'];geometry=json.loads(json.dumps(mapping(g)))
            result['records'].append({'id':digest([VERSION,sha,number,g.normalize().wkb_hex]),
                'geometry_pdf_native':geometry,'source_layout_candidate_ids':sorted(group['candidates']),
                'source_fills':sorted(group['fills'],key=lambda r:r['paint_operation_index']),
                'labels':sorted(group['labels'],key=lambda r:r['id']),
                'basis':'existing_layout_and_labelled_fill' if group['candidates'] and group['fills'] else 'existing_source_layout' if group['candidates'] else 'unique_labelled_opaque_source_fill',
                'physical_identity_verified':False,'height_reconstruction_eligible':False})
        result['records'].sort(key=lambda r:r['id']);result['work']={'points':points,'comparisons':checks}
    except (ValueError,RuntimeError,KeyError,TypeError,OverflowError) as error:return finish(str(error)[:512])
    return finish()


def page_review(page,paving,layout=None,*,options=None,cancelled=lambda:False):
    claims=planning_gap_boundaries.page_building_claims(page,paving,cancelled=cancelled)
    from .planning_view_geometry import _native_frame
    return review(paving,layout,source_claims=claims,native_page_bounds=list(_native_frame(page).bounds),options=options,cancelled=cancelled)


def write_overlay(result,paving,preview,destination):
    if not result or not result['analysis_complete']:return None
    from pathlib import Path
    base=planning_hatch_regions.write_overlay(paving,preview,destination)
    if not base:return None
    matrix=pymupdf.Matrix(preview['pdf_native_to_pixels']);paths=[]
    for row in result['records']:
        g=shape(row['geometry_pdf_native']);parts=list(g.geoms) if g.geom_type=='MultiPolygon' else [g]
        for part in parts:
            commands=[]
            for ring in [part.exterior,*part.interiors]:
                points=[pymupdf.Point(*p)*matrix for p in ring.coords]
                commands.append('M'+' L'.join(f'{p.x:.4f},{p.y:.4f}' for p in points)+' Z')
            label=', '.join(c['text'] for c in row['labels']) or 'Existing source-layout proposal'
            paths.append('<path d="'+' '.join(commands)+'" fill="#278ada" fill-opacity="0.18" fill-rule="evenodd" stroke="#0875db" stroke-width="2.5" vector-effect="non-scaling-stroke"><title>'+escape(label)+'; '+row['id']+'</title></path>')
    for row in result['label_decisions']:
        if row['status']=='unique_source_fill':continue
        g=shape(row['label_geometry_pdf_native']);points=[pymupdf.Point(*p)*matrix for p in g.exterior.coords]
        paths.append('<path d="M'+' L'.join(f'{p.x:.4f},{p.y:.4f}' for p in points)+' Z" fill="none" stroke="#d38200" stroke-width="2"><title>Unresolved: '+escape(row['text'])+'</title></path>')
    path=Path(destination);raw=path.read_text().replace('</svg>',''.join(paths)+'</svg>').encode()
    if len(raw)>16000000:raise ValueError('Building overlay byte budget exceeded')
    path.write_bytes(raw)
    import hashlib
    return {'file':path.name,'sha256':hashlib.sha256(raw).hexdigest(),**result['summary']}
