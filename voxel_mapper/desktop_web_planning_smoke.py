"""Synthetic cached application-to-drawings check in the actual managed worker."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pymupdf
import requests

from . import web_evidence as web
from .desktop_runtime import DesktopRuntime, _wait, write_json
from .desktop_planning_smoke import draw_component_fixture


def seed(cache):
    with pymupdf.open() as document:
        for index,text in enumerate(('Proposed Ground Floor Plan | 1:100','Proposed Front Elevation')):
            page=document.new_page(width=600,height=500)
            page.draw_rect((30,30,190,140));page.insert_text((50,80),'Footpath',fontsize=10)
            draw_component_fixture(page)
            page.insert_text((30,190),text,fontsize=10)
            page.insert_text((30,450),'DEMO-AA-BB-CC-DR-A-'+('0201' if index==0 else '0301'),fontsize=8)
            if index==0:page.insert_text((500,450),'0301',fontsize=8)
            else:page.insert_text((30,240),'2 No. 2.1m x 3.5m Shipping containers.',fontsize=8)
        data=document.tobytes()
    class Response:
        status_code=200
        headers={'Content-Type':'text/html'}
        def __init__(self,body):self.body=body
        def iter_content(self,*args):yield self.body
        def close(self):pass
    session=requests.Session()
    try:
        for value,body in (('https://example.org/',b'<html><main>APP/1 <a href="/drawing">Proposed floor plan</a></main></html>'),
                           ('https://example.org/drawing',data)):
            with patch.object(session,'get',return_value=Response(body)):
                web.fetch(value,cache,['example.org'],session=session,
                    resolver=lambda *args,**kwargs:[(2,1,6,'',('93.184.216.34',443))])
    finally:session.close()
    return hashlib.sha256(data).hexdigest()


def run(output):
    root=Path(output).resolve()
    if root.exists():raise ValueError('Fresh automatic web planning smoke output required')
    root.mkdir(parents=True);sha=seed(root/'memory'/'web-cache')
    runtime=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
    try:
        jid=runtime.submit_web_planning('APP/1',urls=['https://example.org/'],
            allowed_hosts=['example.org'],offline=True)
        job=_wait(runtime,jid,timeout=90);runtime._futures[jid].result(timeout=10)
        if job['status']!='completed':raise ValueError('Automatic web planning worker failed: '+str(job.get('error')))
        result=job['result'];pack=Path(job['output_directory'])
        if result['summary']['completed_pages']!=2 or result['summary']['surface_candidates']!=1:
            raise ValueError('Application link did not produce page-specific drawing analysis')
        if result['handoffs'][0]['page_roles']!={'1':'floor-plan','2':'elevation'}:
            raise ValueError('Drawing page roles were lost')
        if result['summary'].get('component_boundary_candidates')!=2:
            raise ValueError('Automatic web planning lost fine component boundary candidates')
        if result['summary'].get('size_consistent_component_hypotheses')!=2:
            raise ValueError('Automatic web planning lost linked printed-size diagnostics')
        if hashlib.sha256((pack/'originals'/(sha+'.pdf')).read_bytes()).hexdigest()!=sha:
            raise ValueError('Original web PDF bytes changed')
        for name,pin in result['output_sha256'].items():
            if hashlib.sha256((pack/name).read_bytes()).hexdigest()!=pin:
                raise ValueError('Automatic planning pack output hash mismatch')
        if result['training_labels_generated'] or result['world_placement_eligible'] or result['geometric_accuracy'] is not None:
            raise ValueError('Source handoff asserted physical acceptance or training labels')
        if runtime.store.summary()['feedback_records'] or runtime.store.summary()['checkpoints']:
            raise ValueError('Source handoff changed reviewed learning data')
    finally:runtime.close(wait=True)
    runtime=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
    try:
        if runtime.store.job(jid)['result']['summary']!=result['summary']:
            raise ValueError('Automatic web planning history did not survive restart')
        with runtime.store.connect() as db:
            count=db.execute("SELECT COUNT(*) FROM knowledge WHERE kind='web_source_observation'").fetchone()[0]
        if count!=2:raise ValueError('Web source memory did not retain both application and drawing')
    finally:runtime.close(wait=True)
    receipt={'status':'passed','dataset_kind':'synthetic','job':job,
        'single_application_url_to_original_analysis':True,'page_roles_verified':True,
        'component_boundaries_verified':True,
        'component_measurements_verified':True,
        'original_and_output_hashes_verified':True,'persistent_restart_verified':True,
        'public_network_assessed':False,'installed_model_inference_assessed':False,
        'training_labels_generated':0,'world_placement_eligible':False}
    write_json(root/'web-planning-smoke.json',receipt)
    return receipt
