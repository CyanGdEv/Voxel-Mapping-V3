"""Bounded vision jobs retain exact source manifests and leave rankers alone."""
from concurrent.futures import CancelledError
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from voxel_mapper.desktop_app import JOB_KINDS
from voxel_mapper.desktop_runtime import DesktopRuntime, HEAVY, KINDS, _wait, _worker, file_hash, read_json, write_json


class DesktopStudyVisionTests(unittest.TestCase):
    def dataset(self,root):
        directory=root/'dataset files';directory.mkdir()
        write_json(directory/'dataset.json',{'version':'retained-study-dataset-v1','id':'wrapper-fixture'})
        return directory

    def test_vision_is_heavy_and_previous_component_training_stays_registered(self):
        self.assertIn('train_study_vision',HEAVY)
        self.assertIn('train_study_vision',KINDS)
        kinds=dict(JOB_KINDS).values()
        self.assertIn('train_study_vision',kinds)
        self.assertIn('train_study_components',kinds)
        self.assertIn('train_study_components',HEAVY)

    def test_submission_pins_exact_manifest_and_bounded_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);directory=self.dataset(root)
            runtime=DesktopRuntime(root/'memory',memory_budget_mb=2048)
            try:
                with patch.object(runtime,'submit',return_value='vision-job') as submit:
                    self.assertEqual(runtime.submit_study_vision(directory,epochs=20,channels=8,input_size=32),'vision-job')
                kind,path=submit.call_args.args;config=read_json(path)
                self.assertEqual(kind,'train_study_vision')
                self.assertEqual(config,{'dataset_directory':str(directory.resolve()),
                    'dataset_sha256':file_hash(directory/'dataset.json'),'epochs':20,'channels':8,'input_size':32})
                self.assertIsNone(runtime.store.setting('active_model'))
                self.assertEqual(runtime.store.summary()['feedback_records'],0)
                self.assertEqual(runtime.store.summary()['checkpoints'],0)
            finally:runtime.close(wait=True)

    def test_invalid_manifest_settings_and_boolean_sizes_do_not_queue(self):
        for mode in ('missing','version','epochs','channels','size','bool_epochs','bool_channels','bool_size'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);directory=self.dataset(root)
                if mode=='missing':(directory/'dataset.json').unlink()
                if mode=='version':write_json(directory/'dataset.json',{'version':'unknown'})
                runtime=DesktopRuntime(root/'memory',memory_budget_mb=2048)
                try:
                    with patch.object(runtime,'submit') as submit,self.assertRaises(ValueError):
                        runtime.submit_study_vision(directory,
                            epochs=101 if mode=='epochs' else True if mode=='bool_epochs' else 30,
                            channels=3 if mode=='channels' else True if mode=='bool_channels' else 4,
                            input_size=128 if mode=='size' else True if mode=='bool_size' else 64)
                    submit.assert_not_called()
                finally:runtime.close(wait=True)

    def request(self,root,**extra):
        directory=self.dataset(root);path=root/'request.json'
        write_json(path,{'dataset_directory':'dataset files','dataset_sha256':file_hash(directory/'dataset.json'),
            'epochs':20,'channels':4,'input_size':32,**extra})
        return directory,{'version':'desktop-worker-v1','kind':'train_study_vision','config_path':str(path),
            'config_sha256':file_hash(path),'output_directory':str(root/'fresh output'),
            'progress_path':str(root/'progress.json'),'cancel_path':str(root/'cancel')}

    def test_worker_resolves_relative_dataset_and_calls_vision_trainer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);directory,request=self.request(root)
            expected={'status':'exploratory_component_vision_trained','production_eligible':False,
                'model_weights_updated':True,'mask_predictions_generated':True,'geometry_generated':False}
            with patch('voxel_mapper.study_vision_learning.train',return_value=expected) as train:
                self.assertEqual(_worker(request),expected)
            train.assert_called_once();self.assertEqual(train.call_args.args,(directory.resolve(),root/'fresh output'))
            options=train.call_args.kwargs
            self.assertEqual((options['epochs'],options['channels'],options['input_size']),(20,4,32))
            self.assertFalse(options['cancelled']());self.assertTrue(callable(options['progress']))

    def test_changed_manifest_and_unsupported_config_never_start_training(self):
        for mode in ('changed','unknown','pin','epochs','size'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);directory,request=self.request(root,**({'unknown':1} if mode=='unknown' else {}))
                if mode=='changed':(directory/'dataset.json').write_text('{}')
                elif mode in ('pin','epochs','size'):
                    config=read_json(request['config_path'])
                    key={'pin':'dataset_sha256','epochs':'epochs','size':'input_size'}[mode]
                    config[key]='?'*64 if mode=='pin' else 101 if mode=='epochs' else 128
                    write_json(request['config_path'],config);request['config_sha256']=file_hash(request['config_path'])
                with patch('voxel_mapper.study_vision_learning.train') as train,self.assertRaises(ValueError):
                    _worker(request)
                train.assert_not_called();self.assertFalse((root/'fresh output').exists())

    def test_cancel_marker_prevents_trainer_and_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);_,request=self.request(root);Path(request['cancel_path']).touch()
            with patch('voxel_mapper.study_vision_learning.train') as train,self.assertRaises(CancelledError):
                _worker(request)
            train.assert_not_called();self.assertFalse((root/'fresh output').exists())

    def test_shared_source_cannot_be_held_out_under_false_group_labels(self):
        from voxel_mapper.building_spec import digest
        from voxel_mapper.desktop_study_vision_smoke import seed
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);directory=root/'dataset';manifest=seed(directory)
            manifest['records'][0]['source']['document_sha256']=manifest['records'][-1]['source']['document_sha256']
            manifest['id']=digest({k:v for k,v in manifest.items() if k!='id'})
            write_json(directory/'dataset.json',manifest);path=root/'request.json'
            write_json(path,{'dataset_directory':'dataset','dataset_sha256':file_hash(directory/'dataset.json'),
                'epochs':1,'channels':4,'input_size':32})
            request={'version':'desktop-worker-v1','kind':'train_study_vision','config_path':str(path),
                'config_sha256':file_hash(path),'output_directory':str(root/'fresh output'),
                'progress_path':str(root/'progress.json'),'cancel_path':str(root/'cancel')}
            with self.assertRaises(ValueError):_worker(request)
            self.assertFalse((root/'fresh output').exists())

    def test_research_vision_job_preserves_existing_active_ranker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);directory=self.dataset(root)
            runtime=DesktopRuntime(root/'memory',memory_budget_mb=2048)
            try:
                previous={'path':'previous-reviewed-ranker.json','sha256':'e'*64}
                runtime.store.set_setting('active_model',previous)
                result={'status':'exploratory_component_vision_trained','production_eligible':False,
                    'model_weights_updated':True,'mask_predictions_generated':True,'geometry_generated':False,
                    'training_labels_generated':0,'park_world_blocks_added':0}
                with patch.object(runtime,'_subprocess_job',return_value=result),patch.object(runtime,'_store_checkpoint') as promote:
                    jid=runtime.submit_study_vision(directory,epochs=20,input_size=32)
                    job=_wait(runtime,jid,timeout=10);runtime._futures[jid].result(timeout=5)
                self.assertEqual(job['status'],'completed')
                self.assertEqual(runtime.store.setting('active_model'),previous)
                promote.assert_not_called();self.assertEqual(runtime.store.summary()['feedback_records'],0)
                self.assertEqual(runtime.store.summary()['checkpoints'],0)
            finally:runtime.close(wait=True)


if __name__=='__main__':unittest.main()
