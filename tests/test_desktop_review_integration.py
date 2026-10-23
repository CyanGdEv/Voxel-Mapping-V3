"""The visual review artifacts use real managed workers and durable feedback."""
import copy
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest

from voxel_mapper.desktop_review import bind_source,load_session,save_review
from voxel_mapper.desktop_runtime import DesktopRuntime,_wait,write_json
from voxel_mapper.reconstruction_benchmark import reference_digest


class DesktopReviewIntegrationTests(unittest.TestCase):
    @contextmanager
    def runtime(self,path):
        runtime=DesktopRuntime(path,workers=2,memory_budget_mb=2048)
        try:yield runtime
        finally:runtime.close(wait=True)

    def completed(self,runtime,jid):
        job=_wait(runtime,jid,timeout=30)
        runtime._futures[jid].result(timeout=10)
        self.assertEqual(job['status'],'completed',job.get('error'))
        return job

    def test_correction_draft_then_explicit_review_import_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);memory=root/'memory'
            with self.runtime(memory) as runtime:
                prepared=self.completed(runtime,runtime.submit_review('synthetic_demo'))['result']
                session=load_session(prepared['queue_path'],prepared['batch_path'])
                for path in prepared['source_paths']:session=bind_source(session,path)
                row=session['records'][0]
                correction={'type':'dimension','component_id':row['candidate']['spec']['components'][0]['id'],
                    'axis':'x','value_m':8.5,'source_sha256':row['source_sha256'][0],'source_page':1}
                original=copy.deepcopy(row['candidate'])
                draft=save_review(session,building_id=row['building_id'],candidate_sha256=row['candidate_sha256'],
                    outcome=None,review_basis=None,review_reference='',corrections=[correction],output_directory=root/'draft')
                self.assertIsNone(draft['feedback_path'])
                self.assertEqual(runtime.store.summary()['feedback_records'],0)
                reviewed=save_review(session,building_id=row['building_id'],candidate_sha256=row['candidate_sha256'],
                    outcome='rejected',review_basis='independent_review',
                    review_reference='Synthetic integration decision; no real building review claim',
                    corrections=[correction],output_directory=root/'reviewed')
                self.assertEqual(runtime.store.summary()['feedback_records'],0)
                imported=self.completed(runtime,runtime.submit_reviewed_feedback(reviewed['feedback_path']))
                self.assertEqual(imported['result']['imported'],1)
                self.assertEqual(runtime.store.feedback()[0]['candidate_sha256'],row['candidate_sha256'])
                self.assertEqual(runtime.store.feedback()[0]['outcome'],'rejected')
                self.assertEqual(session['records'][0]['candidate'],original)
                self.assertEqual(runtime.store.summary()['checkpoints'],0)
            with self.runtime(memory) as reopened:
                self.assertEqual(reopened.store.summary()['feedback_records'],1)
                self.assertIsNone(reopened.store.summary()['active_model'])
                self.assertEqual(reopened.store.feedback()[0]['features'],row['features'])

    def test_benchmark_runs_in_managed_worker_without_creating_feedback(self):
        source=Path(__file__).resolve().parents[1]/'examples'/'desktop'/'reconstruction-benchmark-synthetic.json'
        with tempfile.TemporaryDirectory() as tmp:
            with self.runtime(Path(tmp)/'memory') as runtime:
                job=self.completed(runtime,runtime.submit('reconstruction_benchmark',source))
                self.assertEqual(job['result']['status'],'benchmark_completed')
                self.assertEqual(job['result']['dataset_kind'],'synthetic')
                self.assertEqual(job['result']['training_labels_generated'],0)
                report=Path(job['output_directory'])/'report.json'
                self.assertEqual(json.loads(report.read_text()),job['result'])
                self.assertEqual(runtime.store.summary()['feedback_records'],0)
                self.assertEqual(runtime.store.summary()['checkpoints'],0)

    def test_benchmark_rejects_training_source_leakage_in_worker(self):
        source=Path(__file__).resolve().parents[1]/'examples'/'desktop'/'reconstruction-benchmark-synthetic.json'
        config=json.loads(source.read_text())
        config['lineage']={'training_buildings':[], 'evaluation_buildings':[],
            'training_sources':[config['cases'][0]['source_sha256'][0]],'evaluation_sources':[]}
        config['reference_sha256']=reference_digest(config)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'leaked.json';write_json(path,config)
            with self.runtime(root/'memory') as runtime:
                jid=runtime.submit('reconstruction_benchmark',path)
                job=_wait(runtime,jid,timeout=30)
                self.assertEqual(job['status'],'failed')
                self.assertIn('overlap',job['error'].lower())
                self.assertEqual(runtime.store.summary()['feedback_records'],0)
                self.assertFalse((Path(job['output_directory'])/'report.json').exists())

    def test_managed_regeneration_produces_world_and_new_unreviewed_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with self.runtime(root/'memory') as runtime:
                prepared=self.completed(runtime,runtime.submit_review('synthetic_demo'))['result']
                session=load_session(prepared['queue_path'],prepared['batch_path'])
                for path in prepared['source_paths']:session=bind_source(session,path)
                row=session['records'][0]
                change={'type':'dimension','component_id':'front-wall','axis':'x','value_m':9,
                    'source_sha256':row['source_sha256'][0],'source_page':1}
                draft=save_review(session,building_id=row['building_id'],candidate_sha256=row['candidate_sha256'],outcome=None,
                    review_basis=None,review_reference='',corrections=[change],output_directory=root/'draft')
                job=self.completed(runtime,runtime.submit_regeneration(draft['output_directory']))
                result=job['result']
                self.assertTrue(Path(result['corrected_world_path']).is_file())
                next_session=load_session(result['queue_path'],result['batch_path'])
                self.assertEqual(max(p[0] for p in next_session['records'][0]['candidate']['spec']['components'][0]['geometry']['profile']),9)
                self.assertFalse(any(next_session['records'][0]['candidate']['gates'].values()))
                self.assertEqual(runtime.store.summary()['feedback_records'],0)
                self.assertEqual(runtime.store.summary()['checkpoints'],0)
                self.assertGreater(job['peak_memory_mb'],0)

    def test_queued_review_pin_refuses_a_changed_review_before_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with self.runtime(root/'memory') as runtime:
                prepared=self.completed(runtime,runtime.submit_review('synthetic_demo'))['result']
                session=load_session(prepared['queue_path'],prepared['batch_path'])
                for path in prepared['source_paths']:session=bind_source(session,path)
                row=session['records'][0]
                change={'type':'dimension','component_id':'front-wall','axis':'x','value_m':9,
                    'source_sha256':row['source_sha256'][0],'source_page':1}
                draft=save_review(session,building_id=row['building_id'],candidate_sha256=row['candidate_sha256'],outcome=None,
                    review_basis=None,review_reference='',corrections=[change],output_directory=root/'draft')
                runtime._heavy.acquire()
                try:
                    jid=runtime.submit_regeneration(draft['output_directory'],world=False)
                    path=Path(draft['output_directory'])/'report.json';path.write_bytes(path.read_bytes()+b' ')
                finally:runtime._heavy.release()
                job=_wait(runtime,jid,timeout=30)
                self.assertEqual(job['status'],'failed')
                self.assertIn('Queued saved review changed',job['error'])
                self.assertFalse((Path(job['output_directory'])/'report.json').exists())


if __name__=='__main__':unittest.main()
