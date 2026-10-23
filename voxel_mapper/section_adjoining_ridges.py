"""Whole adjoining-ridge endpoint tests using unchanged section camera proposals."""
import math

import numpy as np
import pymupdf

from .reconstruction_evidence_queue import digest

VERSION = 'original-section-adjoining-ridges-v1'
MAX_RESIDUAL_PDF_POINTS = .5


def horizontal_strokes(page, sha, groups, charge):
    """Extract whole opaque solid strokes in fixed source-only neighbourhoods.

    Predictions do not select or clip vectors. Every horizontal line in each
    neighbourhood is retained before any endpoint comparison takes place.
    """
    paths = page.get_cdrawings(extended=True)
    if len(paths) > 500000:
        raise OverflowError('adjoining_original_path_budget')
    windows = {}
    for group in groups:
        if group['status'] != 'original_three_spoke_whole_base_candidate':
            continue
        points = [s['source_base_vertex_pdf_unrotated'] for s in group['source_roof_spokes']]
        windows[group['id']] = [points[0][0]-250, points[0][1], points[-1][0]+250, points[0][1]+80]
    result = []
    for pi, path in enumerate(paths):
        charge()
        if (path['type'] != 's' or path.get('layer') or path.get('stroke_opacity') != 1
                or path.get('dashes') != '[] 0'):
            continue
        x0,y0,x1,y1 = path['rect']
        if not any(x0 <= w[2] and x1 >= w[0] and y0 <= w[3] and y1 >= w[1] for w in windows.values()):
            continue
        if len(path['items']) > 10000:
            raise OverflowError('adjoining_original_item_budget')
        for ii, item in enumerate(path['items']):
            charge()
            if item[0] != 'l':
                continue
            points = [list(p) for p in item[1:3]]
            if not np.isfinite(points).all():
                raise ValueError('Finite original adjoining strokes required')
            a, b = points
            if a[1] != b[1] or not 12 <= abs(b[0]-a[0]) <= 250:
                continue
            memberships = [gid for gid, (x0,y0,x1,y1) in windows.items()
                           if x0 <= min(a[0],b[0]) <= max(a[0],b[0]) <= x1 and y0 <= a[1] <= y1]
            if not memberships:
                continue
            row = {'document_sha256':sha, 'page':page.number+1, 'path_index':pi, 'item_index':ii,
                   'path_record_sha256':digest(path), 'source_endpoints_pdf_unrotated':points,
                   'color_rgb':list(path['color']), 'stroke_width_pdf_points':path['width'],
                   'paint_seqno':path['seqno'], 'source_group_ids':memberships,
                   'source_line_clipped_or_extended':False}
            row['id'] = digest([VERSION,row]); result.append(row)
            if len(result) > 512:
                raise OverflowError('adjoining_local_line_budget')
    return result


def compare(group, pose, candidate, ridge, plan_unit, lines, charge):
    """Compare both whole endpoint stations; never fit a shift, scale or height."""
    points = np.asarray(ridge['source_endpoints_pdf_native'], float)
    apex = np.asarray(candidate['source_apex_pdf_native'], float)
    u = np.asarray(pose['unit_projection_horizontal_vector'], float)
    section_unit = group['nominal_metres_per_pdf_point']
    if (points.shape != (2,2) or apex.shape != (2,) or u.shape != (2,)
            or not np.isfinite(points).all() or not np.isfinite(apex).all() or not np.isfinite(u).all()
            or not math.isfinite(plan_unit) or plan_unit <= 0
            or not math.isfinite(section_unit) or section_unit <= 0
            or abs(np.linalg.norm(u)-1) > 1e-10 or np.array_equal(points[0],points[1])):
        raise ValueError('Original whole ridge, positive source scales and parent unit camera required')
    prediction = group['source_apex_pdf_unrotated'][0] + ((points-apex)*plan_unit)@u/section_unit
    order = np.argsort(prediction).tolist(); comparisons=[]
    for line in lines:
        charge()
        if group['id'] not in line['source_group_ids']:
            continue
        source = sorted(p[0] for p in line['source_endpoints_pdf_unrotated'])
        residuals = [float(prediction[ci]-source[j]) for j,ci in enumerate(order)]
        supported = (pose['status']=='conditional_source_projection_supported'
                     and abs(float(prediction[1]-prediction[0])) > 1e-10
                     and max(abs(v) for v in residuals) <= MAX_RESIDUAL_PDF_POINTS)
        comparisons.append({'source_line_id':line['id'], 'left_right_original_ridge_endpoint_indices':order,
                            'source_endpoint_residuals_pdf_points':residuals,
                            'maximum_endpoint_residual_pdf_points':max(abs(v) for v in residuals),
                            'endpoints_compatible':supported})
    row = {'source_group_id':group['id'], 'parent_projection_id':pose['id'],
           'original_plan_candidate_id':candidate['id'], 'original_ridge_source_id':ridge['source_component_id'],
           'projected_original_ridge_endpoint_x_pdf_points':prediction.tolist(),
           'maximum_permitted_residual_pdf_points':MAX_RESIDUAL_PDF_POINTS,
           'candidate_shared_cap_visible':pose['shared_cap_candidate_visible'],
           'comparisons':comparisons, 'same_adjoining_roof_and_orthographic_camera_assumed':True,
           'source_stations_or_scale_fitted':False, 'vertical_ridge_level_inferred':False,
           'physical_correspondence_verified':False, 'wall_closure_authorized':False}
    row['id'] = digest([VERSION,row]); return row


def summarize(groups, checks, pixels):
    supported = {p['line_id'] for p in pixels if p['all_samples_supported']}
    result=[]
    for group in groups:
        rows = [r for r in checks if r['source_group_id']==group['id']]
        surviving = [r for r in rows if any(c['endpoints_compatible'] and c['source_line_id'] in supported for c in r['comparisons'])]
        unique = {r['parent_projection_id']:r for r in surviving}
        surviving = list(unique.values())
        visible = sum(r['candidate_shared_cap_visible'] for r in surviving)
        row = {'source_group_id':group['id'], 'parent_projection_count':len(rows),
               'conditionally_supported_projection_ids':sorted({r['parent_projection_id'] for r in surviving}),
               'conditionally_supported_projection_count':len(surviving),
               'shared_cap_visible_candidates':visible, 'shared_cap_hidden_candidates':len(surviving)-visible,
               'conditional_shared_cap_visibility_consistent':bool(surviving) and visible in (0,len(surviving)),
               'conditional_shared_cap_visible':bool(visible) if surviving and visible in (0,len(surviving)) else None,
               'status':'conditional_adjoining_ridge_endpoint_support' if surviving else 'adjoining_ridge_source_support_held',
               'parent_orientations_deleted':False, 'best_residual_candidate_selected':False,
               'physical_face_assignment_verified':False, 'wall_closure_authorized':False,
               'next_requirement':'Independent physical building correspondence and section cut/view direction; shared-cap surface and datum'}
        row['id'] = digest([VERSION,row]); result.append(row)
    return result
