"""Managed whole-crop context learning from outlines to filled regions."""
from pathlib import Path

from PIL import Image, ImageDraw
import numpy as np

from .building_spec import digest
from .desktop_runtime import DesktopRuntime, _wait, file_hash, write_json


def seed(directory):
    """Hollow source outlines and filled target regions from three source groups."""
    directory=Path(directory)
    if directory.exists():raise ValueError('Fresh study context fixture directory required')
    directory.mkdir(parents=True)
    records=[];groups=[];pins={}
    for number in range(3):
        building='synthetic-context-'+str(number);source=chr(100+number)*64
        group_id=digest({'building_ids':[building],'source_sha256':[source]})
        group_records=[]
        for kind in ('door','window'):
            for variant in range(2):
                identifier=building+'-'+kind+'-'+str(variant)
                base='examples/'+identifier+'/'
                input_file=base+'input.png';mask_file=base+'target-mask.png'
                path=directory/input_file;path.parent.mkdir(parents=True)
                image=Image.new('L',(32,32),255);mask=Image.new('L',(32,32),0)
                shift=2*variant-1
                bounds=(5+shift,4,15+shift,27) if kind=='door' else (6+shift,10,27+shift,21)
                ImageDraw.Draw(image).rectangle(bounds,outline=20+number*4,width=1)
                ImageDraw.Draw(mask).rectangle(bounds,fill=255)
                if kind=='window':
                    hole=(14+shift,13,19+shift,18)
                    ImageDraw.Draw(image).rectangle(hole,outline=20+number*4,width=1)
                    ImageDraw.Draw(mask).rectangle(hole,fill=0)
                image.save(path);mask.save(directory/mask_file)
                input_pin=file_hash(path);mask_pin=file_hash(directory/mask_file)
                pins[input_file]=input_pin;pins[mask_file]=mask_pin
                records.append({'id':identifier,'building_id':building,'kind':kind,
                    'source':{'document_sha256':source,'page':1},'input_file':input_file,
                    'input_sha256':input_pin,'target_mask_file':mask_file,'target_mask_sha256':mask_pin,
                    'group_id':group_id,'learning_eligible':True,'evidence_level':'synthetic_smoke_fixture',
                    'assumptions':['Synthetic outline-to-filled-region task including interior holes; no real planning evidence.']})
                group_records.append(identifier)
        groups.append({'group_id':group_id,'building_ids':[building],
            'source_sha256':[source],'record_ids':sorted(group_records)})
    manifest={'version':'retained-study-dataset-v1','dataset_kind':'synthetic_context_smoke_fixture',
        'records':records,'groups':sorted(groups,key=lambda group:group['group_id']),
        'output_sha256':pins,'world_placement_eligible':False,'park_world_blocks_added':0}
    manifest['id']=digest(manifest);write_json(directory/'dataset.json',manifest)
    return manifest


def _verify_held_out_templates(manifest,dataset,evaluation,directory):
    """Reconstruct each mean template from its fitting groups and pinned masks."""
    records={row['id']:row for row in manifest['records']}
    predictions=evaluation['predictions']
    if sorted(row['record_id'] for row in predictions)!=sorted(records):
        raise ValueError('Context evaluation did not predict every held-out record exactly once')
    for fold in evaluation['folds']:
        fitting=[row for row in records.values() if row['group_id'] not in fold['held_out_group_ids']]
        held=[row for row in records.values() if row['group_id'] in fold['held_out_group_ids']]
        if (fold['training_record_ids']!=sorted(row['id'] for row in fitting)
                or fold['evaluation_record_ids']!=sorted(row['id'] for row in held)
                or set(fold['training_sources'])&set(fold['evaluation_sources'])
                or set(fold['training_buildings'])&set(fold['evaluation_buildings'])):
            raise ValueError('Context evaluation leaked a held-out source, building or record')
        masks=[]
        for row in fitting:
            with Image.open(dataset/row['target_mask_file']) as image:
                masks.append(np.asarray(image,dtype=np.float64)/255.)
        mean=np.asarray(masks).mean(axis=0)
        if fold['mean_mask_baseline_sha256']!=digest(mean.tolist()):
            raise ValueError('Context template baseline used labels outside its fitting groups')
        for prediction in (row for row in predictions if row['fold_id']==fold['id']):
            path=directory/prediction['baseline_mask_file']
            with Image.open(path) as image:
                if not np.array_equal(np.asarray(image),np.rint(mean*255).astype(np.uint8)):
                    raise ValueError('Saved context template differs from its fitting-only target mean')
            if file_hash(path)!=prediction['baseline_mask_sha256']:
                raise ValueError('Saved context template differs from its receipt')


def run(output):
    from .study_context_learning import load_model, predict
    from .study_context_network import initialize
    root=Path(output).expanduser().resolve()
    if root.exists():raise ValueError('Fresh study context smoke output required')
    root.mkdir(parents=True);dataset=root/'dataset';manifest=seed(dataset)
    for row in manifest['records']:
        with Image.open(dataset/row['input_file']) as image,Image.open(dataset/row['target_mask_file']) as target:
            ink=np.asarray(image)<128;filled=np.asarray(target)>128
            if np.array_equal(ink,filled) or np.count_nonzero(filled&~ink)<30:
                raise ValueError('Context fixture must learn filled interiors from distinct source outlines')
    runtime=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
    try:
        jid=runtime.submit_study_context(dataset,epochs=40,channels=4,input_size=32)
        job=_wait(runtime,jid,timeout=120);runtime._futures[jid].result(timeout=10)
        if job['status']!='completed':raise ValueError('Managed study context training failed: '+str(job.get('error')))
        result=job['result'];directory=Path(job['output_directory']);model=load_model(directory/'model.json')
        if (result.get('status')!='exploratory_component_context_trained'
                or result.get('model_weights_updated') is not True
                or result.get('mask_predictions_generated') is not True
                or result.get('production_eligible') is not False
                or model.get('production_eligible') is not False):
            raise ValueError('Context checkpoint did not retain research-only type/mask training scope')
        if (result.get('training_labels_generated')!=0 or result.get('geometry_generated') is not False
                or result.get('park_world_blocks_added')!=0):
            raise ValueError('Source-crop masks became physical geometry or correctness labels')
        evaluation=result['cross_source_evaluation']
        if evaluation.get('status')!='assessed_leave_one_group_out' or evaluation.get('source_groups')!=3:
            raise ValueError('Context evaluation did not hold out three independent source groups')
        if len(evaluation.get('folds',[]))!=3:
            raise ValueError('Context evaluation omitted a source group')
        _verify_held_out_templates(manifest,dataset,evaluation,directory)
        training=model['training']
        if (not training['final_loss']<training['initial_loss']
                or not training['final_mask_loss']<training['initial_mask_loss']
                or training.get('conv_filters_updated') is not True
                or training.get('context_decoder_updated') is not True):
            raise ValueError('Actual convolution and global context decoder training did not improve its learning loss')
        initial=initialize(input_size=32,channels=4,classes=len(model['classes']),seed=training['seed'],
            mask_prior=np.asarray(model['network']['mask_prior']))
        if digest({key:value.tolist() for key,value in initial.items()})!=training['initial_parameters_sha256']:
            raise ValueError('Context training initialization differs from its saved source lineage')
        if not any(np.any(np.asarray(model['network']['parameters'][key])!=initial[key])
                   for key in ('conv1_weights','conv2_weights')):
            raise ValueError('Saved convolution filters remained at their initial weights')
        for key in ('context_weights','mask_weights'):
            if not np.any(np.asarray(model['network']['parameters'][key])!=initial[key]):
                raise ValueError('Saved global context decoder weights remained at initialization: '+key)
        if (evaluation['metrics']['accuracy']<.9
                or evaluation['metrics']['accuracy']<=evaluation['majority_baseline_metrics']['accuracy']):
            raise ValueError('Synthetic crop recognition did not beat its source-held-out majority baseline')
        if (evaluation['mask_metrics']['mean_binary_iou']
                <=evaluation['mean_mask_baseline_metrics']['mean_binary_iou']):
            raise ValueError('Synthetic mask proposals did not beat the training-only mean-mask baseline')
        if (evaluation['mask_metrics']['mean_soft_iou']
                <=evaluation['mean_mask_baseline_metrics']['mean_soft_iou']):
            raise ValueError('Synthetic soft mask proposals did not beat the fitting-only mean-mask baseline')
        if model['artifact_sha256']!=result['model_sha256']:
            raise ValueError('Saved context checkpoint differs from the managed training result')
        first=manifest['records'][0];prediction=predict(model,dataset/first['input_file'])
        if prediction['kind']!=first['kind']:
            raise ValueError('Reloaded context model did not recognize its synthetic crop type')
        probabilities=np.asarray(prediction['mask_probabilities'],dtype=float)
        if (prediction.get('mask_size')!=[32,32] or probabilities.shape!=(32,32)
                or not np.isfinite(probabilities).all() or np.any(probabilities<0) or np.any(probabilities>1)):
            raise ValueError('Reloaded context model did not return a bounded 32-pixel mask proposal')
        Image.fromarray(np.rint(probabilities*255).astype(np.uint8)).save(root/'reloaded-mask-proposal.png')
        if runtime.store.summary()['feedback_records'] or runtime.store.summary()['checkpoints']:
            raise ValueError('Context training generated building-ranker labels or checkpoints')
        if runtime.store.setting('active_model') is not None:
            raise ValueError('Context checkpoint replaced the active building ranker')
        model_pin=file_hash(directory/'model.json');prediction_pin=digest(prediction)
    finally:runtime.close(wait=True)
    runtime=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
    try:
        retained=runtime.store.job(jid)
        if retained['status']!='completed' or retained['result']!=result:
            raise ValueError('Context training history did not survive restart')
        saved=Path(retained['output_directory'])/'model.json';reopened=load_model(saved)
        if file_hash(saved)!=model_pin or reopened['artifact_sha256']!=model['artifact_sha256']:
            raise ValueError('Context checkpoint changed after restart')
        if digest(predict(reopened,dataset/first['input_file']))!=prediction_pin:
            raise ValueError('Reloaded context class/mask prediction changed after restart')
        if runtime.store.setting('active_model') is not None:
            raise ValueError('Restart promoted the exploratory context checkpoint')
        if runtime.store.summary()['feedback_records'] or runtime.store.summary()['checkpoints']:
            raise ValueError('Restart invented building feedback or a ranker checkpoint')
    finally:runtime.close(wait=True)
    receipt={'status':'passed','dataset_kind':'synthetic_context_smoke_fixture','job':job,
        'dataset_id':manifest['id'],'dataset_manifest_sha256':file_hash(dataset/'dataset.json'),
        'training_records':len(manifest['records']),'source_groups':3,'input_size':32,'channels':4,
        'actual_convolution_weight_updates_verified':True,'source_group_holdout_verified':True,
        'actual_global_context_decoder_updates_verified':True,'training_only_templates_verified':True,
        'source_outline_pixels_differ_from_filled_targets':True,'target_holes_retained':True,
        'research_checkpoint_saved_and_reopened':True,'mask_prediction_reloaded':True,
        'persistent_restart_verified':True,'active_building_ranker_unchanged':True,
        'production_eligible':False,'training_labels_generated':0,'geometry_generated':False,
        'mask_predictions_generated':True,'park_world_blocks_added':0,'real_world_accuracy_assessed':False,
        'model_file_sha256':model_pin,'reloaded_prediction_sha256':prediction_pin}
    write_json(root/'study-context-smoke.json',receipt)
    return receipt
