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
            for index,archive in enumerate(acquisition.get('retained_archives',[])):
                from .planning_archive import import_archive
                checkpoint('retained_archive_'+str(index),import_archive(corpus,path(archive['file']),archive['sha256'],acquisition['official_hosts'],catalogue_member=archive.get('catalogue_member','metadata/alton-planning-catalogue.json'),allow_partial=archive.get('allow_partial',False)))
            report=corpus.acquire(workers=acquisition.get('workers',4),limit=acquisition.get('max_downloads',10000),max_run_bytes=acquisition.get('max_run_bytes',2000000000),
                                  offline=acquisition.get('offline',False),cache=str(path(acquisition['cache'])) if acquisition.get('cache') else None)
            checkpoint('downloads',report);checkpoint('inspection',corpus.inspect(acquisition.get('max_inspection_pages',10000)))
            audit=job.get('anchor_audit',{})
            if audit.get('enabled',False):
                from .anchor_audit import run as audit_anchors
                checkpoint('anchor_audit',audit_anchors(corpus,root/'anchors',audit['bounds_wgs84'],max_pages=audit.get('max_pages',10000)))
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
            if job.get('footprint_extraction',{}).get('enabled',False):
                from .drawing_footprints import run as extract_footprints
                checkpoint('footprints',extract_footprints(corpus,root/'footprints',max_pages=job['footprint_extraction'].get('max_pages',1000)))
            geometry=job.get('drawing_geometry',{})
            if geometry.get('enabled',False):
                from .drawing_geometry import run as extract_geometry
                checkpoint('drawing_geometry',extract_geometry(corpus,root/'drawing-geometry',max_pages=geometry.get('max_pages',10000),curve_tolerance_points=geometry.get('curve_tolerance_points',.25)))
            components=job.get('drawing_components',{})
            if components.get('enabled',False):
                from .drawing_components import run as split_components
                if not geometry.get('enabled',False):raise ValueError('Drawing components require drawing geometry')
                checkpoint('drawing_components',split_components(corpus,root/'drawing-geometry/geometry-candidates.jsonl',root/'drawing-components',max_records=components.get('max_records',2500000)))
            polygon_candidates=root/'drawing-components/polygon-candidates.jsonl' if components.get('enabled',False) else root/'drawing-geometry/polygon-candidates.jsonl' if geometry.get('enabled',False) else root/'footprints/footprint-candidates.jsonl'
            drawing_candidates=root/'drawing-components/component-candidates.jsonl' if components.get('enabled',False) else root/'drawing-geometry/geometry-candidates.jsonl' if geometry.get('enabled',False) else polygon_candidates
            linework=job.get('linework_boundaries',{})
            if linework.get('enabled',False):
                from .linework_boundaries import run as recover_boundaries
                if not geometry.get('enabled',False):raise ValueError('Linework boundary recovery requires drawing geometry')
                selected=json.loads(path(linework['sheets']).read_text()) if linework.get('sheets') else None
                checkpoint('linework_boundaries',recover_boundaries(corpus,root/'drawing-geometry/geometry-candidates.jsonl',root/'linework-boundaries',sheets=selected,recovery_options=linework.get('options'),max_records=linework.get('max_records',2500000)))
                drawing_candidates=root/'linework-boundaries/boundary-candidates.jsonl';polygon_candidates=root/'linework-boundaries/polygon-candidates.jsonl'
            placement=job.get('mapped_placement',{})
            if placement.get('enabled',False):
                from .mapped_sheet_placement import run as place_mapped
                if not geometry.get('enabled',False) and not job.get('footprint_extraction',{}).get('enabled',False):raise ValueError('Mapped placement requires retained drawing geometry or footprints')
                feed=drawing_candidates
                selected=json.loads(path(placement['sheets']).read_text()) if placement.get('sheets') else None
                checkpoint('mapped_placement',place_mapped(feed,path(placement['references']),placement['reference_crs'],placement['target_crs'],root/'mapped-placement',corpus,sheets=selected,max_seed_fits=placement.get('max_seed_fits',512),min_iou=placement.get('min_iou',.7),tolerance_m=placement.get('tolerance_m',10.),max_records=placement.get('max_records',2500000)))
            matching=job.get('footprint_matching',{})
            layout=job.get('drawing_layout',{})
            if layout.get('enabled',False):
                from .drawing_layout import run as inspect_layout
                checkpoint('drawing_layout',inspect_layout(corpus,root/'drawing-layout',max_pages=layout.get('max_pages',10000),**layout.get('options',{})))
            outline=job.get('outline_review',{})
            if outline.get('enabled',False):
                from .outline_batch import run as review_outlines
                if not geometry.get('enabled',False) and not job.get('footprint_extraction',{}).get('enabled',False):raise ValueError('Outline review requires drawing geometry or footprint extraction')
                feed=drawing_candidates
                checkpoint('outline_review',review_outlines(corpus,feed,root/'outline-review',max_records=outline.get('max_records',2500000)))
            if matching.get('enabled',False):
                from .footprint_matching import run as match_footprints,VERSION as matching_version
                candidates=polygon_candidates;references=path(matching['references']);destination=root/'footprint-matching'
                target=matching.get('target_crs') or json.loads(path(job['manifest']).read_text())['crs']
                with candidates.open('rb') as stream:candidate_hash=hashlib.file_digest(stream,'sha256').hexdigest()
                with references.open('rb') as stream:reference_hash=hashlib.file_digest(stream,'sha256').hexdigest()
                contract={'version':matching_version,'candidate_sha256':candidate_hash,'reference_sha256':reference_hash,'reference_crs':matching['reference_crs'],'target_crs':target,'native_names_enabled':True,'max_records':matching.get('max_records',2500000)}
                if destination.exists():
                    report_path=destination/'matching-report.json'
                    if not report_path.exists():raise ValueError('Matching output is incomplete; remove that output directory before retrying')
                    report=json.loads(report_path.read_text())
                    if any(report.get(key)!=value for key,value in contract.items()):raise ValueError('Matching inputs changed; use a fresh job')
                    for filename in ('associations.jsonl','revision-review.jsonl'):
                        with (destination/filename).open('rb') as stream:
                            if hashlib.file_digest(stream,'sha256').hexdigest()!=report[filename+'_sha256']:raise ValueError('Matching output checksum mismatch')
                else:report=match_footprints(candidates,references,matching['reference_crs'],target,destination,corpus=corpus,max_records=contract['max_records'])
                checkpoint('footprint_matching',report)
            boundary=job.get('boundary_registration',{})
            if boundary.get('enabled',False):
                from .boundary_registration import run as register_boundaries,VERSION as boundary_version,file_hash
                if not matching.get('enabled',False):raise ValueError('Boundary registration requires footprint_matching')
                candidates=polygon_candidates;destination=root/'boundary-registration';matching_root=root/'footprint-matching'
                reviews=json.loads(path(boundary['reviews']).read_text()) if boundary.get('reviews') else []
                contract={'version':boundary_version,'candidate_sha256':file_hash(candidates),'association_sha256':file_hash(matching_root/'associations.jsonl'),'reference_sha256':file_hash(path(matching['references'])),'target_crs':target,'reference_crs':matching['reference_crs'],'max_fits':boundary.get('max_fits',10000),'review_sha256':hashlib.sha256(json.dumps(reviews,sort_keys=True).encode()).hexdigest()}
                if destination.exists():
                    report_path=destination/'boundary-report.json'
                    if not report_path.exists():raise ValueError('Boundary output is incomplete; remove that output directory before retrying')
                    report=json.loads(report_path.read_text())
                    if any(report.get(key)!=value for key,value in contract.items()):raise ValueError('Boundary inputs changed; use a fresh job')
                    if file_hash(destination/'boundary-hypotheses.jsonl')!=report['output_sha256']:raise ValueError('Boundary output checksum mismatch')
                else:report=register_boundaries(candidates,matching_root,path(matching['references']),matching['reference_crs'],target,destination,corpus,max_fits=contract['max_fits'],registration_reviews=reviews)
                checkpoint('boundary_registration',report)

            sheet=job.get('sheet_alignment',{})
            if sheet.get('enabled',False):
                from .sheet_alignment import run as align_sheet
                if not matching.get('enabled',False):raise ValueError('Sheet alignment requires footprint_matching')
                candidates=polygon_candidates
                checkpoint('sheet_alignment',align_sheet(candidates,root/'footprint-matching',path(matching['references']),matching['reference_crs'],target,root/'sheet-alignment',corpus,max_pair_fits=sheet.get('max_pair_fits',2000),max_records=sheet.get('max_records',2500000)))

        finally:corpus.close()
    if stage in ('all','reconstruct','compile'):
        manifest_path=path(job['manifest']);manifest=json.loads(manifest_path.read_text())
        pinned={'manifest':hashlib.sha256(manifest_path.read_bytes()).hexdigest()}
        annotation_config=job.get('drawing_annotations',{})
        if annotation_config.get('enabled',False):
            from .drawing_annotations import run as inspect_annotations
            annotation_report=inspect_annotations(path(annotation_config['documents']),root/'drawing-annotations',
                                                  max_pages=annotation_config.get('max_pages',10000))
            checkpoint('drawing_annotations',annotation_report)
            pinned['drawing_annotations']={'contract':annotation_report['contract'],'annotations_sha256':annotation_report['annotations_sha256']}
        callout_config=job.get('drawing_callouts',{})
        if callout_config.get('enabled',False):
            from .drawing_callouts import run as inspect_callouts
            callout_report=inspect_callouts(path(callout_config['documents']),root/'drawing-callouts',
                                          max_pages=callout_config.get('max_pages',10000))
            checkpoint('drawing_callouts',callout_report)
            pinned['drawing_callouts']={'contract':callout_report['contract'],'callouts_sha256':callout_report['callouts_sha256']}
        face_config=job.get('drawing_faces',{})
        if face_config.get('enabled',False):
            from .drawing_faces import run as inspect_faces
            face_report=inspect_faces(path(face_config['documents']),root/'drawing-faces',
                                     max_pages=face_config.get('max_pages',10000))
            checkpoint('drawing_faces',face_report)
            pinned['drawing_faces']={'contract':face_report['contract'],'output_sha256':face_report['output_sha256']}
        bridge=job.get('registration_bridge',{});bridge_feed=None
        if bridge.get('enabled',False):
            from .drawing_registration_bridge import run_batch
            destination=root/'registration-bridge'
            bridge_report=run_batch(path(bridge['documents']),manifest_path,path(bridge['references']),destination,
                                    max_pages=bridge.get('max_pages',10000),max_features=bridge.get('max_features',2500000))
            checkpoint('registration_bridge',bridge_report)
            pinned['registration_bridge']=bridge_report['contract']
            pinned['registered_manifest']=bridge_report['output_sha256']['manifest.json']
            pinned['registered_features']=bridge_report['output_sha256']['features.jsonl']
            manifest_path=destination/'manifest.json';manifest=json.loads(manifest_path.read_text())
            if bridge_report['feature_count']:bridge_feed=destination/'features.jsonl'
        for key in ('feature_records','terrain_config'):
            if job.get(key) and (key!='terrain_config' or bridge_feed or job.get('local_buildings') or job.get('geometry_feeds') or job.get('feature_records') or job.get('footprint_extraction',{}).get('feature_reviews') or job.get('drawing_geometry',{}).get('feature_reviews')):
                with path(job[key]).open('rb') as stream:pinned[key]=hashlib.file_digest(stream,'sha256').hexdigest()
        if job.get('footprint_extraction',{}).get('feature_reviews') and job.get('drawing_geometry',{}).get('feature_reviews'):raise ValueError('Use one combined extraction review list per job')
        footprint_reviews=job.get('drawing_geometry',{}).get('feature_reviews') or job.get('footprint_extraction',{}).get('feature_reviews')
        if footprint_reviews:
            with path(footprint_reviews).open('rb') as stream:pinned['footprint_reviews']=hashlib.file_digest(stream,'sha256').hexdigest()
        building_feed=None
        if job.get('local_buildings'):
            from .reconstruction.local_buildings import prepare_feed
            building_feed=root/'local-buildings/features.jsonl'
            building_report=prepare_feed(job['local_buildings'],manifest,path,building_feed)
            pinned['local_buildings']=building_report
            checkpoint('local_buildings',building_report)
        previous=state['stages'].get('input_contract')
        if previous is not None and previous!=pinned:raise ValueError('Reconstruction inputs changed; use a fresh job')
        checkpoint('input_contract',pinned)
        sources={s['id']:Source(**s) for s in manifest['sources']};normalized=root/'normalized';normalized.mkdir(exist_ok=True)
        feeds=[bridge_feed] if bridge_feed else []
        if building_feed:feeds.append(building_feed)
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
        if footprint_reviews:
            from .drawing_footprints import promote
            candidates=root/'drawing-geometry/geometry-candidates.jsonl' if job.get('drawing_geometry',{}).get('feature_reviews') else root/'footprints/footprint-candidates.jsonl';output=root/'reviewed-footprints.jsonl';receipt_path=output.with_suffix('.receipt.json')
            with candidates.open('rb') as stream:candidate_hash=hashlib.file_digest(stream,'sha256').hexdigest()
            identity={'candidate_file_sha256':candidate_hash,'review_sha256':pinned['footprint_reviews'],'manifest_sha256':pinned['manifest']}
            if output.exists() and not receipt_path.exists():output.unlink()
            if output.exists():
                receipt=json.loads(receipt_path.read_text())
                with output.open('rb') as stream:output_hash=hashlib.file_digest(stream,'sha256').hexdigest()
                if receipt['inputs']!=identity or receipt['output_sha256']!=output_hash:raise ValueError('Reviewed footprint inputs changed; use a fresh job')
            else:
                corpus=Corpus(root/'corpus')
                try:checkpoint('reviewed_footprints',promote(candidates,path(footprint_reviews),manifest_path,output,corpus))
                finally:corpus.close()
                with output.open('rb') as stream:output_hash=hashlib.file_digest(stream,'sha256').hexdigest()
                receipt_path.write_text(json.dumps({'inputs':identity,'output_sha256':output_hash},indent=2)+'\n')
            feeds.append(output)
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
        if stage == 'compile': return state
        if not report['unique_voxel_cells']:checkpoint('export',{'status':'withheld_no_accepted_geometry'});return state
        if base:
            subprocess.run([sys.executable,'-m','voxel_mapper.reconstruction.batch','native',*common,'--base-world',str(base),'--terrain-config',str(terrain),'--output',str(root/'world')],check=True)
            checkpoint('export',json.loads((root/'world/park-batch-report.json').read_text()))
        else:
            if not (root/'tiles').exists():subprocess.run([sys.executable,'-m','voxel_mapper.reconstruction.batch','tiles',*common,'--output',str(root/'tiles')],check=True)
            checkpoint('export',json.loads((root/'tiles/batch-report.json').read_text()))
    return state


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--job',required=True);p.add_argument('--stage',choices=['all','acquire','compile','reconstruct'],default='all');a=p.parse_args()
    state=run(a.job,a.stage);print(json.dumps({'job_sha256':state['job_sha256'],'stages':{k:v.get('status') for k,v in state['stages'].items()}},indent=2))

if __name__=='__main__':main()
