"""One resumable park job: acquire corpus, normalize whole-park feeds, compile and export."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from .planning_bulk import Corpus,discover_alton
from .reconstruction.model import Source
from .reconstruction.normalize import normalize


def run(job_path,stage='all'):
    job_path=Path(job_path).resolve();data=job_path.read_bytes();job=json.loads(data)
    def path(value):return (job_path.parent/value).resolve()
    root=path(job['work_directory']);root.mkdir(parents=True,exist_ok=True)
    state_path=root/'job-state.json';digest=hashlib.sha256(data).hexdigest()
    state=json.loads(state_path.read_text()) if state_path.exists() else {'job_sha256':digest,'stages':{}}
    if state['job_sha256']!=digest:raise ValueError('Job configuration changed; use a fresh work directory')
    def checkpoint(name,result):
        state['stages'][name]=result;temporary=state_path.with_suffix('.partial')
        temporary.write_text(json.dumps(state,indent=2)+'\n');temporary.replace(state_path)
    if stage in ('all','acquire'):
        corpus=Corpus(root/'corpus')
        try:
            acquisition=job.get('acquisition',{})
            if acquisition.get('provider')=='alton':checkpoint('discovery',discover_alton(corpus,max_search_pages=acquisition.get('max_search_pages',40),max_applications=acquisition.get('max_applications',1000)))
            if acquisition.get('catalogue'):
                catalogue=json.loads(path(acquisition['catalogue']).read_text());corpus.ingest(catalogue.get('entries',catalogue.get('documents',[])),acquisition['official_hosts'])
            report=corpus.acquire(workers=acquisition.get('workers',4),limit=acquisition.get('max_downloads',10000),max_run_bytes=acquisition.get('max_run_bytes',2000000000),
                                  offline=acquisition.get('offline',False),cache=str(path(acquisition['cache'])) if acquisition.get('cache') else None)
            checkpoint('downloads',report);checkpoint('inspection',corpus.inspect(acquisition.get('max_inspection_pages',10000)))
            analysis=job.get('drawing_analysis',{})
            if analysis.get('enabled',True):
                from .drawing_batch import analyze,reference_landmarks
                reviews=json.loads(path(analysis['reviews']).read_text()) if analysis.get('reviews') else None
                landmarks=None
                if analysis.get('landmarks'):
                    data=path(analysis['landmarks']).read_bytes()
                    target=analysis.get('target_crs') or json.loads(path(job['manifest']).read_text())['crs']
                    landmarks=reference_landmarks(json.loads(data),analysis['landmark_crs'],target,hashlib.sha256(data).hexdigest())
                checkpoint('drawing_analysis',analyze(corpus,max_pages=analysis.get('max_pages',10000),registration=analysis.get('registration',True),reviews=reviews,ocr=analysis.get('ocr',True),max_ocr_pages=analysis.get('max_ocr_pages',50),max_ocr_seconds=analysis.get('max_ocr_seconds',180),landmarks=landmarks))
        finally:corpus.close()
    if stage in ('all','reconstruct'):
        manifest_path=path(job['manifest']);manifest=json.loads(manifest_path.read_text())
        pinned={'manifest':hashlib.sha256(manifest_path.read_bytes()).hexdigest()}
        for key in ('feature_records','terrain_config'):
            if job.get(key) and (key!='terrain_config' or job.get('geometry_feeds') or job.get('feature_records')):
                with path(job[key]).open('rb') as stream:pinned[key]=hashlib.file_digest(stream,'sha256').hexdigest()
        previous=state['stages'].get('input_contract')
        if previous is not None and previous!=pinned:raise ValueError('Reconstruction inputs changed; use a fresh job')
        checkpoint('input_contract',pinned)
        sources={s['id']:Source(**s) for s in manifest['sources']};normalized=root/'normalized';normalized.mkdir(exist_ok=True)
        feeds=[]
        for index,feed in enumerate(job.get('geometry_feeds',[])):
            output=normalized/f'feed_{index}.jsonl';metadata=output.with_suffix('.receipt.json')
            input_path=path(feed['file'])
            with input_path.open('rb') as stream:input_hash=hashlib.file_digest(stream,'sha256').hexdigest()
            if output.exists():
                if not metadata.exists():output.unlink()
            if output.exists():
                receipt=json.loads(metadata.read_text())
                with output.open('rb') as stream:output_hash=hashlib.file_digest(stream,'sha256').hexdigest()
                if receipt['input_sha256']!=input_hash or receipt['output_sha256']!=output_hash:raise ValueError('Geometry feed changed; use a fresh job')
            else:
                receipt=normalize(input_path,output,sources[feed['source']],manifest['crs'])
                with output.open('rb') as stream:receipt['output_sha256']=hashlib.file_digest(stream,'sha256').hexdigest()
                metadata.write_text(json.dumps(receipt,indent=2)+'\n')
            feeds.append(output)
        if job.get('feature_records'):feeds.append(path(job['feature_records']))
        if not feeds:
            checkpoint('reconstruction',{'status':'awaiting_normalized_geometry','reason':'Corpus pages do not automatically become semantic registered features'})
            return state
        combined=root/'park-features.jsonl'
        with combined.open('wb') as out:
            for feed in feeds:
                with feed.open('rb') as source:
                    for line in source:
                        if len(line)>8000000:raise ValueError('Feature line budget exceeded')
                        if line.strip():out.write(line.rstrip(b'\r\n')+b'\n')
        common=['--manifest',str(manifest_path),'--database',str(root/'geometry.sqlite')]
        terrain=path(job['terrain_config']);base=path(job['base_world']) if job.get('base_world') else None
        command=[sys.executable,'-m','voxel_mapper.reconstruction.batch','compile',*common,'--features',str(combined),'--terrain-config',str(terrain)]
        if base:command+=['--base-world',str(base)]
        if job.get('allow_estimates'):command+=['--allow-estimates']
        subprocess.run(command,check=True)
        from .reconstruction.batch import GeometryStore
        import sqlite3
        connection=sqlite3.connect(root/'geometry.sqlite')
        contract=json.loads(connection.execute("SELECT value FROM metadata WHERE key='contract'").fetchone()[0]);connection.close()
        store=GeometryStore(root/'geometry.sqlite',contract)
        try:report=store.report()
        finally:store.close()
        checkpoint('reconstruction',report)
        if not report['unique_voxel_cells']:checkpoint('export',{'status':'withheld_no_accepted_geometry'});return state
        if base:
            subprocess.run([sys.executable,'-m','voxel_mapper.reconstruction.batch','native',*common,'--base-world',str(base),'--terrain-config',str(terrain),'--output',str(root/'world')],check=True)
            checkpoint('export',json.loads((root/'world/park-batch-report.json').read_text()))
        else:
            if not (root/'tiles').exists():subprocess.run([sys.executable,'-m','voxel_mapper.reconstruction.batch','tiles',*common,'--output',str(root/'tiles')],check=True)
            checkpoint('export',json.loads((root/'tiles/batch-report.json').read_text()))
    return state


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--job',required=True);p.add_argument('--stage',choices=['all','acquire','reconstruct'],default='all');a=p.parse_args()
    state=run(a.job,a.stage);print(json.dumps({'job_sha256':state['job_sha256'],'stages':{k:v.get('status') for k,v in state['stages'].items()}},indent=2))

if __name__=='__main__':main()
