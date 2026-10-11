"""Audit source caption layout on six pinned CTD plan/elevation sheets."""
import argparse
import hashlib
import json
from pathlib import Path
import pymupdf
from voxel_mapper.drawing_geometry import extract_page
from voxel_mapper.architectural_graph import build
from voxel_mapper.architectural_view_layout import review

SOURCES=['f12239c04faecc10973483ac4f559f763300facb8fd9c1b3a1002f9c5666e58b',
'ee51901543aea06b1b9f961576c5066438a67aa1c33e6aa720cc162e37467bb8',
'90ecfc6b13f95eb5a911f11b7f481ae8eb25900d9fac7518160cecd5944468a1',
'62eec055f6cc9e143e2c79d3424940134d0abb79d2956422bc5d0a195e145315',
'6abc1f8e7de17e0a0dc7bf2f1c845a5a0ee1aab35a74409b6ee4c1a77e35d510',
'78335a3713c61282af5442923945e51c856fe0bdb0400f1f76b609dc3d675ec7']
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();pages=[]
for sha in SOURCES:
    path=a.input_root/'mutiny-bay-sources'/(sha+'.pdf')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('Pinned PDF required')
    with pymupdf.open(path) as document:
        if len(document)!=1:raise ValueError('Pinned single-page source required')
        parents,extraction=extract_page(document[0],sha,1,min_line_length_points=.25,max_candidates=10000)
        if extraction['status']!='unplaced_geometry_candidates':raise ValueError('Complete native extraction required')
        graph=build(parents);layout=review(document[0],sha,1,graph)
        if layout['status']!='caption_layout_hypotheses_only':raise ValueError('Complete layout audit required')
        samples=layout['component_membership'][:5]+[r for r in layout['component_membership'] if r['status']=='ambiguous_or_crossing_windows'][:5]
        selected={r['component_id'] for r in samples}
        pages.append({k:layout[k] for k in ('version','document_sha256','page','coordinate_frame','source_graph_sha256','status',
            'view_captions','sheet_titles','page_scale_claims','candidate_windows','checks','counts','limitations')})
        pages[-1].update(layout_records_sha256=hashlib.sha256(json.dumps(layout,sort_keys=True).encode()).hexdigest(),
            source_parent_records_sha256=graph['source_parent_records_sha256'],component_membership_samples=samples,
            source_component_samples=[r for r in graph['source_components'] if r['id'] in selected],
            view_scope_verified=False,scale_application_verified=False,world_geometry_additions=0)
        print(sha[:8],layout['counts'],[(v['printed_claim']['view_kind'],v['printed_claim'].get('printed_scale_denominator')) for v in layout['view_captions']],flush=True)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('PDF changed during layout review')
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps({'pages':pages,'world_geometry_additions':0},separators=(',',':'))+'\n')
