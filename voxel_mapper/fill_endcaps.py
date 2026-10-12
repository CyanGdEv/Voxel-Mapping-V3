"""Bounded facing-endcap hypotheses from exact filled polygon boundaries."""
import hashlib
import json
import math
from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.strtree import STRtree

VERSION = 'exact-fill-endcap-pairs-v1'


def recover(candidates, unit, maximum_gap_m=8):
    if not math.isfinite(unit) or unit <= 0 or not 0 < maximum_gap_m <= 10:
        raise ValueError('Finite positive scale and bounded gap search required')
    if len(candidates) > 4000:
        raise ValueError('Endcap fill budget exceeded')
    if len({c['id'] for c in candidates}) != len(candidates):
        raise ValueError('Duplicate fill identity')
    candidates = sorted(candidates, key=lambda c: c['id'])
    caps = []; vertices = 0
    geometries = [shape(c['geometry']) for c in candidates]
    if any(g.is_empty or not g.is_valid or g.geom_type not in ('Polygon', 'MultiPolygon') for g in geometries):
        raise ValueError('Valid filled polygons required')
    for index, (candidate, g) in enumerate(zip(candidates, geometries)):
        if list(candidate['fill_color']) == [1, 1, 1]:
            continue
        parts = list(g.geoms) if g.geom_type == 'MultiPolygon' else [g] if g.geom_type == 'Polygon' else []
        for part_index, part in enumerate(parts):
            points = list(part.exterior.coords)
            vertices += len(points)
            if vertices > 500000:
                raise ValueError('Endcap vertex inspection budget exceeded')
            for edge_index, (a, b) in enumerate(zip(points, points[1:])):
                length = math.dist(a, b)
                if not .08 <= length * unit <= 1:
                    continue
                tangent = ((b[0]-a[0])/length, (b[1]-a[1])/length)
                inward = (-tangent[1], tangent[0]) if part.exterior.is_ccw else (tangent[1], -tangent[0])
                center = ((a[0]+b[0])/2, (a[1]+b[1])/2)
                # Inset only the containment probe to avoid roundoff at the boundary.
                # Source caps and output corridor vertices remain exact.
                ray = LineString([(center[0]+inward[0]*1e-7, center[1]+inward[1]*1e-7),
                                  (center[0]+inward[0]*length, center[1]+inward[1]*length)])
                if not part.covers(ray):
                    continue
                caps.append({'candidate_index': index, 'fill_candidate_id': candidate['id'], 'polygon_part': part_index,
                             'boundary_edge_index': edge_index, 'source_endpoints': [list(a), list(b)],
                             'center': center, 'inward': inward, 'length': length, 'inward_support_geometry': mapping(ray)})
                if len(caps) > 10000:
                    raise ValueError('Endcap boundary budget exceeded')
    tree = STRtree([Point(c['center']) for c in caps]); result = []; comparisons = 0
    fill_tree = STRtree(geometries)
    for i, left in enumerate(caps):
        for j in sorted(tree.query(Point(left['center']).buffer(maximum_gap_m/unit)).tolist()):
            if j <= i:
                continue
            comparisons += 1
            if comparisons > 100000:
                raise ValueError('Endcap comparison budget exceeded')
            right = caps[j]; lc = candidates[left['candidate_index']]; rc = candidates[right['candidate_index']]
            if lc['fill_color'] != rc['fill_color'] or (left['candidate_index'], left['polygon_part']) == (right['candidate_index'], right['polygon_part']):
                continue
            axis = (-left['inward'][0], -left['inward'][1]); normal = (-axis[1], axis[0])
            dot = axis[0]*right['inward'][0]+axis[1]*right['inward'][1]
            delta = (right['center'][0]-left['center'][0], right['center'][1]-left['center'][1])
            gap = delta[0]*axis[0]+delta[1]*axis[1]
            offset = abs(delta[0]*normal[0]+delta[1]*normal[1])
            if dot < math.cos(math.radians(.5)) or not .08 <= gap*unit <= maximum_gap_m or offset > 1 or abs(left['length']-right['length']) > 1:
                continue
            # Source cap vertices define the corridor; no source polygons are modified.
            lp = left['source_endpoints']; rp = right['source_endpoints']
            if math.dist(lp[0],rp[0])+math.dist(lp[1],rp[1]) < math.dist(lp[0],rp[1])+math.dist(lp[1],rp[0]):
                rp = rp[::-1]
            corridor = Polygon([lp[0], lp[1], rp[0], rp[1]])
            if not corridor.is_valid or corridor.area <= 0:
                continue
            overlap = []; blocked = False
            for k in sorted(fill_tree.query(corridor).tolist()):
                comparisons += 1
                if comparisons > 100000:
                    raise ValueError('Endcap overlap budget exceeded')
                area = corridor.intersection(geometries[k]).area
                if area <= corridor.area * 1e-9:
                    continue
                overlap.append({'fill_candidate_id': candidates[k]['id'], 'gap_area_fraction': area/corridor.area})
                if k in (left['candidate_index'], right['candidate_index']):
                    blocked = True
            if blocked:
                continue
            parents = [{k:v for k,v in cap.items() if k not in ('candidate_index','center','inward','length')} for cap in (left,right)]
            identity = [VERSION, parents]
            result.append({'id': hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest(),
                           'fill_candidate_id': lc['id'], 'parent_fill_candidate_ids': [lc['id'], rc['id']],
                           'source_endcaps': parents, 'projected_gap_endpoints': [list(left['center']),list(right['center'])],
                           'gap_corridor_geometry': mapping(corridor), 'nominal_gap_width_m': gap*unit,
                           'coordinate_frame': 'unrotated_mupdf_points_y_down', 'intersecting_fill_candidates': overlap,
                           'candidate_recipe': {'minimum_inward_support_cap_widths': 1, 'support_probe_inset_pdf_points': 1e-7,
                                                'maximum_axis_difference_degrees': .5,
                                                'maximum_transverse_offset_pdf_points': 1, 'maximum_cap_width_difference_pdf_points': 1,
                                                'nominal_cap_width_range_m': [.08, 1], 'maximum_gap_m': maximum_gap_m,
                                                'source_overlap_area_fraction_epsilon': 1e-9},
                           'complete_page_visibility_verified': False,
                           'status': 'unverified_facing_fill_endcaps', 'physical_opening_verified': False,
                           'geometry_bridge_added': False, 'world_geometry_additions': 0})
            if len(result) > 4000:
                raise ValueError('Endcap pair output budget exceeded')
    return {'version': VERSION, 'endcaps_examined': len(caps), 'comparisons': comparisons,
            'gaps': result, 'world_geometry_additions': 0}
