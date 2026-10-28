"""Fixed, source-pinned multi-park expansion; reserved sites never enter fitting."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import resource
import time

import numpy as np
from PIL import Image
from pyproj import Transformer
from shapely.geometry import box

from . import aerial_surface_encoder as aerial, layered_surface_benchmark as data, layered_surface_learning as net
from .surface_dataset_expansion import training_records
from .generation_cycles import atomic_json, file_hash
from .lidar_surface_features import VERSION as LIDAR_VERSION, CHANNELS


def load_rows(root, feature_cache, lidar_cache, manifest):
    rows=[]
    for r in manifest['records']:
        rgb=np.array(Image.open(root/r['image_file']).convert('RGB'));g=np.array(Image.open(root/r['ground_file']));c=np.array(Image.open(root/r['canopy_file']))
        arrays=[]
        for cache,n in ((feature_cache,16),(lidar_cache,4)):
            p=cache/(r['id']+'.npz');receipt_file=cache/(r['id']+'.json');receipt=json.loads(receipt_file.read_text())
            if receipt['features_sha256']!=file_hash(p):raise ValueError('Feature hash differs')
            if n==16:
                if receipt['encoder_sha256']!=aerial.WEIGHTS or receipt['source_sha256']!=r['image_sha256']:raise ValueError('Frozen source encoder pin differs')
            else:
                from .dutch_surface_sources import VERSION as AHN_VERSION,validate_context_receipt
                if receipt.get('version')==AHN_VERSION:validate_context_receipt(receipt)
                elif receipt.get('version')!=LIDAR_VERSION:raise ValueError('Known LiDAR processor required')
                if receipt['image_sha256']!=r['image_sha256'] or receipt['channels']!=CHANNELS:raise ValueError('LiDAR source pin differs')
            with np.load(p,allow_pickle=False) as archive:f=archive['features']
            if f.shape!=(*g.shape,n) or not np.isfinite(f).all() or f.min()<0 or f.max()>1.00001:raise ValueError('Finite native features required')
            arrays.append(f)
        if not np.allclose(arrays[0][:,:,:3],rgb.astype(np.float32)/255,atol=1e-7):raise ValueError('Source RGB differs')
        rows.append({'record':r,'features':np.concatenate(arrays,2),'ground':g,'canopy':c,'lidar_pin':file_hash(lidar_cache/(r['id']+'.json')),'lidar_version':receipt['version']})
    return rows


def run(dataset,feature_cache,lidar_cache,protocol,baseline,alton_baseline,output):
    import torch
    torch.set_num_threads(2);start=time.monotonic();root=Path(dataset);out=Path(output)
    if out.exists():raise ValueError('Fresh experiment required; reserved evaluation may not be retuned')
    manifest=data.validate(root);p=json.loads(Path(protocol).read_text());settings={**net.SETTINGS,'lidar_dropout':.15}
    if p['version']!='surface-expansion-protocol-v1' or p['settings']!=settings or p['parent_dataset_id']!=manifest['parent_dataset_id'] or manifest['reserved_evaluation_site_ids']!=[p['reserved_site']] or p['automatic_promotion'] or p['selection_on_reserved_scores']:raise ValueError('Frozen non-promoting protocol required')
    if set(p['added_training_sites'])!={r['site_id'] for r in manifest['records'] if 'annotation_sha256' in r and not r['evaluation_only']}:raise ValueError('Added sites differ')
    out.mkdir(parents=True);rows=load_rows(root,Path(feature_cache),Path(lidar_cache),manifest)
    tr=Transformer.from_crs(3857,27700,always_xy=True);footprints=[]
    for r in rows:
        receipt=json.loads((root/r['record']['receipt_file']).read_text());footprints.append(box(*tr.transform_bounds(*receipt['extent_epsg3857'],densify_pts=21)))
    distances=[{'a':a['record']['id'],'b':b['record']['id'],'distance_m':footprints[i].distance(footprints[j])} for i,a in enumerate(rows) for j,b in enumerate(rows) if j>i and a['record']['site_id']!=b['record']['site_id']]
    if min(d['distance_m'] for d in distances)<24:raise ValueError('Cross-park geographic guard failed')
    atomic_json(out/'geographic-guard.json',{'required_m':24,'passed':True,'distances':distances,'within_site_overlap':'All views kept in one park group'})
    parents=[]
    for folder,excluded in ((baseline,()),(alton_baseline,('alton-towers',))):
        model,meta=net.load(folder);expected=[r for r in rows if 'annotation_sha256' not in r['record'] and r['record']['site_id'] not in excluded]
        if meta['dataset_id']!=p['parent_dataset_id'] or meta['training_record_ids']!=[r['record']['id'] for r in expected] or meta['training_source_sha256']!=[r['record']['image_sha256'] for r in expected] or meta['encoder_pin']!=aerial.WEIGHTS or meta['training']['settings']!=settings or meta['channels']!=20 or meta.get('lidar_feature_receipts_sha256')!=[r['lidar_pin'] for r in expected]:raise ValueError('Baseline lineage differs')
        parents.append((model,meta))
    atomic_json(out/'design.json',{'protocol':p,'protocol_sha256':file_hash(protocol),'dataset_id':manifest['id'],'independent_human_review':False,'encoder_updated':False,'single_seed':137,'production_eligible':False,'labels':'Provisional sparse source-assisted interiors; not full-scene or boundary truth'})
    models=[];fitrecords=[]
    for name,excluded in (('expanded',()),('alton-held-out',('alton-towers',))):
        ids={r['id'] for r in training_records(manifest,excluded)};fitrows=[r for r in rows if r['record']['id'] in ids];print('Fitting',name,[r['record']['id'] for r in fitrows],flush=True)
        model,training=net.fit(fitrows,balanced=True,settings=settings);folder=out/'models'/name;net.save(model,fitrows,manifest,folder,training,aerial.WEIGHTS);loaded,meta=net.load(folder);models.append((model,loaded,meta));fitrecords.append(fitrows)
    # Written after both fits, before any reserved prediction or scoring.
    atomic_json(out/'checkpoint-seal.json',{'created_utc':datetime.now(timezone.utc).isoformat(),'protocol_sha256':file_hash(protocol),'dataset_id':manifest['id'],'target_sha256':{r['record']['id']:{k:r['record'][k+'_sha256'] for k in ('ground','canopy')} for r in rows},'baseline_ids':[m['id'] for _,m in parents],'candidate_ids':[m['id'] for _,_,m in models],'reserved_scores_viewed':False})
    results=[];roundtrips=[]
    for comparison,index,held in [('reserved-flamingo',0,[r for r in rows if r['record']['evaluation_only']]),('alton-development',1,[r for r in rows if r['record']['site_id']=='alton-towers'])]:
        for row in held:
            for variant,model in [('parent',parents[index][0]),('expanded',models[index][0])]:
                print('Scoring',comparison,row['record']['id'],variant,flush=True);g,c,u=net.predict(model,row['features']);folder=out/'predictions'/comparison/row['record']['id']/variant;folder.mkdir(parents=True);Image.fromarray(g).save(folder/'ground.png');Image.fromarray(c).save(folder/'canopy.png');Image.fromarray(np.rint(u*255).astype(np.uint8)).save(folder/'uncertainty.png');score=net.score(row,g,c);atomic_json(folder/'scores.json',score)
                results.append({'comparison':comparison,'id':row['record']['id'],'variant':variant,'scores':score})
                if variant=='expanded':
                    gg,cc,_=net.predict(models[index][1],row['features']);match=np.array_equal(g,gg) and np.array_equal(c,cc)
                    if not match:raise ValueError('Checkpoint roundtrip changed predictions')
                    roundtrips.append({'id':row['record']['id'],'comparison':comparison,'exact':True})
    report={'version':'fixed-multi-park-surface-transfer-v1','dataset_id':manifest['id'],'results':results,'training_coverage':{name:meta['training']['ground_counts'] for name,(_,_,meta) in zip(('expanded','alton-held-out'),models)},'parameter_change_l2':{name:meta['training']['parameter_change_l2'] for name,(_,_,meta) in zip(('expanded','alton-held-out'),models)},'reserved_site_now_consumed':p['reserved_site'],'independent_human_review':False,'production_eligible':False,'baseline_replaced':False,'selection_on_reserved_scores':False,'scope':'Single-seed, assistant provisional sparse labels. Alton development already consumed; Flamingo prospectively reserved only for this experiment. No boundary precision claim.'}
    atomic_json(out/'report.json',report);atomic_json(out/'checkpoint-roundtrip.json',roundtrips);atomic_json(out/'resources.json',{'wall_seconds':time.monotonic()-start,'peak_rss_mb':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,'cpu_threads':2,'gpu_used':False});return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ('dataset','feature-cache','lidar-cache','protocol','baseline','alton-baseline','output'):parser.add_argument('--'+arg,required=True)
    run(**{k.replace('-','_'):v for k,v in vars(parser.parse_args()).items()})
