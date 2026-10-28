"""CPU four-surface spatial CNN benchmark against a per-pixel neural control."""
import argparse
import json
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image
from scipy import ndimage

from . import connected_surfaces as surfaces, study_component_learning as safe
from .generation_cycles import atomic_json,file_hash
from . import paving_spatial_transfer as metrics

VERSION='four-surface-cpu-model-v1'
SETTINGS={'seed':137,'steps':120,'batch':4,'patch':96,'learning_rate':.002,'threads':2}


def architecture(kind):
    import torch
    from torch import nn
    if kind=='pixel':return nn.Sequential(nn.Conv2d(3,16,1),nn.ReLU(),nn.Conv2d(16,16,1),nn.ReLU(),nn.Conv2d(16,4,1))
    if kind!='spatial':raise ValueError('Known surface architecture required')
    class Spatial(nn.Module):
        def __init__(self):
            super().__init__();self.fine=nn.Sequential(nn.Conv2d(3,12,3,padding=1),nn.ReLU(),nn.Conv2d(12,16,3,padding=1),nn.ReLU())
            self.coarse=nn.Sequential(nn.AvgPool2d(2),nn.Conv2d(16,24,3,padding=1),nn.ReLU(),nn.Conv2d(24,24,3,padding=2,dilation=2),nn.ReLU())
            self.out=nn.Sequential(nn.Conv2d(40,16,3,padding=1),nn.ReLU(),nn.Conv2d(16,4,1))
        def forward(self,x):
            fine=self.fine(x);coarse=self.coarse(fine);coarse=nn.functional.interpolate(coarse,size=fine.shape[-2:],mode='bilinear',align_corners=False)
            return self.out(torch.cat([fine,coarse],dim=1))
    return Spatial()


def fit(rows,kind,settings=SETTINGS):
    import torch
    torch.set_num_threads(settings['threads']);torch.manual_seed(settings['seed']);torch.use_deterministic_algorithms(True)
    model=architecture(kind);initial={k:v.detach().numpy().copy() for k,v in model.state_dict().items()};model.train()
    optimizer=torch.optim.Adam(model.parameters(),lr=settings['learning_rate']);rng=np.random.default_rng(settings['seed']);patch=settings['patch']
    indices=[[np.argwhere(r['target']==c) for c in range(4)] for r in rows]
    classes=[[c for c in range(4) if len(indices[i][c])] for i in range(len(rows))]
    if not rows or any(not c for c in classes):raise ValueError('Every fitting image needs observed surface labels')
    loss_fn=torch.nn.CrossEntropyLoss(ignore_index=255);history=[]
    for step in range(settings['steps']):
        images=[];targets=[]
        for batch in range(settings['batch']):
            i=int(rng.integers(len(rows)));c=int(rng.choice(classes[i]));r=rows[i];p=indices[i][c][int(rng.integers(len(indices[i][c])))];h,w=r['target'].shape
            top=int(np.clip(p[0]-rng.integers(patch//4,3*patch//4),0,h-patch));left=int(np.clip(p[1]-rng.integers(patch//4,3*patch//4),0,w-patch))
            rgb=r['rgb'][top:top+patch,left:left+patch];target=r['target'][top:top+patch,left:left+patch]
            k=int(rng.integers(4));rgb=np.rot90(rgb,k);target=np.rot90(target,k)
            if rng.random()<.5:rgb=np.flip(rgb,1);target=np.flip(target,1)
            images.append(rgb.transpose(2,0,1).copy());targets.append(target.copy())
        x=torch.from_numpy(np.stack(images)).float()/255;y=torch.from_numpy(np.stack(targets)).long()
        optimizer.zero_grad();loss=loss_fn(model(x),y);loss.backward();optimizer.step()
        if step in (0,settings['steps']-1) or (step+1)%20==0:history.append({'step':step+1,'loss':float(loss.detach())})
    change=float(sum(np.square(v.detach().numpy()-initial[k]).sum() for k,v in model.state_dict().items())**.5)
    return model.eval(),{'loss_history':history,'parameter_change_l2':change,'parameter_count':sum(p.numel() for p in model.parameters())}


def predict(model,rgb):
    import torch
    if rgb.dtype!=np.uint8 or rgb.ndim!=3 or rgb.shape[2]!=3 or rgb.shape[0]*rgb.shape[1]>1048576:raise ValueError('Bounded clean RGB required')
    h,w=rgb.shape[:2];core=160;halo=16;hp=(-h)%core;wp=(-w)%core
    padded=np.pad(rgb,((halo,hp+halo),(halo,wp+halo),(0,0)),mode='reflect');out=np.empty((h,w),np.uint8)
    model.eval()
    with torch.no_grad():
        for top in range(0,h,core):
            for left in range(0,w,core):
                tile=padded[top:top+core+2*halo,left:left+core+2*halo]
                x=torch.from_numpy(tile.transpose(2,0,1).copy()).float()[None]/255
                pred=model(x).argmax(1)[0].numpy()[halo:halo+core,halo:halo+core]
                hh,ww=min(core,h-top),min(core,w-left);out[top:top+hh,left:left+ww]=pred[:hh,:ww]
    return out


def save(model,kind,rows,manifest,folder,training):
    folder=Path(folder);folder.mkdir(parents=True)
    np.savez_compressed(folder/'weights.npz',**{k:v.detach().numpy() for k,v in model.state_dict().items()})
    metadata={'version':VERSION,'architecture':kind,'labels':surfaces.LABELS,'dataset_id':manifest['id'],
        'training_record_ids':[r['record']['id'] for r in rows],'training_source_sha256':[r['record']['image_sha256'] for r in rows],
        'weights_sha256':file_hash(folder/'weights.npz'),'settings':SETTINGS,'training':training,
        'pretrained_backbone':False,'production_eligible':False,'surface_labels_independently_verified':False}
    atomic_json(folder/'model.json',metadata)


def load(folder):
    import torch
    folder=Path(folder);m,_=safe._json(folder/'model.json',2000000)
    if m.get('version')!=VERSION or m.get('labels')!=surfaces.LABELS or m.get('production_eligible') is not False:raise ValueError('Known provisional surface checkpoint required')
    p=folder/'weights.npz'
    if file_hash(p)!=m['weights_sha256'] or p.stat().st_size>2000000:raise ValueError('Pinned bounded surface weights required')
    model=architecture(m['architecture']);expected=model.state_dict()
    with zipfile.ZipFile(p) as z:
        if sum(i.file_size for i in z.infolist())>2000000:raise ValueError('Bounded expanded surface weights required')
        if set(z.namelist())!={k+'.npy' for k in expected}:raise ValueError('Known surface tensor entries required')
        for k,v in expected.items():
            with z.open(k+'.npy') as stream:
                version=np.lib.format.read_magic(stream)
                shape,fortran,dtype=np.lib.format._read_array_header(stream,version)
                if shape!=tuple(v.shape) or fortran or dtype!=np.dtype('float32'):raise ValueError('Bounded surface tensor headers required')
    with np.load(p,allow_pickle=False) as arrays:
        if set(arrays.files)!=set(expected):raise ValueError('Known surface weight tensors required')
        weights={}
        for k,v in expected.items():
            a=arrays[k]
            if a.dtype!=np.float32 or a.shape!=tuple(v.shape) or not np.isfinite(a).all() or np.abs(a).max()>100:raise ValueError('Finite correctly shaped surface weights required')
            weights[k]=torch.from_numpy(a.copy())
    model.load_state_dict(weights);return model.eval(),m


def score(target,pred,probes,points):
    valid=target!=255;matrix=np.bincount(target[valid].astype(int)*4+pred[valid],minlength=16).reshape(4,4)
    intersection=np.diag(matrix);union=matrix.sum(0)+matrix.sum(1)-intersection;iou=np.divide(intersection,union,out=np.zeros(4),where=union>0)
    true=target==0;positive=pred==0;radius=ndimage.distance_transform_edt(true);narrow=true & (radius<=2)
    binary=np.where(target==255,255,np.where(target==0,1,0)).astype(np.uint8)
    boundary=positive & ~ndimage.binary_erosion(positive);coords=np.array([p['clean_xy'] for p in points if p['label']=='path_boundary'])
    from scipy.spatial import cKDTree
    by,bx=np.nonzero(boundary);recall=float((cKDTree(np.column_stack([bx,by])).query(coords)[0]<=2).mean()) if len(bx) and len(coords) else 0.
    components,n=ndimage.label(true);missed=0;total=0
    for c in range(1,n+1):
        region=components==c
        if region.sum()<80:continue
        total+=1;missed+=float(positive[region].mean())<.2
    return {'confusion':matrix.tolist(),'known_pixels':int(valid.sum()),'class_iou':{k:float(iou[v]) for k,v in surfaces.LABELS.items() if v!=255},'macro_iou':float(iou.mean()),
        'paving_precision':float(matrix[0,0]/max(1,matrix[:,0].sum())),'paving_recall':float(matrix[0,0]/max(1,matrix[0].sum())),
        'paving_on_known_building_pixels':int(((target==1)&positive).sum()),'paving_on_known_water_pixels':int(((target==3)&positive).sum()),
        'narrow_labelled_strip_recall':float(positive[narrow].mean()) if narrow.any() else None,
        'missed_labelled_path_components':missed,'labelled_path_components':total,
        'connections':metrics.connections(binary,positive,probes),
        'user_edge_hint_recall_within_2_clean_pixels':recall,
        'boundary_f1':metrics.boundary_f1(binary,positive)['f1'],
        'scope':'Known assistant-draft semantic regions only. Edge-hint recall is not full boundary precision; narrow strips are labelled interiors, not measured path widths.'}


def fitting_rows(rows,held):
    """Keep every record from a held-out park out of fitting when sites differ."""
    cross_site=len({r['record']['site_id'] for r in rows})>1
    return [r for r in rows if (r['record']['site_id']!=held['record']['site_id'] if cross_site else r is not held)]


def train(dataset,output):
    from pyproj import Transformer
    from scipy.spatial import cKDTree
    root=Path(dataset).resolve();output=Path(output)
    if output.exists():raise ValueError('Fresh spatial surface experiment required')
    m=surfaces.validate(root);rows=[]
    for record in m['records']:
        with Image.open(root/record['image_file']) as im:rgb=np.array(im.convert('RGB'))
        with Image.open(root/record['mask_file']) as im:target=np.array(im)
        probes,_=safe._json(root/record['probes_file'],2000000);points,_=safe._json(root/record['points_file'],2000000)
        rows.append({'record':record,'rgb':rgb,'target':target,'probes':probes,'points':points['points']})
    project=Transformer.from_crs(3857,27700,always_xy=True);world=[]
    for row in rows:
        receipt,_=safe._json(root/row['record']['metadata_file'],2000000);e=receipt['extent_epsg3857'];y,x=np.nonzero(row['target']!=255);h,w=row['target'].shape
        xx,yy=project.transform(e[0]+x/w*(e[2]-e[0]),e[3]-y/h*(e[3]-e[1]));world.append(np.column_stack([xx,yy]))
    minimum=min(float(cKDTree(world[i]).query(world[j])[0].min()) for i in range(len(world)) for j in range(i+1,len(world)))
    if minimum<24:raise ValueError('Whole-image surface examples require a 24 m geographic context guard')
    sites={r['record']['site_id'] for r in rows};cross_site=len(sites)>1
    output.mkdir(parents=True);atomic_json(output/'design.json',{'settings':SETTINGS,'architectures':['pixel','spatial'],'dataset_id':m['id'],
        'evaluation':'whole-site held out' if cross_site else 'whole-image held out, same park',
        'held_out_score_used_for_selection':False,'unknown_target':255,
        'spatial_halo_pixels':16,'adoption':'no automatic promotion; source-assisted labels require independent review'})
    folds=[]
    for held in rows:
        fitting=fitting_rows(rows,held);scores={}
        for kind in ('pixel','spatial'):
            print('Fitting',kind,'excluding',held['record']['id'],flush=True)
            model,training=fit(fitting,kind);folder=output/'folds'/held['record']['id']/kind;save(model,kind,fitting,m,folder,training)
            if held['record']['image_sha256'] in [r['record']['image_sha256'] for r in fitting]:raise ValueError('Held-out source entered fitting')
            pred=predict(model,held['rgb']);Image.fromarray(pred).save(folder/'prediction.png');scores[kind]=score(held['target'],pred,held['probes'],held['points'])
            atomic_json(folder/'scores.json',scores[kind])
        for name,value in [('always_paving',0),('training_majority',int(np.argmax(sum(np.bincount(r['target'][r['target']!=255],minlength=4) for r in fitting))))]:
            scores[name]=score(held['target'],np.full(held['target'].shape,value,np.uint8),held['probes'],held['points'])
        folds.append({'held_out_id':held['record']['id'],'held_out_site_id':held['record']['site_id'],
            'training_site_ids':sorted({r['record']['site_id'] for r in fitting}),
            'scores':scores,'source_in_fitting':False})
    for kind in ('pixel','spatial'):
        print('Fitting final',kind,flush=True);model,training=fit(rows,kind);save(model,kind,rows,m,output/'models'/kind,training)
        for r in rows:
            folder=output/'fitted-previews'/r['record']['id'];folder.mkdir(parents=True,exist_ok=True)
            Image.fromarray(predict(model,r['rgb'])).save(folder/(kind+'.png'))
    surfaces.validate(root)
    report={'version':'four-surface-spatial-benchmark-v1','dataset_id':m['id'],'folds':folds,
        'same_park_development_only':not cross_site,'evaluation_scope':'whole_site' if cross_site else 'whole_image_same_site',
        'independent_blind_test':False,'production_eligible':False,'old_paving_checkpoint_replaced':False,
        'all_data_previews_are_fitted_not_validation':True,'new_architecture_is_spatial_convolution':True}
    report['minimum_known_label_distance_m']=minimum
    atomic_json(output/'report.json',report);return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dataset',required=True);p.add_argument('--output',required=True);a=p.parse_args();print(json.dumps(train(a.dataset,a.output)))


if __name__=='__main__':main()
