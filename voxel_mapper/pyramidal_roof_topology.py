"""Target-blind, exact-endpoint four-spoke roof patterns and boundary overlaps.

These are unclassified source graphs. No endpoint snapping or inferred closure.
"""
from collections import defaultdict
from itertools import combinations, product
import math
import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union
from .reconstruction_evidence_queue import digest

VERSION = 'original-four-spoke-roof-topology-v1'


def discover(topology, charge):
    lines = sorted(topology['lines'],key=lambda l:l['source_component_id']); unit = topology['nominal_metres_per_pdf_point']
    if len(lines) > 4096: raise OverflowError('pyramid_original_line_budget')
    if len({l['source_component_id'] for l in lines})!=len(lines):raise ValueError('Unique original line identities required')
    if not math.isfinite(unit) or unit <= 0: raise ValueError('Positive finite original plan scale required')
    endpoints = defaultdict(list); edges = defaultdict(list)
    for line in lines:
        charge(); points = np.array(line['source_endpoints_pdf_native'], float)
        if points.shape != (2, 2) or not np.isfinite(points).all() or np.linalg.norm(points[1]-points[0]) == 0:
            raise ValueError('Two finite distinct original endpoints required')
        a, b = map(tuple, points.tolist())
        endpoints[a].append((line['source_component_id'], b)); endpoints[b].append((line['source_component_id'], a))
        edges[tuple(sorted((a,b)))].append(line['source_component_id'])
    candidates = []
    for center, spokes in sorted(endpoints.items()):
        charge()
        # Exact duplicate paints share geometry but keep every source identity.
        groups = defaultdict(list)
        for source_id, corner in spokes: groups[corner].append(source_id)
        if len(groups) < 4: continue
        if math.comb(len(groups), 4) > 256: raise OverflowError('pyramid_spoke_combination_budget')
        for corners in combinations(sorted(groups), 4):
            charge(); corners = sorted(corners, key=lambda p: math.atan2(p[1]-center[1], p[0]-center[0]))
            perimeter = [edges.get(tuple(sorted((corners[i], corners[(i+1)%4]))), []) for i in range(4)]
            if any(not e for e in perimeter): continue
            polygon = Polygon(corners)
            if not polygon.is_valid or not polygon.contains(Point(center)): continue
            points = np.array(corners); vectors = np.roll(points,-1,axis=0)-points
            lengths = np.linalg.norm(vectors,axis=1); directions = vectors/lengths[:,None]
            if min(lengths)*unit < 2 or max(lengths)*unit > 40: continue
            if any(abs(float(directions[i] @ directions[(i+1)%4])) > math.sin(math.radians(5)) for i in range(4)): continue
            if any(abs(float(directions[i] @ directions[i+2])) < math.cos(math.radians(5)) for i in (0,1)): continue
            row = {'view_id': topology['view_id'], 'source_apex_pdf_native': list(center),
                'source_corners_pdf_native': [list(p) for p in corners],
                'source_spoke_ids_per_corner': [sorted(groups[p]) for p in corners],
                'source_perimeter_ids_per_edge': [sorted(ids) for ids in perimeter],
                'nominal_edge_lengths_m': (lengths*unit).tolist(),
                'status': 'unclassified_original_four_spoke_closed_perimeter',
                'source_endpoints_snapped': False, 'source_closure_inferred': False,
                'rectangular_pyramid_template_assumed': True, 'physical_roof_roles_verified': False}
            row['id'] = digest([VERSION,row]); candidates.append(row)
            if len(candidates) > 64: raise OverflowError('pyramid_source_candidate_budget')
    return {'view_id': topology['view_id'], 'document_sha256': topology['document_sha256'],
        'page': topology['page'], 'nominal_metres_per_pdf_point': unit,
        'original_lines': lines, 'candidates': candidates}


def junctions(topology, pyramids, supported_candidate_ids, charge):
    """Original shared cap identities and literal rail/perimeter overlap only."""
    lines = {r['source_component_id']: r for r in topology['lines']}; result = []
    unit = topology['nominal_metres_per_pdf_point']
    for low in topology['candidates']:
        if low['id'] not in supported_candidate_ids: continue
        for pyramid in pyramids:
            charge(); perimeter = {source for ids in pyramid['source_perimeter_ids_per_edge'] for source in ids}
            for junction in low['source_junctions']:
                cap_ids = sorted({c['cap_source_id'] for contact in junction['rail_contacts'] for c in contact['alternatives']} & perimeter)
                for cap_id in cap_ids:
                    contacts = [[c for c in contact['alternatives'] if c['cap_source_id'] == cap_id and
                        max(c['ridge_to_cap_gap_pdf_points'],c['cap_to_rail_gap_pdf_points']) <= 1e-6]
                        for contact in junction['rail_contacts']]
                    if len(contacts) != 2 or any(not group for group in contacts): continue
                    for entries in product(*contacts):
                        charge(); tails = []
                        for rail, contact in zip(low['rail_source_ids'], entries):
                            original = lines[rail]['source_endpoints_pdf_native']; cap = contact['cap_endpoint_pdf_native']
                            ridge = lines[low['ridge_source_id']]['source_endpoints_pdf_native']
                            axis = np.array(ridge[1])-ridge[0]; axis /= np.linalg.norm(axis)
                            station = float(np.array(cap)@axis); direction = 1 if junction['ridge_endpoint_index'] == 1 else -1
                            for endpoint_index, end in enumerate(original):
                                if direction*(float(np.array(end)@axis)-station) <= 1e-6: continue
                                segment = LineString([cap,end]); overlaps = []; coverage_shapes=[]
                                for source_id in sorted(perimeter):
                                    charge(); shape = LineString(lines[source_id]['source_endpoints_pdf_native'])
                                    length = segment.intersection(shape).length
                                    if length > 0:
                                        coverage_shapes.append(segment.intersection(shape))
                                        overlaps.append({'source_perimeter_id': source_id,
                                            'coincident_original_interval_nominal_m': length*unit})
                                tails.append({'rail_source_id': rail, 'whole_source_endpoints_pdf_native': original,
                                    'original_cap_endpoint_pdf_native': cap, 'original_rail_endpoint_index': endpoint_index,
                                    'original_tail_endpoint_pdf_native': end, 'source_tail_length_nominal_m': segment.length*unit,
                                    'boundary_overlaps': overlaps, 'whole_rail_trimmed': False,
                                    'unique_boundary_coverage_nominal_m':unary_union(coverage_shapes).length*unit,
                                    'tail_is_complete_boundary_overlap': abs(unary_union(coverage_shapes).length-segment.length)*unit <= 1e-9})
                        row = {'gable_candidate_id': low['id'], 'pyramid_candidate_id': pyramid['id'],
                            'shared_original_cap_source_id': cap_id, 'ridge_endpoint_index': junction['ridge_endpoint_index'],
                            'original_cap_contacts': list(entries), 'rail_tail_relations': tails,
                            'status': 'shared_original_cap_with_boundary_coincident_tails' if len(tails)==2 and all(t['tail_is_complete_boundary_overlap'] for t in tails)
                                else 'shared_original_cap_tail_relation_unresolved',
                            'physical_roof_join_verified': False, 'source_tails_shortened': False,
                            'new_join_mesh': None}
                        row['id'] = digest([VERSION,row]); result.append(row)
                        if len(result)>256: raise OverflowError('pyramid_junction_budget')
    return result
