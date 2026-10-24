from concurrent.futures import CancelledError
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from voxel_mapper import planning_collection as collection
from voxel_mapper import web_evidence as web,web_research,web_planning_pilot as pilot
from voxel_mapper.desktop_memory import digest
from test_web_evidence import PUBLIC,Response,Session,resolver
from test_web_planning_pilot import pdf


def fixture(cache,count=7,missing=(),duplicate_last=False):
    data=[]
    for number in range(count):
        data.append(pdf(['Proposed Ground Floor Plan | 1:100']))
    if duplicate_last:data[-1]=data[0]
    index=('<html><main>APP/1 '+''.join('<a href="/plan-'+str(i)+'.pdf">Drawing '+str(i)+'</a>' for i in range(count))+'</main></html>').encode()
    for value,body in [(PUBLIC,index)]+[(PUBLIC+'plan-'+str(i)+'.pdf',v) for i,v in enumerate(data) if i not in missing]:
        web.fetch(value,cache,['example.org'],session=Session([Response(body)]),resolver=resolver)
    return {'version':collection.VERSION,'pilot':{'version':pilot.VERSION,'area_id':'synthetic collection',
        'application_reference':'APP/1','research':{'version':web_research.VERSION,
            'urls':[PUBLIC],'allowed_hosts':['example.org'],'offline':True,'refresh':False}}},data


class PlanningCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.cache=self.root/'cache';self.storage=self.root/'state'
        self.config,self.data=fixture(self.cache)

    def run_job(self,name='output',**kwargs):
        return collection.run(self.config,self.root/name,self.cache,self.storage,**kwargs)

    def test_changed_geometry_dependencies_create_a_fresh_analysis_scope(self):
        original=collection.collection_key(self.config)
        fingerprint=pilot.planning._implementation
        for module in (pilot.planning.drawing_geometry,pilot.planning.linework_boundaries,
                       pilot.planning.drawing_page_tools):
            def changed(value):
                return {'basis':'module_file_bytes','sha256':'f'*64} if value is module else fingerprint(value)
            with patch.object(pilot.planning,'_implementation',side_effect=changed):
                self.assertNotEqual(collection.collection_key(self.config),original)

    def test_followup_batches_finish_more_than_six_sources_from_one_request(self):
        result=self.run_job()
        self.assertEqual(result['summary']['completed_batches'],2)
        self.assertEqual(result['summary']['completed_sources'],8)
        self.assertEqual(result['summary']['completed_pages'],7)
        self.assertEqual(result['summary']['unique_originals_handed_to_analysis'],7)
        self.assertEqual(result['unresolved_sources'],[])
        self.assertEqual(result['network_bytes'],0)
        self.assertFalse(result['source_discovery_exhaustive'])
        self.assertEqual(result['training_labels_generated'],0);self.assertFalse(result['world_placement_eligible'])
        self.assertIn('batch-0002/review.html',(self.root/'output/review.html').read_text())

    def test_restart_reuses_completed_analyses_and_continues_pending_documents(self):
        self.config['limits']={'max_batches':1}
        first=self.run_job('first');self.assertEqual(first['summary']['completed_pages'],5)
        self.assertEqual(len(first['unresolved_sources']),2)
        self.config['limits']={};calls=[]
        def run_batch(*args,**kwargs):
            calls.append(args[0]['research']['urls']);return pilot.run(*args,**kwargs)
        second=self.run_job('second',run_batch=run_batch)
        self.assertEqual(len(calls),1);self.assertEqual(second['summary']['completed_pages'],7)
        def forbidden(*args,**kwargs):raise AssertionError('Completed analysis was rerun')
        third=self.run_job('third',run_batch=forbidden)
        self.assertEqual(third['summary']['new_batches'],0)

    def test_duplicate_bytes_in_later_batch_are_not_reanalysed(self):
        self.config,self.data=fixture(self.cache,count=6,duplicate_last=True)
        result=self.run_job()
        self.assertEqual(result['summary']['completed_sources'],7)
        self.assertEqual(result['summary']['unique_originals_handed_to_analysis'],5)
        self.assertEqual(result['summary']['completed_pages'],5)

    def network_batch(self,fetch):
        def research(*args,**kwargs):return web_research.run(*args,**kwargs,fetch=fetch)
        def batch(*args,**kwargs):return pilot.run(*args,**kwargs,research=research)
        return batch

    def test_temporary_http_failure_retries_and_permanent_404_remains_a_gap(self):
        self.config,self.data=fixture(self.cache,count=2)
        self.config['pilot']['research']['offline']=False
        counts={};clock=[100.0]
        def fetch(value,cache,approved,**kwargs):
            counts[value]=counts.get(value,0)+1
            if value==PUBLIC+'plan-0.pdf' and counts[value]==1:
                raise web.WebError('http_status','HTTP 503',http_status=503)
            if value==PUBLIC+'plan-1.pdf':raise web.WebError('http_status','HTTP 404',http_status=404)
            return web.fetch(value,cache,approved,offline=True)
        result=self.run_job(run_batch=self.network_batch(fetch),clock=lambda:clock[0],pause=lambda n:clock.__setitem__(0,clock[0]+n))
        self.assertEqual(counts[PUBLIC+'plan-0.pdf'],2)
        self.assertEqual(counts[PUBLIC+'plan-1.pdf'],1)
        self.assertEqual(result['summary']['completed_pages'],1)
        self.assertEqual(result['unresolved_sources'][0]['error']['http_status'],404)

    def test_retry_limit_stops_repeated_503_and_honours_retry_after(self):
        self.config,self.data=fixture(self.cache,count=1)
        self.config['pilot']['research']['offline']=False;self.config['limits']={'max_attempts':2}
        clock=[0.0];calls=[]
        def fetch(value,cache,approved,**kwargs):
            if value!=PUBLIC:
                calls.append(clock[0]);raise web.WebError('http_status','HTTP 503',http_status=503,retry_after_seconds=5)
            return web.fetch(value,cache,approved,offline=True)
        result=self.run_job(run_batch=self.network_batch(fetch),clock=lambda:clock[0],pause=lambda n:clock.__setitem__(0,clock[0]+n))
        self.assertEqual(len(calls),2);self.assertGreaterEqual(calls[1]-calls[0],5)
        self.assertEqual(result['unresolved_sources'][0]['attempts'],2)
        self.assertEqual(result['unresolved_sources'][0]['status'],'unavailable')

    def test_cached_refresh_failure_retries_without_reanalysing_identical_original(self):
        self.config,self.data=fixture(self.cache,count=1)
        self.config['pilot']['research'].update(offline=False,refresh=True)
        calls=[0];clock=[0.0]
        def fetch(value,cache,approved,**kwargs):
            if value==PUBLIC:return web.fetch(value,cache,approved,offline=True)
            calls[0]+=1
            response=Response(status=503) if calls[0]==1 else Response(self.data[0])
            return web.fetch(value,cache,approved,session=Session([response]),resolver=resolver,
                budget=kwargs['budget'],deadline=kwargs['deadline'])
        result=self.run_job(run_batch=self.network_batch(fetch),clock=lambda:clock[0],pause=lambda n:clock.__setitem__(0,clock[0]+n))
        self.assertEqual(calls[0],2)
        self.assertEqual(result['unresolved_sources'],[])
        self.assertEqual(result['summary']['completed_pages'],1)
        self.assertEqual(result['summary']['unique_originals_handed_to_analysis'],1)

    def test_offline_misses_resume_when_original_is_later_available_online(self):
        self.cache=self.root/'missing-cache'
        self.config,self.data=fixture(self.cache,count=1,missing=(0,))
        first=self.run_job('offline')
        self.assertEqual(first['unresolved_sources'][0]['status'],'offline_missing')
        self.assertEqual(first['unresolved_sources'][0]['attempts'],0)
        web.fetch(PUBLIC+'plan-0.pdf',self.cache,['example.org'],session=Session([Response(self.data[0])]),resolver=resolver)
        self.config['pilot']['research']['offline']=False
        result=self.run_job('online')
        self.assertEqual(result['summary']['completed_pages'],1)
        self.assertEqual(result['unresolved_sources'],[])

    def test_search_only_request_discovers_and_collects_all_drawing_links(self):
        self.config['pilot']['research'].update(urls=[],query='Planning fixture')
        def research(*args,**kwargs):
            return web_research.run(*args,**kwargs,search=lambda *a,**k:{'status':'synthetic','results':[{'url':PUBLIC}]})
        def batch(*args,**kwargs):return pilot.run(*args,**kwargs,research=research)
        result=self.run_job(run_batch=batch)
        self.assertEqual(result['summary']['completed_pages'],7)

    def test_unavailable_search_remains_pending_and_can_be_resumed(self):
        self.config['pilot']['research'].update(urls=[],query='Planning fixture')
        def research(*args,**kwargs):
            return web_research.run(*args,**kwargs,search=lambda *a,**k:{'status':'unavailable','results':[]})
        def batch(*args,**kwargs):return pilot.run(*args,**kwargs,research=research)
        result=self.run_job('empty',run_batch=batch)
        self.assertTrue(result['initial_search_pending'])
        self.assertEqual(result['stop_reason'],'search_unavailable_or_no_results')
        def available(*args,**kwargs):
            return web_research.run(*args,**kwargs,search=lambda *a,**k:{'status':'synthetic','results':[{'url':PUBLIC}]})
        def resumed(*args,**kwargs):return pilot.run(*args,**kwargs,research=available)
        result=self.run_job('available',run_batch=resumed)
        self.assertFalse(result['initial_search_pending'])
        self.assertEqual(result['summary']['completed_pages'],7)

    def test_shared_execution_byte_budget_is_not_reset_by_followup_batches(self):
        self.config['pilot']['research']['offline']=False
        self.config['limits']={'max_run_bytes':650}
        def fetch(value,cache,approved,**kwargs):
            if kwargs['budget'].exhausted:raise web.WebError('byte_budget','Global budget exhausted')
            kwargs['budget'].take(100)
            return web.fetch(value,cache,approved,offline=True)
        result=self.run_job(run_batch=self.network_batch(fetch))
        self.assertEqual(result['network_bytes'],700)
        self.assertEqual(result['stop_reason'],'byte_budget_reached')
        self.assertEqual(result['summary']['completed_sources'],6)
        self.assertEqual(len(result['unresolved_sources']),2)

    def test_cancelled_after_completed_batch_resumes_without_repeating_it(self):
        cancelled=[False]
        def batch(*args,**kwargs):
            result=pilot.run(*args,**kwargs);cancelled[0]=True;return result
        with self.assertRaises(CancelledError):self.run_job('cancelled',run_batch=batch,cancelled=lambda:cancelled[0])
        self.assertFalse((self.root/'cancelled/report.json').exists())
        result=self.run_job('resumed')
        self.assertEqual(result['summary']['completed_batches'],2)
        self.assertEqual(result['summary']['new_batches'],1)

    def test_complete_orphan_batch_is_recovered_after_worker_interruption(self):
        def batch(*args,**kwargs):
            pilot.run(*args,**kwargs);raise CancelledError('Killed before ledger commit')
        with self.assertRaises(CancelledError):self.run_job('interrupted',run_batch=batch)
        result=self.run_job('recovered')
        self.assertEqual(result['summary']['completed_batches'],2)
        self.assertEqual(result['summary']['new_batches'],1)

    def test_changed_saved_original_blocks_reuse_before_any_new_requests(self):
        self.config['limits']={'max_batches':1};self.run_job('first')
        original=next((self.storage/'batches').rglob('originals/*.pdf'));original.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'output changed'):self.run_job('changed')

    def test_saved_windows_path_separators_are_verified_and_resumed(self):
        self.config['limits']={'max_batches':1};self.run_job('first')
        path=self.storage/'ledger.json';state=json.loads(path.read_text())
        report_path=self.storage/'batches/batch-0001/report.json'
        report=json.loads(report_path.read_text())
        report['output_sha256']={k.replace('/','\\'):v for k,v in report['output_sha256'].items()}
        report_path.write_text(json.dumps(report))
        from voxel_mapper.generation_cycles import file_hash
        state['batches'][0]['report_sha256']=file_hash(report_path)
        state['artifact_sha256']=digest({k:v for k,v in state.items() if k!='artifact_sha256'})
        path.write_text(json.dumps(state));self.config['limits']={}
        result=self.run_job('resumed')
        self.assertEqual(result['summary']['completed_pages'],7)

    def test_resealed_fake_completed_entry_cannot_skip_an_unread_source(self):
        self.config['limits']={'max_batches':1};self.run_job('first')
        path=self.storage/'ledger.json';state=json.loads(path.read_text())
        pending=next(v for v in state['entries'].values() if v['status']=='pending')
        pending.update(status='completed',body_sha256='0'*64)
        state['artifact_sha256']=digest({k:v for k,v in state.items() if k!='artifact_sha256'})
        path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError,'no verified source batch'):self.run_job('fake')

    def test_url_quota_is_explicit_and_can_resume_with_a_larger_execution_limit(self):
        self.config['pilot']['research']['limits']={'max_sources':2}
        self.config['limits']={'max_urls':2}
        result=self.run_job('small')
        self.assertTrue(result['queue_overflow']);self.assertEqual(result['stop_reason'],'url_budget_reached')
        self.config['limits']={'max_urls':16}
        result=self.run_job('larger')
        self.assertFalse(result['queue_overflow']);self.assertEqual(result['summary']['completed_sources'],8)

    def test_validation_rejects_unbounded_limits_and_private_scopes(self):
        for change in ({'limits':{'max_batches':100}},{'limits':{'max_attempts':True}},{'unexpected':True}):
            with self.subTest(change=change),self.assertRaises(ValueError):collection.validate({**self.config,**change})
        config=deepcopy(self.config);config['pilot']['research']['urls']=['http://127.0.0.1/']
        with self.assertRaises(ValueError):collection.validate(config)

    def test_execution_mode_changes_resume_same_scope_but_changed_analysis_does_not(self):
        original=collection.collection_key(self.config)
        changed=deepcopy(self.config)
        changed['pilot']['research'].update(offline=False,refresh=True,model='small')
        changed['limits']={'max_batches':1}
        changed['pilot']['area_id']='A different display title'
        self.assertEqual(collection.collection_key(changed),original)
        changed['pilot']['analysis_options']={'max_document_pages':1}
        self.assertNotEqual(collection.collection_key(changed),original)
