"""Guarded experimental paving/structure trace learning from clean RGB + LiDAR.

This classifies sparse user guide locations, not whole paving surfaces. Feature
windows never read annotation ink; held-out points are spatially separated.
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
from scipy.spatial import cKDTree

from . import aerial_semantic_network as net
from .desktop_memory import digest
from .generation_cycles import atomic_json, file_hash
from .horizontal_grid import OSTN15Transform
from .imagery_capture_quality import audit
from .ride_aerial_supervision import project_pixels

VERSION = 'tight-paving-structure-trace-head-v1'
LABELS = {'structure_trace': 0, 'paving_trace': 1}
SETTINGS = {**net.DEFAULTS, 'hidden': 48, 'epochs': 80, 'learning_rate': .007, 'regularization': .001}
HEIGHT_NAMES = ['height_above_ground', 'ground_slope', 'height_mean_4m', 'height_max_4m', 'height_std_4m', 'height_valid']


def rgb_samples(rgb, xy, metres_per_pixel, tile_size=512):
    xy = np.asarray(xy, np.int64)
    if xy.ndim != 2 or xy.shape[1] != 2 or not 1 <= len(xy) <= 100000:
        raise ValueError('Bounded clean-image sample locations required')
    if (xy < 0).any() or (xy[:, 0] >= rgb.shape[1]).any() or (xy[:, 1] >= rgb.shape[0]).any():
        raise ValueError('Sample outside clean source')
    halo = math.ceil(12/metres_per_pixel)+3
    output = np.empty((len(xy), net.FEATURE_COUNT), np.float32)
    tiles = xy//tile_size
    for col, row in np.unique(tiles, axis=0):
        selected = (tiles[:, 0] == col) & (tiles[:, 1] == row)
        x0, y0 = max(0, col*tile_size-halo), max(0, row*tile_size-halo)
        x1, y1 = min(rgb.shape[1], (col+1)*tile_size+halo), min(rgb.shape[0], (row+1)*tile_size+halo)
        features = net.features(rgb[y0:y1, x0:x1], metres_per_pixel)
        output[selected] = features[xy[selected, 1]-y0, xy[selected, 0]-x0]
    return output


def height_samples(archive, xy, metres_per_pixel):
    with np.load(archive, allow_pickle=False) as data:
        ground, surface = data['dtm_odn_m'], data['dsm_odn_m']
    valid = np.isfinite(ground) & np.isfinite(surface)
    hag = np.clip(np.nan_to_num(surface-ground, nan=0), 0, 30).astype(np.float32)
    ground = np.nan_to_num(ground, nan=float(np.nanmedian(ground)))
    smooth = ndi.uniform_filter(ground, size=2*round(1/metres_per_pixel)+1)
    dy, dx = np.gradient(smooth, metres_per_pixel)
    slope = np.clip(np.hypot(dx, dy), 0, 2)/2
    size = 2*round(4/metres_per_pixel)+1
    mean = ndi.uniform_filter(hag, size=size)
    std = np.sqrt(np.maximum(0, ndi.uniform_filter(hag*hag, size=size)-mean*mean))
    maximum = ndi.maximum_filter(hag, size=size)
    yy, xx = xy[:, 1], xy[:, 0]
    values = np.column_stack([hag[yy, xx]/30, slope[yy, xx], mean[yy, xx]/30,
                              maximum[yy, xx]/30, std[yy, xx]/10, valid[yy, xx]]).astype(np.float32)
    return values, hag[yy, xx]


def spatial_split(en, labels, *, guard_each_side_m=15):
    """Choose by label coverage only, before any fit or prediction."""
    lo, hi = np.min(en[:, 0]), np.max(en[:, 0])
    for fraction in (.65, .50, .35):
        cut = lo+(hi-lo)*fraction
        train, held = en[:, 0] < cut-guard_each_side_m, en[:, 0] >= cut+guard_each_side_m
        if all(np.count_nonzero(mask & (labels == code)) >= 32 for mask in (train, held) for code in (0, 1)):
            return train, held, {'axis': 'BNG easting', 'fraction': fraction, 'split_easting': float(cut),
                'guard_each_side_m': guard_each_side_m, 'selection': 'First predeclared fraction with >=32 of each class on both sides; no prediction used',
                'held_out_scope': 'A separate region of this same image; not a new park or independent human/survey test'}
    raise ValueError('Both classes need separated source regions for a guarded holdout')


def metrics(labels, probabilities):
    predicted = np.argmax(probabilities, axis=1)
    matrix = np.bincount(labels*2+predicted, minlength=4).reshape(2, 2)
    scores = []
    for code in (0, 1):
        tp = int(matrix[code, code]); actual = int(matrix[code].sum()); guessed = int(matrix[:, code].sum())
        recall = tp/actual if actual else None; precision = tp/guessed if guessed else 0.
        f1 = 2*tp/(actual+guessed) if actual+guessed else None
        scores.append({'class': next(k for k, v in LABELS.items() if v == code), 'samples': actual,
                       'precision': precision, 'recall': recall, 'f1': f1})
    return {'samples': len(labels), 'confusion_matrix': matrix.tolist(), 'classes': scores,
            'macro_f1': float(np.mean([s['f1'] for s in scores if s['f1'] is not None])),
            'balanced_accuracy': float(np.mean([s['recall'] for s in scores if s['recall'] is not None]))}


def choose_head(scores):
    base, height = scores['rgb'], scores['rgb_height']
    def safe(a, b):
        return b['macro_f1'] >= a['macro_f1'] and all(y['recall'] >= x['recall']-.03 for x, y in zip(a['classes'], b['classes']))
    if not safe(base['all_held_guides'], height['all_held_guides']):
        return 'rgb', 'Height model regresses overall guide score or a class recall'
    a, b = base['raised_or_canopy_context_held_guides'], height['raised_or_canopy_context_held_guides']
    if not a or not b or any(c['samples'] < 32 for s in (a, b) for c in s['classes']):
        return 'rgb', 'Insufficient separated raised/canopy evidence to select height features'
    if not safe(a, b): return 'rgb', 'Height model regresses raised/canopy guide score or a class recall'
    return 'rgb_height', 'Both overall and raised/canopy guide checks pass'


def predict_samples(features, checkpoint):
    if checkpoint.get('version') != VERSION or checkpoint.get('labels') != LABELS or checkpoint.get('production_eligible') is not False:
        raise ValueError('Research trace checkpoint required')
    if checkpoint.get('artifact_sha256') != digest({k: v for k, v in checkpoint.items() if k != 'artifact_sha256'}):
        raise ValueError('Trace checkpoint checksum differs')
    features = np.asarray(features, np.float32); count = checkpoint['feature_count']
    if count not in (31, 37) or features.ndim != 2 or features.shape[1] != count or not np.isfinite(features).all():
        raise ValueError('Matching finite trace features required')
    network = checkpoint['network']; hidden = network['settings']['hidden']
    parameters = {k: np.asarray(v, np.float32) for k, v in network['parameters'].items()}
    for k, expected in {'w1': (count, hidden), 'b1': (hidden,), 'w2': (hidden, 2), 'b2': (2,)}.items():
        if parameters[k].shape != expected or not np.isfinite(parameters[k]).all(): raise ValueError('Invalid trace network dimensions')
    mean, scale = [np.asarray(network['normalization'][k], np.float32) for k in ('mean', 'scale')]
    if mean.shape != (count,) or scale.shape != (count,) or not np.isfinite(mean).all() or not np.isfinite(scale).all() or (scale < .03).any():
        raise ValueError('Invalid trace normalization')
    return net.forward((features-mean)/scale, parameters)[1]


def train(dataset, frame_file, output):
    dataset, frame_file, output = Path(dataset), Path(frame_file), Path(output)
    if output.exists(): raise ValueError('Fresh trace training output required')
    source = json.loads((dataset/'review.json').read_text()); receipt = json.loads((dataset/'imagery-receipt.json').read_text())
    if file_hash(dataset/'model-input.png') != source['source_pins']['clean']:
        raise ValueError('Clean source changed')
    rgb = np.asarray(Image.open(dataset/'model-input.png').convert('RGB')); target = np.asarray(Image.open(dataset/'training-targets.png'))
    yy, xx = np.nonzero(np.isin(target, [10, 11])); labels = (target[yy, xx] == 11).astype(np.int64)
    xy = np.column_stack([xx, yy]); frame = json.loads(frame_file.read_text())
    project = OSTN15Transform(4326, 27700, {'method': 'ostn15-bng-v1', 'path': frame['datum_grid']['file'], 'sha256': frame['datum_grid']['sha256']})
    en = project_pixels(xy, (receipt['width'], receipt['height']), receipt['extent_epsg3857'], project)
    # Avoid counting thick ink as many independent measurements of one metre cell.
    _, selected = np.unique(np.column_stack([np.floor(en).astype(int), labels]), axis=0, return_index=True)
    selected = np.sort(selected); xy, en, labels = xy[selected], en[selected], labels[selected]
    train_mask, held_mask, split = spatial_split(en, labels)
    distance = cKDTree(en[train_mask]).query(en[held_mask], k=1)[0]
    if distance.min() <= 25: raise ValueError('Feature contexts overlap across held-out guard')
    scale = audit(receipt)['approx_export_ground_sampling_m_xy'][0]
    if file_hash(dataset/'height-context.npz') != source['height_context']['height_context_sha256']:
        raise ValueError('Height features changed')
    output.mkdir(parents=True)
    pins = {name: file_hash(dataset/name) for name in ['model-input.png', 'training-targets.png', 'reference-labels.png', 'legend.json', 'height-context.npz', 'review.json']}
    design = {'version': VERSION, 'source_pins': pins, 'settings': SETTINGS, 'labels': LABELS,
        'sampling_m_per_pixel': scale, 'sampling': 'One guide location per BNG metre cell and class; all unmarked pixels ignored',
        'split': split, 'minimum_train_to_held_distance_m': float(distance.min()), 'rgb_context_radius_m': 12,
        'rgb_model_feature_count': 31, 'height_model_feature_count': 37, 'height_features': HEIGHT_NAMES,
        'checkpoint_selection': 'Height model only if macro F1 is no worse and neither class recall falls by more than .03 overall and in a raised/canopy cohort with >=32 samples per class; otherwise RGB retained',
        'marker_rgb_used_as_features': False, 'coordinates_used_as_features': False,
        'absolute_odn_used_as_features': False, 'target_is_complete_paving_mask': False}
    atomic_json(output/'design.json', design)
    features = rgb_samples(rgb, xy, scale); height, hag = height_samples(dataset/'height-context.npz', xy, scale)
    hybrid = np.column_stack([features, height]); np.savez_compressed(output/'samples.npz', rgb=features, height=height,
        labels=labels, xy=xy, bng_en=en, training=train_mask, held_out=held_mask, height_above_ground_m=hag)
    scores, checkpoints, probabilities = {}, {}, {}
    for name, values in [('rgb', features), ('rgb_height', hybrid)]:
        fit = net.fit(values[train_mask], labels[train_mask], SETTINGS, class_count=2, feature_count=values.shape[1])
        model = {'version': VERSION, 'labels': LABELS, 'feature_count': values.shape[1],
            'feature_version': 'rgb-lab-multiscale-metres-v1' if name == 'rgb' else 'rgb-lab-multiscale-metres-plus-native-height-v1',
            'network': fit, 'source_pins': pins, 'training_samples': int(train_mask.sum()),
            'production_eligible': False, 'human_pixel_labels_verified': False, 'world_blocks_generated': 0}
        model['artifact_sha256'] = digest(model); atomic_json(output/(name+'-trace-head.json'), model)
        probability = predict_samples(values, model); checkpoints[name] = model; probabilities[name] = probability
        scores[name] = {'all_held_guides': metrics(labels[held_mask], probability[held_mask]),
            'raised_or_canopy_context_held_guides': metrics(labels[held_mask & (hag > 2)], probability[held_mask & (hag > 2)]) if np.any(held_mask & (hag > 2)) else None,
            'parameters_updated_l2': fit['weight_change_l2']}
        print('Fitted', name, scores[name]['all_held_guides']['macro_f1'], flush=True)
    choice, reason = choose_head(scores)
    np.savez_compressed(output/'predictions.npz', **probabilities)
    preview = Image.fromarray(rgb.copy()); draw = ImageDraw.Draw(preview)
    pred = probabilities[choice].argmax(axis=1)
    for (x, y), correct in zip(xy[held_mask], pred[held_mask] == labels[held_mask]):
        draw.ellipse((int(x)-1, int(y)-1, int(x)+1, int(y)+1), fill=(25, 230, 70) if correct else (255, 35, 35))
    preview.save(output/'held-guide-errors.png')
    report = {'version': VERSION, 'source_reference': source['reference_id'], 'source_pins': pins,
        'guide_samples': len(labels), 'training_samples': int(train_mask.sum()), 'held_out_samples': int(held_mask.sum()),
        'guarded_samples_ignored': int((~train_mask & ~held_mask).sum()), 'split': split,
        'minimum_train_to_held_distance_m': float(distance.min()), 'scores': scores,
        'selected_development_head': choice, 'selected_checkpoint_sha256': file_hash(output/(choice+'-trace-head.json')),
        'selection_reason': reason,
        'new_weights_trained': True, 'existing_production_weights_replaced': False, 'world_blocks_changed': 0,
        'general_accuracy_improvement_established': False, 'target_is_complete_paving_mask': False,
        'limitations': ['Single-image spatial development holdout; no independent park or surveyed boundary test.',
            'User confirms colour semantics; automatic extraction and projected hidden boundaries remain unverified.',
            'This head distinguishes paving and structure guides. It does not generate complete paving polygons or infer missing connections.',
            'LiDAR features retain native one-metre resolution and can include trees, roofs and other elevated objects; no heights are assigned to hidden paths.']}
    atomic_json(output/'report.json', report)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset', required=True); p.add_argument('--frame', required=True); p.add_argument('--output', required=True)
    a = p.parse_args(); result = train(a.dataset, a.frame, a.output)
    print(json.dumps({'selected': result['selected_development_head'], 'training': result['training_samples'], 'held': result['held_out_samples']}))


if __name__ == '__main__': main()
