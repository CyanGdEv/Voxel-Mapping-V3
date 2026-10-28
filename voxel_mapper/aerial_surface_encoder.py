"""Pinned FLAIR aerial SegFormer descriptors; offline safe-tensor CPU inference."""
from pathlib import Path
import json

import numpy as np
from PIL import Image

from .generation_cycles import file_hash

WEIGHTS='c3bc3e2c96e5b1ec5c84f26579db4c02c6c1b78d4da4122602fa644ef4b4c649'
CONFIG='8875cec7d5ddf42ded1ace67839177739d319297da1f1efb07d1d7527f352f7e'
VERSION='flair-b0-native-rgb16-v1'


class Encoder:
    def __init__(self,directory,threads=2):
        import torch
        from transformers import SegformerConfig,SegformerForSemanticSegmentation
        from safetensors import safe_open
        from safetensors.torch import load_file
        directory=Path(directory)
        if file_hash(directory/'config.json')!=CONFIG or file_hash(directory/'model.safetensors')!=WEIGHTS:raise ValueError('Pinned aerial weights and config required')
        if type(threads) is not int or not 1<=threads<=4:raise ValueError('Bounded CPU threads required')
        torch.set_num_threads(threads)
        config=SegformerConfig.from_json_file(directory/'config.json');self.model=SegformerForSemanticSegmentation(config)
        expected=self.model.state_dict()
        with safe_open(directory/'model.safetensors',framework='pt',device='cpu') as f:
            if set(f.keys())!=set(expected):raise ValueError('Known aerial tensors required')
            for k,v in expected.items():
                s=f.get_slice(k)
                if tuple(s.get_shape())!=tuple(v.shape) or s.get_dtype() not in ('F32','I64'):raise ValueError('Bounded aerial tensor headers required')
        weights=load_file(directory/'model.safetensors',device='cpu')
        if any(not torch.isfinite(v).all() for v in weights.values()):raise ValueError('Finite aerial weights required')
        self.model.load_state_dict(weights,strict=True);self.model.eval()
        if [config.id2label[i] for i in (1,3,5,6,7,10)]!=['building','impervious surface','water','coniferous','deciduous','herbaceous vegetation']:raise ValueError('Expected aerial class mapping required')
        self.mean=np.array([.485,.456,.406],np.float32)[:,None,None];self.std=np.array([.229,.224,.225],np.float32)[:,None,None]

    def features(self,rgb):
        import torch
        from torch.nn import functional as F
        if rgb.dtype!=np.uint8 or rgb.ndim!=3 or rgb.shape[2]!=3 or rgb.shape[0]*rgb.shape[1]>1048576:raise ValueError('Bounded native clean RGB required')
        h,w=rgb.shape[:2];output=np.zeros((h,w,16),np.float32);weight=np.zeros((h,w),np.float32)
        def positions(n):return [0] if n<=512 else sorted(set([*range(0,n-512,384),n-512]))
        with torch.no_grad():
            for y in positions(h):
                for x in positions(w):
                    tile=rgb[y:y+512,x:x+512];hh,ww=tile.shape[:2];tile=np.pad(tile,((0,512-hh),(0,512-ww),(0,0)),mode='reflect')
                    values=(tile.astype(np.float32).transpose(2,0,1)/255-self.mean)/self.std
                    logits=self.model(torch.from_numpy(values)[None]).logits
                    if logits.shape!=(1,13,128,128) or not torch.isfinite(logits).all():raise ValueError('Finite expected aerial logits required')
                    p=F.interpolate(logits.softmax(1),size=(512,512),mode='bilinear',align_corners=False)[0].permute(1,2,0).numpy()
                    output[y:y+hh,x:x+ww,3:]+=p[:hh,:ww];weight[y:y+hh,x:x+ww]+=1
        if not (weight>0).all():raise ValueError('Incomplete native aerial coverage')
        output[:,:,3:]/=weight[:,:,None];output[:,:,:3]=rgb.astype(np.float32)/255
        return output


def zero_shot(features):
    """Unmapped FLAIR surfaces abstain; canopy does not imply known ground."""
    if features.ndim!=3 or features.shape[-1]!=16 or features.size>1048576*16 or not np.isfinite(features).all():raise ValueError('Bounded aerial feature tensor required')
    p=features[:,:,3:];winner=p.argmax(2);ground=np.full(winner.shape,255,np.uint8)
    for native,target in [(3,0),(1,1),(10,2),(5,3)]:ground[winner==native]=target
    crown=p[:,:,6]+p[:,:,7];canopy=(crown>=.5).astype(np.uint8)
    return ground,canopy
