"""Fixed Dutch RGB-detail comparison with unchanged labels, extent and height inputs."""
import argparse
import gc
from datetime import datetime,timezone
import json
from pathlib import Path
import resource
import shutil
import time

import numpy as np
from PIL import Image
from pyproj import Geod,Transformer

from . import aerial_surface_encoder as aerial,layered_surface_benchmark as data,layered_surface_learning as net,dutch_surface_sources as dutch
from .surface_dataset_expansion import training_records
from .surface_transfer_experiment import load_rows
from .generation_cycles import atomic_json,file_hash
from .desktop_memory import digest


def coarsen_dataset(native,output,sites=('efteling','toverland')):
    root=Path(native);out=Path(output);m=data.validate(root)
    if out.exists():raise ValueError('Fresh controlled coarse dataset required')
    if set(sites)!={'efteling','toverland'} or not set(sites)<={r['site_id'] for r in m['records']}:raise ValueError('Two declared Dutch sites required')
    out.mkdir(parents=True);records=[];transforms={}
    for original in m['records']:
        r=dict(original)
        for key in ('image','receipt','ground','canopy','dense_windows','inferred'):
            dest=out/r[key+'_file'];dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/r[key+'_file'],dest)
        if r['site_id'] in sites:
            receipt=json.loads((root/r['receipt_file']).read_text());spacing=receipt['grid']['spacing_m']
            if abs(spacing-.08)>1e-8 or receipt['layer']!='2025_orthoHR':raise ValueError('Fixed eight-centimetre 2025 source grid required')
            rgb=np.array(Image.open(root/r['image_file']).convert('RGB'));coarse,processing=dutch.coarse_rgb(rgb,spacing,.25);p=out/r['image_file'];Image.fromarray(coarse).save(p,format='PNG');r['image_sha256']=file_hash(p)
            receipt.update(version='controlled-aerial-coarsening-v1',image_sha256=r['image_sha256'],derived_from_native_image_sha256=original['image_sha256'],original_receipt_sha256=original['receipt_sha256'],processing=processing,adds_optical_information=False)
            atomic_json(out/r['receipt_file'],receipt);r['receipt_sha256']=file_hash(out/r['receipt_file']);r['label_source_original_sha256']=original['image_sha256'];transforms[r['id']]=processing
        records.append(r)
    recipe={'version':'dutch-rgb-coarse-dataset-v1','native_dataset_id':m['id'],'native_recipe_sha256':m['recipe_sha256'],'transforms':transforms,'labels_unchanged':True,'old_uk_images_unchanged':True}
    atomic_json(out/'recipe.json',recipe);new={**m,'records':records,'recipe_sha256':file_hash(out/'recipe.json'),'source_dataset_id':m['id'],'comparison_native_dataset_id':m['id'],'controlled_rgb_detail_only':True};new.pop('id',None);new['id']=digest(new);atomic_json(out/'dataset.json',new);data.validate(out);return new


def prepare_caches(native,coarse,parent_features,parent_lidar,sources,encoder,output):
    out=Path(output)
    if out.exists():raise ValueError('Fresh source-only feature caches required')
    enc=None;receipts=[]
    for variant,root in [('native_rgb',Path(native)),('coarse_rgb',Path(coarse))]:
        m=data.validate(root);cache=out/variant; (cache/'features').mkdir(parents=True);(cache/'lidar-features').mkdir()
        for r in m['records']:
            id=r['id']
            if r['site_id'] not in ('efteling','toverland'):
                for name,source in [('features',Path(parent_features)),('lidar-features',Path(parent_lidar))]:
                    for extension in ('.npz','.json'):shutil.copy2(source/(id+extension),cache/name/(id+extension))
                continue
            if enc is None:enc=aerial.Encoder(encoder)
            rgb=np.array(Image.open(root/r['image_file']).convert('RGB'));features=enc.features(rgb);dest=cache/'features'/(id+'.npz');np.savez_compressed(dest,features=features)
            atomic_json(dest.with_suffix('.json'),{'version':aerial.VERSION,'encoder_sha256':aerial.WEIGHTS,'source_sha256':r['image_sha256'],'features_sha256':file_hash(dest),'shape':list(features.shape),'image_variant':variant,'marker_colours_used':False})
            image_receipt=json.loads((root/r['receipt_file']).read_text());meta=dutch.align(image_receipt,Path(sources)/r['site_id'],cache/'lidar-features'/(id+'.npz'));receipts.append({'variant':variant,'id':id,'valid_height_fraction':meta['valid_fraction']});print('Pinned features',variant,id,flush=True)
    atomic_json(out/'cache-report.json',receipts);return receipts


def validate_pair(native,coarse,protocol):
    expected={**net.SETTINGS,'lidar_dropout':.15}
    if protocol.get('version')!='dutch-resolution-transfer-protocol-v1' or protocol['settings']!=expected or protocol['selection_on_reserved_scores'] or protocol['automatic_promotion'] or protocol['encoder_updated'] or protocol['variants']!=['native_rgb','coarse_rgb']:raise ValueError('Fixed unpromoted resolution protocol required')
    if native['parent_dataset_id']!=protocol['parent_dataset_id'] or coarse.get('comparison_native_dataset_id')!=native['id'] or native['reserved_evaluation_site_ids']!=[protocol['reserved_site']] or coarse['reserved_evaluation_site_ids']!=native['reserved_evaluation_site_ids']:raise ValueError('Source-bound native/coarse reservation differs')
    if [r['id'] for r in native['records']]!=[r['id'] for r in coarse['records']]:raise ValueError('Identical geographic records required')
    for a,b in zip(native['records'],coarse['records']):
        if a['site_id']!=b['site_id'] or a['evaluation_only']!=b['evaluation_only'] or any(a[key+'_sha256']!=b[key+'_sha256'] for key in ('ground','canopy','dense_windows','inferred')):raise ValueError('Labels and whole-park split must be identical')
        if a['site_id'] not in ('efteling','toverland') and (a['image_sha256']!=b['image_sha256'] or a['receipt_sha256']!=b['receipt_sha256']):raise ValueError('Existing UK sources must remain unchanged')
    if set(protocol['excluded_consumed_sites'])&{r['site_id'] for r in native['records']}:raise ValueError('Consumed excluded park returned')
    return True


def geographic_guard(root,manifest):
    inverse=Transformer.from_crs(3857,4326,always_xy=True);geod=Geod(ellps='WGS84');frames=[]
    for r in manifest['records']:
        e=json.loads((root/r['receipt_file']).read_text())['extent_epsg3857'];lon,lat=inverse.transform((e[0]+e[2])/2,(e[1]+e[3])/2);corners=[inverse.transform(x,y) for x,y in ((e[0],e[1]),(e[2],e[1]),(e[2],e[3]),(e[0],e[3]))];radius=max(geod.inv(lon,lat,x,y)[2] for x,y in corners);frames.append((r,lon,lat,radius))
    rows=[]
    for i,(a,x,y,radius) in enumerate(frames):
        for b,xx,yy,rr in frames[i+1:]:
            if a['site_id']==b['site_id']:continue
            lower=geod.inv(x,y,xx,yy)[2]-radius-rr;rows.append({'a':a['id'],'b':b['id'],'conservative_footprint_separation_m':lower})
    if not rows or min(r['conservative_footprint_separation_m'] for r in rows)<24:raise ValueError('Cross-park geographic context guard failed')
    return {'required_m':24,'passed':True,'method':'Geodesic centres minus enclosing corner radii; conservative full-image separation','same_park_views_grouped':True,'pairs':rows}


def run(native,coarse,caches,protocol,output):
    import torch
    torch.set_num_threads(2);start=time.monotonic();out=Path(output);roots={'native_rgb':Path(native),'coarse_rgb':Path(coarse)};manifests={k:data.validate(v) for k,v in roots.items()};p=json.loads(Path(protocol).read_text());validate_pair(manifests['native_rgb'],manifests['coarse_rgb'],p)
    if out.exists():raise ValueError('Fresh fixed comparison required; reserved site becomes consumed after scoring')
    out.mkdir(parents=True);atomic_json(out/'design.json',{'protocol':p,'protocol_sha256':file_hash(protocol),'datasets':{k:v['id'] for k,v in manifests.items()},'production_eligible':False,'independent_human_review':False});atomic_json(out/'geographic-guard.json',geographic_guard(roots['native_rgb'],manifests['native_rgb']))
    # Compare pinned arrays before fitting, without holding both full datasets.
    for a,b in zip(manifests['native_rgb']['records'],manifests['coarse_rgb']['records']):
        for kind in ('features','lidar-features'):
            if kind=='features' and a['site_id'] in ('efteling','toverland'):continue
            left=Path(caches)/'native_rgb'/kind/(a['id']+'.npz');right=Path(caches)/'coarse_rgb'/kind/(b['id']+'.npz')
            if file_hash(left)!=file_hash(right):
                with np.load(left,allow_pickle=False) as aa,np.load(right,allow_pickle=False) as bb:
                    if not np.array_equal(aa['features'],bb['features']):raise ValueError('Controlled height or existing UK features changed')
    models={};metas={}
    for variant in p['variants']:
        fit_manifest={**manifests[variant],'records':training_records(manifests[variant])};fitrows=load_rows(roots[variant],Path(caches)/variant/'features',Path(caches)/variant/'lidar-features',fit_manifest);_,counts=net.class_weights(fitrows,'ground',4)
        if (counts==0).any() or {r['record']['site_id'] for r in fitrows}&{p['reserved_site']}:raise ValueError('All fitting classes and excluded reserved park required')
        print('Fitting',variant,[r['record']['id'] for r in fitrows],flush=True);model,training=net.fit(fitrows,balanced=True,settings=p['settings']);folder=out/'models'/variant;net.save(model,fitrows,manifests[variant],folder,training,aerial.WEIGHTS);loaded,meta=net.load(folder);models[variant]=(model,loaded);metas[variant]=meta
        del fitrows;gc.collect()
    atomic_json(out/'checkpoint-seal.json',{'created_utc':datetime.now(timezone.utc).isoformat(),'protocol_sha256':file_hash(protocol),'datasets':{k:v['id'] for k,v in manifests.items()},'models':{k:v['id'] for k,v in metas.items()},'reserved_target_hashes':{r['id']:{key:r[key+'_sha256'] for key in ('ground','canopy')} for r in manifests['native_rgb']['records'] if r['evaluation_only']},'reserved_scores_viewed':False})
    results=[];reloads=[]
    for variant in p['variants']:
        preview_manifest={**manifests[variant],'records':[r for r in manifests[variant]['records'] if r['evaluation_only'] or r['site_id']=='efteling']}
        preview_rows=load_rows(roots[variant],Path(caches)/variant/'features',Path(caches)/variant/'lidar-features',preview_manifest)
        for row in preview_rows:
            scope='reserved-toverland' if row['record']['evaluation_only'] else 'fitted-efteling-not-validation';print('Predicting',scope,variant,flush=True);g,c,u=net.predict(models[variant][0],row['features']);gg,cc,_=net.predict(models[variant][1],row['features']);assert np.array_equal(g,gg) and np.array_equal(c,cc);reloads.append({'variant':variant,'id':row['record']['id'],'exact_ground_canopy_reload':True});folder=out/'predictions'/scope/variant;folder.mkdir(parents=True);Image.fromarray(g).save(folder/'ground.png');Image.fromarray(c).save(folder/'canopy.png');Image.fromarray(np.rint(u*255).astype(np.uint8)).save(folder/'uncertainty.png')
            if row['record']['evaluation_only']:
                score=net.score(row,g,c);atomic_json(folder/'scores.json',score);results.append({'variant':variant,'id':row['record']['id'],'scores':score,'positive_canopy_evaluation_supported':bool((row['canopy']==1).any())})
        del preview_rows,row;gc.collect()
    report={'version':'dutch-resolution-transfer-v1','results':results,'training':{k:v['training'] for k,v in metas.items()},'training_sites':{k:v['training_site_ids'] for k,v in metas.items()},'reserved_site_now_consumed':p['reserved_site'],'production_eligible':False,'baseline_replaced':False,'encoder_updated':False,'nir_used_for_training':False,'selection_on_reserved_scores':False,'independent_human_review':False,'height_arrays_exactly_equal':True,'old_uk_features_exactly_equal':True,'scope':'One prospectively reserved park crop with assistant source-assisted labels. Controlled RGB-detail pilot, not surveyed accuracy or full-park geometry validation.'}
    atomic_json(out/'report.json',report);atomic_json(out/'checkpoint-roundtrip.json',reloads);atomic_json(out/'resources.json',{'wall_seconds':time.monotonic()-start,'peak_rss_mb':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,'cpu_threads':2,'gpu_used':False});return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='mode',required=True);b=sub.add_parser('coarsen')
    for arg in ('native','output'):b.add_argument('--'+arg,required=True)
    c=sub.add_parser('cache')
    for arg in ('native','coarse','parent-features','parent-lidar','sources','encoder','output'):c.add_argument('--'+arg,required=True)
    t=sub.add_parser('train')
    for arg in ('native','coarse','caches','protocol','output'):t.add_argument('--'+arg,required=True)
    args=vars(parser.parse_args());mode=args.pop('mode');result=coarsen_dataset(**args) if mode=='coarsen' else prepare_caches(**args) if mode=='cache' else run(**args);print(json.dumps(result))
