"""Replay the two pinned Mutiny sheets against retained mapped park polygons."""
import argparse
import json,hashlib
from pathlib import Path
import pymupdf
from pyproj import datadir
from pyproj.transformer import TransformerGroup
from shapely.geometry import shape
from shapely.ops import transform
from voxel_mapper.cli import parse_osm
from voxel_mapper.drawing_geometry import extract_page
from voxel_mapper.linework_boundaries import recover_page
from voxel_mapper.linework_envelopes import combine
from voxel_mapper.drawing_sheet_links import link
from voxel_mapper.mapped_sheet_placement import propose
from voxel_mapper.mapped_alignment_checks import check,printed_scale_review
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--input-root',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--envelopes',action='store_true')
args=parser.parse_args()
root=args.input_root.resolve()
mapfile=root/'mutiny-bay-sources/current-courtyard-osm.json'
grid=root/'park-cycle-inputs/retained/uk_os_OSTN15_NTv2_OSGBtoETRS.tif'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
datadir.append_data_dir(str(grid.parent));group=TransformerGroup('EPSG:4326','EPSG:27700',always_xy=True)
if not group.best_available:raise ValueError('Precise retained projection unavailable')
project=group.transformers[0]
collection,skipped=parse_osm(json.loads(mapfile.read_text()))
refs=[{'id':f['id'],'geometry':transform(project.transform,shape(f['geometry']))} for f in collection['features'] if f['geometry']['type']=='Polygon' and f['properties']['kind'] in ('building','plaza','water','path','parking')]
sheet_records=[]
report={'status':'map_alignment_review_only','reference_sha256':sha(mapfile),'reference_count':len(refs),'target_crs':'EPSG:27700','grid_sha256':sha(grid),'projection':project.description,'pages':[],'world_geometry_additions':0,'registration_verified':False}
for digest,title in [('cefe2556ff04c5bf4822f99ca88a1a295c58def18467f73d2eac3db6b09a6bd2','3023-08 Existing ground floor plan'),('581e0fb0b88ceabd526f5d56decafd21e37945bf49ae433117be2c94bbabcaf4','3023-10 Existing Roof Plan')]:
 pdf=root/'alton-associated-area-cycle-test/mutiny-bay/corpus/files'/f'{digest}.pdf'
 if sha(pdf)!=digest:raise ValueError('Source PDF hash mismatch')
 with pymupdf.open(pdf) as doc:
  parents,extraction=extract_page(doc[0],digest,1);recovered,recovery=recover_page(parents)
 if args.envelopes:
  envelopes,envelope_review=combine(recovered)
  recovered+=envelopes
  recovery['envelope_recovery']=envelope_review
 seen=set();objects=[];retained=[]
 for c in parents+recovered:
  if c['geometry']['type']!='Polygon' or c.get('paint_reference_truncated') or c.get('curve_approximation',{}).get('cubic_segments',0):continue
  if c.get('rendering_status')!='supported_straight_unclipped_polygon' and c.get('extraction_kind') not in ('linework_boundaries','linework_envelopes'):continue
  geometry=shape(c['geometry']);key=geometry.normalize().wkb_hex
  if key in seen:continue
  seen.add(key);retained.append(c);objects.append({'candidate_id':c['id'],'geometry':geometry})
 scale_review=printed_scale_review(pdf,1)
 scales=scale_review['denominators']
 print(title,len(objects),'objects',len(refs),'refs',scales,flush=True)
 proposal=propose(objects,refs,max_seed_fits=512)
 sheet_records.append((retained,scale_review))
 review=check(objects,refs,proposal['hypotheses'],expected_scale=scale_review['expected_metres_per_pdf_point'],search_flags=proposal['review_flags'])
 report['pages'].append({'document_sha256':digest,'page':1,'title':title,'printed_scale_review':scale_review,'printed_scale_denominators':scales,'candidate_count':len(objects),'candidate_ids_sha256':hashlib.sha256(json.dumps(sorted(o['candidate_id'] for o in objects)).encode()).hexdigest(),'extraction':extraction,'recovery':recovery,'proposal':proposal,'alignment_checks':review})
 if sha(pdf)!=digest:raise ValueError('Source changed during audit')
 print(proposal['status'],len(proposal['hypotheses']),review['status'],flush=True)
if args.envelopes:
 report['cross_sheet_link']=link(sheet_records[0][0],sheet_records[1][0],sheet_records[0][1],sheet_records[1][1])
 report['envelopes_enabled']=True
if sha(mapfile)!=report['reference_sha256'] or sha(grid)!=report['grid_sha256']:raise ValueError('Reference inputs changed during audit')
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(report,indent=2)+'\n')
