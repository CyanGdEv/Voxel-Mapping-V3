"""Repeatable original-drawing pilots with explicit reconstruction coverage gaps.

Discovery runs without per-view recipes. Candidates remain source evidence;
this command neither supplies reference truth nor accepts park geometry.
"""
import argparse
import base64
from collections import Counter
from concurrent.futures import CancelledError
import hashlib
from html import escape
import json
import math
import marshal
from pathlib import Path
import re
import sys

import pymupdf

from . import architectural_view_layout, building_pdf_discovery, drawing_view_candidates
from . import ordinary_surfaces, planning_view_geometry, drawing_geometry, linework_boundaries, drawing_page_tools, building_raster_views
from . import planning_outline_semantics, glyph_visibility
from .building_spec import digest
from .generation_cycles import atomic_json, file_hash
from .drawing_page_tools import native_inverse

VERSION = 'planning-area-pilot-v1'
LIMITS = {'max_documents': 16, 'max_pages': 32, 'max_document_pages': 8,
          'max_document_bytes': 24000000, 'max_output_bytes': 128000000,
          'render_edge_pixels': 1200}
ROLES = {'site-plan', 'floor-plan', 'block-plan', 'landscape-plan',
         'elevation', 'section', 'detail', 'location-plan', 'roof-plan', 'unclassified'}
SURFACE_ROLES = {'site-plan', 'block-plan', 'floor-plan', 'landscape-plan'}


class PilotBudgetExceeded(ValueError):
    """Stop output growth immediately, without a completion receipt."""


def _implementation(module):
    """Pin source bytes or the loader's actual code in a frozen distribution."""
    path=Path(module.__file__)
    if path.is_file(): return {'basis':'module_file_bytes','sha256':file_hash(path)}
    loader=module.__spec__.loader
    code=loader.get_code(module.__name__)
    if code is None: raise ValueError('Runtime implementation code is unavailable')
    return {'basis':'runtime_module_code_object','sha256':hashlib.sha256(marshal.dumps(code)).hexdigest()}


def _text(value, name, maximum=512):
    if not isinstance(value, str) or not value.strip() or len(value)>maximum:
        raise ValueError('Bounded nonempty '+name+' required')
    return value


def validate(config):
    if not isinstance(config, dict) or config.get('version') != VERSION:
        raise ValueError('Versioned planning area pilot required')
    if set(config)-{'version', 'area_id', 'application_references', 'documents',
                    'development_exposure', 'options', 'source_directory', 'download_missing'}:
        raise ValueError('Unknown planning pilot setting')
    _text(config.get('area_id'), 'area identity', 128)
    if 'source_directory' in config: _text(config['source_directory'],'original PDF directory',2048)
    if type(config.get('download_missing',False)) is not bool:
        raise ValueError('Explicit boolean source download setting required')
    refs = config.get('application_references')
    if (not isinstance(refs, list) or not 1<=len(refs)<=16 or
            any(not isinstance(r, str) or not r.strip() or len(r)>128 for r in refs) or
            len(set(refs))!=len(refs)):
        raise ValueError('Distinct bounded application references required')
    exposure = config.get('development_exposure', 'unassessed')
    if exposure not in ('previously_inspected', 'unassessed'):
        raise ValueError('Development exposure must not assert unseen-source independence')
    overrides = config.get('options', {})
    if not isinstance(overrides, dict) or set(overrides)-set(LIMITS):
        raise ValueError('Known pilot limits required')
    limits = {**LIMITS, **overrides}
    if any(type(v) is not int or not 1<=v<=LIMITS[k] for k,v in limits.items()):
        raise ValueError('Bounded pilot limits required')
    if limits['render_edge_pixels']<200:
        raise ValueError('Pilot render edge must be at least 200 pixels')
    documents = config.get('documents')
    if not isinstance(documents, list) or not 1<=len(documents)<=limits['max_documents']:
        raise ValueError('Bounded original drawing manifest required')
    seen = set()
    for item in documents:
        if not isinstance(item, dict) or set(item)-{
                'file', 'sha256', 'title', 'role', 'drawing_state',
                'application_reference', 'url', 'transport_url', 'pages', 'page_roles'}:
            raise ValueError('Known original drawing fields required')
        sha = item.get('sha256')
        if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha) or sha in seen:
            raise ValueError('Distinct pinned original drawings required')
        seen.add(sha)
        for key in ('file', 'title', 'application_reference'):
            _text(item.get(key), key)
        if item['application_reference'] not in refs or item.get('role') not in ROLES:
            raise ValueError('Drawing must belong to a selected application and supported role')
        if item.get('drawing_state') not in ('existing', 'proposed', 'unknown'):
            raise ValueError('Explicit catalogue drawing state required')
        if 'url' in item: _text(item['url'], 'source URL', 2048)
        if 'transport_url' in item:
            if not item.get('url') or item['transport_url']!=item['url'].replace('https://','http://',1):
                raise ValueError('Recorded fallback must name the same original attachment')
        pages = item.get('pages')
        if pages is not None and (not isinstance(pages, list) or not pages or
                len(pages)>limits['max_document_pages'] or
                any(type(p) is not int or not 1<=p<=10000 for p in pages) or
                len(set(pages))!=len(pages)):
            raise ValueError('Distinct bounded source pages required')
        page_roles=item.get('page_roles',{})
        if (not isinstance(page_roles,dict) or len(page_roles)>limits['max_document_pages'] or
                any(not isinstance(k,str) or not re.fullmatch(r'[1-9][0-9]{0,4}',k) or
                    int(k)>10000 or not isinstance(v,str) or v not in ROLES for k,v in page_roles.items()) or
                (pages is not None and not set(page_roles)<=set(map(str,pages)))):
            raise ValueError('Bounded roles for selected original pages required')
    return limits


def _preview(page, path, edge):
    # Check the allocation bound before rendering, including rounding margins.
    width, height = page.rect.width, page.rect.height
    if not all(math.isfinite(v) and v>0 for v in (width,height)):
        raise ValueError('Finite original page dimensions required')
    scale = edge/max(width,height)
    if (math.ceil(width*scale)+2)*(math.ceil(height*scale)+2)>(edge+2)**2:
        raise ValueError('Pilot preview pixel budget exceeded')
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),
                          colorspace=pymupdf.csRGB, alpha=False)
    if max(pix.width,pix.height)>edge+2:
        raise ValueError('Pilot preview edge budget exceeded')
    pix.save(path)
    return {'file':path.name, 'sha256':file_hash(path),
            'size_pixels':[pix.width,pix.height],
            'pdf_native_to_pixels':list((~native_inverse(page))*page.rotation_matrix*
                pymupdf.Matrix(scale,scale)*pymupdf.Matrix(1,0,0,1,-pix.x,-pix.y))}


def _outline_overlay(result, preview, path):
    """Draw the retained source outlines over their original-page preview."""
    inventory=(result.get('surface_report') or {}).get('source_outline_inventory') or {}
    hints={r['candidate_id']:r for r in (result.get('outline_semantics') or {}).get('outlines',[])
           if r['status'] in ('visible_label_enclosure_hint','shared_component_label_enclosure_hint')}
    records=[('label_hint' if r['candidate_id'] in hints else 'source',r['candidate']['geometry'],
              r['candidate_id'],{**r['native_metrics'],**({'source_label_hint':hints[r['candidate_id']]} if r['candidate_id'] in hints else {})})
             for r in inventory.get('records',[])]
    scoped=result.get('view_geometry') or {}
    records += [('view',r['geometry_pdf_native'],r['id'],r.get('measurements_nominal_metres') or {})
                for r in scoped.get('outlines',[])]
    if not records:return None
    if len(records)>1000:raise PilotBudgetExceeded('Outline overlay record budget exceeded')
    width,height=preview['size_pixels'];matrix=pymupdf.Matrix(preview['pdf_native_to_pixels'])
    background=base64.b64encode((path.parent/preview['file']).read_bytes()).decode('ascii')
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="Unclassified source outlines over the original drawing">',
        f'<image href="data:image/png;base64,{background}" width="{width}" height="{height}"/>']
    points=0
    for kind,geometry,identifier,metrics in records:
        polygons=[geometry['coordinates']] if geometry['type']=='Polygon' else geometry['coordinates']
        commands=[]
        for polygon in polygons:
            for ring in polygon:
                points+=len(ring)
                if points>250000:raise PilotBudgetExceeded('Outline overlay point budget exceeded')
                projected=[pymupdf.Point(*p)*matrix for p in ring]
                commands.append('M'+' L'.join(f'{p.x:.3f},{p.y:.3f}' for p in projected)+' Z')
        title=escape(kind+' outline '+identifier+'; '+json.dumps(metrics,sort_keys=True))
        color={'source':'#007985','view':'#c94b00','label_hint':'#087b36'}[kind]
        parts.append(f'<path class="{kind}" data-source-candidate-id="{escape(identifier,quote=True)}" fill="none" stroke="{color}" stroke-width="1.5" vector-effect="non-scaling-stroke" d="{" ".join(commands)}"><title>{title}</title></path>')
    parts.append('</svg>');data=''.join(parts).encode('utf-8')
    if len(data)>16000000:raise PilotBudgetExceeded('Outline overlay byte budget exceeded')
    path.write_bytes(data)
    return {'file':path.name,'sha256':file_hash(path),'outlines':len(records),
            'pdf_native_to_pixels':preview['pdf_native_to_pixels'],
            'legend':{'cyan':'unclassified closed source outlines','orange':'view-region source outlines',
                      'green':'visible source-label enclosure hints; physical identity unverified'},
            'physical_geometry_verified':False}


def _page(page, sha, number, role, *, cancelled=lambda:False):
    discovery = building_pdf_discovery.discover_page(page,sha,number)
    layout = discovery.get('caption_layout')
    view_pack = None
    if layout is not None:
        # Incomplete geometry can still supply caption-only crop hints. Never
        # pass its partial linework to view membership or scale application.
        sources = [{**r,'kind':'native_vector'} for r in discovery['source_geometry']]
        view_pack = drawing_view_candidates.candidates(page,sha,number,layout,sources)
    surfaces, labels, surface_report = [], [], None
    if role in SURFACE_ROLES:
        surfaces, labels, surface_report = ordinary_surfaces.page_candidates(page,sha,number)
    outlines = None if surface_report is None else surface_report.get('source_outline_inventory')
    semantics = None if outlines is None or not outlines.get('inventory_complete') else planning_outline_semantics.page_candidates(
        page,sha,number,outlines,cancelled=cancelled)
    semantic_summary={} if semantics is None else semantics['summary']
    scoped = None if view_pack is None or not view_pack['views'] else planning_view_geometry.page_candidates(
        page,sha,number,view_pack,cancelled=cancelled)
    visible = [] if layout is None else [r for r in layout['view_captions']
        if r['glyph_screen']['status']=='raster_consistent_candidate']
    # Catalogue state is never a substitute for the visible native claims.
    states = sorted({r['printed_claim']['printed_state'] for r in visible
                     if r['printed_claim']['printed_state'] in ('existing','proposed')})
    titles = [] if layout is None else layout['sheet_titles']
    blockers = ['geographic_registration_unresolved', 'finished_levels_unresolved',
                'current_as_built_state_unverified', 'independent_reference_inventory_missing']
    if role=='unclassified': blockers.append('page_drawing_role_unresolved')
    if discovery['status']!='native_drawing_candidates_discovered':
        blockers.append(discovery['status'])
    if visible: blockers += ['physical_view_scope_unverified', 'cross_view_component_correspondence_unresolved']
    if labels:
        blockers.append('surface_boundary_role_and_scope_unverified')
        if not surfaces: blockers.append('no_supported_contained_surface_boundaries')
    if outlines and outlines['status']!='complete_source_outline_inventory':
        blockers.append('closed_source_outline_inventory_incomplete')
    if scoped and scoped['status']!='scoped_source_geometry_candidates':
        blockers.append('view_region_geometry_incomplete')
    outline_count=0 if outlines is None else len(outlines['records'])
    view_outlines=[] if scoped is None else scoped['outlines']
    if outline_count or view_outlines:
        blockers.append('source_outlines_require_physical_interpretation')
    if semantics and not semantics['inventory_complete']:
        blockers.append('source_label_association_incomplete')
    return {'document_sha256':sha, 'page':number,
        'coordinate_frame':'pdf_native_points_y_up',
        'discovery':discovery, 'view_candidates':view_pack,
        'surface_candidates':surfaces, 'surface_labels':labels, 'surface_report':surface_report,
        'view_geometry':scoped,
        'outline_semantics':semantics,
        'summary':{'geometry_status':discovery['status'],'analysis_role':role,
            'visible_view_captions':len(visible),
            'visible_view_kinds':dict(Counter(r['printed_claim']['view_kind'] for r in visible)),
            'printed_view_states':states,
            'sheet_title_claims':len(titles),
            'view_candidates':0 if view_pack is None else len(view_pack['views']),
            'surface_labels':len(labels), 'surface_candidates':len(surfaces),
            'closed_source_outlines':outline_count,
            'view_source_outlines':len(view_outlines),
            'nominal_view_outlines':sum(r.get('geometry_nominal_local') is not None for r in view_outlines),
            'source_outline_role_hints':semantic_summary.get('associated_outline_hints',0),
            'building_outline_hints':semantic_summary.get('outline_role_hints',{}).get('building',0),
            'path_plaza_outline_hints':sum(semantic_summary.get('outline_role_hints',{}).get(k,0) for k in ('path','plaza')),
            'surface_label_statuses':dict(Counter(r['status'] for r in labels)),
            'surface_connectivity_status':'not_assessed_unverified_surface_geometry',
            'blockers':blockers},
        'physical_identity_verified':False, 'world_placement_eligible':False}


def _html(config, documents, pages):
    sections=[]
    for document in documents:
        title=escape(document['title']); status=escape(document['status'])
        sections.append(f'<h2>{title}</h2><p>{status}</p>')
        for page in (p for p in pages if p['document_sha256']==document['sha256']):
            summary=page['summary']
            sections.append(f'<h3>Page {page["page"]}</h3><p>'
                f'{summary["visible_view_captions"]} visible view captions; '
                f'{summary["view_candidates"]} candidate view regions; '
                f'{summary["surface_labels"]} surface labels; '
                f'{summary["surface_candidates"]} enclosed surface candidates; '
                f'{summary.get("closed_source_outlines",0)} unclassified closed source outlines; '
                f'{summary.get("nominal_view_outlines",0)} outlines with nominal view measurements.</p>')
            sections.append(f'<p>{summary.get("source_outline_role_hints",0)} source-label enclosure hints '
                f'({summary.get("building_outline_hints",0)} building-related; '
                f'{summary.get("path_plaza_outline_hints",0)} path/plaza-related). These are source associations, not accepted physical features.</p>')
            evidence=escape(page['evidence_file'],quote=True)
            sections.append(f'<p><a href="{evidence}">Source-bound extraction evidence</a></p>')
            captions=page.get('captions',[])
            if captions: sections.append('<ul>'+''.join('<li>'+escape(c)+'</li>' for c in captions)+'</ul>')
            if 'preview_file' in page:
                image=escape(page['preview_file'],quote=True)
                sections.append(f'<a href="{image}"><img src="{image}" alt="{title}, original drawing page"></a>')
            if page.get('outline_overlay'):
                overlay=escape(page['outline_overlay']['file'],quote=True)
                sections.append('<details><summary>Inspect extracted source outlines</summary>'
                    '<p>Cyan: unclassified closed outlines. Orange: view-region outlines. Green: visible source-label enclosure hints. Inventories may overlap. '
                    'Symbols, annotations and context can be included. Nominal metres use printed view scale claims; '
                    'physical identity, scale application and geographic placement remain unverified.</p>'
                    f'<a href="{overlay}"><img src="{overlay}" alt="Extracted source outlines over original drawing"></a></details>')
            hints=page.get('source_label_hints',[])
            if hints:
                sections.append('<h4>Visible source-label associations</h4><p>Printed words identify source enclosure hints. '
                    'Multiple component labels in one enclosure do not identify separate component footprints.</p><ul>')
                for hint in hints:
                    sections.append('<li>'+escape(str(hint['source_role_hint']))+': '+escape(', '.join(hint['label_texts']))+
                        ' — '+escape(hint['status'].replace('_',' '))+'; source outline '+escape(hint['candidate_id'])+'.</li>')
                sections.append('</ul>')
                if page.get('source_label_hint_count',0)>len(hints):
                    sections.append('<p>Showing the first 50 associations. The linked extraction evidence retains all bounded records.</p>')
            sections.append('<p>Remaining: '+escape(', '.join(summary['blockers']).replace('_',' '))+'.</p>')
    return ('<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Planning reconstruction pilot</title><style>'
        'body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:0 20px;line-height:1.5}'
        'img{max-width:100%;border:1px solid #aaa}h2{margin-top:3em}</style>'
        '<h1>'+escape(config['area_id'])+' — planning reconstruction pilot</h1>'
        '<p>Original drawings and automatically discovered candidates. View regions are crop hints; '
        'surface enclosures still require physical interpretation. No completed building, registered '
        'path network or verified park reconstruction is supplied.</p>'
        '<p>Accuracy remains unassessed until a separate checked reference inventory is available. '
        'Proposed work is kept separate from existing drawing claims.</p>'+''.join(sections)+'</html>')


def run(config, resolve, output, *, cancelled=lambda:False, progress=lambda message:None):
    limits=validate(config)
    config=json.loads(json.dumps(config,allow_nan=False))
    root=Path(output)
    if root.exists(): raise ValueError('Fresh planning pilot directory required')
    def check():
        if cancelled(): raise CancelledError('Planning pilot cancelled')
    check();root.mkdir(parents=True)
    contract={'version':VERSION,'config_sha256':digest(config),'limits':limits,
        'implementations':{m.__name__:_implementation(m) for m in (
            sys.modules[__name__],building_pdf_discovery,architectural_view_layout,
            ordinary_surfaces,drawing_view_candidates,planning_view_geometry,
            drawing_geometry,linework_boundaries,drawing_page_tools,building_raster_views,
            planning_outline_semantics,glyph_visibility)},
        'semantic_backends':planning_outline_semantics.BACKENDS,
        'caption_version':architectural_view_layout.VERSION,
        'pymupdf_version':pymupdf.VersionBind}
    atomic_json(root/'config.json',config);atomic_json(root/'contract.json',contract)
    documents=[];pages=[];verified=[];used=0;written=0
    for item in config['documents']:
        check();progress('Inspecting '+item['title'])
        row={k:v for k,v in item.items() if k!='file'}
        row.update(status='source_unavailable',selected_pages=[],completed_pages=0)
        documents.append(row)
        path=Path(resolve(item['file']))
        if not path.exists() and config.get('download_missing',False):
            from .desktop_area import _download
            try:
                path.parent.mkdir(parents=True,exist_ok=True)
                progress('Gathering pinned original: '+item['title'])
                row['acquisition_attempts']=_download(item,path,cancelled)
            except CancelledError:
                raise
            except Exception as error:
                row.update(reason=str(error),acquisition_attempts=getattr(error,'attempts',[]))
        if not path.is_file(): row.setdefault('reason','Pinned original PDF is unavailable');continue
        try:
            if path.stat().st_size>limits['max_document_bytes']:
                raise ValueError('Original PDF byte budget exceeded')
            data=path.read_bytes()
            if len(data)>limits['max_document_bytes'] or hashlib.sha256(data).hexdigest()!=item['sha256']:
                raise ValueError('Original PDF checksum mismatch or byte budget exceeded')
            verified.append((path,item['sha256']))
            with pymupdf.open(stream=data,filetype='pdf') as document:
                count=len(document)
                if count>10000 or ('pages' not in item and count>limits['max_document_pages']):
                    raise ValueError('Pilot page budget exceeded; select bounded pages')
                selected=sorted(item.get('pages',range(1,count+1)))
                if not selected or selected[-1]>count:
                    raise ValueError('Requested original page is absent')
                if len(selected)>limits['max_document_pages'] or used+len(selected)>limits['max_pages']:
                    raise ValueError('Pilot page budget exceeded; select bounded pages')
                row.update(status='original_pdf_inspected',selected_pages=selected)
                for number in selected:
                    check();used+=1
                    name=item['sha256']+'-page-'+str(number)
                    record={'document_sha256':item['sha256'],'page':number}
                    try:
                        role=item.get('page_roles',{}).get(str(number),item['role'])
                        result=_page(document[number-1],item['sha256'],number,role,cancelled=cancelled)
                        check()
                        raw=(json.dumps(result,sort_keys=True,allow_nan=False)+'\n').encode()
                        if len(raw)>32000000 or written+len(raw)>limits['max_output_bytes']:
                            raise PilotBudgetExceeded('Pilot output byte budget exceeded')
                        (root/(name+'.json')).write_bytes(raw);written+=len(raw)
                        preview=_preview(document[number-1],root/(name+'.png'),limits['render_edge_pixels'])
                        written+=(root/preview['file']).stat().st_size
                        overlay=_outline_overlay(result,preview,root/(name+'-outlines.svg'))
                        if overlay:written+=(root/overlay['file']).stat().st_size
                        if written>limits['max_output_bytes']: raise PilotBudgetExceeded('Pilot output byte budget exceeded')
                        layout=result['discovery'].get('caption_layout',{})
                        record.update(summary=result['summary'],evidence_file=name+'.json',
                            preview_file=preview['file'],preview=preview,
                            outline_overlay=overlay,
                            captions=[r['text'] for r in layout.get('view_captions',[])])
                        hints=[r for r in (result.get('outline_semantics') or {}).get('outlines',[])
                               if r['status'] in ('visible_label_enclosure_hint','shared_component_label_enclosure_hint')]
                        record.update(source_label_hints=hints[:50],source_label_hint_count=len(hints))
                        row['completed_pages']+=1
                    except PilotBudgetExceeded:
                        raise
                    except (ValueError,RuntimeError) as error:
                        record.update(evidence_file=name+'-failure.json',captions=[],
                            summary={'geometry_status':'page_failed','visible_view_captions':0,
                                'visible_view_kinds':{},'printed_view_states':[], 'view_candidates':0,
                                'surface_labels':0,'surface_candidates':0,'surface_label_statuses':{},
                                'closed_source_outlines':0,'view_source_outlines':0,'nominal_view_outlines':0,
                                'source_outline_role_hints':0,'building_outline_hints':0,'path_plaza_outline_hints':0,
                                'blockers':['page_extraction_failed'],'reason':str(error)})
                        atomic_json(root/record['evidence_file'],record)
                    pages.append(record)
                if row['completed_pages']!=len(selected): row['status']='partial_original_pdf_inspection'
        except PilotBudgetExceeded:
            raise
        except (ValueError,RuntimeError,OSError) as error:
            row.update(status='source_withheld',reason=str(error))
    check()
    # Recheck every source used, including a document with failed extraction.
    for path,sha in verified:
        if file_hash(path)!=sha: raise ValueError('Original PDF changed during planning pilot')
    page_blockers=Counter(b for p in pages for b in p['summary']['blockers'])
    source_blockers=[{'sha256':r['sha256'],'title':r['title'],'status':r['status'],
                     'reason':r.get('reason')} for r in documents if r['status']!='original_pdf_inspected']
    summary={'requested_documents':len(documents),'inspected_documents':sum(
        r['status']=='original_pdf_inspected' for r in documents),'attempted_pages':len(pages),
        'completed_pages':sum(r['completed_pages'] for r in documents),
        'visible_view_captions':sum(p['summary']['visible_view_captions'] for p in pages),
        'view_candidates':sum(p['summary']['view_candidates'] for p in pages),
        'surface_labels':sum(p['summary']['surface_labels'] for p in pages),
        'surface_candidates':sum(p['summary']['surface_candidates'] for p in pages),
        **{k:sum(p['summary'].get(k,0) for p in pages) for k in
           ('closed_source_outlines','view_source_outlines','nominal_view_outlines',
            'source_outline_role_hints','building_outline_hints','path_plaza_outline_hints')},
        'reconstructed_buildings':0,'registered_path_networks':0,
        'physical_component_coverage':None,'geometric_accuracy':None,
        'reconstruction_completed':False}
    reference={'status':'awaiting_separate_checked_reference_inventory',
        'required_families':['buildings','paths_and_plazas'],
        'requirements':['source_bound_component_identities','drawing_state_and_current_state',
            'footprints_heights_and_openings','surveyed_positions_and_finished_levels',
            'surface_boundaries_entrances_and_expected_connections'],
        'reference_geometry_generated_from_predictions':False,
        'development_exposure':config.get('development_exposure','unassessed'),
        'unseen_source_generalisation':'not_assessed'}
    atomic_json(root/'reference-requirements.json',reference)
    (root/'review.html').write_text(_html(config,documents,pages),encoding='utf-8')
    total=sum(p.stat().st_size for p in root.iterdir() if p.is_file())
    if total>limits['max_output_bytes']: raise PilotBudgetExceeded('Pilot output byte budget exceeded')
    report={'version':VERSION,'status':'source_review_pack_generated_with_reconstruction_blockers',
        'contract':contract,'area_id':config['area_id'],'documents':documents,'pages':pages,
        'summary':summary,'source_blockers':source_blockers,'page_blocker_counts':dict(page_blockers),
        'benchmark':reference,'training_labels_generated':0,'model_promoted':False,
        'world_placement_eligible':False,'park_world_blocks_added':0,
        'output_sha256':{p.name:file_hash(p) for p in sorted(root.iterdir()) if p.is_file()}}
    if total+len(json.dumps(report,indent=2,sort_keys=True,allow_nan=False).encode())+1>limits['max_output_bytes']:
        raise PilotBudgetExceeded('Pilot report byte budget exceeded')
    check();atomic_json(root/'report.json',report)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--source-directory')
    parser.add_argument('--download-missing',action='store_true',help='Recover pinned originals from their recorded council attachments.')
    args=parser.parse_args(argv);path=Path(args.config).resolve()
    if path.stat().st_size>16000000: raise ValueError('Pilot configuration byte budget exceeded')
    config=json.loads(path.read_text(encoding='utf-8'))
    if args.download_missing: config['download_missing']=True
    base=Path(args.source_directory).resolve() if args.source_directory else (path.parent/config.get('source_directory','.')).resolve()
    report=run(config,lambda name:base/name,args.output)
    print(json.dumps({'status':report['status'],**report['summary']},sort_keys=True))


if __name__=='__main__': main()
