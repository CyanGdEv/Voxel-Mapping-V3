"""Search original retained PDF text for requirement candidates, never accept geometry."""
from collections import Counter
import json
from pathlib import Path
import re
import pymupdf
from .generation_cycles import atomic_json, file_hash
from .reconstruction_evidence_queue import digest

VERSION='retained-evidence-matching-v1'
PATTERNS={
 'view_scope':r'\b(?:site\s+plan|floor\s+plan|roof\s+plan|key\s*plan|elevation|section)\b|\b1\s*:\s*\d+\b',
 'physical_exterior':r'\b(?:floor\s+plan|roof\s+plan|courtyard|external\s+wall|elevation|section)\b',
 'plan_elevation_correspondence':r'\b(?:archway\s*\d+|[wd]\.\d+\.\d+|elevation|roof\s+plan|section)\b',
 'relative_dimensions':r'\b(?:eaves(?:\s+level)?|ridge(?:\s+(?:level|u/s))?|floor\s+level|finished\s+floor|FFL|dimension)\b(?:\s*[:=]?\s*[+-]?\d+(?:\.\d+)?)?',
 'horizontal_registration':r'\b(?:o\.?\s*s\.?\s*b\.?\s*m\.?|topographical|survey\s+control|survey\s+station|benchmark|bench\s+mark|national\s+grid|grid\s+reference|eastings?|northings?|site\s+location)\b',
 'vertical_datum':r'\b(?:o\.?\s*s\.?\s*b\.?\s*m\.?|datum|benchmark|bench\s+mark|AOD|ODN|Ordnance\s+Datum|finished\s+floor(?:\s+level)?|FFL)\b(?:\s*[:=]?\s*[+-]?\d+(?:\.\d+)?)?',
}
REGEX={kind:re.compile(pattern,re.I) for kind,pattern in PATTERNS.items()}


def lead_role(kind, text):
    if kind=='vertical_datum':
        return ('datum_reference_candidate' if re.search(r'\b(?:o\.?\s*s\.?\s*b\.?\s*m\.?|AOD|ODN|Ordnance\s+Datum|benchmark|bench\s+mark)\b',text,re.I)
                else 'floor_or_unspecified_datum_context_only')
    if kind=='horizontal_registration':
        return ('survey_reference_candidate' if re.search(r'\b(?:o\.?\s*s\.?\s*b\.?\s*m\.?|survey\s+control|survey\s+station|benchmark|bench\s+mark|topographical)\b',text,re.I)
                else 'location_or_coordinate_context_only')
    return 'requirement_text_candidate'


def match(queue, documents, *, max_pages=10000, max_hits=20000, max_assignments=100000):
    for value,ceiling in ((max_pages,10000),(max_hits,100000),(max_assignments,100000)):
        if type(value) is not int or not 1<=value<=ceiling:raise ValueError('Bounded match budgets required')
    tasks=queue['tasks']
    if len(tasks)>100000 or len({t['id'] for t in tasks})!=len(tasks):raise ValueError('Unique bounded task inventory required')
    if any(t['kind'] not in REGEX for t in tasks):raise ValueError('Supported evidence requirements required')
    if queue['status']!='missing_evidence_worklist':
        return {'version':VERSION,'status':'complete_requirement_queue_required','hits':[],'task_results':[],
            'source_pages':[],'world_geometry_additions':0,'geometry_export_authorized':False}
    documents=sorted(documents,key=lambda d:d['sha256'])
    if len(documents)>1000 or len({d['sha256'] for d in documents})!=len(documents):raise ValueError('Unique bounded source inventory required')
    kinds=sorted({t['kind'] for t in tasks});hits=[];pages=[];benchmarks=[];exhausted=False
    for document in documents:
        path=Path(document['path']);sha=document['sha256']
        if not re.fullmatch('[0-9a-f]{64}',sha) or file_hash(path)!=sha:raise ValueError('Pinned retained PDF required')
        with pymupdf.open(path) as pdf:
            for page in pdf:
                if len(pages)>=max_pages:exhausted=True;break
                text=page.get_text()
                if len(text)>500000:exhausted=True;break
                text_sha=digest(text);number=page.number+1
                if re.search(r'\bo\.?\s*s\.?\s*b\.?\s*m\.?\b|\bbench\s*mark\b',text,re.I):
                    from .benchmark_label_evidence import review as review_benchmarks
                    benchmarks.append(review_benchmarks(page,sha,number))
                pages.append({'document_sha256':sha,'page':number,'native_text_sha256':text_sha,
                    'printed_state_claims':sorted({m.group().lower() for m in re.finditer(r'\b(?:existing|proposed|as[- ]built)\b',text,re.I)})})
                for kind in kinds:
                    for found in REGEX[kind].finditer(text):
                        if len(hits)>=max_hits:exhausted=True;break
                        proof={'document_sha256':sha,'page':number,'native_text_sha256':text_sha,
                            'character_start':found.start(),'character_end':found.end(),'matched_text':found.group()}
                        hits.append({'id':digest([kind,proof]),'kind':kind,'proof':proof,
                            'context_excerpt':text[max(0,found.start()-80):min(len(text),found.end()+120)],
                            'source_links':document.get('source_links',[]),
                            'status':'native_text_lead_only','lead_role':lead_role(kind,found.group()),'glyph_visibility_verified':False,
                            'physical_area_membership_verified':False,'construction_state_verified':False,
                            'dimensions_verified':False,'geometry_export_authorized':False})
                    if exhausted:break
                if exhausted:break
        if file_hash(path)!=sha:raise ValueError('Source changed during matching')
        if exhausted:break
    assignments=0;results=[]
    by_kind={k:sorted(h['id'] for h in hits if h['kind']==k) for k in kinds}
    direct={k:sorted(h['id'] for h in hits if h['kind']==k and not h['lead_role'].endswith('_context_only')) for k in kinds}
    if not exhausted:
        for task in sorted(tasks,key=lambda t:t['id']):
            ids=by_kind[task['kind']];assignments+=len(ids)
            if assignments>max_assignments:exhausted=True;break
            results.append({'task_id':task['id'],'kind':task['kind'],
                'status':'candidate_sources_found' if direct[task['kind']] else 'related_text_only' if ids else 'no_retained_text_lead',
                'candidate_hit_ids':ids,'direct_requirement_hit_ids':direct[task['kind']],'requirement_resolved':False,
                'next_action':'validate_source_view_and_physical_identity' if direct[task['kind']] else 'seek_additional_source_documents'})
    if exhausted:hits=[];results=[];benchmarks=[]
    return {'version':VERSION,'area_id':queue['area_id'],'requirement_queue_sha256':digest(queue),
        'status':'matching_budget_withheld' if exhausted else 'retained_source_leads_only',
        'source_pages':pages,'benchmark_reviews':benchmarks,'hits':sorted(hits,key=lambda h:h['id']),'task_results':results,
        'counts':dict(Counter(h['kind'] for h in hits)),'pages_examined':len(pages),
        'assignments_examined':assignments,'budgets':{'max_pages':max_pages,'max_hits':max_hits,'max_assignments':max_assignments},
        'world_geometry_additions':0,'geometry_export_authorized':False,
        'limitations':['Text matches are discovery leads, not visible annotations or measurements.',
            'Source application membership does not establish physical area, project or object correspondence.',
            'Existing/proposed claims stay explicit; none establishes current as-built condition.',
            'Missing text matches do not prove that a raster drawing or unlabelled source lacks the evidence.']}


def run(corpus, queue_directory, output, *, benchmark_archive=None):
    queue_directory=Path(queue_directory);output=Path(output)
    queue_path=queue_directory/'missing-evidence.json'
    queue_report=json.loads((queue_directory/'queue-report.json').read_text())
    queue_pin=file_hash(queue_path)
    if queue_pin!=queue_report['output_sha256']:raise ValueError('Requirement queue output changed')
    queue=json.loads(queue_path.read_text());documents={};pending=[]
    for url,sha,status,raw in corpus.db.execute('SELECT d.url,l.sha,l.status,d.record FROM documents d JOIN downloads l ON d.url=l.url ORDER BY d.id'):
        record=json.loads(raw)
        link={'url':url,'title':record.get('title',''),'application_reference':record.get('applicationReference',record.get('application_reference')),
            'declared_state':record.get('state','unknown')}
        if status=='downloaded':
            row=documents.setdefault(sha,{'sha256':sha,'path':str(corpus.root/'files'/f'{sha}.pdf'),'source_links':[]})
            if link not in row['source_links']:row['source_links'].append(link)
        else:pending.append({**link,'download_status':status})
    for d in documents.values():
        if file_hash(d['path'])!=d['sha256']:raise ValueError('Retained matching source changed')
        d['source_links'].sort(key=lambda r:json.dumps(r,sort_keys=True))
    inventory=[{'sha256':d['sha256'],'source_links':d['source_links']} for _,d in sorted(documents.items())]
    from .benchmark_label_evidence import VERSION as benchmark_version
    from .glyph_visibility import VERSION as glyph_version, INK_VERSION as ink_version
    contract={'version':VERSION,'benchmark_label_version':benchmark_version,'glyph_version':glyph_version,'glyph_ink_version':ink_version,'requirement_queue_sha256':queue_pin,'inventory':inventory,'pending':pending}
    if benchmark_archive is not None:
        if file_hash(benchmark_archive['file'])!=benchmark_archive['sha256']:raise ValueError('Benchmark archive input changed')
        from .benchmark_archive_matching import VERSION as archive_version
        contract['benchmark_archive']={k:benchmark_archive[k] for k in ('sha256','search_bounds_bng')}
        contract['benchmark_archive_version']=archive_version
    run_id=digest(contract);target=output/run_id
    if target.exists():
        report=json.loads((target/'matching-report.json').read_text())
        if report['contract']!=contract or file_hash(target/'source-matches.json')!=report['output_sha256']:
            raise ValueError('Retained evidence matches changed')
        return {**report,'run_pages':0,'reused_pages':report['pages_examined'],'run_id':run_id}
    results=match(queue,list(documents.values()))
    if benchmark_archive is not None and results['status']=='retained_source_leads_only':
        from .benchmark_archive_matching import review as review_archive
        results['benchmark_archive_review']=review_archive(results['benchmark_reviews'],benchmark_archive['file'],benchmark_archive['sha256'],benchmark_archive['search_bounds_bng'])
    results['unavailable_document_leads']=[{**r,'candidate_requirement_kinds':sorted(k for k,rx in REGEX.items() if rx.search(r['title']))}
        for r in pending]
    if file_hash(queue_path)!=queue_pin:raise ValueError('Requirement queue changed during matching')
    if benchmark_archive is not None and file_hash(benchmark_archive['file'])!=benchmark_archive['sha256']:
        raise ValueError('Benchmark archive changed during matching')
    for d in documents.values():
        if file_hash(d['path'])!=d['sha256']:raise ValueError('Retained matching source changed')
    target.mkdir(parents=True)
    atomic_json(target/'source-matches.json',results)
    report={'contract':contract,'status':results['status'],'counts':results.get('counts',{}),
        'pages_examined':results.get('pages_examined',0),'candidate_hits':len(results['hits']),
        'tasks_with_retained_leads':sum(r['status']=='candidate_sources_found' for r in results['task_results']),
        'tasks_with_related_text_only':sum(r['status']=='related_text_only' for r in results['task_results']),
        'tasks_without_retained_leads':sum(r['status']=='no_retained_text_lead' for r in results['task_results']),
        'pending_documents':len(pending),'output_sha256':file_hash(target/'source-matches.json'),
        'world_geometry_additions':0,'requirements_resolved':0}
    atomic_json(target/'matching-report.json',report)
    return {**report,'run_pages':report['pages_examined'],'reused_pages':0,'run_id':run_id}
