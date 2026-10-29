"""Acquire aligned public layers from a retained Nominatim park boundary."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json,math,time,io,zipfile,hashlib,argparse
import requests
import numpy as np
from pyproj import datadir,Transformer,Geod
from pyproj.transformer import TransformerGroup
from shapely.geometry import shape,mapping
from shapely.ops import transform
from voxel_mapper import aerial_material_research as aerial,web_evidence as web
from voxel_mapper.acquisition import ensure_ea_grid,USER_AGENT
from voxel_mapper.survey import crop_pair
from voxel_mapper.osm_alignment_snapshot import acquire as acquire_osm
from voxel_mapper.generation_cycles import atomic_json,file_hash
parser=argparse.ArgumentParser(description='Acquire bounded public Alton Towers world inputs');parser.add_argument('--work',required=True);parser.add_argument('--location',required=True);args=parser.parse_args();w=Path(args.work);w.mkdir(parents=True,exist_ok=True);loc=json.loads(Path(args.location).read_text())[0];boundary=shape(loc['geojson']);bounds=list(boundary.bounds);atomic_json(w/'boundary.geojson',{'type':'Feature','geometry':mapping(boundary),'properties':{'osm_way_id':loc['osm_id'],'name':loc['display_name'],'source':'OpenStreetMap via Nominatim','license':'ODbL-1.0'}})
inputs=w/'inputs';inputs.mkdir(exist_ok=True);terrain=inputs/'survey';terrain.mkdir(exist_ok=True);grid=ensure_ea_grid(terrain);group=TransformerGroup(4326,27700,always_xy=True,allow_ballpark=False)
if not group.best_available or not group.transformers or not 0<=group.transformers[0].accuracy<=1:raise ValueError('Preferred OSTN15 registration required')
t=group.transformers[0];metric=transform(t.transform,boundary);e0,n0,e1,n1=metric.bounds;extent=[math.floor((e0-16)/16)*16,math.floor((n0-16)/16)*16,math.ceil((e1+16)/16)*16,math.ceil((n1+16)/16)*16]
atomic_json(w/'frame.json',{'version':'alton-world-bng-frame-v1','crs':'EPSG:27700','vertical_datum':'ODN','blocks_per_metre':1,'bounds_wgs84':bounds,'bounds_bng':extent,'origin_bng':[extent[0],extent[1]],'boundary_bng':mapping(metric),'projection_accuracy_m':t.accuracy,'datum_grid':grid,'projection_description':t.description,'minecraft_x':'easting minus origin_easting','minecraft_z':'origin_northing minus northing','physical_registration_independently_verified':False})
def osm():
 b=[bounds[0]-.0002,bounds[1]-.0002,bounds[2]+.0002,bounds[3]+.0002];path,r=acquire_osm(inputs/'osm',b);print('OSM',r['bytes'],flush=True)
def image():
 b=[bounds[0]-.0002,bounds[1]-.0002,bounds[2]+.0002,bounds[3]+.0002];c={'version':aerial.VERSION,'site':'Alton Towers','site_id':'alton-towers','provider':'esri_world_imagery','bounds_wgs84':b,'width':2048,'height':1024,'exclude_footer_pixels':0}
 path,r=aerial.acquire(c,inputs/'web-cache',cancelled=lambda:False,deadline=time.monotonic()+180,budget=web.Budget(32000000));dest=inputs/'aerial.png';dest.write_bytes(Path(path).read_bytes());atomic_json(inputs/'aerial-receipt.json',r);print('Aerial RGB',r['width'],r['height'],flush=True)
def elevation():
 archives={};receipts={}
 for kind in ['dtm','dsm']:
  url=f'https://environment.data.gov.uk/tiles/collections/survey/national_lidar_programme_{kind}/2022/1/SK0540';raw=bytearray()
  with requests.get(url,headers={'User-Agent':USER_AGENT},stream=True,timeout=(10,180)) as r:
   r.raise_for_status()
   for chunk in r.iter_content(1000000):
    raw.extend(chunk)
    if len(raw)>100000000:raise ValueError('Native survey archive exceeds source budget')
  archives[kind]=bytes(raw);receipts[kind]={'url':url,'bytes':len(raw),'archive_sha256':hashlib.sha256(raw).hexdigest()};print('Downloaded',kind,len(raw),flush=True)
 survey=crop_pair(archives,extent,terrain,'2022','SK0540');atomic_json(terrain/'survey-receipt.json',{'survey':survey,'sources':receipts,'crs':'EPSG:27700','vertical_datum':'ODN','native_resolution_m':1,'bounds_bng':extent,'grid':grid,'dtm_sha256':file_hash(terrain/'ea-national-dtm.tif'),'dsm_sha256':file_hash(terrain/'ea-national-dsm.tif'),'license':'OGL-UK-3.0'});print('Matched elevation pair',survey['survey_id'],flush=True)
with ThreadPoolExecutor(max_workers=3) as pool:
 futures=[pool.submit(f) for f in [osm,image,elevation]]
 for f in futures:f.result()
print('Source acquisition complete',extent,metric.area,flush=True)
