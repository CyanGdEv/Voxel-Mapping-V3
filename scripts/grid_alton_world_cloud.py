"""Reproducible raw LiDAR input for voxel_mapper.alton_aligned_world."""
from pathlib import Path
import json,zipfile,collections,time,argparse
import numpy as np
import laspy
from voxel_mapper.point_cloud import is_bng
from voxel_mapper.generation_cycles import atomic_json,file_hash
parser=argparse.ArgumentParser(description='Stream the pinned Alton Towers 2022 native classified survey into metre bins')
parser.add_argument('--work',required=True);parser.add_argument('--archive',required=True);parser.add_argument('--source-receipt',required=True);parser.add_argument('--output')
args=parser.parse_args();w=Path(args.work);output=Path(args.output) if args.output else w/'inputs';output.mkdir(parents=True,exist_ok=True)
frame=json.loads((w/'frame.json').read_text());e0,n0,e1,n1=frame['bounds_bng'];width=e1-e0;height=n1-n0;archive=Path(args.archive);prior=json.loads(Path(args.source_receipt).read_text());sha=file_hash(archive)
if width%16 or height%16 or width*height>=1<<22:raise ValueError('Chunk-aligned bounded metre frame required')
if sha!=prior['archive_sha256']:raise ValueError('Retained source archive checksum differs')
roof=np.full(height*width,-np.inf,np.float32);vegetation=roof.copy();counts={k:np.zeros(height*width,np.uint16) for k in ['roof','vegetation','ground']};packed=[];classes=collections.Counter();scanned=kept=0;start=time.monotonic()
with zipfile.ZipFile(archive) as z:
 entries=z.infolist()
 if len(entries)!=1 or entries[0].filename!='SK0540_P_10682_20220105_20220105.laz':raise ValueError('Known survey-matched LAZ entry required')
 with z.open(entries[0]) as stream,laspy.open(stream) as reader:
  if not is_bng(reader.header.parse_crs()) or reader.header.point_count!=98342681:raise ValueError('Known native BNG point-cloud header required')
  for points in reader.chunk_iterator(500000):
   scanned+=len(points);x=np.asarray(points.x);y=np.asarray(points.y);zz=np.asarray(points.z);eligible=~np.asarray(points.withheld,dtype=bool)&~np.asarray(points.synthetic,dtype=bool);sel=(x>=e0)&(x<e1)&(y<=n1)&(y>n0)&np.isfinite(zz)&eligible
   if sel.any():
    c=np.floor(x[sel]-e0).astype(np.int32);r=np.floor(n1-y[sel]).astype(np.int32);ids=r*width+c;labels=np.asarray(points.classification)[sel];elev=zz[sel].astype(np.float32);kept+=len(ids);v,k=np.unique(labels,return_counts=True);classes.update({int(a):int(b) for a,b in zip(v,k)})
    for kind,mask,array in [('roof',labels==6,roof),('vegetation',np.isin(labels,[3,4,5]),vegetation),('ground',labels==2,None)]:
     if mask.any():
      np.add.at(counts[kind],ids[mask],1)
      if array is not None:np.maximum.at(array,ids[mask],elev[mask])
      if kind=='vegetation':
       native=np.floor(elev[mask]).astype(np.int64)
       good=(native>=-64)&(native<500);packed.append(ids[mask][good].astype(np.uint64)|((native[good]+512).astype(np.uint64)<<22))
   if scanned%10000000==0:print('Scanned',scanned,'retained',kept,flush=True)
leaf=np.unique(np.concatenate(packed)) if packed else np.empty(0,np.uint64);cells=(leaf&((1<<22)-1)).astype(np.int64);rows=cells//width;cols=cells%width;chunk=(rows//16)*(width//16)+cols//16;order=np.argsort(chunk,kind='stable');leaf=leaf[order];chunk=chunk[order];offsets=np.searchsorted(chunk,np.arange((height//16)*(width//16)+1)).astype(np.int64)
roof[~np.isfinite(roof)]=np.nan;vegetation[~np.isfinite(vegetation)]=np.nan;dest=output/'point-cloud-grids.npz';np.savez_compressed(dest,roof=roof.reshape(height,width),vegetation=vegetation.reshape(height,width),roof_count=counts['roof'].reshape(height,width),vegetation_count=counts['vegetation'].reshape(height,width),ground_count=counts['ground'].reshape(height,width),leaf_voxels=leaf,leaf_chunk_offsets=offsets)
atomic_json(output/'point-cloud-receipt.json',{'version':'alton-native-return-grid-v1','url':prior['url'],'archive_sha256':sha,'archive_bytes':archive.stat().st_size,'entry':entries[0].filename,'survey_id':'P_10682','survey_date':'2022-01-05','crs':'EPSG:27700','vertical_datum':'ODN','bounds_bng':frame['bounds_bng'],'resolution_m':1,'scanned_points':scanned,'retained_eligible_points_in_rectangle':kept,'classes':dict(classes),'observed_foliage_voxels':len(leaf),'withheld_and_synthetic_excluded':True,'grid_file_sha256':file_hash(dest),'license':'OGL-UK-3.0','attribution':'Contains Environment Agency information © Environment Agency and/or database right','wall_seconds':time.monotonic()-start,'scope':'Observed return bins and classification context. Inferred tree trunks and sampled building surfaces are separate reconstruction choices.'})
print('Cloud complete',scanned,kept,len(leaf),flush=True)
