"""Exercise original-PDF planning discovery through the packaged managed worker."""
import hashlib
import json
from pathlib import Path

import pymupdf

from .desktop_runtime import DesktopRuntime, _wait, write_json
from .planning_area_pilot import VERSION


def run(output):
    root=Path(output).resolve()
    if root.exists(): raise ValueError('Fresh planning pilot smoke output required')
    root.mkdir(parents=True)
    source=root/'synthetic-original.pdf'
    with pymupdf.open() as document:
        page=document.new_page(width=600,height=500)
        page.draw_rect((30,30,190,140));page.insert_text((50,80),'Footpath',fontsize=10)
        page.insert_text((30,190),'Proposed Ground Floor Plan | 1:100',fontsize=10)
        page.insert_text((30,450),'Existing Front Elevation',fontsize=10)
        document.save(source)
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    config={'version':VERSION,'area_id':'synthetic-packaged-pilot',
        'application_references':['synthetic-fixture'], 'source_directory':str(root),
        'development_exposure':'previously_inspected', 'documents':[{
            'file':source.name,'sha256':sha,'title':'Synthetic mixed drawing',
            'role':'floor-plan','drawing_state':'unknown','application_reference':'synthetic-fixture'}]}
    write_json(root/'pilot.json',config)
    runtime=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
    try:
        jid=runtime.submit('planning_source_pilot',root/'pilot.json')
        job=_wait(runtime,jid,timeout=120);runtime._futures[jid].result(timeout=10)
        if job['status']!='completed': raise ValueError('Managed planning pilot failed: '+str(job.get('error')))
        result=job['result'];summary=result['summary'];pack=Path(job['output_directory'])
        if summary['completed_pages']!=1 or summary['visible_view_captions']!=2 or summary['surface_candidates']!=1:
            raise ValueError('Original drawing extraction did not match synthetic fixture')
        if summary['geometric_accuracy'] is not None or result['world_placement_eligible'] or result['training_labels_generated']:
            raise ValueError('Discovery supplied unverified accuracy, acceptance or labels')
        for name,pin in result['output_sha256'].items():
            if hashlib.sha256((pack/name).read_bytes()).hexdigest()!=pin:
                raise ValueError('Planning pilot output checksum mismatch')
        if runtime.store.summary()['feedback_records'] or runtime.store.summary()['checkpoints']:
            raise ValueError('Discovery changed reviewed learning data')
    finally:runtime.close(wait=True)
    reopened=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
    try:
        if reopened.store.job(jid)['result']['summary']!=summary:
            raise ValueError('Planning pilot history did not survive restart')
    finally:reopened.close(wait=True)
    receipt={'status':'passed','dataset_kind':'synthetic','job':job,
        'original_pdf_verified':hashlib.sha256(source.read_bytes()).hexdigest()==sha,
        'output_hashes_verified':True,'persistent_restart_verified':True,
        'real_park_accuracy_assessed':False,'world_placement_eligible':False,
        'training_labels_generated':0,'model_promoted':False}
    write_json(root/'planning-pilot-smoke.json',receipt)
    return receipt
