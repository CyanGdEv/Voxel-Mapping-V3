"""Durable bounded follow-up batches for discovered public planning documents."""
import argparse
from concurrent.futures import CancelledError
from copy import deepcopy
from html import escape
import json
from pathlib import Path
import sys
import time

from . import web_evidence as web, web_research, web_planning_pilot as pilot
from .desktop_memory import digest
from .generation_cycles import file_hash

VERSION='planning-document-collection-v1'
LIMITS={'max_batches':12,'max_urls':64,'max_attempts':3,'max_seconds':900,
        'max_run_bytes':64000000,'max_output_bytes':128000000}
TRANSIENT_HTTP={408,425,429,500,502,503,504}


def validate(config):
    if not isinstance(config,dict) or config.get('version')!=VERSION or set(config)-{'version','pilot','limits'}:
        raise ValueError('Versioned planning collection required')
    approved,analysis=pilot.validate(config.get('pilot'))
    override=config.get('limits',{})
    if not isinstance(override,dict) or set(override)-set(LIMITS):raise ValueError('Known collection limits required')
    limits={**LIMITS,**override}
    if any(type(v) is not int or not 1<=v<=LIMITS[k] for k,v in limits.items()):
        raise ValueError('Bounded collection limits required')
    return approved,analysis,limits


def contract(config):
    approved,analysis,_=validate(config);value=deepcopy(config['pilot'])
    _,seeds,prompt,_=web_research.validate(value['research'])
    # Execution mode and budget changes resume the same source/analysis scope.
    # Changed drawing-analysis code/options get a separate collection.
    value.pop('area_id',None)
    for name in ('offline','refresh','model','endpoint','model_options','limits'):
        value['research'].pop(name,None)
    value['research'].update(allowed_hosts=sorted(approved),urls=seeds,
        query=value['research'].get('query',''),prompt=prompt)
    value['analysis_options']=analysis
    value['development_exposure']=value.get('development_exposure','unassessed')
    return {'version':VERSION,'scope':value,'pymupdf_version':pilot.pymupdf.VersionBind,'implementations':{
        m.__name__:pilot.planning._implementation(m) for m in
        (sys.modules[__name__],pilot,pilot.planning,pilot.captions,web,web_research,
         pilot.planning.building_pdf_discovery,pilot.planning.ordinary_surfaces,pilot.planning.drawing_view_candidates)}}


def collection_key(config):return digest(contract(config))


def _read(path,maximum=4000000):
    path=Path(path)
    if not path.is_file() or path.stat().st_size>maximum:raise ValueError('Bounded collection receipt required')
    return json.loads(path.read_text(encoding='utf-8'))


def _usage(root):
    count=0;size=0
    for path in root.rglob('*'):
        count+=1
        if count>4096:raise ValueError('Collection file-count quota reached')
        if path.is_symlink():raise ValueError('Collection files cannot be symbolic links')
        if path.is_file():size+=path.stat().st_size
    return size


def _batch(storage,number):
    if type(number) is not int or not 1<=number<=64:raise ValueError('Bounded collection batch number required')
    return storage/'batches'/('batch-'+str(number).zfill(4))


def _verified_batch(storage,record,approved,cache):
    root=_batch(storage,record['number']);report=_read(root/'report.json',16000000)
    if file_hash(root/'report.json')!=record['report_sha256']:
        raise ValueError('Saved collection batch report changed')
    if (report.get('version')!=pilot.VERSION or report.get('world_placement_eligible') is not False or
            report.get('training_labels_generated')!=0 or report.get('world_geometry_additions')!=0):
        raise ValueError('Saved source batch asserted unsupported acceptance')
    for name,pin in report['output_sha256'].items():
        rel=Path(name.replace('\\','/'))
        if rel.is_absolute() or '..' in rel.parts or ':' in name:
            raise ValueError('Relative collection output path required')
        path=root/rel
        if path.is_symlink() or file_hash(path)!=pin:raise ValueError('Saved collection batch output changed')
    for source in report['sources']:
        current=web.cached(source['requested_url'],cache,approved)
        if current is None or current['body_sha256']!=source['body_sha256']:
            raise ValueError('Saved collection source bytes changed; use a fresh source scope/cache')
    return report


def run(config,output,cache,storage,*,memory='',cancelled=lambda:False,
        progress=lambda value:None,run_batch=None,clock=time.time,monotonic=time.monotonic,pause=time.sleep):
    approved,analysis,limits=validate(config)
    config=deepcopy(config);root=Path(output);cache=Path(cache);storage=Path(storage)
    if root.exists():raise ValueError('Fresh planning collection job output required')
    from .desktop_runtime import DirectoryLock,write_json
    def check():
        if cancelled():raise CancelledError('Planning collection cancelled; saved batches retained')
    check();storage.mkdir(parents=True,exist_ok=True)
    lock=DirectoryLock(storage/'collection.lock')
    try:
        identity=contract(config);state_path=storage/'ledger.json'
        if state_path.exists():
            state=_read(state_path)
            if (state.get('version')!=VERSION or state.get('contract')!=identity or
                    state.get('artifact_sha256')!=digest({k:v for k,v in state.items() if k!='artifact_sha256'})):
                raise ValueError('Collection scope, code or saved progress changed')
        else:
            state={'version':VERSION,'contract':identity,'entries':{},'batches':[],
                'next_batch':1,'inflight':None,'initial_done':False,'queue_overflow':False}
        if len(state['entries'])>64 or len(state['batches'])>64:raise ValueError('Collection ledger quota exceeded')
        state['queue_overflow']=False
        root.mkdir(parents=True);write_json(root/'config.json',config)
        def save():
            state['artifact_sha256']=digest({k:v for k,v in state.items() if k!='artifact_sha256'})
            if len(json.dumps(state))>2000000:raise ValueError('Collection ledger byte quota exceeded')
            write_json(state_path,state)
        def enqueue(value,document=False):
            try:value=web.url(value,approved)
            except ValueError:return
            if value not in state['entries']:
                if len(state['entries'])>=limits['max_urls']:
                    state['queue_overflow']=True;return
                state['entries'][value]={'url':value,'document':document,'status':'pending',
                    'attempts':0,'next_retry_at':0,'error':None}
            if document:state['entries'][value]['document']=True
        for value,entry in state['entries'].items():
            if web.url(value,approved)!=value or entry['url']!=value:
                raise ValueError('Saved collection URL scope changed')
            if type(entry['attempts']) is not int or not 0<=entry['attempts']<=3:
                raise ValueError('Bounded saved URL attempts required')
            if entry['status']=='offline_missing' and not config['pilot']['research'].get('offline',False):
                entry.update(status='pending',next_retry_at=0)
        for value in config['pilot']['research'].get('urls',[]):enqueue(value)
        reports=[];processed=set()
        def completed(record):
            result=_verified_batch(storage,record,approved,cache);reports.append((record,result))
            for item in result['handoffs']:
                if item['status']=='original_pdf_handed_to_analysis':processed.add(item['body_sha256'])
            return result
        for record in state['batches']:
            completed(record)
            saved_web=_read(_batch(storage,record['number'])/'web-research/report.json',16000000)
            for value in saved_web.get('unattempted_document_urls',[]):enqueue(value,True)
        if len({r['number'] for r in state['batches']})!=len(state['batches']):
            raise ValueError('Collection batch was recorded more than once')
        known_urls={web.url(v,approved) for v in config['pilot']['research'].get('urls',[])}
        verified_sources={}
        for record,result in reports:
            saved_web=_read(_batch(storage,record['number'])/'web-research/report.json',16000000)
            known_urls.update(saved_web['attempted_urls']);known_urls.update(saved_web.get('unattempted_document_urls',[]))
            verified_sources.update({s['requested_url']:s['body_sha256'] for s in result['sources']})
        for value,entry in state['entries'].items():
            if value not in known_urls:raise ValueError('Saved queue URL has no retained discovery evidence')
            if entry['status']=='completed' and entry.get('body_sha256')!=verified_sources.get(value):
                raise ValueError('Saved completed URL has no verified source batch')
        offline=config['pilot']['research'].get('offline',False)
        def commit(number,result):
            directory=_batch(storage,number)
            web_report=_read(directory/'web-research/report.json',16000000)
            failures={f['url']:f for f in web_report['failures']}
            sources={s['requested_url']:s for s in result['sources']}
            for value in web_report['attempted_urls']:
                enqueue(value);entry=state['entries'].get(value)
                if entry is None:continue
                failure=failures.get(value);source=sources.get(value)
                if source:
                    entry.update(status='completed',error=None,body_sha256=source['body_sha256'],next_retry_at=0)
                    if source['retrieval']=='cached_after_network_failure':
                        metadata=_read(directory/'web-research'/(source['citation_id']+'.json'))
                        failure={'code':metadata.get('network_error_code','network_unavailable'),
                            'http_status':metadata.get('http_status'),
                            'retry_after_seconds':metadata.get('retry_after_seconds'),
                            'error':metadata['network_error']}
                elif failure is None:
                    failure={'code':'source_handoff_unavailable','error':'Read source was not retained'}
                if not offline and (failure or {}).get('code') not in ('byte_budget','deadline'):
                    entry['attempts']=min(3,entry['attempts']+1)
                if failure:
                    code=failure['code'];transient=(code in ('network_unavailable','dns_unavailable') or
                        (code=='http_status' and failure.get('http_status') in TRANSIENT_HTTP))
                    status='retry' if transient and entry['attempts']<limits['max_attempts'] else 'unavailable'
                    if code=='offline_cache_miss':status='offline_missing'
                    if code in ('byte_budget','deadline'):status='deferred'
                    delay=max(min(30,2**entry['attempts']),failure.get('retry_after_seconds') or 0)
                    entry.update(status=status,error=failure,next_retry_at=clock()+delay if status=='retry' else 0)
            for value in web_report.get('unattempted_document_urls',[]):enqueue(value,True)
            record={'number':number,'report_sha256':file_hash(directory/'report.json')}
            state['batches'].append(record)
            state['initial_done']=state['initial_done'] or bool(web_report['attempted_urls'])
            state['inflight']=None
            save();completed(record)
        # A killed worker can leave a completely written batch before ledger
        # commit. Verify and commit it once; partial batches remain separate.
        if state['inflight']:
            intent=state['inflight'];directory=_batch(storage,intent['number'])
            if (directory/'report.json').is_file():
                result=_read(directory/'report.json',16000000)
                if result['config_sha256']!=intent['config_sha256']:raise ValueError('Interrupted batch input changed')
                commit(intent['number'],result)
            else:
                for value in intent['urls']:
                    if value in state['entries']:
                        state['entries'][value].update(status='pending',error={'code':'interrupted_batch','error':'Partial batch retained'})
                state['inflight']=None;save()
        # Byte/time budgets apply to this execution across every batch.
        budget=web.Budget(limits['max_run_bytes']);deadline=monotonic()+limits['max_seconds']
        run_batch=run_batch or pilot.run;made=0;stop='known_document_queue_drained'
        while True:
            check()
            if made>=limits['max_batches']:stop='batch_budget_reached';break
            if budget.exhausted:stop='byte_budget_reached';break
            if monotonic()>=deadline:stop='time_budget_reached';break
            if state['next_batch']>64:stop='collection_history_quota_reached';break
            remaining=limits['max_output_bytes']-_usage(storage)-1000000
            if remaining<1:stop='collection_output_quota_reached';break
            candidates=[e for e in state['entries'].values() if e['status'] in ('pending','retry','deferred')]
            candidates.sort(key=lambda e:(not e['document'],e['status']=='retry'))
            ready=[e['url'] for e in candidates if e['next_retry_at']<=clock()]
            if state['initial_done'] and not ready:
                if not candidates:
                    if state['queue_overflow']:stop='url_budget_reached'
                    break
                wait=min(1,max(.01,min(e['next_retry_at'] for e in candidates)-clock()))
                progress({'progress':.05+.8*made/limits['max_batches'],
                    'message':'Waiting for scheduled source retries; saved progress retained'})
                pause(wait);continue
            batch_config=deepcopy(config['pilot'])
            if state['initial_done']:
                batch_config['research']['query']='';batch_config['research']['urls']=ready[:6]
            batch_config['analysis_options']={**batch_config.get('analysis_options',{}),
                'max_output_bytes':min(analysis['max_output_bytes'],remaining)}
            number=state['next_batch'];state['next_batch']+=1
            state['inflight']={'number':number,'urls':batch_config['research'].get('urls',[]),
                'config_sha256':digest(batch_config)};save()
            progress({'progress':.05+.8*made/limits['max_batches'],
                'message':'Collecting planning documents, batch '+str(number)})
            skipped=[e['url'] for e in state['entries'].values() if e['status'] in ('completed','unavailable','offline_missing')]
            try:
                result=run_batch(batch_config,_batch(storage,number),cache,memory=memory,
                    cancelled=cancelled,progress=progress,already_processed_sha256=processed,
                    research_options={'skip_urls':skipped,'parent_budget':budget,'run_deadline':deadline})
            except pilot.planning.PilotBudgetExceeded:
                stop='collection_output_quota_reached';break
            commit(number,result);made+=1
            if not state['initial_done']:
                stop='search_unavailable_or_no_results';break
        check();save()
        # Export a bounded, portable verified snapshot. Copy completed batches
        # only; partial interrupted outputs stay in the durable collection.
        for record,result in reports:
            source=_batch(storage,record['number']);destination=_batch(root,record['number'])
            for path in source.rglob('*'):
                check()
                if path.is_file():
                    target=destination/path.relative_to(source);target.parent.mkdir(parents=True,exist_ok=True)
                    with path.open('rb') as src,target.open('wb') as dst:
                        while chunk:=src.read(1048576):check();dst.write(chunk)
                    if file_hash(path)!=file_hash(target):raise ValueError('Collection export changed during copy')
        sources={};summary={'completed_batches':len(reports),'new_batches':made,'known_urls':len(state['entries']),
            'completed_sources':sum(e['status']=='completed' for e in state['entries'].values()),
            'completed_pages':0,'unique_originals_handed_to_analysis':0,'visible_view_captions':0,
            'surface_labels':0,'surface_candidates':0}
        analysis_gaps={}
        for record,result in reports:
            for item in result['sources']:sources[item['requested_url']]=item
            for item in result['handoffs']:
                if (item['status']=='drawing_withheld' or item.get('ocr_required') or
                        any(p['role']=='unclassified' for p in item['pages'])):
                    analysis_gaps[item['body_sha256']]={'url':item['url'],'sha256':item['body_sha256'],
                        'status':item['status'],'reason':item.get('reason'),
                        'ocr_required':item.get('ocr_required',False),'batch':record['number']}
            for name in ('completed_pages','unique_originals_handed_to_analysis','visible_view_captions','surface_labels','surface_candidates'):
                summary[name]+=result['summary'][name]
        unresolved=[deepcopy(e) for e in state['entries'].values() if e['status']!='completed']
        summary['unresolved_sources']=len(unresolved)
        summary['documents_needing_analysis_review']=len(analysis_gaps)
        body='<h1>'+escape(config['pilot']['area_id'])+'</h1><p>Planning document collection. Source membership and physical geometry remain unverified.</p><ul>'
        body+=''.join('<li><a href="batches/batch-'+str(r['number']).zfill(4)+'/review.html">Batch '+str(r['number'])+' drawings and source gaps</a></li>' for r,_ in reports)
        body+='</ul><p>'+str(len(unresolved))+' unresolved sources. Stop: '+escape(stop)+'.</p><p><a href="ledger.json">Saved document queue</a></p>'
        (root/'review.html').write_text('<!doctype html><html><meta charset="utf-8"><title>Planning collection</title><body>'+body+'</body></html>',encoding='utf-8')
        write_json(root/'ledger.json',state)
        result={'version':VERSION,'status':'known_documents_processed_with_reconstruction_gaps' if not unresolved and not state['queue_overflow'] and state['initial_done'] else 'planning_collection_with_source_gaps',
            'summary':summary,'stop_reason':stop,'collection_key':digest(identity),'network_bytes':budget.spent,
            'limits':limits,'queue_overflow':state['queue_overflow'],'unresolved_sources':unresolved,'sources':list(sources.values()),
            'initial_search_pending':not state['initial_done'],
            'analysis_gaps':list(analysis_gaps.values()),
            'source_discovery_exhaustive':False,'application_membership_verified':False,
            'source_evidence_verified':False,'world_placement_eligible':False,'geometric_accuracy':None,
            'training_labels_generated':0,'model_weights_updated':False,'world_geometry_additions':0,
            'output_sha256':{p.relative_to(root).as_posix():file_hash(p) for p in root.rglob('*') if p.is_file()}}
        write_json(root/'report.json',result)
        if _usage(root)>limits['max_output_bytes']:
            (root/'report.json').unlink();raise pilot.planning.PilotBudgetExceeded('Collection export byte budget exceeded')
        return result
    finally:lock.close()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('config','output','cache','state'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args(argv)
    result=run(_read(args.config,1000000),args.output,args.cache,args.state)
    print(json.dumps({'status':result['status'],**result['summary']}))


if __name__=='__main__':main()
