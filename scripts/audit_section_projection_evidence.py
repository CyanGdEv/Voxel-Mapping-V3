"""Independent camera equations, original plan items and all face alternatives."""
import argparse
from collections import Counter
import json
from pathlib import Path
import tempfile

import numpy as np
import pymupdf

from voxel_mapper.section_projection_evidence import build
from voxel_mapper.generation_cycles import atomic_json,file_hash
from voxel_mapper.reconstruction_evidence_queue import digest


def audit(evidence,section_evidence,pyramid_evidence,section_catalogue,source_directory,fascia_evidence,roof_plan_pdf,output):
    evidence,section_evidence,pyramid_evidence,section_catalogue,source_directory,fascia_evidence,roof_plan_pdf,output=map(Path,
        (evidence,section_evidence,pyramid_evidence,section_catalogue,source_directory,fascia_evidence,roof_plan_pdf,output))
    path=evidence/'section-projection-evidence.json';r=json.loads(path.read_text());checked=Counter()
    with tempfile.TemporaryDirectory() as temp:
        fresh=build(section_evidence,pyramid_evidence,section_catalogue,source_directory,fascia_evidence,roof_plan_pdf,temp,max_checks=r['contract']['max_projection_checks'])
        fresh.pop('directory');assert fresh==r
    assert r['status']=='section_projection_diagnostics_only' and r['parent_section_fresh_replay_identical']
    parent=json.loads(pyramid_evidence.read_text());groups={g['id']:g for g in r['source_groups']};candidates={c['id']:(c,g) for g in parent['plan_graphs'] for c in g['candidates']}
    with pymupdf.open(roof_plan_pdf) as doc:
        for witness in r['plan_source_witnesses']:
            graph=next(g for g in parent['plan_graphs'] if any(l['source_component_id']==witness['source_component_id'] for l in g['original_lines']))
            page=doc[graph['page']-1];assert page.cropbox.x0==page.cropbox.y0==0
            source=page.get_cdrawings(extended=True)[witness['original_pdf_path_index']]
            assert digest(source)==witness['original_path_record_sha256'];item=source['items'][witness['original_pdf_item_index']];assert item[0]=='l'
            # The pinned source has a zero-offset media/crop box. Convert directly
            # with its original media height, independently of native_inverse.
            original=[[float(p[0]),float(page.mediabox.height-p[1])] for p in item[1:3]]
            assert original==witness['original_endpoints_pdf_native'];checked['independent_original_plan_items']+=1
    for row in r['projection_candidates']:
        group=groups[row['source_group_id']];c,g=candidates[row['original_plan_candidate_id']]
        corners=(np.array(c['source_corners_pdf_native'])-c['source_apex_pdf_native'])*g['nominal_metres_per_pdf_point']
        mapping=row['source_left_middle_right_plan_corner_indices'];s=np.array([p['source_base_vertex_pdf_unrotated'][0] for p in group['source_roof_spokes']]);unit=group['nominal_metres_per_pdf_point']
        a=corners[mapping[1]]-corners[mapping[0]];b=corners[mapping[2]]-corners[mapping[1]];d=np.diff(s)*unit;det=a[0]*b[1]-a[1]*b[0]
        raw=np.array([(d[0]*b[1]-a[1]*d[1])/det,(a[0]*d[1]-d[0]*b[0])/det]);norm=np.sqrt(raw[0]**2+raw[1]**2);u=raw/norm
        assert np.allclose(raw,row['raw_projection_horizontal_vector'],atol=1e-12,rtol=0)
        assert abs(norm-row['raw_projection_vector_norm'])<1e-12
        projected=group['source_apex_pdf_unrotated'][0]+corners@u/unit
        assert np.allclose(projected,row['projected_original_plan_corner_x_pdf_points'],atol=1e-10,rtol=0)
        residual=[float(projected[mapping[i]]-s[i]) for i in range(3)]
        assert np.allclose(residual,row['source_station_residuals_pdf_points'],atol=1e-10,rtol=0)
        viewer=np.array(row['candidate_viewer_direction_native_xy']);assert abs(float(viewer@u))<1e-12;assert abs(np.linalg.norm(viewer)-1)<1e-12
        assert np.argmax(corners@viewer)==row['original_plan_front_corner_index']
        visible=[];centroid=corners.mean(axis=0)
        for i in range(4):
            edge=corners[(i+1)%4]-corners[i];normal=np.array([edge[1],-edge[0]])
            if float(normal@((corners[i]+corners[(i+1)%4])/2-centroid))<0:normal=-normal
            if float(normal@viewer)>0:visible.append(i)
        assert visible==row['candidate_visible_original_edge_indices']
        cap=[i for i,ids in enumerate(c['source_perimeter_ids_per_edge']) if row['shared_cap_source_id'] in ids];assert len(cap)==1
        assert (cap[0] in visible)==row['shared_cap_candidate_visible']
        assert not row['plan_corners_or_apex_moved'] and not row['original_source_stations_changed']
        assert not row['physical_face_assignment_verified'] and not row['wall_closure_authorized']
        checked['independent_source_span_camera_equations']+=1;checked['independent_visible_face_sets']+=1;checked['independent_source_station_residuals']+=3
    for summary in r['face_ambiguity']:
        rows=[p for p in r['projection_candidates'] if p['source_group_id']==summary['source_group_id'] and p['status']=='conditional_source_projection_supported']
        assert len(rows)==summary['supported_projection_count'];assert sum(p['shared_cap_candidate_visible'] for p in rows)==summary['shared_cap_visible_candidates']
        assert not summary['best_residual_candidate_selected'] and not summary['wall_closure_authorized'];checked['independent_ambiguity_gates']+=1
    assert not r['wall_closure_authorized'] and r['world_geometry_additions']==0
    receipt={'status':'passed','fresh_replay_identical':True,'review_sha256':file_hash(path),'source_section_sha256':file_hash(section_evidence),
        'source_pyramid_sha256':file_hash(pyramid_evidence),'checked':dict(checked)}
    atomic_json(output,receipt);return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('evidence','section-evidence','pyramid-evidence','section-catalogue','source-directory','fascia-evidence','roof-plan-pdf','output'):p.add_argument('--'+name,type=Path,required=True)
    print(json.dumps(audit(**vars(p.parse_args()))))
