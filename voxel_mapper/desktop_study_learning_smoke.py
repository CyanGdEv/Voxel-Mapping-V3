"""Actual managed image learning and restart from an explicitly synthetic dataset."""
from pathlib import Path

from PIL import Image, ImageDraw

from .building_spec import digest
from .desktop_runtime import DesktopRuntime, _wait, file_hash, write_json


def seed(directory):
    """Small portable fixture with distinct source groups and visible classes."""
    directory=Path(directory)
    if directory.exists():raise ValueError('Fresh study fixture directory required')
    directory.mkdir(parents=True)
    records=[];groups=[];pins={}
    for number in range(3):
        building='synthetic-study-'+str(number)
        source=chr(97+number)*64
        group_id=digest({'building_ids':[building],'source_sha256':[source]})
        group_records=[]
        for kind in ('door','window'):
            for variant in range(3):
                identifier=building+'-'+kind+'-'+str(variant)
                relative='examples/'+identifier+'/input.png'
                path=directory/relative;path.parent.mkdir(parents=True)
                image=Image.new('L',(32,32),255);draw=ImageDraw.Draw(image)
                shift=variant-1
                if kind=='door':
                    draw.rectangle((5+shift,4,12+shift,28),fill=20+number*4)
                else:
                    draw.rectangle((18+shift,8,28+shift,19),fill=20+number*4)
                image.save(path)
                pin=file_hash(path);pins[relative]=pin
                records.append({'id':identifier,'building_id':building,'kind':kind,
                    'source':{'document_sha256':source,'page':1},
                    'input_file':relative,'input_sha256':pin,'group_id':group_id,
                    'learning_eligible':True,'evidence_level':'synthetic_smoke_fixture',
                    'assumptions':['Synthetic image classification fixture; no real building evidence.']})
                group_records.append(identifier)
        groups.append({'group_id':group_id,'building_ids':[building],
            'source_sha256':[source],'record_ids':sorted(group_records)})
    manifest={'version':'retained-study-dataset-v1','dataset_kind':'synthetic_smoke_fixture',
        'records':records,'groups':sorted(groups,key=lambda group:group['group_id']),
        'output_sha256':pins,'world_placement_eligible':False,'park_world_blocks_added':0}
    manifest['id']=digest(manifest)
    write_json(directory/'dataset.json',manifest)
    return manifest


def run(output):
    from .study_component_learning import load_model, predict
    root=Path(output).expanduser().resolve()
    if root.exists():raise ValueError('Fresh study learning smoke output required')
    root.mkdir(parents=True)
    dataset=root/'dataset';manifest=seed(dataset)
    runtime=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
    try:
        jid=runtime.submit_study_training(dataset,epochs=60,hidden_units=16)
        job=_wait(runtime,jid,timeout=120);runtime._futures[jid].result(timeout=10)
        if job['status']!='completed':
            raise ValueError('Managed study training failed: '+str(job.get('error')))
        result=job['result'];directory=Path(job['output_directory'])
        model=load_model(directory/'model.json')
        if (result.get('status')!='exploratory_component_classifier_trained'
                or result.get('model_weights_updated') is not True
                or result.get('production_eligible') is not False
                or model.get('production_eligible') is not False):
            raise ValueError('Study checkpoint was not trained as a research-only model')
        if (result.get('training_labels_generated')!=0 or result.get('geometry_generated') is not False
                or result.get('park_world_blocks_added')!=0):
            raise ValueError('Component classification claimed new geometry or correctness labels')
        evaluation=result['cross_source_evaluation']
        if evaluation.get('status')!='assessed_leave_one_group_out' or evaluation.get('source_groups')!=3:
            raise ValueError('Independent source-group holdout evaluation was not performed')
        if len(evaluation.get('folds',[]))!=3:
            raise ValueError('Study evaluation omitted a synthetic source group')
        if (evaluation['metrics']['accuracy']<.9
                or evaluation['metrics']['accuracy']<=evaluation['baseline_metrics']['accuracy']):
            raise ValueError('Synthetic image recognition did not beat its source-held-out baseline')
        training=model['training']
        if not training['final_loss']<training['initial_loss']:
            raise ValueError('Actual synthetic image training did not reduce its learning loss')
        if model['artifact_sha256']!=result['model_sha256']:
            raise ValueError('Saved research checkpoint differs from the evaluated result')
        first=manifest['records'][0]
        if predict(model,dataset/first['input_file'])['kind']!=first['kind']:
            raise ValueError('Reopened research model cannot classify its synthetic source crop')
        if runtime.store.summary()['feedback_records'] or runtime.store.summary()['checkpoints']:
            raise ValueError('Study training created building-ranker labels or checkpoints')
        if runtime.store.setting('active_model') is not None:
            raise ValueError('Study checkpoint was activated as the building ranker')
        model_file_pin=file_hash(directory/'model.json')
    finally:runtime.close(wait=True)
    runtime=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
    try:
        retained=runtime.store.job(jid)
        if retained['status']!='completed' or retained['result']!=result:
            raise ValueError('Study training history did not survive restart')
        if file_hash(Path(retained['output_directory'])/'model.json')!=model_file_pin:
            raise ValueError('Saved study model changed during restart')
        reopened=load_model(Path(retained['output_directory'])/'model.json')
        if reopened['artifact_sha256']!=model['artifact_sha256']:
            raise ValueError('Research model integrity changed after restart')
        if runtime.store.setting('active_model') is not None:
            raise ValueError('Restart promoted the exploratory study checkpoint')
        if runtime.store.summary()['feedback_records'] or runtime.store.summary()['checkpoints']:
            raise ValueError('Restart invented building feedback or a ranker checkpoint')
    finally:runtime.close(wait=True)
    receipt={'status':'passed','dataset_kind':'synthetic_smoke_fixture','job':job,
        'dataset_id':manifest['id'],'dataset_manifest_sha256':file_hash(dataset/'dataset.json'),
        'training_records':len(manifest['records']),'source_groups':3,
        'actual_image_weight_updates_verified':True,'source_group_holdout_verified':True,
        'research_checkpoint_saved_and_reopened':True,'persistent_restart_verified':True,
        'active_building_ranker_unchanged':True,'production_eligible':False,
        'training_labels_generated':0,'geometry_generated':False,'park_world_blocks_added':0,
        'real_world_accuracy_assessed':False,'model_file_sha256':model_file_pin}
    write_json(root/'study-learning-smoke.json',receipt)
    return receipt
