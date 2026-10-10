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

VERSION='resort-area-reconstruction-v1'


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


def run(config_path, stage='extract', max_cycles=1):
    config_path=Path(config_path).resolve();raw=config_path.read_bytes();config=json.loads(raw)
    resolve=lambda value:(config_path.parent/value).resolve()
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
    contract={'version':VERSION,'config_sha256':hashlib.sha256(raw).hexdigest(),'catalogue_sha256':file_hash(catalogue_path),'supplement_sha256':supplement_pins,
              'recipe_sha256':{a['id']:file_hash(resolve(a['reconstruction_job'])) for a in areas if a.get('reconstruction_job')}}
    state_path=root/'area-state.json'
    state=json.loads(state_path.read_text()) if state_path.exists() else {'contract':contract,'areas':{i:{'status':'pending'} for i in ids}}
    if state['contract']!=contract:raise ValueError('Area inputs changed; use a fresh reconstruction run')
    next_area=next((a for a in areas if state['areas'][a['id']]['status']!='complete'),None)
    if next_area is None:return state
    area=next_area;entry=state['areas'][area['id']];work=root/area['id'];work.mkdir(exist_ok=True)
    def save():atomic_json(state_path,state);atomic_json(work/'area-report.json',{'area':area,**entry})
    docs=select_documents(catalogue,area)
    if not docs:
        entry.update(status='awaiting_applications',missing_components=area['required_families']);save();return state
    atomic_json(work/'selected-catalogue.json',{'entries':docs})
    corpus=Corpus(work/'corpus')
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
        acquisition=corpus.acquire(offline=config.get('offline',True),workers=4,limit=10000,interval=0)
        # Real native PDF extraction precedes semantic reconstruction per area.
        from .drawing_geometry import run as extract
        extracted=extract(corpus,work/'drawing-geometry',max_pages=config.get('max_pages',1000))
        from .planning_components import run as identify
        mentions=identify(corpus,work/'drawing-geometry',work/'components')
        available={sha for (sha,) in corpus.db.execute("SELECT DISTINCT sha FROM downloads WHERE status='downloaded'")}
        entry.update(name=area['name'],applications=area['application_references'],document_records=len(docs),
                     selected_documents=[{'title':d.get('title'),'state':d.get('state','unknown'),'sha256':d.get('sha256'),'url':d['url']} for d in docs],
                     acquisition=acquisition,extraction=extracted,component_mentions=mentions,available_planning_sha256=sorted(available),
                     status='awaiting_reconstruction',missing_components=area['required_families'],
                     world_geometry_additions=0)
    finally:corpus.close()
    if stage=='extract' or not area.get('reconstruction_job'):
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
    job['acquisition']={'catalogue':str(work/'selected-catalogue.json'),'official_hosts':config['official_hosts'],
                        'offline':True,'cache':str(work/'corpus'),'workers':4}
    if job.get('planning_components'):
        job['planning_components'].update(mentions=str(work/'components/component-mentions.jsonl'),
            candidates=str(work/'drawing-geometry/geometry-candidates.jsonl'),corpus=str(work/'corpus'))
    prior=[state['areas'][a['id']] for a in areas[:areas.index(area)] if state['areas'][a['id']]['status']=='complete']
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
    from .generation_cycle_export import run_isolated
    try:result=run_isolated(plan,geometry,base,work/'output',job['terrain_config'],max_cycles)
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
                     status='complete' if required_ids and not entry['missing_component_ids'] and not entry['missing_components'] else 'partial_area_preview',
                     component_inventory_bound=bool(required_ids))
    save();return state


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--job',required=True)
    parser.add_argument('--stage',choices=['extract','reconstruct'],default='extract');parser.add_argument('--max-cycles',type=int,default=1)
    args=parser.parse_args();print(json.dumps(run(args.job,args.stage,args.max_cycles),indent=2))


if __name__=='__main__':main()
