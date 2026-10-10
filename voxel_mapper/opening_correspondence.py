"""Compare located native gaps with reviewed traces, without accepting identity."""
import math
import numpy as np

VERSION = 'reviewed-opening-correspondence-v1'


def compare(gaps, openings, native_matrix, layout_inverse, unit, sampling_bound, tolerance=.25):
    if len(gaps) > 4000 or len(openings) > 100:
        raise ValueError('Opening comparison budget exceeded')
    layout = np.asarray(layout_inverse, dtype=float)
    if layout.shape != (2, 2) or not np.isfinite(layout).all() or np.linalg.det(layout) <= 0:
        raise ValueError('Finite orientation-preserving layout matrix required')
    if not all(math.isfinite(x) and x > 0 for x in (unit, sampling_bound, tolerance)) or tolerance > 1:
        raise ValueError('Finite positive bounded comparison inputs required')
    # pymupdf row convention: x*a+y*c+e, x*b+y*d+f.
    a, b, c, d, e, f = native_matrix
    if not all(math.isfinite(x) for x in native_matrix):
        raise ValueError('Finite native coordinate matrix required')
    if a * d - b * c == 0:
        raise ValueError('Invertible native coordinate matrix required')
    results = []
    for gap in gaps:
        if gap['coordinate_frame'] != 'unrotated_mupdf_points_y_down':
            raise ValueError('Unsupported source coordinate frame')
        points = np.asarray(gap['projected_gap_endpoints'], dtype=float)
        if points.shape != (2, 2) or not np.isfinite(points).all():
            raise ValueError('Finite endpoint pair required')
        native = points @ np.array([[a, b], [c, d]]) + [e, f]
        corrected = native @ layout * unit
        matches = []
        for opening in openings:
            target = np.asarray(opening['raw_native_endpoints'], dtype=float)
            if target.shape != (2, 2) or not np.isfinite(target).all():
                raise ValueError('Finite reviewed endpoint pair required')
            residual = min(float(np.max(np.linalg.norm(native - target[::order], axis=1))) * unit for order in (1, -1))
            if residual <= tolerance:
                matches.append({'reviewed_opening_id': opening['id'], 'maximum_endpoint_residual_nominal_m': residual,
                                'within_manual_endpoint_sampling_bound': residual <= sampling_bound,
                                'physical_correspondence_verified': False})
        results.append({'fill_candidate_id': gap['fill_candidate_id'],
                        'source_gap_endpoints_native': native.tolist(),
                        'raw_nominal_width_m': gap['nominal_gap_width_m'],
                        'layout_normalized_width_m': float(np.linalg.norm(corrected[1] - corrected[0])),
                        'reviewed_trace_candidates': matches,
                        'status': 'ambiguous_reviewed_traces' if len(matches) > 1 else 'unverified_reviewed_trace_candidate' if matches else 'no_reviewed_trace_match',
                        'layout_correction_is_provisional': True, 'physical_opening_verified': False,
                        'world_geometry_additions': 0})
    return results


def cap_corner_options(endcaps, opening, native_matrix, unit, sampling_bound):
    """Retain every source cap-corner pairing; do not select a physical wall face."""
    if len(endcaps) != 2:
        raise ValueError('Two source endcaps required')
    if not all(math.isfinite(x) and x > 0 for x in (unit, sampling_bound)):
        raise ValueError('Finite positive corner comparison scale and bound required')
    a, b, c, d, e, f = native_matrix
    if not all(math.isfinite(x) for x in native_matrix) or a*d-b*c == 0:
        raise ValueError('Finite invertible native coordinate matrix required')
    caps = [np.asarray(cap['source_endpoints'], dtype=float) @ np.array([[a, b], [c, d]]) + [e, f] for cap in endcaps]
    target = np.asarray(opening['raw_native_endpoints'], dtype=float)
    if target.shape != (2, 2) or any(cap.shape != (2, 2) for cap in caps) or not np.isfinite(target).all() or any(not np.isfinite(cap).all() for cap in caps):
        raise ValueError('Finite source corner pairs required')
    result = []
    for order in (1, -1):
        for left in range(2):
            for right in range(2):
                points = np.array([caps[0][left], caps[1][right]])
                residual = float(np.max(np.linalg.norm(points-target[::order], axis=1))) * unit
                result.append({'cap_corner_indices': [left, right], 'reviewed_endpoint_order': order,
                               'native_source_points': points.tolist(), 'maximum_residual_nominal_m': residual,
                               'within_manual_endpoint_sampling_bound': residual <= sampling_bound,
                               'physical_wall_face_identity_verified': False})
    return result


def nearby_plan_segments(edges, corridor_geometry, unit, native_matrix, layout_inverse):
    """Retain nearby short source strokes; a door-leaf or reveal role is unverified."""
    from shapely.geometry import LineString, shape
    if len(edges)>20000 or not math.isfinite(unit) or unit<=0:
        raise ValueError('Bounded edges and finite positive scale required')
    corridor=shape(corridor_geometry)
    if corridor.is_empty or not corridor.is_valid or corridor.geom_type!='Polygon':
        raise ValueError('Valid source gap corridor required')
    a,b,c,d,e,f=native_matrix;layout=np.asarray(layout_inverse,dtype=float)
    if not all(math.isfinite(v) for v in native_matrix) or layout.shape!=(2,2) or not np.isfinite(layout).all() or np.linalg.det(layout)<=0:
        raise ValueError('Finite native and layout matrices required')
    result=[]
    for edge in edges:
        points=np.asarray(edge['points'],dtype=float)
        if points.shape!=(2,2) or not np.isfinite(points).all():raise ValueError('Finite source edge pair required')
        line=LineString(points);width=line.length*unit;distance=line.distance(corridor)*unit
        if not .5<=width<=1.2 or distance>.25:continue
        native=points@np.array([[a,b],[c,d]])+[e,f];normalized=native@layout*unit
        result.append({'source_edge':edge,'nominal_length_m':width,'nominal_distance_to_gap_corridor_m':distance,
                       'layout_normalized_length_m':float(np.linalg.norm(normalized[1]-normalized[0])),
                       'door_leaf_or_reveal_role_verified':False,'world_geometry_additions':0})
        if len(result)>500:raise ValueError('Nearby stroke result budget exceeded')
    return sorted(result,key=lambda r:r['source_edge']['id'])
