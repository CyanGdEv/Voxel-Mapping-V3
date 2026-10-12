"""Replay the provenance-limited face on the pinned existing Mutiny floor plan."""
import argparse
import hashlib
import json
from pathlib import Path
import pymupdf
from voxel_mapper.drawing_geometry import extract_page
from voxel_mapper.linework_boundaries import recover_page, VERSION

SHA='cefe2556ff04c5bf4822f99ca88a1a295c58def18467f73d2eac3db6b09a6bd2'
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--input-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();path=a.input_root/'mutiny-bay-sources'/(SHA+'.pdf')
if hashlib.sha256(path.read_bytes()).hexdigest()!=SHA:raise ValueError('Pinned source PDF required')
with pymupdf.open(path) as doc:
    if len(doc)!=1:raise ValueError('Pinned single-page source required')
    parents,extraction=extract_page(doc[0],SHA,1,min_line_length_points=.25,max_candidates=10000)
if extraction['status']!='unplaced_geometry_candidates':raise ValueError('Complete extraction required')
baseline,baseline_review=recover_page(parents)
expanded,expanded_review=recover_page(parents,recovery_options={'max_face_provenance':2048})
old={r['id']:r for r in baseline};new={r['id']:r for r in expanded}
# Provenance option changes derived contracts, never the pre-existing geometries.
if any(i not in new or new[i]['geometry']!=r['geometry'] for i,r in old.items()):
    raise ValueError('Existing source geometry changed')
additional=[new[i] for i in sorted(set(new)-set(old))]
report={'version':VERSION,'document_sha256':SHA,'page':1,'title':'3023-08 Existing Ground Floor Plan',
    'coordinate_frame':'pdf_native_points_y_up','extraction':extraction,
    'source_parent_records_sha256':hashlib.sha256(json.dumps(parents,sort_keys=True).encode()).hexdigest(),
    'default_provenance_limit':256,'expanded_provenance_limit':2048,
    'baseline_review':baseline_review,'expanded_review':expanded_review,'additional_faces':additional,
    'existing_geometry_unchanged':True,'physical_identity_verified':False,'registration_verified':False,
    'world_geometry_additions':0,'limitations':[
        'The newly recovered source face includes outdoor space; it is not an accepted building footprint.',
        'All original holes and full source links remain retained. No snapping or gap closure is introduced.',
        'Printed scale, geographic registration, building identity and heights are not authorized by face closure.']}
if hashlib.sha256(path.read_bytes()).hexdigest()!=SHA:raise ValueError('Source PDF changed')
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,separators=(',',':'))+'\n')
print({'additional_faces':len(additional),'baseline_faces':baseline_review['recovered_faces'],'expanded_faces':expanded_review['recovered_faces']})
