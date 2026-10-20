"""Independent source extent/origin hypotheses; never fit a facade to an opening."""
from collections import Counter
import math

import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import Point, mapping, shape

from .automatic_opening_links import affine, bounded_work
from .reconstruction_evidence_queue import digest

VERSION = 'automatic-facade-alignment-v1'
TOLERANCE_M = .25
PAINT_NEIGHBOURHOOD_POINTS = .25


def projected_extent(geometry, frame, unit, charge):
    """Project original vertices, retaining both extrema and their provenance."""
    if type(unit) not in (int, float) or not math.isfinite(unit) or unit <= 0:
        raise ValueError('Positive finite nominal plan scale required')
    points = []
    for part_index, part in enumerate(geometry.geoms if geometry.geom_type == 'MultiPolygon' else [geometry]):
        for vertex_index, point in enumerate(part.exterior.coords):
            charge()
            value = sum(point[i]*frame['diagnostic_axis'][i] for i in (0, 1))*unit-frame['projection_min_m']
            points.append({'part_index': part_index, 'exterior_vertex_index': vertex_index,
                           'point_pdf_native': list(point), 'position_m': value})
    extrema = [min(points, key=lambda p: p['position_m']), max(points, key=lambda p: p['position_m'])]
    if extrema[0]['position_m'] >= extrema[1]['position_m']:
        raise ValueError('Positive original projected extent required')
    return {'nominal_plan_position_interval_m': [p['position_m'] for p in extrema],
            'source_extreme_vertices': extrema, 'geometry_pdf_native': mapping(geometry),
            'source_part_count': len(geometry.geoms) if geometry.geom_type == 'MultiPolygon' else 1,
            'source_hole_count': sum(len(p.interiors) for p in (geometry.geoms if geometry.geom_type == 'MultiPolygon' else [geometry])),
            'span_establishes_continuity': False, 'physical_facade_extent_verified': False}


def plan_extents(plan, source_view, record, frame, charge):
    label = next(l for l in plan['building_scope_review']['labels'] if l['id'] == record['label_id'])
    enclosure = next(c for c in label['candidates'] if c['id'] == record['enclosure_id'])
    unit = plan['nominal_metres_per_pdf_point']; zone = shape(source_view['geometry'])
    result = []
    def retain(geometry, kind, source_id, source_hash):
        extent = {**projected_extent(geometry, frame, unit, charge), 'source_kind': kind,
                  'source_id': source_id, 'source_record_sha256': source_hash}
        extent['id'] = digest([VERSION, record['id'], frame['id'], extent]); result.append(extent)
    retain(shape(enclosure['geometry_pdf_native']), 'named_enclosure', enclosure['id'], digest(enclosure))
    matrix = pymupdf.Matrix(plan['plan_gap_review']['unrotated_mupdf_to_pdf_native_matrix'])
    withheld = []
    for fill in plan['plan_gap_review']['page_fill_recovery']['candidates']:
        charge()
        if list(fill['fill_color']) == [1, 1, 1]: continue
        geometry = affine_transform(shape(fill['geometry']), affine(matrix))
        distance = min(geometry.boundary.distance(Point(p)) for p in frame['ray_hits_pdf_native'])
        if distance > PAINT_NEIGHBOURHOOD_POINTS: continue
        if not zone.covers(geometry):
            withheld.append({'source_fill_id': fill['id'], 'source_fill_sha256': digest(fill),
                             'status': 'whole_source_paint_crosses_plan_view'}); continue
        retain(geometry, 'near_ray_original_paint', fill['id'], digest(fill))
        result[-1]['ray_boundary_distance_pdf_points'] = distance
    return result, withheld


def surrounds(parent, child, charge):
    """All original witnesses must surround all child witnesses with distinct jambs."""
    if parent['residual_family_id'] == child['residual_family_id']: return False
    for outer in parent['witnesses']:
        for inner in child['witnesses']:
            charge(); a, b = outer['source_bounds_pixels'], inner['source_bounds_pixels']
            if not (a[0] < b[0] and a[2] > b[2] and a[1] < b[1] and a[3] >= b[3]): return False
            if (outer['variant_index'] == inner['variant_index']
                    and set(outer['jamb_group_indices']) & set(inner['jamb_group_indices'])): return False
    return True


def compare_extent(extent, parent, matrix, unit, charge):
    low, high = extent['nominal_plan_position_interval_m']; width = high-low; witnesses = []
    for source in parent['witnesses']:
        charge(); bounds = source['source_bounds_pixels']; observed = (bounds[2]-bounds[0])*matrix[0]*unit
        witnesses.append({'variant_index': source['variant_index'], 'pair_index': source['pair_index'],
            'source_witness_sha256': digest(source), 'source_bounds_pixels': bounds,
            'nominal_elevation_width_m': observed, 'elevation_minus_plan_width_m': observed-width,
            'diagnostic_elevation_to_plan_width_ratio': observed/width,
            'within_discovery_tolerance': abs(observed-width) <= TOLERANCE_M})
    passed = [w['within_discovery_tolerance'] for w in witnesses]
    row = {'plan_extent_id': extent['id'], 'parent_family_review_id': parent['id'],
           'parent_residual_family_id': parent['residual_family_id'], 'source_parent_review_sha256': digest(parent),
           'nominal_plan_width_m': width, 'witnesses': witnesses,
           'status': 'all_witness_extent_widths_compatible' if all(passed) else
                     'extent_width_witnesses_disagree' if any(passed) else 'independent_extent_width_mismatch',
           'scale_correction_applied': False, 'physical_facade_extent_verified': False}
    row['id'] = digest([VERSION, row]); return row


def compare_position(extent, parent, child, projection, matrix, unit, reverse, charge):
    """Anchor to independent extent edges; never translate/rescale to a child gap."""
    low, high = extent['nominal_plan_position_interval_m']; target = projection['nominal_plan_position_interval_m']
    witnesses = []
    for outer in parent['witnesses']:
        left = outer['source_bounds_pixels'][0]; slope = matrix[0]*unit*(-1 if reverse else 1)
        intercept = (high if reverse else low)-slope*left
        for inner in child['witnesses']:
            charge(); bounds = inner['source_bounds_pixels']; interval = sorted(slope*bounds[i]+intercept for i in (0, 2))
            residual = max(abs(interval[i]-target[i]) for i in (0, 1))
            witnesses.append({'source_parent_witness_sha256': digest(outer), 'source_child_witness_sha256': digest(inner),
                'source_child_bounds_pixels': bounds, 'pixel_x_to_plan_position_affine': [slope, intercept],
                'nominal_position_interval_m': interval, 'maximum_endpoint_residual_m': residual,
                'within_discovery_tolerance': residual <= TOLERANCE_M})
    passed = [w['within_discovery_tolerance'] for w in witnesses]
    row = {'elevation_x_reversed': reverse, 'plan_extent_id': extent['id'], 'projection_id': projection['id'],
           'parent_family_review_id': parent['id'], 'child_family_review_id': child['id'],
           'source_projection_sha256': digest(projection), 'witnesses': witnesses,
           'status': 'all_witness_positions_compatible' if all(passed) else
                     'position_witnesses_disagree' if any(passed) else 'independent_origin_position_mismatch',
           'origin_fit_to_opening': False, 'scale_correction_applied': False,
           'physical_correspondence_verified': False, 'position_alignment_verified': False}
    row['id'] = digest([VERSION, row]); return row


def run(source_pages, inventories, buildings, levels, *, max_checks=100000):
    bounded_work(max_checks)
    lookup = {v['view_id']: v for v in inventories}; pins = {key: digest(v) for key, v in lookup.items()}
    if len(inventories)>32 or len(lookup)!=len(inventories): raise ValueError('Bounded unique source inventories required')
    if (buildings['source_inventory_sha256'] != pins or levels['source_inventory_sha256'] != pins
            or levels['source_building_links_sha256'] != digest(buildings)):
        raise ValueError('Matching source inventory and upstream reviews required')
    result = {'version': VERSION, 'status': 'independent_source_extent_and_origin_hypotheses_only',
        'source_inventory_sha256': pins, 'source_building_links_sha256': digest(buildings),
        'source_level_context_sha256': digest(levels), 'frames': [], 'checks': 0,
        'recipe': {'extent_and_position_tolerance_nominal_m': TOLERANCE_M,
            'paint_ray_neighbourhood_pdf_points': PAINT_NEIGHBOURHOOD_POINTS,
            'parent_recipe': 'every original parent witness surrounds every child witness with distinct jamb groups',
            'plan_recipes': ['whole_named_enclosure', 'whole_near_ray_paint_including_all_parts_and_holes'],
            'origin_recipe': 'left parent pixel edge maps to plan extent left or right edge; both parities retained',
            'scale_recipe': 'original_nominal_scales_only_no_fit', 'max_checks': max_checks},
        'physical_facade_extent_verified': False, 'position_alignment_verified': False,
        'physical_opening_verified': False, 'world_geometry_additions': 0, 'training_labels_generated': 0}
    if buildings['status']!='numbered_source_facade_candidates_only' or levels['status']!='source_relative_elevation_context_only':
        return {**result, 'status': 'source_facade_and_level_context_required'}
    selected_sources = [(p, v) for p in source_pages for v in p['views'] if v['id'] in lookup]
    sources = {v['id']: (p, v) for p, v in selected_sources}
    if (len(selected_sources)!=len(lookup) or len(sources)!=len(lookup)
            or any(digest(sources[k][1])!=v['source_view_sha256'] for k, v in lookup.items())):
        raise ValueError('Matching automatic source views required')
    views = {v['view_id']: v for v in levels['views']}
    projections = {p['id']: p for p in buildings['projected_gaps']}
    def charge():
        result['checks'] += 1
        if result['checks']>max_checks: raise OverflowError('facade_alignment_work_budget')
    def hold(reason):
        return {**result, 'status': 'facade_alignment_budget_withheld', 'reason': reason, 'frames': [], 'counts': {}}
    try:
        for record in buildings['frames']:
            charge()
            row = {'facade_record_id': record['id'], 'source_facade_record_sha256': digest(record),
                   'plan_view_id': record['plan_view_id'], 'target_elevation_view_ids': record['target_elevation_view_ids'],
                   'status': 'single_numbered_elevation_target_required', 'frame_reviews': []}
            result['frames'].append(row)
            if len(record['target_elevation_view_ids'])!=1: continue
            target = record['target_elevation_view_ids'][0]; level = views.get(target)
            if not record['frame_review']['frames']:
                row['status'] = record['frame_review']['status']; continue
            if not level or level['status']!='all_original_residual_families_reviewed_against_source_level':
                row['status'] = 'complete_source_level_family_review_required'; continue
            matrix = level['pixel_edge_to_source_display_matrix']; unit = lookup[target]['nominal_metres_per_pdf_point']
            if (not matrix or len(matrix)!=6 or any(not math.isfinite(x) for x in matrix)
                    or abs(matrix[1])>1e-7 or abs(matrix[2])>1e-7 or matrix[0]<=0 or matrix[3]<=0
                    or type(unit) not in (int, float) or not math.isfinite(unit) or unit<=0):
                raise ValueError('Positive aligned source display transform required')
            families = {f['residual_family_id']: f for f in level['families']}
            retained = [f for f in families.values() if f['status']=='all_threshold_witnesses_support_above_level_rows'
                        and f['candidate_scope_status']!='candidate_scope_crossing_withheld']
            if len(retained)>8192: return hold('retained_facade_family_budget')
            row['status'] = 'independent_extent_reviews_only'
            for frame in record['frame_review']['frames']:
                extents, withheld = plan_extents(lookup[record['plan_view_id']], sources[record['plan_view_id']][1], record, frame, charge)
                review = {'frame_id': frame['id'], 'plan_extents': extents, 'withheld_plan_paints': withheld,
                          'reviewed_level_link_sha256': [], 'parent_child_relations': [],
                          'extent_comparisons': [], 'position_comparisons': []}
                row['frame_reviews'].append(review); seen = {}; positions = set()
                for link in levels['level_supported_width_links']:
                    charge(); projection = projections[link['projection_id']]
                    if (projection['facade_record_id']!=record['id'] or projection['frame_id']!=frame['id']
                            or link['elevation_view_id']!=target): continue
                    review['reviewed_level_link_sha256'].append(digest(link))
                    child = families[link['residual_family_id']]
                    for parent in retained:
                        charge()
                        if not surrounds(parent, child, charge): continue
                        review['parent_child_relations'].append({'source_level_link_sha256': digest(link),
                            'parent_family_review_id': parent['id'], 'child_family_review_id': child['id'],
                            'source_parent_review_sha256': digest(parent), 'source_child_review_sha256': digest(child)})
                        for extent in extents:
                            key = (extent['id'], parent['id'])
                            if key not in seen:
                                seen[key] = compare_extent(extent, parent, matrix, unit, charge)
                                review['extent_comparisons'].append(seen[key])
                            if seen[key]['status']!='all_witness_extent_widths_compatible': continue
                            for reverse in (False, True):
                                identity = (*key, child['id'], projection['id'], reverse)
                                if identity in positions: continue
                                positions.add(identity)
                                comparison = compare_position(extent, parent, child, projection, matrix, unit, reverse, charge)
                                comparison['source_extent_comparison_id'] = seen[key]['id']
                                comparison['id'] = digest([VERSION, {k:v for k,v in comparison.items() if k!='id'}])
                                review['position_comparisons'].append(comparison)
        reviews = [v for r in result['frames'] for v in r['frame_reviews']]
        result['counts'] = dict(Counter(c['status'] for r in reviews for c in [*r['extent_comparisons'], *r['position_comparisons']]))
        result['counts'].update({'numbered_facade_records': len(result['frames']),
            'plan_extent_candidates': sum(len(r['plan_extents']) for r in reviews),
            'parent_child_relations': sum(len(r['parent_child_relations']) for r in reviews),
            'extent_comparisons': sum(len(r['extent_comparisons']) for r in reviews),
            'position_comparisons': sum(len(r['position_comparisons']) for r in reviews)})
        return result
    except OverflowError as error: return hold(str(error))
