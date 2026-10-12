"""Persistent survey-source leads and known-attachment acquisition priorities.

Native wording and catalogue titles select investigation targets, never controls.
No guessed attachment URLs, inferred CRS, geographic placement or training labels.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import pymupdf
from .generation_cycles import file_hash,atomic_json
from .survey_reference import inspect_reference_notes
from .survey_context import inspect_survey_context,VERSION as CONTEXT_VERSION

VERSION='survey-source-discovery-v1'
RULES={
 'station_table':r'\b(?:station|control point|point id)\b[^\n]{0,80}\b(?:easting|northing)\b',
 'coordinate_grid':r'\b(?:easting|northing)\b',
 'explicit_epsg':r'\bEPSG\s*[:=]?\s*\d{4,6}\b',
 'survey_title':r'\b(?:topograph(?:ic|ical)|land|measured|control)\s+survey\b',
 'georeferenced_title':r'\bgeo[- ]?referenced\b',
}
WEIGHTS={'station_table':8,'coordinate_grid':1,'explicit_epsg':8,'survey_title':6,'georeferenced_title':8,'referenced_survey':10}
REFERENCE=re.compile(r'\b(?:SURVEYS?\s+)?DRAWING\s*(?:NO\.?\s*)?:?\s*([A-Z0-9][A-Z0-9/-]{2,31})\s+(MASTER LAND SURVEY)\b',re.I)


def signals(text):
    if not isinstance(text,str) or len(text)>500000:raise ValueError('Bounded native survey source text required')
    notes=inspect_reference_notes(text);context=inspect_survey_context(text)
    matches=[name for name,pattern in RULES.items() if re.search(pattern,text,re.I)]
    citations=sorted({(m[1].upper(),m[2].upper()) for m in REFERENCE.finditer(re.sub(r'\s+',' ',text))})
    if len(citations)>64:raise ValueError('Survey drawing citation budget exceeded')
    if citations:matches.append('referenced_survey')
    return {'signals':matches,'priority_score':sum(WEIGHTS[m] for m in matches),
            'drawing_references':[{'drawing_number':number,'title':title} for number,title in citations],
            'survey_context':context,'reference_notes':notes,'visibility_verified':False,
            'registration_verified':False,'world_geometry_additions':0}


def catalogue_queue(records,observations,statuses,*,max_priorities=128):
    if type(max_priorities) is not int or not 1<=max_priorities<=128:raise ValueError('Priority limit must be 1..128')
    if len(records)>10000 or len(observations)>10000:raise ValueError('Survey source input budget exceeded')
    by_url={};by_sha={};references=[];drawing_index={}
    for row in observations:
        by_sha.setdefault(row['document_sha256'],[]).append(row)
        for reference in row.get('drawing_references',[]):
            references.append({**reference,'source_document_sha256':row['document_sha256'],'source_page':row['page']})
    if len(references)>10000:raise ValueError('Survey reference queue budget exceeded')
    for record in records:
        url=record['url'];title=str(record.get('title',record.get('attachment_label','')))
        if len(title)>2000:raise ValueError('Catalogue title budget exceeded')
        evidence=signals(title)
        identifiers=set(re.findall(r'[A-Za-z0-9]+(?:[/-][A-Za-z0-9]+)*',title.upper()))
        if record.get('drawing_number'):identifiers.add(str(record['drawing_number']).upper())
        for identifier in identifiers:drawing_index.setdefault(identifier,set()).add(url)
        status=statuses[url]
        reasons=[{'kind':'catalogue_title','signals':evidence['signals'],'priority_score':evidence['priority_score']}]
        page_signals=[r for r in by_sha.get(status.get('sha'),[]) if r.get('signals')]
        for page in page_signals:reasons.append({'kind':'native_page_text','page':page['page'],'signals':page['signals'],'priority_score':page['priority_score']})
        score=max([evidence['priority_score']]+[r['priority_score'] for r in page_signals])
        item=by_url.setdefault(url,{'url':url,'titles':[],'application_references':[],
            'acquisition_status':status['status'],'document_sha256':status.get('sha'),
            'priority_score':0,'reasons':[],'registration_verified':False})
        item['titles'].append(title);item['application_references'].append(str(record.get('applicationReference',record.get('application_reference','')) or ''))
        item['priority_score']=max(item['priority_score'],score);item['reasons'].extend(reasons)
    resolved=[]
    for reference in references:
        number=reference['drawing_number'];matches=sorted(drawing_index.get(number,set()))
        resolved.append({**reference,'catalogue_urls':matches,'status':'unresolved_reference' if not matches else
            'ambiguous_catalogue_candidates' if len(matches)>1 else 'catalogue_candidate_only',
            'search_terms':reference['title']+' '+number,'registration_verified':False})
        for url in matches:
            by_url[url]['priority_score']=max(by_url[url]['priority_score'],10)
            by_url[url]['reasons'].append({'kind':'printed_drawing_reference','source_document_sha256':reference['source_document_sha256'],
                'source_page':reference['source_page'],'drawing_number':number,'identity_verified':False})
    candidates=[]
    for item in by_url.values():
        if item['priority_score']<3:continue
        item['titles']=sorted(set(item['titles']));item['application_references']=sorted(set(item['application_references']))
        item['reasons']=sorted({json.dumps(r,sort_keys=True) for r in item['reasons']})
        item['reasons']=[json.loads(r) for r in item['reasons']]
        candidates.append(item)
    candidates.sort(key=lambda r:(-r['priority_score'],r['url']))
    priorities=[r['url'] for r in candidates if r['acquisition_status']!='downloaded'][:max_priorities]
    return {'candidates':candidates,'drawing_references':resolved,'priority_urls':priorities,
        'unresolved_references':sum(r['status']=='unresolved_reference' for r in resolved),
        'registration_verified':False,'accepted_controls':0,'accepted_checkpoints':0,'world_geometry_additions':0}


def run(corpus,output,*,max_pages=1000,max_priorities=128):
    if type(max_pages) is not int or not 1<=max_pages<=10000:raise ValueError('Page budget must be 1..10000')
    if type(max_priorities) is not int or not 1<=max_priorities<=128:raise ValueError('Priority limit must be 1..128')
    rows=corpus.db.execute('SELECT url,record FROM documents ORDER BY id LIMIT 10001').fetchall()
    if len(rows)>10000:raise ValueError('Catalogue document budget exceeded')
    records=[json.loads(raw) for _,raw in rows]
    statuses={url:{'status':status,'sha':sha} for url,status,sha in corpus.db.execute('SELECT url,status,sha FROM downloads')}
    contract=hashlib.sha256(json.dumps({'version':VERSION,'context_version':CONTEXT_VERSION},sort_keys=True).encode()).hexdigest()
    corpus.db.execute('CREATE TABLE IF NOT EXISTS survey_source_pages(sha TEXT,page INTEGER,contract TEXT,result TEXT,PRIMARY KEY(sha,page,contract))')
    observations=[];computed=reused=0;errors=[];deferred=0
    shas=sorted({v['sha'] for v in statuses.values() if v['status']=='downloaded' and v['sha']})
    for index,sha in enumerate(shas):
        if len(observations)>=max_pages:deferred=len(shas)-index;break
        if not re.fullmatch('[0-9a-f]{64}',sha):raise ValueError('Pinned survey source hash required')
        path=corpus.root/'files'/(sha+'.pdf')
        if file_hash(path)!=sha:raise ValueError('Survey source checksum mismatch')
        try:
            with pymupdf.open(path) as pdf:
                if len(pdf)>1000:raise ValueError('PDF page inventory budget exceeded')
                for page in range(len(pdf)):
                    if len(observations)>=max_pages:deferred=len(shas)-index;break
                    cached=corpus.db.execute('SELECT result FROM survey_source_pages WHERE sha=? AND page=? AND contract=?',(sha,page+1,contract)).fetchone()
                    if cached:result=json.loads(cached[0]);reused+=1
                    else:
                        result={'document_sha256':sha,'page':page+1,**signals(pdf[page].get_text()),'status':'native_survey_source_leads_only'}
                        if file_hash(path)!=sha:raise ValueError('Survey source changed during inspection')
                        with corpus.db:corpus.db.execute('INSERT INTO survey_source_pages VALUES(?,?,?,?)',(sha,page+1,contract,json.dumps(result,sort_keys=True)))
                        computed+=1
                    observations.append(result)
        except Exception as error:errors.append({'document_sha256':sha,'reason':str(error)[:256]})
        if file_hash(path)!=sha:raise ValueError('Survey source changed during inspection')
    queue=catalogue_queue(records,observations,statuses,max_priorities=max_priorities)
    report={'version':VERSION,'page_contract':contract,'status':'survey_source_leads_only','pages':len(observations),
        'run_pages':computed,'reused_pages':reused,'max_pages':max_pages,'deferred_documents':deferred,'errors':errors,
        'native_signal_counts':dict(Counter(s for r in observations for s in r['signals'])),
        'page_observations':observations,**queue}
    report['inputs_sha256']=hashlib.sha256(json.dumps({'records':records,'statuses':statuses},sort_keys=True).encode()).hexdigest()
    output=Path(output);output.mkdir(parents=True,exist_ok=True);atomic_json(output/'survey-source-queue.json',report)
    return report


def main():
    from .planning_bulk import Corpus
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--max-pages',type=int,default=1000);args=parser.parse_args();corpus=Corpus(args.corpus)
    try:
        report=run(corpus,args.output,max_pages=args.max_pages)
        print(json.dumps({k:report[k] for k in ('pages','run_pages','reused_pages','priority_urls','unresolved_references','native_signal_counts')}))
    finally:corpus.close()

if __name__=='__main__':main()
