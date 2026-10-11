"""Replay architectural component hints on the two pinned Mutiny Bay plans."""
import argparse
import hashlib,json
from pathlib import Path
import pymupdf
from voxel_mapper.drawing_geometry import extract_page
from voxel_mapper.linework_boundaries import recover_page
from voxel_mapper.mapped_alignment_checks import printed_scale_review
from voxel_mapper.architectural_interpretation import interpret_page
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--input-root',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
root=args.input_root.resolve()/'mutiny-bay-sources';pages=[]
for sha in ['cefe2556ff04c5bf4822f99ca88a1a295c58def18467f73d2eac3db6b09a6bd2','581e0fb0b88ceabd526f5d56decafd21e37945bf49ae433117be2c94bbabcaf4']:
 path=root/(sha+'.pdf')
 if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('Source PDF checksum mismatch')
 with pymupdf.open(path) as doc:
  parents,extraction=extract_page(doc[0],sha,1,min_line_length_points=.25,max_candidates=10000)
  records,recovery=recover_page(parents);polygons=[r for r in records if r['geometry']['type']=='Polygon']
  report=interpret_page(doc[0],sha,1,parents,polygons,printed_scale_review(path,1))
  report['extraction']=extraction;report['recovery']=recovery
  if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('Source PDF changed during audit')
  pages.append(report)
  print(sha[:8],report['network_review'],report['role_counts'],'bound roof',report['bound_roof_labels'],flush=True)
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps({'pages':pages,'world_geometry_additions':0},separators=(',',':'))+'\n')
