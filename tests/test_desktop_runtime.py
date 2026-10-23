"""CPU-only desktop subprocess, durable memory and reviewed learning integration."""
from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest

from voxel_mapper.desktop_memory import MemoryStore,digest,source_separated_split
from voxel_mapper.desktop_runtime import DesktopRuntime,_wait,write_json
from voxel_mapper.neural_learning import FEATURES


def reviewed_fixture(suffix='initial',invert=False):
    records=[];split={'training_buildings':[],'evaluation_buildings':[]}
    for phase,count in (('training',20),('evaluation',4)):
        for i in range(5):
            building=f'synthetic-{phase}-{i}';split[phase+'_buildings'].append(building)
            for j in range(count):
                high=bool(j%2);accepted=not high if invert else high
                records.append({'id':f'{building}:{suffix}:{j}','building_id':building,
                    'candidate_sha256':digest([building,suffix,j]),'source_sha256':[digest(building)],
                    'features':dict.fromkeys(FEATURES,.9 if high else .1),
                    'outcome':'accepted' if accepted else 'rejected','review_basis':'independent_review',
                    'review_reference':'synthetic integration fixture; no real-world review claim'})
    return records,split


class DesktopRuntimeTests(unittest.TestCase):
    @contextmanager
    def runtime(self,path):
        runtime=DesktopRuntime(path,workers=2,memory_budget_mb=2048)
        try:yield runtime
        finally:runtime.close(wait=True)

    def completed(self,runtime,jid):
        job=_wait(runtime,jid,timeout=8)
        self.assertEqual(job['status'],'completed',job.get('error') or job.get('message'))
        # A completed import can be visible just before its finally block queues
        # training. Joining that existing future observes the complete operation.
        runtime._futures[jid].result(timeout=8)
        return job

    def import_dataset(self,runtime,root,records,split,name='initial'):
        write_json(root/(name+'-feedback.json'),{'version':'building-feedback-v1','records':records})
        write_json(root/(name+'-split.json'),split)
        path=root/(name+'-import.json');write_json(path,{'feedback_path':name+'-feedback.json','split_path':name+'-split.json','continuous':True})
        return self.completed(runtime,runtime.submit('import_feedback',path))

    def training_jobs(self,runtime):return [j for j in runtime.store.jobs() if j['kind']=='train_ranker']

    def test_real_subprocess_observations_and_jobs_survive_application_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source evidence.json';source.write_text(json.dumps({'status':'synthetic_unverified','counts':{'roof_points':4}}))
            config=root/'inspect.json';write_json(config,{'paths':['source evidence.json']});directory=root/'memory with spaces'
            with self.runtime(directory) as runtime:
                ids=[runtime.submit('inspect_evidence',config) for _ in range(2)]
                for jid in ids:
                    job=self.completed(runtime,jid);self.assertEqual(job['result']['status'],'evidence_inspected')
                    self.assertEqual(job['result']['training_labels_generated'],0)
                    self.assertEqual(job['result']['observations'][0]['sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
                    files=Path(job['output_directory']).parent
                    self.assertTrue((files/'request.json').is_file());self.assertTrue((files/'worker-result.json').is_file())
                    self.assertTrue((files/'worker.log').is_file())
                self.assertEqual(runtime.snapshot()['config']['workers'],2)
                self.assertEqual(runtime.store.summary()['feedback_records'],0)
                self.assertGreaterEqual(runtime.store.summary()['knowledge_items'],3)
                self.assertEqual(self.training_jobs(runtime),[])
            with self.runtime(directory) as reopened:
                self.assertTrue(all(reopened.store.job(jid)['status']=='completed' for jid in ids))
                self.assertIn('synthetic_unverified',reopened.store.context())
                self.assertEqual(reopened.store.summary()['feedback_records'],0)
                self.assertEqual(reopened.store.summary()['checkpoints'],0)

    def test_active_data_directory_lock_refuses_second_application(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'memory'
            with self.runtime(path):
                with self.assertRaisesRegex(ValueError,'already open'):DesktopRuntime(path,workers=2,memory_budget_mb=2048)
            with self.runtime(path) as reopened:self.assertFalse(reopened.snapshot()['closed'])

    def test_feedback_needs_review_reference_and_never_accepts_model_predictions(self):
        records,_=reviewed_fixture();row=records[0]
        with tempfile.TemporaryDirectory() as tmp:
            store=MemoryStore(tmp)
            for mode in ('missing','blank','prediction'):
                changed=copy.deepcopy(row)
                if mode=='missing':changed.pop('review_reference')
                elif mode=='blank':changed['review_reference']=' '
                else:changed['review_basis']='model_prediction'
                with self.assertRaises(ValueError):store.import_feedback([changed])
                self.assertEqual(store.feedback(),[])

    def test_duplicate_feedback_is_idempotent_and_conflict_rolls_back_whole_batch(self):
        records,_=reviewed_fixture();first,second=records[:2]
        with tempfile.TemporaryDirectory() as tmp:
            store=MemoryStore(tmp);self.assertEqual(store.import_feedback([first]),1)
            self.assertEqual(store.import_feedback([first]),0)
            conflict=copy.deepcopy(first);conflict['outcome']='accepted' if first['outcome']=='rejected' else 'rejected'
            with self.assertRaisesRegex(ValueError,'Conflicting'):store.import_feedback([second,conflict])
            self.assertEqual(store.feedback(),[first])
            self.assertEqual(store.import_feedback([second]),1)
            self.assertEqual(store.summary()['feedback_records'],2)

    def test_invalid_import_configuration_cannot_partially_commit_feedback(self):
        records,split=reviewed_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);write_json(root/'feedback.json',{'version':'building-feedback-v1','records':records})
            write_json(root/'overlapping-split.json',{'training_buildings':['same'],'evaluation_buildings':['same']})
            configs=[{'feedback_path':'feedback.json','continuous':'yes'},
                     {'feedback_path':'feedback.json','split_path':'missing-split.json'},
                     {'feedback_path':'feedback.json','split_path':'overlapping-split.json'}]
            with self.runtime(root/'memory') as runtime:
                for index,value in enumerate(configs):
                    path=root/f'invalid-{index}.json';write_json(path,value)
                    jid=runtime.submit('import_feedback',path);failed=_wait(runtime,jid,timeout=8)
                    runtime._futures[jid].result(timeout=8)
                    self.assertEqual(failed['status'],'failed')
                    self.assertEqual(runtime.store.feedback(),[])
                    self.assertIsNone(runtime.store.setting('explicit_split'))
                    self.assertTrue(runtime.store.setting('continuous_learning'))
                self.assertEqual(self.training_jobs(runtime),[])

    def test_source_connected_splits_are_stable_under_order_and_new_unrelated_sources(self):
        records,_=reviewed_fixture();split,assignments=source_separated_split(records)
        self.assertEqual(source_separated_split(list(reversed(records)),assignments),(split,assignments))
        extra=copy.deepcopy(records[0]);extra.update(id='extra',building_id='new-unrelated',candidate_sha256=digest('extra'),source_sha256=[digest('new-source')])
        _,updated=source_separated_split(records+[extra],assignments)
        self.assertTrue(all(updated[b]==phase for b,phase in assignments.items()))
        connected=copy.deepcopy(extra);connected['building_id']='new-connected';connected['source_sha256']=records[0]['source_sha256']
        _,linked=source_separated_split(records+[connected],assignments)
        self.assertEqual(linked['new-connected'],assignments[records[0]['building_id']])

    def test_new_source_connection_cannot_join_training_and_evaluation(self):
        a={'building_id':'a','source_sha256':[digest('source-a')]};b={'building_id':'b','source_sha256':[digest('source-b')]}
        bridge={'building_id':'bridge','source_sha256':[digest('source-a'),digest('source-b')]}
        previous={'a':'training','b':'evaluation'};before=copy.deepcopy(previous)
        with self.assertRaisesRegex(ValueError,'connects training and evaluation'):source_separated_split([a,b,bridge],previous)
        self.assertEqual(previous,before)

    def test_automatic_training_runs_only_for_new_reviewed_data_and_failed_promotion_keeps_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);records,split=reviewed_fixture();directory=root/'memory'
            with self.runtime(directory) as runtime:
                imported=self.import_dataset(runtime,root,records,split)
                self.assertEqual(imported['result']['imported'],120)
                jobs=self.training_jobs(runtime);self.assertEqual(len(jobs),1)
                trained=self.completed(runtime,jobs[0]['id']);self.assertTrue(trained['result']['promotion_eligible'])
                active=runtime.store.setting('active_model');self.assertIsNotNone(active)
                self.assertEqual(active['sha256'],trained['result']['candidate_sha256'])
                self.assertTrue(Path(active['path']).is_file())
                repeated=self.import_dataset(runtime,root,records,split,name='same')
                self.assertEqual(repeated['result']['imported'],0);self.assertEqual(len(self.training_jobs(runtime)),1)
                changed,_=reviewed_fixture('contradictory-reviewed-fixture',invert=True)
                self.import_dataset(runtime,root,changed,split,name='changed')
                jobs=self.training_jobs(runtime);self.assertEqual(len(jobs),2)
                second=next(j for j in jobs if j['id']!=trained['id']);withheld=self.completed(runtime,second['id'])
                self.assertFalse(withheld['result']['promotion_eligible'])
                self.assertEqual(runtime.store.setting('active_model'),active)
                self.assertEqual(runtime.store.setting('learning_state')['status'],'checkpoint_withheld')
                self.assertEqual(runtime.store.summary()['feedback_records'],240)
                self.assertEqual(runtime.store.summary()['checkpoints'],2)
            with self.runtime(directory) as reopened:
                self.assertEqual(reopened.store.setting('active_model'),active)
                self.assertEqual(len(self.training_jobs(reopened)),2)
                self.assertEqual(reopened.store.summary()['feedback_records'],240)

    def test_crashed_cancelling_job_becomes_interrupted_on_memory_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=MemoryStore(tmp);store.add_job({'id':'interrupted-training','kind':'train_ranker','config_path':'missing.json','config_sha256':'a'*64,'output_directory':'unused'})
            store.update_job('interrupted-training',status='cancelling')
            reopened=MemoryStore(tmp)
            self.assertEqual(reopened.job('interrupted-training')['status'],'interrupted')
