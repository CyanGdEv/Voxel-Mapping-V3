"""Original grayscale edge evidence and explicit plan-projection ambiguity.

Complementary to the unchanged binary-threshold partial-gable review. No wing
geometry, eave endpoints, depth, physical pitch or park placement is accepted.
"""
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image
from rasterio.features import rasterize
from scipy import ndimage

from . import automatic_partial_gables as partial
from . import automatic_gable_roof as roof
from .automatic_opening_links import bounded_work
from .generation_cycles import atomic_json, file_hash
from .reconstruction_evidence_queue import digest

VERSION = 'source-gradient-gable-review-v1'


def gradient_lines(gray, excluded, contrast, charge):
    """Propose whole local runs before fitting; retain every pixel and seed receipt."""
    if (gray.dtype != np.uint8 or gray.ndim != 2 or gray.size > 6000000
            or max(gray.shape) > 3000 or excluded.shape != gray.shape or excluded.dtype != bool):
        raise ValueError('Bounded original gray raster and boolean exclusions required')
    if contrast not in (32, 64):
        raise ValueError('Original grayscale gradient contrast cutoffs required')
    gx = ndimage.sobel(gray.astype(float), axis=1)
    gy = ndimage.sobel(gray.astype(float), axis=0)
    orientation = (np.degrees(np.arctan2(-gx, gy)) + 90) % 180 - 90
    eligible = (gray < 250) & ~excluded & (abs(orientation) >= 15) & (abs(orientation) <= 65) & (np.hypot(gx, gy) >= contrast)
    y, x = np.nonzero(eligible)
    angles = orientation[y, x]
    if len(x) > 65536:
        raise OverflowError('gradient_gable_source_pixel_budget')
    radius = math.ceil(math.hypot(*gray.shape))
    votes = np.zeros((len(roof.ANGLES), 2 * radius + 1), np.int32)
    for i, angle in enumerate(roof.ANGLES):
        charge()
        rad = math.radians(angle)
        keep = abs(angles - angle) <= 12
        bins = np.rint(y[keep] * math.cos(rad) - x[keep] * math.sin(rad)).astype(int) + radius
        votes[i] = np.bincount(bins, minlength=2 * radius + 1)
    peaks = np.argwhere((votes >= 16) & (votes == ndimage.maximum_filter(votes, size=(5, 5), mode='constant')))
    if len(peaks) > 2048:
        raise OverflowError('gradient_gable_hough_peak_budget')
    lines, memberships = [], {}
    gray_sha = hashlib.sha256(gray.tobytes()).hexdigest()
    mask_sha = hashlib.sha256(excluded.astype('uint8').tobytes()).hexdigest()
    groups_considered = 0
    for i, j in peaks:
        charge()
        angle, rho = float(roof.ANGLES[i]), int(j - radius)
        rad = math.radians(angle)
        ids = np.flatnonzero((abs(angles - angle) <= 12)
            & (abs(y * math.cos(rad) - x * math.sin(rad) - rho) <= 1.5))
        ids = ids[np.lexsort((y[ids], x[ids]))]
        # Partition by source columns before fitting. No corridor extension or gap fill.
        cuts = np.r_[0, np.flatnonzero(np.diff(x[ids]) > 4) + 1, len(ids)]
        for lo, hi in zip(cuts[:-1], cuts[1:]):
            charge()
            groups_considered += 1
            group = ids[lo:hi]
            if not len(group):
                continue
            xx, yy = x[group], y[group]
            if len(group) < 24 or not 24 <= xx[-1] - xx[0] < 64:
                continue
            if len(group) > 1024:
                raise OverflowError('gradient_gable_line_pixel_budget')
            fit = xx % 2 == 0
            check = ~fit
            if min(int(fit.sum()), int(check.sum())) < 8:
                continue
            slope, intercept = np.linalg.lstsq(np.c_[xx[fit], np.ones(int(fit.sum()))], yy[fit], rcond=None)[0]
            residual = abs(slope * xx + intercept - yy) / math.hypot(slope, 1)
            if not math.tan(math.radians(15)) <= abs(slope) <= math.tan(math.radians(65)) or max(residual) > 3:
                continue
            membership = hashlib.sha256(np.asarray(sorted((yy * gray.shape[1] + xx).tolist()), dtype='<u8').tobytes()).hexdigest()
            seed = {'angle_degrees': angle, 'normal_offset_pixels': rho, 'votes': int(votes[i, j]),
                'whole_seed_membership_sha256': hashlib.sha256(np.asarray(sorted((y[ids] * gray.shape[1] + x[ids]).tolist()), dtype='<u8').tobytes()).hexdigest(),
                'local_group_source_x_interval': [int(xx[0]), int(xx[-1])]}
            if membership in memberships:
                memberships[membership]['hough_seeds'].append(seed)
                continue
            columns = np.unique(xx)
            line = {'slope': float(slope), 'intercept': float(intercept),
                'pitch_magnitude_degrees': abs(math.degrees(math.atan(slope))),
                'source_x_interval': [int(xx[0]), int(xx[-1])],
                'source_pixels': [{'x': int(a), 'y': int(b), 'gray': int(gray[b, a]),
                    'role': 'fit' if a % 2 == 0 else 'check'} for a, b in zip(xx, yy)],
                'source_membership_sha256': membership, 'hough_seeds': [seed],
                'fit_max_normal_residual_pixels': float(max(residual[fit])),
                'check_max_normal_residual_pixels': float(max(residual[check])),
                'unsupported_column_intervals': [[int(a + 1), int(b)] for a, b in zip(columns[:-1], columns[1:]) if b > a + 1],
                'source_gaps_filled': False, 'source_points_removed_after_fit': 0,
                'fit_role_recipe': 'even_original_columns_fit_odd_columns_check_no_outlier_removal',
                'physical_roof_edge_verified': False}
            line['id'] = digest([VERSION, contrast, gray_sha, mask_sha, membership])
            memberships[membership] = line
            lines.append(line)
            if len(lines) > 1024:
                raise OverflowError('gradient_gable_short_line_budget')
    return {'gradient_cutoff': contrast, 'source_ink_ceiling_exclusive': 250, 'source_gray_sha256': gray_sha, 'source_exclusion_mask_sha256': mask_sha,
        'eligible_source_edge_pixels': len(x), 'hough_peak_count': len(peaks),
        'whole_local_groups_considered': groups_considered, 'lines': lines}


def direction_cohorts(inventory, charge):
    """Whole original straight plan lines; source-ID roles before gable comparison."""
    unit = inventory['nominal_metres_per_pdf_point']
    if not math.isfinite(unit) or unit <= 0:
        raise ValueError('Finite nominal plan units required')
    if len(inventory['source_components']) > 4096:
        raise OverflowError('gradient_plan_source_component_budget')
    groups = defaultdict(list)
    for component in inventory['source_components']:
        charge(); geometry = component['geometry']
        if (geometry['type'] != 'LineString' or len(geometry['coordinates']) != 2
                or component['rendering_status'] != 'supported_straight_unclipped_polyline'
                or component['curve_approximation']['cubic_segments']):
            continue
        points = np.asarray(geometry['coordinates'], float)
        if not np.isfinite(points).all():
            raise ValueError('Finite original plan endpoints required')
        delta = points[1] - points[0]
        length = float(np.linalg.norm(delta))
        if length * unit < 1:
            continue
        vector = delta / length
        angle = math.degrees(math.atan2(vector[1], vector[0])) % 180
        bucket = int(round(angle)) % 180
        row = {'source_component_id': component['id'], 'source_component_sha256': digest(component),
            'source_endpoints_pdf_native': geometry['coordinates'], 'source_unit_vector': vector.tolist(),
            'source_angle_degrees_modulo_180': angle, 'nominal_source_length_m': length * unit,
            'source_points_moved': False, 'physical_line_role_verified': False}
        groups[bucket].append(row)
    cohorts = []
    for bucket, lines in sorted(groups.items()):
        charge(); lines.sort(key=lambda line: line['source_component_id'])
        row = {'source_direction_bin_degrees': bucket, 'lines': lines,
            'direction_witness_source_component_id': lines[0]['source_component_id'],
            'source_direction_unit_vector': lines[0]['source_unit_vector'],
            'direction_role_recipe': 'lexically_first_original_source_component_before_any_gable_comparison',
            'status': 'repeated_source_plan_direction' if len(lines) >= 3 else 'insufficient_repeated_source_direction_support',
            'physical_gable_width_axis_verified': False, 'hatch_or_other_line_semantics_unverified': True}
        row['id'] = digest([VERSION, inventory['view_id'], row]); cohorts.append(row)
    return {'view_id': inventory['view_id'], 'document_sha256': inventory['document_sha256'], 'page': inventory['page'],
        'plan_form': inventory['printed_claim'].get('plan_level_or_form'), 'cohorts': cohorts}


def comparison_rows(a, b, charge, *, recipe, context):
    """Keep all consistency alternatives. Shared source pixels are not independent controls."""
    result = []
    for check in partial.threshold_checks([{'pairs': a}, {'pairs': b}], charge):
        row = {k: check[k] for k in ('ridge_distance_source_pixels', 'pitch_differences_degrees')}
        row.update(context)
        row.update(source_pair_ids=check['threshold_pair_ids'], comparison_recipe=recipe,
            status='source_variant_measurements_agree' if check['status'] == 'source_threshold_measurements_agree' else 'source_variant_measurements_disagree',
            original_source_pixels_can_be_shared=True, independent_survey_checks=False, lines_refitted=False,
            physical_correspondence_verified=False)
        row['id'] = digest([VERSION, row]); result.append(row)
    return result


def projection_pitch(apparent_pitch, projected_fraction):
    if not np.isfinite([apparent_pitch, projected_fraction]).all() or not 0 < apparent_pitch < 90 or not 0 <= projected_fraction <= 1 + 1e-12:
        raise ValueError('Finite apparent pitch and unit direction projection required')
    if projected_fraction <= math.sin(math.radians(5)):
        return None
    return math.degrees(math.atan(math.tan(math.radians(apparent_pitch)) * min(1., projected_fraction)))


def plan_projection_reviews(rows, direction_reviews, inventories, reviews, preview, charge):
    """Direction agreement and conditional pitch diagnostics; never a plan/wing match."""
    contexts, direction_checks, projections = [], [], []
    targets = {(t['pair_id'], tuple(t['key'])): t for t in preview['target_marker_checks']}
    row_lookup = {r['view_id']: r for r in rows}
    for record in reviews['building_facade_links']['frames']:
        if len(record['target_elevation_view_ids']) != 1 or record['target_elevation_view_ids'][0] not in row_lookup:
            continue
        for frame in record['frame_review']['frames']:
            for artwork in reviews['artwork_scale_controls']['pairs']:
                charge(); target = targets.get((artwork['id'], tuple(record['target_view_key_candidate'])))
                if not target or target['status'] != 'fixed_non_target_layout_agrees_at_target_annotation':
                    continue
                floor = [r for r in direction_reviews if r['plan_form'] == 'groundfloor' and [r['document_sha256'], r['page']] == artwork['subject_page_key']]
                plans = [r for r in direction_reviews if r['plan_form'] == 'roof' and [r['document_sha256'], r['page']] == artwork['reference_page_key']]
                matrix = np.asarray(artwork['subject_to_reference_linear_row_matrix'], float)
                axis = np.asarray(frame['diagnostic_axis']) @ matrix
                axis /= np.linalg.norm(axis)
                for ground in floor:
                    for plan in plans:
                        charge()
                        context = {'elevation_view_id': record['target_elevation_view_ids'][0],
                            'source_frame_id': frame['id'], 'source_frame_sha256': digest(frame),
                            'fixed_artwork_pair_id': artwork['id'], 'fixed_artwork_pair_sha256': digest(artwork),
                            'floor_view_id': ground['view_id'], 'roof_view_id': plan['view_id'],
                            'source_view_horizontal_axis_in_roof_pdf': axis.tolist(),
                            'source_view_projection_frame_verified': False, 'physical_building_correspondence_verified': False,
                            'plan_translation_applied': False, 'diagnostic_gable_template_is_assumed': True}
                        context['id'] = digest([VERSION, context]); contexts.append(context)
                        if len(contexts) > 128:
                            raise OverflowError('gradient_plan_context_budget')
                        floor_groups = [g for g in ground['cohorts'] if g['status'] == 'repeated_source_plan_direction']
                        roof_groups = [g for g in plan['cohorts'] if g['status'] == 'repeated_source_plan_direction']
                        for f in floor_groups:
                            fv = np.asarray(f['source_direction_unit_vector']) @ matrix; fv /= np.linalg.norm(fv)
                            for r in roof_groups:
                                charge(); rv = np.asarray(r['source_direction_unit_vector'])
                                cosine = min(1., abs(float(fv @ rv)))
                                direction_checks.append({'context_id': context['id'], 'floor_direction_id': f['id'], 'roof_direction_id': r['id'],
                                    'axis_difference_degrees': math.degrees(math.acos(cosine)),
                                    'status': 'source_plan_directions_agree' if cosine >= math.cos(math.radians(1)) else 'source_plan_directions_disagree',
                                    'source_lines_refitted': False, 'building_identity_verified': False, 'eaves_or_depth_established': False})
                        source = row_lookup[context['elevation_view_id']]
                        for scan in source['variants']:
                            for anchor in scan['anchor_reviews']:
                                for pair in anchor['pairs']:
                                    if pair['status'] != 'conditional_partial_gable_source_support':
                                        continue
                                    for r in roof_groups:
                                        charge(); rv = np.asarray(r['source_direction_unit_vector'])
                                        fraction = min(1., abs(float(axis @ rv)))
                                        pitches = [projection_pitch(pair[k], fraction) for k in ('left_pitch_degrees', 'right_pitch_degrees')]
                                        projections.append({'context_id': context['id'], 'source_pair_id': pair['id'], 'roof_direction_id': r['id'],
                                            'projected_width_fraction': fraction,
                                            'conditional_deprojected_pitch_degrees': pitches,
                                            'status': 'edge_on_direction_pitch_withheld' if pitches[0] is None else 'conditional_direction_pitch_diagnostic_only',
                                            'width_parallel_to_plan_direction_is_assumed': True,
                                            'ridge_perpendicular_to_width_is_assumed': True,
                                            'true_pitch_verified': False, 'wing_depth_m': None, 'eave_endpoints': None,
                                            'physical_plan_elevation_match_verified': False, 'world_placement_eligible': False})
                                        if len(projections) > 8192:
                                            raise OverflowError('gradient_plan_projection_budget')
                        if len(direction_checks) > 8192:
                            raise OverflowError('gradient_plan_direction_check_budget')
    return contexts, direction_checks, projections


def build(source_partial, gable, profile, preview, components, views, corpus, output, *, max_checks=100000):
    bounded_work(max_checks)
    source_partial, gable, profile, preview, components, views, corpus, output = map(Path,
        (source_partial, gable, profile, preview, components, views, corpus, output))
    source_path = source_partial / 'partial-gables.json'; source_sha = file_hash(source_path)
    old_partial = roof._load(source_path)
    with tempfile.TemporaryDirectory() as temp:
        fresh = partial.build(gable, profile, preview, components, views, corpus, temp, max_checks=old_partial['contract']['max_checks'])
        fresh.pop('directory')
        if digest(fresh) != digest(old_partial):
            raise ValueError('Original partial gable replay changed')
    if old_partial['status'] != 'conditional_partial_gable_review_only':
        raise ValueError('Complete preceding partial gable review required')
    parent = roof._load(gable / 'gable-roof-review.json')
    _, _, inventories, _, reviews = roof.automatic_facade_preview._verified_inputs(components, views, corpus)
    source_views = roof._load(views / 'view-candidates.json')
    lookup = {v['id']: v for page in source_views['pages'] for v in page['views']}
    contract = {'version': VERSION, 'implementation_sha256': file_hash(Path(__file__)),
        'source_partial_review_sha256': source_sha, 'source_partial_contract': old_partial['contract'],
        'dependency_sha256': {m.__name__: file_hash(Path(m.__file__)) for m in (partial, roof)}, 'max_checks': max_checks}
    result = {'version': VERSION, 'contract': contract, 'status': 'source_gradient_gable_and_plan_direction_review_only',
        'checks': 0, 'views': [], 'direction_reviews': [], 'projection_contexts': [], 'plan_direction_checks': [], 'pitch_projection_diagnostics': [],
        'recipe': {'source_ink_ceiling_exclusive': 250, 'gradient_cutoffs': [32, 64],
            'gradient': 'Sobel of original uint8 grayscale, no smoothing or binary mask gradient',
            'short_group_and_hough_recipe': 'unchanged local support gates from preceding partial review',
            'parent_ink_thresholds': [220, 235], 'source_point_roles': 'even original columns fit, odd check; no outlier removal',
            'source_plan_direction_minimum_length_nominal_m': 1., 'source_plan_direction_bin_degrees': 1.,
            'source_plan_direction_minimum_members': 3, 'direction_check_maximum_degrees': 1.,
            'source_view_axis_is_fixed_from_parent': True, 'edge_on_pitch_hold_degrees': 5.},
        'previous_binary_threshold_hold_overridden': False, 'source_mask_gaps_filled': False,
        'parent_models_changed': False, 'new_roof_models': [], 'physical_wing_identity_verified': False,
        'physical_scale_verified': False, 'world_placement_eligible': False,
        'accepted_physical_components': 0, 'world_geometry_additions': 0, 'training_labels_generated': 0,
        'unresolved': ['Unique physical gable/building and plan correspondence',
            'True gable orientation/pitch, eave endpoints, full silhouette and plan depth',
            'Complete walls/openings, source state and park/vertical registration']}
    def charge():
        result['checks'] += 1
        if result['checks'] > max_checks:
            raise OverflowError('gradient_gable_work_budget')
    try:
        if len(parent['gable_views']) > 16:
            raise OverflowError('gradient_gable_source_view_budget')
        for original in parent['gable_views']:
            charge(); key = original['view_id']; image_path = views / lookup[key]['render']['png']
            if file_hash(image_path) != original['source_png_sha256']:
                raise ValueError('Original grayscale source changed')
            with Image.open(image_path) as im:
                if im.width * im.height > 6000000 or max(im.size) > 3000:
                    raise OverflowError('gradient_gable_source_raster_budget')
                gray = np.asarray(im.convert('L')).copy()
            records = original['source_exclusions']['records']
            if len(records) > 14096:
                raise OverflowError('gradient_gable_exclusion_budget')
            mask = rasterize([(r['geometry_pixels'], 1) for r in records], out_shape=gray.shape, all_touched=True) > 0 if records else np.zeros_like(gray, bool)
            if hashlib.sha256(mask.astype('uint8').tobytes()).hexdigest() != original['source_exclusions']['source_mask_sha256']:
                raise ValueError('Original source exclusions changed')
            row = {k: original[k] for k in ('view_id', 'caption', 'document_sha256', 'page', 'source_png_sha256', 'printed_level_pixel', 'nominal_metres_per_pixel')}
            row.update(variants=[], contrast_checks=[], anchor_checks=[], source_exclusions_sha256=digest(original['source_exclusions']))
            for contrast in (32, 64):
                scan = gradient_lines(gray, mask, contrast, charge); scan['anchor_reviews'] = []
                for anchor in original['variants']:
                    paired = partial.partial_pairs(anchor, scan['lines'], row['nominal_metres_per_pixel'], row['printed_level_pixel'], charge)
                    for pair in paired['pairs']:
                        pair.update(source_parent_ink_threshold=anchor['threshold'], source_gradient_cutoff=contrast)
                        pair['id'] = digest([VERSION, key, pair])
                    scan['anchor_reviews'].append({'source_parent_ink_threshold': anchor['threshold'], **paired})
                row['variants'].append(scan)
            for index, threshold in enumerate((220, 235)):
                row['contrast_checks'].extend(comparison_rows(row['variants'][0]['anchor_reviews'][index]['pairs'], row['variants'][1]['anchor_reviews'][index]['pairs'], charge,
                    recipe='fixed_parent_anchor_compared_across_grayscale_gradient_cutoffs', context={'source_parent_ink_threshold': threshold, 'source_gradient_cutoffs': [32,64]}))
            for scan in row['variants']:
                row['anchor_checks'].extend(comparison_rows(scan['anchor_reviews'][0]['pairs'], scan['anchor_reviews'][1]['pairs'], charge,
                    recipe='two_parent_ink_anchors_compared_with_shared_grayscale_short_evidence', context={'source_gradient_cutoff': scan['gradient_cutoff'], 'source_parent_ink_thresholds': [220,235]}))
            row['source_contrast_status'] = ('pairwise_source_contrast_support_with_both_parent_anchors' if
                all(any(c['source_parent_ink_threshold'] == t and c['status'] == 'source_variant_measurements_agree' for c in row['contrast_checks']) for t in (220,235))
                else 'source_contrast_support_not_established_with_both_parent_anchors')
            row['pairwise_consistency_is_not_unique_physical_correspondence'] = True
            result['views'].append(row)
        for inv in inventories.values():
            if inv['printed_claim']['view_kind'] == 'plan':
                result['direction_reviews'].append(direction_cohorts(inv, charge))
        contexts, checks, projections = plan_projection_reviews(result['views'], result['direction_reviews'], inventories, reviews,
            roof._load(preview / 'facade-preview.json'), charge)
        result.update(projection_contexts=contexts, plan_direction_checks=checks, pitch_projection_diagnostics=projections)
    except OverflowError as error:
        result.update(status='source_gradient_gable_budget_withheld', reason=str(error), views=[], direction_reviews=[],
            projection_contexts=[], plan_direction_checks=[], pitch_projection_diagnostics=[])
    roof.automatic_facade_preview._verified_inputs(components, views, corpus)
    if file_hash(source_path) != source_sha or file_hash(gable / 'gable-roof-review.json') != old_partial['contract']['source_gable_review_sha256']:
        raise ValueError('Preceding source reviews changed during grayscale build')
    for root, name, pin in [(profile,'facade-profile.json','source_profile_sha256'), (preview,'facade-preview.json','source_preview_sha256'),
            (components,'component-report.json','component_report_sha256'), (views,'view-report.json','view_report_sha256')]:
        if file_hash(root / name) != parent['contract'][pin]:
            raise ValueError('Parent source contract changed during grayscale build')
    for receipt in roof._load(preview / 'facade-preview.json')['source_crop_receipts']:
        if file_hash(preview / receipt['file']) != receipt['png_sha256']:
            raise ValueError('Original preview crop changed during grayscale build')
    for group in roof._load(profile / 'facade-profile.json')['profiles']:
        for variant in group['variants']:
            for name in ('roof', 'wall'):
                receipt = variant.get(name + '_mask_receipt')
                if receipt and file_hash(profile / receipt['file']) != receipt['png_sha256']:
                    raise ValueError('Original profile mask changed during grayscale build')
    scans = [s for r in result['views'] for s in r['variants']]
    pairs = [p for s in scans for a in s['anchor_reviews'] for p in a['pairs']]
    result['counts'] = {'source_views': len(result['views']), 'source_gradient_lines': sum(len(s['lines']) for s in scans),
        'source_gradient_pixel_memberships': sum(len(l['source_pixels']) for s in scans for l in s['lines']),
        'partial_intersections': len(pairs), 'conditional_partial_intersections': sum(p['status'] == 'conditional_partial_gable_source_support' for p in pairs),
        'held_partial_intersections': sum(p['status'] == 'partial_gable_source_check_held' for p in pairs),
        'contrast_checks': sum(len(r['contrast_checks']) for r in result['views']),
        'contrast_checks_agree': sum(c['status'] == 'source_variant_measurements_agree' for r in result['views'] for c in r['contrast_checks']),
        'anchor_checks': sum(len(r['anchor_checks']) for r in result['views']),
        'anchor_checks_agree': sum(c['status'] == 'source_variant_measurements_agree' for r in result['views'] for c in r['anchor_checks']),
        'views_with_pairwise_contrast_support': sum(r['source_contrast_status'] == 'pairwise_source_contrast_support_with_both_parent_anchors' for r in result['views']),
        'source_plan_line_receipts': sum(len(g['lines']) for r in result['direction_reviews'] for g in r['cohorts']),
        'repeated_plan_direction_cohorts': sum(g['status'] == 'repeated_source_plan_direction' for r in result['direction_reviews'] for g in r['cohorts']),
        'source_projection_contexts': len(result['projection_contexts']), 'floor_roof_direction_checks': len(result['plan_direction_checks']),
        'floor_roof_direction_checks_agree': sum(c['status'] == 'source_plan_directions_agree' for c in result['plan_direction_checks']),
        'conditional_pitch_diagnostics': len(result['pitch_projection_diagnostics']),
        'edge_on_pitch_holds': sum(p['status'] == 'edge_on_direction_pitch_withheld' for p in result['pitch_projection_diagnostics']), 'new_roof_models': 0}
    if len(json.dumps(result).encode()) > 64000000:
        raise ValueError('Source gradient output budget exceeded')
    root = output / digest(contract)
    if root.exists():
        if digest(roof._load(root / 'source-gradient-gables.json')) != digest(result):
            raise ValueError('Saved source gradient review changed')
    else:
        atomic_json(root / 'source-gradient-gables.json', result)
    return {**result, 'directory': str(root)}
