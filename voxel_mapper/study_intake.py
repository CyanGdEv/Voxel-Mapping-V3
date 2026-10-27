"""Portable multi-source study intake with site-isolated evaluation reservations.

Existing reviewed crop labels may be retained. Context assets and review feedback
never become labels, and an export or test pass is never physical acceptance.
"""
import argparse
import copy
from collections import Counter
from html import escape
import json
from pathlib import Path
import re
import shutil
import tempfile

from .building_spec import digest
from .generation_cycles import atomic_json
from . import study_component_learning as reader
from .study_dataset import connected_groups,file_hash

VERSION='multi-source-study-intake-v1'
KINDS={'planning_pdf','lidar','photograph','orthophoto','cad','minecraft_reference','correction_review'}
DECISIONS={'accepted','rejected','unreviewed'}


def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}',value):
        raise ValueError('Safe bounded intake identity required')
    return value


def text(value,name,limit=4000):
    if not isinstance(value,str) or not value.strip() or len(value)>limit:
        raise ValueError('Bounded '+name+' required')
    return value


def input_path(base,value):
    text(value,'input path')
    path=Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (base/path).resolve()


def reservation(rows,evaluation_sites,assets):
    """Whole sites, physical identities, source PDFs and shared inputs stay apart."""
    sites={r['site_id'] for r in rows};evaluation=set(evaluation_sites)
    if evaluation-sites:raise ValueError('Evaluation sites must contain selected eligible records')
    training=sites-evaluation
    train=[r for r in rows if r['site_id'] in training];held=[r for r in rows if r['site_id'] in evaluation]
    for name,values in [
        ('building identity',lambda r:{r['building_id']}),
        ('source document',lambda r:{r['source']['document_sha256']}),
        ('source crop',lambda r:{r['input_sha256']})]:
        a={v for r in train for v in values(r)};b={v for r in held for v in values(r)}
        if a&b:raise ValueError('Cross-site evaluation leakage through '+name)
    a={r['sha256'] for r in assets if set(r['site_ids'])&training}
    b={r['sha256'] for r in assets if set(r['site_ids'])&evaluation}
    if a&b:raise ValueError('Cross-site evaluation leakage through shared context asset')
    ready=bool(train and held)
    classes=set(r['kind'] for r in train)
    return {'status':'site_reservation_ready' if ready else 'awaiting_independent_evaluation_site',
        'training_sites':sorted(training),'evaluation_sites':sorted(evaluation),
        'training_record_ids':sorted(r['id'] for r in train),'evaluation_record_ids':sorted(r['id'] for r in held),
        'evaluation_classes_absent_from_training':sorted({r['kind'] for r in held}-classes),
        'is_accuracy_or_production_readiness':False,
        'single_site_random_split_used':False,'model_weights_updated':False}


def build(request_path,output,*,cancelled=lambda:False):
    request_path=Path(request_path).resolve();output=Path(output)
    request,raw=reader._json(request_path,8_000_000)
    if not isinstance(request,dict) or request.get('version')!=VERSION:raise ValueError('Current intake request version required')
    definitions=request.get('datasets');evaluation=request.get('evaluation_sites',[])
    if not isinstance(definitions,list) or not 1<=len(definitions)<=16:raise ValueError('One to sixteen source datasets required')
    if not isinstance(evaluation,list) or len(evaluation)!=len(set(evaluation)):raise ValueError('Unique explicit evaluation sites required')
    for site in evaluation:identifier(site)
    contexts=request.get('context_assets',[]);feedback=request.get('feedback',[])
    if not isinstance(contexts,list) or len(contexts)>128 or not isinstance(feedback,list) or len(feedback)>2048:raise ValueError('Bounded context and feedback inventory required')
    if output.exists():raise ValueError('Fresh intake output directory required')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='study-intake-',dir=output.parent) as temporary:
        stage=Path(temporary)/'result';stage.mkdir();rows=[];excluded=[];origins=[];assets=[];seen=set();copied=0
        def copy_asset(source,name,pin):
            nonlocal copied
            reader._check(cancelled)
            if not reader._hash(pin) or not source.is_file() or source.stat().st_size>reader.MAX_ASSET_BYTES or file_hash(source)!=pin:
                raise ValueError('Pinned bounded intake asset required: '+name)
            copied+=source.stat().st_size
            if copied>reader.MAX_TOTAL_ASSET_BYTES:raise ValueError('Intake asset byte budget exceeded')
            target=reader._asset(stage,name);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
            if file_hash(target)!=pin or file_hash(source)!=pin:raise ValueError('Intake asset changed while copying')
        for definition in definitions:
            reader._check(cancelled)
            key=identifier(definition.get('id'));site=identifier(definition.get('site_id'))
            if key in seen:raise ValueError('Unique source dataset identities required')
            seen.add(key);directory=input_path(request_path.parent,definition.get('directory'))
            manifest,eligible,unused,pin=reader.read_dataset(directory,cancelled=cancelled);del unused
            if definition.get('manifest_sha256')!=pin:raise ValueError('Source dataset manifest changed')
            if manifest['dataset_kind'].startswith('synthetic'):raise ValueError('Synthetic datasets require a separate experiment, not real-source intake')
            selected=definition.get('record_ids',[r['id'] for r in eligible]);all_ids={r['id'] for r in manifest['records']}
            if not isinstance(selected,list) or len(selected)!=len(set(selected)) or set(selected)-all_ids:raise ValueError('Unique selected source record identities required')
            decisions=definition.get('record_decisions',{})
            if not isinstance(decisions,dict) or set(decisions)-set(selected) or any(v not in DECISIONS for v in decisions.values()):raise ValueError('Known selected-record review decisions required')
            prefix='datasets/'+key+'/'
            for name,asset_pin in manifest['output_sha256'].items():copy_asset(reader._asset(directory,name),prefix+name,asset_pin)
            copy_asset(directory/'dataset.json',prefix+'dataset.json',pin)
            eligible_by_id={r['id']:r for r in eligible}
            for rid in selected:
                decision=decisions.get(rid,'accepted')
                if decision!='accepted' or rid not in eligible_by_id:
                    excluded.append({'dataset_id':key,'site_id':site,'record_id':rid,'decision':decision,'reason':'review_withheld' if decision!='accepted' else 'upstream_not_learning_eligible'});continue
                original=eligible_by_id[rid];row=copy.deepcopy(original)
                row.update(id=key+'-'+digest(rid)[:24],site_id=site,origin_dataset_id=key,origin_record_id=rid,
                    origin_dataset_manifest_sha256=pin,review_assets_root=prefix+'reviews')
                for field in ['input_file','target_file','target_mask_file']:
                    if field in row:row[field]=prefix+row[field]
                row.pop('record_sha256',None);rows.append(row)
            origins.append({'id':key,'site_id':site,'manifest_sha256':pin,'manifest_file':prefix+'dataset.json',
                'original_dataset_id':manifest['id'],'selected_records':len(selected),'retained_records':sum(r['origin_dataset_id']==key for r in rows)})
        if not rows or len(rows)>reader.MAX_RECORDS:raise ValueError('One to 2048 retained reviewed rows required')
        sites={r['site_id'] for r in rows}
        for context in contexts:
            key=identifier(context.get('id'))
            if key in {r['id'] for r in assets}:raise ValueError('Unique context identities required')
            site_ids=context.get('site_ids')
            if not isinstance(site_ids,list) or not site_ids or len(site_ids)!=len(set(site_ids)) or set(site_ids)-sites:raise ValueError('Context must name known unique sites')
            if context.get('kind') not in KINDS:raise ValueError('Known evidence modality required')
            if context.get('source_state','unknown') not in ['existing','proposed','unknown']:raise ValueError('Known source state required')
            source=input_path(request_path.parent,context.get('path'));suffix=source.suffix.lower()
            if not re.fullmatch(r'\.[a-z0-9]{1,10}',suffix):raise ValueError('Simple context file extension required')
            name='context/'+key+suffix;copy_asset(source,name,context.get('sha256'))
            assets.append({'id':key,'site_ids':site_ids,'kind':context['kind'],'file':name,'sha256':context['sha256'],
                'source':text(context.get('source'),'context source'),'license':text(context.get('license'),'context reuse description'),
                'epoch':text(context.get('epoch','unknown'),'context epoch'),'source_state':context.get('source_state','unknown'),
                'role':'reference_context_only','learning_eligible':False})
        decisions=[];feedback_ids=set();asset_ids={r['id'] for r in assets}
        for case in feedback:
            key=identifier(case.get('id'))
            if key in feedback_ids or case.get('result_asset_id') not in asset_ids or case.get('decision') not in DECISIONS:raise ValueError('Unique feedback on an existing context result required')
            feedback_ids.add(key)
            decisions.append({'id':key,'result_asset_id':case['result_asset_id'],'decision':case['decision'],
                'reason':text(case.get('reason'),'feedback reason'),'review_basis':text(case.get('review_basis'),'review provenance'),
                'training_labels_generated':0,'automatically_promoted':False})
        groups=connected_groups(rows);owners={rid:g['group_id'] for g in groups for rid in g['record_ids']}
        for row in rows:row['group_id']=owners[row['id']];row['record_sha256']=digest(row)
        split=reservation(rows,evaluation,assets)
        manifest={'version':reader.DATASET_VERSION,'dataset_kind':'multi_source_reviewed_study_intake',
            'records':rows,'groups':groups,'input_datasets':origins,'context_assets':assets,
            'review_feedback':decisions,'excluded_records':excluded,'site_reservation':split,
            'source_request_sha256':reader._sha(raw),'summary':{'reviewed_examples_retained':len(rows),
                'sites':len(sites),'source_connected_groups':len(groups),'classes':dict(sorted(Counter(r['kind'] for r in rows).items())),
                'excluded_examples':len(excluded),'context_assets':len(assets),'feedback_cases':len(decisions)},
            'training_labels_generated':0,'model_weights_updated':False,'physical_geometry_verified':False,'world_placement_eligible':False,
            'limitations':['Upstream reviewed crop labels are retained; intake does not authenticate physical correctness.',
                'Context files and feedback never become labels, regardless of an accepted disposition.',
                'A reserved site is an evaluation boundary, not evidence of model accuracy. Existing trainers must explicitly honour this reservation.']}
        atomic_json(stage/'site-reservation.json',split)
        table=''.join('<tr><td><a href="'+escape(r['file'],quote=True)+'">'+escape(str(r['id']))+'</a></td><td>'+escape(r['kind'])+'</td><td>'+escape(', '.join(r['site_ids']))+'</td><td>Reference only</td></tr>' for r in assets)
        galleries=''.join('<p><a href="datasets/'+escape(r['id'],quote=True)+'/index.html">'+escape(r['id'])+' source crops and reviewed masks</a></p>' for r in origins if (stage/'datasets'/r['id']/'index.html').is_file())
        (stage/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Multi-source study intake</title><h1>Study evidence intake</h1><p>'+str(len(rows))+' reviewed component examples; '+str(len(sites))+' site(s). Evaluation: '+escape(split['status'])+'. No new training or physical acceptance.</p>'+galleries+'<table><tr><th>Evidence</th><th>Type</th><th>Sites</th><th>Use</th></tr>'+table+'</table><p>See dataset.json for source lineage, exclusions and feedback. Context assets do not supply training labels.</p>',encoding='utf-8')
        manifest['output_sha256']={f.relative_to(stage).as_posix():file_hash(f) for f in sorted(stage.rglob('*')) if f.is_file()}
        manifest['id']=digest(manifest);atomic_json(stage/'dataset.json',manifest)
        reader.read_dataset(stage,cancelled=cancelled,allow_reserved_evaluation=True)
        reader._check(cancelled);shutil.move(stage,output)
    return manifest


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args(argv);report=build(args.request,args.output)
    print(json.dumps({'id':report['id'],**report['summary'],'evaluation':report['site_reservation']['status'],'model_weights_updated':False}))

if __name__=='__main__':main()
