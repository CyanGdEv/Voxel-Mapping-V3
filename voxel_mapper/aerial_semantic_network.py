"""Small CPU RGB/context semantic network; labels never enter inference features."""
from concurrent.futures import CancelledError
import math
import numpy as np
from scipy import ndimage

VERSION='aerial-rgb-context-network-v1'
CLASSES=['paths_plazas','building_roofs','car_parks','landscaped_islands','other_visible']
FEATURE_VERSION='rgb-lab-multiscale-metres-v1'
FEATURE_COUNT=31
DEFAULTS={'hidden':24,'epochs':60,'batch_size':512,'learning_rate':.01,'regularization':.0001,'seed':137}


def check(cancelled):
    if cancelled():raise CancelledError('Aerial semantic learning cancelled')


def features(rgb,metres_per_pixel,*,cancelled=lambda:False):
    if not isinstance(rgb,np.ndarray) or rgb.ndim!=3 or rgb.shape[2]!=3 or rgb.shape[0]*rgb.shape[1]>1048576:
        raise ValueError('Bounded H by W RGB array required')
    if not math.isfinite(metres_per_pixel) or not .05<=metres_per_pixel<=5:raise ValueError('Bounded imagery scale required')
    from .aerial_material_research import _lab
    values=np.asarray(rgb,np.float32)/255
    if not np.isfinite(values).all() or values.min()<0 or values.max()>1:raise ValueError('Finite byte RGB values required')
    lab=_lab(rgb).astype(np.float32)/np.array([100,128,128],np.float32)
    luminance=values@np.array([.2126,.7152,.0722],np.float32)
    edge=np.hypot(ndimage.sobel(luminance,axis=0),ndimage.sobel(luminance,axis=1))/8
    parts=[values,lab,luminance[:,:,None],edge[:,:,None]]
    for radius in (1.,4.,12.):
        check(cancelled);size=min(129,max(3,2*round(radius/metres_per_pixel)+1))
        mean=ndimage.uniform_filter(values,size=(size,size,1),mode='reflect')
        variance=np.maximum(0,ndimage.uniform_filter(values*values,size=(size,size,1),mode='reflect')-mean*mean)
        parts.extend([mean,np.sqrt(variance),ndimage.uniform_filter(edge,size=size)[:,:,None]])
    parts.extend([((values[:,:,1]-values[:,:,0])/(values[:,:,1]+values[:,:,0]+.01))[:,:,None],
        (values.max(axis=2)-values.min(axis=2))[:,:,None]])
    result=np.concatenate(parts,axis=2).astype(np.float32)
    if result.shape[2]!=FEATURE_COUNT:raise ValueError('Semantic feature contract changed')
    return result


def initialize(inputs=FEATURE_COUNT,hidden=24,classes=5,seed=137):
    rng=np.random.default_rng(seed)
    return {'w1':rng.normal(0,1/math.sqrt(inputs),(inputs,hidden)).astype(np.float32),'b1':np.zeros(hidden,np.float32),
        'w2':rng.normal(0,1/math.sqrt(hidden),(hidden,classes)).astype(np.float32),'b2':np.zeros(classes,np.float32)}


def forward(x,parameters):
    hidden=np.tanh(x@parameters['w1']+parameters['b1']);logits=hidden@parameters['w2']+parameters['b2']
    logits-=logits.max(axis=1,keepdims=True);p=np.exp(logits);p/=p.sum(axis=1,keepdims=True)
    return hidden,p


def fit(x,y,settings=None,*,cancelled=lambda:False):
    settings={**DEFAULTS,**(settings or {})}
    if set(settings)!=set(DEFAULTS):raise ValueError('Known aerial network settings required')
    for key,low,high in [('hidden',8,64),('epochs',1,120),('batch_size',32,2048),('seed',0,2**32-1)]:
        if type(settings[key]) is not int or not low<=settings[key]<=high:raise ValueError('Bounded aerial network settings required')
    if any(type(settings[k]) not in (int,float) for k in ['learning_rate','regularization']):raise ValueError('Numeric optimizer settings required')
    if not 0<float(settings['learning_rate'])<=.05 or not 0<=float(settings['regularization'])<=.1:raise ValueError('Bounded optimization settings required')
    x=np.asarray(x,np.float32);y=np.asarray(y)
    if x.ndim!=2 or x.shape[1]!=FEATURE_COUNT or len(x)!=len(y) or not 5<=len(x)<=100000 or not np.isfinite(x).all():raise ValueError('Bounded labelled aerial samples required')
    if y.dtype.kind not in 'iu' or set(y.tolist())!=set(range(5)):raise ValueError('All five semantic classes required for fitting')
    mean=x.mean(axis=0);scale=np.maximum(x.std(axis=0),.03);normalized=(x-mean)/scale
    parameters=initialize(hidden=settings['hidden'],seed=settings['seed']);initial={k:v.copy() for k,v in parameters.items()}
    moments={k:np.zeros_like(v) for k,v in parameters.items()};velocities={k:np.zeros_like(v) for k,v in parameters.items()}
    counts=np.bincount(y,minlength=5);weights=len(y)/(5*counts);rng=np.random.default_rng(settings['seed']);history=[];step=0
    for epoch in range(settings['epochs']):
        check(cancelled);order=rng.permutation(len(y));loss=0
        for start in range(0,len(y),settings['batch_size']):
            check(cancelled);indices=order[start:start+settings['batch_size']];batch=normalized[indices];target=y[indices]
            hidden,p=forward(batch,parameters);sample_weight=weights[target].astype(np.float32)
            loss+=float(-(np.log(np.maximum(p[np.arange(len(target)),target],1e-8))*sample_weight).sum())
            delta=p.copy();delta[np.arange(len(target)),target]-=1;delta*=sample_weight[:,None]/len(target)
            dh=(delta@parameters['w2'].T)*(1-hidden*hidden)
            gradients={'w2':hidden.T@delta+settings['regularization']*parameters['w2'],'b2':delta.sum(axis=0),
                'w1':batch.T@dh+settings['regularization']*parameters['w1'],'b1':dh.sum(axis=0)}
            step+=1
            for key in parameters:
                gradient=np.clip(gradients[key],-5,5);moments[key]=.9*moments[key]+.1*gradient;velocities[key]=.999*velocities[key]+.001*gradient*gradient
                parameters[key]-=settings['learning_rate']*(moments[key]/(1-.9**step))/(np.sqrt(velocities[key]/(1-.999**step))+1e-8)
        if epoch in (0,settings['epochs']-1) or (epoch+1)%10==0:history.append({'epoch':epoch+1,'weighted_cross_entropy':loss/len(y)})
    return {'parameters':{k:v.tolist() for k,v in parameters.items()},'normalization':{'mean':mean.tolist(),'scale':scale.tolist()},
        'settings':settings,'loss_history':history,'weight_change_l2':float(sum(np.sum((parameters[k]-initial[k])**2) for k in parameters)**.5)}


def validate_model(model):
    if model.get('version')!='aerial-semantic-model-v1' or model.get('network_version')!=VERSION or model.get('feature_version')!=FEATURE_VERSION or model.get('classes')!=CLASSES:
        raise ValueError('Known aerial semantic checkpoint required')
    from .desktop_memory import digest
    if model.get('artifact_sha256')!=digest({k:v for k,v in model.items() if k!='artifact_sha256'}) or model.get('production_eligible') is not False:
        raise ValueError('Pinned research aerial semantic checkpoint required')
    if model.get('physical_geometry_verified') is not False or model.get('world_blocks_generated')!=0 or model.get('label_policy')!='assistant_visual_review_provisional_not_human_ground_truth':raise ValueError('Research-only semantic lineage required')
    hidden=model['network']['settings']['hidden']
    if type(hidden) is not int or not 8<=hidden<=64:raise ValueError('Bounded semantic hidden size required')
    result={}
    for key,size in {'w1':(FEATURE_COUNT,hidden),'b1':(hidden,),'w2':(hidden,5),'b2':(5,)}.items():
        value=model['network']['parameters'][key]
        if not isinstance(value,list) or len(value)!=size[0] or (len(size)==2 and any(not isinstance(row,list) or len(row)!=size[1] for row in value)):
            raise ValueError('Bounded semantic parameter dimensions required')
        array=np.asarray(value,np.float32)
        if array.shape!=size or not np.isfinite(array).all() or np.abs(array).max()>100:raise ValueError('Finite semantic parameters required')
        result[key]=array
    normalization=model['network']['normalization']
    if any(not isinstance(normalization.get(k),list) or len(normalization[k])!=FEATURE_COUNT for k in ['mean','scale']):raise ValueError('Bounded normalization vectors required')
    mean=np.asarray(normalization['mean'],np.float32);scale=np.asarray(normalization['scale'],np.float32)
    if mean.shape!=(FEATURE_COUNT,) or scale.shape!=(FEATURE_COUNT,) or not np.isfinite(mean).all() or not np.isfinite(scale).all() or np.any(scale<.03):raise ValueError('Finite semantic normalization required')
    return result,mean,scale


def predict(feature_grid,model,*,cancelled=lambda:False):
    parameters,mean,scale=validate_model(model);shape=feature_grid.shape
    if len(shape) not in (2,3) or shape[-1]!=FEATURE_COUNT or feature_grid.size>1048576*FEATURE_COUNT:raise ValueError('Bounded source feature grid required')
    flat=np.asarray(feature_grid,np.float32).reshape(-1,FEATURE_COUNT)
    if not np.isfinite(flat).all():raise ValueError('Finite inference features required')
    probabilities=np.empty((len(flat),5),np.float32)
    for start in range(0,len(flat),16384):
        check(cancelled);_,p=forward((flat[start:start+16384]-mean)/scale,parameters);probabilities[start:start+len(p)]=p
    return probabilities.reshape(*shape[:-1],5)
