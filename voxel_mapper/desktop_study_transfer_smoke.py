"""Managed CPU feature extraction and learned heads on explicit synthetic RGB crops."""
from pathlib import Path

from PIL import Image
import numpy as np

from .building_spec import digest
from .desktop_runtime import DesktopRuntime, _wait, file_hash, write_json
from .desktop_study_context_smoke import _verify_held_out_templates


def seed(directory):
    """Keep outline/interior labels distinct and give the tiny RGB encoder a class cue."""
    from .desktop_study_context_smoke import seed as context_seed
    directory=Path(directory);manifest=context_seed(directory)
    for row in manifest['records']:
        path=directory/row['input_file']
        with Image.open(path) as original:
            ink=np.asarray(original)<128
        pixels=np.full((32,32,3),255,dtype=np.uint8)
        # The 3-D smoke encoder has no pretrained spatial features. Explicit
        # synthetic colour cues let its real CPU forward discriminate the two
        # fixture classes while their targets retain different filled regions.
        pixels[ink]=(180,20,20) if row['kind']=='door' else (20,20,180)
        Image.fromarray(pixels,mode='RGB').save(path)
        pin=file_hash(path);row['input_sha256']=pin
        manifest['output_sha256'][row['input_file']]=pin
        row['assumptions']=['Synthetic RGB class cue for a three-feature test encoder; hollow source outlines supervise filled target regions. No real planning evidence.']
    manifest['dataset_kind']='synthetic_transfer_smoke_fixture'
    manifest['id']=digest({key:value for key,value in manifest.items() if key!='id'})
    write_json(directory/'dataset.json',manifest)
    return manifest


def run(output):
    from .study_pretrained_encoder import encoder_info,synthetic_encoder
    from .study_transfer_learning import load_model,predict
    root=Path(output).expanduser().resolve()
    if root.exists():raise ValueError('Fresh study transfer smoke output required')
    root.mkdir(parents=True);dataset=root/'dataset';manifest=seed(dataset)
    fixture=synthetic_encoder(root/'synthetic-encoder.onnx')
    encoder=Path(fixture['path']);encoder_pin=fixture['sha256']
    info=encoder_info(encoder,encoder_pin,allow_synthetic=True)
    if (info.get('provider')!='CPUExecutionProvider' or info.get('synthetic') is not True
            or info.get('feature_count')!=3):
        raise ValueError('Transfer smoke requires its explicit three-feature CPU test encoder')
    runtime=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
    try:
        jid=runtime.submit_study_transfer(dataset,encoder,encoder_pin,ridge_alpha=100.,input_size=32)
        job=_wait(runtime,jid,timeout=30);runtime._futures[jid].result(timeout=10)
        if job['status']!='completed':raise ValueError('Managed study transfer training failed: '+str(job.get('error')))
        result=job['result'];directory=Path(job['output_directory']);model=load_model(directory/'model.json')
        if (result.get('status')!='exploratory_pretrained_transfer_trained'
                or result.get('model_weights_updated') is not True
                or result.get('encoder_weights_updated') is not False
                or result.get('production_eligible') is not False
                or result.get('mask_predictions_generated') is not True
                or model.get('production_eligible') is not False):
            raise ValueError('Transfer checkpoint did not retain frozen-encoder research scope')
        if (result.get('training_labels_generated')!=0 or result.get('geometry_generated') is not False
                or result.get('park_world_blocks_added')!=0 or file_hash(encoder)!=encoder_pin):
            raise ValueError('Transfer training changed the frozen encoder or generated geometry or ranker labels')
        evaluation=result['cross_source_evaluation']
        if (evaluation.get('status')!='assessed_leave_one_group_out'
                or evaluation.get('source_groups')!=3 or len(evaluation.get('folds',[]))!=3):
            raise ValueError('Transfer evaluation did not hold out all three source groups')
        _verify_held_out_templates(manifest,dataset,evaluation,directory)
        training=model['training']
        if (training.get('head_weights_updated') is not True
                or training.get('encoder_weights_updated') is not False
                or not training['final_loss']<training['initial_loss']
                or not training['final_class_loss']<training['initial_class_loss']
                or not training['final_mask_loss']<training['initial_mask_loss']):
            raise ValueError('Actual learned transfer heads did not improve their fitting losses')
        for name in ('class_weights','mask_weights'):
            weights=np.asarray(model['parameters'][name],dtype=float)
            if not np.isfinite(weights).all() or not np.any(weights!=0):
                raise ValueError('Saved transfer head remained at its zero-weight prior: '+name)
        target_masks=[]
        for row in manifest['records']:
            with Image.open(dataset/row['target_mask_file']) as target:
                target_masks.append(np.asarray(target,dtype=np.float64)/255.)
        reduced=np.asarray(target_masks).reshape(12,16,2,16,2).mean(axis=(2,4))
        initial={'class_weights':np.zeros_like(model['parameters']['class_weights']).tolist(),
            'class_bias':[.5,.5],'mask_weights':np.zeros_like(model['parameters']['mask_weights']).tolist(),
            'mask_bias':reduced.mean(axis=0).reshape(-1).tolist()}
        if training['initial_parameters_sha256']!=digest(initial):
            raise ValueError('Transfer head initialization differs from its balanced-class and target-mean priors')
        bundled=directory/model['encoder_file']
        if file_hash(bundled)!=encoder_pin:
            raise ValueError('Transfer checkpoint did not retain the exact frozen encoder')
        if (evaluation['metrics']['accuracy']<.9
                or evaluation['metrics']['accuracy']<=evaluation['majority_baseline_metrics']['accuracy']
                or evaluation['mask_metrics']['mean_soft_iou']<=evaluation['mean_mask_baseline_metrics']['mean_soft_iou']):
            raise ValueError('Synthetic transfer heads did not beat their source-held-out priors')
        if model['artifact_sha256']!=result['model_sha256']:
            raise ValueError('Reloaded transfer model differs from the managed training result')
        first=manifest['records'][0]
        prediction=predict(model,dataset/first['input_file'],encoder_path=encoder,encoder_sha256=encoder_pin)
        probabilities=np.asarray(prediction['mask_probabilities'],dtype=float)
        if (prediction['kind']!=first['kind'] or prediction.get('mask_size')!=[32,32]
                or probabilities.shape!=(32,32) or not np.isfinite(probabilities).all()
                or np.any(probabilities<0) or np.any(probabilities>1)):
            raise ValueError('Reloaded transfer checkpoint did not return its bounded crop class and mask')
        Image.fromarray(np.rint(probabilities*255).astype(np.uint8)).save(root/'reloaded-mask-proposal.png')
        if (runtime.store.setting('active_model') is not None or runtime.store.summary()['feedback_records']
                or runtime.store.summary()['checkpoints']):
            raise ValueError('Transfer research changed building-ranker state')
        model_pin=file_hash(directory/'model.json');prediction_pin=digest(prediction)
    finally:runtime.close(wait=True)
    runtime=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
    try:
        retained=runtime.store.job(jid)
        if retained['status']!='completed' or retained['result']!=result:
            raise ValueError('Transfer history did not survive restart')
        saved=Path(retained['output_directory'])/'model.json';reopened=load_model(saved)
        if (file_hash(saved)!=model_pin or reopened['artifact_sha256']!=model['artifact_sha256']
                or file_hash(encoder)!=encoder_pin
                or file_hash(saved.parent/reopened['encoder_file'])!=encoder_pin
                or digest(predict(reopened,dataset/first['input_file'],encoder_path=saved.parent/reopened['encoder_file'],encoder_sha256=encoder_pin))!=prediction_pin):
            raise ValueError('Transfer checkpoint, frozen encoder or prediction changed after restart')
        if (runtime.store.setting('active_model') is not None or runtime.store.summary()['feedback_records']
                or runtime.store.summary()['checkpoints']):
            raise ValueError('Restart promoted the transfer research checkpoint')
    finally:runtime.close(wait=True)
    receipt={'status':'passed','dataset_kind':manifest['dataset_kind'],'job':job,
        'dataset_id':manifest['id'],'dataset_manifest_sha256':file_hash(dataset/'dataset.json'),
        'training_records':12,'source_groups':3,'input_size':32,
        'synthetic_encoder_fixture_only':True,'cpu_execution_provider_verified':True,
        'encoder_provider':info['provider'],'encoder_runtime_version':info['runtime_version'],
        'encoder_feature_count':3,'encoder_file_sha256':encoder_pin,'encoder_weights_unchanged':True,
        'actual_learned_head_updates_verified':True,'source_group_holdout_verified':True,
        'exact_initial_head_lineage_verified':True,
        'bundled_encoder_reloaded':True,
        'training_only_templates_verified':True,'research_checkpoint_saved_and_reopened':True,
        'mask_prediction_reloaded':True,'persistent_restart_verified':True,'active_building_ranker_unchanged':True,
        'production_eligible':False,'training_labels_generated':0,'geometry_generated':False,
        'mask_predictions_generated':True,'park_world_blocks_added':0,'real_world_accuracy_assessed':False,
        'model_file_sha256':model_pin,'reloaded_prediction_sha256':prediction_pin}
    write_json(root/'study-transfer-smoke.json',receipt)
    return receipt
