"""Unseeded plan endcaps and nominal-width links; never opening identity."""
import math

import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import LineString, shape, mapping

from . import clipped_plan_fills, fill_endcaps
from .drawing_page_tools import native_inverse
from .reconstruction_evidence_queue import digest

VERSION = 'automatic-plan-opening-links-v1'
TOLERANCE_M = .25


def affine(matrix):
    return [matrix.a, matrix.c, matrix.b, matrix.d, matrix.e, matrix.f]


def bounded_work(max_checks):
    if type(max_checks) is not int or not 1 <= max_checks <= 100000:
        raise ValueError('Bounded opening-link work required')


def plan_gaps(page, view, *, max_checks=100000):
    """Recover whole-page source fills, then retain whole gaps in this view.

    Outside/crossing fills still enter the original overlap test. Filtering fills
    before endcap recovery would erase blockers and change the source recipe.
    """
    bounded_work(max_checks)
    result = {'version': VERSION, 'status': 'not_a_floor_plan', 'gaps': [],
              'page_fill_recovery': None, 'page_endcap_recovery': None,
              'withheld_scope_gap_ids': [], 'physical_opening_verified': False,
              'world_geometry_additions': 0}
    claim = view['printed_claim']
    if claim['view_kind'] != 'plan' or claim.get('plan_level_or_form') == 'roof': return result
    factor = view['nominal_metres_per_pdf_point']
    if factor is None:
        return {**result, 'status': 'nominal_view_scale_required'}
    if type(factor) not in (int, float) or not math.isfinite(factor) or not 0 < factor <= 10000*.0254/72:
        raise ValueError('Bounded nominal source scale required')
    if page is None: return {**result, 'status': 'original_source_page_required'}
    if page.number+1 != view['page']: raise ValueError('Matching original source page required')
    matrix = native_inverse(page); scope = shape(view['geometry'])
    try:
        fills = clipped_plan_fills.recover(page, view['document_sha256'], view['page'])
        endcaps = fill_endcaps.recover(fills['candidates'], factor, max_checks=max_checks)
    except ValueError as error:
        if 'budget exceeded' not in str(error): raise
        return {**result, 'status': 'plan_gap_budget_withheld', 'reason': str(error)}
    result.update(page_fill_recovery=fills, page_endcap_recovery=endcaps,
                  unrotated_mupdf_to_pdf_native_matrix=list(matrix))
    whole = {c['id'] for c in fills['candidates']
             if scope.covers(affine_transform(shape(c['geometry']), affine(matrix)))}
    for gap in endcaps['gaps']:
        corridor = affine_transform(shape(gap['gap_corridor_geometry']), affine(matrix))
        if not set(gap['parent_fill_candidate_ids']) <= whole or not scope.covers(corridor):
            result['withheld_scope_gap_ids'].append(gap['id']); continue
        endpoints = [list(pymupdf.Point(p)*matrix) for p in gap['projected_gap_endpoints']]
        result['gaps'].append({'id': gap['id'], 'source_gap_sha256': digest(gap),
            'geometry_pdf_native': mapping(corridor), 'gap_endpoints_pdf_native': endpoints,
            'nominal_gap_width_m': gap['nominal_gap_width_m'],
            'nominal_endpoint_distance_m': LineString(endpoints).length*factor,
            'source_fill_overlap_present': bool(gap['intersecting_fill_candidates']),
            'physical_opening_verified': False, 'opening_type': None})
    result['status'] = 'whole_view_source_endcap_gaps_only'
    return result


def compare(inventories, *, max_checks=100000):
    """Compare every scoped plan gap with every retained residual family.

    The same area is only a search domain, never a building/view association.
    No position, facing direction, height, state or layout correction is inferred.
    """
    bounded_work(max_checks)
    if len(inventories) > 32 or len({v['view_id'] for v in inventories}) != len(inventories):
        raise ValueError('Bounded unique view inventories required')
    base = {'version': VERSION, 'status': 'nominal_width_links_only', 'matches': [],
        'plan_gaps': [], 'plan_views': [], 'elevation_views': [], 'checks': 0,
        'recipe': {'nominal_width_tolerance_m': TOLERANCE_M,
                   'elevation_search_scope': 'residual_jamb_groups_only',
                   'plan_width_basis': 'source_endcap_axis_projection',
                   'elevation_width_basis': 'first_threshold_family_pixel_edges',
                   'max_checks': max_checks},
        'building_identity_verified': False, 'view_association_verified': False,
        'physical_opening_verified': False, 'world_geometry_additions': 0,
        'training_labels_generated': 0}
    gaps = []; families = []; seen = set()
    for view in sorted(inventories, key=lambda v: v['view_id']):
        pin = digest(view)
        if view['printed_claim']['view_kind'] == 'plan' and view['printed_claim'].get('plan_level_or_form') != 'roof':
            base['plan_views'].append({'view_id': view['view_id'], 'source_inventory_sha256': pin,
                                       'gap_status': view['plan_gap_review']['status']})
        for gap in view['plan_gap_review']['gaps']:
            key = (view['view_id'], gap['id'])
            if key in seen: raise ValueError('Unique source gaps required')
            seen.add(key)
            width = gap['nominal_gap_width_m']
            if type(width) not in (int, float) or not math.isfinite(width) or width <= 0:
                raise ValueError('Finite positive nominal gap width required')
            gaps.append((view, pin, gap))
        if view['printed_claim']['view_kind'] != 'elevation': continue
        scan = view['residual_raster_scan']; scale = view['nominal_metres_per_pdf_point']
        status = 'source_scan_withheld' if scan.get('index') is None else 'nominal_view_scale_required' if scale is None else 'retained_residual_families_only'
        base['elevation_views'].append({'view_id': view['view_id'], 'status': status,
            'source_inventory_sha256': pin, 'scan_status': scan['status']})
        if status != 'retained_residual_families_only': continue
        matrix = pymupdf.Matrix(view['raster_coordinate_receipt']['pixel_edge_to_pdf_native_matrix'])
        step = math.hypot(matrix.a, matrix.b)*scale
        if not math.isfinite(step) or step <= 0: raise ValueError('Finite positive source pixel scale required')
        for hypothesis in view['residual_raster_hypotheses']:
            if hypothesis['status'] == 'candidate_scope_crossing_withheld': continue
            index = hypothesis['consensus_family_index']; family = scan['index']['consensus_families'][index]
            width = (family['bounds_pixels'][2]-family['bounds_pixels'][0])*step
            families.append((view, pin, hypothesis, width))
    if len(gaps) > 4000 or len(families) > 8192:
        return {**base, 'status': 'opening_link_budget_withheld', 'reason': 'source_inventory_budget'}
    matches = []; summaries = []
    for plan, plan_pin, gap in gaps:
        identities = []; incompatible = []
        for elevation, elevation_pin, family, width in families:
            base['checks'] += 1
            if base['checks'] > max_checks:
                return {**base, 'status': 'opening_link_budget_withheld', 'reason': 'pair_comparison_budget',
                        'matches': [], 'plan_gaps': []}
            # Conflicting explicit states are not comparable. Unspecified states
            # remain possible, with an explicit unresolved-state flag on the link.
            states = [v['printed_claim'].get('printed_state', 'unspecified') for v in (plan, elevation)]
            if all(s != 'unspecified' for s in states) and states[0] != states[1]:
                incompatible.append(elevation['view_id']); continue
            residual = width-gap['nominal_gap_width_m']
            if abs(residual) > TOLERANCE_M: continue
            link = {'plan_view_id': plan['view_id'], 'source_gap_id': gap['id'],
                'plan_inventory_sha256': plan_pin, 'elevation_view_id': elevation['view_id'],
                'elevation_inventory_sha256': elevation_pin, 'residual_family_id': family['id'],
                'consensus_family_index': family['consensus_family_index'],
                'plan_nominal_width_m': gap['nominal_gap_width_m'], 'elevation_nominal_width_m': width,
                'elevation_minus_plan_width_m': residual, 'source_fill_overlap_present': gap['source_fill_overlap_present'],
                'construction_state_unresolved': 'unspecified' in states,
                'physical_correspondence_verified': False, 'position_alignment_verified': False}
            link['id'] = digest([VERSION, link]); identities.append(link['id']); matches.append(link)
        summaries.append({'plan_view_id': plan['view_id'], 'source_gap_id': gap['id'],
            'match_ids': identities, 'explicit_state_conflict_view_ids': sorted(set(incompatible)),
            'status': 'multiple_nominal_width_alternatives' if len(identities)>1 else
                      'single_nominal_width_alternative' if identities else 'no_retained_nominal_width_match',
            'physical_opening_verified': False})
    base.update(matches=matches, plan_gaps=summaries,
        counts={'source_plan_gaps': len(gaps), 'scoped_residual_families': len(families),
                'nominal_width_links': len(matches),
                'linked_residual_families': len({m['residual_family_id'] for m in matches}),
                'unmatched_plan_gaps': sum(not r['match_ids'] for r in summaries)})
    return base
