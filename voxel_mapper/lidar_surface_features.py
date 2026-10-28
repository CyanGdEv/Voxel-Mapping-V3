"""Dated native-metre LiDAR context aligned to unmarked imagery, never path labels."""
from pathlib import Path
import json

import numpy as np
import rasterio
from scipy import ndimage
from pyproj import datadir
from pyproj.transformer import TransformerGroup

from .generation_cycles import atomic_json, file_hash

VERSION='dated-lidar-surface-context-v1'
CHANNELS=['height_above_terrain_div_30m','terrain_slope_div_pi_over_two','surface_height_std_3m_div_5m','valid_dtm_dsm_neighbourhood']


def native_features(dtm,dsm,dtm_valid,dsm_valid,resolution=1.):
    """Compute structure context at original resolution, preserving every gap."""
    if dtm.shape!=dsm.shape or dtm.shape!=dtm_valid.shape or dtm.shape!=dsm_valid.shape or dtm.size>8000000 or min(dtm.shape)<3 or resolution!=1.:raise ValueError('Matching bounded native one-metre LiDAR pair required')
    valid=dtm_valid&dsm_valid&np.isfinite(dtm)&np.isfinite(dsm)
    height=np.where(valid,np.maximum(0,dsm-dtm),0)
    count=ndimage.uniform_filter(valid.astype(np.float32),size=3,mode='constant')
    mean=ndimage.uniform_filter(height.astype(np.float32),size=3,mode='constant')/np.maximum(count,1e-8)
    square=ndimage.uniform_filter(np.square(height).astype(np.float32),size=3,mode='constant')/np.maximum(count,1e-8)
    rough=np.sqrt(np.maximum(0,square-mean*mean))
    gy,gx=np.gradient(np.where(dtm_valid,dtm,0),resolution)
    support=valid&(count>.999)&ndimage.binary_erosion(dtm_valid,iterations=1,border_value=0)
    out=np.stack([np.clip(height/30,0,1),np.arctan(np.hypot(gx,gy))/(np.pi/2),np.clip(rough/5,0,1),support],axis=2).astype(np.float32)
    out[~support]=0
    if not np.isfinite(out).all():raise ValueError('Finite native LiDAR context required')
    return out


def sample_native(features,bx,by,transform):
    """Nearest native cell; fine image grids do not create finer LiDAR detail."""
    if transform.b!=0 or transform.d!=0 or transform.a!=1 or transform.e!=-1:raise ValueError('Native north-up metre grid required')
    col=np.floor((bx-transform.c)/transform.a).astype(np.int64);row=np.floor((by-transform.f)/transform.e).astype(np.int64)
    valid=(row>=0)&(row<features.shape[0])&(col>=0)&(col<features.shape[1])
    out=np.zeros((*bx.shape,4),np.float32);out[valid]=features[row[valid],col[valid]];return out


def align(receipt,pair_directory,output):
    root=Path(pair_directory);out=Path(output)
    if out.exists():raise ValueError('Fresh LiDAR feature receipt required')
    acquisition=json.loads((root/'acquisition.json').read_text())
    if acquisition.get('status')!='downloaded':raise ValueError('Acquired matched dated LiDAR pair required')
    source=acquisition['source'];survey=source['survey'];grid=source['coordinate_transform']['grid'];path=root/'proj-grids'/Path(grid['file']).name
    if file_hash(path)!=grid['sha256']:raise ValueError('Pinned horizontal datum grid required')
    datadir.append_data_dir(str(path.parent.resolve()));group=TransformerGroup(3857,27700,always_xy=True,allow_ballpark=False)
    if not group.best_available or not group.transformers or not 0<=group.transformers[0].accuracy<=1:raise ValueError('Best metre-scale datum transform required')
    arrays=[];masks=[];transforms=[];pins={}
    for name in ('dtm','dsm'):
        p=root/('ea-national-'+name+'.tif');pins[name]=file_hash(p)
        with rasterio.open(p) as ds:
            if ds.crs.to_epsg()!=27700 or ds.res!=(1.,1.) or ds.width*ds.height>8000000 or ds.count!=1:raise ValueError('Bounded native BNG LiDAR required')
            a=ds.read(1,masked=True);arrays.append(a.filled(np.nan));masks.append(~np.ma.getmaskarray(a));transforms.append(ds.transform)
    if transforms[0]!=transforms[1]:raise ValueError('Matched terrain and surface grids required')
    native=native_features(arrays[0],arrays[1],masks[0],masks[1]);h,w=receipt['height'],receipt['width']
    if h*w>1048576:raise ValueError('Bounded imagery alignment grid required')
    e=receipt['extent_epsg3857'];y,x=np.indices((h,w));px=e[0]+(x+.5)/w*(e[2]-e[0]);py=e[3]-(y+.5)/h*(e[3]-e[1]);bx,by=group.transformers[0].transform(px,py)
    t=transforms[0];inside=(bx>=t.c)&(bx<t.c+native.shape[1])&(by<=t.f)&(by>t.f-native.shape[0]);outside_fraction=float((~inside).mean())
    if outside_fraction>.001:raise ValueError('LiDAR crop must cover the actual exported imagery extent')
    features=sample_native(native,bx,by,t);out.parent.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(out,features=features)
    report={'version':VERSION,'channels':CHANNELS,'image_sha256':receipt['image_sha256'],'features_sha256':file_hash(out),'shape':list(features.shape),
      'dtm_sha256':pins['dtm'],'dsm_sha256':pins['dsm'],'datum_grid_sha256':grid['sha256'],'survey':survey,'native_resolution_m':1.,'resampling':'nearest native cell, no interpolation or gap filling',
      'valid_fraction':float((features[:,:,3]>0).mean()),'outside_lidar_raster_fraction':outside_fraction,'transform_accuracy_m':group.transformers[0].accuracy,'features_are_labels':False,'raw_point_cloud_used':False,
      'limitations':['Raster-derived LiDAR context, not raw point-return density or proof of a path beneath trees.','Survey and aerial dates differ; raster heights never override user labels.','One-metre source detail cannot establish sub-metre path edges.']}
    atomic_json(out.with_suffix('.json'),report);return report


if __name__=='__main__':
    import argparse
    from .layered_surface_benchmark import validate
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dataset',required=True);p.add_argument('--pairs',required=True);p.add_argument('--output',required=True);args=p.parse_args();root=Path(args.dataset);out=Path(args.output)
    if out.exists():raise ValueError('Fresh aligned LiDAR feature directory required')
    manifest=validate(root);out.mkdir(parents=True)
    for record in manifest['records']:
        receipt=json.loads((root/record['receipt_file']).read_text());result=align(receipt,Path(args.pairs)/record['site_id'],out/(record['id']+'.npz'));print(record['id'],result['valid_fraction'])
