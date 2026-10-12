"""Replay four checksum-pinned architectural sheets for source topology."""
import argparse
import hashlib
import json
from pathlib import Path
import pymupdf
from voxel_mapper.drawing_geometry import extract_page
from voxel_mapper.architectural_graph import build
from voxel_mapper.architectural_references import review_page
from voxel_mapper.archway_ends import review as review_ends

SOURCES=['f12239c04faecc10973483ac4f559f763300facb8fd9c1b3a1002f9c5666e58b',
'ee51901543aea06b1b9f961576c5066438a67aa1c33e6aa720cc162e37467bb8',
'cefe2556ff04c5bf4822f99ca88a1a295c58def18467f73d2eac3db6b09a6bd2',
'581e0fb0b88ceabd526f5d56decafd21e37945bf49ae433117be2c94bbabcaf4']
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--input-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();pages=[]
for sha in SOURCES:
    path=a.input_root/'mutiny-bay-sources'/(sha+'.pdf')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('Pinned source PDF required')
    with pymupdf.open(path) as document:
        if len(document)!=1:raise ValueError('Pinned single-page source required')
        parents,extraction=extract_page(document[0],sha,1,min_line_length_points=.25,max_candidates=10000)
        if extraction['status']!='unplaced_geometry_candidates':raise ValueError('Complete source extraction required')
        graph=build(parents)
        if graph['status']!='source_drawing_topology_only':raise ValueError('Complete graph required for this audit')
        references=review_page(document[0],sha,1,[]);ends=review_ends(parents,[references])
        identifiers={s['component_id'] for c in ends['connections'] for s in c['solid_sides']+[c['dashed_end']]}
        sample_edges=[e for e in graph['edges'] if e['component_id'] in identifiers]
        sample_nodes={n for e in sample_edges for n in e['node_ids']}
        pages.append({'document_sha256':sha,'page':1,'extraction':extraction,'graph_version':graph['version'],
            'graph_records_sha256':hashlib.sha256(json.dumps(graph,sort_keys=True).encode()).hexdigest(),
            'source_parent_records_sha256':graph['source_parent_records_sha256'],'counts':graph['counts'],
            'archway_source_components':[c for c in graph['source_components'] if c['id'] in identifiers],
            'archway_source_edges':sample_edges,'archway_source_nodes':[n for n in graph['nodes'] if n['id'] in sample_nodes],
            'bounded_curve_component_samples':[c for c in graph['source_components'] if c['curve_approximation']['cubic_segments']][:3],
            'physical_connectivity_verified':False,'view_scope_verified':False,'world_geometry_additions':0})
        print(sha[:8],graph['counts'],flush=True)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('Source changed during graph audit')
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps({'pages':pages,'world_geometry_additions':0},separators=(',',':'))+'\n')
