"""Source-pinned RGB semantic research learning, with entire parks held out."""
import argparse
from collections import Counter
from html import escape
import json
import re
from pathlib import Path
import shutil
import sqlite3
import tempfile

import numpy as np
from PIL import Image,ImageDraw
from scipy import ndimage

from . import aerial_semantic_network as net, study_component_learning as safe
from .desktop_memory import digest
from .generation_cycles import atomic_json,file_hash

DATASET_VERSION='aerial-semantic-dataset-v1'
VERSION='aerial-semantic-training-v1'
MODEL_VERSION='aerial-semantic-model-v1'
POLICY='assistant_visual_review_provisional_not_human_ground_truth'
COLOURS=[(230,199,70),(225,120,50),(130,115,210),(70,170,95),(90,110,130)]


def annotation_mask(regions,size,border=2):
    masks=[np.zeros((size[1],size[0]),bool) for _ in net.CLASSES]
    if not isinstance(regions,list) or len(regions)>256:raise ValueError('Bounded literal annotation polygons required')
    for item in regions:
        c=item['class'];points=item['points']
        if type(c) is not int or not 0<=c<5 or not isinstance(points,list) or not 3<=len(points)<=128:
            raise ValueError('Known semantic class and polygon required')
        if any(not isinstance(p,list) or len(p)!=2 or any(type(v) not in (int,float) or not np.isfinite(v) or not 0<=v<=size[i] for i,v in enumerate(p)) for p in points):
            raise ValueError('In-image finite annotation pixels required')
        image=Image.new('L',size,0);ImageDraw.Draw(image).polygon([tuple(p) for p in points],fill=255)
        mask=np.asarray(image)>0
        if border:mask=ndimage.binary_erosion(mask,iterations=border)
        masks[c]|=mask
    votes=np.stack(masks);unique=votes.sum(axis=0)==1;result=np.full(votes.shape[1:],255,np.uint8)
    result[unique]=votes[:,unique].argmax(axis=0)
    return result


def build_dataset(items,annotation_path,output):
    output=Path(output)
    if output.exists():raise ValueError('Fresh semantic dataset output required')
    annotations,raw=safe._json(Path(annotation_path),2000000)
    if annotations['class_names']!=net.CLASSES or annotations['status']!='provisional_visible_region_annotations_not_human_ground_truth':
        raise ValueError('Explicit provisional visual annotation policy required')
    output.mkdir(parents=True);(output/'images').mkdir();(output/'masks').mkdir();(output/'originals').mkdir();(output/'metadata').mkdir()
    shutil.copy2(annotation_path,output/'annotations.json');records=[]
    for item in items:
        source=Path(item['source_directory']);receipt=json.loads((source/'report.json').read_text())['imagery'];original=source/'source-image.bin'
        if file_hash(original)!=receipt['image_sha256']:raise ValueError('Original aerial source changed')
        identifier=item['id'];side=item.get('input_size',512)
        if not isinstance(identifier,str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,79}',identifier) or type(side) is not int or not 64<=side<=512:raise ValueError('Bounded image identity/size required')
        image_name='images/'+identifier+'.png';mask_name='masks/'+identifier+'.png';original_name='originals/'+identifier+'.bin';meta_name='metadata/'+identifier+'.json'
        with Image.open(original) as image:
            if image.width*image.height>4000000:raise ValueError('Original imagery pixel budget exceeded')
            rgb=image.convert('RGB').resize((side,side),Image.Resampling.BOX)
            opacity=image.convert('RGBA').resize((side,side),Image.Resampling.BOX)
        rgb.save(output/image_name);mask=annotation_mask(annotations['annotations'][identifier],(side,side),annotations['boundary_ignore_pixels'])
        mask[np.asarray(opacity)[:,:,3]!=255]=255;Image.fromarray(mask).save(output/mask_name)
        shutil.copy2(original,output/original_name);atomic_json(output/meta_name,receipt)
        ext=receipt['extent_epsg3857'];centre=(item['bounds_wgs84'][1]+item['bounds_wgs84'][3])/2
        metres=(ext[2]-ext[0])/side*float(np.cos(np.deg2rad(centre)))
        records.append({'id':identifier,'site_id':item['site_id'],'image_file':image_name,'image_sha256':file_hash(output/image_name),
            'mask_file':mask_name,'mask_sha256':file_hash(output/mask_name),'source_file':original_name,'source_sha256':file_hash(output/original_name),
            'metadata_file':meta_name,'metadata_sha256':file_hash(output/meta_name),'input_size':[side,side],
            'metres_per_pixel':metres,'extent_epsg3857':ext,'supervision_status':POLICY,
            'annotated_pixel_counts':{net.CLASSES[i]:int((mask==i).sum()) for i in range(5)}})
    manifest={'version':DATASET_VERSION,'classes':net.CLASSES,'annotation_file':'annotations.json','annotation_sha256':file_hash(output/'annotations.json'),
        'label_policy':POLICY,'records':records,'geometry_verified':False,'human_labels_verified':False}
    manifest['id']=digest(manifest);atomic_json(output/'dataset.json',manifest)
    return manifest


def read_dataset(directory,*,cancelled=lambda:False):
    root=Path(directory);manifest,raw=safe._json(root/'dataset.json',2000000)
    if manifest.get('version')!=DATASET_VERSION or manifest.get('classes')!=net.CLASSES or manifest.get('label_policy')!=POLICY or manifest.get('id')!=digest({k:v for k,v in manifest.items() if k!='id'}):
        raise ValueError('Pinned provisional aerial semantic dataset required')
    rows=manifest.get('records',[])
    if not isinstance(rows,list) or not 3<=len(rows)<=16 or len({r['id'] for r in rows})!=len(rows):raise ValueError('Three to sixteen distinct aerial records required')
    if len({r['site_id'] for r in rows})<3:raise ValueError('At least three sites required for park-held-out evaluation')
    path=safe._asset(root,manifest['annotation_file'])
    if file_hash(path)!=manifest['annotation_sha256']:raise ValueError('Visual annotation source changed')
    annotations,_=safe._json(path,2000000)
    if annotations.get('class_names')!=net.CLASSES or annotations.get('status')!='provisional_visible_region_annotations_not_human_ground_truth':raise ValueError('Provisional annotation class/policy changed')
    result=[];pixels=0;source_sites={}
    for row in rows:
        net.check(cancelled)
        if row.get('supervision_status')!=POLICY:raise ValueError('Annotation supervision policy changed')
        for key in ['image','mask','source','metadata']:
            asset=safe._asset(root,row[key+'_file'])
            if not asset.is_file() or asset.stat().st_size>16000000 or file_hash(asset)!=row[key+'_sha256']:raise ValueError('Pinned semantic '+key+' asset changed')
        metadata,_=safe._json(root/row['metadata_file'],2000000)
        if metadata.get('image_sha256')!=row['source_sha256'] or metadata.get('extent_epsg3857')!=row['extent_epsg3857']:raise ValueError('Original metadata lineage changed')
        if source_sites.get(row['source_sha256'],row['site_id'])!=row['site_id']:raise ValueError('One original source cannot occur in different held-out sites')
        source_sites[row['source_sha256']]=row['site_id']
        with Image.open(root/row['image_file']) as image:
            if image.format!='PNG' or image.mode!='RGB' or image.size!=tuple(row['input_size']) or max(image.size)>512:raise ValueError('Bounded RGB training PNG required')
            rgb=np.asarray(image).copy();pixels+=image.width*image.height
        if pixels>2097152:raise ValueError('Dataset feature-memory pixel budget exceeded')
        with Image.open(root/row['source_file']) as original:
            if original.width*original.height>4000000:raise ValueError('Original image pixel budget exceeded')
            expected=np.asarray(original.convert('RGB').resize(tuple(row['input_size']),Image.Resampling.BOX))
            opacity=np.asarray(original.convert('RGBA').resize(tuple(row['input_size']),Image.Resampling.BOX))[:,:,3]
        if not np.array_equal(rgb,expected):raise ValueError('Training RGB is not the declared original-source resize')
        with Image.open(root/row['mask_file']) as image:
            if image.mode!='L' or image.size!=tuple(row['input_size']):raise ValueError('Matching byte semantic mask required')
            labels=np.asarray(image).copy()
        expected=annotation_mask(annotations['annotations'][row['id']],tuple(row['input_size']),annotations['boundary_ignore_pixels']);expected[opacity!=255]=255
        if not np.array_equal(labels,expected):raise ValueError('Target mask differs from pinned visual annotation polygons')
        result.append({'record':row,'rgb':rgb,'labels':labels,'features':net.features(rgb,row['metres_per_pixel'],cancelled=cancelled)})
    # Different held-out parks may not share the same geographic image coverage.
    from shapely.geometry import box
    for a in rows:
        for b in rows:
            if a['site_id']!=b['site_id'] and box(*a['extent_epsg3857']).intersection(box(*b['extent_epsg3857'])).area>0:
                raise ValueError('Held-out site imagery footprints overlap')
    return manifest,result,safe._sha(raw)


def _model(fit,manifest,pin,rows):
    model={'version':MODEL_VERSION,'network_version':net.VERSION,'feature_version':net.FEATURE_VERSION,'classes':net.CLASSES,
        'dataset_id':manifest['id'],'dataset_sha256':pin,'training_record_ids':[r['record']['id'] for r in rows],
        'training_site_ids':sorted({r['record']['site_id'] for r in rows}),'training_source_sha256':sorted({r['record']['source_sha256'] for r in rows}),
        'network':fit,'label_policy':POLICY,'production_eligible':False,'physical_geometry_verified':False,'world_blocks_generated':0}
    model['artifact_sha256']=digest(model);return model


def _samples(rows,maximum=1500):
    xs=[];ys=[]
    for row in rows:
        rng=np.random.default_rng(137);labels=row['labels'].reshape(-1);features=row['features'].reshape(-1,net.FEATURE_COUNT)
        for c in range(5):
            indices=np.flatnonzero(labels==c)
            if len(indices)>maximum:indices=rng.choice(indices,maximum,replace=False)
            if len(indices):xs.append(features[indices]);ys.append(np.full(len(indices),c,np.int64))
    return np.concatenate(xs),np.concatenate(ys)


def _metrics(matrix):
    total=int(matrix.sum());rows=[]
    for i,name in enumerate(net.CLASSES):
        support=int(matrix[i].sum());union=int(matrix[i].sum()+matrix[:,i].sum()-matrix[i,i])
        rows.append({'class':name,'support':support,'iou':float(matrix[i,i]/union) if union else None,
            'recall':float(matrix[i,i]/support) if support else None})
    known=[r['iou'] for r in rows if r['iou'] is not None]
    return {'annotated_pixels':total,'pixel_accuracy':float(np.trace(matrix)/total) if total else 0,
        'mean_iou':float(np.mean(known)) if known else 0,'per_class':rows,'confusion':matrix.tolist(),
        'scope':'Agreement on provisional visually annotated pixels only; unlabeled pixels/boundary completeness are not scored.'}


def train(directory,output,settings=None,*,cancelled=lambda:False,progress=lambda v:None):
    output=Path(output)
    if output.exists():raise ValueError('Fresh semantic training output required')
    manifest,rows,pin=read_dataset(directory,cancelled=cancelled);output.mkdir(parents=True)
    sites=sorted({r['record']['site_id'] for r in rows});folds=[];total=np.zeros((5,5),np.int64);baseline_total=total.copy()
    for number,site in enumerate(sites):
        net.check(cancelled);fitting=[r for r in rows if r['record']['site_id']!=site];held=[r for r in rows if r['record']['site_id']==site]
        progress({'progress':.05+.7*number/len(sites),'message':'Training aerial semantics; held-out park '+site})
        x,y=_samples(fitting);fit=net.fit(x,y,settings,cancelled=cancelled);model=_model(fit,manifest,pin,fitting)
        fold_directory=output/'folds'/site;fold_directory.mkdir(parents=True,exist_ok=True);atomic_json(fold_directory/'model.json',model)
        matrix=np.zeros((5,5),np.int64);baseline_matrix=matrix.copy()
        centroids=np.array([x[y==c,:3].mean(axis=0) for c in range(5)])
        for item in held:
            labels=item['labels'].reshape(-1);valid=labels!=255;features=item['features'].reshape(-1,net.FEATURE_COUNT)[valid]
            predicted=net.predict(features,model,cancelled=cancelled).argmax(axis=1)
            base=np.linalg.norm(features[:,:3,None]-centroids.T[None,:,:],axis=1).argmin(axis=1)
            np.add.at(matrix,(labels[valid],predicted),1);np.add.at(baseline_matrix,(labels[valid],base),1)
        total+=matrix;baseline_total+=baseline_matrix
        folds.append({'held_out_site':site,'training_sites':model['training_site_ids'],'training_record_ids':model['training_record_ids'],
            'held_out_record_ids':[r['record']['id'] for r in held],'neural':_metrics(matrix),'rgb_centroid_baseline':_metrics(baseline_matrix)})
    progress({'progress':.85,'message':'Fitting final aerial semantic checkpoint on available provisional annotations'})
    x,y=_samples(rows);fit=net.fit(x,y,settings,cancelled=cancelled);model=_model(fit,manifest,pin,rows)
    atomic_json(output/'model.json',model)
    report={'version':VERSION,'dataset_id':manifest['id'],'dataset_sha256':pin,'records':len(rows),'sites':sites,'classes':net.CLASSES,
        'label_policy':POLICY,'labelled_pixel_counts':dict(sum((Counter({net.CLASSES[c]:int((r['labels']==c).sum()) for c in range(5)}) for r in rows),Counter())),
        'training_samples':len(y),'folds':folds,'park_held_out_neural':_metrics(total),'park_held_out_rgb_baseline':_metrics(baseline_total),
        'network_settings':fit['settings'],'final_loss_history':fit['loss_history'],'weight_change_l2':fit['weight_change_l2'],
        'model_sha256':file_hash(output/'model.json'),'model_weights_updated':True,'production_eligible':False,'world_blocks_generated':0,
        'limitations':['Annotations are assistant visual traces, not independently verified human labels or surveyed boundaries.',
            'All source images from a park stay in the same held-out fold; final checkpoint fits all available records and has no untouched final test.',
            'Paths/plazas share one paved-pedestrian class; visible roof regions are not ground footprints or building heights.',
            'Landscaped islands combine planting/grass islands; canopy, shadows, unknown pixels and unseen seasons remain uncertain.',
            'No held-out scores were used to choose settings; model outputs are proposals, not accepted geometry or training labels.']}
    atomic_json(output/'report.json',report);return report


def ensure_checkpoint(directory,memory,settings=None,*,cancelled=lambda:False,progress=lambda v:None):
    """Train a changed labelled dataset once; check and reuse its saved weights."""
    manifest,rows,pin=read_dataset(directory,cancelled=cancelled)
    del rows
    normalized={**net.DEFAULTS,**(settings or {})}
    key=digest({'dataset_sha256':pin,'network':net.VERSION,'features':net.FEATURE_VERSION,'settings':normalized})
    memory=Path(memory);memory.mkdir(parents=True,exist_ok=True);target=memory/key
    db=sqlite3.connect(memory/'checkpoints.sqlite3',timeout=30)
    db.execute('CREATE TABLE IF NOT EXISTS checkpoints(key TEXT PRIMARY KEY,model_sha256 TEXT,report_sha256 TEXT)')
    try:
        db.execute('BEGIN IMMEDIATE');saved=db.execute('SELECT model_sha256,report_sha256 FROM checkpoints WHERE key=?',(key,)).fetchone()
        updated=False
        if not target.exists():
            with tempfile.TemporaryDirectory(dir=memory,prefix='semantic-fit-') as temp:
                staged=Path(temp)/'complete';train(directory,staged,normalized,cancelled=cancelled,progress=progress);staged.rename(target)
            updated=True
        model_file=target/'model.json';report_file=target/'report.json'
        if saved and (file_hash(model_file)!=saved[0] or file_hash(report_file)!=saved[1]):raise ValueError('Persisted semantic checkpoint changed')
        model=load_model(model_file);report,_=safe._json(report_file,2000000)
        if model['dataset_sha256']!=pin or model['dataset_id']!=manifest['id'] or model['network']['settings']!=normalized or report['model_sha256']!=file_hash(model_file):
            raise ValueError('Semantic checkpoint lineage differs from current dataset/settings')
        db.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)',(key,file_hash(model_file),file_hash(report_file)));db.commit()
        return {'status':'trained_new_semantic_checkpoint' if updated else 'reused_unchanged_semantic_checkpoint',
            'model_file':str(model_file.resolve()),'model_sha256':file_hash(model_file),'dataset_sha256':pin,'dataset_id':manifest['id'],
            'model_weights_updated':updated,'held_out_mean_iou':report['park_held_out_neural']['mean_iou'],
            'rgb_baseline_mean_iou':report['park_held_out_rgb_baseline']['mean_iou'],
            'per_class':report['park_held_out_neural']['per_class'],'label_policy':POLICY,'production_eligible':False}
    finally:db.close()


def load_model(path,pin=None):
    if pin and file_hash(path)!=pin:raise ValueError('Semantic model file changed')
    model,_=safe._json(path,2000000);net.validate_model(model);return model


def infer(image_path,receipt,model_path,output,*,model_sha256=None,cancelled=lambda:False,threshold=.6,margin=.10):
    output=Path(output)
    if type(threshold) not in (int,float) or not .2<=threshold<=.99 or type(margin) not in (int,float) or not 0<=margin<=.9:raise ValueError('Bounded semantic abstention thresholds required')
    if output.exists():raise ValueError('Fresh semantic prediction output required')
    if file_hash(image_path)!=receipt['image_sha256']:raise ValueError('Original imagery changed before semantic prediction')
    model=load_model(model_path,model_sha256)
    with Image.open(image_path) as image:
        if image.width*image.height>4000000:raise ValueError('Bounded semantic inference imagery required')
        size=(max(64,round(image.width*min(1,512/max(image.size)))),max(64,round(image.height*min(1,512/max(image.size)))))
        rgba=np.asarray(image.convert('RGBA').resize(size,Image.Resampling.BOX));rgb=rgba[:,:,:3]
    ext=receipt['extent_epsg3857'];inverse=__import__('pyproj').Transformer.from_crs(3857,4326,always_xy=True);_,lat=inverse.transform((ext[0]+ext[2])/2,(ext[1]+ext[3])/2)
    metres=(ext[2]-ext[0])/size[0]*float(np.cos(np.deg2rad(lat)))
    p=net.predict(net.features(rgb,metres,cancelled=cancelled),model,cancelled=cancelled)
    ranked=np.sort(p,axis=2);labels=p.argmax(axis=2).astype(np.uint8)
    labels[(ranked[:,:,-1]<threshold)|((ranked[:,:,-1]-ranked[:,:,-2])<margin)|(rgba[:,:,3]!=255)]=255
    output.mkdir(parents=True);Image.fromarray(labels).save(output/'semantic-mask.png');Image.fromarray(rgb).save(output/'rgb.png')
    colours=np.full_like(rgb,40)
    for c,colour in enumerate(COLOURS):colours[labels==c]=colour
    Image.fromarray(colours).save(output/'class-map.png');Image.fromarray((rgb*.55+colours*.45).astype(np.uint8)).save(output/'overlay.png')
    from rasterio.features import shapes
    from rasterio.transform import from_bounds
    from shapely.geometry import shape,mapping
    from shapely.ops import transform
    affine=from_bounds(*ext,*size);features=[];factor=float(np.cos(np.deg2rad(lat)))**2
    for g,c in shapes(labels,mask=(labels!=255)&(labels!=4),transform=affine):
        net.check(cancelled);geom=shape(g)
        if geom.area*factor<4:continue
        if not geom.is_valid:continue
        geom=geom.simplify(abs(affine.a)*.5,preserve_topology=True)
        features.append({'type':'Feature','geometry':mapping(transform(inverse.transform,geom)),
            'properties':{'class':net.CLASSES[int(c)],'source':'trained_rgb_context_model','image_sha256':receipt['image_sha256'],
                'model_sha256':file_hash(model_path),'geometry_verified':False,'training_eligible':False}})
        if len(features)>=512:break
    if file_hash(image_path)!=receipt['image_sha256']:raise ValueError('Original imagery changed during semantic prediction')
    atomic_json(output/'semantic-candidates.geojson',{'type':'FeatureCollection','features':features})
    report={'version':'aerial-semantic-prediction-v1','image_sha256':receipt['image_sha256'],'model_sha256':file_hash(model_path),
        'source_in_training':receipt['image_sha256'] in model['training_source_sha256'],'training_site_ids':model['training_site_ids'],
        'class_pixel_counts':{name:int((labels==c).sum()) for c,name in enumerate(net.CLASSES)},'unknown_pixels':int((labels==255).sum()),
        'candidate_counts':dict(Counter(f['properties']['class'] for f in features)),'threshold':threshold,'margin':margin,
        'confidence_is_calibrated':False,'geometry_verified':False,'production_eligible':False,'world_blocks_generated':0}
    atomic_json(output/'report.json',report)
    legend=' · '.join('<span style="color:rgb'+str(colour)+'">'+escape(name.replace('_',' '))+'</span>' for name,colour in zip(net.CLASSES,COLOURS))
    (output/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Aerial semantic model</title><style>body{font:16px system-ui;max-width:1100px;margin:30px auto}img{max-width:49%}</style><h1>Trained aerial semantic proposals</h1><p>'+('Training-source demonstration' if receipt['image_sha256'] in model['training_source_sha256'] else 'Held-out/unseen-source demonstration')+'</p><p>'+legend+'</p><img src="rgb.png"><img src="overlay.png"><p>Dark areas are uncertain/other; model scores are not calibrated accuracy. All boundaries remain draft.</p><p>'+escape(receipt.get('attribution','Esri World Imagery and its providers'))+'</p>')
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    train_p=sub.add_parser('train');train_p.add_argument('--dataset',required=True);train_p.add_argument('--output',required=True)
    pred=sub.add_parser('predict')
    for key in ['image','receipt','model','output']:pred.add_argument('--'+key,required=True)
    args=p.parse_args(argv)
    if args.action=='train':result=train(args.dataset,args.output)
    else:result=infer(args.image,json.loads(Path(args.receipt).read_text()),args.model,args.output)
    print(json.dumps(result))


if __name__=='__main__':main()
