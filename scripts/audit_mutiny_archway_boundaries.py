"""Audit original open-passage line brackets on two pinned courtyard plans."""
import argparse
import hashlib
import json
from pathlib import Path
import pymupdf
from voxel_mapper.architectural_references import review_page
from voxel_mapper.archway_boundaries import review
from voxel_mapper.archway_ends import review as review_ends
from voxel_mapper.drawing_geometry import extract_page
from voxel_mapper.linework_boundaries import recover_page

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--input-root',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
a=parser.parse_args();pages=[]
for sha in ('f12239c04faecc10973483ac4f559f763300facb8fd9c1b3a1002f9c5666e58b',
            'ee51901543aea06b1b9f961576c5066438a67aa1c33e6aa720cc162e37467bb8'):
    path=a.input_root/'mutiny-bay-sources'/(sha+'.pdf')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('Pinned PDF required')
    with pymupdf.open(path) as document:
        if len(document)!=1:raise ValueError('Single-page source required')
        parents,extraction=extract_page(document[0],sha,1,min_line_length_points=.25,max_candidates=10000)
        polygons,recovery=recover_page(parents)
        if extraction['status']!='unplaced_geometry_candidates' or recovery['status']!='enclosed_faces_only':
            raise ValueError('Complete original linework required')
        references=review_page(document[0],sha,1,[r for r in polygons if r['geometry']['type']=='Polygon'])
        result=review(parents,[references]);result['passage_end_review']=review_ends(parents,[references]);result.update(document_sha256=sha,page=1,
            printed_state=references['printed_state'],source_parent_records_sha256=hashlib.sha256(json.dumps(parents,sort_keys=True).encode()).hexdigest())
        pages.append(result)
        print(sha[:8],len(result['passage_end_review']['connections']),'end connections',result['status'],[(r['reference_id'],len(r['boundary_pairs'])) for r in result['references']],flush=True)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('PDF changed during audit')
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps({'pages':pages,'world_geometry_additions':0},separators=(',',':'))+'\n')
