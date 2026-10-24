"""Exercise cached synthetic web evidence through the actual managed worker."""
import json
from pathlib import Path
from unittest.mock import patch

from .desktop_runtime import DesktopRuntime, _wait, write_json
from . import web_evidence as web


def run(output):
    root=Path(output).resolve()
    if root.exists(): raise ValueError('Fresh web smoke output required')
    root.mkdir(parents=True);cache=root/'memory'/'web-cache'
    class Response:
        status_code=200
        headers={'Content-Type':'text/html'}
        def iter_content(self,*args): yield b'<html><title>Synthetic planning fixture</title>Footpath width: 2 m.</html>'
        def close(self): pass
    # Only this fixture construction replaces the transport. The submitted
    # worker uses production cache validation and never contacts the network.
    import requests
    session=requests.Session()
    try:
        with patch.object(session,'get',return_value=Response()):
            item=web.fetch('https://example.org/',cache,['example.org'],session=session,
                resolver=lambda *args,**kwargs:[(2,1,6,'',('93.184.216.34',443))])
    finally:session.close()
    runtime=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
    try:
        jid=runtime.submit_web(urls=['https://example.org/'],allowed_hosts=['example.org'],offline=True)
        job=_wait(runtime,jid,timeout=60);runtime._futures[jid].result(timeout=10)
        if job['status']!='completed': raise ValueError('Managed web worker failed: '+str(job.get('error')))
        result=job['result']
        if len(result['sources'])!=1 or result['sources'][0]['citation_id']!=item['source']['citation_id']:
            raise ValueError('Managed web worker lost original-source citation')
        if result['network_bytes'] or result['operational_proposals_executed'] or result['training_labels_generated']:
            raise ValueError('Offline web research performed unintended operations')
        if runtime.store.summary()['feedback_records'] or runtime.store.summary()['checkpoints']:
            raise ValueError('Web observations changed reviewed learning data')
    finally:runtime.close(wait=True)
    runtime=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
    try:
        if runtime.store.job(jid)['result']['sources']!=result['sources']:
            raise ValueError('Web research history did not survive restart')
        with runtime.store.connect() as db:
            rows=db.execute("SELECT payload FROM knowledge WHERE kind='web_source_observation'").fetchall()
        if len(rows)!=1 or json.loads(rows[0][0])['citation_id']!=item['source']['citation_id']:
            raise ValueError('Cited source observation did not survive restart')
    finally:runtime.close(wait=True)
    receipt={'status':'passed','dataset_kind':'synthetic','job':job,
        'offline_worker_verified':True,'persistent_restart_verified':True,
        'real_public_network_assessed':False,'installed_model_inference_assessed':False,
        'source_evidence_verified':False,'training_labels_generated':0}
    write_json(root/'web-smoke.json',receipt)
    return receipt
