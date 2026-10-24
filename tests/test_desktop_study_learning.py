"""Pinned source-dataset training stays separate from the active building ranker."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from voxel_mapper.desktop_app import JOB_KINDS
from voxel_mapper.desktop_runtime import DesktopRuntime, HEAVY, _wait, _worker, file_hash, read_json, write_json


class DesktopStudyLearningTests(unittest.TestCase):
    def dataset(self, root):
        directory=root/'dataset files';directory.mkdir()
        write_json(directory/'dataset.json',{'version':'retained-study-dataset-v1','id':'test-fixture'})
        return directory

    def test_registered_as_a_managed_heavy_operation(self):
        self.assertIn('train_study_components',HEAVY)
        self.assertIn('train_study_components',dict(JOB_KINDS).values())

    def test_submission_pins_manifest_and_preserves_building_learning_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);directory=self.dataset(root)
            runtime=DesktopRuntime(root/'memory',memory_budget_mb=2048)
            try:
                with patch.object(runtime,'submit',return_value='study-job') as submit:
                    self.assertEqual(runtime.submit_study_training(directory,epochs=60,hidden_units=12),'study-job')
                kind,path=submit.call_args.args
                config=read_json(path)
                self.assertEqual(kind,'train_study_components')
                self.assertEqual(Path(config['dataset_directory']),directory.resolve())
                self.assertEqual(config['dataset_sha256'],file_hash(directory/'dataset.json'))
                self.assertEqual((config['epochs'],config['hidden_units']),(60,12))
                self.assertIsNone(runtime.store.setting('active_model'))
                self.assertEqual(runtime.store.summary()['feedback_records'],0)
                self.assertEqual(runtime.store.summary()['checkpoints'],0)
            finally:runtime.close(wait=True)

    def test_submission_refuses_unknown_dataset_and_unbounded_training(self):
        for mode in ('missing','version','epochs','hidden','boolean'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);directory=self.dataset(root)
                if mode=='missing':(directory/'dataset.json').unlink()
                elif mode=='version':write_json(directory/'dataset.json',{'version':'unknown'})
                runtime=DesktopRuntime(root/'memory',memory_budget_mb=2048)
                try:
                    with patch.object(runtime,'submit') as submit,self.assertRaises(ValueError):
                        runtime.submit_study_training(directory,
                            epochs=301 if mode=='epochs' else True if mode=='boolean' else 60,
                            hidden_units=33 if mode=='hidden' else 16)
                    submit.assert_not_called()
                finally:runtime.close(wait=True)

    def request(self,root,**extra):
        directory=self.dataset(root);path=root/'request.json'
        write_json(path,{'dataset_directory':'dataset files',
            'dataset_sha256':file_hash(directory/'dataset.json'),'epochs':60,'hidden_units':12,**extra})
        return directory,{'version':'desktop-worker-v1','kind':'train_study_components',
            'config_path':str(path),'config_sha256':file_hash(path),
            'output_directory':str(root/'fresh output'),'progress_path':str(root/'progress.json'),
            'cancel_path':str(root/'cancel')}

    def test_worker_resolves_relative_dataset_and_calls_image_trainer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);directory,request=self.request(root)
            expected={'status':'exploratory_component_classifier_trained','production_eligible':False,
                'model_weights_updated':True,'geometry_generated':False,'park_world_blocks_added':0}
            with patch('voxel_mapper.study_component_learning.train',return_value=expected) as train:
                self.assertEqual(_worker(request),expected)
            train.assert_called_once()
            self.assertEqual(train.call_args.args,((directory).resolve(),root/'fresh output'))
            options=train.call_args.kwargs
            self.assertEqual((options['epochs'],options['hidden_units']),(60,12))
            self.assertFalse(options['cancelled']())
            self.assertTrue(callable(options['progress']))

    def test_queued_manifest_change_and_unknown_options_do_not_train(self):
        for mode in ('changed','unknown','pin','epochs'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);directory,request=self.request(root,**({'unknown':True} if mode=='unknown' else {}))
                if mode=='changed':(directory/'dataset.json').write_text('{}')
                elif mode in ('pin','epochs'):
                    config=read_json(request['config_path'])
                    config['dataset_sha256' if mode=='pin' else 'epochs']='?'*64 if mode=='pin' else 301
                    write_json(request['config_path'],config);request['config_sha256']=file_hash(request['config_path'])
                with patch('voxel_mapper.study_component_learning.train') as train,self.assertRaises(ValueError):
                    _worker(request)
                train.assert_not_called()
                self.assertFalse((root/'fresh output').exists())

    def test_research_training_does_not_replace_an_existing_active_ranker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);directory=self.dataset(root)
            runtime=DesktopRuntime(root/'memory',memory_budget_mb=2048)
            try:
                previous={'path':'previous-reviewed-ranker.json','sha256':'e'*64}
                runtime.store.set_setting('active_model',previous)
                result={'status':'exploratory_component_classifier_trained','production_eligible':False,
                    'model_weights_updated':True,'training_labels_generated':0,'geometry_generated':False,
                    'park_world_blocks_added':0}
                with patch.object(runtime,'_subprocess_job',return_value=result),patch.object(runtime,'_store_checkpoint') as promote:
                    jid=runtime.submit_study_training(directory,epochs=60)
                    job=_wait(runtime,jid,timeout=10);runtime._futures[jid].result(timeout=5)
                self.assertEqual(job['status'],'completed')
                self.assertEqual(runtime.store.setting('active_model'),previous)
                promote.assert_not_called()
                self.assertEqual(runtime.store.summary()['feedback_records'],0)
                self.assertEqual(runtime.store.summary()['checkpoints'],0)
            finally:runtime.close(wait=True)


if __name__=='__main__':unittest.main()
