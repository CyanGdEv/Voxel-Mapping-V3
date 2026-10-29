"""Mixed UK/Dutch error correction with metric references and excluded parks."""
import argparse
from datetime import datetime, timezone
import gc
import json
from pathlib import Path
import resource
import time

import numpy as np
from PIL import Image

from . import aerial_marker_correction as correction, metric_boundary_learning as metric
from . import aerial_surface_encoder as aerial, layered_surface_learning as base
from .aerial_marker_experiment import confusion, scores
from .generation_cycles import atomic_json, file_hash


def availability(source):
    return 'rgb_cir' if source.get('cir_file') else 'rgb_only'


def images(source):
    if file_hash(source['image_file']) != source['image_sha256']:
        raise ValueError('Source RGB bytes changed')
    rgb = np.array(Image.open(source['image_file']).convert('RGB'))
    cir = None
    if source.get('cir_file'):
        if file_hash(source['cir_file']) != source['cir_sha256']:
            raise ValueError('Source CIR bytes changed')
        cir = np.array(Image.open(source['cir_file']).convert('RGB'))
    return rgb, cir


def geographic_guard(sources):
    """Conservative ground-distance separation of every fresh/development crop."""
    from pyproj import Transformer, Geod
    t = Transformer.from_crs(3857, 4326, always_xy=True)
    geod = Geod(ellps='WGS84')
    frames = {}
    for id, source in sources.items():
        if file_hash(source['receipt_file']) != source['receipt_sha256']:
            raise ValueError('Pinned geographic source receipt required')
        receipt = json.loads(Path(source['receipt_file']).read_text())
        e = receipt['extent_epsg3857']
        lon, lat = t.transform((e[0] + e[2]) / 2, (e[1] + e[3]) / 2)
        radius = max(geod.inv(lon, lat, *t.transform(x, y))[2]
                     for x, y in [(e[0], e[1]), (e[2], e[1]), (e[2], e[3]), (e[0], e[3])])
        frames[id] = (lon, lat, radius)
    checks = []
    for id, source in sources.items():
        if source['role'] != 'fresh_check':
            continue
        x, y, radius = frames[id]
        for other, dev in sources.items():
            if dev['role'] != 'development':
                continue
            xx, yy, rr = frames[other]
            distance = geod.inv(x, y, xx, yy)[2] - radius - rr
            if distance < 100:
                raise ValueError('Fresh imagery overlaps the development geographic context guard')
            checks.append({'fresh_source': id, 'development_source': other,
                           'conservative_separation_m': distance})
    return {'required_m': 100, 'pairs': checks, 'passed': True}


def prepare(source, work, baseline, encoder):
    """Only development sources may be predicted before the checkpoint seal."""
    work = Path(work)
    if source['role'] == 'fresh_check':
        if not (work / 'checkpoint-seal.json').exists():
            raise ValueError('Excluded source predictions require a completed checkpoint seal')
        seal = json.loads((work / 'checkpoint-seal.json').read_text())
        if seal['sources_sha256'] != file_hash(work / 'sources.json'):
            raise ValueError('Fresh prediction seal does not match the current source reservation')
    folder = work / 'prepared' / source['id']
    if folder.exists():
        receipt = json.loads((folder / 'receipt.json').read_text())
        if (receipt['source_sha256'] != source['image_sha256']
                or receipt['height_sha256'] != file_hash(source['height_file'])
                or receipt['base_checkpoint_sha256'] != file_hash(work / 'base/weights.safetensors')
                or receipt['descriptor_sha256'] != file_hash(folder / 'descriptors.npz')
                or receipt['base_probability_sha256'] != file_hash(folder / 'base.npz')):
            raise ValueError('Prepared source pins changed')
        return
    rgb, cir = images(source)
    hp = Path(source['height_file'])
    hmeta = json.loads(hp.with_suffix('.json').read_text())
    if hmeta['features_sha256'] != file_hash(hp) or hmeta['image_sha256'] != source['image_sha256']:
        raise ValueError('Pinned source-aligned relative height context required')
    with np.load(hp, allow_pickle=False) as f:
        height = f['features']
    if source.get('features_file'):
        fp = Path(source['features_file'])
        fm = json.loads(fp.with_suffix('.json').read_text())
        if file_hash(fp) != fm['features_sha256'] or fm['encoder_sha256'] != aerial.WEIGHTS:
            raise ValueError('Pinned frozen source descriptors required')
        with np.load(fp, allow_pickle=False) as f:
            feature = f['features']
    else:
        feature = aerial.Encoder(encoder).features(rgb)
    if not np.array_equal(feature[:, :, :3], rgb.astype(np.float32) / 255):
        raise ValueError('Frozen RGB feature grid must match clean source pixels')
    print('Preparing frozen baseline', source['id'], flush=True)
    ground, canopy, uncertainty, probability = base.predict(baseline, np.concatenate([feature, height], 2), return_probabilities=True)
    del feature
    folder.mkdir(parents=True)
    np.savez_compressed(folder / 'base.npz', probabilities=probability)
    Image.fromarray(ground).save(folder / 'base-ground.png')
    Image.fromarray(canopy).save(folder / 'canopy.png')
    d = correction.descriptors(rgb, cir, height, probability)
    np.savez_compressed(folder / 'descriptors.npz', features=d)
    atomic_json(folder / 'receipt.json', {'source_sha256': source['image_sha256'],
                'cir_sha256': source.get('cir_sha256'), 'height_sha256': file_hash(hp),
                'base_checkpoint_sha256': file_hash(work / 'base/weights.safetensors'),
                'base_probability_sha256': file_hash(folder / 'base.npz'),
                'descriptor_sha256': file_hash(folder / 'descriptors.npz'),
                'source_role': source['role'], 'descriptor_version': correction.VERSION})


def load_prepared(work, source):
    folder = Path(work) / 'prepared' / source['id']
    with np.load(folder / 'base.npz', allow_pickle=False) as f:
        p = f['probabilities']
    with np.load(folder / 'descriptors.npz', allow_pickle=False) as f:
        d = f['features']
    return p, d


def measured(grid, references, source, settings):
    return [{**metric.measure(grid, r, source['spacing_m_xy'],
                             settings['search_radius_m'], settings['step_m'], settings['probe_m']),
             'source': source['id'], 'site_id': source['site_id'], 'role': r['role'],
             'group': availability(source)} for r in references]


def validate_split(sources, references, protocol):
    fitted = {s['site_id'] for s in sources.values() if s['role'] == 'development'}
    fresh = {s['site_id'] for s in sources.values() if s['role'] == 'fresh_check'}
    if (fitted & fresh or fresh != set(protocol['fresh_sites'])
            or fitted & set(protocol['excluded_consumed_sites'])
            or set(sources) != set(references)
            or {id for id, s in sources.items() if s['role'] == 'development'} != set(protocol['fitting_sources'])):
        raise ValueError('Whole fresh parks must be excluded from all development sources')
    for id, source in sources.items():
        if source['role'] not in ('development', 'fresh_check'):
            raise ValueError('Explicit source role required')
        expected = {'fresh_check'} if source['role'] == 'fresh_check' else {'calibration_fit', 'calibration_check'}
        if any(r['role'] not in expected for r in references[id]):
            raise ValueError('Reference role conflicts with the source reservation')


def prepare_development(work, encoder):
    import torch
    torch.set_num_threads(2)
    work = Path(work)
    sources = json.loads((work / 'sources.json').read_text())
    baseline, _ = base.load(work / 'base')
    for source in sources.values():
        if source['role'] != 'development':
            continue
        prepare(source, work, baseline, encoder)
        gc.collect()


def run(work, encoder):
    import torch
    torch.set_num_threads(2)
    work = Path(work)
    start = time.monotonic()
    if (work / 'model').exists() or (work / 'report.json').exists():
        raise ValueError('Fresh fit output required; scored fresh sites become consumed')
    p = json.loads((work / 'protocol.json').read_text())
    sources = json.loads((work / 'sources.json').read_text())
    refs = json.loads((work / 'references.json').read_text())
    seal = json.loads((work / 'reference-seal.json').read_text())
    if (seal['references_sha256'] != file_hash(work / 'references.json')
            or seal['sources_sha256'] != file_hash(work / 'sources.json')
            or seal['protocol_sha256'] != file_hash(work / 'protocol.json')
            or not seal['no_fresh_predictions_computed'] or p['automatic_promotion']):
        raise ValueError('Source-only references must be sealed before correction fitting')
    validate_split(sources, refs, p)
    atomic_json(work / 'geographic-guard.json', geographic_guard(sources))
    for source in sources.values():
        if file_hash(source['target_file']) != source['target_sha256']:
            raise ValueError('Pinned observed target mask changed')
    baseline, base_meta = base.load(work / 'base')
    if base_meta['id'] != p['base_checkpoint_id'] or base_meta['weights_sha256'] != p['base_weights_sha256']:
        raise ValueError('Declared frozen baseline required')
    samples, before = [], []
    for id, source in sources.items():
        if source['role'] != 'development':
            continue
        prepare(source, work, baseline, encoder)
        probability, features = load_prepared(work, source)
        target = np.array(Image.open(source['target_file']))
        ground = probability.argmax(2).astype(np.uint8)
        sample = metric.sample_source(features, target, refs[id], ground, source['spacing_m_xy'], p['fit'])
        sample['report'].update(source=id, site_id=source['site_id'], group=availability(source))
        np.savez_compressed(work / 'prepared' / id / 'fit-samples.npz',
                            **{k: v for k, v in sample.items() if k != 'report'})
        samples.append(sample)
        before.extend(measured(ground, refs[id], source, p['measurement']))
        del probability, features, target, ground
        gc.collect()
    print('Fitting balanced metric correction', flush=True)
    model, training = metric.fit(samples, p['fit'])
    del samples
    results = {group: {a: {'rows': [], 'pixel_deltas': []} for a in p['selection']['alpha']}
               for group in p['selection']['separate_availability_groups']}
    pixel_before = {}
    for id, source in sources.items():
        if source['role'] != 'development':
            continue
        rgb, cir = images(source)
        probability, features = load_prepared(work, source)
        residual = correction.residuals(model, features)
        np.savez_compressed(work / 'prepared' / id / 'residual.npz', residual=residual)
        target = np.array(Image.open(source['target_file']))
        base_score = scores(confusion(target, probability.argmax(2)))
        pixel_before[id] = base_score
        check = [r for r in refs[id] if r['role'] == 'calibration_check']
        for alpha in p['selection']['alpha']:
            q = correction.corrected_probabilities(probability, residual, rgb, cir, alpha, 0.)
            ground = q.argmax(2).astype(np.uint8)
            result = results[availability(source)][alpha]
            result['rows'].extend(measured(ground, check, source, p['measurement']))
            score = scores(confusion(target, ground))
            deltas = [b - a for a, b in zip(base_score['iou'], score['iou']) if a is not None]
            result['pixel_deltas'].append({'source': id, 'macro_iou_delta': score['macro_iou'] - base_score['macro_iou'],
                                          'worst_present_class_iou_delta': min(deltas), 'scores': score})
        del rgb, cir, probability, features, residual, q, ground, target
        gc.collect()
    choices, candidates = {}, []
    for group, variants in results.items():
        rows = []
        for alpha, value in variants.items():
            rows.append({'role': 'calibration_check', 'group': group, 'alpha': alpha,
                         'errors': metric.summarise(value['rows']), 'development_pixel_checks': value['pixel_deltas'],
                         'worst_source_macro_iou_delta': min(r['macro_iou_delta'] for r in value['pixel_deltas']),
                         'worst_source_present_class_iou_delta': min(r['worst_present_class_iou_delta'] for r in value['pixel_deltas'])})
        winner = metric.select(rows, group, p['selection'])
        choices[group] = winner['alpha']
        candidates.extend(rows)
    atomic_json(work / 'calibration-selection.json', {'candidates': candidates, 'selected_alpha': choices,
                'fresh_sites_used': False, 'pixel_guards_scope': 'Consumed development masks; not independent validation.'})
    pins = {'protocol_sha256': file_hash(work / 'protocol.json'),
            'sources_sha256': file_hash(work / 'sources.json'), 'references_sha256': file_hash(work / 'references.json'),
            'base_checkpoint_id': base_meta['id'], 'encoder_sha256': aerial.WEIGHTS,
            'fitting_source_ids': p['fitting_sources'], 'fresh_sites_excluded': sorted(p['fresh_sites'])}
    meta = correction.save(model, work / 'model', training, pins, choices)
    loaded, _ = correction.load(work / 'model')
    atomic_json(work / 'checkpoint-seal.json', {'created_utc': datetime.now(timezone.utc).isoformat(), **pins,
                'model_id': meta['id'], 'weights_sha256': meta['weights_sha256'], 'selected_alpha': choices,
                'calibration_selection_sha256': file_hash(work / 'calibration-selection.json'),
                'fresh_predictions_computed': False})
    after, pixels, roundtrips = [], {}, []
    for id, source in sources.items():
        prepare(source, work, baseline, encoder)
        rgb, cir = images(source)
        probability, features = load_prepared(work, source)
        residual = correction.residuals(model, features)
        if not np.array_equal(residual, correction.residuals(loaded, features)):
            raise ValueError('Saved metric correction changed on reload')
        roundtrips.append({'source': id, 'exact_residual_reload': True})
        q = correction.corrected_probabilities(probability, residual, rgb, cir, choices[availability(source)], 0.)
        ground = q.argmax(2).astype(np.uint8)
        Image.fromarray(ground).save(work / 'prepared' / id / 'corrected-ground.png')
        if source['role'] == 'fresh_check':
            before.extend(measured(probability.argmax(2).astype(np.uint8), refs[id], source, p['measurement']))
        after.extend(measured(ground, refs[id], source, p['measurement']))
        target = np.array(Image.open(source['target_file']))
        pixels[id] = {'role': source['role'], 'site_id': source['site_id'], 'group': availability(source),
                      'baseline': scores(confusion(target, probability.argmax(2))),
                      'corrected': scores(confusion(target, ground)),
                      'scope': 'Provisional source-assisted interior windows; not full-scene ground truth.' if source['role'] == 'fresh_check' else 'Consumed development masks.'}
        del rgb, cir, probability, features, residual, q, ground, target
        gc.collect()
    cohorts = {}
    for role in ('calibration_fit', 'calibration_check', 'fresh_check'):
        b, a = [r for r in before if r['role'] == role], [r for r in after if r['role'] == role]
        cohorts[role] = {'baseline': metric.summarise(b), 'corrected': metric.summarise(a),
                         'by_group': {g: {'baseline': metric.summarise([r for r in b if r['group'] == g]),
                                          'corrected': metric.summarise([r for r in a if r['group'] == g])}
                                      for g in sorted({r['group'] for r in b})}}
    atomic_json(work / 'baseline-markers.json', before)
    atomic_json(work / 'corrected-markers.json', after)
    atomic_json(work / 'checkpoint-roundtrip.json', roundtrips)
    report = {'version': metric.VERSION, 'cohorts': cohorts, 'pixel_scores': pixels,
              'selected_alpha': choices, 'base_checkpoint_id': base_meta['id'], 'model_id': meta['id'],
              'fresh_sites_now_consumed': sorted(p['fresh_sites']), 'fresh_source_ids': [id for id, s in sources.items() if s['role'] == 'fresh_check'],
              'selection_on_fresh_scores': False, 'independent_human_review': False,
              'production_eligible': False, 'canopy_unchanged': True, 'base_and_encoder_unchanged': True,
              'scope': 'Source-assisted metric boundary pilot on two excluded parks, including two correlated Walibi crops; not surveyed accuracy or independent human truth.'}
    atomic_json(work / 'report.json', report)
    atomic_json(work / 'resources.json', {'wall_seconds': time.monotonic() - start,
                'peak_rss_mb': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 'cpu_threads': 2, 'gpu_used': False})
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare-development', 'train'))
    parser.add_argument('--work', required=True)
    parser.add_argument('--encoder', required=True)
    args = parser.parse_args()
    result = prepare_development(args.work, args.encoder) if args.mode == 'prepare-development' else run(args.work, args.encoder)
    print(json.dumps(result, indent=2))
