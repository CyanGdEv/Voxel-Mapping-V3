"""Metre-based boundary measurements and mixed-source correction fitting.

Image sampling and reference uncertainty remain explicit. A missing boundary is
penalized, not dropped. No test-site data may enter fitting or setting selection.
"""
import numpy as np
from scipy import ndimage

from . import aerial_marker_correction as correction, aerial_marker_errors as legacy

VERSION = 'metric-surface-boundary-learning-v1'


def spacing_xy(spacing):
    s = np.asarray([spacing, spacing] if np.isscalar(spacing) else spacing, float)
    if s.shape != (2,) or not np.isfinite(s).all() or (s < .05).any() or (s > 1.).any():
        raise ValueError('Finite physical x/y image sampling in metres required')
    return s


def metric_direction(reference, shape, spacing):
    point, normal = legacy.validate_reference(reference, (shape[1], shape[0]))
    s = spacing_xy(spacing)
    ground_normal = normal / s
    ground_normal /= np.linalg.norm(ground_normal)
    return point, ground_normal / s


def measure(prediction, reference, spacing, radius_m=4., step_m=.02, probe_m=.5):
    if (prediction.ndim != 2 or prediction.size > 1048576
            or not set(np.unique(prediction)) <= {0, 1, 2, 3}
            or not .5 <= radius_m <= 6 or not .01 <= step_m <= .1
            or not .2 <= probe_m <= 1.5):
        raise ValueError('Bounded categorical grid and physical transect required')
    point, direction = metric_direction(reference, prediction.shape, spacing)
    distance = np.linspace(-radius_m, radius_m, round(2 * radius_m / step_m) + 1)
    xy = point + distance[:, None] * direction
    if ((xy[:, 0] < 0).any() or (xy[:, 1] < 0).any()
            or (xy[:, 0] >= prediction.shape[1]).any()
            or (xy[:, 1] >= prediction.shape[0]).any()):
        raise ValueError('Complete metric transect must be inside the source image')
    inside = ndimage.map_coordinates((prediction == reference['class']).astype(np.uint8),
                                     [xy[:, 1], xy[:, 0]], order=0, mode='nearest')
    # Approximately 0.08 m median support, independent of image pixel sampling.
    kernel = max(1, round(.08 / step_m)) | 1
    inside = ndimage.median_filter(inside, size=kernel, mode='nearest')
    crossed = np.flatnonzero((inside[:-1] == 1) & (inside[1:] == 0))
    candidates = (distance[crossed] + distance[crossed + 1]) / 2
    delta = float(candidates[np.argmin(np.abs(candidates))]) if len(candidates) else None
    probe_xy = point + np.array([-probe_m, probe_m])[:, None] * direction
    classes = ndimage.map_coordinates(prediction, [probe_xy[:, 1], probe_xy[:, 0]], order=0)
    uncertainty = reference.get('uncertainty_m')
    if uncertainty is None or not np.isfinite(uncertainty) or not 0 <= uncertainty < radius_m:
        raise ValueError('Explicit bounded source-reference uncertainty in metres required')
    outside = reference.get('outside_class')
    opposite = classes[1] == outside if outside is not None else classes[1] != reference['class']
    error = abs(delta) if delta is not None else radius_m
    return {'id': reference['id'], 'class': reference['class'], 'outside_class': outside,
            'source_point_xy': point.tolist(), 'normal_xy': reference['normal_xy'],
            'spacing_m_xy': spacing_xy(spacing).tolist(), 'directed_crossings': len(crossed),
            'missing_marker': delta is None, 'signed_offset_m': delta,
            'absolute_error_m': abs(delta) if delta is not None else None,
            'capped_error_m': error, 'uncertainty_excess_m': max(0., error - uncertainty),
            'reference_uncertainty_m': float(uncertainty),
            'marker_xy': (point + delta * direction).tolist() if delta is not None else None,
            'inside_outside_probes_correct': bool(classes[0] == reference['class'] and opposite),
            'probe_evaluable_beyond_reference_uncertainty': uncertainty < probe_m,
            'search_cap_m': radius_m, 'probe_distance_m': probe_m}


def summarise(rows):
    result = legacy.summarise(rows)
    result['uncertainty_excess_mean_m'] = float(np.mean([r['uncertainty_excess_m'] for r in rows])) if rows else None
    result['reference_uncertainty_mean_m'] = float(np.mean([r['reference_uncertainty_m'] for r in rows])) if rows else None
    result['probe_evaluable_samples'] = sum(r['probe_evaluable_beyond_reference_uncertainty'] for r in rows)
    result['scope'] = 'Physical normal offsets relative to source-assisted aerial edges, with explicit uncertainty; not surveyed or independent human truth.'
    return result


def guard(shape, references, spacing, guard_m=4.):
    s = spacing_xy(spacing)
    yy, xx = np.ogrid[:shape[0], :shape[1]]
    allowed = np.ones(shape, bool)
    for r in references:
        if r.get('role') == 'calibration_check':
            p, _ = legacy.validate_reference(r, (shape[1], shape[0]))
            allowed &= ((xx - p[0]) * s[0]) ** 2 + ((yy - p[1]) * s[1]) ** 2 > guard_m ** 2
    return allowed


def reference_band(reference, shape, spacing, half_normal_m=1.5, half_tangent_m=.25):
    point, direction = metric_direction(reference, shape, spacing)
    s = spacing_xy(spacing)
    normal = direction * s
    tangent = np.array([-normal[1], normal[0]])
    radius = int(np.ceil((half_normal_m + half_tangent_m) / s.min())) + 2
    x0, x1 = max(0, int(point[0] - radius)), min(shape[1], int(point[0] + radius + 1))
    y0, y1 = max(0, int(point[1] - radius)), min(shape[0], int(point[1] + radius + 1))
    yy, xx = np.mgrid[y0:y1, x0:x1]
    dx, dy = (xx - point[0]) * s[0], (yy - point[1]) * s[1]
    d, t = dx * normal[0] + dy * normal[1], dx * tangent[0] + dy * tangent[1]
    unknown = max(float(reference['uncertainty_m']), .12)
    scope = (np.abs(d) <= half_normal_m) & (np.abs(t) <= half_tangent_m)
    target = np.full(scope.shape, 255, np.uint8)
    target[scope & (d < -unknown)] = reference['class']
    if reference.get('outside_class') is not None:
        target[scope & (d > unknown)] = reference['outside_class']
    return (slice(y0, y1), slice(x0, x1)), target


def sample_source(features, target, references, baseline, spacing, settings, seed=137):
    if any(r.get('role') not in ('calibration_fit', 'calibration_check') for r in references):
        raise ValueError('Only development references may supply correction fitting pixels')
    if (features.shape != (*target.shape, len(correction.FEATURES))
            or baseline.shape != target.shape or not np.isfinite(features).all()
            or not set(np.unique(target)) <= {0, 1, 2, 3, 255}):
        raise ValueError('Matching bounded source features and observed masks required')
    s = spacing_xy(spacing)
    allowed = guard(target.shape, references, s)
    rng = np.random.default_rng(seed)
    coords, labels, weights, boundary = [], [], [], []
    counts, bands = [], []
    for c in range(4):
        erosion = max(1, int(np.ceil(.3 / s.min())))
        points = np.argwhere(ndimage.binary_erosion(target == c, iterations=erosion) & allowed)
        if len(points) > settings['interior_per_class_per_source']:
            points = points[rng.choice(len(points), settings['interior_per_class_per_source'], replace=False)]
        coords.extend(points)
        labels.extend([c] * len(points))
        weights.extend((1 + settings['hard_error_multiplier'] * (baseline[points[:, 0], points[:, 1]] != c)).tolist())
        boundary.extend([False] * len(points))
        counts.append(len(points))
    for r in references:
        if r['role'] != 'calibration_fit':
            continue
        sl, band = reference_band(r, target.shape, s)
        points = np.argwhere((band != 255) & allowed[sl])
        labels.extend(band[points[:, 0], points[:, 1]].tolist())
        points += np.array([sl[0].start, sl[1].start])
        error = measure(baseline, r, s)
        weight = 1 + min(3., error['uncertainty_excess_m'] / .5)
        coords.extend(points)
        weights.extend([weight] * len(points))
        boundary.extend([True] * len(points))
        bands.append({'id': r['id'], 'pixels': len(points), 'weight': weight,
                      'baseline_error_m': error['capped_error_m']})
    yx = np.asarray(coords, int)
    if not len(yx) or not allowed[yx[:, 0], yx[:, 1]].all():
        raise ValueError('Fitting samples must stay outside every metric check guard')
    return {'x': features[yx[:, 0], yx[:, 1]], 'y': np.asarray(labels, np.int64),
            'weight': np.asarray(weights, np.float32), 'boundary': np.asarray(boundary, bool),
            'coordinates_yx': yx,
            'report': {'evaluation_only': False, 'interior_counts': counts, 'bands': bands,
                       'fit_guard_m': 4., 'samples': len(yx), 'spacing_m_xy': s.tolist()}}


def fit(samples, settings):
    import torch
    from torch.nn import functional as F
    if (not samples or any(s['report'].get('evaluation_only') is not False for s in samples)
            or not 1 <= settings['steps'] <= 1200 or not 32 <= settings['batch'] <= 4096
            or not 0 <= settings['boundary_draw_fraction'] <= .5 or settings['hidden'] != [32, 16]):
        raise ValueError('Bounded development-only metric correction fit required')
    torch.set_num_threads(2)
    torch.manual_seed(settings['seed'])
    torch.use_deterministic_algorithms(True)
    x, y, weight, boundary = [np.concatenate([s[k] for s in samples]) for k in ('x', 'y', 'weight', 'boundary')]
    if (x.shape != (len(y), 27) or len(y) > settings['maximum_training_samples']
            or set(np.unique(y)) != {0, 1, 2, 3} or not np.isfinite(x).all()
            or not np.isfinite(weight).all() or (weight <= 0).any()):
        raise ValueError('Finite mixed-source four-class training samples required')
    interior, edge = np.flatnonzero(~boundary), np.flatnonzero(boundary)
    if not len(interior):
        raise ValueError('Observed source interiors required')
    tx, ty, tw = torch.from_numpy(x), torch.from_numpy(y), torch.from_numpy(weight)
    counts = np.bincount(y, minlength=4)
    class_weight = torch.from_numpy((1 / np.sqrt(counts) / (1 / np.sqrt(counts)).mean()).astype(np.float32))
    model = correction.architecture()
    initial = {k: v.detach().clone() for k, v in model.state_dict().items()}
    optimizer = torch.optim.AdamW(model.parameters(), lr=settings['learning_rate'], weight_decay=settings['weight_decay'])
    rng = np.random.default_rng(settings['seed'])
    pools = {'interior': [], 'boundary': []}
    offset = 0
    for sample in samples:
        availability = bool(sample['x'][0, 26])
        for key, mask in [('interior', ~sample['boundary']), ('boundary', sample['boundary'])]:
            pool = np.flatnonzero(mask) + offset
            if len(pool):
                pools[key].append((availability, pool))
        offset += len(sample['y'])

    def draw(key, n):
        if not n:
            return np.empty(0, int)
        available = sorted({g for g, _ in pools[key]})
        groups = rng.choice(available, n)
        out = np.empty(n, int)
        for group in available:
            places = np.flatnonzero(groups == group)
            sources = [pool for g, pool in pools[key] if g == group]
            choices = rng.integers(len(sources), size=len(places))
            for i, pool in enumerate(sources):
                selected = places[choices == i]
                out[selected] = rng.choice(pool, len(selected))
        return out

    history, edge_draws = [], 0
    for step in range(settings['steps']):
        n = round(settings['batch'] * settings['boundary_draw_fraction']) if len(edge) else 0
        indices = np.r_[draw('interior', settings['batch'] - n), draw('boundary', n)]
        edge_draws += n
        values = tx[indices].clone()
        drop = torch.from_numpy(rng.random(len(indices)) < settings['cir_dropout'])
        values[drop, 3:6] = 0
        values[drop, 9] = 0
        values[drop, 26] = 0
        residual = model(values)
        logits = values[:, 10:14].clamp(min=1e-7).log() + residual
        loss = (F.cross_entropy(logits, ty[indices], weight=class_weight, reduction='none') * tw[indices]).sum() / tw[indices].sum()
        loss += .002 * residual.square().mean()
        if not torch.isfinite(loss):
            raise ValueError('Finite mixed-source correction loss required')
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        if step in (0, settings['steps'] - 1) or (step + 1) % 100 == 0:
            history.append({'step': step + 1, 'loss': float(loss.detach())})
    return model.eval(), {'version': VERSION, 'settings': settings, 'history': history,
                          'samples': len(y), 'class_counts': counts.tolist(),
                          'boundary_samples': int(boundary.sum()), 'boundary_draws': edge_draws,
                          'sampling_balance': 'Uniform availability group, then uniform source within group; separate interior and boundary draws.',
                          'source_reports': [s['report'] for s in samples],
                          'parameter_change_l2': float(sum((v.detach() - initial[k]).square().sum() for k, v in model.state_dict().items()).sqrt()),
                          'parameter_count': sum(p.numel() for p in model.parameters()),
                          'coordinates_used_as_features': False}


def select(candidates, group, limits):
    if not candidates or group not in ('rgb_only', 'rgb_cir'):
        raise ValueError('Declared source-availability calibration group required')
    if any(c.get('role') != 'calibration_check' or c.get('group') != group for c in candidates):
        raise ValueError('Fresh sources cannot select metric correction settings')
    if any(c['errors'].get('uncertainty_excess_mean_m') is None or c['errors'].get('capped_mean_error_m') is None for c in candidates):
        raise ValueError('Observed calibration boundary checks required for each availability group')
    eligible = [c for c in candidates if c['worst_source_macro_iou_delta'] >= -limits['maximum_source_macro_iou_regression']
                and c['worst_source_present_class_iou_delta'] >= -limits['maximum_source_present_class_iou_regression']]
    if not eligible:
        raise ValueError('Baseline candidate must be eligible')
    return min(eligible, key=lambda c: (c['errors']['uncertainty_excess_mean_m'],
                                        c['errors']['capped_mean_error_m'], c['alpha']))
