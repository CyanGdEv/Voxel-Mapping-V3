"""Frozen encoder pins and bounded learned-head jobs preserve desktop ranker state."""
from concurrent.futures import CancelledError
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from voxel_mapper.desktop_app import JOB_KINDS,main
from voxel_mapper.desktop_runtime import DesktopRuntime,HEAVY,KINDS,_wait,_worker,file_hash,read_json,write_json


class DesktopStudyTransferTests(unittest.TestCase):
    def fixture(self,root):
        directory=root/'dataset files';directory.mkdir()
        write_json(directory/'dataset.json',{'version':'retained-study-dataset-v1','id':'wrapper-fixture'})
        encoder=root/'encoder files'/'encoder.onnx';encoder.parent.mkdir();encoder.write_bytes(b'pinned synthetic test bytes')
        return directory,encoder

    def request(self,root,**extra):
        directory,encoder=self.fixture(root);path=root/'request.json'
        write_json(path,{'dataset_directory':'dataset files','dataset_sha256':file_hash(directory/'dataset.json'),
            'encoder_path':'encoder files/encoder.onnx','encoder_sha256':file_hash(encoder),
            'ridge_alpha':100.,'input_size':32,**extra})
        return directory,encoder,{'version':'desktop-worker-v1','kind':'train_study_transfer','config_path':str(path),
            'config_sha256':file_hash(path),'output_directory':str(root/'fresh output'),
            'progress_path':str(root/'progress.json'),'cancel_path':str(root/'cancel')}

    def test_new_head_kind_is_heavy_and_keeps_existing_trainers(self):
        self.assertIn('train_study_transfer',HEAVY);self.assertIn('train_study_transfer',KINDS)
        self.assertIn(('Train pretrained vision heads (CPU)','train_study_transfer'),JOB_KINDS)
        for kind in ('train_study_components','train_study_vision','train_study_context'):
            self.assertIn(kind,KINDS);self.assertIn(kind,dict(JOB_KINDS).values())

    def test_submission_pins_raw_dataset_and_encoder_with_fixed_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);directory,encoder=self.fixture(root)
            runtime=DesktopRuntime(root/'memory',memory_budget_mb=2048)
            try:
                with patch.object(runtime,'submit',return_value='transfer-job') as submit:
                    self.assertEqual(runtime.submit_study_transfer(directory,encoder),'transfer-job')
                kind,path=submit.call_args.args
                self.assertEqual(kind,'train_study_transfer')
                self.assertEqual(read_json(path),{'dataset_directory':str(directory.resolve()),
                    'dataset_sha256':file_hash(directory/'dataset.json'),'encoder_path':str(encoder.resolve()),
                    'encoder_sha256':file_hash(encoder),'ridge_alpha':100.,'input_size':64})
                self.assertIsNone(runtime.store.setting('active_model'))
                self.assertEqual(runtime.store.summary()['feedback_records'],0)
                self.assertEqual(runtime.store.summary()['checkpoints'],0)
            finally:runtime.close(wait=True)

    def test_explicit_encoder_pin_and_bounded_nondefault_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);directory,encoder=self.fixture(root)
            runtime=DesktopRuntime(root/'memory',memory_budget_mb=2048)
            try:
                with patch.object(runtime,'submit',return_value='transfer-job') as submit:
                    runtime.submit_study_transfer(directory,encoder,file_hash(encoder),ridge_alpha=.1,input_size=32)
                self.assertEqual(read_json(submit.call_args.args[1])['ridge_alpha'],.1)
            finally:runtime.close(wait=True)

    def test_invalid_pins_settings_and_booleans_never_queue(self):
        cases=[{'ridge_alpha':value} for value in (True,False,0.,.01,10001.,10**400,float('nan'),float('inf'),'100')]
        cases += [{'input_size':value} for value in (True,32.,128)]
        cases += [{'encoder_sha256':value} for value in ('?'*64,'F'*64,'0'*64)]
        for options in cases:
            with self.subTest(options=options),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);directory,encoder=self.fixture(root)
                runtime=DesktopRuntime(root/'memory',memory_budget_mb=2048)
                try:
                    with patch.object(runtime,'submit') as submit,self.assertRaises(ValueError):
                        runtime.submit_study_transfer(directory,encoder,**options)
                    submit.assert_not_called()
                finally:runtime.close(wait=True)

    def test_missing_encoder_or_wrong_manifest_never_queue(self):
        for mode in ('encoder','manifest'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);directory,encoder=self.fixture(root)
                if mode=='encoder':encoder.unlink()
                else:write_json(directory/'dataset.json',{'version':'wrong'})
                runtime=DesktopRuntime(root/'memory',memory_budget_mb=2048)
                try:
                    with patch.object(runtime,'submit') as submit,self.assertRaises(ValueError):
                        runtime.submit_study_transfer(directory,encoder)
                    submit.assert_not_called()
                finally:runtime.close(wait=True)

    def test_worker_resolves_both_relative_paths_and_passes_pinned_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);directory,encoder,request=self.request(root)
            expected={'status':'exploratory_pretrained_transfer_trained','production_eligible':False,
                'model_weights_updated':True,'encoder_weights_updated':False}
            with patch('voxel_mapper.study_transfer_learning.train',return_value=expected) as train:
                self.assertEqual(_worker(request),expected)
            train.assert_called_once();self.assertEqual(train.call_args.args,(directory.resolve(),root/'fresh output'))
            options=train.call_args.kwargs
            self.assertEqual(options['encoder_path'],encoder.resolve())
            self.assertEqual(options['encoder_sha256'],file_hash(encoder))
            self.assertEqual((options['ridge_alpha'],options['input_size']),(100.,32))
            self.assertFalse(options['cancelled']());self.assertTrue(callable(options['progress']))

    def test_manifest_encoder_config_and_unknown_option_changes_prevent_training(self):
        for mode in ('manifest','encoder','config','unknown','alpha','size','pin'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);directory,encoder,request=self.request(root)
                if mode=='manifest':(directory/'dataset.json').write_text('{}')
                elif mode=='encoder':encoder.write_bytes(b'changed')
                else:
                    config=read_json(request['config_path'])
                    if mode in ('unknown','config'):config['unknown']=True
                    elif mode=='alpha':config['ridge_alpha']=True
                    elif mode=='size':config['input_size']=128
                    elif mode=='pin':config['encoder_sha256']='?'*64
                    write_json(request['config_path'],config)
                    if mode!='config':request['config_sha256']=file_hash(request['config_path'])
                with patch('voxel_mapper.study_transfer_learning.train') as train,self.assertRaises(ValueError):
                    _worker(request)
                train.assert_not_called();self.assertFalse((root/'fresh output').exists())

    def test_dataset_or_encoder_change_during_training_is_rejected(self):
        for mode in ('manifest','encoder'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);directory,encoder,request=self.request(root)
                def train(*args,**kwargs):
                    if mode=='manifest':write_json(directory/'dataset.json',{'version':'changed'})
                    else:encoder.write_bytes(b'changed')
                    return {'status':'exploratory_pretrained_transfer_trained'}
                with patch('voxel_mapper.study_transfer_learning.train',side_effect=train),self.assertRaises(ValueError):
                    _worker(request)

    def test_cancel_marker_prevents_head_trainer_and_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);_,_,request=self.request(root);Path(request['cancel_path']).touch()
            with patch('voxel_mapper.study_transfer_learning.train') as train,self.assertRaises(CancelledError):
                _worker(request)
            train.assert_not_called();self.assertFalse((root/'fresh output').exists())

    def test_cancellation_and_progress_callbacks_reach_transfer_trainer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);_,_,request=self.request(root)
            def train(*args,**kwargs):
                kwargs['progress']({'progress':.4,'message':'frozen CPU features'})
                self.assertEqual(read_json(request['progress_path'])['progress'],.4)
                Path(request['cancel_path']).touch();self.assertTrue(kwargs['cancelled']())
                raise CancelledError()
            with patch('voxel_mapper.study_transfer_learning.train',side_effect=train),self.assertRaises(CancelledError):
                _worker(request)
            self.assertFalse((root/'fresh output').exists())

    def test_research_transfer_job_preserves_existing_active_ranker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);directory,encoder=self.fixture(root)
            runtime=DesktopRuntime(root/'memory',memory_budget_mb=2048)
            try:
                previous={'path':'previous-reviewed-ranker.json','sha256':'e'*64};runtime.store.set_setting('active_model',previous)
                result={'status':'exploratory_pretrained_transfer_trained','production_eligible':False,
                    'model_weights_updated':True,'encoder_weights_updated':False,'mask_predictions_generated':True,
                    'geometry_generated':False,'training_labels_generated':0,'park_world_blocks_added':0}
                with patch.object(runtime,'_subprocess_job',return_value=result),patch.object(runtime,'_store_checkpoint') as promote:
                    jid=runtime.submit_study_transfer(directory,encoder,input_size=32)
                    job=_wait(runtime,jid,timeout=10);runtime._futures[jid].result(timeout=5)
                self.assertEqual(job['status'],'completed');self.assertEqual(runtime.store.setting('active_model'),previous)
                promote.assert_not_called();self.assertEqual(runtime.store.summary()['feedback_records'],0)
                self.assertEqual(runtime.store.summary()['checkpoints'],0)
            finally:runtime.close(wait=True)

    def test_smoke_fixture_is_explicit_rgb_with_distinct_filled_target_labels(self):
        from PIL import Image
        import numpy as np
        from voxel_mapper.desktop_study_transfer_smoke import seed
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'dataset';manifest=seed(directory)
            self.assertEqual((manifest['dataset_kind'],len(manifest['groups']),len(manifest['records'])),
                ('synthetic_transfer_smoke_fixture',3,12))
            means={}
            for row in manifest['records']:
                with Image.open(directory/row['input_file']) as image,Image.open(directory/row['target_mask_file']) as target:
                    self.assertEqual(image.mode,'RGB');pixels=np.asarray(image);filled=np.asarray(target)>128
                    means[row['kind']]=pixels.mean(axis=(0,1))
                    self.assertGreater(np.count_nonzero(filled&np.all(pixels==255,axis=2)),30)
            self.assertGreater(means['door'][0],means['door'][2])
            self.assertGreater(means['window'][2],means['window'][0])

    def test_cli_routes_transfer_smoke_without_constructing_a_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'smoke'
            with patch('voxel_mapper.desktop_study_transfer_smoke.run',return_value={'status':'passed'}) as run:
                self.assertEqual(main(['--study-transfer-smoke-test',str(output)]),0)
            run.assert_called_once_with(output)


if __name__=='__main__':unittest.main()
