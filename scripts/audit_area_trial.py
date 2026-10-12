"""Audit a completed area trial without confusing drawing extraction with worlds."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voxel_mapper.area_cycles import load,prepare
from voxel_mapper.generation_cycles import atomic_json,file_hash


def audit(job,check_resume=False):
    _,config,root,_,state=load(job)
    if state['status'] not in ('complete','completed_with_blockers'):
        raise ValueError('Completed area controller pass required')
    if state['cursor']!=len(config['areas']) or state['active_cycle'] is not None:
        raise ValueError('Every configured area must have reached a checkpoint')
    rows=[]
    for area in config['areas']:
        identifier=area['id'];controller=state['areas'][identifier]
        path=root/identifier/'area-report.json'
        if not path.exists():
            rows.append({'area_id':identifier,**controller,'report_available':False})
            continue
        report=json.loads(path.read_text());extraction=report['extraction']
        architecture=report.get('architectural_interpretation',{})
        available=set(report['available_planning_sha256'])
        selected=report['selected_documents']
        rows.append({'area_id':identifier,'status':controller['status'],'report_available':True,
            'application_references':area['application_references'],
            'catalogue_document_records':report['document_records'],
            'verified_original_pdfs':report['acquisition']['distinct_pdf_blobs'],
            'pending_document_links':report['acquisition']['download_status'].get('pending',0),
            'extracted_pages':extraction['pages'],'geometry_candidates':extraction['candidates'],
            'extraction_errors':extraction['errors'],
            'architectural_pages':architecture.get('pages',0),
            'architectural_counts':architecture.get('counts',{}),
            'unbound_component_mentions':report['component_mentions']['mentions'],
            'evidence_tasks':report.get('reconstruction_evidence_queue',{}).get('task_count',0),
            'missing_component_families':report['missing_components'],
            'blockers':controller.get('blockers',[]),
            'world_geometry_additions':report['world_geometry_additions'],
            'report_sha256':file_hash(path),
            'source_manifest':[{'sha256':d.get('sha256'),'title':d.get('title'),'url':d['url'],
                'catalogue_state':d.get('state','unknown'),'original_pdf_available':d.get('sha256') in available}
                for d in selected]})
    resumed=False
    if check_resume:
        # Check all finished artifacts, including byte-for-byte controller state.
        def snapshot():
            return {str(p.relative_to(root)):file_hash(p) for p in root.rglob('*') if p.is_file()}
        before=snapshot()
        if prepare(job)!=state or snapshot()!=before:
            raise ValueError('Completed trial changed on unchanged-input resume')
        resumed=True
    return {'version':'area-scale-trial-audit-v1','controller_status':state['status'],
        'input_contract':state['contract'],'configured_areas':len(config['areas']),
        'published_native_cycles':state['published_cycles'],
        'unchanged_resume_checked':resumed,'areas':rows,
        'limitations':['This is a retained-input offline readiness trial, not complete area reconstruction.',
            'Catalogue associations do not establish exhaustive area coverage or existing building identity.',
            'Local study previews are separate from geographically registered cumulative area worlds.',
            'No training labels or model promotion are authorized by unreviewed drawing candidates.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--check-resume',action='store_true')
    args=parser.parse_args();result=audit(args.job,args.check_resume)
    atomic_json(args.output,result)
    print(json.dumps({k:result[k] for k in ('configured_areas','controller_status','published_native_cycles','unchanged_resume_checked')}))


if __name__=='__main__':main()
