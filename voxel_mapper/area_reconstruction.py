"""Planning-led resort areas; spatial chunk cycles are a downstream work budget."""
import argparse
import hashlib
import json
import re
import shutil
import sqlite3
from pathlib import Path
from .generation_cycles import CyclePlan, atomic_json, file_hash
from .planning_bulk import Corpus
from .reconstruction.park_generators import FAMILY_ALIASES

VERSION='resort-area-reconstruction-v12'


def select_documents(catalogue, area):
    references=set(area['application_references'])
    return [r for r in catalogue['entries']
            if r.get('applicationReference',r.get('application_reference')) in references]


def referenced_plan_hashes(value):
    """Only explicit planning-document provenance fields count as plan bindings."""
    found=set()
    if isinstance(value,dict):
        for key,item in value.items():
            if key in ('document_sha256','planning_document_sha256','source_pdf_sha256') and isinstance(item,str):found.add(item)
            elif key=='planning_document_sha256s' and isinstance(item,list):found.update(item)
            else:found.update(referenced_plan_hashes(item))
    elif isinstance(value,list):
        for item in value:found.update(referenced_plan_hashes(item))
    return found


def compiled_coverage(geometry, plan_hashes):
    """Replay snapshots cannot masquerade as planning-led area reconstruction."""
    db=sqlite3.connect(geometry)
    try:
        contract=json.loads(db.execute("SELECT value FROM metadata WHERE key='contract'").fetchone()[0])
        if contract.get('snapshot_mode')=='review_draft':
            raise ValueError('Retained draft-layer replay is not an area reconstruction recipe')
        sources={s['id']:s for s in contract['manifest']['sources']};coverage={}
        for identifier,record in db.execute('SELECT id,record FROM feature_records'):
            feature=json.loads(record)
            if not db.execute('SELECT 1 FROM evidence WHERE feature=? LIMIT 1',(identifier,)).fetchone():continue
            ids={feature['geometry_source']}|{p['source'] for p in feature.get('parameters',{}).values() if isinstance(p,dict) and 'source' in p}
            provenance=referenced_plan_hashes(feature)
            for source in ids:
                provenance.update(referenced_plan_hashes(sources[source]))
                if sources[source].get('sha256') in plan_hashes:provenance.add(sources[source]['sha256'])
            if not provenance or not provenance<=plan_hashes:
                raise ValueError('Compiled feature lacks this area\'s planning provenance: '+identifier)
            family=FAMILY_ALIASES.get(feature['family'],feature['family'])
            coverage[family]=coverage.get(family,0)+1
        return coverage,contract
    finally:db.close()


def run(config_path, stage='extract', max_cycles=1, area_id=None):
    config_path=Path(config_path).resolve();raw=config_path.read_bytes();config=json.loads(raw)
    from .drawing_geometry import validated_options
    geometry_options=config.get('drawing_geometry_options',{})
    validated_options(geometry_options)
    evidence_settings=config.get('evidence_acquisition',{})
    if not isinstance(evidence_settings,dict) or type(evidence_settings.get('enabled',False)) is not bool:
        raise ValueError('Explicit evidence acquisition settings required')
    from .evidence_acquisition import options as acquisition_options
    evidence_budget=acquisition_options({k:v for k,v in evidence_settings.items() if k!='enabled'})
    evidence_enabled=evidence_settings.get('enabled',False)
    if evidence_enabled and not config.get('architectural_interpretation',{}).get('enabled',False):
        raise ValueError('Evidence acquisition requires architectural interpretation')
    view_settings=config.get('drawing_views',{})
    if not isinstance(view_settings,dict) or type(view_settings.get('enabled',False)) is not bool:
        raise ValueError('Explicit drawing-view settings required')
    from .drawing_view_candidates import options as view_options
    view_budget=view_options({k:v for k,v in view_settings.items() if k!='enabled'})
    component_settings=config.get('drawing_view_components',{})
    if not isinstance(component_settings,dict) or type(component_settings.get('enabled',False)) is not bool:
        raise ValueError('Explicit view-component settings required')
    from .drawing_view_components import options as component_options
    component_budget=component_options({k:v for k,v in component_settings.items() if k!='enabled'})
    if component_settings.get('enabled',False) and not view_settings.get('enabled',False):
        raise ValueError('View-component discovery requires automatic drawing views')
    resolve=lambda value:(config_path.parent/value).resolve()
    initial_base=config.get('initial_base_world');initial_sha=config.get('initial_base_sha256')
    if initial_base or initial_sha:
        if not initial_base or not initial_sha or file_hash(resolve(initial_base)/'park.mcworld')!=initial_sha:
            raise ValueError('Initial area baseline checksum mismatch')
    root=resolve(config['work_directory']);root.mkdir(parents=True,exist_ok=True)
    catalogue_path=resolve(config['catalogue']);catalogue=json.loads(catalogue_path.read_text())
    supplement_pins={}
    for name in config.get('supplemental_catalogues',[]):
        path=resolve(name);supplement_pins[name]=file_hash(path);supplement=json.loads(path.read_text())
        for document in supplement['documents']:
            if not document.get('sha256'):continue
            catalogue['entries'].append({**document,'applicationReference':supplement['application_reference'],
               'url':document.get('canonical_url',document['url'].replace('http://','https://',1)),
               'title':document.get('attachment_label',document.get('drawing_number',document.get('role','Drawing'))),
               'state':document.get('source_state','unknown')})
    areas=config['areas'];ids=[a['id'] for a in areas]
    if not 1<=len(areas)<=64 or len(set(ids))!=len(ids) or any(not re.fullmatch('[a-z0-9][a-z0-9-]{0,63}',i) for i in ids):
        raise ValueError('Unique bounded area identifiers required')
    if area_id is not None and area_id not in ids:
        raise ValueError('Unknown resort area: '+area_id)
    from .automatic_reconstruction import input_contract
    automatic_contract=input_contract(config,resolve)
    from .registration_qualification import input_contract as qualification_contract
    frame_contract=qualification_contract(config,resolve)
    from .survey_landmark_discovery import input_contract as station_contract
    landmark_contract=station_contract(config,resolve)
    contract={'version':VERSION,'config_sha256':hashlib.sha256(raw).hexdigest(),'catalogue_sha256':file_hash(catalogue_path),'supplement_sha256':supplement_pins,
              'recipe_sha256':{a['id']:file_hash(resolve(a['reconstruction_job'])) for a in areas if a.get('reconstruction_job')}}
    local_reviews={}
    for a in areas:
        seeds=a.get('local_wing_review_seeds',[])
        if not isinstance(seeds,list) or len(seeds)>8 or any(not isinstance(s,str) for s in seeds):
            raise ValueError('At most eight local wing review seeds per area')
        if seeds:local_reviews[a['id']]={s:file_hash(resolve(s)) for s in seeds}
    if local_reviews:contract['local_wing_review_seed_sha256']=local_reviews
    if automatic_contract is not None:contract['automatic_reconstruction']=automatic_contract
    if frame_contract is not None:contract['registration_qualification']=frame_contract
    if landmark_contract is not None:contract['survey_landmark_discovery']=landmark_contract
    state_path=root/'area-state.json'
    state=json.loads(state_path.read_text()) if state_path.exists() else {'contract':contract,'areas':{i:{'status':'pending'} for i in ids}}
    if state['contract']!=contract:raise ValueError('Area inputs changed; use a fresh reconstruction run')
    selected_id=area_id or state.get('active_area_id')
    if selected_id and state['areas'][selected_id]['status']=='complete' and area_id is None:selected_id=None
    next_area=(next(a for a in areas if a['id']==selected_id) if selected_id is not None else
               next((a for a in areas if state['areas'][a['id']]['status']!='complete'),None))
    if next_area is None:return state
    if state['areas'][next_area['id']]['status']=='complete':return state
    state['active_area_id']=next_area['id']
    area=next_area;entry=state['areas'][area['id']];work=root/area['id'];work.mkdir(exist_ok=True)
    def save():atomic_json(state_path,state);atomic_json(work/'area-report.json',{'area':area,**entry})
    docs=select_documents(catalogue,area)
    if not docs:
        entry.update(status='awaiting_applications',missing_components=area['required_families']);save();return state
    atomic_json(work/'selected-catalogue.json',{'entries':docs})
    corpus=Corpus(work/'corpus')
    discovered_references=None
    try:
        corpus.ingest(docs,config['official_hosts'])
        # Reuse only checksum-matching native PDFs, never a park voxel overlay.
        for record in docs:
            sha=record.get('sha256')
            if not sha:continue
            target=corpus.root/'files'/f'{sha}.pdf'
            if target.exists() and file_hash(target)==sha:continue
            for directory in config.get('source_directories',[]):
                directory=resolve(directory)
                for candidate in (directory/f'{sha}.pdf',directory/'files'/f'{sha}.pdf'):
                    if candidate.is_file() and file_hash(candidate)==sha:
                        shutil.copyfile(candidate,target);break
                if target.exists() and file_hash(target)==sha:break
        survey_sources=config.get('survey_source_discovery',{})
        priority_urls=[]
        if survey_sources.get('enabled',True):
            from .survey_source_discovery import run as discover_survey_sources
            entry['survey_source_discovery']=discover_survey_sources(corpus,work/'survey-source-discovery',
                max_pages=survey_sources.get('max_pages',config.get('max_pages',1000)),
                max_priorities=survey_sources.get('max_priorities',128))
            priority_urls=entry['survey_source_discovery']['priority_urls']
        acquisition=corpus.acquire(offline=config.get('offline',True) or evidence_enabled,workers=4,
            limit=config.get('max_acquisition_documents',10000),interval=0,priority_urls=priority_urls)
        if survey_sources.get('enabled',True):
            entry['survey_source_discovery']=discover_survey_sources(corpus,work/'survey-source-discovery',
                max_pages=survey_sources.get('max_pages',config.get('max_pages',1000)),
                max_priorities=survey_sources.get('max_priorities',128))
        # Real native PDF extraction precedes semantic reconstruction per area.
        from .drawing_geometry import run as extract
        extracted=extract(corpus,work/'drawing-geometry',max_pages=config.get('max_pages',1000),**geometry_options)
        def architecture_review():
            from .architectural_interpretation import run as interpret_architecture, VERSION as architecture_version
            from .reconstruction_evidence_queue import run as prepare_evidence_queue, digest
            from .retained_evidence_matching import run as match_retained_evidence
            architecture=config['architectural_interpretation']
            review_root=work
            if evidence_enabled:
                review_root=work/'evidence-reviews'/digest({'version':architecture_version,
                    'geometry':extracted['file_sha256'], 'drawing_contract':extracted['contract'],
                    'sources':sorted(sha for (sha,) in corpus.db.execute("SELECT DISTINCT sha FROM downloads WHERE status='downloaded'")),
                    'options':architecture.get('options')})
            entry['architectural_interpretation']=interpret_architecture(corpus,work/'drawing-geometry',review_root/'architectural-interpretation',interpretation_options=architecture.get('options'))
            entry['reconstruction_evidence_queue']=prepare_evidence_queue(area['id'],review_root/'architectural-interpretation',review_root/'reconstruction-evidence-queue')
            archive=config.get('evidence_matching',{}).get('benchmark_archive')
            archive={**archive,'file':str(resolve(archive['file']))} if archive else None
            entry['retained_evidence_matching']=match_retained_evidence(corpus,review_root/'reconstruction-evidence-queue',work/'retained-evidence-matching',benchmark_archive=archive)
            return review_root/'reconstruction-evidence-queue'
        if evidence_enabled:
            from .evidence_acquisition import run as acquire_evidence
            queue_directory=architecture_review()
            entry['evidence_acquisition']=acquire_evidence(corpus,queue_directory,work/'evidence-acquisition',
                official_hosts=config['official_hosts'],offline=config.get('offline',True),settings=evidence_budget)
            # Refresh native extraction before every downstream registration,
            # interpretation, component and recipe stage consumes the corpus.
            extracted=extract(corpus,work/'drawing-geometry',max_pages=config.get('max_pages',1000),**geometry_options)
            acquisition=corpus.report()
            if survey_sources.get('enabled',True):
                entry['survey_source_discovery']=discover_survey_sources(corpus,work/'survey-source-discovery',
                    max_pages=survey_sources.get('max_pages',config.get('max_pages',1000)),
                    max_priorities=survey_sources.get('max_priorities',128))
        osm_settings=config.get('osm_provisional_alignment',{})
        if osm_settings.get('enabled',bool(osm_settings.get('snapshot') or osm_settings.get('bounds_wgs84'))):
            from .osm_provisional_alignment import run as align_osm
            if osm_settings.get('snapshot'):
                osm_path=resolve(osm_settings['snapshot'])
                if file_hash(osm_path)!=osm_settings['sha256']:raise ValueError('Pinned OSM alignment snapshot changed')
                target_crs=osm_settings['target_crs']
            else:
                from .osm_alignment_snapshot import acquire as acquire_osm,local_frame
                bounds=osm_settings['bounds_wgs84']
                osm_path,snapshot=acquire_osm(work/'osm-snapshot',bounds,offline=config.get('offline',True))
                entry['osm_snapshot']=snapshot;target_crs=osm_settings.get('target_crs',local_frame(bounds))
            if osm_path is None:entry['osm_provisional_alignment']={'status':'awaiting_osm_snapshot','world_geometry_additions':0}
            else:
                entry['osm_provisional_alignment']=align_osm(corpus,work/'drawing-geometry',osm_path,
                    resolve(osm_settings['knowledge_store']) if osm_settings.get('knowledge_store') else root/'evidence-memory.sqlite',
                    work/'osm-provisional-alignment',target_crs=target_crs,
                    max_pages=osm_settings.get('max_pages',config.get('max_pages',1000)),
                    max_seed_fits=osm_settings.get('max_seed_fits',512),max_name_ocr=osm_settings.get('max_name_ocr',16),
                    max_seed_batches=osm_settings.get('max_seed_batches',8))
        if landmark_contract is not None:
            from .survey_landmark_discovery import run as discover_stations
            landmark_settings=config.get('survey_landmark_discovery',{})
            frame_settings=config.get('registration_qualification',{})
            automatic_settings=config.get('automatic_reconstruction',{})
            landmark_manifest=landmark_settings.get('manifest',frame_settings.get('manifest',automatic_settings.get('manifest')))
            store=landmark_settings.get('knowledge_store',frame_settings.get('knowledge_store',automatic_settings.get('knowledge_store')))
            entry['survey_landmark_discovery']=discover_stations(corpus,work/'drawing-geometry',
                resolve(store) if store else root/'evidence-memory.sqlite',work/'survey-landmark-discovery',
                manifest=resolve(landmark_manifest) if landmark_manifest else None,
                max_pages=landmark_settings.get('max_pages',config.get('max_pages',1000)),
                max_ocr_pages=landmark_settings.get('max_ocr_pages',4))
            if landmark_settings.get('use_discovered_references',False):
                discovered_references=Path(entry['survey_landmark_discovery']['references_file'])
        if frame_contract is not None:
            from .registration_qualification import run as qualify_frames
            settings=config.get('registration_qualification',{})
            automatic=config.get('automatic_reconstruction',{})
            def frame_setting(key):return settings.get(key,automatic.get(key))
            entry['registration_qualification']=qualify_frames(corpus,work/'drawing-geometry',
                resolve(frame_setting('knowledge_store')) if frame_setting('knowledge_store') else root/'evidence-memory.sqlite',
                work/'registration-qualification',
                manifest=resolve(frame_setting('manifest')) if frame_setting('manifest') else None,
                references=discovered_references or (resolve(frame_setting('references')) if frame_setting('references') else None),
                max_pages=settings.get('max_pages',config.get('max_pages',1000)))
        architecture=config.get('architectural_interpretation',{})
        if architecture.get('enabled',False):
            architecture_review()
        if view_settings.get('enabled',False):
            from .drawing_view_candidates import run as discover_views
            entry['drawing_views']=discover_views(corpus,work/'drawing-geometry',work/'drawing-views',settings=view_budget)
        if component_settings.get('enabled',False):
            from .drawing_view_components import run as discover_components
            entry['drawing_view_components']=discover_components(corpus,work/'drawing-geometry',
                entry['drawing_views']['directory'],work/'drawing-view-components',settings=component_budget)
        contextual=config.get('cross_drawing_alignment',{})
        automatic_settings=config.get('automatic_reconstruction',{})
        if contextual.get('enabled',automatic_settings.get('enabled',False)):
            from .cross_drawing_alignment import run as match_cross_drawing
            store=contextual.get('knowledge_store',automatic_settings.get('knowledge_store'))
            target_crs=contextual.get('target_crs')
            if target_crs is None:
                target_crs=json.loads(resolve(automatic_settings['manifest']).read_text())['crs']
            entry['cross_drawing_alignment']=match_cross_drawing(corpus,work/'drawing-geometry',
                resolve(store) if store else root/'evidence-memory.sqlite',work/'cross-drawing-alignment',
                target_crs=target_crs,max_pages=contextual.get('max_pages',1000))
        from .planning_components import run as identify
        mentions=identify(corpus,work/'drawing-geometry',work/'components')
        available={sha for (sha,) in corpus.db.execute("SELECT DISTINCT sha FROM downloads WHERE status='downloaded'")}
        if area.get('local_wing_review_seeds'):
            from .local_wing_review import run as review_wing
            from .native_opening_inventory import run as inventory_openings
            from .opening_boundary_review import run as review_boundaries
            from .aperture_gap_proposals import run as propose_gaps
            from .wing_outline_review import run as review_outlines
            reviews=[];inventories=[];boundaries=[];gaps=[];outlines=[]
            for ordinal,seed in enumerate(area['local_wing_review_seeds']):
                seed_path=resolve(seed)
                if file_hash(seed_path)!=local_reviews[area['id']][seed]:raise ValueError('Local review seed changed during area run')
                recipe=json.loads(seed_path.read_text())
                required={v['sha256'] for v in recipe['documents'].values()}
                if not required<=available:
                    reviews.append({'status':'awaiting_local_review_sources','missing_source_sha256':sorted(required-available),
                                    'world_geometry_additions':0,'world_placement_eligible':False})
                    inventories.append({'status':'awaiting_local_review_sources','world_geometry_additions':0})
                    boundaries.append({'status':'awaiting_local_review_sources','world_geometry_additions':0})
                    gaps.append({'status':'awaiting_local_review_sources','world_geometry_additions':0})
                    outlines.append({'status':'awaiting_local_review_sources','world_geometry_additions':0})
                    continue
                # Corpus owns original blob paths; never fall back to an unrelated source directory.
                paths={k:corpus.root/'files'/(v['sha256']+'.pdf') for k,v in recipe['documents'].items()}
                reviews.append(review_wing(seed_path,paths,work/'local-wing-reviews'/str(ordinal)))
                inventory=inventory_openings(seed_path,paths['elevation'],work/'native-opening-inventories'/str(ordinal))
                inventories.append(inventory)
                boundaries.append(review_boundaries(seed_path,paths['elevation'],inventory,work/'opening-boundary-reviews'/str(ordinal)))
                gaps.append(propose_gaps(seed_path,paths['elevation'],work/'aperture-gap-proposals'/str(ordinal)))
                outlines.append(review_outlines(seed_path,paths,work/'wing-outline-reviews'/str(ordinal)))
            entry['local_wing_reviews']=reviews
            entry['native_opening_inventories']=inventories
            entry['opening_boundary_reviews']=boundaries
            entry['aperture_gap_proposals']=gaps
            entry['wing_outline_reviews']=outlines
        entry.update(name=area['name'],applications=area['application_references'],document_records=len(docs),
                     selected_documents=[{'title':d.get('title'),'state':d.get('state','unknown'),'sha256':d.get('sha256'),'url':d['url']} for d in docs],
                     acquisition=acquisition,extraction=extracted,component_mentions=mentions,available_planning_sha256=sorted(available),
                     status='awaiting_reconstruction',missing_components=area['required_families'],
                     world_geometry_additions=0)
    finally:corpus.close()
    if stage=='extract':
        save();return state
    automatic_job=None
    if not area.get('reconstruction_job') and automatic_contract is not None:
        from .automatic_reconstruction import prepare as automatic_prepare
        automatic_job,automatic_report=automatic_prepare(config,area,resolve,work,available,references_override=discovered_references)
        entry['automatic_reconstruction']=automatic_report
        if automatic_job is None:
            entry['status']=automatic_report['status'];save();return state
        area={**area,'reconstruction_job':str(automatic_job),
              'required_component_ids':area.get('required_component_ids') or automatic_report['discovered_component_ids']}
        entry['reconstruction_recipe_configured']=True
        entry['component_inventory_bound']=True
    if not area.get('reconstruction_job'):
        save();return state
    job_path=resolve(area['reconstruction_job']);job=json.loads(job_path.read_text())
    # Resolve recipe assets against the recipe, not against the generated job.
    path_keys={'manifest','terrain_config','base_world','feature_records','references','reviews','documents','file','model','placement','cache','sheets','bindings','mentions','candidates','corpus','feature_reviews'}
    def absolute(value,key=None):
        if isinstance(value,dict):return {k:absolute(v,k) for k,v in value.items()}
        if isinstance(value,list):return [absolute(v,key) for v in value]
        if key in path_keys and isinstance(value,str):return str((job_path.parent/value).resolve())
        return value
    job=absolute(job);job['work_directory']=str(work/'reconstruction')
    if initial_base:job['base_world']=str(resolve(initial_base))
    job['acquisition']={'catalogue':str(work/'selected-catalogue.json'),'official_hosts':config['official_hosts'],
                        'offline':True,'cache':str(work/'corpus'),'workers':4}
    if job.get('planning_components'):
        job['planning_components'].update(mentions=str(work/'components/component-mentions.jsonl'),
            candidates=str(work/'drawing-geometry/geometry-candidates.jsonl'),corpus=str(work/'corpus'))
    prior=[state['areas'][a['id']] for a in areas[:areas.index(next_area)]
           if state['areas'][a['id']]['status'] in ('complete','partial_area_preview')]
    if prior:
        retained=prior[-1];source=root/retained['base_world']
        if file_hash(source/'park.mcworld')!=retained['world_sha256']:raise ValueError('Previous area download changed')
        job['base_world']=str(source)
    derived=work/'planning-job.json';atomic_json(derived,job)
    from .park_pipeline import run as reconstruct
    reconstruction=reconstruct(derived,stage='compile');entry['reconstruction']=reconstruction
    geometry=work/'reconstruction/geometry.sqlite'
    if not geometry.exists():save();return state
    coverage,compiled=compiled_coverage(geometry,available);entry['generated_families']=coverage
    entry['missing_components']=sorted({FAMILY_ALIASES.get(f,f) for f in area['required_families']}-set(coverage))
    if not coverage:save();return state
    if not area.get('bounds') or not area.get('bounds_crs'):
        entry['status']='awaiting_area_boundary';save();return state
    from shapely.geometry import box
    from shapely.ops import transform
    from pyproj import Transformer
    boundary=transform(Transformer.from_crs(area['bounds_crs'],compiled['manifest']['crs'],always_xy=True).transform,box(*area['bounds']))
    db=sqlite3.connect(geometry)
    try:
        for x,z in db.execute('SELECT DISTINCT x,z FROM voxels'):
            if not boundary.buffer(1e-7).covers(box(x,z,x+1,z+1)):
                raise ValueError('Compiled geometry escapes the selected resort area')
    finally:db.close()
    import amulet
    from .bedrock import material_block
    base=Path(job['base_world']);quality=json.loads((base/'quality-report.json').read_text())
    world=amulet.load_level(str(base/'bedrock-world'));db=sqlite3.connect(geometry)
    try:
        changes=0;offset=quality['world']['vertical_offset_blocks']
        for (text,) in db.execute('SELECT row FROM voxels'):
            row=json.loads(text)
            changes+=world.get_block(row['x'],row['y']+offset,-row['z'],'minecraft:overworld')!=material_block(row['material'])
        entry['planned_native_changes']=changes
    finally:world.close();db.close()
    if not changes:
        entry['status']='no_new_area_geometry';save();return state
    # The job boundary, registration and feature compiler constrain geometry;
    # these chunks are merely budgets inside the selected semantic area.
    db=sqlite3.connect(geometry);chunks=db.execute('SELECT DISTINCT cx,cz FROM voxels').fetchall();db.close()
    plan=CyclePlan.create(work/'cycles.sqlite',geometry,base,chunks,
             sections=1,batch_chunks=area.get('batch_chunks',150),workers=10,terrain_config=job['terrain_config'])
    entry['generation_inputs']={'geometry':str(geometry),'base_world':str(base),
                                'terrain_config':job['terrain_config'],'output':str(work/'output')}
    from .generation_cycle_export import run_isolated,preview
    try:
        if stage=='prepare':
            entry.update(status='ready_for_cycle',chunk_cycles=plan.report());save();return state
        if stage in ('assemble','finish'):
            cycle=plan.next_cycle()
            if stage=='assemble' and cycle is not None:preview(plan,geometry,base,cycle,work/'output',job['terrain_config'])
            result={'progress':plan.report()}
        else:result=run_isolated(plan,geometry,base,work/'output',job['terrain_config'],max_cycles)
    finally:plan.close()
    entry['chunk_cycles']=result['progress'];entry['status']='generating'
    complete=[c for c in result['progress']['cycles'] if c['status']=='complete']
    if complete:
        entry['world_geometry_additions']=changes if result['progress']['status']=='complete' else None
        receipt=complete[-1]['preview'];entry['latest_preview']={**receipt,'area_id':area['id'],'area_name':area['name']}
    if result['progress']['status']=='complete':
        destination=work/'completed-base';destination.mkdir(exist_ok=True)
        source=work/'output/native'
        shutil.copyfile(source/'park.mcworld',destination/'park.mcworld');shutil.copyfile(source/'quality-report.json',destination/'quality-report.json')
        if not (destination/'bedrock-world').exists():shutil.copytree(source/'bedrock-world',destination/'bedrock-world')
        db=sqlite3.connect(geometry)
        try:generated_ids={r[0] for r in db.execute('SELECT DISTINCT feature FROM evidence')}
        finally:db.close()
        required_ids=area.get('required_component_ids',[])
        entry['missing_component_ids']=sorted(set(required_ids)-generated_ids)
        entry.update(base_world=destination.relative_to(root).as_posix(),world_sha256=file_hash(destination/'park.mcworld'),
                     status='complete' if required_ids and not entry['missing_component_ids'] and not entry['missing_components'] and (automatic_job is None or next_area.get('required_component_ids')) else 'partial_area_preview',
                     component_inventory_bound=bool(required_ids))
    save();return state


def run_all(config_path, stage='reconstruct', max_cycles=1):
    """Exercise every named area without counting a blocker as area completion."""
    config_path=Path(config_path).resolve();config=json.loads(config_path.read_text())
    areas=config['areas'];ids=[a['id'] for a in areas]
    if not 1<=len(areas)<=64 or len(set(ids))!=len(ids) or any(not re.fullmatch('[a-z0-9][a-z0-9-]{0,63}',i) for i in ids):
        raise ValueError('Unique bounded area identifiers required')
    root=(config_path.parent/config['work_directory']).resolve();root.mkdir(parents=True,exist_ok=True)
    report={'status':'running','stage':stage,'max_cycles_per_area':max_cycles,
            'config_sha256':file_hash(config_path),'results':[],
            'scope':'Area-by-area coordinator test; source scans and missing recipes are not world generation.'}
    if config.get('initial_base_world'):
        base=(config_path.parent/config['initial_base_world']).resolve()
        report['initial_base_sha256']=file_hash(base/'park.mcworld')
    target=root/'sweep-report.json'
    for area in areas:
        row={'area_id':area['id'],'name':area['name'],
             'reconstruction_recipe_configured':bool(area.get('reconstruction_job')),
             'boundary_configured':bool(area.get('bounds') and area.get('bounds_crs')),
             'component_inventory_configured':bool(area.get('required_component_ids'))}
        try:
            state=run(config_path,stage,max_cycles,area['id']);entry=state['areas'][area['id']]
            for key in ('status','document_records','acquisition','extraction','component_mentions',
                        'generated_families','missing_components','missing_component_ids',
                        'world_geometry_additions','planned_native_changes','latest_preview','world_sha256',
                        'automatic_reconstruction','reconstruction_recipe_configured','component_inventory_bound','reconstruction_evidence_queue','retained_evidence_matching','evidence_acquisition','drawing_views','drawing_view_components','local_wing_reviews','native_opening_inventories','opening_boundary_reviews','aperture_gap_proposals','wing_outline_reviews'):
                if key in entry:row[key]=entry[key]
            row.setdefault('world_geometry_additions',0)
            row['blockers']=[]
            if row['status']=='awaiting_applications':row['blockers'].append('No selected planning application documents')
            if not row['reconstruction_recipe_configured']:row['blockers'].append('No source-bound reconstruction recipe')
            if not row['boundary_configured']:row['blockers'].append('No accepted area boundary')
            if not row['component_inventory_configured'] and not row.get('component_inventory_bound'):row['blockers'].append('No bound physical component inventory')
            if row.get('automatic_reconstruction') and not area.get('required_component_ids'):row['blockers'].append('Complete area inventory remains unverified')
            if row.get('acquisition',{}).get('download_status',{}).get('pending',0):row['blockers'].append('Some planning PDFs unavailable')
            if row.get('extraction',{}).get('errors'):row['blockers'].append('Native extraction errors')
        except Exception as exc:
            row.update(status='test_error',error=str(exc),world_geometry_additions=0)
        report['results'].append(row);atomic_json(target,report)
    counts={}
    for row in report['results']:counts[row['status']]=counts.get(row['status'],0)+1
    report.update(status='complete' if counts.get('complete',0)==len(config['areas']) else 'completed_with_blockers',
                  area_status_counts=counts,areas_tested=len(report['results']),
                  areas_with_native_preview=sum(bool(r.get('latest_preview')) for r in report['results']))
    atomic_json(target,report);return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--job',required=True)
    parser.add_argument('--area',help='Select a named area without completing earlier unfinished areas')
    parser.add_argument('--all-areas',action='store_true',help='Test every area and record results, continuing past blockers')
    parser.add_argument('--stage',choices=['extract','reconstruct'],default='extract');parser.add_argument('--max-cycles',type=int,default=1)
    args=parser.parse_args()
    if args.all_areas and args.area:parser.error('--area and --all-areas are mutually exclusive')
    result=run_all(args.job,args.stage,args.max_cycles) if args.all_areas else run(args.job,args.stage,args.max_cycles,args.area)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
