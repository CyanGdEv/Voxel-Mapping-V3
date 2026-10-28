"""Training-coverage-directed research with persistent source and checkpoint memory."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sqlite3
import time

from . import study_component_learning as reader
from . import study_transfer_learning as transfer
from . import web_research, web_focus, web_evidence as web, map_planning_research as maps
from .desktop_memory import digest
from .generation_cycles import atomic_json, file_hash

VERSION='research-learning-cycle-v1'
TAGS={
    'ride_track_centreline':['track centreline','ride layout','dimensioned plan'],
    'ride_support_footprint':['support foundation plan','footing positions','ride survey'],
    'ride_support_crossline':['support frame plan','track supports','engineering drawing'],
    'ride_structure_trace':['ride support structure','diagonal braces','measured drawing'],
    'ride_track_profile':['track elevation','ride sections','height datum'],
    'ride_track_layout_trace':['roller coaster layout','track plan','engineering drawing'],
    'building':['building footprint','floor plan','survey'],
    'path':['paving layout','path boundaries','landscape plan'],
    'plaza':['courtyard plan','paving boundaries','landscape plan']}


def curriculum(rows, sites, errors=None):
    """Queries use explicit public site metadata and component taxonomy only."""
    groups=defaultdict(set);owners=defaultdict(set);counts=Counter()
    for row in rows:
        groups[row['kind']].add(row['group_id']);owners[row['kind']].add(row.get('site_id',''));counts[row['kind']]+=1
    tasks=[]
    for kind in sorted(groups,key=lambda k:(len(groups[k]),-float((errors or {}).get(k,0)),k)):
        candidates=[s for s in sites if not kind.startswith(('ride_track','ride_support')) or 'coaster' in s.get('ride_types',[])]
        candidates.sort(key=lambda s:(s['site_id'] in owners[kind],s['site_id']))
        tags=TAGS.get(kind,[kind.replace('_',' '),'measured drawing','planning application'])
        for site in candidates:
            query=' '.join([site['name'],site.get('location',''),tags[0],tags[1]])[:300]
            profile={'site':site['name'],'location':site.get('location',''),'tags':tags,
                'applications':site.get('applications',[]),'exclude_tags':site.get('exclude_tags',[])}
            web_focus.profile(profile)
            task={'kind':kind,'source_groups':len(groups[kind]),'examples':counts[kind],
                'additional_groups_requested':max(0,3-len(groups[kind])),
                'measured_error_priority':float((errors or {}).get(kind,0)),
                'site_id':site['site_id'],'query':query,'research_profile':profile,
                'seed_urls':site.get('urls',[]),
                'reason':'Seek the same component on independent rides/sources; supplied-crop variants are not new evidence.'}
            task['id']=digest(task);tasks.append(task)
    return tasks


def validate(config):
    if (not isinstance(config,dict) or config.get('version')!=VERSION
            or set(config)-{'version','dataset_directory','encoder_path','encoder_sha256','dataset_manifest_sha256',
                'public_sites','research','max_research_jobs','refresh_research','aerial_semantics'}):
        raise ValueError('Versioned research-learning cycle configuration required')
    for key in ['dataset_directory','encoder_path']:
        if not isinstance(config.get(key),str) or not config[key]:raise ValueError('Existing dataset and registered encoder paths required')
    if not reader._hash(config.get('encoder_sha256')):raise ValueError('Registered encoder pin required')
    sites=config.get('public_sites')
    if not isinstance(sites,list) or not 1<=len(sites)<=16:raise ValueError('One to sixteen explicit public site profiles required')
    if any(not isinstance(s,dict) for s in sites):raise ValueError('Public site profiles must be objects')
    identities=[s.get('site_id') for s in sites]
    if any(not isinstance(i,str) for i in identities) or len(set(identities))!=len(sites):
        raise ValueError('Unique public site identities required')
    for site in sites:
        if not isinstance(site,dict) or set(site)-{'site_id','name','location','applications','exclude_tags','ride_types','urls','map_context','planning_hosts','map_focus_names','aerial_context','imagery_geometry_context'}:
            raise ValueError('Known public site profile fields required')
        reader._identifier(site.get('site_id'),'public site id')
        web_focus.profile({'site':site.get('name'),'location':site.get('location',''),
            'applications':site.get('applications',[]),'exclude_tags':site.get('exclude_tags',[])})
        types=site.get('ride_types',[])
        if not isinstance(types,list) or len(types)>16 or any(t not in ['coaster','carousel','water','flat','tower','transport'] for t in types):
            raise ValueError('Known ride-type research hints required')
        urls=site.get('urls',[])
        if not isinstance(urls,list) or len(urls)>12:raise ValueError('Bounded exact public site seed links required')
        for value in urls:web.url(value)
        if 'map_context' in site:maps.validate_source(site['map_context'])
        web_focus.profile({'site':site['name'],'tags':site.get('map_focus_names',[])})
        if site.get('planning_hosts'):web.hosts(site['planning_hosts'])
        if 'aerial_context' in site:
            from . import aerial_material_research as aerial
            if not isinstance(site['aerial_context'],dict):raise ValueError('Aerial context must be an object')
            aerial.validate({**site['aerial_context'],'version':aerial.VERSION,'site_id':site['site_id'],'site':site['name']})
    if sum('map_context' in site for site in sites)>4:raise ValueError('At most four map areas per learning cycle')
    for site in sites:
        if 'imagery_geometry_context' in site:
            from . import imagery_geometry_research as geometry
            geometry.validate(site['imagery_geometry_context'])
            if site['imagery_geometry_context']['site_id']!=site['site_id']:raise ValueError('Imagery geometry site identity changed')
    if sum('imagery_geometry_context' in s for s in sites)>2:raise ValueError('At most two imagery geometry areas per cycle')
    if sum('aerial_context' in s for s in sites)>2:raise ValueError('At most two aerial areas per learning cycle')
    if 'aerial_semantics' in config:
        spec=config['aerial_semantics']
        if not isinstance(spec,dict) or set(spec)-{'dataset_directory','settings','use_for_geometry'} or not isinstance(spec.get('dataset_directory'),str) or not spec['dataset_directory'] or type(spec.get('use_for_geometry',False)) is not bool:raise ValueError('Known aerial semantic dataset/settings required')
    maximum=config.get('max_research_jobs',2)
    if type(maximum) is not int or not 0<=maximum<=6 or type(config.get('refresh_research',False)) is not bool:
        raise ValueError('Bounded repeatable research cycle required')
    research=config.get('research',{})
    if not isinstance(research,dict) or set(research)-{'allowed_hosts','allow_public_discovery','model','endpoint','model_options','offline','refresh','limits','source_families'}:
        raise ValueError('Known web research transport/reasoning settings required')
    web_research.validate({'version':web_research.VERSION,'query':'public source research',**research})
    return sites,maximum,research


def run(config, output, memory_directory, cache, *, cancelled=lambda:False, progress=lambda value:None,
        research=None, trainer=None):
    sites,maximum,settings=validate(config);output=Path(output);memory_directory=Path(memory_directory)
    if output.exists():raise ValueError('Fresh research-learning output required')
    reader._check(cancelled)
    manifest,rows,_,pin=reader.read_dataset(config['dataset_directory'],cancelled=cancelled)
    if config.get('dataset_manifest_sha256',pin)!=pin:raise ValueError('Learning dataset manifest changed')
    # The standard reader refuses reserved evaluation rows; a cycle cannot
    # silently refit them into its checkpoint.
    from .study_pretrained_encoder import encoder_info
    encoder_info(config['encoder_path'],config['encoder_sha256'],allow_synthetic=manifest['dataset_kind'].startswith('synthetic'))
    if not 2<=len({r['kind'] for r in rows})<=16:raise ValueError('Two to sixteen reviewed learning classes required')
    output.mkdir(parents=True);memory_directory.mkdir(parents=True,exist_ok=True)
    atomic_json(output/'config.json',config)
    db=sqlite3.connect(memory_directory/'research-learning.sqlite3',timeout=30)
    db.executescript('CREATE TABLE IF NOT EXISTS checkpoints(key TEXT PRIMARY KEY, path TEXT, sha256 TEXT, report_sha256 TEXT);'
        'CREATE TABLE IF NOT EXISTS research_tasks(id TEXT PRIMARY KEY, query TEXT, source_count INTEGER);'
        'CREATE TABLE IF NOT EXISTS sources(sha256 TEXT PRIMARY KEY, url TEXT, citation TEXT);'
        'CREATE TABLE IF NOT EXISTS map_followups(id TEXT PRIMARY KEY, payload TEXT);')
    key=digest({'dataset_manifest_sha256':pin,'encoder_sha256':config['encoder_sha256'],'trainer':'frozen-feature-ridge-100-v1'})
    model_directory=memory_directory/'models'/key
    training_status='reused_unchanged_dataset_checkpoint'
    train=trainer or transfer.train;research=research or web_research.run
    try:
        db.execute('BEGIN IMMEDIATE')
        stored=db.execute('SELECT path,sha256,report_sha256 FROM checkpoints WHERE key=?',(key,)).fetchone()
        if stored:
            if Path(stored[0]).resolve()!=model_directory.resolve() or file_hash(model_directory/'model.json')!=stored[1] or file_hash(model_directory/'report.json')!=stored[2]:
                raise ValueError('Persisted research checkpoint changed')
        elif not model_directory.exists():
            progress({'progress':.05,'message':'Fitting source-backed learning heads for this dataset version'})
            train(config['dataset_directory'],model_directory,encoder_path=config['encoder_path'],
                encoder_sha256=config['encoder_sha256'],cancelled=cancelled)
            training_status='trained_new_dataset_checkpoint'
        model=transfer.load_model(model_directory/'model.json')
        report,_=reader._json(model_directory/'report.json',transfer.MAX_REPORT_BYTES)
        if model['dataset_file_sha256']!=pin or model['encoder_sha256']!=config['encoder_sha256']:
            raise ValueError('Checkpoint lineage does not match the current source dataset')
        db.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?,?,?)',(key,str(model_directory.resolve()),file_hash(model_directory/'model.json'),file_hash(model_directory/'report.json')))
        db.commit()
        errors={kind:1-float(row['recall']) for kind,row in report.get('cross_source_evaluation',{}).get('metrics',{}).get('per_class',{}).items() if row['support']}
        semantic_checkpoint=None
        if 'aerial_semantics' in config:
            from .aerial_semantic_learning import ensure_checkpoint
            spec=config['aerial_semantics']
            semantic_checkpoint=ensure_checkpoint(spec['dataset_directory'],memory_directory/'aerial-semantic-models',spec.get('settings'),cancelled=cancelled,progress=progress)
            atomic_json(output/'aerial-semantic-checkpoint.json',semantic_checkpoint)
        tasks=curriculum(rows,sites,errors)
        if semantic_checkpoint:
            semantic_tasks=[]
            hints={'paths_plazas':['pedestrian paving layout','landscape plan'],'building_roofs':['building roof plan','aerial building footprint'],
                'car_parks':['car park layout','parking plan'],'landscaped_islands':['planter grass island layout','landscape planting plan']}
            for metric in sorted(semantic_checkpoint['per_class'],key=lambda r:r['iou'] if r['iou'] is not None else 1):
                if metric['class'] not in hints:continue
                tags=hints[metric['class']]
                for site in sites:
                    task={'kind':'aerial_semantic_'+metric['class'],'site_id':site['site_id'],
                        'query':' '.join([site['name'],site.get('location',''),tags[0],tags[1]])[:300],
                        'research_profile':{'site':site['name'],'location':site.get('location',''),'tags':tags,'applications':site.get('applications',[])},
                        'seed_urls':site.get('urls',[]),'measured_error_priority':1-float(metric['iou'] or 0),
                        'semantic_dataset_sha256':semantic_checkpoint['dataset_sha256'],
                        'reason':'Seek evidence for weak RGB classes; downloaded media require source-linked annotation before fitting.'}
                    task['id']=digest(task);semantic_tasks.append(task)
            tasks=semantic_tasks+tasks
        completed={r[0] for r in db.execute('SELECT id FROM research_tasks WHERE source_count>0')}
        seen={r[0] for r in db.execute('SELECT sha256 FROM sources')}|set(model['training_sources'])
        deadline=time.monotonic()+600;budget=web.Budget(64_000_000);results=[];new=set();failures=[]
        map_reports=[];map_failures=[];map_tasks=[]
        mapped=[site for site in sites if 'map_context' in site]
        if len(mapped)>4:raise ValueError('At most four map areas per learning cycle')
        for site in mapped:
            reader._check(cancelled)
            try:
                context=maps.run({'version':maps.VERSION,'site_id':site['site_id'],'site':site['name'],
                    'location':site.get('location',''),'map_source':site['map_context'],
                    'planning_hosts':site.get('planning_hosts',[]),'applications':site.get('applications',[]),
                    'focus_names':site.get('map_focus_names',[]),'max_queries':32},
                    output/('map-'+site['site_id']),cache,cancelled=cancelled,progress=progress,
                    parent_budget=budget,run_deadline=deadline)
            except (web.WebError,ValueError,OSError) as error:
                map_failures.append({'site_id':site['site_id'],'error':str(error)});continue
            map_reports.append({'site_id':site['site_id'],'features':context['feature_count'],
                'queries':len(context['queries']),'source_body_sha256':context['snapshot']['body_sha256']})
            for source in context['sources']:
                body=source['body_sha256']
                if body not in seen:new.add(body)
                seen.add(body)
                db.execute('INSERT OR IGNORE INTO sources VALUES(?,?,?)',(body,source['url'],source['citation_id']))
            for base in [t for t in tasks if t['site_id']==site['site_id']]:
                selected=0
                for clue in context['queries']:
                    # Match map categories to the component being researched.
                    kind=base['kind'];category=clue['feature_category']
                    if kind.startswith('ride_') and category!='ride':continue
                    if kind.startswith(('ride_track','ride_support')) and clue['ride_type_hint']!='coaster':continue
                    if kind in ('building','door','window','wall','roof','roof_profile','roof_outline','building_footprint') and category not in ('building','facility'):continue
                    if kind in ('path','plaza') and category not in ('path','area'):continue
                    task={**base,'query':(clue['query']+' '+TAGS.get(kind,[kind])[0])[:300],
                        'seed_urls':list(dict.fromkeys(base['seed_urls']+clue['seed_urls']))[:12],
                        'research_profile':{**base['research_profile'],
                            'applications':list(dict.fromkeys(base['research_profile']['applications']+clue['research_profile']['applications']))[:8],
                            'tags':list(dict.fromkeys(clue['research_profile']['tags']+base['research_profile']['tags']))[:16]},
                        'map_clue':{k:clue[k] for k in ['feature_id','source_body_sha256','source_map_url','name_tag']}}
                    task['id']=digest({k:v for k,v in task.items() if k!='id'});map_tasks.append(task)
                    selected+=1
                    if selected>=4:break
            db.commit()
        aerial_reports=[];aerial_failures=[]
        for site in [s for s in sites if 'aerial_context' in s]:
            from . import aerial_material_research as aerial
            try:
                rgb=aerial.run({**site['aerial_context'],'version':aerial.VERSION,'site_id':site['site_id'],'site':site['name']},
                    output/('aerial-'+site['site_id']),cache,cancelled=cancelled,progress=progress,parent_budget=budget,run_deadline=deadline)
            except (web.WebError,ValueError,OSError) as error:
                aerial_failures.append({'site_id':site['site_id'],'error':str(error)});continue
            aerial_reports.append({'site_id':site['site_id'],'status':rgb['status'],'provider':rgb['provider'],
                'sample_cells':rgb['sample_cells'],'provisional_material_assignments':rgb.get('provisional_material_assignments',0),
                'colour_material_assignments':rgb.get('colour_material_assignments'),'candidate_file_sha256':rgb['candidate_file_sha256'],'material_assignments_accepted':0})
            for source in rgb['sources']:
                body=source['body_sha256']
                if body not in seen:new.add(body)
                seen.add(body);db.execute('INSERT OR IGNORE INTO sources VALUES(?,?,?)',(body,source['url'],source['citation_id']))
            db.commit()
        geometry_reports=[];geometry_failures=[]
        for site in [s for s in sites if 'imagery_geometry_context' in s]:
            from . import imagery_geometry_research as geometry
            try:
                context=json.loads(json.dumps(site['imagery_geometry_context']))
                if semantic_checkpoint and config['aerial_semantics'].get('use_for_geometry') and 'semantic_model' not in context:
                    context['semantic_model']={'file':semantic_checkpoint['model_file'],'sha256':semantic_checkpoint['model_sha256']}
                draft=geometry.run(context,output/('imagery-geometry-'+site['site_id']),cache,
                    cancelled=cancelled,progress=progress,parent_budget=budget,run_deadline=deadline)
            except (web.WebError,ValueError,OSError) as error:
                geometry_failures.append({'site_id':site['site_id'],'error':str(error)});continue
            geometry_reports.append({'site_id':site['site_id'],'candidate_counts':draft['candidate_counts'],
                'queue_reference_lines':draft['queue_reference_lines'],'candidate_file_sha256':draft['candidate_file_sha256'],
                'paving_file_sha256':draft.get('paving_file_sha256'),'paving_refinement':draft.get('paving_refinement'),
                'geometry_verified':False,'registration_verified':False,'learned_semantics':draft.get('learned_semantics')})
            for source in draft['sources']:
                body=source['body_sha256']
                if body not in seen:new.add(body)
                seen.add(body);db.execute('INSERT OR IGNORE INTO sources VALUES(?,?,?)',(body,source['url'],source['citation_id']))
            db.commit()
        pins={r['source_body_sha256'] for r in map_reports};active_sites={s['site_id'] for s in mapped}
        remembered=[]
        for (raw,) in db.execute('SELECT payload FROM map_followups ORDER BY rowid LIMIT 256'):
            item=json.loads(raw)
            if digest({k:v for k,v in item.items() if k!='id'})!=item.get('id'):
                raise ValueError('Remembered map research task changed')
            if item.get('map_clue',{}).get('source_body_sha256') in pins and item.get('site_id') in active_sites:
                remembered.append(item)
        tasks=remembered+map_tasks+tasks;atomic_json(output/'curriculum.json',tasks)
        task_queries={t['query'] for t in tasks};map_document_clues=[]
        for task in tasks:
            reader._check(cancelled)
            if len(results)+len(failures)>=maximum or time.monotonic()>=deadline or budget.exhausted:break
            if task['id'] in completed and not config.get('refresh_research',False):continue
            request={'version':web_research.VERSION,**settings,'query':task['query'],
                'urls':task['seed_urls'],
                'research_profile':task['research_profile'],'prompt':'Research '+task['query']+'. Find original source drawings/images and explain source coverage and remaining geometry evidence.'}
            progress({'progress':.2+.7*(len(results)+len(failures))/max(1,maximum),'message':'Researching missing evidence: '+task['query']})
            try:
                result=research(request,output/('research-'+task['id'][:12]),cache,
                    cancelled=cancelled,progress=progress,parent_budget=budget,run_deadline=deadline)
            except (web.WebError,ValueError) as error:
                failures.append({'task_id':task['id'],'error':str(error)});continue
            for source in result['sources']:
                body=source['body_sha256']
                if body not in seen:new.add(body)
                seen.add(body)
                db.execute('INSERT OR IGNORE INTO sources VALUES(?,?,?)',(body,source['url'],source['citation_id']))
            db.execute('INSERT OR REPLACE INTO research_tasks VALUES(?,?,?)',(task['id'],task['query'],len(result['sources'])))
            if 'map_clue' in task:
                discovered=maps.document_clues(result,cache,cancelled=cancelled,deadline=deadline);map_document_clues.extend(discovered)
                site=next(s for s in sites if s['site_id']==task['site_id'])
                follow=maps.followups({'site':site['name'],'location':site.get('location',''),
                    'planning_hosts':site.get('planning_hosts',[])},task,discovered)
                follow=[t for t in follow if t['query'] not in task_queries]
                for t in follow:
                    task_queries.add(t['query'])
                    if db.execute('SELECT count(*) FROM map_followups').fetchone()[0]<256:
                        db.execute('INSERT OR IGNORE INTO map_followups VALUES(?,?)',(t['id'],json.dumps(t,sort_keys=True)))
                at=tasks.index(task)+1;tasks[at:at]=follow
            db.commit();results.append({'task_id':task['id'],'query':task['query'],'sources':len(result['sources']),
                'status':result['status'],'output':'research-'+task['id'][:12]})
        atomic_json(output/'curriculum.json',tasks)
        summary={'version':VERSION,'status':'research_learning_cycle_completed','dataset_id':manifest['id'],
            'dataset_manifest_sha256':pin,'training_status':training_status,'checkpoint_directory':str(model_directory.resolve()),
            'checkpoint_sha256':file_hash(model_directory/'model.json'),'curriculum_tasks':len(tasks),
            'imagery_geometry_reports':geometry_reports,'imagery_geometry_failures':geometry_failures,
            'aerial_reports':aerial_reports,'aerial_failures':aerial_failures,'research_results':results,'research_failures':failures,'map_reports':map_reports,'map_failures':map_failures,'map_document_clues':map_document_clues,'remembered_map_followups':db.execute('SELECT count(*) FROM map_followups').fetchone()[0],'new_source_bodies':len(new),
            'remembered_sources':db.execute('SELECT count(*) FROM sources').fetchone()[0],
            'sources':[{'body_sha256':body,'url':url,'citation_id':citation,'source_evidence_verified':False,
                'training_labels_generated':0} for body,url,citation in db.execute('SELECT sha256,url,citation FROM sources ORDER BY sha256 LIMIT 64')],
            'network_bytes':budget.spent,'aerial_semantic_checkpoint':semantic_checkpoint,'source_pair_head_weights_updated':training_status=='trained_new_dataset_checkpoint',
            'model_weights_updated':training_status=='trained_new_dataset_checkpoint' or bool(semantic_checkpoint and semantic_checkpoint['model_weights_updated']),
            'encoder_weights_updated':False,'web_sources_automatically_labelled':0,'production_eligible':False,
            'world_blocks_generated':0,'limitations':['Research priorities learn from source-group coverage and measured errors; they are not physical verification.',
                'Unchanged dataset versions reuse checked checkpoints. New verified source-pair datasets trigger fitting automatically.',
                'Downloaded unlabelled media remain research candidates, not invented geometry supervision.',
                'Optional installed local reasoning model guides cited link-following; unavailable backends remain explicit.']}
        reader._check(cancelled);atomic_json(output/'report.json',summary)
        return summary
    finally:
        db.close()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ['config','output','memory','cache']:parser.add_argument('--'+key,required=True)
    args=parser.parse_args(argv);config,_=reader._json(Path(args.config),1_000_000)
    base=Path(args.config).resolve().parent
    for field in ['dataset_directory','encoder_path']:config[field]=str((base/config[field]).resolve())
    if 'aerial_semantics' in config:config['aerial_semantics']['dataset_directory']=str((base/config['aerial_semantics']['dataset_directory']).resolve())
    for site in config.get('public_sites',[]):
        if 'imagery_geometry_context' in site:
            from .imagery_geometry_research import resolve_paths
            site['imagery_geometry_context']=resolve_paths(site['imagery_geometry_context'],base)
        source=site.get('map_context',{})
        if 'snapshot_path' in source:source['snapshot_path']=str((base/source['snapshot_path']).resolve())
    print(json.dumps(run(config,args.output,args.memory,args.cache)))


if __name__=='__main__':main()
