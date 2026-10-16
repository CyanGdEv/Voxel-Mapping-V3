"""Bounded requirement-directed acquisition of known official attachments.

Text and catalogue matches prioritize investigation; none authorizes geometry.
Durable per-resource intents prevent repeated requests after failure/restart.
"""
import json
from pathlib import Path
import re
from urllib.parse import urlparse

from .generation_cycles import atomic_json, file_hash
from .reconstruction_evidence_queue import digest
from .retained_evidence_matching import REGEX, run as match_sources

VERSION='evidence-directed-acquisition-v1'
DEFAULTS={'max_documents':8,'max_file_bytes':16000000,'max_run_bytes':32000000}


def options(settings=None):
    settings={} if settings is None else settings
    if not isinstance(settings,dict) or set(settings)-set(DEFAULTS):
        raise ValueError('Known evidence acquisition settings required')
    result={**DEFAULTS,**settings}
    for key,ceiling in [('max_documents',32),('max_file_bytes',64000000),('max_run_bytes',128000000)]:
        if type(result[key]) is not int or not 1<=result[key]<=ceiling:
            raise ValueError('Bounded evidence acquisition budgets required')
    return result


def plan(corpus,queue,hosts):
    if queue['status']!='missing_evidence_worklist':
        raise ValueError('Complete missing-evidence worklist required')
    tasks=queue['tasks'];by_kind={}
    if len(tasks)>100000 or len({t['id'] for t in tasks})!=len(tasks):
        raise ValueError('Unique bounded evidence tasks required')
    for task in tasks:
        if task['kind'] not in REGEX:raise ValueError('Supported evidence requirement required')
        by_kind.setdefault(task['kind'],[]).append(task['id'])
    bootstrap=not tasks and not queue.get('source_pages')
    if bootstrap:by_kind={kind:[] for kind in REGEX}
    records=corpus.db.execute('SELECT d.record,l.url,l.expected_sha,l.transport_url,l.status FROM documents d JOIN downloads l ON d.url=l.url ORDER BY d.id LIMIT 10001').fetchall()
    if len(records)>10000:raise ValueError('Bounded attachment inventory required')
    candidates={};assignments=0
    for raw,url,pin,transport,status in records:
        record=json.loads(raw);parsed=urlparse(url)
        if (record['url']!=url or parsed.scheme!='https' or parsed.hostname not in hosts
                or parsed.username or parsed.password or parsed.port not in (None,443) or parsed.fragment):
            raise ValueError('Known official HTTPS attachment required')
        if pin and (len(pin)!=64 or any(c not in '0123456789abcdef' for c in pin)):
            raise ValueError('Valid attachment checksum required')
        if transport:
            alternate=urlparse(transport)
            if (alternate.scheme not in ('http','https') or alternate.hostname!=parsed.hostname
                    or alternate.path!=parsed.path or alternate.query!=parsed.query
                    or alternate.username or alternate.password or alternate.fragment
                    or alternate.port not in (None,80 if alternate.scheme=='http' else 443)
                    or (alternate.scheme=='http' and not pin)):
                raise ValueError('Pinned same-resource transport required')
        title=record.get('title','')
        if not isinstance(title,str) or len(title)>2000:raise ValueError('Bounded attachment title required')
        # Common attachment-title abbreviations/plurals are discovery hints,
        # never a change to source text or a geometry interpretation.
        search_title=re.sub(r'\b(elevation|section|plan)s\b',r'\1',title,flags=re.I)
        search_title=re.sub(r'\bGF\s+plan\b','floor plan',search_title,flags=re.I)
        kinds=[kind for kind in sorted(by_kind) if REGEX[kind].search(search_title)]
        if not kinds or status=='downloaded':continue
        request={'version':VERSION,'url':url,'expected_sha256':pin,'transport_url':transport}
        item=candidates.setdefault(url,{'request':request,'request_id':digest(request),
            'titles':set(),'task_ids':set(),'requirement_kinds':set(),
            'matching_basis':'catalogue_bootstrap' if bootstrap else 'missing_requirement_titles',
            'physical_identity_verified':False,'geometry_export_authorized':False})
        item['titles'].add(title);item['requirement_kinds'].update(kinds)
        for kind in kinds:item['task_ids'].update(by_kind[kind])
    rows=[]
    for url,item in sorted(candidates.items()):
        assignments+=len(item['task_ids'])
        if assignments>100000:raise ValueError('Evidence acquisition assignment budget exceeded')
        rows.append({k:sorted(v) if isinstance(v,set) else v for k,v in item.items()})
    return rows


def run(corpus,queue_directory,output,*,official_hosts,offline=True,settings=None,fetch=None,fault=None):
    budget=options(settings);hosts=sorted(set(official_hosts));output=Path(output)
    if type(offline) is not bool or not hosts:raise ValueError('Explicit acquisition mode and official hosts required')
    queue_directory=Path(queue_directory);queue_path=queue_directory/'missing-evidence.json'
    queue_report=json.loads((queue_directory/'queue-report.json').read_text())
    queue_pin=file_hash(queue_path)
    if queue_pin!=queue_report['output_sha256']:raise ValueError('Requirement queue changed')
    queue=json.loads(queue_path.read_text())
    contract={'version':VERSION,'budgets':budget,'official_hosts':hosts,'offline':offline}
    if output.exists():
        if json.loads((output/'contract.json').read_text())!=contract:
            raise ValueError('Evidence acquisition policy changed; use a fresh output')
    else:
        output.mkdir(parents=True);atomic_json(output/'contract.json',contract)
    # Validate the last published report before replacing it on a changed corpus.
    pointer=output/'report-pin.json'
    if pointer.exists():
        if file_hash(output/'acquisition-report.json')!=json.loads(pointer.read_text())['sha256']:
            raise ValueError('Evidence acquisition report changed')
    before=match_sources(corpus,queue_directory,output/'matching')
    candidates=plan(corpus,queue,hosts);attempts=output/'attempts';attempts.mkdir(exist_ok=True)
    retained={};spent=0
    for directory in sorted(attempts.iterdir()):
        intent_path=directory/'intent.json'
        if file_hash(intent_path)!=json.loads((directory/'intent-pin.json').read_text())['sha256']:
            raise ValueError('Evidence acquisition intent changed')
        intent=json.loads(intent_path.read_text())
        if digest(intent['request'])!=directory.name:raise ValueError('Evidence acquisition intent changed')
        receipt_path=directory/'receipt.json';pin_path=directory/'receipt-pin.json'
        if receipt_path.exists():
            if not pin_path.exists() or file_hash(receipt_path)!=json.loads(pin_path.read_text())['sha256']:
                raise ValueError('Evidence acquisition receipt changed')
            receipt=json.loads(receipt_path.read_text())
        else:
            # A process may die before the request, during it, or after its DB
            # commit. Never blindly repeat a resource whose outcome is unknown.
            corpus.acquire(offline=True,max_bytes=budget['max_file_bytes'],only_urls=[intent['request']['url']])
            row=corpus.db.execute('SELECT status,sha,error FROM downloads WHERE url=?',(intent['request']['url'],)).fetchone()
            receipt={'request':intent['request'],'status':'interrupted_attempt_not_repeated',
                'observed_download_status':row[0] if row else 'absent','document_sha256':row[1] if row else None,
                'error':row[2] if row else None,'charged_network_bytes':intent['reserved_bytes'],
                'recovered_after_interruption':True,'geometry_export_authorized':False}
            atomic_json(receipt_path,receipt);atomic_json(pin_path,{'sha256':file_hash(receipt_path)})
        if receipt['request']!=intent['request']:raise ValueError('Evidence acquisition receipt identity changed')
        retained[directory.name]=receipt;spent+=receipt['charged_network_bytes']
    if len(retained)>budget['max_documents'] or spent>budget['max_run_bytes']:
        raise ValueError('Retained acquisition exceeds its policy budget')
    selected=[];covered=set();remaining=[c for c in candidates if c['request_id'] not in retained]
    while remaining and len(retained)+len(selected)<budget['max_documents']:
        remaining.sort(key=lambda c:(-len(set(c['requirement_kinds'])-covered),c['request']['url']))
        item=remaining.pop(0);selected.append(item);covered.update(item['requirement_kinds'])
    new=[];network_bytes=0
    if not offline:
        for item in selected:
            if spent>=budget['max_run_bytes']:break
            request=item['request'];url=request['url'];directory=attempts/item['request_id'];directory.mkdir()
            reserved=min(budget['max_file_bytes'],budget['max_run_bytes']-spent)
            atomic_json(directory/'intent.json',{'request':request,'queue_sha256':queue_pin,
                'task_ids':item['task_ids'],'reserved_bytes':reserved})
            atomic_json(directory/'intent-pin.json',{'sha256':file_hash(directory/'intent.json')})
            if fault:fault('after_intent',url)
            # Reconcile retained pinned bytes before selecting this exact URL.
            corpus.acquire(offline=True,max_bytes=budget['max_file_bytes'],only_urls=[url])
            status,prior=corpus.db.execute('SELECT status,attempts FROM downloads WHERE url=?',(url,)).fetchone()
            result={'run_network_bytes':0}
            if status!='downloaded' and prior<10:
                result=corpus.acquire(workers=1,limit=1,attempts=prior+1,max_bytes=budget['max_file_bytes'],
                    max_run_bytes=reserved,interval=0,priority_urls=[url],only_urls=[url],fetch=fetch)
            if fault:fault('after_acquire',url)
            status,sha,error=corpus.db.execute('SELECT status,sha,error FROM downloads WHERE url=?',(url,)).fetchone()
            used=result['run_network_bytes'];spent+=used;network_bytes+=used
            receipt={'request':request,'status':status,'document_sha256':sha,'error':error,
                'charged_network_bytes':used,'recovered_after_interruption':False,'geometry_export_authorized':False}
            atomic_json(directory/'receipt.json',receipt)
            atomic_json(directory/'receipt-pin.json',{'sha256':file_hash(directory/'receipt.json')})
            retained[item['request_id']]=receipt;new.append(receipt)
    after=match_sources(corpus,queue_directory,output/'matching')
    if file_hash(queue_path)!=queue_pin:raise ValueError('Requirement queue changed during acquisition')
    report={'version':VERSION,'status':'offline_evidence_plan' if offline else 'evidence_sources_rechecked',
        'catalogue_bootstrap':not queue['tasks'] and not queue.get('source_pages'),
        'queue_sha256':queue_pin,'budgets':budget,'candidates':candidates,
        'attempts':list(retained.values()),'run_attempts':len(new),'retained_attempts':len(retained)-len(new),
        'run_network_bytes':network_bytes,'charged_network_bytes':spent,
        'new_downloads':sum(r['status']=='downloaded' for r in new),
        'remaining_unattempted_candidates':sum(c['request_id'] not in retained for c in candidates),
        'before_matching':before,'after_matching':after,
        'requirements_resolved':0,'geometry_export_authorized':False,'world_geometry_additions':0,
        'limitations':['Only known official catalogue attachments are considered; no new application or URL discovery is claimed.',
            'Title/text matches are investigation priorities, not physical identity, dimensions or registration.',
            'An unchanged failed or interrupted resource is not requested again by this acquisition pass.']}
    atomic_json(output/'acquisition-report.json',report)
    atomic_json(pointer,{'sha256':file_hash(output/'acquisition-report.json')})
    return report
