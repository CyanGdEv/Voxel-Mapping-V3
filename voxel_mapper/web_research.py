"""Read-only model-directed web evidence within operator-selected source scope."""
import argparse
from concurrent.futures import CancelledError
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

from . import web_evidence as web
from .desktop_memory import digest
from .generation_cycles import atomic_json, file_hash
from . import local_reasoning

VERSION='web-research-v1'
LIMITS={'max_sources':6,'max_model_rounds':2,'max_run_bytes':16000000,'max_seconds':300}


def validate(config):
    if not isinstance(config,dict) or config.get('version')!=VERSION:
        raise ValueError('Versioned web research configuration required')
    if set(config)-{'version','query','urls','allowed_hosts','prompt','model','endpoint','model_options',
                    'offline','refresh','limits'}: raise ValueError('Unknown web research setting')
    approved=web.hosts(config.get('allowed_hosts',list(web.DEFAULT_HOSTS)))
    urls=config.get('urls',[])
    if not isinstance(urls,list) or len(urls)>6: raise ValueError('At most six public seed URLs required')
    normalized=[web.url(u,approved) for u in urls]
    if len(set(normalized))!=len(normalized): raise ValueError('Distinct seed URLs required')
    query=config.get('query','')
    if not isinstance(query,str) or len(query)>300 or any(ord(c)<32 for c in query):
        raise ValueError('Bounded public search query required')
    if not normalized and not query.strip(): raise ValueError('Supply public seed URLs or an explicit search query')
    prompt=config.get('prompt',query or 'Inspect these sources and identify the next evidence checks.')
    if not isinstance(prompt,str) or not 1<=len(prompt.strip())<=2048: raise ValueError('Bounded research question required')
    for key in ('offline','refresh'):
        if type(config.get(key,False if key=='offline' else True)) is not bool:
            raise ValueError('Explicit web cache mode required')
    override=config.get('limits',{})
    if not isinstance(override,dict) or set(override)-set(LIMITS): raise ValueError('Known web limits required')
    limits={**LIMITS,**override}
    if any(type(v) is not int or not 1<=v<=LIMITS[k] for k,v in limits.items()): raise ValueError('Bounded web limits required')
    model=config.get('model','')
    if not isinstance(model,str) or len(model)>128: raise ValueError('Bounded installed model name required')
    if model:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:@-]{0,127}',model): raise ValueError('Installed model name required')
        local_reasoning._endpoint(config.get('endpoint',local_reasoning.DEFAULT_ENDPOINT))
        local_reasoning._options(config.get('model_options'))
    return approved,normalized,prompt,limits


def _context(prompt,memory,sources,known):
    maximum=min(2048,4096-len(prompt));records=[];offered=[]
    titles={link['url']:link['title'][:100] for item in sources for link in item['source']['links']}
    # Preserve complete bounded JSON records; truncating a whole serialized
    # memory string can hide which source excerpts the model actually received.
    private=memory[:min(256,maximum//4)]
    def serialized():
        return json.dumps({'untrusted_local_observations':private,
            'untrusted_web_excerpts':records,'discovered_links':[
                {'url':value,'title':titles.get(value,'')} for value in offered]},ensure_ascii=False,separators=(',',':'))
    included=[]
    for item in sources:
        source=item['source']
        row={'citation_id':source['citation_id'],'url':source['url'],
             'title':source['title'][:100],'excerpt':source['text'][:350],
             'retrieved_at_utc':source['retrieved_at_utc'],'retrieval':item['retrieval']}
        records.append(row)
        if len(serialized())>maximum-(384 if known else 0): records.pop();continue
        included.append(source['citation_id'])
    for link in known:
        offered.append(link)
        if len(serialized())>maximum: offered.pop();continue
    return serialized(),included,offered


def run(config, output, cache, *, memory='', cancelled=lambda:False, progress=lambda value:None,
        fetch=None, search=None, reason=None, skip_urls=(), parent_budget=None, run_deadline=None):
    approved,seeds,prompt,limits=validate(config)
    skipped={web.url(value,approved) for value in skip_urls}
    config=json.loads(json.dumps(config,allow_nan=False));output=Path(output)
    if output.exists(): raise ValueError('Fresh web research output required')
    if not isinstance(memory,str): raise ValueError('Retained source context must be text')
    fetch=fetch or web.fetch;search=search or web.search;reason=reason or local_reasoning.reason
    if cancelled(): raise CancelledError('Web research cancelled')
    output.mkdir(parents=True);atomic_json(output/'config.json',config)
    started=time.monotonic();deadline=started+limits['max_seconds']
    if run_deadline is not None:deadline=min(deadline,run_deadline)
    budget=web.Budget(limits['max_run_bytes'],parent=parent_budget)
    sources=[];failures=[];attempted=set();known=[];document_links=set();rounds=[];executions=[];withheld=[]
    search_report=None;model_error=None
    def check():
        if cancelled(): raise CancelledError('Web research cancelled')
        return time.monotonic()<deadline
    def discover(value):
        try: target=web.url(value,approved)
        except ValueError: return
        if target not in known and len(known)<64: known.append(target)
        return target if target in known else None
    def pending():
        return sorted((value for value in known if value not in attempted and value not in skipped),
            key=lambda value:0 if value in document_links else 1)
    for value in seeds: discover(value)
    if config.get('query','').strip():
        check();progress({'progress':.05,'message':'Searching public web sources'})
        try:
            search_report=search(config['query'],cache,approved,offline=config.get('offline',False),
                refresh=config.get('refresh',True),budget=budget,cancelled=cancelled,deadline=deadline)
            for item in search_report['results']: discover(item['url'])
            atomic_json(output/'search.json',search_report)
        except (web.WebError,ValueError) as error:
            search_report={'status':'search_unavailable','error':str(error),'results':[]}
    def read(value,proposal_id=None):
        if not check(): return
        value=web.url(value,approved)
        if value in attempted or value in skipped or len(attempted)>=limits['max_sources']: return
        attempted.add(value);progress({'progress':.1+.5*len(attempted)/limits['max_sources'],
            'message':'Reading web evidence: '+value[:180]})
        try:
            item=fetch(value,cache,approved,offline=config.get('offline',False),
                refresh=config.get('refresh',True),budget=budget,cancelled=cancelled,deadline=deadline)
            source=item['source'];sources.append(item)
            atomic_json(output/(source['citation_id']+'.json'),item)
            for link in source['links']:
                target=discover(link['url'])
                if target and (urlsplit(target).path.lower().endswith('.pdf') or
                        'attachmentshowservlet' in urlsplit(target).path.lower() or
                        re.search(r'\b(plan|drawing|elevations?|sections?|surfacing)\b',link['title'],re.I)):
                    document_links.add(target)
            if proposal_id: executions.append({'proposal_id':proposal_id,'url':value,'citation_id':source['citation_id']})
        except (web.WebError,ValueError) as error:
            failures.append({'url':value,'code':getattr(error,'code','invalid_source'),
                'http_status':getattr(error,'http_status',None),
                'retry_after_seconds':getattr(error,'retry_after_seconds',None),'error':str(error)})
    # Explicit seeds are read first. Without a model, bounded search results
    # can still be gathered and retained for later local-model reasoning.
    initial=seeds or known[:2]
    for value in initial: read(value)
    model=config.get('model','')
    if not model:
        while len(attempted)<limits['max_sources'] and check():
            candidates=pending()
            if not candidates: break
            read(candidates[0])
    else:
        for number in range(limits['max_model_rounds']):
            if not check(): break
            context,included,offered=_context(prompt,memory,sources,pending())
            try:
                reply=reason(prompt,model=model,memory=context,
                    endpoint=config.get('endpoint',local_reasoning.DEFAULT_ENDPOINT),
                    options=config.get('model_options'),cancelled=cancelled,
                    max_seconds=max(1,min(300,deadline-time.monotonic())))
                local_reasoning.validate_receipt(reply)
            except (local_reasoning.ReasoningError,ValueError) as error:
                model_error={'code':getattr(error,'code','invalid_model_input'),'error':str(error)};break
            observed={s['source']['citation_id'] for s in sources if s['source']['citation_id'] in included}
            referenced=set(re.findall(r'\[(W[0-9a-f]{12})\]',reply['summary']))
            round_report={'advisory_receipt':reply,'context_citation_ids':included,
                'offered_links':offered,'cited_source_ids':sorted(referenced&observed),
                'unknown_citation_ids':sorted(referenced-observed),
                'citations_fact_checked':False,'model_context_sha256':digest(context)}
            rounds.append(round_report);atomic_json(output/f'model-round-{number+1}.json',round_report)
            selected=[]
            for proposal in reply['proposals']:
                if proposal['action']!='read_web':
                    withheld.append({'proposal_id':proposal['id'],'reason':'operational_action_not_executed'});continue
                target=web.url(proposal['parameters']['url'])
                if target not in offered:
                    withheld.append({'proposal_id':proposal['id'],'reason':'url_not_an_exact_offered_link'});continue
                if target not in attempted and target not in selected: selected.append(target)
            if number+1==limits['max_model_rounds']:
                for p in reply['proposals']:
                    if p['action']=='read_web' and web.url(p['parameters']['url']) in selected:
                        withheld.append({'proposal_id':p['id'],'reason':'model_round_budget_reached'})
                break
            if not selected: break
            for target in selected:
                proposal=next(p for p in reply['proposals'] if p['action']=='read_web' and web.url(p['parameters']['url'])==target)
                read(target,proposal['id'])
    within_time=check()
    observations=[{'url':r['source']['url'],'requested_url':r['source']['requested_url'],
        'citation_id':r['source']['citation_id'],'title':r['source']['title'],
        'body_sha256':r['source']['body_sha256'],'artifact_sha256':r['source']['artifact_sha256'],
        'retrieved_at_utc':r['source']['retrieved_at_utc'],'retrieval':r['retrieval'],
        'excerpt':r['source']['text'][:600],'source_evidence_verified':False,
        'training_labels_generated':0} for r in sources]
    status='web_evidence_gathered' if sources else 'web_sources_unavailable'
    if model_error: status+='__reasoning_unavailable'
    summary=rounds[-1]['advisory_receipt']['summary'] if rounds else 'Retrieved '+str(len(sources))+' web sources; source interpretation remains unverified.'
    if rounds and rounds[-1]['unknown_citation_ids']:
        summary='Model returned citations outside its supplied source context; inspect the retained evidence.'
        status+='__unsupported_model_citations'
    report={'version':VERSION,'status':status,'summary':summary,'config_sha256':digest(config),
        'sources':observations,'failures':failures,'search':search_report,'model_rounds':rounds,
        'read_only_model_requests_executed':executions,'withheld_proposals':withheld,
        'model_error':model_error,'limits':limits,'attempted_sources':len(attempted),
        'attempted_urls':sorted(attempted),
        'network_bytes':budget.spent,'cache_directory':str(Path(cache).resolve()),
        'unattempted_discovered_urls':pending(),
        'unattempted_document_urls':[value for value in pending() if value in document_links],
        'source_budget_exhausted':len(attempted)>=limits['max_sources'] and bool(pending()),
        'discovery_exhaustive':False,
        'time_budget_exhausted':not within_time,'byte_budget_exhausted':budget.spent>=budget.limit,
        'operational_proposals_executed':False,'source_evidence_verified':False,
        'training_labels_generated':0,'model_weights_updated':False,'world_geometry_additions':0,
        'elapsed_seconds':round(time.monotonic()-started,3),
        'output_sha256':{p.name:file_hash(p) for p in sorted(output.iterdir()) if p.is_file()}}
    atomic_json(output/'report.json',report)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('config','output','cache'): parser.add_argument('--'+name,required=True)
    args=parser.parse_args(argv);path=Path(args.config)
    if path.stat().st_size>1000000: raise ValueError('Web request configuration too large')
    report=run(json.loads(path.read_text()),args.output,args.cache)
    print(json.dumps({'status':report['status'],'sources':len(report['sources']),
        'model_rounds':len(report['model_rounds']),'network_bytes':report['network_bytes']}))


if __name__=='__main__': main()
