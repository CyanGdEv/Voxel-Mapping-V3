"""Recover checksum-pinned raster opening candidates and compare plan spans."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pymupdf
from review_wicker_opening_correspondence import run as plan_review, ELEVATION, FLOOR
from voxel_mapper.raster_openings import detect
from voxel_mapper.opening_correspondence import nearby_plan_segments
from voxel_mapper.plan_elevation_edges import straight_edges
from voxel_mapper.drawing_page_tools import native_inverse


def run(pdf_directory):
    annotations_path=Path('evidence/wicker-shop-vertical-annotations.json')
    annotations=json.loads(annotations_path.read_text())
    pdf=Path(pdf_directory)/(ELEVATION+'.pdf')
    if hashlib.sha256(pdf.read_bytes()).hexdigest()!=ELEVATION or annotations['source_sha256']!=ELEVATION:
        raise ValueError('Elevation source checksum mismatch')
    with pymupdf.open(pdf) as doc:
        page=doc[0];zoom=1888/page.rect.width
        pix=page.get_pixmap(matrix=pymupdf.Matrix(zoom,zoom),alpha=False)
        if [pix.width,pix.height]!=annotations['render_size_pixels'] or hashlib.sha256(pix.samples).hexdigest()!=annotations['render_samples_sha256']:
            raise ValueError('Pinned elevation render changed')
        rgb=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,pix.n)
        gray=np.rint(rgb[:,:,:3].astype(float)@np.array([.299,.587,.114])).astype(np.uint8)
        render_to_native=list(~(page.rotation_matrix*pymupdf.Matrix(zoom,zoom)))
    plan=plan_review(pdf_directory,True);rows=[]
    door_records = [r for r in plan['records'] if any(m['reviewed_opening_id']=='door-NW' for m in r['reviewed_trace_candidates'])]
    if len(door_records)!=1:
        raise ValueError('Unique northwest plan correspondence required for stroke review')
    door_record = door_records[0]
    door_gap = next(g for g in plan['endcap_recovery']['gaps'] if g['id']==door_record['source_gap_candidate_id'])
    layout_path=Path('evidence/wicker-shop-floor-scale-review.json')
    layout=json.loads(layout_path.read_text())
    with pymupdf.open(Path(pdf_directory)/(FLOOR+'.pdf')) as doc:
        door_strokes=nearby_plan_segments(straight_edges(doc[0],FLOOR,1),door_gap['gap_corridor_geometry'],
            100*.0254/72,list(native_inverse(doc[0])),layout['floor_to_roof_linear_matrix'])
    for key in ('SW-opening','NE-opening','NW-door'):
        trace=annotations['vertical_traces'][key]
        result=detect(gray,trace['top_pixel'],trace['bottom_pixel'],100*.0254/72/zoom,
                      endpoint_bound=annotations['manual_endpoint_bound_pixels'])
        matches=[(r,m) for r in plan['records'] for m in r['reviewed_trace_candidates']
                 if m['reviewed_elevation_height_trace']['view']==trace['view']]
        comparisons=[]
        for record,match in matches:
            width=record['layout_normalized_width_m']
            comparisons.append({'reviewed_opening_id':match['reviewed_opening_id'],
                                'source_plan_gap_candidate_id':record['source_gap_candidate_id'],
                                'plan_layout_normalized_cap_centre_span_m':width,
                                'raster_interval_candidates':[{'interval_m':c['nominal_width_interval_m'],
                                    'plan_span_in_raster_sampling_interval':c['nominal_width_interval_m'][0]<=width<=c['nominal_width_interval_m'][1]}
                                    for c in result['candidates']],
                                'physical_plan_elevation_correspondence_verified':False})
        rows.append({'trace_id':key,'view':trace['view'],'raster_review':result,'plan_comparisons':comparisons})
    return {'elevation_pdf_sha256':ELEVATION,'annotation_sha256':hashlib.sha256(annotations_path.read_bytes()).hexdigest(),
            'render_samples_sha256':annotations['render_samples_sha256'],'render_to_unrotated_mupdf_matrix':render_to_native,
            'grayscale_recipe':'RGB weighted sum 0.299R+0.587G+0.114B; numpy rint to uint8',
            'plan_review_sha256':hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest(),
            'opening_reviews':rows,'scale_is_nominal':True,'as_built_verified':False,
            'northwest_door_nearby_plan_stroke_review':{'source_pdf_sha256':FLOOR,
                'layout_review_sha256':hashlib.sha256(layout_path.read_bytes()).hexdigest(),
                'nominal_length_discovery_range_m':[.5,1.2],'maximum_gap_distance_nominal_m':.25,
                'source_gap_candidate_id':door_gap['id'],'stroke_candidates':door_strokes,
                'reveal_depth_m':None,'door_leaf_width_m':None,'physical_roles_verified':False},
            'accepted_components':0,'world_geometry_additions':0}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pdf-directory',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();Path(a.output).write_text(json.dumps(run(a.pdf_directory),sort_keys=True,indent=2)+'\n')
