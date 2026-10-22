"""Target-blind original roof-line junctions and conditional relative positions.

Candidates are drawing topology, including hatching, not classified roofs. All
original endpoints survive; interior cap junctions never trim source rail tails.
"""
from itertools import combinations, product
import json
import math
from pathlib import Path
import tempfile

import numpy as np
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from . import source_gradient_gables as gradient
from .automatic_opening_links import bounded_work
from .generation_cycles import atomic_json, file_hash
from .reconstruction_evidence_queue import digest

VERSION = 'roof-source-topology-v1'
JUNCTION_PDF = .25


def native_lines(inventory, charge):
    """All whole supported two-point strokes, before inspecting any elevation."""
    unit = inventory['nominal_metres_per_pdf_point']
    if not math.isfinite(unit) or unit <= 0:
        raise ValueError('Finite positive nominal plan scale required')
    if len(inventory['source_components']) > 4096:
        raise OverflowError('roof_topology_source_budget')
    rows = []
    for c in inventory['source_components']:
        charge(); g = c['geometry']
        if (g['type'] != 'LineString' or len(g['coordinates']) != 2
                or c['rendering_status'] != 'supported_straight_unclipped_polyline'
                or c['curve_approximation']['cubic_segments']):
            continue
        p = np.asarray(g['coordinates'], float)
        if not np.isfinite(p).all():
            raise ValueError('Finite original source endpoints required')
        length = float(np.linalg.norm(p[1] - p[0]))
        if length * unit < 1:
            continue
        rows.append({'source_component_id': c['id'], 'source_component_sha256': digest(c),
            'source_endpoints_pdf_native': g['coordinates'], 'nominal_length_m': length * unit,
            'unit_vector': ((p[1] - p[0]) / length).tolist()})
    rows.sort(key=lambda r: r['source_component_id'])
    if len({r['source_component_id'] for r in rows}) != len(rows):
        raise ValueError('Unique source component identities required')
    return rows


def connected_candidates(inventory, charge):
    """Retain every cap-connected rail triple, with junction gaps and tails.

Caps can be whole crossbars or half crossbars. Their original endpoints must
meet a parallel rail, and their original segment must reach a ridge endpoint.
The far cap may meet a rail interior: that rail remains whole in the receipt.
"""
    rows = native_lines(inventory, charge)
    unit = inventory['nominal_metres_per_pdf_point']
    if not rows:
        return {'view_id': inventory['view_id'], 'lines': [], 'candidates': []}
    points = [np.asarray(r['source_endpoints_pdf_native']) for r in rows]
    vectors = [np.asarray(r['unit_vector']) for r in rows]
    shapes = [LineString(p) for p in points]; tree = STRtree(shapes)
    result = []
    for ri, ridge in enumerate(rows):
        charge()
        if ridge['nominal_length_m'] < 2:
            continue
        axis = vectors[ri]; normal = np.array([-axis[1], axis[0]])
        ends = []
        for endpoint in points[ri]:
            contacts = {}
            for ci in sorted(tree.query(Point(endpoint), predicate='dwithin', distance=JUNCTION_PDF).tolist()):
                charge()
                if abs(axis @ vectors[ci]) > math.sin(math.radians(5)):
                    continue
                for cap_end_index, corner in enumerate(points[ci]):
                    charge(); signed_run = float((corner - endpoint) @ normal) * unit
                    if abs(signed_run) < 1:
                        continue
                    for ei in sorted(tree.query(Point(corner), predicate='dwithin', distance=JUNCTION_PDF).tolist()):
                        charge()
                        if ei == ri or abs(axis @ vectors[ei]) < math.cos(math.radians(5)):
                            continue
                        receipt = {'cap_source_id': rows[ci]['source_component_id'],
                            'cap_endpoint_index': cap_end_index, 'cap_endpoint_pdf_native': corner.tolist(),
                            'ridge_to_cap_gap_pdf_points': shapes[ci].distance(Point(endpoint)),
                            'cap_to_rail_gap_pdf_points': shapes[ei].distance(Point(corner)),
                            'rail_station_fraction': shapes[ei].project(Point(corner), normalized=True),
                            'signed_run_nominal_m': signed_run}
                        contacts.setdefault(ei, []).append(receipt)
            ends.append(contacts)
        # At least one cap must reach an original rail endpoint. A hatch ending
        # at the interior of two much longer strokes is insufficient by itself.
        common = sorted(i for i in set(ends[0]) & set(ends[1]) if any(
            min(np.linalg.norm(np.asarray(c['cap_endpoint_pdf_native']) - p) for p in points[i]) <= JUNCTION_PDF
            for end in ends for c in end[i]))
        for ai, bi in combinations(common, 2):
            charge()
            offsets = [float((points[i][0] - points[ri][0]) @ normal) * unit for i in (ai, bi)]
            if offsets[0] * offsets[1] >= 0 or not 2 <= abs(offsets[0] - offsets[1]) <= 40:
                continue
            # Explicit bounded, near-balanced gable-template hypothesis. Values
            # are retained individually, never averaged or made symmetric.
            if abs(abs(offsets[0]) - abs(offsets[1])) > .25:
                continue
            ordered = sorted((ai, bi), key=lambda i: float((points[i][0] - points[ri][0]) @ normal))
            junctions = []
            for end_index in (0, 1):
                junctions.append({'ridge_endpoint_index': end_index,
                    'rail_contacts': [{'rail_source_id': rows[i]['source_component_id'],
                        'alternatives': ends[end_index][i]} for i in ordered]})
            tails = []
            for i in ordered:
                interval = sorted((points[i] @ axis).tolist())
                stations = sorted((points[ri] @ axis).tolist())
                tails.append({'rail_source_id': rows[i]['source_component_id'],
                    'nominal_source_tails_m': [max(0., stations[0] - interval[0]) * unit,
                        max(0., interval[1] - stations[1]) * unit],
                    'source_trimmed': False})
            row = {'ridge_source_id': ridge['source_component_id'],
                'rail_source_ids': [rows[i]['source_component_id'] for i in ordered],
                'source_junctions': junctions, 'source_rail_tails': tails,
                'nominal_ridge_length_m': ridge['nominal_length_m'],
                'nominal_rail_lengths_m': [rows[i]['nominal_length_m'] for i in ordered],
                'nominal_runs_m': sorted(abs(v) for v in offsets),
                'near_balanced_gable_template_assumed': True,
                'status': 'source_connected_unclassified_line_triple',
                'physical_roof_roles_verified': False, 'source_points_moved': False,
                'complete_roof_mesh': None}
            row['id'] = digest([VERSION, inventory['view_id'], row]); result.append(row)
            if len(result) > 256:
                raise OverflowError('roof_topology_candidate_budget')
    return {'view_id': inventory['view_id'], 'document_sha256': inventory['document_sha256'],
        'page': inventory['page'], 'nominal_metres_per_pdf_point': unit,
        'lines': rows, 'candidates': result}


def relative_positions(topologies, source_gradient, gable, profile, charge):
    """Compare original ridge endpoints using both main-roof end anchors/signs.

No fitted translation, residual-ranked candidate, averaged anchor, or overridden
local source hold. A position agreement is not a physical correspondence.
"""
    results = []
    profiles = {p['view_id']: p for p in profile['profiles']}
    plans = {p['source_view_id']: p for p in gable['plan_reviews']}
    for context in source_gradient['projection_contexts']:
        plan = plans.get(context['roof_view_id']); group = profiles.get(context['elevation_view_id'])
        if not plan or not group:
            continue
        axis = np.asarray(context['source_view_horizontal_axis_in_roof_pdf'])
        # Existing profile is along the main roof; only a parallel source frame
        # supports this one-dimensional end alignment.
        source_axis = np.asarray(plan['source_axis_pdf_native'])
        if abs(axis @ source_axis) < math.cos(math.radians(.1)):
            continue
        source_row = next(r for r in source_gradient['views'] if r['view_id'] == group['view_id'])
        topology = next(t for t in topologies if t['view_id'] == context['roof_view_id'])
        lines = {l['source_component_id']: l for l in topology['lines']}
        unit = topology['nominal_metres_per_pdf_point']
        # Every original parent plan triple line is retained as an anchor witness.
        spans = {}
        for variant in group['variants']:
            spans.setdefault(tuple(variant['source_upper_span_pixels']), []).append(variant['threshold'])
        for span, thresholds in sorted(spans.items()):
            mpp = group['nominal_metres_per_source_pixel']
            for anchor in plan['lines']:
                stations = anchor['along_interval_nominal_m']
                for scan in source_row['variants']:
                    for parent in scan['anchor_reviews']:
                        for pair in parent['pairs']:
                            if pair['status'] != 'conditional_partial_gable_source_support':
                                continue
                            for candidate in topology['candidates']:
                                ridge = lines[candidate['ridge_source_id']]
                                for endpoint_index, point in enumerate(ridge['source_endpoints_pdf_native']):
                                    station = float(np.asarray(point) @ source_axis) * unit
                                    for sign, end_index in product((1, -1), (0, 1)):
                                        charge(); origin = stations[end_index if sign == 1 else 1 - end_index]
                                        predicted = origin + sign * (pair['inferred_ridge_pixel'][0] - span[end_index]) * mpp
                                        error = station - predicted
                                        row = {'context_id': context['id'], 'candidate_id': candidate['id'],
                                            'source_pair_id': pair['id'], 'source_pair_status': pair['status'],
                                            'profile_thresholds_with_identical_original_span': thresholds,
                                            'anchor_source_component_id': anchor['source_component_id'],
                                            'anchor_source_pixel': span[end_index], 'anchor_plan_station_nominal_m': origin,
                                            'source_axis_sign_hypothesis': sign, 'ridge_endpoint_index': endpoint_index,
                                            'ridge_endpoint_plan_station_nominal_m': station,
                                            'predicted_plan_station_nominal_m': predicted,
                                            'signed_position_error_nominal_m': error,
                                            'status': 'relative_source_position_agrees' if abs(error) <= .25 else 'relative_source_position_disagrees',
                                            'physical_correspondence_verified': False, 'source_translation_refitted': False}
                                        row['id'] = digest([VERSION, row]); results.append(row)
    return results


def build(source_gradient, source_partial, gable, profile, preview, components, views, corpus, output, *, max_checks=100000):
    bounded_work(max_checks)
    source_gradient, source_partial, gable, profile, preview, components, views, corpus, output = map(Path,
        (source_gradient, source_partial, gable, profile, preview, components, views, corpus, output))
    path = source_gradient / 'source-gradient-gables.json'; source_sha = file_hash(path)
    previous = json.loads(path.read_text())
    with tempfile.TemporaryDirectory() as temp:
        fresh = gradient.build(source_partial, gable, profile, preview, components, views, corpus, temp,
            max_checks=previous['contract']['max_checks']); fresh.pop('directory')
        if digest(fresh) != digest(previous):
            raise ValueError('Original grayscale source replay changed')
    if previous['status'] != 'source_gradient_gable_and_plan_direction_review_only':
        raise ValueError('Complete source gradient review required')
    parent_contract = previous['contract']['source_partial_contract']
    gable_contract = parent_contract['source_gable_contract']
    pins = [(gable / 'gable-roof-review.json', parent_contract['source_gable_review_sha256']),
        (profile / 'facade-profile.json', gable_contract['source_profile_sha256']),
        (components / 'component-report.json', gable_contract['component_report_sha256']),
        (views / 'view-report.json', gable_contract['view_report_sha256'])]
    for source, pin in pins:
        if file_hash(source) != pin:
            raise ValueError('Original topology input changed after source replay')
    contract = {'version': VERSION, 'implementation_sha256': file_hash(Path(__file__)),
        'source_gradient_sha256': source_sha, 'max_checks': max_checks,
        'source_input_sha256': {p.name: pin for p, pin in pins},
        'junction_tolerance_pdf_points': JUNCTION_PDF, 'position_tolerance_nominal_m': .25}
    result = {'contract': contract, 'status': 'roof_source_topology_review_only', 'checks': 0,
        'topologies': [], 'position_checks': [], 'new_roof_models': [],
        'accepted_physical_components': 0, 'world_blocks': 0, 'training_labels': 0,
        'prior_source_holds_overridden': False, 'parent_models_changed': False,
        'unresolved': ['Physical roof/building identity and label correspondence',
            'Hatching versus roof role, source tails, eave heights and full depth',
            'Independent second-view edge support, complete geometry and park registration']}
    def charge():
        result['checks'] += 1
        if result['checks'] > max_checks:
            raise OverflowError('roof_topology_work_budget')
    try:
        report = json.loads((components / 'component-report.json').read_text())
        for record in report['results']:
            inventory = json.loads((components / record['file']).read_text())
            if inventory['printed_claim'].get('plan_level_or_form') == 'roof':
                result['topologies'].append(connected_candidates(inventory, charge))
        result['position_checks'] = relative_positions(result['topologies'], previous,
            json.loads((gable / 'gable-roof-review.json').read_text()),
            json.loads((profile / 'facade-profile.json').read_text()), charge)
    except OverflowError as error:
        result.update(status='roof_source_topology_budget_withheld', reason=str(error), topologies=[], position_checks=[])
    if file_hash(path) != source_sha:
        raise ValueError('Original grayscale source changed during topology build')
    gradient.roof.automatic_facade_preview._verified_inputs(components, views, corpus)
    for source, pin in pins:
        if file_hash(source) != pin:
            raise ValueError('Original topology input changed during build')
    result['counts'] = {'original_plan_lines': sum(len(t['lines']) for t in result['topologies']),
        'source_connected_candidates': sum(len(t['candidates']) for t in result['topologies']),
        'relative_position_checks': len(result['position_checks']),
        'relative_position_agreements': sum(c['status'] == 'relative_source_position_agrees' for c in result['position_checks']),
        'new_roof_models': 0}
    if len(json.dumps(result).encode()) > 32000000:
        raise ValueError('Roof topology output budget exceeded')
    root = output / digest(contract); target = root / 'roof-source-topology.json'
    if target.exists():
        if digest(json.loads(target.read_text())) != digest(result):
            raise ValueError('Saved roof topology review changed')
    else:
        atomic_json(target, result)
    return {**result, 'directory': str(root)}
