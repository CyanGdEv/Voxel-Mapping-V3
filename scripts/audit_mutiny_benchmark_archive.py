"""Corroborate visible Mutiny benchmark labels against the pinned official OS archive."""
import argparse,json
from pathlib import Path
from voxel_mapper.benchmark_archive_matching import review
from voxel_mapper.generation_cycles import file_hash

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--archive',type=Path,required=True)
p.add_argument('--matching',type=Path,default=Path('evidence/mutiny-retained-evidence-matching-audit.json'))
p.add_argument('--output',type=Path,required=True)
p.add_argument('--terrain',type=Path)
a=p.parse_args();matching_pin=file_hash(a.matching);matching=json.loads(a.matching.read_text())
result=review(matching['benchmark_reviews'],a.archive,file_hash(a.archive),[405345,341810,409345,345810])
result['matching_audit_sha256']=matching_pin
result['search_domain_basis']='Two-kilometre axis offsets around the retained application site-address coordinate (407345,343810); not a benchmark identity or accepted area boundary.'
if a.terrain:
 import rasterio
 from rasterio.windows import from_bounds
 import numpy as np
 terrain_pin=file_hash(a.terrain);samples=[]
 ids={i for link in result['links'] for i in link['candidate_archive_ids']}
 with rasterio.open(a.terrain) as raster:
  if raster.crs.to_epsg()!=27700:raise ValueError('Native BNG terrain required for diagnostic sampling')
  for row in result['nearby_archive_records']:
   if row['id'] not in ids:continue
   x,y=row['position_bng'];radius=row['grid_reference_resolution_m']
   window=from_bounds(x-radius,y-radius,x+radius,y+radius,raster.transform)
   data=raster.read(1,window=window,boundless=True,masked=True)
   values=data.compressed();values=values[np.isfinite(values)]
   samples.append({'archive_id':row['id'],'search_radius_m':radius,
    'grid_reference_pixel_height':float(next(raster.sample([(x,y)]))[0]),
    'neighbourhood_valid_pixels':len(values),'neighbourhood_min':float(values.min()) if len(values) else None,
    'neighbourhood_max':float(values.max()) if len(values) else None,
    'benchmark_ground_offset_claim_m':row['original_archive_row'].get('HEIGHT ABOVE GROUND'),
    'terrain_datum_verified':False,'benchmark_identity_verified':False,
    'purpose':'Terrain context at coarse historical grid reference; never a datum or registration acceptance check.'})
 if file_hash(a.terrain)!=terrain_pin:raise ValueError('Terrain changed during diagnostic')
 result['terrain_context']={'sha256':terrain_pin,'samples':samples}
if file_hash(a.matching)!=matching_pin:raise ValueError('Matching audit changed')
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
print(json.dumps({'status':result['status'],'nearby_records':len(result['nearby_archive_records']),'links':[(l['status'],len(l['candidate_archive_ids'])) for l in result['links']]}))
