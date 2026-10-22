"""Original fascia-end pixels and conditional source-cap roof patches.

Mesh support ends at original plan cap witnesses. Whole rail tails remain
unmeshed; continuous surfaces and physical roof/fascia roles are assumptions.
"""
from itertools import product
import hashlib
import math

import numpy as np

from .reconstruction_evidence_queue import digest

VERSION = 'source-cap-roof-patches-v1'


def vertical_caps(gray, excluded, threshold, charge):
    """Whole short original ink-column runs, before any roof/corner prediction.

A one-pixel dark stroke can have zero binary Sobel response at its centre.
This complementary column recipe uses literal ink, with no edge interpolation.
"""
    if (gray.dtype != np.uint8 or gray.ndim != 2 or gray.size > 6000000 or max(gray.shape) > 3000
            or excluded.shape != gray.shape or excluded.dtype != bool or threshold not in (220, 235)):
        raise ValueError('Bounded original gray/boolean mask and source threshold required')
    eligible = (gray < threshold) & ~excluded; rows = []
    gray_sha = hashlib.sha256(gray.tobytes()).hexdigest()
    for x in range(gray.shape[1]):
        charge(); yy = np.flatnonzero(eligible[:, x])
        cuts = np.r_[0, np.flatnonzero(np.diff(yy) > 2) + 1, len(yy)]
        for lo, hi in zip(cuts[:-1], cuts[1:]):
            charge(); group = yy[lo:hi]
            if len(group) < 16 or not 16 <= group[-1] - group[0] < 64: continue
            row = {'x': x, 'source_y_interval_pixels': [int(group[0]), int(group[-1])],
                'source_pixels': [{'x': x, 'y': int(y), 'gray': int(gray[y, x])} for y in group],
                'unsupported_row_intervals': [[int(a+1), int(b)] for a, b in zip(group[:-1], group[1:]) if b > a+1],
                'source_gaps_filled': False, 'physical_fascia_role_verified': False}
            row['id'] = digest([VERSION, threshold, gray_sha, row]); rows.append(row)
            if len(rows) > 2048: raise OverflowError('source_fascia_column_budget')
    return rows


def source_cap_variants(topology, candidate):
    """Only exact original cap junctions can bound a patch; no gap repair."""
    lines = {r['source_component_id']: r for r in topology['lines']}
    ridge = np.array(lines[candidate['ridge_source_id']]['source_endpoints_pdf_native'])
    axis = (ridge[1]-ridge[0]) / np.linalg.norm(ridge[1]-ridge[0]); normal = np.array([-axis[1], axis[0]])
    choices = []
    for junction in sorted(candidate['source_junctions'], key=lambda j: j['ridge_endpoint_index']):
        for rail in candidate['rail_source_ids']:
            contact = next(c for c in junction['rail_contacts'] if c['rail_source_id'] == rail)
            choices.append([a for a in contact['alternatives'] if max(a['ridge_to_cap_gap_pdf_points'], a['cap_to_rail_gap_pdf_points']) <= 1e-6])
    if len(choices) != 4 or any(not q for q in choices): return []
    if math.prod(map(len, choices)) > 64: raise OverflowError('source_cap_junction_combination_budget')
    result = []
    for entries in product(*choices):
        points = np.array([entries[0]['cap_endpoint_pdf_native'], entries[2]['cap_endpoint_pdf_native'],
            ridge[0], ridge[1], entries[1]['cap_endpoint_pdf_native'], entries[3]['cap_endpoint_pdf_native']])
        unit = topology['nominal_metres_per_pdf_point']; local = np.c_[(points-ridge[0]) @ axis, (points-ridge[0]) @ normal] * unit
        row = {'source_vertices_pdf_native': points.tolist(), 'local_horizontal_vertices_nominal_m': local.tolist(),
            'source_cap_contacts': list(entries),
            'native_runs_m': [abs(float(local[0,1])), abs(float(local[4,1]))],
            'source_rail_tails_left_unmeshed': candidate['source_rail_tails']}
        row['id'] = digest([VERSION, row]); result.append(row)
    return result


def endcap_checks(pair, caps, source_cap, mpp, charge):
    """All cap columns near both projected corners, including failed pair checks."""
    result = []
    x, y = pair['inferred_ridge_pixel']
    for orientation in (1, -1):
        runs = source_cap['native_runs_m'][::orientation]
        predicted = [[x-runs[0]/mpp, y+math.tan(math.radians(pair['left_pitch_degrees']))*runs[0]/mpp],
            [x+runs[1]/mpp, y+math.tan(math.radians(pair['right_pitch_degrees']))*runs[1]/mpp]]
        sides = []
        for point in predicted:
            side = []
            for cap in caps:
                charge(); errors = [cap['x']-point[0], cap['source_y_interval_pixels'][0]-point[1]]
                # Bounded local witnesses are indexed by horizontal position;
                # retain vertical failures, rather than selecting nearest y.
                if abs(errors[0]) <= 4: side.append((cap, errors))
            sides.append(side)
        for left, right in product(*sides):
            charge(); errors = [left[1], right[1]]
            row = {'source_pair_id': pair['id'], 'source_cap_variant_id': source_cap['id'],
                'image_left_to_native_rail_orientation': orientation,
                'source_fascia_column_ids': [left[0]['id'], right[0]['id']],
                'predicted_corner_pixels': predicted, 'source_corner_error_pixels': errors,
                'source_eave_top_pixels': [[q[0]['x'], q[0]['source_y_interval_pixels'][0]] for q in (left, right)],
                'status': 'conditional_source_endcaps_agree' if max(abs(v) for e in errors for v in e) <= 4
                    and abs(pair['left_pitch_degrees']-pair['right_pitch_degrees']) <= 2 else 'source_endcap_check_held',
                'source_points_moved': False, 'physical_eave_role_verified': False}
            row['id'] = digest([VERSION, row]); result.append(row)
            if len(result) > 4096: raise OverflowError('source_endcap_comparison_budget')
    return result


def patch_mesh(source_cap, pair, check, level_pixel, mpp):
    if check['status'] != 'conditional_source_endcaps_agree': raise ValueError('Source endcap agreement required')
    ridge = (level_pixel-pair['inferred_ridge_pixel'][1])*mpp
    image_eaves = [(level_pixel-p[1])*mpp for p in check['source_eave_top_pixels']]
    eaves = image_eaves[::check['image_left_to_native_rail_orientation']]
    if min(ridge-e for e in eaves) <= 0: raise ValueError('Positive source roof rises required')
    xy = source_cap['local_horizontal_vertices_nominal_m']
    vertices = [[*point, height] for point, height in zip(xy, [eaves[0], eaves[0], ridge, ridge, eaves[1], eaves[1]])]
    return {'vertices': vertices, 'triangles': [[0, 1, 3], [0, 3, 2], [2, 3, 5], [2, 5, 4]],
        'coordinate_frame': 'unplaced source-native nominal horizontal metres; z relative to selected printed level marker',
        'source_cap_variant_id': source_cap['id'], 'source_plan_vertices_moved': False,
        'ridge_height_above_printed_level_nominal_m': ridge,
        'eave_endcap_heights_above_printed_level_nominal_m': eaves,
        'continuous_roof_planes_assumed': True, 'source_cap_patch_only': True,
        'whole_source_rail_tails_left_unmeshed': source_cap['source_rail_tails_left_unmeshed'],
        'complete_wing_mesh': False, 'physical_roof_roles_verified': False, 'world_placement_eligible': False}
