"""Actual managed collection workers, multiple batches and restart without reanalysis."""
import hashlib
from pathlib import Path
from unittest.mock import patch

import pymupdf
import requests

from . import web_evidence as web
from .desktop_runtime import DesktopRuntime,_wait,write_json


def seed(cache):
    sources=[]
    for number in range(7):
        with pymupdf.open() as document:
            page=document.new_page(width=600,height=500)
            page.draw_rect((30,30,190,140));page.insert_text((50,80),'Footpath',fontsize=10)
            page.insert_text((30,190),'Proposed Ground Floor Plan | 1:100',fontsize=10)
            page.insert_text((30,450),'Synthetic document '+str(number),fontsize=10)
            sources.append(('https://example.org/plan-'+str(number)+'.pdf',document.tobytes()))
    index=('<html><main>APP/1 '+''.join('<a href="'+value+'">Drawing</a>' for value,_ in sources)+'</main></html>').encode()
    class Response:
        status_code=200
        headers={'Content-Type':'text/html'}
        def __init__(self,data):self.data=data
        def iter_content(self,*args):yield self.data
        def close(self):pass
    session=requests.Session()
    try:
        for value,data in [('https://example.org/',index)]+sources:
            with patch.object(session,'get',return_value=Response(data)):
                web.fetch(value,cache,['example.org'],session=session,
                    resolver=lambda *args,**kwargs:[(2,1,6,'',('93.184.216.34',443))])
    finally:session.close()


def run(output):
    root=Path(output).resolve()
    if root.exists():raise ValueError('Fresh planning collection smoke output required')
    root.mkdir(parents=True);seed(root/'memory'/'web-cache')
    def submit(runtime):
        jid=runtime.submit_web_planning('APP/1',urls=['https://example.org/'],
            allowed_hosts=['example.org'],offline=True,collect=True)
        job=_wait(runtime,jid,timeout=120);runtime._futures[jid].result(timeout=10)
        if job['status']!='completed':raise ValueError('Managed planning collection failed: '+str(job.get('error')))
        return job
    runtime=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
    try:
        first=submit(runtime);result=first['result'];pack=Path(first['output_directory'])
        if result['summary']['completed_batches']!=2 or result['summary']['completed_pages']!=7:
            raise ValueError('Automatic collection did not complete its follow-up batch')
        if result['summary']['completed_sources']!=8 or result['unresolved_sources']:
            raise ValueError('Known synthetic sources were left unread')
        if result['summary'].get('closed_source_outlines')!=7 or result['summary'].get('nominal_view_outlines',0)<7:
            raise ValueError('Automatic batches lost source outlines or nominal view measurements')
        if result['summary'].get('source_outline_role_hints')!=7 or result['summary'].get('path_plaza_outline_hints')!=7:
            raise ValueError('Automatic batches lost source-label enclosure hints')
        for name,pin in result['output_sha256'].items():
            if hashlib.sha256((pack/name).read_bytes()).hexdigest()!=pin:
                raise ValueError('Planning collection snapshot output changed')
    finally:runtime.close(wait=True)
    runtime=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
    try:
        if runtime.store.job(first['id'])['result']['summary']!=result['summary']:
            raise ValueError('Collection history did not survive restart')
        second=submit(runtime)
        if second['result']['summary']['new_batches']!=0 or second['result']['summary']['completed_pages']!=7:
            raise ValueError('Restart repeated completed drawing analysis')
        if runtime.store.summary()['feedback_records'] or runtime.store.summary()['checkpoints']:
            raise ValueError('Collection created reviewed labels or model checkpoints')
    finally:runtime.close(wait=True)
    receipt={'status':'passed','dataset_kind':'synthetic','first_job':first,'resumed_job':second,
        'multiple_automatic_batches_verified':True,'restart_without_reanalysis_verified':True,
        'original_and_output_hashes_verified':True,'network_bytes':result['network_bytes'],
        'source_label_hints_verified':True,
        'public_network_assessed':False,'installed_model_quality_assessed':False,
        'training_labels_generated':0,'world_placement_eligible':False}
    write_json(root/'planning-collection-smoke.json',receipt)
    return receipt
