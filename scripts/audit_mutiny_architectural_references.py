"""Replay eight pinned Mutiny plan/elevation sources for printed object-reference links."""
import argparse
import hashlib
import json
from pathlib import Path
import pymupdf
from voxel_mapper.architectural_references import review_page,link_pages
from voxel_mapper.drawing_geometry import extract_page
from voxel_mapper.archway_ends import review as review_ends,occurrence_index
from voxel_mapper.linework_boundaries import recover_page

SOURCES=[
    'f12239c04faecc10973483ac4f559f763300facb8fd9c1b3a1002f9c5666e58b',
    'ee51901543aea06b1b9f961576c5066438a67aa1c33e6aa720cc162e37467bb8',
    'cd5ddf8a912dc07ba2059d6af28b7b047c9146135f7a3f9ca984c4a03ed1506b',
    '6abc1f8e7de17e0a0dc7bf2f1c845a5a0ee1aab35a74409b6ee4c1a77e35d510',
    '90ecfc6b13f95eb5a911f11b7f481ae8eb25900d9fac7518160cecd5944468a1',
    '25f5481a936ffdba9842768a63316fe8610ac7a6862d9aefe6ea4f9d4c161cb6',
    '78335a3713c61282af5442923945e51c856fe0bdb0400f1f76b609dc3d675ec7',
    '62eec055f6cc9e143e2c79d3424940134d0abb79d2956422bc5d0a195e145315',
]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--input-root',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args();root=args.input_root.resolve()/'mutiny-bay-sources';pages=[]
for sha in SOURCES:
    path=root/(sha+'.pdf')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('Source PDF checksum mismatch')
    with pymupdf.open(path) as document:
        if len(document)!=1:raise ValueError('Pinned single-page reference source required')
        parents,extraction=extract_page(document[0],sha,1,min_line_length_points=.25,max_candidates=10000)
        records,recovery=recover_page(parents)
        if extraction['status']!='unplaced_geometry_candidates' or recovery['status']!='enclosed_faces_only':
            raise ValueError('Complete native extraction and recovery required')
        report=review_page(document[0],sha,1,[r for r in records if r['geometry']['type']=='Polygon'])
        if report['view_kind']=='plan':
            report['archway_end_connections']=review_ends(parents,[report])
            for i,row in enumerate(report['reference_occurrences']):
                row.update(occurrence_index(report['archway_end_connections'],i))
        report['extraction']=extraction;report['recovery']=recovery
        report['source_parent_records_sha256']=hashlib.sha256(json.dumps(parents,sort_keys=True).encode()).hexdigest()
        print(sha[:8],report['project_code'],report['printed_state'],report['view_kind'],len(report['reference_occurrences']),flush=True)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('Source PDF changed during reference audit')
    pages.append(report)
links=link_pages(pages)
result={'pages':pages,'reference_links':links,'counts':{'source_pages':len(pages),'reference_correspondences':len(links['links']),
    'unique_enclosure_occurrences':sum(len(r['containing_candidate_ids'])==1 for p in pages for r in p['reference_occurrences'])},
    'coordinate_alignment_verified':False,'height_application_verified':False,'world_geometry_additions':0}
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(result,separators=(',',':'))+'\n')
