"""Replay and independently check original pixels, complete local runs and intersections."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image
from rasterio.features import rasterize
from scipy import ndimage

from voxel_mapper.automatic_partial_gables import build
from voxel_mapper.generation_cycles import atomic_json, file_hash
from voxel_mapper.reconstruction_evidence_queue import digest


def audit(partial, gable, profile, preview, components, views, corpus, output):
    partial, gable, profile, preview, components, views, corpus, output = map(Path, (partial, gable, profile, preview, components, views, corpus, output))
    evidence = json.loads((partial / 'partial-gables.json').read_text())
    with tempfile.TemporaryDirectory() as temp:
        fresh = build(gable, profile, preview, components, views, corpus, temp, max_checks=evidence['contract']['max_checks'])
        fresh.pop('directory')
        assert digest(evidence) == digest(fresh)
    parent = json.loads((gable / 'gable-roof-review.json').read_text())
    sources = json.loads((views / 'view-candidates.json').read_text())
    lookup = {v['id']: v for p in sources['pages'] for v in p['views']}
    originals = {v['view_id']: v for v in parent['gable_views']}
    checked = Counter()
    for row in evidence['views']:
        original = originals[row['view_id']]
        assert row['source_exclusions_sha256'] == digest(original['source_exclusions'])
        image = views / lookup[row['view_id']]['render']['png']
        assert file_hash(image) == row['source_png_sha256']
        with Image.open(image) as im:
            gray = np.asarray(im.convert('L'))
        records = original['source_exclusions']['records']
        excluded = rasterize([(r['geometry_pixels'], 1) for r in records], out_shape=gray.shape, all_touched=True) > 0 if records else np.zeros_like(gray, bool)
        assert hashlib.sha256(excluded.astype('uint8').tobytes()).hexdigest() == original['source_exclusions']['source_mask_sha256']
        for scan in row['variants']:
            t = scan['threshold']
            old = next(s for s in original['variants'] if s['threshold'] == t)
            old_lines = {line['id']: line for line in old['lines']}
            paired = {p[k] for p in old['gable_pairs'] for k in ('left_line_id', 'right_line_id')}
            assert scan['source_unpaired_long_line_ids'] == [l['id'] for l in old['lines'] if l['id'] not in paired]
            dark = gray < t
            gx = ndimage.sobel(dark.astype(float), axis=1)
            gy = ndimage.sobel(dark.astype(float), axis=0)
            orient = (np.degrees(np.arctan2(-gx, gy)) + 90) % 180 - 90
            eligible = dark & ~excluded & (abs(orient) >= 15) & (abs(orient) <= 65) & (np.hypot(gx, gy) >= 1)
            y, x = np.nonzero(eligible)
            angles = orient[y, x]
            lines = {line['id']: line for line in scan['lines']}
            assert len(x) == scan['eligible_source_edge_pixels']
            for line in scan['lines']:
                pts = line['source_pixels']
                xx = np.array([p['x'] for p in pts]); yy = np.array([p['y'] for p in pts])
                assert eligible[yy, xx].all()
                assert all(p['gray'] == gray[p['y'], p['x']] and p['role'] == ('fit' if p['x'] % 2 == 0 else 'check') for p in pts)
                assert len(pts) >= 24 and 24 <= xx.max() - xx.min() < 64
                assert [int(xx.min()), int(xx.max())] == line['source_x_interval']
                columns = np.unique(xx)
                assert np.diff(columns).max() <= 4
                assert line['unsupported_column_intervals'] == [[int(a+1), int(b)] for a,b in zip(columns[:-1], columns[1:]) if b>a+1]
                fit = xx % 2 == 0
                # Separate covariance regression; no call to the kernel's least-squares solver.
                dx = xx[fit] - xx[fit].mean()
                slope = float(dx @ (yy[fit] - yy[fit].mean()) / (dx @ dx))
                intercept = float(yy[fit].mean() - slope * xx[fit].mean())
                assert abs(slope - line['slope']) < 1e-10 and abs(intercept - line['intercept']) < 1e-8
                residual = abs(slope * xx + intercept - yy) / np.hypot(slope, 1)
                assert abs(residual[fit].max() - line['fit_max_normal_residual_pixels']) < 1e-8
                assert abs(residual[~fit].max() - line['check_max_normal_residual_pixels']) < 1e-8
                for seed in line['hough_seeds']:
                    rad = np.radians(seed['angle_degrees'])
                    normal = y * np.cos(rad) - x * np.sin(rad)
                    window = abs(angles - seed['angle_degrees']) <= 12
                    assert np.count_nonzero(window & (np.rint(normal) == seed['normal_offset_pixels'])) == seed['votes']
                    ids = np.flatnonzero(window & (abs(normal - seed['normal_offset_pixels']) <= 1.5))
                    ids = ids[np.lexsort((y[ids], x[ids]))]
                    assert hashlib.sha256(np.asarray(sorted((y[ids]*gray.shape[1]+x[ids]).tolist()),dtype='<u8').tobytes()).hexdigest() == seed['whole_seed_membership_sha256']
                    # Independently walk the full ordered seed, splitting on original column gaps.
                    groups, current, previous_x = [], [], None
                    for index in ids:
                        if previous_x is not None and x[index] - previous_x > 4:
                            groups.append(current); current = []
                        current.append(int(index)); previous_x = x[index]
                    if current: groups.append(current)
                    matching = [g for g in groups if [int(x[g[0]]), int(x[g[-1]])] == seed['local_group_source_x_interval']]
                    assert len(matching) == 1
                    indices = matching[0]
                    assert list(zip(x[indices].tolist(), y[indices].tolist())) == list(zip(xx.tolist(), yy.tolist()))
                    checked['whole_original_hough_groups'] += 1
                assert not line['source_gaps_filled'] and line['source_points_removed_after_fit'] == 0
                assert not line['physical_roof_edge_verified']
                checked['original_short_source_pixels'] += len(pts)
                checked['separate_covariance_fits'] += 1
            for pair in scan['pairs']:
                long = old_lines[pair['source_long_line_id']]; short = lines[pair['source_short_line_id']]
                assert long['id'] not in paired
                left, right = (long, short) if long['slope'] < 0 else (short, long)
                # Separate 2x2 system checks the inferred ridge.
                point = np.linalg.solve([[-left['slope'], 1.], [-right['slope'], 1.]], [left['intercept'], right['intercept']])
                assert np.allclose(point, pair['inferred_ridge_pixel'], rtol=0, atol=1e-9)
                assert abs((row['printed_level_pixel']-point[1])*row['nominal_metres_per_pixel'] - pair['nominal_ridge_height_m']) < 1e-9
                ends = [abs(point[0]-left['source_x_interval'][1]), abs(point[0]-right['source_x_interval'][0])]
                pitch = abs(math.degrees(math.atan(left['slope']))) - abs(math.degrees(math.atan(right['slope'])))
                assert np.allclose(ends, pair['source_ridge_end_errors_pixels'], rtol=0, atol=1e-9)
                assert abs(abs(pitch)-pair['pitch_difference_degrees']) < 1e-9
                assert pair['source_ridge_at_visible_support_ends'] == (max(ends) <= 12)
                assert (pair['status'] == 'conditional_partial_gable_source_support') == (max(ends) <= 12 and abs(pitch) <= 2)
                assert pair['independent_depth_measurement_m'] is pair['complete_wing_mesh'] is None
                assert not pair['world_placement_eligible'] and not pair['physical_gable_identity_verified'] and not pair['source_long_line_refitted']
                checked['independent_partial_intersections'] += 1
            checked['source_threshold_variants'] += 1
        pair_lookup = {p['id']: p for scan in row['variants'] for p in scan['pairs']}
        for c in row['threshold_checks']:
            a, b = [pair_lookup[k] for k in c['threshold_pair_ids']]
            distance = math.sqrt(sum((x-y)**2 for x,y in zip(a['inferred_ridge_pixel'], b['inferred_ridge_pixel'])))
            errors = [abs(a[k]-b[k]) for k in ('left_pitch_degrees','right_pitch_degrees')]
            assert abs(distance-c['ridge_distance_source_pixels']) < 1e-9
            assert c['pitch_differences_degrees'] == errors
            assert (c['status']=='source_threshold_measurements_agree') == (distance <= 4 and max(errors) <= 2)
            assert not c['lines_refitted'] and not c['physical_correspondence_verified']
            checked['cross_threshold_comparisons'] += 1
        assert (row['source_threshold_status']=='conditional_source_threshold_support') == any(c['status']=='source_threshold_measurements_agree' for c in row['threshold_checks'])
    assert evidence['new_roof_models'] == [] and not evidence['parent_models_changed'] and not evidence['world_placement_eligible']
    assert evidence['accepted_physical_components'] == evidence['world_geometry_additions'] == evidence['training_labels_generated'] == 0
    result = {'version': 'automatic-partial-gable-audit-v1', 'status': 'passed', 'fresh_replay_identical': True,
        'source_review_sha256': file_hash(partial/'partial-gables.json'), 'parent_review_sha256': file_hash(gable/'gable-roof-review.json'),
        'counts': evidence['counts'], 'checked': dict(checked), 'world_geometry_additions': 0,
        'scope': 'Short original strokes and competing inferred partial ridges; no complete wing, eaves, plan depth or physical correspondence acceptance.'}
    atomic_json(output, result)
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('partial', 'gable', 'profile', 'preview', 'components', 'views', 'corpus', 'output'):
        parser.add_argument('--'+key, type=Path, required=True)
    a = parser.parse_args()
    print(json.dumps(audit(a.partial,a.gable,a.profile,a.preview,a.components,a.views,a.corpus,a.output)))
