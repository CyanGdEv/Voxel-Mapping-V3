"""Read public OSM features as cited clues for planning-application research."""
import argparse
from collections import Counter
from concurrent.futures import CancelledError
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import time
from urllib.parse import quote, urlencode
import xml.etree.ElementTree as ET

import requests
from . import web_evidence as web, web_research, web_focus
from .desktop_memory import digest
from .generation_cycles import atomic_json, file_hash

VERSION='map-planning-research-v1'
API='https://api.openstreetmap.org/api/0.6/map'
MAX_BYTES=16000000
TAGS={'name','name:en','alt_name','old_name','loc_name','official_name','attraction','roller_coaster',
      'tourism','leisure','building','building:part','amenity','shop','highway','area:highway','place',
      'natural','waterway','operator','brand','website','contact:website','wikidata','wikipedia',
      'ref:planning','planning:reference','start_date','opening_date','layer','bridge','tunnel','covered',
      'source','addr:city','addr:street','addr:postcode'}
HINTS={'ride':'ride layout planning application','building':'building floor plan planning application',
       'facility':'site plan planning application','path':'landscape paving plan planning application',
       'area':'landscape site plan planning application'}


def validate_source(source):
    if not isinstance(source,dict) or set(source)-{'bounds_wgs84','snapshot_path','snapshot_sha256','offline'}:
        raise ValueError('Known map source settings required')
    b=source.get('bounds_wgs84')
    if (not isinstance(b,list) or len(b)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in b)
            or not -180<=b[0]<b[2]<=180 or not -90<b[1]<b[3]<90
            or b[2]-b[0]>.05 or b[3]-b[1]>.05):
        raise ValueError('Small finite WGS84 map bounds [west,south,east,north] required')
    if type(source.get('offline',False)) is not bool:raise ValueError('Explicit offline map setting required')
    if 'snapshot_path' in source:
        if not isinstance(source['snapshot_path'],str) or not source['snapshot_path'] or not re.fullmatch('[0-9a-f]{64}',source.get('snapshot_sha256','')):
            raise ValueError('Local map snapshot requires its SHA256 pin')
    elif 'snapshot_sha256' in source:raise ValueError('Map pin requires a snapshot path')
    return b


def validate(config):
    if not isinstance(config,dict) or config.get('version')!=VERSION or set(config)-{
        'version','site_id','site','location','map_source','planning_hosts','applications','max_queries','max_research_jobs','research','focus_names'}:
        raise ValueError('Versioned mapping research configuration required')
    if not isinstance(config.get('site_id'),str) or not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}',config['site_id']):
        raise ValueError('Bounded public site identifier required')
    web_focus.profile({'site':config.get('site'),'location':config.get('location',''),'applications':config.get('applications',[])})
    web_focus.profile({'site':config['site'],'tags':config.get('focus_names',[])})
    validate_source(config.get('map_source'))
    hosts=config.get('planning_hosts',[])
    if hosts:web.hosts(hosts)
    elif not isinstance(hosts,list):raise ValueError('Planning hosts must be a list')
    for field,default,low,high in [('max_queries',24,1,32),('max_research_jobs',0,0,6)]:
        value=config.get(field,default)
        if type(value) is not int or not low<=value<=high:raise ValueError('Bounded map research jobs/queries required')
    settings=config.get('research',{})
    if not isinstance(settings,dict) or set(settings)-{'allowed_hosts','allow_public_discovery','model','endpoint','model_options','offline','refresh','limits'}:
        raise ValueError('Known web research settings required')
    web_research.validate({'version':web_research.VERSION,'query':'public map research',**settings})


def _check(cancelled,deadline):
    if cancelled():raise CancelledError('Map research cancelled')
    if time.monotonic()>=deadline:raise web.WebError('deadline','Map research deadline reached')


def acquire(source, cache, *, cancelled, deadline, budget):
    bounds=validate_source(source);url=API+'?'+urlencode({'bbox':','.join(map(str,bounds))})
    root=Path(cache)/'maps'/digest({'url':url});root.mkdir(parents=True,exist_ok=True)
    path=root/'osm.xml';receipt=root/'receipt.json'
    _check(cancelled,deadline)
    if 'snapshot_path' in source:
        path=Path(source['snapshot_path'])
        if not path.is_file() or path.stat().st_size>MAX_BYTES or file_hash(path)!=source['snapshot_sha256']:
            raise ValueError('Pinned local map snapshot changed or exceeded budget')
        return path,{'source_url':url,'body_sha256':file_hash(path),'retrieval':'pinned_local_snapshot',
            'bounds_wgs84':bounds,'bytes':path.stat().st_size,'retrieved_at_utc':None,'license':'ODbL-1.0',
            'attribution':'© OpenStreetMap contributors','local_snapshot_bounds_verified':False}
    if receipt.exists():
        record=json.loads(receipt.read_text())
        if record.get('source_url')!=url or not path.is_file() or path.stat().st_size>MAX_BYTES or file_hash(path)!=record['body_sha256']:
            raise ValueError('Retained map snapshot changed')
        return path,{**record,'retrieval':'cached'}
    if source.get('offline'):raise web.WebError('offline_cache_miss','No retained map snapshot for these bounds')
    # Fixed official API, public DNS, no credentials/cookies, no redirects.
    web._public_dns(url,web.socket.getaddrinfo)
    data=bytearray()
    with requests.Session() as client:
        with client.get(url,headers={'User-Agent':'VoxelMapperV3 public map research','Accept':'application/xml'},
                auth=web._NoOriginAuth(),stream=True,allow_redirects=False,
                timeout=(min(5,max(.1,deadline-time.monotonic())),min(15,max(.1,deadline-time.monotonic())))) as response:
            if response.status_code!=200:raise web.WebError('map_http_status','Official map API did not return 200',http_status=response.status_code)
            for chunk in response.iter_content(65536):
                _check(cancelled,deadline);budget.take(len(chunk));data.extend(chunk)
                if len(data)>MAX_BYTES:raise ValueError('Map snapshot byte budget exceeded')
    # Check syntax before committing a reusable snapshot.
    _xml(bytes(data));temporary=root/'osm.xml.partial';temporary.write_bytes(data);temporary.replace(path)
    record={'source_url':url,'body_sha256':file_hash(path),'retrieval':'network','bounds_wgs84':bounds,
        'bytes':len(data),'retrieved_at_utc':datetime.now(timezone.utc).isoformat(),'license':'ODbL-1.0',
        'attribution':'© OpenStreetMap contributors','local_snapshot_bounds_verified':True}
    atomic_json(receipt,record);return path,record


def _xml(raw):
    if len(raw)>MAX_BYTES:raise ValueError('Map snapshot byte budget exceeded')
    try:text=raw.decode('utf-8-sig')
    except UnicodeError as error:raise ValueError('UTF-8 OSM XML required') from error
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():raise ValueError('XML declarations/entities are not map data')
    root=ET.fromstring(text)
    if root.tag!='osm' or len(root)>100000:raise ValueError('Bounded official OSM XML required')
    return root


def analyse(raw, bounds, *, cancelled=lambda:False, deadline=None):
    deadline=deadline or time.monotonic()+60;root=_xml(raw);nodes={};items={};counts=Counter();seen=set()
    for item in root:
        _check(cancelled,deadline)
        if item.tag not in ('node','way','relation'):continue
        identifier=item.get('id','')
        if not re.fullmatch('[0-9]{1,20}',identifier):raise ValueError('Valid OSM identity required')
        key=(item.tag,identifier)
        if key in seen:raise ValueError('Duplicate OSM identity')
        seen.add(key);items[key]=item;counts[item.tag]+=1
        if item.tag=='node':
            lon=float(item.attrib['lon']);lat=float(item.attrib['lat'])
            if not math.isfinite(lon+lat) or not -180<=lon<=180 or not -90<=lat<=90:raise ValueError('Finite map coordinates required')
            nodes[identifier]=(lon,lat)
    def points(item):
        if item.tag=='node':return [nodes[item.get('id')]]
        if item.tag=='way':return [nodes[n.get('ref')] for n in item.findall('nd') if n.get('ref') in nodes]
        # One relation level: do not infer geometry from missing or cyclic members.
        result=[]
        for m in item.findall('member')[:1024]:
            member=items.get((m.get('type'),m.get('ref')))
            if member is not None and member.tag!='relation':result.extend(points(member))
        return result
    features=[];tag_counts=Counter();unlocated=0;outside=0
    for (kind,identifier),item in items.items():
        _check(cancelled,deadline)
        all_tags=item.findall('tag')
        if len(all_tags)>256:raise ValueError('Map feature tag budget exceeded')
        tags={t.get('k'):t.get('v') for t in all_tags if t.get('k') in TAGS}
        if any(not isinstance(v,str) or len(v)>2048 or any(ord(c)<32 for c in v) for v in tags.values()):
            raise ValueError('Bounded literal map tags required')
        tag_counts.update(tags.keys())
        names=[]
        for field in ['name','name:en','official_name','alt_name','old_name','loc_name']:
            for name in tags.get(field,'').split(';')[:8]:
                name=name.strip()
                if name and len(name)<=128 and name not in [r['text'] for r in names]:names.append({'text':name,'tag':field})
        if not names:continue
        category=('ride' if tags.get('attraction') or tags.get('roller_coaster') else
            'building' if tags.get('building','no')!='no' or tags.get('building:part','no')!='no' else
            'facility' if tags.get('amenity') or tags.get('shop') else
            'path' if tags.get('highway') or tags.get('area:highway') else
            'area' if tags.get('place') or tags.get('leisure') or tags.get('tourism') else None)
        if not category:continue
        coords=points(item)
        inside=[p for p in coords if bounds[0]<=p[0]<=bounds[2] and bounds[1]<=p[1]<=bounds[3]]
        if not coords:unlocated+=1;continue
        if not inside:outside+=1;continue
        links=[]
        for field in ['website','contact:website']:
            try:target=web.url(tags.get(field,''))
            except ValueError:continue
            links.append({'url':target,'tag':field})
        if re.fullmatch('Q[1-9][0-9]*',tags.get('wikidata','')):
            links.append({'url':'https://www.wikidata.org/wiki/'+tags['wikidata'],'tag':'wikidata'})
        if re.fullmatch('[a-z-]{2,12}:.{1,200}',tags.get('wikipedia','')):
            lang,title=tags['wikipedia'].split(':',1)
            links.append({'url':'https://'+lang+'.wikipedia.org/wiki/'+quote(title.replace(' ','_'),safe=''),'tag':'wikipedia'})
        features.append({'id':'osm/'+kind+'/'+identifier,'map_url':'https://www.openstreetmap.org/'+kind+'/'+identifier,
            'category':category,'ride_type_hint':('coaster' if tags.get('roller_coaster') or tags.get('attraction')=='roller_coaster' else {'carousel':'carousel','log_flume':'water','river_rafting':'water','drop_tower':'tower'}.get(tags.get('attraction'),'unknown')),'names':names[:8],'tags':tags,'position_wgs84':list(inside[0]),
            'position_role':'in_bounds_member_point_not_surveyed_centroid','links':links,
            'version':item.get('version'),'timestamp':item.get('timestamp'),
            'physical_identity_verified':False,'planning_application_identity_verified':False})
    features.sort(key=lambda r:({'ride':0,'building':1,'facility':2,'area':3,'path':4}[r['category']],r['names'][0]['text'],r['id']))
    return {'features':features[:256],'feature_count':len(features),'features_truncated':len(features)>256,
        'element_counts':dict(counts),'tag_counts':dict(tag_counts),'unlocated_named_features':unlocated,
        'outside_bounds_named_features':outside}


def queries(config, features, source_pin, *, hint=None):
    tasks=[];seen=set()
    focus={n.casefold():i for i,n in enumerate(config.get('focus_names',[]))}
    ordered=sorted(features,key=lambda f:min((focus[n['text'].casefold()] for n in f['names'] if n['text'].casefold() in focus),default=100))
    for feature in ordered:
        for name in feature['names'][:3]:
            text=name['text'];key=text.casefold()
            if key in seen:continue
            seen.add(key)
            query=' '.join(filter(None,[config['site'],config.get('location',''),'"'+text.replace('"','')+'"',hint or HINTS[feature['category']],('site:'+config['planning_hosts'][0]) if config.get('planning_hosts') else '']))
            # Keep map names intact and explicitly scoped to the selected public site.
            if len(query)>300:continue
            tags=[text[:80],feature['category']+' plan']
            applications=list(config.get('applications',[]))
            for k in ['ref:planning','planning:reference']:
                v=feature['tags'].get(k)
                if v and len(v)<=80 and v not in applications:applications.append(v)
            task={'query':query,'site_id':config['site_id'],'feature_id':feature['id'],'feature_category':feature['category'],'ride_type_hint':feature['ride_type_hint'],
                'name_tag':name['tag'],'source_body_sha256':source_pin,'source_map_url':feature['map_url'],
                'research_profile':{'site':config['site'],'location':config.get('location',''),'tags':tags,
                    'applications':applications[:8]},'seed_urls':[r['url'] for r in feature['links']][:4],
                'planning_hosts':config.get('planning_hosts',[]),'planning_application_identity_verified':False}
            task['id']=digest(task);tasks.append(task)
    # Reserve search slots for buildings/facilities/areas/paths as well as rides.
    # Focused feature names and their former names stay first.
    focused=[t for t in tasks if any(f['id']==t['feature_id'] and any(n['text'].casefold() in focus for n in f['names']) for f in ordered)]
    remaining=[t for t in tasks if t not in focused];selected=list(focused)
    queues={category:[t for t in remaining if t['feature_category']==category] for category in HINTS}
    while any(queues.values()):
        for category in HINTS:
            if queues[category]:selected.append(queues[category].pop(0))
    return selected[:config.get('max_queries',24)]



def document_clues(report, cache, *, cancelled=lambda:False, deadline=None):
    """Retain literal project codes/references from fetched originals, never invent aliases."""
    from bs4 import BeautifulSoup
    deadline=deadline or time.monotonic()+60
    clues=[]
    for source in report['sources']:
        _check(cancelled,deadline)
        receipt=web.cached(source['url'],cache,None)
        if not receipt or receipt['body_sha256']!=source['body_sha256']:continue
        path=web._body_path(Path(cache),receipt)
        if receipt['format']=='html':
            soup=BeautifulSoup(path.read_bytes(),'html.parser')
            for element in soup(['script','style','template','noscript']):element.decompose()
            text=soup.get_text(' ',strip=True)[:2000000]
        else:
            text=receipt['text']
            focused=next((v for v in report.get('focused_source_views',[]) if v['citation_id']==receipt['citation_id']),None)
            if focused:text=focused['text']
        _check(cancelled,deadline)
        if file_hash(path)!=receipt['body_sha256']:raise ValueError('Research original changed during clue extraction')
        for kind,pattern in [('application_reference',r'\b(?:SMD/\d{4}/\d{3,6}|RU[./]\d{2,4}[/_]\d{3,6}[A-Z]?)\b'),
                ('project_codename',r'\b(?:SW[0-9]{1,2}|Secret Weapon [0-9]{1,2}|Project [A-Z][A-Za-z-]{2,30})\b')]:
            seen=set()
            for match in re.finditer(pattern,text):
                if match[0] in seen:continue
                seen.add(match[0]);clues.append({'kind':kind,'text':match[0],
                    'source_url':receipt['url'],'source_body_sha256':receipt['body_sha256'],
                    'citation_id':receipt['citation_id'],'literal_witness':text[max(0,match.start()-80):match.end()+100],
                    'identity_verified':False})
                if len(seen)>=8:break
    return clues[:32]


def followups(config, parent, clues):
    tasks=[]
    for clue in clues[:8]:
        query=' '.join(filter(None,[config['site'],config.get('location',''),'"'+clue['text']+'"',
            'planning application drawings',('site:'+config['planning_hosts'][0]) if config.get('planning_hosts') else '']))
        if len(query)>300:continue
        task={**parent,'query':query,'seed_urls':[],
            'research_profile':{**parent['research_profile'],'tags':[clue['text'],*parent['research_profile']['tags']][:16]},
            'document_clue':clue}
        task['id']=digest({k:v for k,v in task.items() if k!='id'});tasks.append(task)
    return tasks


def run(config, output, cache, *, cancelled=lambda:False, progress=lambda v:None, parent_budget=None, run_deadline=None, fetch=None, research=None):
    validate(config);output=Path(output)
    if output.exists():raise ValueError('Fresh map research output required')
    deadline=min(time.monotonic()+600,run_deadline or float('inf'));budget=web.Budget(64000000,parent=parent_budget)
    output.mkdir(parents=True);atomic_json(output/'config.json',config)
    progress({'progress':.05,'message':'Reading named map features and public tags'})
    path,receipt=(fetch or acquire)(config['map_source'],cache,cancelled=cancelled,deadline=deadline,budget=budget)
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=receipt['body_sha256']:raise ValueError('Map snapshot changed before analysis')
    data=analyse(raw,config['map_source']['bounds_wgs84'],cancelled=cancelled,deadline=deadline)
    shutil.copy2(path,output/'osm.xml')
    if file_hash(output/'osm.xml')!=receipt['body_sha256']:raise ValueError('Map snapshot changed while retaining evidence')
    tasks=queries(config,data['features'],receipt['body_sha256']);results=[];failures=[];clues=[]
    pending=list(tasks);attempted=set();query_keys={t['query'] for t in tasks}
    while pending and len(results)+len(failures)<config.get('max_research_jobs',0):
        task=pending.pop(0)
        if task['query'] in attempted:continue
        attempted.add(task['query'])
        _check(cancelled,deadline)
        settings=config.get('research',{});approved=settings.get('allowed_hosts',config.get('planning_hosts') or list(web.DEFAULT_HOSTS))
        request={'version':web_research.VERSION,**settings,'allowed_hosts':approved,'query':task['query'],
            'research_profile':task['research_profile'],'urls':task['seed_urls'] if settings.get('allow_public_discovery') else [],
            'prompt':'Find original planning applications/drawings for '+task['query']+'. Treat map names, aliases and tags as unverified search clues.'}
        try:
            result=(research or web_research.run)(request,output/('research-'+task['id'][:12]),cache,
                cancelled=cancelled,progress=progress,parent_budget=budget,run_deadline=deadline)
            results.append({'task_id':task['id'],'query':task['query'],'status':result['status'],'sources':result['sources']})
            discovered=document_clues(result,cache,cancelled=cancelled,deadline=deadline);clues.extend(discovered)
            follow=[t for t in followups(config,task,discovered) if t['query'] not in query_keys]
            for t in follow:query_keys.add(t['query'])
            tasks.extend(follow);pending=follow+pending
        except (web.WebError,ValueError) as error:failures.append({'task_id':task['id'],'error':str(error)})
    source={'url':receipt['source_url'],'body_sha256':receipt['body_sha256'],'citation_id':'M'+receipt['body_sha256'][:12],
        'source_evidence_verified':False,'training_labels_generated':0}
    result={'version':VERSION,'status':'map_clues_extracted','site_id':config['site_id'],'site':config['site'],
        'location':config.get('location',''),'snapshot':receipt,**data,'queries':tasks,'document_clues':clues,'research_results':results,
        'research_failures':failures,'sources':[source]+[s for r in results for s in r['sources']],
        'network_bytes':budget.spent,'model_weights_updated':False,'training_labels_generated':0,
        'world_blocks_generated':0,'production_eligible':False,'limitations':[
            'OpenStreetMap names/tags and former names are public research clues, not verified plan identity or geometry.',
            'Only features with a retained member point within the requested bounds are included; missing/outside members remain gaps.',
            'At most 256 features, 32 initial queries and eight follow-ups per completed web job; one relation level; no proprietary tile/image scraping.',
            'Map dates/layers are not track heights; external links and application references remain unverified.']}
    atomic_json(output/'report.json',result);return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['config','output','cache']:p.add_argument('--'+name,required=True)
    args=p.parse_args(argv);path=Path(args.config).resolve();config=json.loads(path.read_text())
    if 'snapshot_path' in config.get('map_source',{}):config['map_source']['snapshot_path']=str((path.parent/config['map_source']['snapshot_path']).resolve())
    print(json.dumps(run(config,args.output,args.cache)))


if __name__=='__main__':main()
