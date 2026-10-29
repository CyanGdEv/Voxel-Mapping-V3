"""Measure source-bound marker errors, calibrate, then score one excluded park crop."""
import argparse
from datetime import datetime, timezone
import gc
import json
from pathlib import Path
import resource
import time

import numpy as np
from PIL import Image

from . import aerial_marker_correction as correction, aerial_marker_errors as errors
from . import aerial_surface_encoder as aerial, layered_surface_learning as net
from .generation_cycles import atomic_json, file_hash


def confusion(target, prediction):
    known = target != 255
    return np.bincount(4 * target[known].astype(int) + prediction[known], minlength=16).reshape(4, 4)


def scores(matrix):
    support = matrix.sum(1)
    union = support + matrix.sum(0) - matrix.diagonal()
    iou = np.divide(matrix.diagonal(), union, out=np.zeros(4), where=union > 0)
    return {'confusion': matrix.tolist(), 'support': support.tolist(),
            'iou': [float(v) if support[i] else None for i, v in enumerate(iou)],
            'macro_iou': float(iou[support > 0].mean()) if (support > 0).any() else 0.}


def source_root(parent, work, site):
    return (work if site == 'duinrell' else parent) / 'sources' / site


def prepare(parent, work, site, baseline, encoder):
    """Serial native-grid inference; assert old calibration outputs did not change."""
    root = source_root(parent, work, site)
    rgb = np.array(Image.open(root / 'source-image.jpg').convert('RGB'))
    cir = np.array(Image.open(root / 'infrared.jpg').convert('RGB'))
    height_path = (work / 'height' if site == 'duinrell' else parent / 'caches/native_rgb/lidar-features') / (site + '.npz')
    height_meta = json.loads(height_path.with_suffix('.json').read_text())
    if height_meta['features_sha256'] != file_hash(height_path) or height_meta['image_sha256'] != file_hash(root / 'source-image.jpg'):
        raise ValueError('Pinned source-aligned height context required')
    with np.load(height_path, allow_pickle=False) as f:
        height = f['features']
    if site == 'duinrell':
        feature = aerial.Encoder(encoder).features(rgb)
    else:
        feature_path = parent / 'caches/native_rgb/features' / (site + '.npz')
        meta = json.loads(feature_path.with_suffix('.json').read_text())
        if meta['features_sha256'] != file_hash(feature_path) or meta['encoder_sha256'] != aerial.WEIGHTS:
            raise ValueError('Pinned frozen aerial descriptors required')
        with np.load(feature_path, allow_pickle=False) as f:
            feature = f['features']
    if not np.array_equal(feature[:, :, :3], rgb.astype(np.float32) / 255):
        raise ValueError('Clean source RGB must match the frozen feature grid exactly')
    print('Predicting frozen base', site, flush=True)
    ground, canopy, uncertainty, probabilities = net.predict(baseline, np.concatenate([feature, height], 2), return_probabilities=True)
    del feature
    if site != 'duinrell':
        scope = 'fitted-efteling-not-validation' if site == 'efteling' else 'reserved-toverland'
        previous = parent / 'training/predictions' / scope / 'native_rgb'
        if (not np.array_equal(ground, np.array(Image.open(previous / 'ground.png')))
                or not np.array_equal(canopy, np.array(Image.open(previous / 'canopy.png')))):
            raise ValueError('Frozen ground/canopy output changed from the previous experiment')
    folder = work / 'prepared' / site
    folder.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(folder / 'base.npz', probabilities=probabilities)
    Image.fromarray(ground).save(folder / 'base-ground.png')
    Image.fromarray(canopy).save(folder / 'canopy.png')
    Image.fromarray(np.rint(uncertainty * 255).astype(np.uint8)).save(folder / 'uncertainty.png')
    descriptor = correction.descriptors(rgb, cir, height, probabilities)
    np.savez_compressed(folder / 'descriptors.npz', features=descriptor)
    atomic_json(folder / 'receipt.json', {
        'source_sha256': file_hash(root / 'source-image.jpg'), 'cir_sha256': file_hash(root / 'infrared.jpg'),
        'height_sha256': file_hash(height_path), 'height_receipt_sha256': file_hash(height_path.with_suffix('.json')),
        'base_probability_sha256': file_hash(folder / 'base.npz'),
        'descriptor_sha256': file_hash(folder / 'descriptors.npz'),
        'base_ground_sha256': file_hash(folder / 'base-ground.png'),
        'canopy_sha256': file_hash(folder / 'canopy.png'), 'descriptor_version': correction.VERSION,
        'site': site, 'prior_ground_canopy_exact': site != 'duinrell'})
    return descriptor, ground


def measured(ground, references, site):
    return [{**errors.measure(ground, r), 'site': site, 'role': r['role']} for r in references]


def read_prepared(parent, work, site):
    root = source_root(parent, work, site)
    folder = work / 'prepared' / site
    receipt = json.loads((folder / 'receipt.json').read_text())
    if (receipt['source_sha256'] != file_hash(root / 'source-image.jpg')
            or receipt['cir_sha256'] != file_hash(root / 'infrared.jpg')
            or receipt['base_probability_sha256'] != file_hash(folder / 'base.npz')
            or receipt['descriptor_sha256'] != file_hash(folder / 'descriptors.npz')):
        raise ValueError('Pinned prepared correction source grids required')
    rgb = np.array(Image.open(root / 'source-image.jpg').convert('RGB'))
    cir = np.array(Image.open(root / 'infrared.jpg').convert('RGB'))
    with np.load(folder / 'base.npz', allow_pickle=False) as f:
        probabilities = f['probabilities']
    with np.load(folder / 'descriptors.npz', allow_pickle=False) as f:
        features = f['features']
    return rgb, cir, probabilities, features


def run(parent, work, encoder):
    import torch
    torch.set_num_threads(2)
    start = time.monotonic()
    parent, work = Path(parent), Path(work)
    p = json.loads((work / 'protocol.json').read_text())
    refs = json.loads((work / 'references.json').read_text())
    ref_seal = json.loads((work / 'reference-seal.json').read_text())
    if (p['calibration_sites'] != ['efteling', 'toverland'] or p['fresh_check_site'] != 'duinrell'
            or p['automatic_promotion'] or p['production_eligible']
            or not refs['no_fresh_predictions_viewed']
            or ref_seal['references_sha256'] != file_hash(work / 'references.json')
            or ref_seal['protocol_sha256'] != file_hash(work / 'protocol.json')):
        raise ValueError('Sealed source references and prospectively declared crop split required')
    if (work / 'prepared').exists() or (work / 'report.json').exists():
        raise ValueError('Fresh experiment output required; a scored fresh crop is consumed')
    for site, pin in refs['sites'].items():
        root = source_root(parent, work, site)
        if pin['image_sha256'] != file_hash(root / 'source-image.jpg') or pin['cir_sha256'] != file_hash(root / 'infrared.jpg'):
            raise ValueError('Reference source image pins differ')
        expected_role = 'fresh_check' if site == p['fresh_check_site'] else None
        if expected_role and any(r['role'] != expected_role for r in refs['references'][site]):
            raise ValueError('Fresh crop must remain fully excluded from calibration')
    baseline, base_meta = net.load(parent / 'training/models/native_rgb')
    if base_meta['id'] != p['base_checkpoint_id'] or base_meta['weights_sha256'] != p['base_weights_sha256']:
        raise ValueError('Frozen declared baseline required')
    samples, baseline_rows = [], []
    for site in p['calibration_sites']:
        features, ground = prepare(parent, work, site, baseline, encoder)
        target = np.array(Image.open(parent / 'native-dataset' / site / 'ground.png'))
        sample = correction.sample_source(features, target, refs['references'][site], ground, p['corrector'])
        sample['report']['site'] = site
        samples.append(sample)
        np.savez_compressed(work / 'prepared' / site / 'fit-samples.npz',
                            x=sample['x'], y=sample['y'], weight=sample['weight'], coordinates_yx=sample['coordinates_yx'])
        baseline_rows.extend(measured(ground, refs['references'][site], site))
        del features, ground, target
        gc.collect()
    atomic_json(work / 'baseline-calibration-markers.json', baseline_rows)
    print('Fitting error-weighted residual correction', flush=True)
    model, training = correction.fit(samples, p['corrector'])
    training['source_samples'] = [s['report'] for s in samples]
    del samples
    candidates = {(a, s): {'rows': [], 'confusion': np.zeros((4, 4), np.int64)}
                  for a in p['selection']['alpha'] for s in p['selection']['smoothing']}
    base_confusion = np.zeros((4, 4), np.int64)
    for site in p['calibration_sites']:
        rgb, cir, probability, features = read_prepared(parent, work, site)
        residual = correction.residuals(model, features)
        np.savez_compressed(work / 'prepared' / site / 'residual.npz', residual=residual)
        target = np.array(Image.open(parent / 'native-dataset' / site / 'ground.png'))
        checks = [r for r in refs['references'][site] if r['role'] == 'calibration_check']
        target[errors.fit_guard(target.shape, refs['references'][site])] = 255
        base_confusion += confusion(target, probability.argmax(2))
        for (alpha, smoothing), result in candidates.items():
            q = correction.corrected_probabilities(probability, residual, rgb, cir, alpha, smoothing)
            ground = q.argmax(2).astype(np.uint8)
            result['rows'].extend(measured(ground, checks, site))
            result['confusion'] += confusion(target, ground)
        del rgb, cir, probability, features, residual, q, ground, target
        gc.collect()
    base_checks = [r for r in baseline_rows if r['role'] == 'calibration_check']
    base_check_score = scores(base_confusion)
    rows = []
    for (alpha, smoothing), result in candidates.items():
        score = scores(result['confusion'])
        rows.append({'role': 'calibration_check', 'alpha': alpha, 'smoothing': smoothing,
                     'errors': errors.summarise(result['rows']), 'pixel_scores': score,
                     'macro_iou_delta': score['macro_iou'] - base_check_score['macro_iou']})
    selected = correction.choose(rows, errors.summarise(base_checks)['capped_mean_error_m'], p['selection']['maximum_macro_iou_regression'])
    setting = {key: selected[key] for key in ('alpha', 'smoothing')} if selected else {'alpha': 0., 'smoothing': 0.}
    atomic_json(work / 'calibration-selection.json', {
        'baseline_errors': errors.summarise(base_checks), 'baseline_check_pixel_scores': base_check_score,
        'candidates': rows, 'selected': setting, 'improvement_found': selected is not None,
        'fresh_crop_used': False, 'check_pixels_excluded_from_fitting': True,
        'consumed_previous_check_site': 'toverland'})
    pins = {'protocol_sha256': file_hash(work / 'protocol.json'),
            'references_sha256': file_hash(work / 'references.json'),
            'base_checkpoint_id': base_meta['id'], 'base_weights_sha256': base_meta['weights_sha256'],
            'encoder_sha256': aerial.WEIGHTS,
            'calibration_sites': p['calibration_sites'], 'fresh_site_excluded': p['fresh_check_site'],
            'source_receipts_sha256': {s: file_hash(work / 'prepared' / s / 'receipt.json') for s in p['calibration_sites']}}
    meta = correction.save(model, work / 'model', training, pins, setting)
    loaded, _ = correction.load(work / 'model')
    # Seal settings before even computing the new park's frozen-model prediction.
    atomic_json(work / 'checkpoint-seal.json', {'created_utc': datetime.now(timezone.utc).isoformat(),
                'model_id': meta['id'], 'weights_sha256': meta['weights_sha256'], 'selected': setting,
                'selection_sha256': file_hash(work / 'calibration-selection.json'),
                **pins, 'fresh_predictions_computed': False})
    corrected_rows = []
    all_pixel_scores = {}
    roundtrips = []
    for site in [*p['calibration_sites'], p['fresh_check_site']]:
        if site == p['fresh_check_site']:
            print('Scoring excluded crop after checkpoint seal', site, flush=True)
            features, base_ground = prepare(parent, work, site, baseline, encoder)
            del features, base_ground
        rgb, cir, probability, features = read_prepared(parent, work, site)
        residual = correction.residuals(model, features)
        reloaded = correction.residuals(loaded, features)
        if not np.array_equal(residual, reloaded):
            raise ValueError('Correction checkpoint reload changed inference')
        roundtrips.append({'site': site, 'exact_residual_reload': True})
        q = correction.corrected_probabilities(probability, residual, rgb, cir, **setting)
        ground = q.argmax(2).astype(np.uint8)
        folder = work / 'prepared' / site
        Image.fromarray(ground).save(folder / 'corrected-ground.png')
        Image.fromarray(np.rint(q.max(2) * 255).astype(np.uint8)).save(folder / 'corrected-confidence.png')
        if site == p['fresh_check_site']:
            baseline_rows.extend(measured(probability.argmax(2).astype(np.uint8), refs['references'][site], site))
        corrected_rows.extend(measured(ground, refs['references'][site], site))
        if site in p['calibration_sites']:
            target = np.array(Image.open(parent / 'native-dataset' / site / 'ground.png'))
            all_pixel_scores[site] = {'baseline': scores(confusion(target, probability.argmax(2))),
                                      'corrected': scores(confusion(target, ground)),
                                      'scope': 'Previously consumed development masks; not unseen validation.'}
        del rgb, cir, probability, features, residual, reloaded, q, ground
        gc.collect()
    cohorts = {}
    for role in ('calibration_fit', 'calibration_check', 'fresh_check'):
        before = [r for r in baseline_rows if r['role'] == role]
        after = [r for r in corrected_rows if r['role'] == role]
        cohorts[role] = {'baseline': errors.summarise(before), 'corrected': errors.summarise(after),
                         'by_class': {str(c): {'baseline': errors.summarise([r for r in before if r['class'] == c]),
                                               'corrected': errors.summarise([r for r in after if r['class'] == c])}
                                      for c in sorted({r['class'] for r in before})}}
    report = {'version': 'aerial-marker-error-correction-experiment-v1', 'cohorts': cohorts,
              'all_calibration_pixel_scores': all_pixel_scores,
              'base_checkpoint_id': base_meta['id'], 'correction_checkpoint_id': meta['id'],
              'selected': setting, 'production_eligible': False, 'independent_human_review': False,
              'automatic_promotion': False, 'base_and_encoder_unchanged': True, 'canopy_unchanged': True,
              'fresh_site_now_consumed': p['fresh_check_site'], 'selection_on_fresh_site': False,
              'scope': 'Small assistant-source-reviewed image-relative normal transects. Not surveyed accuracy, independent truth or a full-scene boundary benchmark.',
              'tree_boundary_validation_supported': False,
              'reference_uncertainty_m': refs['reference_uncertainty_m'],
              'missing_boundary_penalty_m': p['missing_boundary_penalty_m']}
    atomic_json(work / 'baseline-markers.json', baseline_rows)
    atomic_json(work / 'corrected-markers.json', corrected_rows)
    atomic_json(work / 'checkpoint-roundtrip.json', roundtrips)
    atomic_json(work / 'report.json', report)
    atomic_json(work / 'resources.json', {'wall_seconds': time.monotonic() - start,
                'peak_rss_mb': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                'cpu_threads': 2, 'gpu_used': False})
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('parent', 'work', 'encoder'):
        parser.add_argument('--' + name, required=True)
    print(json.dumps(run(**vars(parser.parse_args())), indent=2))
