"""Exercise original-PDF planning discovery through the packaged managed worker."""
import hashlib
import json
from pathlib import Path

import pymupdf

from .desktop_runtime import DesktopRuntime, _wait, write_json
from .planning_area_pilot import VERSION


def draw_component_fixture(page):
    """Adjacent labelled faces made only of sub-12-point source segments."""
    for x1,y1,x2,y2 in ((300,40,500,40),(300,100,500,100),
                          (300,40,300,100),(400,40,400,100),(500,40,500,100)):
        count=int(max(abs(x2-x1),abs(y2-y1))/5)
        for i in range(count):
            page.draw_line((x1+(x2-x1)*i/count,y1+(y2-y1)*i/count),
                           (x1+(x2-x1)*(i+1)/count,y1+(y2-y1)*(i+1)/count))
    page.insert_text((320,75),'Container',fontsize=8)
    page.insert_text((420,75),'Container',fontsize=8)


def run(output):
    root=Path(output).resolve()
    if root.exists(): raise ValueError('Fresh planning pilot smoke output required')
    root.mkdir(parents=True)
    source=root/'synthetic-original.pdf'
    with pymupdf.open() as document:
        page=document.new_page(width=600,height=500)
        page.draw_rect((30,30,190,140));page.insert_text((50,80),'Footpath',fontsize=10)
        draw_component_fixture(page)
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
        if summary.get('closed_source_outlines')!=1 or summary.get('nominal_view_outlines',0)<1:
            raise ValueError('Closed outline inventory and nominal regional geometry were not retained')
        if not result['pages'][0].get('outline_overlay'):
            raise ValueError('Source-bound outline preview missing')
        if summary.get('path_plaza_outline_hints')!=1 or summary.get('source_outline_role_hints')!=1:
            raise ValueError('Visible source-label enclosure hint missing')
        if summary.get('component_boundary_candidates')!=2:
            raise ValueError('Fine linework did not recover two separate component boundaries')
        if summary.get('components_with_nominal_scale_trials')!=2:
            raise ValueError('Nominal component scale trials were not retained')
        page_evidence=json.loads((pack/result['pages'][0]['evidence_file']).read_text(encoding='utf-8'))
        components=page_evidence['component_footprints']
        if (not components['analysis_complete'] or len({r['source_outline']['candidate_id'] for r in components['candidates']})!=2
                or any(r['physical_identity_verified'] or r['world_placement_eligible'] for r in components['candidates'])):
            raise ValueError('Separate source components or acceptance boundaries changed')
        measurement_review=json.loads((pack/'component-measurements.json').read_text())
        if measurement_review['local_3d_components'] or measurement_review['physical_component_footprints_verified']:
            raise ValueError('Missing height or unverified source footprints became a 3D building')
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
        'source_label_hints_verified':True,
        'component_boundaries_verified':True,
        'component_measurements_verified':True,
        'real_park_accuracy_assessed':False,'world_placement_eligible':False,
        'training_labels_generated':0,'model_promoted':False}
    write_json(root/'planning-pilot-smoke.json',receipt)
    return receipt
