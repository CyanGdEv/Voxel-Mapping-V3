"""Verified public-web PDF handoff into bounded original-drawing analysis."""
import argparse
from concurrent.futures import CancelledError
import hashlib
from html import escape
import json
from pathlib import Path
import re
import sys

import pymupdf

from . import architectural_view_layout as captions
from . import planning_area_pilot as planning
from . import web_evidence as web
from . import web_research
from .desktop_memory import digest
from .generation_cycles import atomic_json, file_hash

VERSION='web-planning-pilot-v1'


def validate(config):
    if not isinstance(config,dict) or config.get('version')!=VERSION:
        raise ValueError('Versioned web-to-planning request required')
    if set(config)-{'version','area_id','application_reference','research','analysis_options','development_exposure'}:
        raise ValueError('Unknown web-to-planning setting')
    for key,maximum in (('area_id',128),('application_reference',128)):
        value=config.get(key)
        if not isinstance(value,str) or not 1<=len(value.strip())<=maximum or any(ord(c)<32 for c in value):
            raise ValueError('Bounded area identity and application reference required')
    approved,*_=web_research.validate(config.get('research'))
    # Reuse the drawing pipeline's validation and limits, including lower-only
    # overrides. This dummy is validation data, never a discovered source.
    manifest={'version':planning.VERSION,'area_id':config['area_id'],
        'application_references':[config['application_reference']],
        'development_exposure':config.get('development_exposure','unassessed'),
        'options':config.get('analysis_options',{}),'documents':[{'file':'validation.pdf',
            'sha256':'0'*64,'title':'Validation only','role':'unclassified',
            'drawing_state':'unknown','application_reference':config['application_reference']}]}
    return approved,planning.validate(manifest)


def classify(page):
    """Literal native caption hints only; no current-state or scale acceptance."""
    text=page.get_text()
    if len(text)>500000: raise ValueError('Page classification text budget exceeded')
    claims=[];roles=set();states=set()
    for number,line in enumerate(text.splitlines(),1):
        line=line.strip()
        if not line or len(line)>180: continue
        claim=captions.view_claim(line)
        role=None
        if claim:
            kind=claim['view_kind'];form=claim.get('plan_level_or_form','') or ''
            if kind=='elevation': role='elevation'
            elif kind=='section': role='section'
            elif form in ('site','block','location'): role=form+'-plan'
            elif form.startswith('roof'): role='roof-plan'
            elif kind=='plan' and 'floor' in form: role='floor-plan'
        else:
            detail=re.fullmatch(r'(?:(existing|proposed|new)\s+)?(?:no[- ]dig\s+)?(?:surfacing|paving|construction)\s+detail',line,re.I)
            if detail:
                role='detail';claim={'printed_state':(detail[1] or 'unspecified').lower()}
        if role:
            roles.add(role)
            state=claim.get('printed_state','unspecified')
            if state in ('existing','proposed'): states.add(state)
            claims.append({'line':number,'text':line,'role':role,'printed_state':state})
            if len(claims)>128: raise ValueError('Page classification caption budget exceeded')
    role=next(iter(roles)) if len(roles)==1 else 'unclassified'
    state=next(iter(states)) if len(states)==1 else 'unknown'
    return {'role':role,'drawing_state':state,'observed_roles':sorted(roles),
        'observed_states':sorted(states),'claims':claims,
        'basis':'literal_native_caption_text_unverified',
        'status':'single_role_caption_hint' if len(roles)==1 else 'mixed_roles_withheld' if roles else 'no_supported_role_caption',
        'physical_scope_verified':False,'current_as_built_state_verified':False}


def _size(root):
    return sum(p.stat().st_size for p in root.rglob('*') if p.is_file())


def run(config, output, cache, *, memory='', cancelled=lambda:False,
        progress=lambda value:None, research=None, analyze=None, research_options=None,
        already_processed_sha256=()):
    approved,limits=validate(config)
    processed=set(already_processed_sha256)
    if len(processed)>64 or any(not isinstance(v,str) or not re.fullmatch('[0-9a-f]{64}',v) for v in processed):
        raise ValueError('Bounded previously processed original hashes required')
    config=json.loads(json.dumps(config,allow_nan=False));root=Path(output);cache=Path(cache)
    if root.exists(): raise ValueError('Fresh web-to-planning output required')
    def check():
        if cancelled(): raise CancelledError('Web-to-planning pilot cancelled')
    def quota():
        if _size(root)>limits['max_output_bytes']:
            raise planning.PilotBudgetExceeded('Combined web-to-planning output byte budget exceeded')
    check();root.mkdir(parents=True);atomic_json(root/'config.json',config);quota()
    research=research or web_research.run;analyze=analyze or planning.run
    web_report=research(config['research'],root/'web-research',cache,memory=memory,
        cancelled=cancelled,progress=progress,**(research_options or {}))
    check();quota();originals=root/'originals';originals.mkdir()
    # Reload the verified receipts, not model descriptions or model-supplied
    # local paths. Preserve the exact snapshot that the web stage reported.
    records=[];gaps=[]
    for observation in web_report['sources']:
        check()
        try:
            source=web.cached(observation['requested_url'],cache,approved)
            if (source is None or source['artifact_sha256']!=observation['artifact_sha256'] or
                    source['body_sha256']!=observation['body_sha256'] or source['url']!=observation['url']):
                raise ValueError('Web source snapshot changed before drawing handoff')
            records.append(source)
        except (ValueError,OSError) as error:
            gaps.append({'url':observation['requested_url'],'status':'source_snapshot_withheld','reason':str(error)})
    links={}
    for record in records:
        for link in record['links']:
            links.setdefault(link['url'],[]).append({'parent_citation_id':record['citation_id'],
                'title':link['title'],'application_reference_observed':
                    bool(re.search(r'(?<![A-Za-z0-9/])'+re.escape(config['application_reference'])+
                        r'(?![A-Za-z0-9/])',record['text'],re.I))})
    documents=[];handoffs=[];seen=set();used_pages=0;verified=[]
    for source in records:
        check()
        if source['format']!='pdf': continue
        sha=source['body_sha256']
        row={'url':source['url'],'requested_url':source['requested_url'],
            'citation_id':source['citation_id'],'source_snapshot_sha256':source['artifact_sha256'],
            'body_sha256':sha,'application_reference':config['application_reference'],
            'native_text_status':source['text_status'],
            'ocr_required':source['text_status']=='no_native_text_ocr_required',
            'application_reference_basis':'selected_research_scope_only',
            'application_membership_verified':False,'source_evidence_verified':False,
            'parent_link_claims':links.get(source['requested_url'],[]),
            'status':'pending','pages':[]}
        handoffs.append(row)
        if sha in processed:
            row['status']='original_bytes_processed_in_prior_batch';continue
        if sha in seen:
            row['status']='duplicate_original_bytes';continue
        seen.add(sha)
        if len(documents)>=limits['max_documents']:
            row.update(status='drawing_withheld',reason='Document analysis budget reached');continue
        try:
            path=web._body_path(cache,source);data=path.read_bytes()
            if len(data)>web.MAX_BYTES or hashlib.sha256(data).hexdigest()!=sha:
                raise ValueError('Original web PDF bytes changed during handoff')
            if _size(root)+len(data)>limits['max_output_bytes']:
                raise planning.PilotBudgetExceeded('Combined original-PDF output budget exceeded')
            target=originals/(sha+'.pdf');target.write_bytes(data)
            row['original_file']='originals/'+target.name
            verified.append((path,sha));verified.append((target,sha))
            with pymupdf.open(stream=data,filetype='pdf') as document:
                if document.is_encrypted: raise ValueError('Encrypted drawing requires a separate source review')
                count=len(document)
                if not 1<=count<=limits['max_document_pages'] or used_pages+count>limits['max_pages']:
                    raise ValueError('Complete document exceeds bounded page analysis; no pages silently selected')
                for number in range(1,count+1):
                    check();row['pages'].append({'page':number,**classify(document[number-1])})
            states={state for page in row['pages'] for state in page['observed_states']}
            roles={page['role'] for page in row['pages']}
            title=next((v['title'] for v in row['parent_link_claims'] if v['title']),source['title'])
            item={'file':target.name,'sha256':sha,'title':title.strip()[:512] or 'Unclassified original PDF',
                'role':next(iter(roles)) if len(roles)==1 else 'unclassified',
                'page_roles':{str(p['page']):p['role'] for p in row['pages']},
                'drawing_state':next(iter(states)) if len(states)==1 else 'unknown',
                'application_reference':config['application_reference'],'url':source['url']}
            documents.append(item);used_pages+=len(row['pages'])
            row.update(status='original_pdf_handed_to_analysis',manifest_file=item['file'],
                drawing_state=item['drawing_state'],page_roles=item['page_roles'])
        except planning.PilotBudgetExceeded: raise
        except (ValueError,RuntimeError,OSError) as error:
            row.update(status='drawing_withheld',reason=str(error))
    check();quota()
    manifest=None;analysis=None
    if documents:
        remaining=limits['max_output_bytes']-_size(root)
        if remaining<1: raise planning.PilotBudgetExceeded('No output budget remains for drawing analysis')
        manifest={'version':planning.VERSION,'area_id':config['area_id'],
            'application_references':[config['application_reference']],
            'development_exposure':config.get('development_exposure','unassessed'),
            'source_directory':'originals','documents':documents,
            'options':{**limits,'max_output_bytes':remaining}}
        atomic_json(root/'planning-manifest.json',manifest)
        analysis=analyze(manifest,lambda name:originals/name,root/'analysis',cancelled=cancelled,
            progress=lambda message:progress({'progress':.8,'message':message}))
    for path,sha in verified:
        check()
        if file_hash(path)!=sha: raise ValueError('Original PDF changed during automatic analysis')
    check();quota();atomic_json(root/'handoff.json',{'version':VERSION,'documents':handoffs,'gaps':gaps})
    summary={'retrieved_sources':len(records),'pdf_sources':len(handoffs),
        'unique_originals_handed_to_analysis':len(documents),
        'completed_pages':0 if analysis is None else analysis['summary']['completed_pages'],
        'visible_view_captions':0 if analysis is None else analysis['summary']['visible_view_captions'],
        'surface_candidates':0 if analysis is None else analysis['summary']['surface_candidates'],
        'surface_labels':0 if analysis is None else analysis['summary']['surface_labels'],
        **{k:0 if analysis is None else analysis['summary'].get(k,0) for k in
           ('closed_source_outlines','view_source_outlines','nominal_view_outlines',
            'source_outline_role_hints','building_outline_hints','path_plaza_outline_hints','component_boundary_candidates',
            'components_with_nominal_scale_trials','size_consistent_component_hypotheses',
            'nominal_section_profile_hypotheses','physical_section_heights_verified',
            'section_plan_context_pairs','profiles_with_multiple_plan_candidates',
            'source_sheet_reference_markers','physical_component_correspondences_verified',
            'section_cut_topology_candidates','source_design_dimension_claims',
            'conditional_design_massing_alternatives','conditional_design_row_groups','physical_design_buildings_verified',
            'size_mismatched_component_hypotheses','unresolved_component_size_hypotheses',
            *planning.SURFACE_FOOTPRINT_COUNTS,*planning.AREA_LAYOUT_COUNTS)},
        'unattempted_document_links':len(web_report.get('unattempted_document_urls',[])),
        'unclassified_pages':sum(p['role']=='unclassified' for r in handoffs for p in r['pages']),
        'drawing_state_conflicts':sum(len(p['observed_states'])>1 for r in handoffs for p in r['pages'])}
    blockers=['application_membership_unverified','measured_building_geometry_unresolved',
        'geographic_registration_unresolved','current_as_built_state_unverified','independent_reference_inventory_missing']
    if analysis is None: blockers.append('no_original_pdf_available_for_analysis')
    if web_report['failures'] or gaps: blockers.append('web_source_acquisition_incomplete')
    if web_report.get('unattempted_document_urls'): blockers.append('discovered_document_links_remain_unread')
    if any(r['status']=='drawing_withheld' for r in handoffs): blockers.append('some_drawings_withheld')
    if any(r['ocr_required'] for r in handoffs): blockers.append('scanned_pdf_requires_ocr')
    body='<h1>'+escape(config['area_id'])+'</h1><p>Automatic web evidence and original-drawing analysis. Source membership, current state and physical geometry remain unverified.</p>'
    body+='<p><a href="web-research/report.json">Web sources and failures</a> | <a href="handoff.json">PDF handoff and page classifications</a></p>'
    if analysis is not None: body+='<p><a href="analysis/review.html">Open analysed original drawings and previews</a> | <a href="analysis/area-layouts.html">Source-local building and path plan layouts</a></p>'
    else: body+='<p>No original PDF was eligible for analysis. Inspect the source gaps.</p>'
    body+='<p>Remaining: '+escape(', '.join(blockers).replace('_',' '))+'.</p>'
    (root/'review.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>Web planning source pack</title><body>'+body+'</body></html>',encoding='utf-8')
    quota()
    report={'version':VERSION,'status':'analysed_web_source_pack_with_reconstruction_blockers' if analysis is not None else 'web_source_pack_without_analysable_pdfs',
        'config_sha256':digest(config),'summary':summary,'sources':web_report['sources'],
        'implementations':{m.__name__:planning._implementation(m) for m in
            (sys.modules[__name__],web,web_research,planning,captions)},
        'web_report':'web-research/report.json','planning_report':'analysis/report.json' if analysis is not None else None,
        'area_layout_review':'analysis/area-layouts.json' if analysis is not None else None,
        'area_layout_files':[] if analysis is None else [
            {**entry,'file':'analysis/'+entry['file'],
             **({'geojson_file':'analysis/'+entry['geojson_file']} if 'geojson_file' in entry else {})}
            for entry in analysis.get('area_layout_files',[])],
        'handoffs':handoffs,'handoff_gaps':gaps,'blockers':blockers,
        'unattempted_document_urls':web_report.get('unattempted_document_urls',[]),
        'source_budget_exhausted':web_report.get('source_budget_exhausted',False),
        'source_discovery_exhaustive':False,
        'page_blocker_counts':{} if analysis is None else analysis['page_blocker_counts'],
        'source_blockers':[] if analysis is None else analysis['source_blockers'],
        'source_evidence_verified':False,'application_membership_verified':False,
        'world_placement_eligible':False,'training_labels_generated':0,'model_weights_updated':False,
        'world_geometry_additions':0,'geometric_accuracy':None,
        'output_sha256':{p.relative_to(root).as_posix():file_hash(p) for p in sorted(root.rglob('*')) if p.is_file()}}
    atomic_json(root/'report.json',report)
    if _size(root)>limits['max_output_bytes']:
        (root/'report.json').unlink()
        raise planning.PilotBudgetExceeded('Completed report exceeds combined output budget')
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('config','output','cache'): parser.add_argument('--'+name,required=True)
    args=parser.parse_args(argv);path=Path(args.config)
    if path.stat().st_size>1000000: raise ValueError('Web planning request exceeds config byte budget')
    report=run(json.loads(path.read_text(encoding='utf-8')),args.output,args.cache)
    print(json.dumps({'status':report['status'],**report['summary']}))


if __name__=='__main__': main()
