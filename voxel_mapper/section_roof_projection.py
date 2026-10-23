"""All original-corner orthographic hypotheses; no preferred physical face."""
import math

import numpy as np

from .reconstruction_evidence_queue import digest

VERSION = 'original-section-roof-projection-v1'
MAX_RESIDUAL_PDF_POINTS = .5


def spoke_groups(page, charge):
    """Use an original hip/base incidence without splitting the whole base line."""
    lines = {r['id']: r for r in page['source_lines']}
    proofs = {r['line_id']: r for r in page['line_pixel_checks']}
    result = []
    for leader in page['leaders']:
        charge()
        closed = [p for p in leader['roof_pairs'] if p['status'] == 'closed_original_section_triangle_candidate']
        for pair in closed or [None]:
            charge()
            row = {'source_document_sha256': page['document_sha256'], 'source_page': page['page'],
                   'source_leader_id': leader['id'], 'closed_source_pair_id': pair['id'] if pair else None,
                   'source_roof_spokes': [], 'status': 'section_three_spoke_group_held',
                   'original_closed_base_split': False, 'previous_outline_holds_overridden': False}
            if pair:
                apex = pair['source_apex_pdf_unrotated']; left, right = sorted(pair['source_slope_far_endpoints'])
                ids = sorted({sid for alternative in leader['roof_pairs'] for sid in alternative['slope_source_ids']})
                by_corner = {}
                for sid in ids:
                    charge(); endpoints = lines[sid]['source_endpoints_pdf_unrotated']
                    if apex not in endpoints: continue
                    end = endpoints[1] if endpoints[0] == apex else endpoints[0]
                    if end[1] == left[1] == right[1] and left[0] <= end[0] <= right[0]:
                        by_corner.setdefault(tuple(end), []).append(sid)
                row['source_roof_spokes'] = [{'source_base_vertex_pdf_unrotated': list(p), 'whole_source_spoke_ids': sorted(ids)}
                                            for p, ids in sorted(by_corner.items())]
                row.update(source_apex_pdf_unrotated=apex, original_closed_base_source_ids=pair['cap_source_ids'],
                           nominal_metres_per_pdf_point=page['nominal_metres_per_pdf_point_candidate'])
                used = [leader['leader_source_id'], *pair['cap_source_ids'], *ids]
                supported = all(proofs[sid]['all_samples_supported'] for sid in used)
                if (len(by_corner) == 3 and min(by_corner)[0] == left[0] and max(by_corner)[0] == right[0]
                        and supported):
                    row['status'] = 'original_three_spoke_whole_base_candidate'
                row['all_used_source_line_samples_supported'] = supported
            row['id'] = digest([VERSION, row]); result.append(row)
    return result


def projections(group, candidate, unit, shared_cap_source_id, charge):
    """Enumerate four front corners and both orders, never rank by residual.

    Source span differences determine a raw horizontal projection vector.
    Its normalized unit vector proposes a camera; unchanged source stations
    then test the unit-camera prediction, with the original apex as anchor.
    """
    if group['status'] != 'original_three_spoke_whole_base_candidate': return []
    corners = np.array(candidate['source_corners_pdf_native'], dtype=float)
    apex = np.array(candidate['source_apex_pdf_native'], dtype=float)
    if corners.shape != (4,2) or apex.shape != (2,) or not np.isfinite(corners).all() or not np.isfinite(apex).all() or not math.isfinite(unit) or unit <= 0:
        raise ValueError('Finite original four-corner plan geometry and scale required')
    edges = np.roll(corners,-1,axis=0)-corners
    if any(np.linalg.norm(e) == 0 for e in edges): raise ValueError('Nonzero original plan edges required')
    if any(abs(float(edges[i] @ edges[(i+1)%4])) > 1e-8*np.linalg.norm(edges[i])*np.linalg.norm(edges[(i+1)%4]) for i in range(4)):
        raise ValueError('Orthogonal original rectangular plan required for this recipe')
    area = sum(corners[i,0]*corners[(i+1)%4,1]-corners[i,1]*corners[(i+1)%4,0] for i in range(4))
    if area == 0: raise ValueError('Nondegenerate original rectangle required')
    points = (corners-apex)*unit
    source = [r['source_base_vertex_pdf_unrotated'] for r in group['source_roof_spokes']]
    source_unit = group['nominal_metres_per_pdf_point']; source_apex = group['source_apex_pdf_unrotated']
    if not math.isfinite(source_unit) or source_unit <= 0: raise ValueError('Positive original section scale required')
    xs = np.array([p[0] for p in source],float)
    if len(xs) != 3 or not np.isfinite(xs).all() or not np.all(np.diff(xs)>0):
        raise ValueError('Three distinct original ordered source stations required')
    result=[]
    for front in range(4):
        for order in (-1,1):
            charge(); mapping=[(front-order)%4,front,(front+order)%4]
            triangle=points[mapping]
            matrix=np.array([triangle[1]-triangle[0],triangle[2]-triangle[1]])
            raw=np.linalg.solve(matrix,np.diff(xs)*source_unit); norm=float(np.linalg.norm(raw))
            if norm == 0 or not np.isfinite(raw).all(): raise ValueError('Finite nonzero source-derived projection required')
            horizontal=raw/norm; viewer=np.array([-horizontal[1],horizontal[0]])
            if float(points[front]@viewer)<0: viewer=-viewer
            depths=points@viewer; front_unique=int(np.argmax(depths))==front and sum(abs(depths-depths[front])<1e-10)==1
            predictions=source_apex[0]+(points@horizontal)/source_unit
            residuals=[float(predictions[ci]-xs[j]) for j,ci in enumerate(mapping)]
            visible=[]
            for i,edge in enumerate(edges):
                normal=np.array([edge[1],-edge[0]])*(1 if area>0 else -1)
                if float(normal@viewer)>1e-10:visible.append(i)
            expected={(front-1)%4,front}; visible_consistent=set(visible)==expected
            source_assignments=[]
            for j in range(2):
                a,b=mapping[j:j+2]
                edge=a if (a+1)%4==b else b
                source_assignments.append({'source_section_interval_pdf_points':[float(xs[j]),float(xs[j+1])],
                    'original_plan_edge_index':edge,'original_plan_perimeter_source_ids':candidate['source_perimeter_ids_per_edge'][edge]})
            shared=[i for i,ids in enumerate(candidate['source_perimeter_ids_per_edge']) if shared_cap_source_id in ids]
            if len(shared)!=1:raise ValueError('Exactly one original shared-cap edge required')
            row={'source_group_id':group['id'],'original_plan_candidate_id':candidate['id'],
                 'original_plan_front_corner_index':front,'source_left_middle_right_plan_corner_indices':mapping,
                 'source_apex_anchor_pdf_unrotated':source_apex,'source_projected_base_vertices_pdf_unrotated':source,
                 'source_adjacent_span_lengths_nominal_m':(np.diff(xs)*source_unit).tolist(),
                 'raw_projection_horizontal_vector':raw.tolist(),'raw_projection_vector_norm':norm,
                 'unit_projection_horizontal_vector':horizontal.tolist(),'candidate_viewer_direction_native_xy':viewer.tolist(),
                 'candidate_corner_depths_nominal_m':depths.tolist(),'projected_original_plan_corner_x_pdf_points':predictions.tolist(),
                 'source_station_residuals_pdf_points':residuals,'maximum_source_station_residual_pdf_points':max(abs(r) for r in residuals),
                 'maximum_permitted_source_station_residual_pdf_points':MAX_RESIDUAL_PDF_POINTS,
                 'candidate_visible_original_edge_indices':visible,'source_visible_edge_assignments':source_assignments,
                 'shared_cap_source_id':shared_cap_source_id,'shared_cap_original_edge_index':shared[0],
                 'shared_cap_candidate_visible':shared[0] in visible,
                 'shared_cap_source_interval_candidates':[a['source_section_interval_pdf_points'] for a in source_assignments if a['original_plan_edge_index']==shared[0]],
                 'status':'conditional_source_projection_supported' if front_unique and visible_consistent and max(abs(r) for r in residuals)<=MAX_RESIDUAL_PDF_POINTS else 'section_projection_held',
                 'orthographic_rectangular_roof_and_same_component_assumed':True,
                 'camera_unit_constraint_applied':True,'original_source_stations_changed':False,'plan_corners_or_apex_moved':False,
                 'physical_face_assignment_verified':False,'geographic_bearing_verified':False,
                 'wall_closure_authorized':False,'geometry_export_authorized':False}
            row['id']=digest([VERSION,row]);result.append(row)
    return result


def ambiguity(groups, poses):
    result=[]
    for group in groups:
        rows=[p for p in poses if p['source_group_id']==group['id'] and p['status']=='conditional_source_projection_supported']
        visible=sum(r['shared_cap_candidate_visible'] for r in rows)
        row={'source_group_id':group['id'],'supported_projection_ids':[p['id'] for p in rows],
             'supported_projection_count':len(rows),'shared_cap_visible_candidates':visible,
             'shared_cap_hidden_candidates':len(rows)-visible,
             'status':'source_projection_supported_shared_cap_ambiguous' if len(rows)>1 else
                 'single_projection_candidate_physical_identity_held' if rows else 'section_projection_support_held',
             'best_residual_candidate_selected':False,'physical_face_assignment_verified':False,'wall_closure_authorized':False,
             'next_requirement':'Section cut/view direction tied to the original roof plan and adjoining gable'}
        row['id']=digest([VERSION,row]);result.append(row)
    return result
