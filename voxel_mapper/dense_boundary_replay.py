"""Provisional dense interface overlays and fixed replay, with whole-park exclusions."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import resource
import shutil
import time

import numpy as np
from PIL import Image

from . import layered_surface_benchmark as data,layered_surface_learning as net,aerial_surface_encoder as aerial
from .surface_transfer_experiment import load_rows
from .surface_dataset_expansion import training_records
from .generation_cycles import atomic_json,file_hash
from .desktop_memory import digest
from .tight_path_review import evaluate

VERSION='dense-surface-boundary-labels-v1'


def build(parent,annotations,output):
    parent=Path(parent);annotation_path=Path(annotations);out=Path(output);old=data.validate(parent);a=json.loads(annotation_path.read_text())
    if out.exists():raise ValueError('Fresh dense dataset required')
    if a.get('version')!=VERSION or a.get('parent_dataset_id')!=old['id'] or a.get('independent_human_review') is not False:raise ValueError('Pinned provisional source labels required')
    excluded=set(a.get('excluded_site_ids',[]));reserved=set(old.get('reserved_evaluation_site_ids',[]));windows=a.get('windows',[])
    if not excluded or not reserved<=excluded or not 1<=len(windows)<=24:raise ValueError('Consumed evaluation park must remain excluded')
    by={r['id']:r for r in old['records']};groups={}
    for window in windows:
        record=by.get(window.get('source_id'))
        if record is None or record['site_id'] in excluded or record.get('evaluation_only',False):raise ValueError('Dense labels cannot consume excluded evaluation sources')
        if window.get('source_sha256')!=record['image_sha256'] or window.get('independently_verified') is not False:raise ValueError('Source-bound draft labels required')
        if not re.fullmatch('[a-z0-9-]{1,80}',window.get('id','')) or any(window['id']==w['id'] for group in groups.values() for w in group):raise ValueError('Distinct bounded window IDs required')
        groups.setdefault(record['id'],[]).append(window)
    out.mkdir(parents=True);records=[];changes=[]
    for original in old['records']:
        if original['site_id'] in excluded:continue
        r=dict(original);r['evaluation_only']=False
        for key in ('image','receipt','ground','canopy','dense_windows','inferred'):
            dest=out/r[key+'_file'];dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(parent/r[key+'_file'],dest)
        if r['id'] in groups:
            ground=np.array(Image.open(parent/r['ground_file']));canopy=np.array(Image.open(parent/r['canopy_file']));inferred=np.array(Image.open(parent/r['inferred_file']));size=(ground.shape[1],ground.shape[0])
            new_g,new_c,scope=data.targets({'dense_windows':groups[r['id']],'canopy':[]},size,size,[[1,0,0],[0,1,0]],ground,inferred)
            # Do not erase or manufacture observed ground beneath existing canopy.
            new_g[canopy==1]=255;new_c[canopy==1]=1;new_c[~scope]=canopy[~scope];new_c[(inferred>0)&(canopy!=1)]=255
            prior_windows=np.array(Image.open(parent/r['dense_windows_file']))>0
            for key,array in [('ground',new_g),('canopy',new_c),('dense_windows',(prior_windows|scope).astype(np.uint8)*255)]:
                p=out/r[key+'_file'];Image.fromarray(array).save(p);r[key+'_sha256']=file_hash(p)
            r['ground_counts']={k:int((new_g==v).sum()) for k,v in data.GROUND.items()};r['canopy_counts']={k:int((new_c==v).sum()) for k,v in data.CANOPY.items()}
            if np.any(new_g[~scope]!=ground[~scope]) or np.any(new_c[~scope]!=canopy[~scope]):raise ValueError('Labels outside dense windows changed')
            changes.append({'id':r['id'],'window_ids':[w['id'] for w in groups[r['id']]],'changed_ground_pixels':int((ground!=new_g).sum()),'changed_canopy_pixels':int((canopy!=new_c).sum()),'outside_windows_changed':False,'existing_canopy_positive_retained':bool(np.all(new_c[canopy==1]==1))})
        records.append(r)
    recipe={'version':VERSION,'parent_dataset_id':old['id'],'parent_recipe_sha256':old['recipe_sha256'],'annotation_sha256':file_hash(annotation_path),'annotations':a}
    atomic_json(out/'recipe.json',recipe)
    m={'version':data.VERSION,'source_dataset_id':old['id'],'parent_dataset_id':old['id'],'recipe_sha256':file_hash(out/'recipe.json'),'ground_labels':data.GROUND,'canopy_labels':data.CANOPY,'records':records,'reserved_evaluation_site_ids':[],'excluded_consumed_site_ids':sorted(excluded),'independent_human_review':False,'production_eligible':False,'hidden_ground_used_as_observed_truth':False,'dense_overlay_changes':changes}
    m['id']=digest(m);atomic_json(out/'dataset.json',m);data.validate(out);return m


def run(dataset,feature_cache,lidar_cache,protocol,baseline,output,probes,registration):
    import torch
    torch.set_num_threads(2);start=time.monotonic();root=Path(dataset);out=Path(output);m=data.validate(root);p=json.loads(Path(protocol).read_text())
    expected={'dense_labels_only':{**net.SETTINGS,'lidar_dropout':.15},'boundary_replay':{**net.SETTINGS,'lidar_dropout':.15,'boundary_sampling_fraction':.4,'narrow_sampling_fraction':.3,'narrow_max_width_m':4.}}
    if out.exists() or p.get('version')!='dense-boundary-replay-protocol-v1' or p['parent_dataset_id']!=m['parent_dataset_id'] or p['variants']!=expected or p['automatic_promotion'] or p['selection_on_development_scores'] or p['reserved_site_used']:raise ValueError('Fresh fixed non-promoting replay protocol required')
    if p['excluded_consumed_site'] not in m['excluded_consumed_site_ids'] or any(r['site_id']==p['excluded_consumed_site'] for r in m['records']):raise ValueError('Consumed reserved site must be absent')
    recipe=json.loads((root/'recipe.json').read_text())
    if recipe['annotations']['protocol_sha256']!=file_hash(protocol):raise ValueError('Annotations must bind protocol before fitting')
    held=p['development_held_out_site'];source_sites={r['id']:r['site_id'] for r in m['records']}
    if any(source_sites.get(w['source_id']) not in p['new_labels_sites'] or source_sites.get(w['source_id'])==held for w in recipe['annotations']['windows']):raise ValueError('Dense overlays may not change the held-out park targets')
    fitrecords=training_records(m,[held]);ids={r['id'] for r in fitrecords};out.mkdir(parents=True)
    rows=load_rows(root,Path(feature_cache),Path(lidar_cache),m)
    from .imagery_capture_quality import audit
    for row in rows:
        receipt=json.loads((root/row['record']['receipt_file']).read_text());row['ground_sampling_m']=float(np.mean(audit(receipt)['approx_export_ground_sampling_m_xy']))
    fitrows=[r for r in rows if r['record']['id'] in ids];testrows=[r for r in rows if r['record']['site_id']==held]
    if not fitrows or not testrows:raise ValueError('Separate fitting and development parks required')
    parent,meta=net.load(baseline)
    if meta['dataset_id']!=p['parent_dataset_id'] or meta['training_record_ids']!=[r['record']['id'] for r in fitrows] or meta.get('lidar_feature_receipts_sha256')!=[r['lidar_pin'] for r in fitrows] or meta['training']['settings']!=expected['dense_labels_only'] or meta['encoder_pin']!=aerial.WEIGHTS or meta['channels']!=20 or meta['training_source_sha256']!=[r['record']['image_sha256'] for r in fitrows] or held in meta['training_site_ids']:raise ValueError('Excluded-park baseline lineage differs')
    atomic_json(out/'design.json',{'protocol':p,'protocol_sha256':file_hash(protocol),'annotations_sha256':recipe['annotation_sha256'],'dataset_id':m['id'],'development_only':True,'independent_human_review':False,'encoder_updated':False})
    models={'parent':parent};metadata={'parent':meta}
    for variant,settings in expected.items():
        print('Fitting',variant,[r['record']['id'] for r in fitrows],flush=True);model,training=net.fit(fitrows,balanced=True,settings=settings);folder=out/'models'/variant;net.save(model,fitrows,m,folder,training,aerial.WEIGHTS);loaded,metadata[variant]=net.load(folder);models[variant]=loaded
    # Final fit is predeclared, independent of development scores.
    finalrows=[r for r in rows if r['record']['id'] in {x['id'] for x in training_records(m)}]
    print('Fitting final boundary replay on six sources',flush=True);final_model,training=net.fit(finalrows,balanced=True,settings=expected['boundary_replay']);net.save(final_model,finalrows,m,out/'models/final-boundary-replay',training,aerial.WEIGHTS);loaded,finalmeta=net.load(out/'models/final-boundary-replay')
    atomic_json(out/'checkpoint-seal.json',{'created_utc':datetime.now(timezone.utc).isoformat(),'protocol_sha256':file_hash(protocol),'dataset_id':m['id'],'model_ids':{k:v['id'] for k,v in metadata.items()},'final_model_id':finalmeta['id'],'development_scores_viewed':False,'final_variant_predeclared':True})
    reg=json.loads(Path(registration).read_text());probe_list=json.loads(Path(probes).read_text())['probes'];results=[]
    for row in testrows:
        for variant,model in models.items():
            print('Scoring unchanged Alton development',row['record']['id'],variant,flush=True);g,c,u=net.predict(model,row['features']);folder=out/'predictions'/row['record']['id']/variant;folder.mkdir(parents=True);Image.fromarray(g).save(folder/'ground.png');Image.fromarray(c).save(folder/'canopy.png');Image.fromarray(np.rint(u*255).astype(np.uint8)).save(folder/'uncertainty.png');s=net.score(row,g,c)
            if row['record']['id']=='user-tight-gardens':s['local_paths']=evaluate(row['ground'],g,reg,probe_list)
            atomic_json(folder/'scores.json',s);results.append({'id':row['record']['id'],'variant':variant,'scores':s})
    # Fitted previews only, never presented as validation.
    checks=[]
    for row in finalrows:
        g,c,u=net.predict(loaded,row['features']);folder=out/'fitted-previews'/row['record']['id'];folder.mkdir(parents=True);Image.fromarray(g).save(folder/'ground.png');Image.fromarray(c).save(folder/'canopy.png')
        # Compare the saved final checkpoint to its original in-memory model.
        gg,cc,_=net.predict(final_model,row['features']);assert np.array_equal(g,gg) and np.array_equal(c,cc);checks.append({'id':row['record']['id'],'exact_checkpoint_reload':True})
    report={'version':'dense-boundary-replay-development-v1','dataset_id':m['id'],'results':results,'training':{k:v['training'] for k,v in metadata.items()},'final_training':finalmeta['training'],'final_training_sites':finalmeta['training_site_ids'],'excluded_consumed_site':p['excluded_consumed_site'],'reserved_site_used':False,'production_eligible':False,'baseline_replaced':False,'selection_on_development_scores':False,'independent_human_review':False,'scope':'Previously consumed Alton development labels. Dense new windows are fitting labels, not validation; no fresh blind or independent precision claim.'}
    atomic_json(out/'report.json',report);atomic_json(out/'checkpoint-roundtrip.json',checks);atomic_json(out/'resources.json',{'wall_seconds':time.monotonic()-start,'peak_rss_mb':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,'cpu_threads':2,'gpu_used':False});return report


def validate_review(note,annotation_file,dataset_id):
    """Bind reviewer decisions to exact draft labels; never rewrite training truth."""
    if not isinstance(note,dict):raise ValueError('Boundary review object required')
    path=Path(annotation_file);a=json.loads(path.read_text());windows={w['id']:w for w in a['windows']}
    if note.get('version')!='dense-boundary-review-notes-v1' or note.get('dataset_id')!=dataset_id or note.get('annotation_sha256')!=file_hash(path):raise ValueError('Stale or different boundary review labels')
    if not isinstance(note.get('reviewer'),str) or len(note['reviewer'])>120:raise ValueError('Bounded reviewer identity required')
    rows=note.get('notes');seen=set()
    if not isinstance(rows,list) or len(rows)>len(windows):raise ValueError('Bounded boundary review decisions required')
    for row in rows:
        if not isinstance(row,dict):raise ValueError('Review decision object required')
        w=windows.get(row.get('window_id'))
        if not w or w['id'] in seen or row.get('source_sha256')!=w['source_sha256']:raise ValueError('Review source/window differs')
        if row.get('status') not in ('unreviewed','accept','reject','needs_correction') or not isinstance(row.get('comment'),str) or len(row['comment'])>2000:raise ValueError('Known bounded review decision required')
        seen.add(w['id'])
    return {'valid':True,'reviewed_windows':sum(r['status']!='unreviewed' for r in rows),'accepted_windows':sum(r['status']=='accept' for r in rows),'total_windows':len(windows),'changes_training_labels':False,'independent_human_truth_established':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='mode',required=True);b=sub.add_parser('build')
    for arg in ('parent','annotations','output'):b.add_argument('--'+arg,required=True)
    t=sub.add_parser('train')
    for arg in ('dataset','feature-cache','lidar-cache','protocol','baseline','output','probes','registration'):t.add_argument('--'+arg,required=True)
    n=sub.add_parser('review-notes')
    for arg in ('notes','annotations','dataset-id'):n.add_argument('--'+arg,required=True)
    args=vars(parser.parse_args());mode=args.pop('mode')
    if mode=='build':result=build(**args)
    elif mode=='train':result=run(**args)
    else:
        note_path=Path(args['notes'])
        if note_path.stat().st_size>100000:raise ValueError('Bounded boundary review notes required')
        result=validate_review(json.loads(note_path.read_text()),args['annotations'],args['dataset_id'])
    print(json.dumps(result))
