"""CPU layered-surface training with class balance, Dice and labelled interfaces."""
from pathlib import Path
import json

import numpy as np
from PIL import Image

from . import layered_surface_benchmark as data, surface_segmentation as old
from .generation_cycles import atomic_json, file_hash
from .desktop_memory import digest

VERSION='layered-surface-cpu-model-v1'
SETTINGS={'seed':137,'steps':400,'batch':4,'patch':96,'learning_rate':.002,'threads':2,
          'dice_weight':.5,'boundary_weight':2.,'canopy_weight':.5}


def architecture(channels=3):
    from torch import nn
    if channels not in (3,16,20):raise ValueError('RGB, pinned aerial or aligned LiDAR feature input required')
    model=old.architecture('spatial');model.fine[0]=nn.Conv2d(channels,12,3,padding=1);model.out[-1]=nn.Conv2d(16,6,1)
    return model


def class_weights(rows,key,classes):
    counts=sum(np.bincount(r[key][r[key]!=255],minlength=classes) for r in rows)
    w=np.zeros(classes,np.float32);present=counts>0
    w[present]=1/np.sqrt(counts[present]);w[present]/=w[present].mean();w=np.clip(w,0,4)
    return w,counts


def narrow_path_anchors(target,ground_sampling_m,max_width_m=4.):
    """Local paving strips too narrow for a metric disk; sampling only, no new truth."""
    from scipy import ndimage
    if not .05<=ground_sampling_m<=5 or not 1<=max_width_m<=8:raise ValueError('Bounded metric path sampling required')
    radius=min(24,max(1,int(np.ceil(max_width_m/(2*ground_sampling_m)))))
    yy,xx=np.mgrid[-radius:radius+1,-radius:radius+1];disk=xx*xx+yy*yy<=radius*radius;paving=target==0
    wide=ndimage.binary_opening(paving,structure=disk);thin=ndimage.binary_erosion(paving&~wide,iterations=1)
    return np.argwhere(thin)


def masked_loss(logits,target,weights,*,balanced=True,boundary_weight=2.,dice_weight=.5):
    import torch
    from torch.nn import functional as F
    known=target!=255
    if not known.any():return logits.sum()*0
    ce=F.cross_entropy(logits,target,ignore_index=255,reduction='none')
    pixel_weight=known.float()
    if balanced:
        pixel_weight*=weights[target.clamp(max=logits.shape[1]-1)]
        edge=torch.zeros_like(known)
        diff=known[:,1:]&known[:,:-1]&(target[:,1:]!=target[:,:-1]);edge[:,1:]|=diff;edge[:,:-1]|=diff
        diff=known[:,:,1:]&known[:,:,:-1]&(target[:,:,1:]!=target[:,:,:-1]);edge[:,:,1:]|=diff;edge[:,:,:-1]|=diff
        pixel_weight*=1+boundary_weight*edge.float()
    result=(ce*pixel_weight).sum()/pixel_weight.sum().clamp(min=1)
    if balanced and dice_weight:
        p=logits.softmax(1)*known[:,None];one=F.one_hot(target.clamp(max=logits.shape[1]-1),logits.shape[1]).permute(0,3,1,2)*known[:,None]
        support=one.sum((0,2,3));present=support>0
        dice=(2*(p*one).sum((0,2,3))+1)/(p.sum((0,2,3))+support+1)
        result+=dice_weight*(1-dice[present]).mean()
    return result


def fit(rows,balanced=True,settings=None):
    import torch
    s=dict(SETTINGS if settings is None else settings)
    if not rows or not 1<=s['steps']<=2000 or not 1<=s['batch']<=8 or s['patch'] not in (64,96,128) or not 0<=s.get('narrow_sampling_fraction',0)<=1 or not 0<=s.get('lidar_dropout',0)<=.5:raise ValueError('Bounded layered fitting required')
    torch.set_num_threads(s['threads']);torch.manual_seed(s['seed']);torch.use_deterministic_algorithms(True)
    channels=rows[0]['features'].shape[2];model=architecture(channels);initial={k:v.detach().numpy().copy() for k,v in model.state_dict().items()};model.train()
    indices=[];narrow=[]
    for r in rows:
        if r['features'].shape[:2]!=r['ground'].shape or r['ground'].shape!=r['canopy'].shape or r['features'].shape[2]!=channels or r['features'].size>1048576*20 or not np.isfinite(r['features']).all():raise ValueError('Matching bounded layered features and masks required')
        by_class=[np.argwhere(r[key]==c) for key,n in [('ground',4),('canopy',2)] for c in range(n)]
        if not any(len(a) for a in by_class):raise ValueError('Observed training labels required')
        indices.append(by_class)
        narrow.append(narrow_path_anchors(r['ground'],r.get('ground_sampling_m',1.),s.get('narrow_max_width_m',4.)) if s.get('narrow_sampling_fraction',0) else np.empty((0,2),int))
    wg,cg=class_weights(rows,'ground',4);wc,cc=class_weights(rows,'canopy',2)
    wg,wc=torch.from_numpy(wg),torch.from_numpy(wc);rng=np.random.default_rng(s['seed']);focus_rng=np.random.default_rng(s['seed']+1);drop_rng=np.random.default_rng(s['seed']+2);optimizer=torch.optim.Adam(model.parameters(),lr=s['learning_rate']);history=[]
    for step in range(s['steps']):
        features=[];grounds=[];canopies=[]
        for _ in range(s['batch']):
            i=int(rng.integers(len(rows)));available=[c for c,a in enumerate(indices[i]) if len(a)]
            if len(narrow[i]) and focus_rng.random()<s.get('narrow_sampling_fraction',0):anchor=narrow[i][int(rng.integers(len(narrow[i])))]
            else:
                c=int(rng.choice(available));anchor=indices[i][c][int(rng.integers(len(indices[i][c])))]
            r=rows[i];h,w=r['ground'].shape;patch=s['patch']
            if min(h,w)<patch:raise ValueError('Training image smaller than patch')
            top=int(np.clip(anchor[0]-rng.integers(patch//4,3*patch//4),0,h-patch));left=int(np.clip(anchor[1]-rng.integers(patch//4,3*patch//4),0,w-patch));sl=np.s_[top:top+patch,left:left+patch]
            values=[r['features'][sl],r['ground'][sl],r['canopy'][sl]];k=int(rng.integers(4));flip=rng.random()<.5
            values=[np.rot90(a,k) for a in values]
            if flip:values=[np.flip(a,1) for a in values]
            if channels==20 and drop_rng.random()<s.get('lidar_dropout',0):
                values[0]=values[0].copy();values[0][:,:,16:]=0
            features.append(values[0].transpose(2,0,1).copy());grounds.append(values[1].copy());canopies.append(values[2].copy())
        x=torch.from_numpy(np.stack(features)).float();g=torch.from_numpy(np.stack(grounds)).long();c=torch.from_numpy(np.stack(canopies)).long();optimizer.zero_grad();logits=model(x)
        lg=masked_loss(logits[:,:4],g,wg,balanced=balanced,boundary_weight=s['boundary_weight'],dice_weight=s['dice_weight'])
        lc=masked_loss(logits[:,4:],c,wc,balanced=balanced,boundary_weight=s['boundary_weight'],dice_weight=s['dice_weight']);loss=lg+s['canopy_weight']*lc
        if not torch.isfinite(loss):raise ValueError('Nonfinite layered loss')
        loss.backward();optimizer.step()
        if step in (0,s['steps']-1) or (step+1)%50==0:history.append({'step':step+1,'loss':float(loss.detach()),'ground_loss':float(lg.detach()),'canopy_loss':float(lc.detach())})
    change=float(sum(np.square(v.detach().numpy()-initial[k]).sum() for k,v in model.state_dict().items())**.5)
    return model.eval(),{'settings':s,'balanced':balanced,'ground_counts':cg.tolist(),'canopy_counts':cc.tolist(),'ground_weights':wg.tolist(),'canopy_weights':wc.tolist(),'narrow_anchor_counts':[len(a) for a in narrow],'history':history,'parameter_change_l2':change,'parameter_count':sum(p.numel() for p in model.parameters())}


def predict(model,features):
    import torch
    if features.ndim!=3 or features.shape[2] not in (3,16,20) or features.shape[0]*features.shape[1]>1048576 or not np.isfinite(features).all():raise ValueError('Bounded finite layered features required')
    h,w=features.shape[:2];core=160;halo=16;pad=np.pad(features,((halo,(-h)%core+halo),(halo,(-w)%core+halo),(0,0)),mode='reflect');ground=np.empty((h,w),np.uint8);canopy=ground.copy();uncertainty=np.empty((h,w),np.float32)
    model.eval()
    with torch.no_grad():
        for top in range(0,h,core):
            for left in range(0,w,core):
                x=torch.from_numpy(pad[top:top+core+2*halo,left:left+core+2*halo].transpose(2,0,1).copy()).float()[None];logits=model(x)[0,:,halo:halo+core,halo:halo+core];hh,ww=min(core,h-top),min(core,w-left)
                prob=logits[:4].softmax(0);ground[top:top+hh,left:left+ww]=prob.argmax(0).numpy()[:hh,:ww];canopy[top:top+hh,left:left+ww]=logits[4:].argmax(0).numpy()[:hh,:ww]
                uncertainty[top:top+hh,left:left+ww]=(-(prob*prob.clamp(min=1e-8).log()).sum(0)/np.log(4)).numpy()[:hh,:ww]
    return ground,canopy,uncertainty


def save(model,rows,manifest,folder,training,encoder_pin=None):
    from safetensors.torch import save_file
    folder=Path(folder);folder.mkdir(parents=True)
    save_file({k:v.detach().contiguous() for k,v in model.state_dict().items()},str(folder/'weights.safetensors'))
    m={'version':VERSION,'channels':rows[0]['features'].shape[2],'ground_labels':data.GROUND,'canopy_labels':data.CANOPY,'dataset_id':manifest['id'],
       'training_record_ids':[r['record']['id'] for r in rows],'training_site_ids':sorted({r['record']['site_id'] for r in rows}),
       'training_source_sha256':[r['record']['image_sha256'] for r in rows],'weights_sha256':file_hash(folder/'weights.safetensors'),
       'encoder_pin':encoder_pin,'training':training,'production_eligible':False,'independent_human_review':False}
    if m['channels']==20:
        if any(not isinstance(r.get('lidar_pin'),str) or len(r['lidar_pin'])!=64 for r in rows):raise ValueError('Pinned LiDAR feature receipts required')
        m['lidar_feature_receipts_sha256']=[r['lidar_pin'] for r in rows];m['lidar_feature_version']='dated-lidar-surface-context-v1'
    m['id']=digest(m);atomic_json(folder/'model.json',m)


def load(folder):
    from safetensors import safe_open
    from safetensors.torch import load_file
    folder=Path(folder);m=json.loads((folder/'model.json').read_text())
    if m.get('version')!=VERSION or m.get('id')!=digest({k:v for k,v in m.items() if k!='id'}) or m.get('production_eligible') is not False or m.get('ground_labels')!=data.GROUND or m.get('canopy_labels')!=data.CANOPY:raise ValueError('Known pinned layered checkpoint required')
    p=folder/'weights.safetensors'
    if p.stat().st_size>2000000 or file_hash(p)!=m['weights_sha256']:raise ValueError('Pinned bounded layered weights required')
    model=architecture(m['channels']);expected=model.state_dict()
    with safe_open(p,framework='pt',device='cpu') as f:
        if set(f.keys())!=set(expected):raise ValueError('Known layered tensors required')
        for k,v in expected.items():
            s=f.get_slice(k)
            if tuple(s.get_shape())!=tuple(v.shape) or s.get_dtype()!='F32':raise ValueError('Known layered tensor headers required')
    weights=load_file(p,device='cpu')
    import torch
    if any(not torch.isfinite(v).all() or v.abs().max()>100 for v in weights.values()):raise ValueError('Finite bounded layered tensors required')
    model.load_state_dict(weights,strict=True);return model.eval(),m


def score(row,ground,canopy):
    from scipy import ndimage
    from .paving_spatial_transfer import connections
    true=row['ground']==0;radius=ndimage.distance_transform_edt(true);narrow=true&(radius<=2)
    binary=np.where(row['ground']==255,255,np.where(true,1,0)).astype(np.uint8)
    return {'ground':data.class_metrics(row['ground'],ground,4),'canopy':data.class_metrics(row['canopy'],canopy,2),
            'path_connections':connections(binary,ground==0,row.get('probes',[])),
            'narrow_labelled_interior_strip_recall':float((ground[narrow]==0).mean()) if narrow.any() else None,
            'paving_on_known_roof_pixels':int(((row['ground']==1)&(ground==0)).sum()),
            'paving_on_known_water_pixels':int(((row['ground']==3)&(ground==0)).sum()),
            'scope':'Assistant-reviewed draft labels only. Ground and canopy are independently scored; hidden ground remains unknown.'}
