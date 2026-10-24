"""Nominal plan measurements and linked printed-size diagnostics, never buildings."""
from concurrent.futures import CancelledError
from html import escape
import json
import math
from pathlib import Path
import re

import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import Polygon, mapping, shape

from . import architectural_view_layout, glyph_visibility, ordinary_surfaces, planning_component_footprints
from .building_spec import digest
from .drawing_page_tools import native_inverse

VERSION='planning-component-measurements-v1'
LIMITS={'max_components':32,'max_text_evidence':128,'max_scale_claims':8,
        'max_points':200000,'max_output_bytes':4000000}
CODE=re.compile(r'(?P<series>[A-Z][A-Z0-9]{1,9}(?:-[A-Z0-9]{1,10}){4,7})-(?P<sheet>\d{4})')
SIZE=re.compile(r'(?:(?P<count>[1-9]\d?)\s+No\.?\s+)?'
    r'(?P<a>\d{1,4}(?:\.\d{1,3})?)\s*(?P<ua>ft|feet|mm|m)\s*[x×]\s*'
    r'(?P<b>\d{1,4}(?:\.\d{1,3})?)\s*(?P<ub>ft|feet|mm|m)\s+'
    r'(?:steel\s+)?(?:shipping\s+)?containers?\.?',re.I)
UNITS={'ft':.3048,'feet':.3048,'m':1.,'mm':.001}


def printed_size(text):
    match=SIZE.fullmatch(text.strip())
    if not match:return None
    lengths=[float(match[k])*UNITS[match[u].lower()] for k,u in (('a','ua'),('b','ub'))]
    if not all(0<v<=100 for v in lengths):return None
    return {'family':'container','printed_count':int(match['count']) if match['count'] else None,
            'length_pair_m':sorted(lengths),'printed_units':[match['ua'].lower(),match['ub'].lower()],
            'axes_verified':False,'height_supplied':False}


def _bounded(values):
    values={} if values is None else values
    if not isinstance(values,dict) or set(values)-set(LIMITS):raise ValueError('Known measurement limits required')
    limits={**LIMITS,**values}
    if any(type(v) is not int or not 1<=v<=LIMITS[k] for k,v in limits.items()):
        raise ValueError('Lower-only measurement limits required')
    if limits['max_output_bytes']<16384:raise ValueError('Measurement metadata needs 16384 bytes')
    return limits


def page_evidence(page,sha,number,layout,components,*,options=None,cancelled=lambda:False):
    limits=_bounded(options)
    if (not re.fullmatch('[0-9a-f]{64}',str(sha)) or type(number) is not int or page.number+1!=number
            or layout.get('version')!=architectural_view_layout.VERSION
            or layout.get('document_sha256')!=sha or layout.get('page')!=number):
        raise ValueError('Same current original page and caption layout required')
    if components is not None and (components.get('version')!=planning_component_footprints.VERSION
            or components.get('document_sha256')!=sha or components.get('page')!=number):
        raise ValueError('Same current component source required')
    def check():
        if cancelled():raise CancelledError('Component measurement cancelled')
    check()
    result={'version':VERSION,'document_sha256':sha,'page':number,'limits':limits,
        'source_layout_sha256':digest(layout),'source_components_sha256':digest(components),
        'analysis_complete':True,'status':'nominal_source_measurement_evidence_only',
        'drawing_codes':[],'sheet_references':[],'size_notes':[],'paper_claims':[],
        'scale_contexts':[],'trials':[],
        'printed_component_label_count':0 if components is None else components['component_labels'],
        'printed_states':sorted({r['printed_claim']['printed_state'] for r in layout['view_captions']
            if r['glyph_screen']['status']=='raster_consistent_candidate'
            and r['printed_claim']['printed_state']!='unspecified'}),
        'physical_scale_verified':False,'component_identity_verified':False,
        'world_placement_eligible':False,'training_labels_generated':0,'world_geometry_additions':0,
        'height_m':None,'local_3d_preview_status':'withheld_source_height_and_cross_view_scope_unresolved'}
    def finish(reason=None):
        if reason:result.update(status='component_measurements_withheld',analysis_complete=False,reason=reason,trials=[])
        if len(json.dumps(result,allow_nan=False).encode())+80>limits['max_output_bytes']:
            for key in ('drawing_codes','sheet_references','size_notes','paper_claims','scale_contexts','trials'):result[key]=[]
            result.update(status='component_measurements_withheld',analysis_complete=False,reason='measurement_output_budget_exceeded')
        check();result['id']=digest(result);return result
    raw=page.get_texttrace()
    if len(raw)>10000 or sum(len(r['chars']) for r in raw)>500000:return finish('measurement_text_budget_exceeded')
    inverse=native_inverse(page);evidence_count=0
    for run in ordinary_surfaces.label_runs(raw):
        check();text=''.join(chr(c[0]) for c in run['chars']).strip()
        code=CODE.fullmatch(text);note=printed_size(text)
        reference=bool(re.fullmatch(r'\d{4}',text))
        paper=re.fullmatch(r'(?:As indicated|1\s*:\s*\d{1,5})\s*@\s*(A[0-5])',text,re.I)
        if not (code or note or reference or paper):continue
        evidence_count+=1
        if evidence_count>limits['max_text_evidence']:return finish('measurement_evidence_budget_exceeded')
        rect=pymupdf.Rect(run['bbox']);geometry=Polygon([tuple(p*inverse) for p in (rect.tl,rect.tr,rect.br,rect.bl)])
        row={'text':text,'trace_indices':run['trace_indices'],'character_indices':run['character_indices'],
            'geometry_pdf_native':mapping(geometry),'glyph_screen':glyph_visibility.screen_architectural_span(
                page,run,zoom=24 if run['size']<4 else 6)}
        row['id']=digest([VERSION,sha,number,row])
        if code:result['drawing_codes'].append({**row,'series':code['series'],'sheet':code['sheet']})
        if note:result['size_notes'].append({**row,'claim':note})
        if reference:result['sheet_references'].append({**row,'sheet':text})
        if paper:result['paper_claims'].append({**row,'paper_size':paper[1].upper()})
    for caption in layout['view_captions']:
        check()
        if caption['printed_claim']['view_kind']!='plan' or caption['glyph_screen']['status']!='raster_consistent_candidate':continue
        inline=caption['printed_claim'].get('printed_scale_denominator');adjacent=caption.get('adjacent_scale_candidates',[])
        values=[inline] if inline is not None else [r['printed_denominator'] for r in adjacent]
        conflict=inline is not None and any(r['printed_denominator']!=inline for r in adjacent)
        if (len(values)!=1 or conflict or any(r['glyph_screen']['status']!='raster_consistent_candidate' for r in adjacent)):
            continue
        result['scale_contexts'].append({'caption_id':caption['id'],'caption_text':caption['text'],
            'caption_sha256':digest(caption),'printed_denominator':values[0],
            'scale_evidence':adjacent,'scale_assignment_verified':False,'view_scope_verified':False})
    if len(result['scale_contexts'])>limits['max_scale_claims']:return finish('measurement_scale_claim_budget_exceeded')
    denominators=sorted({r['printed_denominator'] for r in result['scale_contexts']})
    if any(type(v) is not int or not 1<=v<=10000 for v in denominators):raise ValueError('Bounded printed scale required')
    kind,value=page.parent.xref_get_key(page.xref,'UserUnit')
    try:unit=1. if kind=='null' else float(value)
    except (ValueError,TypeError):unit=None
    rotation=page.rotation
    try:
        page.set_rotation(0);dimensions=sorted([page.rect.width*25.4/72,page.rect.height*25.4/72])
    finally:page.set_rotation(rotation)
    papers={'A0':(841,1189),'A1':(594,841),'A2':(420,594),'A3':(297,420),'A4':(210,297),'A5':(148,210)}
    visible_papers={r['paper_size'] for r in result['paper_claims'] if r['glyph_screen']['status']=='raster_consistent_candidate'}
    paper_matches=[name for name,size in papers.items() if all(abs(a-b)<=1.5 for a,b in zip(dimensions,size))]
    result.update(pdf_user_unit=unit if unit is not None and math.isfinite(unit) else None,
        effective_page_dimensions_mm=dimensions,matching_paper_sizes=paper_matches,
        scale_claim_denominators=denominators)
    if unit!=1 or page.cropbox!=page.mediabox:return finish('unsupported_native_unit_or_cropped_page')
    if visible_papers and (len(visible_papers)!=1 or visible_papers!=set(paper_matches)):
        return finish('printed_paper_size_does_not_match_original_page')
    if components is None:return finish()
    if not components['analysis_complete']:return finish('complete_component_inventory_required')
    if len(components['candidates'])>limits['max_components']:return finish('measurement_component_budget_exceeded')
    points=0
    for component in components['candidates']:
        check();record=component['source_outline'];candidate=record['candidate']
        if (record['source_record_sha256']!=digest(candidate)
                or digest(candidate['geometry'])!=digest(component['geometry_pdf_native'])
                or component['id']!=digest([planning_component_footprints.VERSION,sha,number,record['candidate_id'],component['label']['id']])):
            raise ValueError('Exact source-bound component geometry required')
        geometry=shape(component['geometry_pdf_native'])
        if (geometry.geom_type!='Polygon' or geometry.is_empty or not geometry.is_valid
                or not all(math.isfinite(v) for v in geometry.bounds)):
            raise ValueError('Finite source component polygon required')
        points+=len(geometry.exterior.coords)+sum(len(r.coords) for r in geometry.interiors)
        if points*max(1,len(denominators))>limits['max_points']:return finish('measurement_point_budget_exceeded')
        for denominator in denominators:
            factor=denominator*.0254/72;x0,y0,_,_=geometry.bounds
            affine=[factor,0,0,factor,-x0*factor,-y0*factor];nominal=affine_transform(geometry,affine)
            corners=list(nominal.minimum_rotated_rectangle.exterior.coords)
            lengths=sorted(math.dist(a,b) for a,b in zip(corners,corners[1:]))
            result['trials'].append({'id':digest([VERSION,sha,number,component['id'],denominator]),
                'source_component_id':component['id'],'source_component_sha256':digest(component),
                'source_geometry_sha256':digest(component['geometry_pdf_native']),
                'status':'nominal_scale_trial_only','coordinate_frame':'nominal_component_xy_metres',
                'printed_scale_denominator':denominator,'metres_per_native_point':factor,
                'native_to_nominal_local_affine':affine,'local_origin_pdf_native':[x0,y0],
                'local_origin_is_physical_datum':False,'geometry_nominal_local':mapping(nominal),
                'nominal_oriented_span_pair_m':[lengths[0],lengths[-1]],'nominal_area_m2':nominal.area,
                'bounding_rectangle_is_source_geometry':False,'physical_scale_verified':False,
                'component_identity_verified':False,'height_m':None,'world_placement_eligible':False})
    return finish()


def review_pages(pages,*,tolerance_m=.25,max_pairs=4096,max_output_bytes=8000000,cancelled=lambda:False):
    if (type(tolerance_m) not in (int,float) or not math.isfinite(tolerance_m) or not 0<tolerance_m<=.25
            or type(max_pairs) is not int or not 1<=max_pairs<=4096
            or type(max_output_bytes) is not int or not 16384<=max_output_bytes<=8000000):
        raise ValueError('Lower-only bounded size diagnostic policy required')
    if not isinstance(pages,list) or len(pages)>512:raise ValueError('Bounded measurement pages required')
    result={'version':VERSION,'status':'nominal_size_diagnostics_only','analysis_complete':True,
        'tolerance_m':tolerance_m,'pairs_checked':0,'components':[],'source_pages':{},
        'physical_component_footprints_verified':0,'local_3d_components':0,
        'local_3d_preview_status':'withheld_source_height_and_cross_view_scope_unresolved',
        'physical_scale_verified':False,'world_placement_eligible':False,
        'training_labels_generated':0,'model_weights_updated':False,'world_geometry_additions':0,
        'geometric_accuracy':None}
    def finish(reason=None):
        if reason:result.update(status='component_size_diagnostics_withheld',analysis_complete=False,reason=reason,components=[])
        result['summary']={'components_with_nominal_scale_trials':len(result['components']),
            'size_consistent_component_hypotheses':sum(r['status']=='printed_size_pair_consistent_diagnostic' for r in result['components']),
            'size_mismatched_component_hypotheses':sum(r['status']=='printed_size_pair_mismatch' for r in result['components']),
            'unresolved_component_size_hypotheses':sum(r['status'] not in ('printed_size_pair_consistent_diagnostic','printed_size_pair_mismatch') for r in result['components'])}
        if len(json.dumps(result,allow_nan=False).encode())>max_output_bytes:
            result.update(status='component_size_diagnostics_withheld',analysis_complete=False,
                reason='size_review_output_budget_exceeded',components=[],source_pages={})
            result['summary']=dict.fromkeys(result['summary'],0)
        if cancelled():raise CancelledError('Component size review cancelled')
        return result
    unique={}
    for page in pages:
        if (page.get('version')!=VERSION or page.get('id')!=digest({k:v for k,v in page.items() if k!='id'})):
            raise ValueError('Exact current measurement page required')
        key=page['document_sha256']+':'+str(page['page'])
        if key in unique and unique[key]!=page:raise ValueError('Conflicting measurement page')
        unique[key]=page;result['source_pages'][key]=digest(page)
    frame_holds={'unsupported_native_unit_or_cropped_page','printed_paper_size_does_not_match_original_page'}
    if any(not p['analysis_complete'] and (p.get('reason') not in frame_holds
           or p['printed_component_label_count'] or p['size_notes']) for p in unique.values()):
        return finish('complete_measurement_page_evidence_required')
    def visible(rows):return [r for r in rows if r['glyph_screen']['status']=='raster_consistent_candidate']
    record_bytes=0
    for page in unique.values():
        codes=visible(page['drawing_codes']);refs=visible(page['sheet_references'])
        groups={}
        for trial in page['trials']:groups.setdefault(trial['source_component_id'],[]).append(trial)
        for identifier,trials in sorted(groups.items()):
            if cancelled():raise CancelledError('Component size review cancelled')
            row={'source_component_id':identifier,'document_sha256':page['document_sha256'],'page':page['page'],
                'trials':trials,'note_evidence':[],'status':'printed_size_note_context_unresolved',
                'link_basis':'shared_printed_drawing_series_and_literal_sheet_reference_only',
                'component_correspondence_verified':False,'dimension_axes_verified':False,
                'physical_exterior_boundary_verified':False,'physical_scale_verified':False,'world_placement_eligible':False}
            result['components'].append(row)
            record_bytes+=len(json.dumps(row,allow_nan=False).encode())
            if record_bytes>max_output_bytes-2048:return finish('size_review_output_budget_exceeded')
            if len(codes)!=1 or len(page['printed_states'])!=1:continue
            for other in unique.values():
                if cancelled():raise CancelledError('Component size review cancelled')
                result['pairs_checked']+=1
                if result['pairs_checked']>max_pairs:return finish('size_note_pair_budget_exceeded')
                if (other['document_sha256'],other['page'])==(page['document_sha256'],page['page']):continue
                other_codes=visible(other['drawing_codes'])
                if (len(other_codes)!=1 or other_codes[0]['series']!=codes[0]['series']
                        or other_codes[0]['sheet'] not in {r['sheet'] for r in refs}
                        or other['printed_states']!=page['printed_states']):continue
                for note in visible(other['size_notes']):
                    result['pairs_checked']+=1
                    if result['pairs_checked']>max_pairs:return finish('size_note_pair_budget_exceeded')
                    witness={'document_sha256':other['document_sha256'],'page':other['page'],
                        'drawing_code':other_codes[0],'literal_references':[r for r in refs if r['sheet']==other_codes[0]['sheet']],
                        'note':note,'count_agrees_with_printed_labels':note['claim']['printed_count'] in (None,page['printed_component_label_count'])}
                    record_bytes+=len(json.dumps(witness,allow_nan=False).encode())
                    if record_bytes>max_output_bytes-2048:return finish('size_review_output_budget_exceeded')
                    row['note_evidence'].append(witness)
            if len({t['printed_scale_denominator'] for t in trials})!=1:
                row['status']='multiple_nominal_scales_withheld';continue
            if not row['note_evidence']:continue
            if not all(r['count_agrees_with_printed_labels'] for r in row['note_evidence']):
                row['status']='printed_component_count_disagreement';continue
            lengths={tuple(r['note']['claim']['length_pair_m']) for r in row['note_evidence']}
            if len(lengths)!=1:row['status']='conflicting_printed_size_notes';continue
            expected=list(next(iter(lengths)));measured=trials[0]['nominal_oriented_span_pair_m']
            errors=[abs(a-b) for a,b in zip(expected,measured)]
            row.update(printed_length_pair_m=expected,nominal_length_pair_m=measured,
                absolute_span_errors_m=errors,maximum_span_error_m=max(errors),
                status='printed_size_pair_consistent_diagnostic' if max(errors)<=tolerance_m+1e-9 else 'printed_size_pair_mismatch')
    return finish()


def write_review(root,review,*,max_preview_points=200000,max_preview_bytes=8000000):
    if (type(max_preview_points) is not int or not 1<=max_preview_points<=200000
            or type(max_preview_bytes) is not int or not 1024<=max_preview_bytes<=8000000):
        raise ValueError('Lower-only plan preview limits required')
    root=Path(root)
    (root/'component-measurements.json').write_text(json.dumps(review,indent=2,sort_keys=True,allow_nan=False)+'\n',encoding='utf-8')
    total_points=sum(len(ring) for row in review['components'] for trial in row['trials']
        for ring in trial['geometry_nominal_local']['coordinates'])
    fallback='<html lang="en"><meta charset="utf-8"><p>Component plan preview withheld: point or byte budget exceeded. No 3D building is generated.</p><a href="component-measurements.json">Complete diagnostic evidence</a></html>'
    if total_points>max_preview_points:
        (root/'component-measurements.html').write_text(fallback,encoding='utf-8');return
    body=['<!doctype html><html lang="en"><meta charset="utf-8"><title>Component size diagnostics</title>',
        '<h1>Component size diagnostics</h1><p>Nominal printed-scale trials only. Exterior walls, scale application, '
        'component correspondence, height and park placement remain unverified. 3D generation is withheld.</p>']
    body.append('<p>Span comparison tolerance: '+str(review['tolerance_m'])+' m. This is a diagnostic threshold, not physical accuracy.</p>')
    points=0
    for row in review['components']:
        body.append('<h2>'+escape(row['source_component_id'][:16])+'</h2><p>'+escape(row['status'].replace('_',' '))+'</p>')
        for trial in row['trials']:
            polygon=shape(trial['geometry_nominal_local']);x0,y0,x1,y1=polygon.bounds
            scale=min(400/max(x1-x0,1e-9),300/max(y1-y0,1e-9));commands=[]
            for ring in (polygon.exterior,*polygon.interiors):
                coords=list(ring.coords);points+=len(coords)
                commands.append('M'+' L'.join(f'{20+(x-x0)*scale:.3f},{320-(y-y0)*scale:.3f}' for x,y in coords)+' Z')
            body.append('<p>Printed scale 1:'+str(trial['printed_scale_denominator'])+'; nominal spans '+
                ' × '.join(f'{v:.3f}' for v in trial['nominal_oriented_span_pair_m'])+' m; height unresolved.</p>')
            body.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 440 340" width="440" role="img" aria-label="Unchanged source polygon under a nominal scale trial"><path fill="#e9d9ee" fill-rule="evenodd" stroke="#8d258f" d="'+''.join(commands)+'"/></svg>')
        if row.get('printed_length_pair_m'):
            body.append('<p>Printed size pair: '+' × '.join(f'{v:.4f}' for v in row['printed_length_pair_m'])+
                ' m; span differences: '+', '.join(f'{v:.3f}' for v in row['absolute_span_errors_m'])+' m.</p>')
        for witness in row['note_evidence']:
            body.append('<p>Source note: '+escape(witness['note']['text'])+'; document '+escape(witness['document_sha256'])+
                ', page '+str(witness['page'])+'.</p>')
    if not review['components']:body.append('<p>No complete component size diagnostics available.</p>')
    body.append('<p><a href="component-measurements.json">Exact source evidence and diagnostic coordinates</a></p></html>')
    encoded=''.join(body).encode()
    if len(encoded)>max_preview_bytes:encoded=fallback.encode()
    (root/'component-measurements.html').write_bytes(encoded)
