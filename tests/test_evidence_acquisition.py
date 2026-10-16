import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf
import requests

from voxel_mapper.evidence_acquisition import run,options
from voxel_mapper.generation_cycles import file_hash
from voxel_mapper.planning_bulk import Corpus
from voxel_mapper.reconstruction_evidence_queue import build


class EvidenceAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.corpus=Corpus(self.root/'corpus');self.hosts=['portal.test']
        self.queue=self.root/'queue';self.queue.mkdir()
        with pymupdf.open() as pdf:
            page=pdf.new_page();page.insert_text((20,40),'EXISTING FLOOR PLAN 1:100')
            self.pdf=pdf.tobytes()
        self.sha=hashlib.sha256(self.pdf).hexdigest()
        self.url='https://portal.test/required-survey'
        self.corpus.ingest([{'url':self.url,'title':'Topographical survey and site plan','sha256':self.sha},
            {'url':'https://portal.test/aaa-unrelated','title':'Ecology report'}],self.hosts)
        self.write_queue(build('alton-test',[{'document_sha256':'a'*64,'page':1}]))

    def tearDown(self):self.corpus.close();self.temp.cleanup()

    def write_queue(self,queue):
        (self.queue/'missing-evidence.json').write_text(json.dumps(queue))
        (self.queue/'queue-report.json').write_text(json.dumps({'output_sha256':file_hash(self.queue/'missing-evidence.json')}))

    def execute(self,**kwargs):
        return run(self.corpus,self.queue,self.root/'acquisition',official_hosts=self.hosts,offline=False,**kwargs)

    def test_download_rematches_original_text_and_resume_requests_nothing(self):
        requests_seen=[]
        first=self.execute(fetch=lambda url:(requests_seen.append(url) or self.pdf))
        self.assertEqual(requests_seen,[self.url]);self.assertEqual(first['new_downloads'],1)
        self.assertEqual(first['before_matching']['pages_examined'],0)
        self.assertEqual(first['after_matching']['pages_examined'],1)
        self.assertGreater(first['after_matching']['candidate_hits'],0)
        self.assertEqual(first['run_network_bytes'],len(self.pdf))
        with patch('voxel_mapper.planning_bulk.requests.Session',side_effect=AssertionError('unexpected network')):
            again=self.execute()
        self.assertEqual(again['run_attempts'],0)
        self.assertEqual(again['charged_network_bytes'],len(self.pdf))
        self.assertEqual(again['after_matching']['requirements_resolved'],0)
        self.assertFalse(again['geometry_export_authorized'])
        self.assertEqual(self.corpus.db.execute('SELECT attempts FROM downloads WHERE url=?',('https://portal.test/aaa-unrelated',)).fetchone()[0],0)

    def test_failed_request_is_not_repeated_even_with_a_new_queue_or_catalogue_entry(self):
        seen=[]
        def failed(url):seen.append(url);raise requests.HTTPError('502 Bad Gateway')
        first=self.execute(fetch=failed);self.assertEqual(first['attempts'][0]['status'],'failed')
        self.write_queue(build('alton-test',[{'document_sha256':'b'*64,'page':1}]))
        other='https://portal.test/second-plan'
        self.corpus.ingest([{'url':other,'title':'Existing site plan','sha256':self.sha}],self.hosts)
        second=self.execute(fetch=lambda url:(seen.append(url) or self.pdf))
        self.assertEqual(seen,[self.url,other]);self.assertEqual(second['run_attempts'],1)
        self.assertEqual(self.corpus.db.execute('SELECT attempts FROM downloads WHERE url=?',(self.url,)).fetchone()[0],1)

    def test_crash_before_or_after_acquisition_is_not_blindly_retried(self):
        for phase in ['after_intent','after_acquire']:
            with self.subTest(phase=phase):
                output=self.root/phase;seen=[]
                def crash(event,url):
                    if event==phase:raise RuntimeError('simulated process stop')
                def execute(**kwargs):
                    return run(self.corpus,self.queue,output,official_hosts=self.hosts,offline=False,**kwargs)
                # Each scenario starts with the same pending resource.
                with self.corpus.db:self.corpus.db.execute("UPDATE downloads SET status='pending',sha=NULL,attempts=0 WHERE url=?",(self.url,))
                (self.corpus.root/'files'/(self.sha+'.pdf')).unlink(missing_ok=True)
                with self.assertRaisesRegex(RuntimeError,'process stop'):
                    execute(fetch=lambda url:(seen.append(url) or self.pdf),fault=crash)
                resumed=execute(fetch=lambda _:self.fail('interrupted resource requested twice'))
                self.assertEqual(resumed['run_attempts'],0)
                self.assertTrue(resumed['attempts'][0]['recovered_after_interruption'])
                self.assertEqual(len(seen),int(phase=='after_acquire'))
                self.assertEqual(resumed['after_matching']['pages_examined'],int(phase=='after_acquire'))

    def test_document_budget_survives_restart_and_inventory_growth(self):
        policy={'max_documents':1}
        self.execute(settings=policy,fetch=lambda _:self.pdf)
        self.corpus.ingest([{'url':'https://portal.test/new-plan','title':'Existing site plan'}],self.hosts)
        result=self.execute(settings=policy,fetch=lambda _:self.fail('lifetime document budget exceeded'))
        self.assertEqual(result['run_attempts'],0);self.assertEqual(result['remaining_unattempted_candidates'],1)
        with self.assertRaisesRegex(ValueError,'policy changed'):self.execute(settings={'max_documents':2})

    def test_byte_budget_is_shared_across_documents_and_restarts(self):
        self.corpus.ingest([{'url':'https://portal.test/zzz-plan','title':'Existing floor plan'}],self.hosts)
        policy={'max_file_bytes':len(self.pdf),'max_run_bytes':len(self.pdf)}
        first=self.execute(settings=policy,fetch=lambda _:self.pdf)
        self.assertEqual(first['run_attempts'],1)
        self.assertEqual(first['charged_network_bytes'],len(self.pdf))
        again=self.execute(settings=policy,fetch=lambda _:self.fail('shared byte budget exceeded'))
        self.assertEqual(again['run_attempts'],0)
        self.assertEqual(again['remaining_unattempted_candidates'],1)

    def test_pinned_source_mismatch_never_becomes_evidence(self):
        with pymupdf.open() as pdf:
            pdf.new_page();wrong=pdf.tobytes()
        result=self.execute(fetch=lambda _:wrong)
        self.assertEqual(result['new_downloads'],0)
        self.assertIn('Pinned drawing changed',result['attempts'][0]['error'])
        self.assertEqual(result['after_matching']['pages_examined'],0)

    def test_offline_and_invalid_policies_cannot_make_requests(self):
        with patch('voxel_mapper.planning_bulk.requests.Session',side_effect=AssertionError('unexpected network')):
            result=run(self.corpus,self.queue,self.root/'offline',official_hosts=self.hosts,offline=True)
        self.assertEqual(result['run_attempts'],0);self.assertEqual(len(result['candidates']),1)
        for settings in [{'max_documents':True},{'max_documents':33},{'unknown':1}]:
            with self.subTest(settings=settings),self.assertRaises(ValueError):options(settings)
        with self.assertRaisesRegex(ValueError,'official HTTPS'):
            run(self.corpus,self.queue,self.root/'badhost',official_hosts=['different.test'])

    def test_empty_corpus_bootstraps_catalogue_drawings_without_invented_page_tasks(self):
        self.write_queue(build('alton-test',[]))
        result=self.execute(fetch=lambda _:self.pdf)
        self.assertTrue(result['catalogue_bootstrap'])
        self.assertEqual(result['new_downloads'],1)
        self.assertEqual(result['candidates'][0]['task_ids'],[])
        self.assertEqual(result['candidates'][0]['matching_basis'],'catalogue_bootstrap')
        self.assertEqual(result['requirements_resolved'],0)

    def test_source_queue_intent_receipt_and_output_tampering_reject(self):
        self.execute(fetch=lambda _:self.pdf)
        attempt=next((self.root/'acquisition/attempts').iterdir())
        for relative in ['acquisition-report.json',str(attempt.relative_to(self.root/'acquisition')/'receipt.json'),str(attempt.relative_to(self.root/'acquisition')/'intent.json')]:
            path=self.root/'acquisition'/relative;data=path.read_bytes();path.write_text('{}')
            try:
                with self.assertRaises((ValueError,KeyError)):self.execute()
            finally:path.write_bytes(data)
        (self.corpus.root/'files'/(self.sha+'.pdf')).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'source changed'):self.execute()

    def test_exact_acquisition_selection_never_falls_through_to_another_url(self):
        self.corpus.acquire(only_urls=[self.url],fetch=lambda _:self.pdf)
        seen=[]
        self.corpus.acquire(only_urls=[self.url],fetch=lambda url:seen.append(url))
        self.assertEqual(seen,[])
        for selection in [[],[self.url,self.url],['https://portal.test/unknown']]:
            with self.subTest(selection=selection),self.assertRaises(ValueError):
                self.corpus.acquire(only_urls=selection,offline=True)

    def test_area_runner_acquires_missing_plan_and_refreshes_native_interpretation(self):
        from tests import test_area_reconstruction as fixtures
        fixture=fixtures.AreaSourceTests();fixture.setUp()
        try:
            record={'applicationReference':'A','url':self.url,'title':'Topographical survey and site plan','sha256':self.sha}
            fixture.catalogue['entries'].append(record)
            (fixture.root/'catalogue.json').write_text(json.dumps(fixture.catalogue))
            fixture.config.update(offline=False,architectural_interpretation={'enabled':True},
                evidence_acquisition={'enabled':True})
            fixture.job.write_text(json.dumps(fixture.config))
            from voxel_mapper.area_reconstruction import run as area_run,run_all
            original=Corpus.acquire;seen=[]
            def acquire(corpus,**kwargs):
                kwargs['fetch']=lambda url:(seen.append(url) or self.pdf)
                return original(corpus,**kwargs)
            with patch.object(Corpus,'acquire',acquire):
                entry=area_run(fixture.job)['areas']['a']
                self.assertEqual(entry['evidence_acquisition']['new_downloads'],1)
                self.assertEqual(entry['extraction']['pages'],2)
                self.assertEqual(entry['architectural_interpretation']['pages'],2)
                self.assertEqual(entry['reconstruction_evidence_queue']['task_count'],4)
                self.assertEqual(entry['retained_evidence_matching']['pages_examined'],2)
                self.assertEqual(area_run(fixture.job)['areas']['a']['evidence_acquisition']['run_attempts'],0)
                self.assertIn('evidence_acquisition',run_all(fixture.job,stage='extract')['results'][0])
            self.assertEqual(seen,[self.url]);self.assertEqual(entry['world_geometry_additions'],0)
        finally:fixture.tearDown()
