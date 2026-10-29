"""Experimental source-colour/height residual correction of frozen surface markers.

No coordinates, reference distances or site identifiers enter the network. Source
review supplies a small set of boundary bands; nearby check pixels stay excluded.
The encoder, ground baseline and canopy output remain frozen.
"""
from pathlib import Path
import json

import numpy as np
from scipy import ndimage

from .aerial_marker_errors import fit_guard, reference_band, measure
from .desktop_memory import digest
from .generation_cycles import atomic_json, file_hash

VERSION = 'aerial-marker-residual-correction-v1'
FEATURES = ('rgb_r', 'rgb_g', 'rgb_b', 'cir_r', 'cir_g', 'cir_b',
            'chromatic_r', 'chromatic_g', 'chromatic_b', 'cir_excess_red',
            'base_paving', 'base_structure', 'base_grass', 'base_water',
            'height', 'slope', 'roughness', 'height_valid', 'brightness',
            'mean_r', 'mean_g', 'mean_b', 'std_r', 'std_g', 'std_b',
            'rgb_gradient', 'cir_present')


def validate_probabilities(probabilities):
    p = np.asarray(probabilities)
    if (p.ndim != 3 or p.shape[2] != 4 or p.shape[0] * p.shape[1] > 1048576
            or min(p.shape[:2]) < 8 or not np.isfinite(p).all()
            or p.min() < 0 or p.max() > 1
            or not np.allclose(p.sum(2), 1, atol=2e-5)):
        raise ValueError('Bounded normalized four-class probabilities required')
    return p


def descriptors(rgb, cir, height, probabilities):
    """Native-grid visible colour cues, experimental CIR colours and dated heights."""
    p = validate_probabilities(probabilities)
    if (rgb.dtype != np.uint8 or rgb.shape != (*p.shape[:2], 3)
            or height.shape != (*p.shape[:2], 4)
            or not np.isfinite(height).all()
            or (cir is not None and (cir.dtype != np.uint8 or cir.shape != rgb.shape))):
        raise ValueError('Matching RGB, optional CIR and finite relative height grid required')
    x = rgb.astype(np.float32) / 255
    ir = cir.astype(np.float32) / 255 if cir is not None else np.zeros_like(x)
    chromatic = x / np.maximum(x.sum(2, keepdims=True), .05)
    excess = np.clip(.5 + (ir[:, :, 0] - ir[:, :, 1:3].mean(2)) / 2, 0, 1)
    if cir is None:
        excess[:] = 0
    mean = ndimage.uniform_filter(x, size=(3, 3, 1), mode='reflect')
    variance = np.maximum(ndimage.uniform_filter(x * x, size=(3, 3, 1), mode='reflect') - mean * mean, 0)
    brightness = x.mean(2)
    gradient = np.clip(np.hypot(ndimage.sobel(brightness, 0), ndimage.sobel(brightness, 1)) / 2, 0, 1)
    result = np.concatenate([x, ir, chromatic, excess[:, :, None], p, height,
                             brightness[:, :, None], mean, np.sqrt(variance) * 4,
                             gradient[:, :, None], np.full((*p.shape[:2], 1), cir is not None, np.float32)], 2)
    if not np.isfinite(result).all():
        raise ValueError('Finite correction descriptors required')
    return result.astype(np.float32)


def architecture():
    from torch import nn
    model = nn.Sequential(nn.Linear(len(FEATURES), 32), nn.ReLU(),
                          nn.Linear(32, 16), nn.ReLU(), nn.Linear(16, 4))
    # Initial residual is identically zero, preserving the frozen baseline.
    nn.init.zeros_(model[-1].weight)
    nn.init.zeros_(model[-1].bias)
    return model


def sample_source(features, target, references, baseline, settings, seed=137):
    """Fit interiors plus error-weighted observed boundary bands; check guard first."""
    if any(r.get('role') not in ('calibration_fit', 'calibration_check') for r in references):
        raise ValueError('Fresh-check references cannot enter correction fitting')
    if features.shape != (*target.shape, len(FEATURES)) or baseline.shape != target.shape:
        raise ValueError('Matching correction grids required')
    if not set(np.unique(target)) <= {0, 1, 2, 3, 255}:
        raise ValueError('Observed four-class mask with unknowns required')
    allowed = fit_guard(target.shape, references, guard_m=4.)
    # Erode draft interiors to avoid teaching the approximate source-mask edges.
    rng = np.random.default_rng(seed)
    coords, labels, weights = [], [], []
    interior_counts = []
    for c in range(4):
        candidates = np.argwhere(ndimage.binary_erosion(target == c, iterations=4) & allowed)
        if len(candidates) > settings['interior_per_class_per_source']:
            candidates = candidates[rng.choice(len(candidates), settings['interior_per_class_per_source'], replace=False)]
        coords.extend(candidates)
        labels.extend([c] * len(candidates))
        weights.extend([1.] * len(candidates))
        interior_counts.append(len(candidates))
    bands = []
    for r in references:
        if r['role'] != 'calibration_fit':
            continue
        sl, band = reference_band(r, target.shape,
                                  settings['boundary_band_half_normal_px'],
                                  settings['boundary_band_half_tangent_px'],
                                  settings['boundary_unknown_half_width_px'])
        yx = np.argwhere((band != 255) & allowed[sl])
        error = measure(baseline, r)
        weight = 1 + min(3., error['capped_error_m'] / .5)
        labels.extend(band[yx[:, 0], yx[:, 1]].tolist())
        yx += np.array([sl[0].start, sl[1].start])
        coords.extend(yx)
        weights.extend([weight] * len(yx))
        bands.append({'id': r['id'], 'pixels': len(yx), 'weight': weight,
                      'baseline_capped_error_m': error['capped_error_m']})
    yx = np.asarray(coords, int)
    if not len(yx) or not allowed[yx[:, 0], yx[:, 1]].all():
        raise ValueError('Guarded fitting pixels required')
    return {'x': features[yx[:, 0], yx[:, 1]], 'y': np.asarray(labels, np.int64),
            'weight': np.asarray(weights, np.float32), 'coordinates_yx': yx,
            'report': {'interior_counts': interior_counts, 'bands': bands,
                       'check_guard_m': 4., 'guarded_pixels': int((~allowed).sum()),
                       'sample_count': len(yx), 'evaluation_only': False}}


def fit(samples, settings):
    import torch
    from torch.nn import functional as F
    if (not samples or any(s['report'].get('evaluation_only') is not False for s in samples)
            or not 1 <= settings['steps'] <= 1200 or not 32 <= settings['batch'] <= 4096
            or not 0 <= settings['cir_dropout'] <= .5 or settings['hidden'] != [32, 16]):
        raise ValueError('Bounded calibration-only residual fitting required')
    torch.set_num_threads(2)
    torch.manual_seed(settings['seed'])
    torch.use_deterministic_algorithms(True)
    x = np.concatenate([s['x'] for s in samples])
    y = np.concatenate([s['y'] for s in samples])
    weight = np.concatenate([s['weight'] for s in samples])
    if (x.ndim != 2 or x.shape[1] != len(FEATURES) or len(x) > 150000
            or not np.isfinite(x).all() or set(np.unique(y)) != {0, 1, 2, 3}
            or len(y) != len(x) or weight.shape != y.shape
            or not np.isfinite(weight).all() or (weight <= 0).any()):
        raise ValueError('Finite balanced observed calibration samples required')
    counts = np.bincount(y, minlength=4)
    class_weight = torch.from_numpy((1 / np.sqrt(counts) / (1 / np.sqrt(counts)).mean()).astype(np.float32))
    tx, ty, tw = torch.from_numpy(x), torch.from_numpy(y), torch.from_numpy(weight)
    model = architecture()
    initial = {k: v.detach().clone() for k, v in model.state_dict().items()}
    optimizer = torch.optim.AdamW(model.parameters(), lr=settings['learning_rate'], weight_decay=settings['weight_decay'])
    rng = np.random.default_rng(settings['seed'])
    history = []
    for step in range(settings['steps']):
        indices = rng.integers(len(x), size=settings['batch'])
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
            raise ValueError('Finite residual loss required')
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        if step in (0, settings['steps'] - 1) or (step + 1) % 100 == 0:
            history.append({'step': step + 1, 'loss': float(loss.detach())})
    return model.eval(), {'settings': settings, 'history': history,
                          'class_counts': counts.tolist(), 'samples': len(x),
                          'parameter_count': sum(p.numel() for p in model.parameters()),
                          'parameter_change_l2': float(sum((v.detach() - initial[k]).square().sum() for k, v in model.state_dict().items()).sqrt()),
                          'residual_l2_penalty': .002, 'coordinates_used_as_features': False,
                          'cir_is_calibrated_reflectance': False, 'cpu_threads': 2}


def residuals(model, features):
    import torch
    if features.ndim != 3 or features.shape[2] != len(FEATURES) or features.shape[0] * features.shape[1] > 1048576 or not np.isfinite(features).all():
        raise ValueError('Bounded finite correction descriptors required')
    flat = features.reshape(-1, len(FEATURES))
    out = np.empty((len(flat), 4), np.float32)
    model.eval()
    with torch.no_grad():
        for i in range(0, len(flat), 65536):
            out[i:i + 65536] = model(torch.from_numpy(flat[i:i + 65536])).numpy()
    return out.reshape(*features.shape[:2], 4)


def corrected_probabilities(probabilities, residual, rgb, cir, alpha, smoothing, steps=5):
    from scipy.special import softmax
    p = validate_probabilities(probabilities)
    if (residual.shape != p.shape or not np.isfinite(residual).all()
            or alpha not in (0., .25, .5, .75, 1.) or smoothing not in (0., 1.)
            or not 1 <= steps <= 5 or rgb.shape != (*p.shape[:2], 3)
            or (cir is not None and cir.shape != rgb.shape)):
        raise ValueError('Declared bounded source-aware correction required')
    unary = np.log(np.maximum(p, 1e-7)) + alpha * residual
    q = softmax(unary, axis=2).astype(np.float32)
    if not smoothing:
        return q
    colour = rgb.astype(np.float32) / 255
    ir = cir.astype(np.float32) / 255 if cir is not None else None
    pairs = []
    for axis in (0, 1):
        a = (slice(1, None), slice(None)) if axis == 0 else (slice(None), slice(1, None))
        b = (slice(None, -1), slice(None)) if axis == 0 else (slice(None), slice(None, -1))
        difference = np.square(colour[a] - colour[b]).sum(2) / (2 * .15 ** 2)
        if ir is not None:
            difference += .5 * np.square(ir[a] - ir[b]).sum(2) / (2 * .18 ** 2)
        pairs.append((a, b, np.exp(-difference)[:, :, None]))
    for _ in range(steps):
        message = np.zeros_like(q)
        denominator = np.zeros((*q.shape[:2], 1), np.float32)
        for a, b, weight in pairs:
            message[a] += weight * q[b]
            message[b] += weight * q[a]
            denominator[a] += weight
            denominator[b] += weight
        q = softmax(unary + smoothing * message / np.maximum(denominator, 1e-7), axis=2).astype(np.float32)
    return q


def choose(candidates, baseline_mean_error, maximum_regression=.05):
    """Only calibration records can select the sealed inference settings."""
    if not candidates or any(r.get('role') != 'calibration_check' for r in candidates):
        raise ValueError('Only calibration check scores may select correction settings')
    eligible = [r for r in candidates if r['macro_iou_delta'] >= -maximum_regression
                and r['errors']['capped_mean_error_m'] < baseline_mean_error]
    return min(eligible, key=lambda r: (r['errors']['capped_mean_error_m'], r['alpha'], r['smoothing'])) if eligible else None


def save(model, folder, training, pins, selected):
    from safetensors.torch import save_file
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    save_file({k: v.detach().contiguous() for k, v in model.state_dict().items()}, str(folder / 'weights.safetensors'))
    meta = {'version': VERSION, 'features': list(FEATURES), 'training': training,
            'pins': pins, 'selected': selected, 'weights_sha256': file_hash(folder / 'weights.safetensors'),
            'production_eligible': False, 'independent_human_review': False,
            'base_and_encoder_frozen': True, 'canopy_unchanged': True}
    meta['id'] = digest(meta)
    atomic_json(folder / 'model.json', meta)
    return meta


def load(folder):
    import torch
    from safetensors import safe_open
    from safetensors.torch import load_file
    folder = Path(folder)
    m = json.loads((folder / 'model.json').read_text())
    p = folder / 'weights.safetensors'
    if (m.get('version') != VERSION or m.get('features') != list(FEATURES)
            or m.get('id') != digest({k: v for k, v in m.items() if k != 'id'})
            or m.get('production_eligible') is not False or p.stat().st_size > 100000
            or file_hash(p) != m['weights_sha256']):
        raise ValueError('Known pinned research correction checkpoint required')
    model = architecture()
    with safe_open(p, framework='pt', device='cpu') as f:
        if set(f.keys()) != set(model.state_dict()):
            raise ValueError('Known correction tensors required')
        for k, v in model.state_dict().items():
            tensor = f.get_slice(k)
            if tuple(tensor.get_shape()) != tuple(v.shape) or tensor.get_dtype() != 'F32':
                raise ValueError('Known bounded correction tensor headers required')
    state = load_file(p, device='cpu')
    if any(not torch.isfinite(v).all() or v.abs().max() > 100 for v in state.values()):
        raise ValueError('Finite bounded correction weights required')
    model.load_state_dict(state, strict=True)
    return model.eval(), m
