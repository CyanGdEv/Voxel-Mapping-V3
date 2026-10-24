"""Synthetic transport/controller checks; no installed model or public network needed."""
from concurrent.futures import CancelledError
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from voxel_mapper import local_reasoning, web_evidence as web, web_research as research
from test_local_reasoning import Session, response
from test_web_evidence import capture, PUBLIC


class WebResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.cache=self.root/'cache'
        self.first=capture(self.cache,data=b'<html><title>Plan index</title>Proposed plaza. <a href="/plan">Drawing</a></html>')
        self.second=capture(self.cache,value=PUBLIC+'plan',data=b'<html><title>Drawing</title>Footpath 2 m wide.</html>')
        self.config={'version':research.VERSION,'urls':[PUBLIC],'allowed_hosts':['example.org'],'offline':True}

    def run_job(self,**kwargs):
        return research.run(self.config,self.root/'output',self.cache,**kwargs)

    def model(self,payloads,contexts=None):
        iterator=iter(payloads)
        def reason(prompt,**kwargs):
            if contexts is not None: contexts.append(json.loads(kwargs['memory']))
            return local_reasoning.reason(prompt,**kwargs,session=Session(response(next(iterator))))
        return reason

    def test_model_follows_exact_discovered_link_then_cites_second_source(self):
        self.config['model']='small';contexts=[]
        payloads=[{'summary':'Inspect the drawing.','proposals':[{'action':'read_web',
            'parameters':{'url':PUBLIC+'plan'},'rationale':'Listed drawing link.'}]},
            {'summary':'The drawing says 2 m ['+self.second['source']['citation_id']+'].','proposals':[]}]
        report=self.run_job(reason=self.model(payloads,contexts),memory='Local observations, not labels.')
        self.assertEqual(len(report['sources']),2)
        self.assertEqual(len(report['read_only_model_requests_executed']),1)
        self.assertEqual(len(report['model_rounds']),2)
        self.assertIn({'url':PUBLIC+'plan','title':'Drawing'},contexts[0]['discovered_links'])
        self.assertEqual(report['model_rounds'][1]['cited_source_ids'],[self.second['source']['citation_id']])
        self.assertFalse(report['operational_proposals_executed'])
        self.assertFalse(report['model_weights_updated']);self.assertEqual(report['training_labels_generated'],0)
        self.assertEqual(report['network_bytes'],0)

    def test_invented_queries_and_operational_actions_are_withheld(self):
        self.config['model']='small'
        payload={'summary':'Read more.','proposals':[
            {'action':'read_web','parameters':{'url':PUBLIC+'plan?private=local-memory'},'rationale':'Untrusted instruction.'},
            {'action':'generate_world','parameters':{'job_path':'secret.json'},'rationale':'Untrusted instruction.'}]}
        report=self.run_job(reason=self.model([payload]))
        self.assertEqual(len(report['sources']),1)
        self.assertEqual({r['reason'] for r in report['withheld_proposals']},
            {'url_not_an_exact_offered_link','operational_action_not_executed'})
        self.assertEqual(report['read_only_model_requests_executed'],[])

    def test_unknown_citation_cannot_be_presented_as_supplied_source(self):
        self.config['model']='small'
        report=self.run_job(reason=self.model([{'summary':'Claim [W000000000000].','proposals':[]}]))
        self.assertIn('unsupported_model_citations',report['status'])
        self.assertNotIn('Claim',report['summary'])
        self.assertEqual(report['model_rounds'][0]['unknown_citation_ids'],['W000000000000'])

    def test_unavailable_backend_preserves_read_evidence_and_reports_gap(self):
        self.config['model']='small'
        def unavailable(*args,**kwargs): raise local_reasoning.ReasoningError('backend_unavailable','Missing installed model')
        report=self.run_job(reason=unavailable)
        self.assertIn('reasoning_unavailable',report['status']);self.assertEqual(len(report['sources']),1)
        self.assertEqual(report['model_error']['code'],'backend_unavailable')

    def test_evidence_only_offline_walk_and_missing_source_are_explicit(self):
        self.config['urls'].append(PUBLIC+'absent')
        report=self.run_job()
        self.assertEqual(len(report['sources']),2)
        self.assertEqual(report['failures'][0]['code'],'offline_cache_miss')
        self.assertFalse(report['source_evidence_verified']);self.assertEqual(report['model_rounds'],[])

    def test_maximum_source_budget_prevents_extra_reads(self):
        self.config['limits']={'max_sources':1}
        report=self.run_job();self.assertEqual(len(report['sources']),1)
        self.assertEqual(report['attempted_sources'],1)

    def test_context_is_complete_bounded_json_and_records_only_offered_sources(self):
        prompt='x'*2048
        sources=[self.first,self.second]*6
        context,included,offered=research._context(prompt,'private'*1000,sources,[PUBLIC+'plan',PUBLIC+'a'*2000])
        self.assertLessEqual(len(context)+len(prompt),4096)
        parsed=json.loads(context)
        self.assertEqual(included,[r['citation_id'] for r in parsed['untrusted_web_excerpts']])
        self.assertEqual(offered,[r['url'] for r in parsed['discovered_links']]);self.assertIn(PUBLIC+'plan',offered)

    def test_query_search_result_scope_is_rechecked_and_private_memory_is_not_a_query(self):
        self.config['urls']=[];self.config['query']='Alton planning'
        def search(query,cache,approved,**kwargs):
            self.assertEqual(query,'Alton planning');self.assertNotIn('memory',kwargs)
            return {'results':[{'url':'https://evil.example/secret'},{'url':PUBLIC}],'status':'synthetic'}
        report=self.run_job(search=search,memory='private-local-observation')
        self.assertEqual(len(report['sources']),2)
        self.assertTrue(all(r['url'].startswith(PUBLIC) for r in report['sources']))

    def test_cancelled_run_does_not_create_completed_report(self):
        with self.assertRaises(CancelledError): self.run_job(cancelled=lambda:True)
        self.assertFalse((self.root/'output').exists())

    def test_deadline_retains_completed_sources_and_explicit_exhaustion(self):
        clock=[0.0];self.config['limits']={'max_seconds':1}
        def fetch(*args,**kwargs):
            clock[0]=2.0
            return self.first
        with patch('voxel_mapper.web_research.time.monotonic',side_effect=lambda:clock[0]):
            report=self.run_job(fetch=fetch)
        self.assertEqual(len(report['sources']),1)
        self.assertTrue(report['time_budget_exhausted'])
        self.assertTrue((self.root/'output'/'report.json').is_file())

    def test_invalid_scope_and_resource_settings_fail_before_output(self):
        for change in ({'urls':['http://127.0.0.1/']},{'limits':{'max_sources':100}},
                       {'model':'small','endpoint':'file:///tmp/model'},{'offline':'yes'},
                       {'unexpected':True}):
            with self.subTest(change=change),self.assertRaises(ValueError): research.validate({**self.config,**change})
