"""Frozen SegFormer spatial descriptors and source-separated paving head benchmarks.

The ADE20K backbone stays unchanged. Only a small binary head is fitted on
provisional paving masks. Reserved-test masks cannot enter fitting.
"""
import argparse
import datetime
from html import escape
import json
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image
from scipy import ndimage

from . import paving_masks as masks, paving_binary_learning as binary, aerial_semantic_network as net
from . import study_component_learning as safe
from .desktop_memory import digest
from .generation_cycles import atomic_json, file_hash

BACKBONE_SHA = '3e5c18a4be395f16646438d54c42377ddc202edfa33d5eced0c9506de75c44c2'
CONFIG_SHA = '435799652b2b64c3e422dea20fed4c59651dae9f0e291fd885e9e067fee0ce2a'
PREPROCESS_SHA = 'dbabd93c735c8a5c39ef207c6c4459bf2d261a5dcc55e1ba1c1b982e5947f518'
FEATURE_VERSION = 'segformer-ade-rgb31-native-tiles-v1'
MODEL_VERSION = 'paving-segformer-frozen-head-v1'
FEATURE_LABELS = ['wall','building','floor','tree','road','grass','sidewalk','earth','plant','car','water',
    'house','sea','field','fence','rock','railing','sand','skyscraper','grandstand','path','stairs',
    'stairway','river','bridge','awning','land','swimming pool']
PAVING_LABELS = ('road', 'sidewalk', 'path')
TILE = 512
STRIDE = 384


def _positions(length):
    return [0] if length <= TILE else sorted(set([*range(0, length-TILE, STRIDE), length-TILE]))


class SpatialEncoder:
    def __init__(self, directory, *, threads=2):
        import onnxruntime as ort
        root = Path(directory).resolve()
        for name, pin in [('model.onnx', BACKBONE_SHA), ('config.json', CONFIG_SHA), ('preprocessor_config.json', PREPROCESS_SHA)]:
            if file_hash(root/name) != pin:
                raise ValueError('Pinned SegFormer backbone/configuration required')
        if type(threads) is not int or not 1 <= threads <= 4:
            raise ValueError('One to four CPU encoder threads required')
        config = json.loads((root/'config.json').read_text())
        labels = {v.strip(): int(k) for k, v in config['id2label'].items()}
        self.indices = [labels[name] for name in FEATURE_LABELS]
        pre = json.loads((root/'preprocessor_config.json').read_text())
        self.mean = np.array(pre['image_mean'], np.float32)[:, None, None]
        self.std = np.array(pre['image_std'], np.float32)[:, None, None]
        options = ort.SessionOptions(); options.intra_op_num_threads = threads; options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(root/'model.onnx'), sess_options=options, providers=['CPUExecutionProvider'])
        if len(self.session.get_inputs()) != 1 or self.session.get_inputs()[0].name != 'pixel_values':
            raise ValueError('Expected pinned SegFormer RGB input required')

    def features(self, original, crop, cache, *, cancelled=lambda: False):
        """RGB-only native tiles; target masks, geography and site IDs are absent."""
        source_pin = file_hash(original)
        with Image.open(original) as image:
            if image.width*image.height > 4000000:
                raise ValueError('Four-megapixel source budget exceeded')
            width, height = image.size; rgb = np.asarray(image.convert('RGB')).copy()
        if not isinstance(crop, list) or len(crop) != 4 or any(type(v) is not int for v in crop) or not 0 <= crop[0] < crop[2] <= width or not 0 <= crop[1] < crop[3] <= height:
            raise ValueError('Native in-source crop required')
        x0, y0, x1, y1 = crop; shape = (y1-y0, x1-x0, 31)
        if shape[0]*shape[1] > 1048576:
            raise ValueError('One-megapixel crop feature budget exceeded')
        key = digest({'source': source_pin, 'crop': crop, 'backbone': BACKBONE_SHA, 'features': FEATURE_VERSION})
        cache = Path(cache); cache.mkdir(parents=True, exist_ok=True)
        path = cache/(key+'.npz'); receipt = cache/(key+'.json')
        if receipt.exists():
            saved, _ = safe._json(receipt, 10000)
            if saved.get('key') != key or file_hash(path) != saved.get('sha256'):
                raise ValueError('Pinned spatial feature cache changed')
            with zipfile.ZipFile(path) as archive:
                if archive.namelist() != ['features.npy'] or archive.getinfo('features.npy').file_size > int(np.prod(shape))*4+512:
                    raise ValueError('Bounded cached spatial feature tensor required')
            with np.load(path, allow_pickle=False) as archive:
                result = archive['features']
            if result.shape != shape or result.dtype != np.float32 or not np.isfinite(result).all() or np.any(result < 0) or np.any(result > 1.00001):
                raise ValueError('Finite pinned spatial feature grid required')
            if file_hash(original) != source_pin: raise ValueError('Spatial source changed during cache read')
            return result
        result = np.zeros(shape, np.float32); weight = np.zeros(shape[:2], np.float32)
        for top in _positions(height):
            for left in _positions(width):
                net.check(cancelled)
                right = min(width, left+TILE); bottom = min(height, top+TILE)
                ix0, iy0, ix1, iy1 = max(left, x0), max(top, y0), min(right, x1), min(bottom, y1)
                if ix0 >= ix1 or iy0 >= iy1:
                    continue
                tile = rgb[top:bottom, left:right]
                tile = np.pad(tile, ((0, TILE-tile.shape[0]), (0, TILE-tile.shape[1]), (0, 0)), mode='edge')
                values = ((tile.astype(np.float32)/255).transpose(2, 0, 1)-self.mean)/self.std
                logits = self.session.run(None, {'pixel_values': values[None]})[0]
                if logits.shape != (1, 150, 128, 128) or not np.isfinite(logits).all():
                    raise ValueError('Expected finite ADE20K spatial logits required')
                logits = logits[0]; logits -= logits.max(axis=0, keepdims=True)
                p = np.exp(logits); p /= p.sum(axis=0, keepdims=True)
                layers = [np.asarray(Image.fromarray(p[i]).resize((TILE, TILE), Image.Resampling.BILINEAR)) for i in self.indices]
                spatial = np.stack(layers, axis=2)
                region = spatial[iy0-top:iy1-top, ix0-left:ix1-left]
                result[iy0-y0:iy1-y0, ix0-x0:ix1-x0, 3:] += region
                weight[iy0-y0:iy1-y0, ix0-x0:ix1-x0] += 1
        if not (weight > 0).all() or file_hash(original) != source_pin:
            raise ValueError('Incomplete spatial coverage or changed source')
        result[:, :, 3:] /= weight[:, :, None]
        result[:, :, :3] = rgb[y0:y1, x0:x1]/255
        np.savez_compressed(path, features=result)
        atomic_json(receipt, {'key': key, 'sha256': file_hash(path), 'source_sha256': source_pin,
            'backbone_sha256': BACKBONE_SHA, 'feature_version': FEATURE_VERSION, 'crop': crop})
        return result


def zero_shot(features):
    return features[:, :, [3+FEATURE_LABELS.index(name) for name in PAVING_LABELS]].sum(axis=2)


def _read_rows(directory, encoder, cache, *, fitting, cancelled):
    root = Path(directory).resolve(); manifest = masks.validate(root)
    if fitting and (manifest.get('reserved_test_only') or any(not r['research_training_eligible'] for r in manifest['records'])):
        raise ValueError('Reserved test masks cannot enter spatial fitting')
    rows = []
    for record in manifest['records']:
        net.check(cancelled)
        features = encoder.features(root/record['source_file'], record['crop_pixels'], cache, cancelled=cancelled)
        target = np.asarray(Image.open(root/record['mask_file'])).copy()
        rgb = np.asarray(Image.open(root/record['image_file'])).copy()
        rng = np.random.default_rng(137); indices = []
        for c in (0, 1):
            selected = np.flatnonzero(target.reshape(-1) == c)
            if fitting and not len(selected):
                raise ValueError('Both paving classes required in each fitting crop')
            if len(selected) > 4000: selected = rng.choice(selected, 4000, replace=False)
            indices.extend(selected.tolist())
        rows.append({'record': record, 'features': features, 'target': target, 'rgb': rgb,
            'indices': np.array(indices, np.int64)})
    return root, manifest, rows


def _head(fit, manifest, pin, rows, design_pin):
    model = binary._model(fit, 'rgb_context', manifest, pin, rows)
    model.update(version=MODEL_VERSION, feature_version=FEATURE_VERSION, feature_mode='segformer_rgb31',
        backbone_sha256=BACKBONE_SHA, design_sha256=design_pin, backbone_weights_updated=False,
        head_weights_updated=True, use_scope='upstream_noncommercial_research_evaluation')
    model['artifact_sha256'] = digest({k: v for k, v in model.items() if k != 'artifact_sha256'})
    return model


def _parameters(model):
    if model.get('version') != MODEL_VERSION or model.get('feature_version') != FEATURE_VERSION or model.get('backbone_sha256') != BACKBONE_SHA or model.get('feature_mode') != 'segformer_rgb31' or model.get('backbone_weights_updated') is not False or model.get('use_scope') != 'upstream_noncommercial_research_evaluation':
        raise ValueError('Known frozen-backbone paving transfer head required')
    if model.get('artifact_sha256') != digest({k: v for k, v in model.items() if k != 'artifact_sha256'}):
        raise ValueError('Pinned spatial head required')
    # Reuse the bounded binary network/lineage validator through an in-memory
    # view. The saved spatial wrapper is always rejected by the RGB loader.
    view = {**model, 'version': binary.MODEL_VERSION, 'feature_version': net.FEATURE_VERSION, 'feature_mode': 'rgb_context'}
    view['artifact_sha256'] = digest({k: v for k, v in view.items() if k != 'artifact_sha256'})
    return binary.validate_model(view)


def probabilities(features, model, *, cancelled=lambda: False):
    parameters, mean, scale = _parameters(model)
    if features.ndim not in (2, 3) or features.shape[-1] != 31 or features.size > 1048576*31 or not np.isfinite(features).all():
        raise ValueError('Bounded finite spatial feature grid required')
    flat = features.reshape(-1, 31); result = np.empty((len(flat), 2), np.float32)
    for start in range(0, len(flat), 16384):
        net.check(cancelled); _, p = net.forward((flat[start:start+16384]-mean)/scale, parameters)
        result[start:start+len(p)] = p
    return result.reshape(*features.shape[:-1], 2)


def _rgb_features(row):
    result = np.zeros((*row['rgb'].shape[:2], 31), np.float32); result[:, :, :3] = row['rgb']/255
    return result


def _score(target, positive):
    valid = target != 255; matrix = np.zeros((2, 2), np.int64)
    np.add.at(matrix, (target[valid], positive[valid].astype(np.uint8)), 1)
    return binary._metrics(matrix)


def _preview(row, p, path):
    path.mkdir(parents=True, exist_ok=True)
    predicted = (p >= .5).astype(np.uint8); preview = predicted.copy()
    preview[np.maximum(p, 1-p) < .6] = 255
    Image.fromarray(predicted).save(path/'score-mask.png'); Image.fromarray(preview).save(path/'preview-mask.png')
    rgb = row['rgb']; image = rgb.copy(); selected = preview == 1
    image[selected] = (rgb[selected]*.45+np.array([35, 165, 255])*.55).astype(np.uint8)
    Image.fromarray(image).save(path/'overlay.png')


def train(directory, encoder_directory, rgb_baseline, design_file, output, cache, *, cancelled=lambda: False):
    output = Path(output)
    if output.exists(): raise ValueError('Fresh spatial benchmark output required')
    design, _ = safe._json(Path(design_file), 100000)
    if design.get('feature_labels') != FEATURE_LABELS or design.get('encoder_sha256') != BACKBONE_SHA or design.get('tile_size') != TILE or design.get('tile_stride') != STRIDE or design.get('score_threshold') != .5:
        raise ValueError('Pinned predeclared spatial experiment design required')
    encoder = SpatialEncoder(encoder_directory)
    root, manifest, rows = _read_rows(directory, encoder, cache, fitting=True, cancelled=cancelled)
    if not 3 <= len(rows) <= 12 or len({r['record']['site_id'] for r in rows}) < 3:
        raise ValueError('Three or more source-separated development parks required')
    baseline = Path(rgb_baseline); previous = json.loads((baseline/'report.json').read_text())
    pin = file_hash(root/'dataset.json')
    if previous['dataset_sha256'] != pin:
        raise ValueError('RGB baseline must use the same corrected target dataset')
    output.mkdir(parents=True); sites = sorted({r['record']['site_id'] for r in rows}); folds = []
    matrices = {name: np.zeros((2, 2), np.int64) for name in ('rgb', 'segformer_zero_shot', 'spatial_head', 'always_paving')}
    for site in sites:
        fitting = [r for r in rows if r['record']['site_id'] != site]
        held = [r for r in rows if r['record']['site_id'] == site]
        x, y = binary._samples(fitting, 'rgb_context')
        fit = net.fit(x, y, design['head_settings'], class_count=2, cancelled=cancelled)
        model = _head(fit, manifest, pin, fitting, file_hash(design_file))
        folder = output/'folds'/site; folder.mkdir(parents=True); atomic_json(folder/'model.json', model)
        rgb_path = baseline/'folds'/site/'rgb_only/model.json'; rgb_model, _ = safe._json(rgb_path, 2000000)
        binary.validate_model(rgb_model)
        if site in rgb_model['training_site_ids'] or site in model['training_site_ids'] or rgb_model['dataset_sha256'] != pin or file_hash(rgb_path) != next(f['scores']['rgb_only']['model_sha256'] for f in previous['folds'] if f['held_out_park'] == site):
            raise ValueError('Park-excluded baseline/model lineage required')
        local = {name: np.zeros((2, 2), np.int64) for name in matrices}
        for row in held:
            predictions = {'rgb': binary.probabilities(_rgb_features(row), rgb_model)[:, :, 1],
                'segformer_zero_shot': zero_shot(row['features']),
                'spatial_head': probabilities(row['features'], model, cancelled=cancelled),
                'always_paving': np.ones(row['target'].shape, np.float32)}
            predictions['spatial_head'] = predictions['spatial_head'][:, :, 1]
            for name, p in predictions.items():
                score = _score(row['target'], p >= .5); matrix = np.array(score['confusion'], np.int64)
                matrices[name] += matrix; local[name] += matrix
                if name != 'always_paving': _preview(row, p, folder/row['record']['id']/name)
        folds.append({'held_out_park': site, 'training_sites': model['training_site_ids'],
            'model_sha256': file_hash(folder/'model.json'), 'scores': {k: binary._metrics(v) for k, v in local.items()}})
    x, y = binary._samples(rows, 'rgb_context')
    fit = net.fit(x, y, design['head_settings'], class_count=2, cancelled=cancelled)
    model = _head(fit, manifest, pin, rows, file_hash(design_file)); atomic_json(output/'model.json', model)
    if masks.validate(root)['id'] != manifest['id'] or file_hash(root/'dataset.json') != pin:
        raise ValueError('Development dataset changed during spatial fitting')
    frozen = {'version': 'paving-spatial-model-freeze-v1', 'frozen_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'model_sha256': file_hash(output/'model.json'), 'rgb_model_sha256': file_hash(baseline/'models/rgb_only/model.json'),
        'design_sha256': file_hash(design_file), 'development_dataset_sha256': pin, 'backbone_sha256': BACKBONE_SHA}
    atomic_json(output/'frozen-models.json', frozen)
    report = {'version': 'paving-spatial-development-benchmark-v1', 'dataset_id': manifest['id'], 'dataset_sha256': pin,
        'backbone_sha256': BACKBONE_SHA, 'feature_version': FEATURE_VERSION, 'design_sha256': file_hash(design_file),
        'folds': folds, 'scores': {k: binary._metrics(v) for k, v in matrices.items()},
        'macro_park_paving_iou': {k: float(np.mean([f['scores'][k]['paving_iou'] for f in folds])) for k in matrices},
        'samples': len(y), 'head_weight_change_l2': fit['weight_change_l2'], 'head_loss_history': fit['loss_history'],
        'backbone_weights_updated': False, 'head_weights_updated': True, 'model_sha256': frozen['model_sha256'],
        'production_eligible': False, 'human_labels_verified': False, 'world_blocks_generated': 0,
        'limitations': ['Pretrained backbone is ADE20K perspective-scene segmentation, not a park orthophoto specialist.',
            'Only a binary neural head is fitted. No end-to-end backbone fine-tuning is claimed.',
            'Development labels are provisional assistant traces, not independent human ground truth.',
            'Reserved test data has not entered fitting; this report covers only existing development parks.',
            'Upstream SegFormer licence permits non-commercial research/evaluation only.']}
    atomic_json(output/'report.json', report)
    return report


def boundary_f1(target, positive, tolerance=2):
    known = target != 255; safe_area = ndimage.binary_erosion(known, iterations=tolerance+1)
    truth = target == 1
    tb = (truth & ~ndimage.binary_erosion(truth)) & safe_area
    pb = (positive & ~ndimage.binary_erosion(positive)) & safe_area
    nt, npred = int(tb.sum()), int(pb.sum())
    if not nt:
        return {'status': 'no_evaluable_known_target_boundaries', 'f1': None, 'target_boundary_pixels': 0}
    precision = int((pb & ndimage.binary_dilation(tb, iterations=tolerance)).sum())/max(1, npred)
    recall = int((tb & ndimage.binary_dilation(pb, iterations=tolerance)).sum())/nt
    return {'status': 'provisional_known_boundary_agreement', 'f1': 2*precision*recall/max(1e-12, precision+recall),
        'precision': precision, 'recall': recall, 'tolerance_native_pixels': tolerance,
        'target_boundary_pixels': nt, 'prediction_boundary_pixels': npred}


def connections(target, positive, pairs):
    true_labels, _ = ndimage.label(target == 1)
    predicted, _ = ndimage.label(positive & (target == 1)); result = []
    for pair in pairs:
        a, b = pair['a_xy'], pair['b_xy']
        if any(not isinstance(p, list) or len(p) != 2 or any(type(v) is not int or not 0 <= v < target.shape[1-i] for i, v in enumerate(p)) for p in (a, b)):
            raise ValueError('In-crop integer connection probes required')
        ax, ay = a; bx, by = b
        if not true_labels[ay, ax] or true_labels[ay, ax] != true_labels[by, bx]:
            raise ValueError('Connection endpoints must share a known true-paving component')
        passed = bool(predicted[ay, ax] and predicted[ay, ax] == predicted[by, bx])
        result.append({'id': pair['id'], 'passed': passed})
    return {'known_paving_pairs': len(result), 'recalled_pairs': sum(r['passed'] for r in result),
        'recall': sum(r['passed'] for r in result)/len(result) if result else None, 'pairs': result,
        'scope': 'Connectivity restricted to known target paving; false bridges are not credited.'}


def evaluate_once(test_directory, encoder_directory, rgb_baseline, training, design_file, annotation_seal,
                  protocol_file, output, cache, *, cancelled=lambda: False):
    output = Path(output); training = Path(training)
    if output.exists(): raise ValueError('Fresh sealed-test output required')
    test_root = Path(test_directory).resolve(); manifest = masks.validate(test_root)
    if manifest.get('reserved_test_only') is not True:
        raise ValueError('Explicitly reserved test-only masks required')
    frozen = json.loads((training/'frozen-models.json').read_text()); seal = json.loads(Path(annotation_seal).read_text())
    design = json.loads(Path(design_file).read_text()); protocol = json.loads(Path(protocol_file).read_text())
    if file_hash(training/'model.json') != frozen['model_sha256'] or file_hash(design_file) != frozen['design_sha256'] or file_hash(Path(rgb_baseline)/'models/rgb_only/model.json') != frozen['rgb_model_sha256']:
        raise ValueError('Models/design changed after test reservation')
    if seal['test_manifest_sha256'] != file_hash(test_root/'dataset.json') or seal['test_annotation_sha256'] != manifest['annotation_sha256'] or seal['frozen_models_sha256'] != file_hash(training/'frozen-models.json') or datetime.datetime.fromisoformat(seal['sealed_at_utc']) < datetime.datetime.fromisoformat(frozen['frozen_at_utc']):
        raise ValueError('Test annotations must be sealed after model freeze and remain unchanged')
    model, _ = safe._json(training/'model.json', 2000000); _parameters(model)
    rgb_model, _ = safe._json(Path(rgb_baseline)/'models/rgb_only/model.json', 2000000); binary.validate_model(rgb_model)
    for row in manifest['records']:
        if row['site_id'] != protocol['test_site_id'] or row['site_id'] in model['training_site_ids'] or row['site_id'] in rgb_model['training_site_ids'] or row['source_sha256'] in model['training_source_sha256'] or row['source_sha256'] in rgb_model['training_source_sha256']:
            raise ValueError('Reserved test source/park must be absent from all fitting data')
        receipt = json.loads((test_root/row['metadata_file']).read_text())
        expected_crop = [receipt['width']//4, receipt['height']//4, 3*receipt['width']//4, 3*receipt['height']//4]
        if row['crop_pixels'] != expected_crop:
            raise ValueError('Reserved test must use the predeclared central-half crop')
    key = digest({'models': frozen, 'annotation_seal': seal, 'protocol_sha256': file_hash(protocol_file), 'threshold': .5})
    marker = training/'test-consumed.json'; replay = marker.exists()
    if replay and json.loads(marker.read_text())['evaluation_key'] != key:
        raise ValueError('Reserved test already consumed with different frozen inputs; reserve a new area')
    if not replay:
        with marker.open('x') as stream: json.dump({'evaluation_key': key, 'frozen_models_sha256': file_hash(training/'frozen-models.json')}, stream)
    encoder = SpatialEncoder(encoder_directory)
    _, _, rows = _read_rows(test_root, encoder, cache, fitting=False, cancelled=cancelled)
    output.mkdir(parents=True); results = []
    for row in rows:
        p = {'rgb': binary.probabilities(_rgb_features(row), rgb_model)[:, :, 1],
            'spatial_head': probabilities(row['features'], model, cancelled=cancelled)[:, :, 1],
            'segformer_zero_shot': zero_shot(row['features']), 'always_paving': np.ones(row['target'].shape, np.float32)}
        scores = {}
        for name, values in p.items():
            positive = values >= .5
            scores[name] = {**_score(row['target'], positive),
                'boundary': boundary_f1(row['target'], positive, design['boundary_tolerance_native_pixels']),
                'connections': connections(row['target'], positive, seal['connection_probes'].get(row['record']['id'], []))}
            if name != 'always_paving': _preview(row, values, output/row['record']['id']/name)
        results.append({'id': row['record']['id'], 'source_in_training': False, 'scores': scores})
    report = {'version': 'paving-sealed-spatial-test-v1', 'evaluation_key': key,
        'deterministic_replay_of_same_sealed_inputs': replay, 'test_dataset_id': manifest['id'],
        'test_manifest_sha256': file_hash(test_root/'dataset.json'), 'annotation_seal_sha256': file_hash(annotation_seal),
        'frozen_models': frozen, 'results': results, 'head_weights_updated': False, 'backbone_weights_updated': False,
        'production_eligible': False, 'human_labels_verified': False, 'world_blocks_generated': 0,
        'limitations': ['One newly reserved paving area; labels are still provisional assistant visual drafts.',
            'Unseen to this paving fitting set does not prove absence from upstream ADE20K/ImageNet pretraining.',
            'No settings/models may be tuned using this score and reuse it as an untouched final test.',
            'Native sampling and boundary tolerance do not establish surveyed physical accuracy.']}
    atomic_json(output/'report.json', report); return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='action', required=True)
    fit = sub.add_parser('train')
    for key in ('dataset', 'encoder', 'rgb-baseline', 'design', 'output', 'cache'): fit.add_argument('--'+key, required=True)
    evaluate = sub.add_parser('evaluate')
    for key in ('test-dataset', 'encoder', 'rgb-baseline', 'training', 'design', 'annotation-seal', 'protocol', 'output', 'cache'): evaluate.add_argument('--'+key, required=True)
    args = parser.parse_args(argv)
    if args.action == 'train': result = train(args.dataset, args.encoder, args.rgb_baseline, args.design, args.output, args.cache)
    else: result = evaluate_once(args.test_dataset, args.encoder, args.rgb_baseline, args.training, args.design, args.annotation_seal, args.protocol, args.output, args.cache)
    print(json.dumps(result))


if __name__ == '__main__': main()
