"""Replay exact wall-side/labelled-region evidence on the existing floor plan."""
import argparse,hashlib,json
from pathlib import Path
import pymupdf
from shapely.geometry import shape
from collections import Counter
from voxel_mapper.drawing_geometry import extract_page
from voxel_mapper.linework_boundaries import recover_page
from voxel_mapper.architectural_interpretation import wall_bands
from voxel_mapper.mapped_alignment_checks import printed_scale_review
from voxel_mapper.wall_region_adjacency import review
SHA='cefe2556ff04c5bf4822f99ca88a1a295c58def18467f73d2eac3db6b09a6bd2'
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();path=a.input_root/'mutiny-bay-sources'/(SHA+'.pdf')
if hashlib.sha256(path.read_bytes()).hexdigest()!=SHA:raise ValueError('Pinned source PDF required')
scale=printed_scale_review(path,1)
if scale['status']!='one_visible_printed_scale':raise ValueError('Visible source scale claim required')
with pymupdf.open(path) as doc:
    parents,extraction=extract_page(doc[0],SHA,1,min_line_length_points=.25,max_candidates=10000)
    if extraction['status']!='unplaced_geometry_candidates':raise ValueError('Complete extraction required')
    records,recovery=recover_page(parents,recovery_options={'max_face_provenance':2048})
    if recovery['status']!='enclosed_faces_only':raise ValueError('Complete recovery required')
    faces=[r for r in records if r['geometry']['type']=='Polygon']
    bands,network=wall_bands(parents,scale['expected_metres_per_pdf_point'])
    report=review(doc[0],SHA,1,parents,faces,bands)
band_geometries={r['id']:shape(r['geometry']) for r in bands}
legacy=Counter();current=Counter();links=0
for item in report['wall_adjacency']:
    for side in item['sides']:
        legacy[shape(side['original_source_geometry']).intersection(band_geometries[item['wall_band_id']].boundary).geom_type]+=1
        current[shape(side['band_side_support']).geom_type]+=1
        links+=len(side['adjacent_regions'])
report['source_side_support_review']={'legacy_polygon_intersection_types':dict(legacy),
    'original_source_interval_types':dict(current),'source_side_region_links':links,
    'source_endpoints_moved':False,'source_gaps_joined':False}
selected={r['face_id'] for a in report['wall_adjacency'] for s in a['sides'] for r in s['adjacent_regions']}
report.update(extraction=extraction,recovery=recovery,wall_band_review=network,printed_scale_review=scale,
    source_wall_bands=bands,adjacent_source_faces=[r for r in faces if r['id'] in selected])
if hashlib.sha256(path.read_bytes()).hexdigest()!=SHA:raise ValueError('Source PDF changed')
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,separators=(',',':'))+'\n')
print(report['counts']);print([(r['text'],r['status']) for r in report['labels']])
