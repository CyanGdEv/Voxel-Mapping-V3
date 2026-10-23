"""Regression guards for desktop cancellation, replay and persistent learning."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from voxel_mapper import desktop_runtime as runtime_module
from voxel_mapper.desktop_memory import MemoryStore, digest
from voxel_mapper.desktop_runtime import DesktopRuntime, DirectoryLock, file_hash, read_json, write_json
from voxel_mapper.neural_learning import FEATURES, baseline


def reviewed_records():
    records=[];split={'training_buildings':[],'evaluation_buildings':[]}
    for phase,count in (('training',20),('evaluation',4)):
        for i in range(5):
            building=f'guard-fixture-{phase}-{i}';split[phase+'_buildings'].append(building)
            for j in range(count):
                records.append({'id':f'{building}-{j}','building_id':building,
                    'candidate_sha256':digest([building,j]),'source_sha256':[digest(building)],
                    'features':dict.fromkeys(FEATURES,.9 if j%2 else .1),
                    'outcome':'accepted' if j%2 else 'rejected','review_basis':'independent_review',
                    'review_reference':'synthetic guard fixture only; not real evidence'})
    return records,split


def worker_request(root,kind,config):
    config_path=root/'operation.json';write_json(config_path,config)
    return {'version':'desktop-worker-v1','kind':kind,'config_path':str(config_path),
        'config_sha256':file_hash(config_path),'output_directory':str(root/'output'),
        'result_path':str(root/'worker-result.json'),'progress_path':str(root/'progress.json'),
        'cancel_path':str(root/'cancel'),'active_model':None,'memory_context':''}


def runtime_without_workers(directory,store=None):
    """Exercise synchronous dispatch guards without subprocesses or sleep loops."""
    runtime=DesktopRuntime.__new__(DesktopRuntime);runtime.directory=Path(directory)
    runtime.store=store or MemoryStore(directory);runtime._closed=False
    runtime._mutex=threading.RLock();runtime._learning_lock=threading.RLock()
    runtime._training_mutex=threading.Lock();runtime._heavy=threading.Semaphore(1)
    runtime._events={};runtime._futures={};runtime._processes={};runtime.memory_budget_mb=2048
    return runtime


class DesktopWorkerGuardTests(unittest.TestCase):
    def test_lock_setup_permission_error_closes_the_open_handle_and_reports_contention(self):
        stream=Mock();stream.read.side_effect=PermissionError('locked byte')
        with patch.object(Path,'open',return_value=stream),self.assertRaisesRegex(ValueError,'already open'):
            DirectoryLock('runtime.lock')
        stream.close.assert_called_once_with()

    def test_retained_context_obeys_zero_and_short_character_budgets(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=MemoryStore(tmp)
            store.remember('source_observation','roof.json',{'status':'unverified','description':'x'*1000})
            self.assertEqual(store.context(0),'')
            for budget in (1,8,50,90,128,512,2048):
                with self.subTest(budget=budget):
                    self.assertLessEqual(len(store.context(budget)),budget)

    def interrupted_learning(self,root,attempts=1):
        store=MemoryStore(root);records,split=reviewed_records();store.import_feedback(records)
        store.set_setting('explicit_split',split);fingerprint=digest({'records':store.feedback(),'split':split})
        store.add_job({'id':'previous-auto','kind':'train_ranker','config_path':'old-config.json',
            'config_sha256':'a'*64,'output_directory':'unused'})
        store.update_job('previous-auto',status='cancelling')
        store.set_setting('last_auto_dataset_sha256',fingerprint);store.set_setting('last_auto_job','previous-auto')
        store.set_setting('auto_training_attempts',{'dataset':fingerprint,'count':attempts})
        return MemoryStore(root),fingerprint

    def test_restarted_cancelling_training_is_retried_for_same_reviewed_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store,fingerprint=self.interrupted_learning(root)
            self.assertEqual(store.job('previous-auto')['status'],'interrupted')
            runtime=runtime_without_workers(root,store);runtime.submit=Mock(return_value='retry-auto')
            runtime._maybe_auto_train()
            runtime.submit.assert_called_once()
            kind,path=runtime.submit.call_args.args
            self.assertEqual(kind,'train_ranker');self.assertEqual(read_json(path)['feedback_path'],'feedback.json')
            self.assertEqual(store.setting('last_auto_job'),'retry-auto')
            self.assertEqual(store.setting('auto_training_attempts'),{'dataset':fingerprint,'count':2})
            self.assertEqual(store.setting('learning_state')['status'],'training_queued')
            self.assertEqual(len(read_json(path.parent/'feedback.json')['records']),120)
            self.assertEqual(store.summary()['checkpoints'],0)

    def test_interrupted_dataset_retry_limit_prevents_an_endless_training_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store,fingerprint=self.interrupted_learning(root,attempts=3)
            runtime=runtime_without_workers(root,store);runtime.submit=Mock()
            runtime._maybe_auto_train()
            runtime.submit.assert_not_called()
            self.assertEqual(store.setting('learning_state')['status'],'retry_limit_reached')
            self.assertEqual(store.setting('last_auto_dataset_sha256'),fingerprint)

    def test_inspection_cannot_associate_old_content_with_a_new_source_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.json';write_json(source,{'status':'before','counts':{'corners':4}})
            request=worker_request(root,'inspect_evidence',{'paths':['source.json']});original_read=read_json
            def changed(path,*args,**kwargs):
                value=original_read(path,*args,**kwargs)
                if Path(path).resolve()==source.resolve():write_json(source,{'status':'after','counts':{'corners':8}})
                return value
            with patch.object(runtime_module,'read_json',side_effect=changed),self.assertRaisesRegex(ValueError,'Evidence changed'):
                runtime_module._worker(request)
            self.assertFalse(Path(request['output_directory']).exists())

    def test_feedback_or_split_change_during_training_cannot_persist_a_checkpoint(self):
        records,split=reviewed_records()
        for changed_name in ('feedback.json','split.json'):
            with self.subTest(source=changed_name),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);write_json(root/'feedback.json',{'version':'building-feedback-v1','records':records})
                write_json(root/'split.json',split)
                request=worker_request(root,'train_ranker',{'feedback_path':'feedback.json','split_path':'split.json','epochs':1})
                def changed(*args,**kwargs):
                    value=read_json(root/changed_name);value['changed_during_training']=True;write_json(root/changed_name,value)
                    return baseline()
                with patch('voxel_mapper.neural_learning.train',side_effect=changed) as train,self.assertRaisesRegex(ValueError,'Training source/configuration changed'):
                    runtime_module._worker(request)
                train.assert_called_once()
                self.assertFalse(Path(request['output_directory']).exists())
                self.assertFalse((root/'output'/'candidate-model.json').exists())

    def test_cancellation_arriving_at_final_checkpoint_mutex_cannot_promote(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);runtime=runtime_without_workers(root/'memory')
            config=root/'train.json';write_json(config,{'feedback_path':'unused-reviewed-source.json'})
            jid='cancel-before-checkpoint';output=root/'job-output'
            runtime.store.add_job({'id':jid,'kind':'train_ranker','config_path':str(config),
                'config_sha256':file_hash(config),'output_directory':str(output)})
            cancelled=threading.Event();runtime._events[jid]=cancelled
            runtime._subprocess_job=Mock(return_value={'status':'neural_checkpoint_evaluated','promotion_eligible':True})
            runtime._store_checkpoint=Mock()
            class CancellationAtMutex:
                def __enter__(self):cancelled.set()
                def __exit__(self,*args):return False
            runtime._mutex=CancellationAtMutex()
            runtime._execute(jid)
            runtime._subprocess_job.assert_called_once();runtime._store_checkpoint.assert_not_called()
            self.assertEqual(runtime.store.job(jid)['status'],'cancelled')
            self.assertIsNone(runtime.store.setting('active_model'))
            self.assertEqual(runtime.store.summary()['checkpoints'],0)

    def test_reason_worker_memory_respects_prompt_headroom_without_model_contact(self):
        for prompt_size in (2049,4096):
            with self.subTest(prompt_size=prompt_size),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);runtime=runtime_without_workers(root/'memory')
                for i in range(4):runtime.store.remember('source_observation',f'roof-{i}',{'description':'x'*900})
                config=root/'reason.json';write_json(config,{'prompt':'p'*prompt_size,'model':'explicit-installed-model'})
                directory=root/'job';directory.mkdir();output=directory/'output'
                job={'id':'reason-budget','kind':'reason','config_path':str(config),
                    'config_sha256':file_hash(config),'output_directory':str(output)}
                runtime.store.add_job(job)
                captured=[]
                class Finished:
                    pid=12345;returncode=0
                    def poll(self):return 0
                def fake_process(command,**kwargs):
                    request=read_json(directory/'request.json');captured.append(request)
                    write_json(request['result_path'],{'status':'advisory_proposals_only'})
                    return Finished()
                with patch.object(runtime_module.subprocess,'Popen',side_effect=fake_process):
                    result=runtime._subprocess_job(job,threading.Event())
                self.assertEqual(result['status'],'advisory_proposals_only')
                self.assertEqual(len(captured),1)
                context=captured[0]['memory_context']
                self.assertLessEqual(len(context),2048)
                self.assertLessEqual(len(context)+prompt_size,4096)
                if prompt_size==4096:self.assertEqual(context,'')
