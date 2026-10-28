"""Run fixed park-holdout layered CPU comparisons; source labels never enter features."""
import argparse
from pathlib import Path
import json,time,threading
import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.spatial import cKDTree
from pyproj import Transformer
from voxel_mapper import layered_surface_benchmark as data,layered_surface_learning as net
from voxel_mapper import aerial_surface_encoder as aerial
from voxel_mapper.generation_cycles import atomic_json,file_hash


def run(dataset,encoder_directory,output,feature_cache=None,resume=False,lidar_cache=None,profile='standard'):
    import psutil,torch
    root=Path(dataset);out=Path(output)
    if out.exists() and not resume:raise ValueError('Fresh layered experiment or explicit matching resume required')
    manifest=data.validate(root)
    if any(r.get('evaluation_only',False) for r in manifest['records']):raise ValueError('Generic all-record training cannot consume reserved evaluation parks')
    out.mkdir(parents=True,exist_ok=True);torch.set_num_threads(2)
    variants={'rgb_unbalanced':{'balanced':False,'features':'rgb'},'rgb_balanced':{'balanced':True,'features':'rgb'},'aerial_balanced':{'balanced':True,'features':'aerial'}}
    if profile=='narrow_lidar':
        if not lidar_cache:raise ValueError('Aligned LiDAR feature cache required')
        variants={'aerial_balanced':{'balanced':True,'features':'aerial'},'lidar_balanced':{'balanced':True,'features':'lidar','settings':{**net.SETTINGS,'lidar_dropout':.15}},
                  'lidar_narrow':{'balanced':True,'features':'lidar','settings':{**net.SETTINGS,'lidar_dropout':.15,'narrow_sampling_fraction':.5,'narrow_max_width_m':4.}}}
    elif profile!='standard':raise ValueError('Known benchmark profile required')
    design={'version':'layered-fixed-comparison-v1','dataset_id':manifest['id'],'settings':net.SETTINGS,'variants':variants,'encoder_sha256':aerial.WEIGHTS,
      'encoder_updated':False,'evaluation':'All records of held-out park excluded from fitting','independent_blind_test':False,'selection_on_held_out_scores':False,
      'source_annotations':'Assistant-source-reviewed drafts, not independent human truth','ground_and_canopy_are_separate':True,'production_eligible':False}
    if profile!='standard':design.update(profile=profile,within_site_overlap_policy='Overlapping views stay in one park group; never an independent test',lidar_feature_version='dated-lidar-surface-context-v1')
    if resume and json.loads((out/'design.json').read_text())!=design:raise ValueError('Resume design must match exactly')
    atomic_json(out/'design.json',design);start=time.monotonic();stop=threading.Event();peaks=[];reused=[]
    def monitor():
        while not stop.wait(.1):peaks.append(psutil.Process().memory_info().rss)
    thread=threading.Thread(target=monitor,daemon=True);thread.start()
    try:
        rows=[];encoder=None
        for record in manifest['records']:
            rgb=np.array(Image.open(root/record['image_file']).convert('RGB'));ground=np.array(Image.open(root/record['ground_file']));canopy=np.array(Image.open(root/record['canopy_file']));features=None
            if feature_cache:
                cache=Path(feature_cache);receipt=json.loads((cache/(record['id']+'.json')).read_text());p=cache/(record['id']+'.npz')
                if receipt['encoder_sha256']!=aerial.WEIGHTS or receipt['source_sha256']!=record['image_sha256'] or receipt['features_sha256']!=file_hash(p):raise ValueError('Pinned feature cache differs')
                with np.load(p,allow_pickle=False) as a:features=a['features']
                if list(features.shape)!=receipt['shape'] or features.shape!=(*ground.shape,16):raise ValueError('Native aerial features required')
            else:
                if encoder is None:encoder=aerial.Encoder(encoder_directory)
                features=encoder.features(rgb)
            if not np.isfinite(features).all() or features.min()<0 or features.max()>1.00001 or not np.allclose(features[:,:,:3],rgb.astype(np.float32)/255,atol=1e-7):raise ValueError('Finite source-only feature grid required')
            components,n=ndimage.label(ground==0);probes=[]
            for label in sorted(range(1,n+1),key=lambda i:np.count_nonzero(components==i),reverse=True)[:3]:
                y,x=np.nonzero(components==label)
                if len(x)<80:continue
                a=int(np.argmin(x+y));b=int(np.argmax(x+y));probes.append({'id':'component-'+str(label),'a_xy':[int(x[a]),int(y[a])],'b_xy':[int(x[b]),int(y[b])]})
            row={'record':record,'rgb':rgb.astype(np.float32)/255,'aerial':features,'ground':ground,'canopy':canopy,'probes':probes}
            if profile=='narrow_lidar':
                from voxel_mapper.lidar_surface_features import VERSION as lidar_version,CHANNELS
                from voxel_mapper.imagery_capture_quality import audit
                cache=Path(lidar_cache);p=cache/(record['id']+'.npz');receipt_file=cache/(record['id']+'.json');receipt=json.loads(receipt_file.read_text())
                if receipt.get('version')!=lidar_version or receipt['image_sha256']!=record['image_sha256'] or receipt['features_sha256']!=file_hash(p) or receipt['channels']!=CHANNELS:raise ValueError('Pinned aligned LiDAR context required')
                with np.load(p,allow_pickle=False) as a:heights=a['features']
                if heights.shape!=(*ground.shape,4) or not np.isfinite(heights).all() or heights.min()<0 or heights.max()>1.00001:raise ValueError('Finite native aligned LiDAR layers required')
                row['lidar']=np.concatenate([features,heights],axis=2);row['lidar_pin']=file_hash(receipt_file);image_receipt=json.loads((root/record['receipt_file']).read_text());row['ground_sampling_m']=float(np.mean(audit(image_receipt)['approx_export_ground_sampling_m_xy']))
            rows.append(row)
        # Require a second site and known label regions outside the existing context guard.
        sites=sorted({r['record']['site_id'] for r in rows})
        if len(sites)<2:raise ValueError('At least two parks required for park holdouts')
        tr=Transformer.from_crs(3857,27700,always_xy=True);world=[]
        for r in rows:
            receipt=json.loads((root/r['record']['receipt_file']).read_text());e=receipt['extent_epsg3857'];y,x=np.nonzero((r['ground']!=255)|(r['canopy']!=255));h,w=r['ground'].shape;xx,yy=tr.transform(e[0]+x/w*(e[2]-e[0]),e[3]-y/h*(e[3]-e[1]));world.append(np.column_stack([xx,yy]))
        pairs=[{'a':rows[i]['record']['id'],'b':rows[j]['record']['id'],'same_site':rows[i]['record']['site_id']==rows[j]['record']['site_id'],
                'distance_m':float(cKDTree(world[i]).query(world[j])[0].min())} for i in range(len(world)) for j in range(i+1,len(world))]
        distance=min(p['distance_m'] for p in pairs if profile=='standard' or not p['same_site'])
        if distance<24:raise ValueError('24 m geographic context guard required')
        atomic_json(out/'geographic-guard.json',{'minimum_known_label_distance_m':distance,'required_m':24,'passed':True,'pairwise_distances':pairs,
                    'guard_scope':'cross-site only, all within-site views grouped' if profile!='standard' else 'every image pair'})
        def view(rows,mode):return [{**r,'features':r[mode]} for r in rows]
        def fit_or_reload(fitrows,v,folder):
            encoder_pin=aerial.WEIGHTS if v['features']=='aerial' else None
            if v['features']=='lidar':encoder_pin=aerial.WEIGHTS
            settings=v.get('settings',net.SETTINGS)
            if resume and (folder/'model.json').exists():
                model,meta=net.load(folder)
                if meta['dataset_id']!=manifest['id'] or meta['training_source_sha256']!=[r['record']['image_sha256'] for r in fitrows] or meta['encoder_pin']!=encoder_pin or meta['training']['settings']!=settings or meta['training']['balanced']!=v['balanced'] or (v['features']=='lidar' and meta.get('lidar_feature_receipts_sha256')!=[r['lidar_pin'] for r in fitrows]):raise ValueError('Resume checkpoint lineage differs')
                reused.append(str(folder.relative_to(out)));return model
            model,training=net.fit(fitrows,balanced=v['balanced'],settings=settings);net.save(model,fitrows,manifest,folder,training,encoder_pin);return model
        def persist(folder,row,model):
            g,c,u=net.predict(model,row['features']);Image.fromarray(g).save(folder/'ground.png');Image.fromarray(c).save(folder/'canopy.png');Image.fromarray(np.rint(u*255).astype(np.uint8)).save(folder/'uncertainty.png');s=net.score(row,g,c);atomic_json(folder/'scores.json',s);return s
        folds=[]
        for site in sites:
            fitting=[r for r in rows if r['record']['site_id']!=site];held=[r for r in rows if r['record']['site_id']==site]
            assert not {r['record']['image_sha256'] for r in fitting}&{r['record']['image_sha256'] for r in held}
            for name,v in variants.items():
                print('Park holdout',site,name,flush=True);fitrows=view(fitting,v['features']);folder=out/'folds'/site/name;model=fit_or_reload(fitrows,v,folder)
                for row in view(held,v['features']):
                    d=folder/row['record']['id'];d.mkdir(exist_ok=True);s=persist(d,row,model);folds.append({'held_out_site':site,'held_out_id':row['record']['id'],'variant':name,'training_site_ids':sorted({r['record']['site_id'] for r in fitrows}),'scores':s})
        zero=[]
        for r in rows:
            folder=out/'zero-shot'/r['record']['id'];folder.mkdir(parents=True,exist_ok=True);g,c=aerial.zero_shot(r['aerial']);Image.fromarray(g).save(folder/'ground.png');Image.fromarray(c).save(folder/'canopy.png');s=net.score(r,g,c);atomic_json(folder/'scores.json',s);zero.append({'id':r['record']['id'],'scores':s})
        reloads=[];review_queue=[]
        for name,v in variants.items():
            print('Final fit',name,flush=True);fitrows=view(rows,v['features']);folder=out/'models'/name;model=fit_or_reload(fitrows,v,folder);loaded,metadata=net.load(folder)
            for row in fitrows:
                d=out/'fitted-previews'/name/row['record']['id'];d.mkdir(parents=True,exist_ok=True);persist(d,row,model);g,c,u=net.predict(loaded,row['features']);assert np.array_equal(g,np.array(Image.open(d/'ground.png'))) and np.array_equal(c,np.array(Image.open(d/'canopy.png')));reloads.append({'variant':name,'id':row['record']['id'],'exact_ground_and_canopy_match':True})
                if name==('lidar_narrow' if profile=='narrow_lidar' else 'aerial_balanced'):
                    h,w=u.shape;candidates=[]
                    for y in range(0,h-95,96):
                        for x in range(0,w-95,96):candidates.append({'id':row['record']['id'],'source_sha256':row['record']['image_sha256'],'native_crop_xyxy':[x,y,x+96,y+96],'mean_normalised_entropy':float(u[y:y+96,x:x+96].mean()),'reason':'Uncalibrated fitted-model uncertainty; review candidate only'})
                    review_queue.extend(sorted(candidates,key=lambda a:a['mean_normalised_entropy'],reverse=True)[:5])
        report={'version':'layered-surface-comparison-v1','dataset_id':manifest['id'],'profile':profile,'folds':folds,'zero_shot_aerial':zero,'production_eligible':False,'old_baseline_replaced':False,'independent_human_review':False,'fitted_previews_are_not_validation':True,'encoder_updated':False,'scope':'Two-park development comparison, overlapping same-park views grouped; not a fresh blind test'}
        atomic_json(out/'report.json',report);atomic_json(out/'checkpoint-roundtrip.json',{'checks':reloads,'pickle_runtime_used':False});atomic_json(out/'review-queue.json',review_queue);data.validate(root);return report
    finally:
        stop.set();thread.join();atomic_json(out/'resources.json',{'wall_seconds':time.monotonic()-start,'peak_process_rss_mb':max(peaks,default=0)/2**20,'cpu_threads':2,'gpu_used':False,'resumed':resume,'reused_checkpoints':reused,'measurement_scope':'This invocation only; interrupted earlier training is not included' if resume else 'Full invocation'})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dataset',required=True);p.add_argument('--encoder',required=True);p.add_argument('--output',required=True);p.add_argument('--feature-cache');p.add_argument('--lidar-cache');p.add_argument('--profile',choices=['standard','narrow_lidar'],default='standard');p.add_argument('--resume',action='store_true');a=p.parse_args();run(a.dataset,a.encoder,a.output,a.feature_cache,a.resume,a.lidar_cache,a.profile)
