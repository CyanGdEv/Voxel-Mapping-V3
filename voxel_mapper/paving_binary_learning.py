"""Train source-pinned RGB and RGB/context binary paving research networks."""
import argparse
import csv
from html import escape
import json
from pathlib import Path
import re

import numpy as np
from PIL import Image
from pyproj import Transformer

from . import paving_masks as masks, aerial_semantic_network as net, study_component_learning as safe
from .desktop_memory import digest
from .generation_cycles import atomic_json, file_hash

VERSION = 'paving-binary-training-v1'
MODEL_VERSION = 'paving-binary-model-v1'
MODES = ('rgb_only', 'rgb_context')


def _features(rgb, receipt, cancelled):
    extent = receipt['extent_epsg3857']
    inverse = Transformer.from_crs(3857, 4326, always_xy=True)
    _, latitude = inverse.transform((extent[0]+extent[2])/2, (extent[1]+extent[3])/2)
    scale = (extent[2]-extent[0])/rgb.shape[1]*float(np.cos(np.deg2rad(latitude)))
    return net.features(rgb, scale, cancelled=cancelled)


def _mode(features, mode):
    if mode not in MODES:
        raise ValueError('Known binary paving feature mode required')
    if mode == 'rgb_context':
        return features
    result = np.zeros_like(features); result[..., :3] = features[..., :3]
    return result


def _rows(directory, cancelled):
    root = Path(directory).resolve(); manifest = masks.validate(root)
    if manifest.get('reserved_test_only') or any(not r['research_training_eligible'] for r in manifest['records']):
        raise ValueError('Reserved test masks cannot enter model fitting')
    if not 3 <= len(manifest['records']) <= 12 or len({r['site_id'] for r in manifest['records']}) < 3:
        raise ValueError('Three to twelve crops from at least three parks required')
    rows = []
    for record in manifest['records']:
        net.check(cancelled)
        with Image.open(root/record['source_file']) as image:
            if image.width*image.height > 1048576:
                raise ValueError('Binary context learning supports at most one megapixel per original')
            rgb = np.asarray(image.convert('RGB')).copy()
        receipt = json.loads((root/record['metadata_file']).read_text())
        full = _features(rgb, receipt, cancelled)
        x0, y0, x1, y1 = record['crop_pixels']
        features = full[y0:y1, x0:x1].copy(); del full, rgb
        with Image.open(root/record['mask_file']) as image:
            target = np.asarray(image).copy()
        with Image.open(root/record['image_file']) as image:
            crop = np.asarray(image).copy()
        if not np.any(target == 0) or not np.any(target == 1):
            raise ValueError('Each crop needs explicit paving and non-paving examples')
        rng = np.random.default_rng(137); indices = []
        for value in (0, 1):
            selected = np.flatnonzero(target.reshape(-1) == value)
            if len(selected) > 4000:
                selected = rng.choice(selected, 4000, replace=False)
            indices.extend(selected.tolist())
        rows.append({'record': record, 'features': features, 'target': target,
            'rgb': crop, 'indices': np.array(indices, np.int64)})
    return root, manifest, rows


def _samples(rows, mode):
    x = []; y = []
    for row in rows:
        x.append(_mode(row['features'].reshape(-1, net.FEATURE_COUNT)[row['indices']], mode))
        y.append(row['target'].reshape(-1)[row['indices']])
    return np.concatenate(x), np.concatenate(y)


def _model(fit, mode, manifest, pin, fitting):
    model = {'version': MODEL_VERSION, 'feature_version': net.FEATURE_VERSION,
        'feature_mode': mode, 'labels': masks.LABELS, 'review_policy': masks.POLICY,
        'dataset_id': manifest['id'], 'dataset_sha256': pin,
        'training_record_ids': sorted(r['record']['id'] for r in fitting),
        'training_site_ids': sorted({r['record']['site_id'] for r in fitting}),
        'training_source_sha256': sorted({r['record']['source_sha256'] for r in fitting}),
        'network': fit, 'human_labels_verified': False, 'geometry_verified': False,
        'production_eligible': False, 'world_blocks_generated': 0}
    model['artifact_sha256'] = digest(model)
    return model


def validate_model(model):
    if model.get('version') != MODEL_VERSION or model.get('feature_version') != net.FEATURE_VERSION or model.get('feature_mode') not in MODES or model.get('labels') != masks.LABELS:
        raise ValueError('Known binary paving checkpoint and label contract required')
    if model.get('artifact_sha256') != digest({k: v for k, v in model.items() if k != 'artifact_sha256'}) or model.get('review_policy') != masks.POLICY:
        raise ValueError('Pinned provisional binary paving checkpoint required')
    if any(model.get(k) is not False for k in ('human_labels_verified', 'geometry_verified', 'production_eligible')) or model.get('world_blocks_generated') != 0:
        raise ValueError('Research-only binary paving policy required')
    for key in ('training_record_ids', 'training_site_ids'):
        values = model.get(key)
        if not isinstance(values, list) or not 1 <= len(values) <= 12 or len(set(values)) != len(values) or any(not isinstance(v, str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,79}', v) for v in values):
            raise ValueError('Bounded binary checkpoint source grouping required')
    pins = model.get('training_source_sha256')
    if not isinstance(pins, list) or not 1 <= len(pins) <= 12 or any(not isinstance(s, str) or not re.fullmatch('[0-9a-f]{64}', s) for s in pins):
        raise ValueError('Pinned binary checkpoint sources required')
    if any(not isinstance(model.get(k), str) or not re.fullmatch('[0-9a-f]{64}', model[k]) for k in ('dataset_id', 'dataset_sha256')):
        raise ValueError('Pinned binary training dataset required')
    hidden = model['network']['settings']['hidden']
    if type(hidden) is not int or not 8 <= hidden <= 64:
        raise ValueError('Bounded binary hidden width required')
    parameters = {}
    for key, shape in {'w1': (31, hidden), 'b1': (hidden,), 'w2': (hidden, 2), 'b2': (2,)}.items():
        value = model['network']['parameters'][key]
        if not isinstance(value, list) or len(value) != shape[0] or (len(shape) == 2 and any(not isinstance(v, list) or len(v) != shape[1] for v in value)):
            raise ValueError('Bounded binary network parameter shapes required')
        array = np.asarray(value, np.float32)
        if array.shape != shape or not np.isfinite(array).all() or np.abs(array).max() > 100:
            raise ValueError('Finite bounded binary weights required')
        parameters[key] = array
    values = model['network']['normalization']
    if any(not isinstance(values.get(k), list) or len(values[k]) != 31 for k in ('mean', 'scale')):
        raise ValueError('Bounded binary normalization required')
    mean = np.asarray(values['mean'], np.float32); scale = np.asarray(values['scale'], np.float32)
    if not np.isfinite(mean).all() or not np.isfinite(scale).all() or np.any(scale < .03):
        raise ValueError('Finite binary normalization required')
    return parameters, mean, scale


def probabilities(features, model, *, cancelled=lambda: False):
    parameters, mean, scale = validate_model(model)
    shape = features.shape
    if len(shape) not in (2, 3) or shape[-1] != 31 or features.size > 1048576*31:
        raise ValueError('Bounded source-only binary feature grid required')
    flat = _mode(np.asarray(features, np.float32), model['feature_mode']).reshape(-1, 31)
    if not np.isfinite(flat).all():
        raise ValueError('Finite source features required')
    p = np.empty((len(flat), 2), np.float32)
    for start in range(0, len(flat), 16384):
        net.check(cancelled); _, values = net.forward((flat[start:start+16384]-mean)/scale, parameters)
        p[start:start+len(values)] = values
    return p.reshape(*shape[:-1], 2)


def _metrics(matrix):
    tn, fp, fn, tp = [int(v) for v in matrix.reshape(-1)]
    return {'confusion': matrix.tolist(), 'annotated_pixels': int(matrix.sum()),
        'paving_iou': tp/max(1, tp+fp+fn), 'paving_precision': tp/max(1, tp+fp),
        'paving_recall': tp/max(1, tp+fn), 'non_paving_iou': tn/max(1, tn+fp+fn),
        'scope': 'Only provisional annotated pixels; unknown targets excluded; threshold .5 fixed before evaluation.'}


def _save_preview(row, model, output, cancelled):
    output.mkdir(parents=True)
    p = probabilities(row['features'], model, cancelled=cancelled)
    predicted = p.argmax(axis=2).astype(np.uint8)
    predicted[p.max(axis=2) < .6] = 255
    Image.fromarray(predicted).save(output/'prediction-mask.png')
    rgb = row['rgb']; overlay = rgb.copy(); positive = predicted == 1
    overlay[positive] = (rgb[positive]*.45+np.array([35, 165, 255])*.55).astype(np.uint8)
    Image.fromarray(overlay).save(output/'paving-overlay.png')
    source_in_training = row['record']['source_sha256'] in model['training_source_sha256']
    if source_in_training or row['record']['site_id'] in model['training_site_ids']:
        raise ValueError('Park-excluded preview cannot use a fitting source or park')
    atomic_json(output/'report.json', {'source_in_training': source_in_training,
        'source_sha256': row['record']['source_sha256'], 'held_out_park': row['record']['site_id'],
        'feature_mode': model['feature_mode'], 'confidence_is_calibrated': False,
        'preview_threshold': .6, 'score_threshold': .5, 'production_eligible': False})


def train(directory, output, settings=None, *, cancelled=lambda: False, progress=lambda v: None):
    output = Path(output)
    if output.exists():
        raise ValueError('Fresh binary paving training output required')
    root, manifest, rows = _rows(directory, cancelled)
    output.mkdir(parents=True); pin = file_hash(root/'dataset.json')
    with (output/'rgb-samples.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['crop_id', 'park_id', 'label', 'crop_x', 'crop_y', 'source_x', 'source_y', 'r', 'g', 'b', 'source_sha256', 'mask_sha256'])
        for row in rows:
            record = row['record']; width = row['target'].shape[1]
            for index in row['indices']:
                y, x = divmod(int(index), width); r, g, b = row['rgb'][y, x]
                writer.writerow([record['id'], record['site_id'], int(row['target'][y, x]), x, y,
                    x+record['crop_pixels'][0], y+record['crop_pixels'][1], int(r), int(g), int(b),
                    record['source_sha256'], record['mask_sha256']])
    totals = {mode: np.zeros((2, 2), np.int64) for mode in MODES}; folds = []; models = {}
    sites = sorted({r['record']['site_id'] for r in rows})
    for number, site in enumerate(sites):
        net.check(cancelled)
        fitting = [r for r in rows if r['record']['site_id'] != site]
        held = [r for r in rows if r['record']['site_id'] == site]; scores = {}
        for mode in MODES:
            progress({'progress': .15+.65*number/len(sites), 'message': 'Training '+mode+' with entire park excluded: '+site})
            x, y = _samples(fitting, mode)
            fit = net.fit(x, y, settings, class_count=2, cancelled=cancelled)
            model = _model(fit, mode, manifest, pin, fitting)
            folder = output/'folds'/site/mode; folder.mkdir(parents=True)
            atomic_json(folder/'model.json', model); matrix = np.zeros((2, 2), np.int64)
            for row in held:
                valid = row['target'] != 255
                prediction = probabilities(row['features'][valid], model, cancelled=cancelled).argmax(axis=1)
                np.add.at(matrix, (row['target'][valid], prediction), 1)
                _save_preview(row, model, folder/row['record']['id'], cancelled)
            totals[mode] += matrix
            scores[mode] = {**_metrics(matrix), 'model_sha256': file_hash(folder/'model.json'),
                'training_site_ids': model['training_site_ids'], 'training_record_ids': model['training_record_ids'],
                'weight_change_l2': fit['weight_change_l2']}
        folds.append({'held_out_park': site, 'held_out_record_ids': [r['record']['id'] for r in held], 'scores': scores})
    for mode in MODES:
        progress({'progress': .85, 'message': 'Fitting all-data binary research checkpoint: '+mode})
        x, y = _samples(rows, mode); fit = net.fit(x, y, settings, class_count=2, cancelled=cancelled)
        model = _model(fit, mode, manifest, pin, rows); folder = output/'models'/mode; folder.mkdir(parents=True)
        atomic_json(folder/'model.json', model)
        models[mode] = {'file': str((folder/'model.json').resolve()), 'sha256': file_hash(folder/'model.json'),
            'weight_change_l2': fit['weight_change_l2'], 'loss_history': fit['loss_history']}
    x, y = _samples(rows, 'rgb_context'); colour = np.rint(x[:, :3]*255).astype(np.uint8)
    # Shared quantized colour bins show how often positive/negative colours
    # overlap. This is a descriptive statistic, not a classifier accuracy.
    bins = np.clip((colour//32).astype(int), 0, 7); keys = bins[:, 0]*64+bins[:, 1]*8+bins[:, 2]
    hist = [np.bincount(keys[y == c], minlength=512)/int((y == c).sum()) for c in (0, 1)]
    stats = {str(c): {'samples': int((y == c).sum()), 'rgb_mean': colour[y == c].mean(axis=0).tolist(),
        'rgb_percentiles_10_50_90': np.percentile(colour[y == c], [10, 50, 90], axis=0).tolist()} for c in (0, 1)}
    if masks.validate(root)['id'] != manifest['id'] or file_hash(root/'dataset.json') != pin:
        raise ValueError('Binary training dataset changed during fitting')
    support = totals['rgb_only'].sum(axis=1)
    always_paving = _metrics(np.array([[0, support[0]], [0, support[1]]], np.int64))
    report = {'version': VERSION, 'dataset_id': manifest['id'], 'dataset_sha256': pin,
        'records': len(rows), 'parks': sites,
        'label_policy': masks.POLICY, 'labels': masks.LABELS, 'samples': len(y),
        'sample_file_sha256': file_hash(output/'rgb-samples.csv'), 'sampled_unknown_pixels': 0,
        'training_settings': {**net.DEFAULTS, **(settings or {})}, 'source_only_feature_count': 31,
        'colour_statistics': stats, 'quantized_rgb_distribution_overlap': float(np.minimum(*hist).sum()),
        'folds': folds, 'park_excluded_scores': {mode: _metrics(totals[mode]) for mode in MODES},
        'always_paving_reference': always_paving,
        'models': models, 'model_weights_updated': True, 'human_labels_verified': False,
        'production_eligible': False, 'world_blocks_generated': 0,
        'limitations': ['Small source-linked crop dataset; labels remain provisional assistant drafts requiring independent review.',
            'These existing development images are not an untouched blind final test. Unknown pixels are not scored.',
            'Context uses RGB/Lab, local edges and multiscale texture; this is not a convolutional segmentation or path-continuity model.',
            'All-data checkpoints have seen every supplied crop and have no untouched final test; previews use park-excluded checkpoints.',
            'No map polygons, coordinates, park names or target masks enter network features. CSV coordinates/IDs are provenance only.',
            'Threshold .5 is fixed for scores; preview abstention at .6 is uncalibrated and scored separately from previews.']}
    atomic_json(output/'report.json', report)
    table = ''.join('<tr><td>'+mode+'</td><td>'+f'{100*report["park_excluded_scores"][mode]["paving_iou"]:.2f}%</td><td>'+f'{100*report["park_excluded_scores"][mode]["paving_precision"]:.2f}%</td><td>'+f'{100*report["park_excluded_scores"][mode]["paving_recall"]:.2f}%</td></tr>' for mode in MODES)
    table = '<tr><td>Always paving reference</td><td>'+f'{100*always_paving["paving_iou"]:.2f}%</td><td>'+f'{100*always_paving["paving_precision"]:.2f}%</td><td>100%</td></tr>'+table
    page = '<!doctype html><meta charset="utf-8"><title>Binary paving colour training</title><style>body{font:16px system-ui;max-width:1100px;margin:30px auto}td,th{padding:10px}img{max-width:48%}</style><h1>RGB versus RGB/context paving training</h1><p>Whole parks excluded together. Provisional development labels only; unknown targets excluded. These are binary scores on different targets from the earlier five-class model, so they do not establish a direct accuracy gain over it.</p><table><tr><th>Features</th><th>Paving IoU</th><th>Precision</th><th>Recall</th></tr>'+table+'</table><p><a href="report.json">All scores and source pins</a> · <a href="rgb-samples.csv">Labelled RGB samples</a></p><p>Blue previews below use .6 confidence abstention. Numeric evaluation uses .5. Unmarked areas do not prove absence of paving.</p>'
    for row in rows:
        record = row['record']; page += '<h2>'+escape(record['id'])+'</h2>'
        for mode in MODES:
            page += '<img alt="'+mode+'" src="folds/'+record['site_id']+'/'+mode+'/'+record['id']+'/paving-overlay.png">'
    (output/'index.html').write_text(page, encoding='utf-8')
    return report


def predict(image_path, receipt, model_path, output, *, model_sha256=None, threshold=.6, cancelled=lambda: False):
    output = Path(output)
    if output.exists() or type(threshold) not in (int, float) or not .5 <= threshold <= .99:
        raise ValueError('Fresh binary prediction output and bounded confidence threshold required')
    model_pin = file_hash(model_path)
    if file_hash(image_path) != receipt['image_sha256'] or (model_sha256 and model_pin != model_sha256):
        raise ValueError('Pinned binary prediction source/model changed')
    model, _ = safe._json(Path(model_path), 2000000); validate_model(model)
    with Image.open(image_path) as image:
        if image.width*image.height > 1048576:
            raise ValueError('One-megapixel binary prediction source budget exceeded')
        rgb = np.asarray(image.convert('RGB')).copy(); opaque = np.asarray(image.convert('RGBA'))[:, :, 3] == 255
    p = probabilities(_features(rgb, receipt, cancelled), model, cancelled=cancelled)
    labels = p.argmax(axis=2).astype(np.uint8); labels[(p.max(axis=2) < threshold) | ~opaque] = 255
    overlay = rgb.copy(); selected = labels == 1
    overlay[selected] = (rgb[selected]*.45+np.array([35, 165, 255])*.55).astype(np.uint8)
    if file_hash(image_path) != receipt['image_sha256'] or file_hash(model_path) != model_pin:
        raise ValueError('Binary prediction source/model changed while reading')
    output.mkdir(parents=True); Image.fromarray(labels).save(output/'prediction-mask.png'); Image.fromarray(overlay).save(output/'paving-overlay.png')
    report = {'version': 'paving-binary-prediction-v1', 'source_sha256': receipt['image_sha256'],
        'model_sha256': model_pin, 'feature_mode': model['feature_mode'],
        'source_in_training': receipt['image_sha256'] in model['training_source_sha256'],
        'pixel_counts': {k: int((labels == v).sum()) for k, v in masks.LABELS.items()},
        'threshold': threshold, 'confidence_is_calibrated': False, 'model_weights_updated': False,
        'geometry_verified': False, 'production_eligible': False, 'world_blocks_generated': 0}
    atomic_json(output/'report.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='action', required=True)
    fit = sub.add_parser('train'); fit.add_argument('--dataset', required=True); fit.add_argument('--output', required=True)
    infer = sub.add_parser('predict')
    for key in ('image', 'receipt', 'model', 'output'):
        infer.add_argument('--'+key, required=True)
    args = parser.parse_args(argv)
    if args.action == 'train': result = train(args.dataset, args.output)
    else: result = predict(args.image, json.loads(Path(args.receipt).read_text()), args.model, args.output)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
