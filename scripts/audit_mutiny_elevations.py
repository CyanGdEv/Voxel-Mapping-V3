"""Replay ten pinned native Mutiny Bay elevation PDFs without projecting to world geometry."""
import argparse
import hashlib
import json
from pathlib import Path
import pymupdf
from voxel_mapper.architectural_interpretation import interpret_page
from voxel_mapper.drawing_geometry import extract_page
from voxel_mapper.linework_boundaries import recover_page
from voxel_mapper.mapped_alignment_checks import printed_scale_review

SOURCES=[
    '52f611a27b3969a53307353dbe4b5b37daa9a560b3772b7576cb78f916bd6e4c',
    '7c94c6eab604315325bf5afdf76d683fe5a9a94aee2fe6450a260a0a8f7986be',
    'c577950913b5d979e4c5a47d2010fd6a4021061007cb87f4efceb859ffd2ba3d',
    'c22df157011d2e64fc0538ab8d706dddc9e4a085483489bd539a4b353c552d54',
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
        if len(document)!=1:raise ValueError('Pinned single-page elevation source required')
        page=document[0];parents,extraction=extract_page(page,sha,1,min_line_length_points=.25,max_candidates=10000)
        records,recovery=recover_page(parents)
        if extraction['status']!='unplaced_geometry_candidates' or recovery['status']!='enclosed_faces_only':
            raise ValueError('Complete native extraction and recovery required for elevation audit')
        report=interpret_page(page,sha,1,parents,[r for r in records if r['geometry']['type']=='Polygon'],printed_scale_review(path,1))
        if 'elevation_interpretation' not in report:raise ValueError('Pinned source elevation captions required')
        report['extraction']=extraction;report['recovery']=recovery
        report['source_parent_records_sha256']=hashlib.sha256(json.dumps(parents,sort_keys=True).encode()).hexdigest()
        report['source_polygon_records_sha256']=hashlib.sha256(json.dumps([r for r in records if r['geometry']['type']=='Polygon'],sort_keys=True).encode()).hexdigest()
        e=report['elevation_interpretation']
        print(sha[:8],e['printed_state'],e['counts'],'view scales',e['view_scale_denominators'],flush=True)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('Source PDF changed during elevation audit')
    pages.append(report)
result={'pages':pages,'counts':{'source_pages':len(pages),
    'material_regions':sum(p['elevation_interpretation']['counts']['material_regions'] for p in pages),
    'bound_material_labels':sum(p['elevation_interpretation']['counts']['bound_material_labels'] for p in pages)},
    'height_application_verified':False,'world_geometry_additions':0}
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(result,separators=(',',':'))+'\n')
