"""Short source strokes paired with previously unpaired long gable candidates.

This downstream review never completes an occluded roof or edits its parent.
"""
import hashlib
import json
import math
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image
from rasterio.features import rasterize
from scipy import ndimage

from . import automatic_gable_roof as roof
from .automatic_opening_links import bounded_work
from .generation_cycles import atomic_json, file_hash
from .reconstruction_evidence_queue import digest

VERSION = 'automatic-partial-gable-evidence-v1'


def short_slope_lines(gray, excluded, threshold, charge):
    """Propose whole local runs before fitting; retain every pixel and seed receipt."""
    if (gray.dtype != np.uint8 or gray.ndim != 2 or gray.size > 6000000
            or max(gray.shape) > 3000 or excluded.shape != gray.shape or excluded.dtype != bool):
        raise ValueError('Bounded original gray raster and boolean exclusions required')
    if threshold not in (220, 235):
        raise ValueError('Original source raster thresholds required')
    dark = gray < threshold
    gx = ndimage.sobel(dark.astype(float), axis=1)
    gy = ndimage.sobel(dark.astype(float), axis=0)
    orientation = (np.degrees(np.arctan2(-gx, gy)) + 90) % 180 - 90
    eligible = dark & ~excluded & (abs(orientation) >= 15) & (abs(orientation) <= 65) & (np.hypot(gx, gy) >= 1)
    y, x = np.nonzero(eligible)
    angles = orientation[y, x]
    if len(x) > 65536:
        raise OverflowError('partial_gable_source_pixel_budget')
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
        raise OverflowError('partial_gable_hough_peak_budget')
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
                raise OverflowError('partial_gable_line_pixel_budget')
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
            line['id'] = digest([VERSION, threshold, gray_sha, mask_sha, membership])
            memberships[membership] = line
            lines.append(line)
            if len(lines) > 1024:
                raise OverflowError('partial_gable_short_line_budget')
    return {'threshold': threshold, 'source_gray_sha256': gray_sha, 'source_exclusion_mask_sha256': mask_sha,
        'eligible_source_edge_pixels': len(x), 'hough_peak_count': len(peaks),
        'whole_local_groups_considered': groups_considered, 'lines': lines}


def partial_pairs(original, short_lines, metres_per_pixel, level_pixel, charge):
    """Keep competing intersections, including support-end and pitch failures."""
    if not np.isfinite([metres_per_pixel, level_pixel]).all() or metres_per_pixel <= 0:
        raise ValueError('Finite original source scale required')
    if len(original['lines']) > 128 or len(original['gable_pairs']) > 512 or len(short_lines) > 1024:
        raise OverflowError('partial_gable_pair_input_budget')
    paired = {p[k] for p in original['gable_pairs'] for k in ('left_line_id', 'right_line_id')}
    unpaired = [line for line in original['lines'] if line['id'] not in paired]
    result = []
    for long in unpaired:
        for short in short_lines:
            charge()
            if long['slope'] * short['slope'] >= 0:
                continue
            left, right = (long, short) if long['slope'] < 0 else (short, long)
            x = (right['intercept'] - left['intercept']) / (left['slope'] - right['slope'])
            y = left['slope'] * x + left['intercept']
            if not (left['source_x_interval'][0] + 32 < x < right['source_x_interval'][1] - 32
                    and left['source_x_interval'][0] - 12 <= x <= left['source_x_interval'][1] + 12
                    and right['source_x_interval'][0] - 12 <= x <= right['source_x_interval'][1] + 12):
                continue
            end_errors = [abs(x - left['source_x_interval'][1]), abs(x - right['source_x_interval'][0])]
            pitch_difference = abs(left['pitch_magnitude_degrees'] - right['pitch_magnitude_degrees'])
            near_ends = max(end_errors) <= 12
            pitch_agrees = pitch_difference <= 2
            row = {'source_long_line_id': long['id'], 'source_short_line_id': short['id'],
                'left_source_kind': 'long' if left is long else 'short',
                'inferred_ridge_pixel': [float(x), float(y)],
                'nominal_ridge_height_m': float((level_pixel - y) * metres_per_pixel),
                'left_pitch_degrees': left['pitch_magnitude_degrees'], 'right_pitch_degrees': right['pitch_magnitude_degrees'],
                'source_ridge_end_errors_pixels': end_errors, 'source_ridge_at_visible_support_ends': near_ends,
                'pitch_difference_degrees': pitch_difference, 'paired_pitch_consistency_within_two_degrees': pitch_agrees,
                'status': 'conditional_partial_gable_source_support' if near_ends and pitch_agrees else 'partial_gable_source_check_held',
                'ridge_is_original_source_vertex': False, 'independent_depth_measurement_m': None,
                'eave_endpoints_verified': False, 'physical_gable_identity_verified': False,
                'complete_wing_mesh': None, 'source_long_line_refitted': False,
                'symmetry_assumed_for_pitch_check_only': True, 'world_placement_eligible': False}
            row['id'] = digest([VERSION, row])
            result.append(row)
            if len(result) > 2048:
                raise OverflowError('partial_gable_pair_budget')
    return {'source_unpaired_long_line_ids': [line['id'] for line in unpaired], 'pairs': result}


def threshold_checks(variants, charge):
    """Compare conditional pairs across thresholds without picking or refitting a winner."""
    good = [[p for p in v['pairs'] if p['status'] == 'conditional_partial_gable_source_support'] for v in variants]
    result = []
    for a in good[0]:
        for b in good[1]:
            charge()
            distance = math.dist(a['inferred_ridge_pixel'], b['inferred_ridge_pixel'])
            pitches = [abs(a[k] - b[k]) for k in ('left_pitch_degrees', 'right_pitch_degrees')]
            row = {'threshold_pair_ids': [a['id'], b['id']], 'ridge_distance_source_pixels': distance,
                'pitch_differences_degrees': pitches,
                'status': 'source_threshold_measurements_agree' if distance <= 4 and max(pitches) <= 2 else 'source_threshold_measurements_disagree',
                'physical_correspondence_verified': False, 'lines_refitted': False}
            row['id'] = digest([VERSION, row]); result.append(row)
            if len(result) > 4096:
                raise OverflowError('partial_gable_threshold_pair_budget')
    return result


def build(gable, profile, preview, components, views, corpus, output, *, max_checks=100000):
    bounded_work(max_checks)
    gable, profile, preview, components, views, corpus, output = map(Path, (gable, profile, preview, components, views, corpus, output))
    path = gable / 'gable-roof-review.json'
    source_sha = file_hash(path)
    previous = roof._load(path)
    with tempfile.TemporaryDirectory() as temp:
        replay = roof.build(profile, preview, components, views, corpus, temp, max_checks=previous['contract']['max_checks'])
        replay.pop('directory')
        if digest(previous) != digest(replay):
            raise ValueError('Original gable roof replay changed')
    if previous['status'] != 'conditional_unplaced_pitched_roof_review_only':
        raise ValueError('Complete preceding source gable review required')
    contract = {'version': VERSION, 'implementation_sha256': file_hash(Path(__file__)),
        'source_gable_review_sha256': source_sha, 'source_gable_contract': previous['contract'],
        'source_kernel_sha256': file_hash(Path(roof.__file__)), 'max_checks': max_checks}
    result = {'version': VERSION, 'contract': contract, 'status': 'conditional_partial_gable_review_only',
        'checks': 0, 'views': [], 'recipe': {'thresholds': [220, 235], 'hough_minimum_votes': 16,
            'minimum_original_points': 24, 'source_x_span_pixels': [24, 64], 'upper_span_is_exclusive': True,
            'maximum_source_column_step': 4, 'minimum_fit_and_check_points': 8,
            'maximum_normal_residual_pixels': 3, 'ridge_support_end_allowance_pixels': 12,
            'paired_pitch_consistency_degrees': 2, 'cross_threshold_ridge_distance_pixels': 4,
            'native_exclusions_and_hough_direction_recipe': 'unchanged_from_parent',
            'line_roles': 'whole local Hough groups before fit; even original columns fit, odd check; no outlier removal'},
        'parent_models_changed': False, 'new_roof_models': [], 'accepted_physical_components': 0,
        'world_geometry_additions': 0, 'training_labels_generated': 0, 'world_placement_eligible': False,
        'unresolved': ['Cross-threshold stability and physical gable/wing correspondence',
            'Occluded eaves, complete wing silhouette, plan depth and source state',
            'Complete walls/openings, physical scale and park registration']}
    def charge():
        result['checks'] += 1
        if result['checks'] > max_checks:
            raise OverflowError('partial_gable_work_budget')
    source = roof._load(views / 'view-candidates.json')
    lookup = {v['id']: v for page in source['pages'] for v in page['views']}
    try:
        if len(previous['gable_views']) > 16:
            raise OverflowError('partial_gable_source_view_budget')
        for parent in previous['gable_views']:
            charge(); view = lookup[parent['view_id']]; image_path = views / view['render']['png']
            if file_hash(image_path) != parent['source_png_sha256']:
                raise ValueError('Original partial gable raster changed')
            with Image.open(image_path) as image:
                if image.width * image.height > 6000000 or max(image.size) > 3000:
                    raise OverflowError('partial_gable_raster_budget')
                gray = np.asarray(image.convert('L')).copy()
            records = parent['source_exclusions']['records']
            if len(records) > 14096:
                raise OverflowError('partial_gable_source_exclusion_budget')
            mask = rasterize([(r['geometry_pixels'], 1) for r in records], out_shape=gray.shape, all_touched=True) > 0 if records else np.zeros_like(gray, bool)
            if hashlib.sha256(mask.astype('uint8').tobytes()).hexdigest() != parent['source_exclusions']['source_mask_sha256']:
                raise ValueError('Original gable exclusions changed')
            row = {k: parent[k] for k in ('view_id', 'caption', 'document_sha256', 'page', 'source_png_sha256', 'nominal_metres_per_pixel', 'printed_level_pixel')}
            row.update(source_exclusions_sha256=digest(parent['source_exclusions']), variants=[])
            for original in parent['variants']:
                scan = short_slope_lines(gray, mask, original['threshold'], charge)
                scan.update(partial_pairs(original, scan['lines'], parent['nominal_metres_per_pixel'], parent['printed_level_pixel'], charge))
                row['variants'].append(scan)
            row['threshold_checks'] = threshold_checks(row['variants'], charge)
            row['source_threshold_status'] = ('conditional_source_threshold_support' if any(c['status'] == 'source_threshold_measurements_agree' for c in row['threshold_checks'])
                else 'source_threshold_stability_not_established')
            result['views'].append(row)
    except OverflowError as error:
        result.update(status='partial_gable_budget_withheld', reason=str(error), views=[])
    # Recheck every bound parent input and original source, including masks/crops.
    roof.automatic_facade_preview._verified_inputs(components, views, corpus)
    if file_hash(path) != contract['source_gable_review_sha256']:
        raise ValueError('Parent gable review changed during partial gable build')
    for root, name, pin in [(profile, 'facade-profile.json', 'source_profile_sha256'),
            (preview, 'facade-preview.json', 'source_preview_sha256'), (components, 'component-report.json', 'component_report_sha256'),
            (views, 'view-report.json', 'view_report_sha256')]:
        if file_hash(root / name) != previous['contract'][pin]:
            raise ValueError('Parent source contract changed during partial gable build')
    for receipt in roof._load(preview / 'facade-preview.json')['source_crop_receipts']:
        if file_hash(preview / receipt['file']) != receipt['png_sha256']:
            raise ValueError('Parent source crop changed during partial gable build')
    for group in roof._load(profile / 'facade-profile.json')['profiles']:
        for variant in group['variants']:
            for name in ('roof', 'wall'):
                receipt = variant.get(name + '_mask_receipt')
                if receipt and file_hash(profile / receipt['file']) != receipt['png_sha256']:
                    raise ValueError('Parent source mask changed during partial gable build')
    scans = [v for row in result['views'] for v in row['variants']]
    pairs = [p for v in scans for p in v['pairs']]
    result['counts'] = {'source_views': len(result['views']), 'short_source_lines': sum(len(v['lines']) for v in scans),
        'original_short_source_pixels': sum(len(l['source_pixels']) for v in scans for l in v['lines']),
        'partial_gable_pairs': len(pairs), 'conditional_partial_gable_pairs': sum(p['status'] == 'conditional_partial_gable_source_support' for p in pairs),
        'held_partial_gable_pairs': sum(p['status'] == 'partial_gable_source_check_held' for p in pairs),
        'cross_threshold_checks': sum(len(v['threshold_checks']) for v in result['views']),
        'views_with_cross_threshold_support': sum(v['source_threshold_status'] == 'conditional_source_threshold_support' for v in result['views']),
        'new_roof_models': 0}
    if len(json.dumps(result).encode()) > 64000000:
        raise ValueError('Partial gable output budget exceeded')
    root = output / digest(contract)
    if root.exists():
        if digest(roof._load(root / 'partial-gables.json')) != digest(result):
            raise ValueError('Saved partial gable review changed')
    else:
        atomic_json(root / 'partial-gables.json', result)
    return {**result, 'directory': str(root)}
