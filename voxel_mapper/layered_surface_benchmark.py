"""Pinned draft surface and independent tree-canopy targets, with scored boundaries."""
import json
from pathlib import Path
import shutil

import numpy as np
from PIL import Image
from scipy import ndimage
from shapely.affinity import affine_transform

from . import connected_surfaces as surfaces, study_component_learning as safe
from .desktop_memory import digest
from .generation_cycles import atomic_json, file_hash

VERSION = 'layered-surface-benchmark-v1'
GROUND = surfaces.LABELS
CANOPY = {'visible_non_canopy': 0, 'tree_canopy': 1, 'unknown': 255}


def _polygon(item, size):
    return surfaces.geometry({k:v for k,v in item.items() if k!='subtype'}, size)


def targets(item, reference_size, clean_size, matrix, old_ground, old_inferred):
    """Explicit window partitions; canopy never fabricates hidden ground truth."""
    M=np.asarray(matrix,float)
    if M.shape!=(2,3) or not np.isfinite(M).all():raise ValueError('Finite image registration required')
    tf=[M[0,0],M[0,1],M[1,0],M[1,1],M[0,2],M[1,2]]
    ground=old_ground.copy();windows=np.zeros(ground.shape,bool)
    if ground.shape!=(clean_size[1],clean_size[0]) or ground.size>1048576:raise ValueError('Bounded native target required')
    def mask(region):return surfaces.raster(affine_transform(_polygon(region,reference_size),tf),clean_size)
    def bare(name,outer,label='paving'):return {'id':name,'outer':outer,'label':label}
    if len(item['dense_windows'])>32 or len(item['canopy'])>128:raise ValueError('Bounded literal windows and crowns required')
    for window in item['dense_windows']:
        region=mask(bare(window['id'],window['outer']));windows|=region
        if window['base'] not in GROUND:raise ValueError('Explicit window base required')
        ground[region]=GROUND[window['base']]
        for part in window['parts']:ground[region & mask(part)]=GROUND[part['label']]
        for ring in window['unknown']:ground[region & mask(bare('unknown',ring))]=255
        # Window crop edges are artificial, not semantic boundaries.
        ground[region & ~ndimage.binary_erosion(region,iterations=2)]=255
    crowns=np.zeros(ground.shape,bool)
    for crown in item['canopy']:crowns|=mask(bare(crown['id'],crown['outer']))
    canopy=np.full(ground.shape,255,np.uint8)
    canopy[ground!=255]=0;canopy[crowns]=1
    canopy[(old_inferred>0)&~crowns]=255
    # Original user-guided canopy inference remains a distinct provenance layer.
    ground[(old_inferred>0)|crowns]=255
    return ground,canopy,windows


def build(source_dataset, examples, recipe_file, output):
    source=Path(source_dataset).resolve();out=Path(output)
    if out.exists():raise ValueError('Fresh layered benchmark required')
    old=surfaces.validate(source);recipe,_=safe._json(Path(recipe_file),2000000)
    inherited,_=safe._json(source/'recipe.json',2000000)
    entries,_=safe._json(Path(examples),2000000);entries={e['id']:e for e in entries};base=Path(examples).resolve().parent
    if recipe.get('version')!='layered-surface-recipe-v1' or recipe.get('independent_human_review') is not False:raise ValueError('Explicit provisional layered recipe required')
    prepared=[]
    for record in old['records']:
        id=record['id'];entry=entries[id];reg,_=safe._json(safe._asset(base,entry['registration']),2000000)
        if recipe['examples'][id]['ground']!=inherited['examples'][id]:raise ValueError('Inherited ground regions are read-only; edit dense windows or rebuild source masks')
        if record['image_sha256']!=reg['clean_source_sha256']:raise ValueError('Registration source differs')
        with Image.open(source/record['mask_file']) as im:old_ground=np.array(im)
        with Image.open(source/id/'inferred-path.png') as im:inferred=np.array(im)
        ground,canopy,windows=targets(recipe['examples'][id],reg['reference_size'],reg['clean_size'],reg['reference_to_clean'],old_ground,inferred)
        prepared.append((record,ground,canopy,windows,inferred))
    out.mkdir(parents=True);records=[]
    for record,ground,canopy,windows,inferred in prepared:
        id=record['id'];folder=out/id;folder.mkdir()
        row={'id':id,'site_id':record['site_id'],'source_original_sha256':record['image_sha256']}
        for key,src in [('image',source/record['image_file']),('receipt',source/record['metadata_file'])]:
            dest=folder/('clean.bin' if key=='image' else 'receipt.json');shutil.copy2(src,dest);row[key+'_file']=str(dest.relative_to(out));row[key+'_sha256']=file_hash(dest)
        for key,values in [('ground',ground),('canopy',canopy),('dense_windows',windows.astype(np.uint8)*255),('inferred',inferred)]:
            dest=folder/(key+'.png');Image.fromarray(values).save(dest);row[key+'_file']=str(dest.relative_to(out));row[key+'_sha256']=file_hash(dest)
        row['ground_counts']={k:int((ground==v).sum()) for k,v in GROUND.items()};row['canopy_counts']={k:int((canopy==v).sum()) for k,v in CANOPY.items()}
        records.append(row)
    shutil.copy2(recipe_file,out/'recipe.json')
    m={'version':VERSION,'source_dataset_id':old['id'],'recipe_sha256':file_hash(recipe_file),'ground_labels':GROUND,'canopy_labels':CANOPY,'records':records,
       'independent_human_review':False,'production_eligible':False,'hidden_ground_used_as_observed_truth':False}
    m['id']=digest(m);atomic_json(out/'dataset.json',m);return m


def validate(root):
    root=Path(root).resolve();m,_=safe._json(root/'dataset.json',2000000)
    if m.get('version')!=VERSION or m.get('id')!=digest({k:v for k,v in m.items() if k!='id'}) or m.get('ground_labels')!=GROUND or m.get('canopy_labels')!=CANOPY:raise ValueError('Pinned layered manifest required')
    if m.get('independent_human_review') is not False or m.get('production_eligible') is not False or m.get('hidden_ground_used_as_observed_truth') is not False:raise ValueError('Draft layered policy required')
    if not 2<=len(m['records'])<=8 or len({r['id'] for r in m['records']})!=len(m['records']):raise ValueError('Distinct bounded records required')
    reserved=m.get('reserved_evaluation_site_ids',[])
    if not isinstance(reserved,list) or len(set(reserved))!=len(reserved) or not set(reserved)<={r['site_id'] for r in m['records']}:raise ValueError('Declared reserved evaluation parks required')
    if file_hash(root/'recipe.json')!=m['recipe_sha256']:raise ValueError('Layered recipe changed')
    for r in m['records']:
        if type(r.get('evaluation_only',False)) is not bool or bool(r.get('evaluation_only',False))!=(r['site_id'] in reserved):raise ValueError('Whole reserved parks must remain evaluation only')
        for key in ('image','receipt','ground','canopy','dense_windows','inferred'):
            p=safe._asset(root,r[key+'_file'])
            if file_hash(p)!=r[key+'_sha256']:raise ValueError('Layered asset changed')
        with Image.open(root/r['image_file']) as im:size=im.size
        if size[0]*size[1]>1048576:raise ValueError('Bounded layered image required')
        receipt,_=safe._json(root/r['receipt_file'],2000000)
        if receipt['image_sha256']!=r['image_sha256'] or size!=(receipt['width'],receipt['height']):raise ValueError('Layered source receipt differs')
        for key,legend in [('ground',GROUND),('canopy',CANOPY)]:
            with Image.open(root/r[key+'_file']) as im:
                a=np.array(im)
                if im.mode!='L' or im.size!=size or not set(np.unique(a))<=set(legend.values()):raise ValueError('Native layered labels required')
            if r[key+'_counts']!={k:int((a==v).sum()) for k,v in legend.items()}:raise ValueError('Layered counts changed')
    return m


def boundary_metrics(target,pred,classes,tolerance=2):
    """Score real labelled interfaces only, away from unknowns and window borders."""
    valid=ndimage.binary_erosion(target!=255,iterations=tolerance+1,border_value=0)
    edges=[]
    for c in range(classes):
        truth=(target==c)^ndimage.binary_erosion(target==c)
        prediction=(pred==c)^ndimage.binary_erosion(pred==c)
        truth&=valid;prediction&=valid
        nt,npred=int(truth.sum()),int(prediction.sum())
        if not nt:edges.append({'class':c,'true_boundary_pixels':0,'f1':None});continue
        precision=float((ndimage.distance_transform_edt(~truth)[prediction]<=tolerance).mean()) if npred else 0.
        recall=float((ndimage.distance_transform_edt(~prediction)[truth]<=tolerance).mean()) if npred else 0.
        edges.append({'class':c,'true_boundary_pixels':nt,'predicted_boundary_pixels':npred,'precision':precision,'recall':recall,'f1':2*precision*recall/(precision+recall) if precision+recall else 0.})
    return {'classes':edges,'tolerance_clean_pixels':tolerance,'evaluation_support_pixels':int(valid.sum()),
            'scope':'Interfaces surrounded by explicit known labels only; partial assistant-draft boundary evaluation, not full-scene boundary accuracy.'}


def class_metrics(target,pred,classes):
    if target.shape!=pred.shape or not set(np.unique(pred))<=set(range(classes))|{255}:raise ValueError('Matching bounded class predictions required')
    valid=target!=255;values=np.where(pred[valid]==255,classes,pred[valid]);matrix=np.bincount(target[valid].astype(int)*(classes+1)+values,minlength=classes*(classes+1)).reshape(classes,classes+1)
    result=[]
    for c in range(classes):
        tp=int(matrix[c,c]);support=int(matrix[c].sum());positive=int(matrix[:,c].sum());union=support+positive-tp
        result.append({'class':c,'support':support,'precision':tp/positive if positive else 0.,'recall':tp/support if support else None,'iou':tp/union if union else None})
    return {'classes':result,'confusion_with_abstain_column':matrix.tolist(),'known_pixels':int(valid.sum()),'abstentions_on_known_pixels':int(matrix[:,-1].sum()),
            'present_target_macro_iou':float(np.mean([c['iou'] for c in result if c['support']])) if valid.any() else None,
            'boundaries':boundary_metrics(target,pred,classes)}


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-dataset',required=True);p.add_argument('--examples',required=True);p.add_argument('--recipe',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    print(json.dumps(build(a.source_dataset,a.examples,a.recipe,a.output)))
