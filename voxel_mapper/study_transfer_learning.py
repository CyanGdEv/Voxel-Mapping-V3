"""Frozen CPU visual descriptors with fitted component and whole-crop mask heads.

The registered encoder never learns from this dataset. Its source-only features
are extracted once; every evaluation fold fits its own normalization and ridge
heads. Reviewed masks, class labels and source identities are never inputs to
the encoder or to prediction.
"""
from concurrent.futures import CancelledError
import json
import math
from pathlib import Path
import shutil
import tempfile

import numpy as np

from . import study_component_learning as baseline
from . import study_context_learning as context
from . import study_pretrained_encoder as encoder
from . import study_vision_learning as vision
from .building_spec import digest
from .generation_cycles import atomic_json

VERSION = 'study-pretrained-transfer-v1'
SCOPE = vision.SCOPE
RIDGE_ALPHA = 100.
GRID = 16
MAX_FEATURES = 1280
MAX_MODEL_BYTES = 24_000_000
MAX_REPORT_BYTES = 24_000_000
MAX_OUTPUT_BYTES = 128_000_000
MAX_FIT_MEMORY_BYTES = 256_000_000
MAX_HEAD_WORK = 40_000_000_000
MAX_BASELINE_WORK = 2_000_000_000
BASELINE_EPOCHS = 150
BASELINE_HIDDEN_UNITS = 16
MASK_THRESHOLD = vision.MASK_THRESHOLD
PARAMETER_KEYS = ('class_weights', 'class_bias', 'mask_weights', 'mask_bias')
read_dataset = vision.read_dataset


def _check(cancelled):
    if cancelled():
        raise CancelledError('Study pretrained transfer learning cancelled')


def _alpha(value):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and .1 <= value <= 10_000
    except (OverflowError, TypeError):
        valid = False
    if not valid:
        raise ValueError('Finite ridge alpha from 0.1 through 10000 required')
    return float(value)


def _array(value, shape, name, *, low=-1_000_000., high=1_000_000.):
    def bounded(item, dimensions):
        if isinstance(item, np.ndarray):
            return (item.shape == dimensions and item.dtype.kind in 'fiu'
                and bool(np.isfinite(item).all()) and bool((item >= low).all()) and bool((item <= high).all()))
        if not dimensions:
            try:
                return type(item) in (int, float) and low <= item <= high and math.isfinite(item)
            except (OverflowError, TypeError):
                return False
        return isinstance(item, list) and len(item) == dimensions[0] and all(bounded(v, dimensions[1:]) for v in item)
    if not bounded(value, shape):
        raise ValueError('Finite bounded transfer array required: '+name)
    return np.asarray(value, dtype=np.float64)


def _parameters(value, features, classes):
    if not isinstance(value, dict) or set(value) != set(PARAMETER_KEYS):
        raise ValueError('Exact transfer head parameter inventory required')
    shapes = {'class_weights': (features, classes), 'class_bias': (classes,),
        'mask_weights': (features, GRID*GRID), 'mask_bias': (GRID*GRID,)}
    return {key: _array(value[key], shape, key) for key, shape in shapes.items()}


def _features(value):
    if (not isinstance(value, np.ndarray) or value.ndim != 2
            or value.dtype.kind not in 'fiu' or not 1 <= value.shape[0] <= baseline.MAX_RECORDS
            or not 1 <= value.shape[1] <= MAX_FEATURES or not np.isfinite(value).all()
            or np.any(value > 10_000) or np.any(value < -10_000)):
        raise ValueError('Bounded finite N by D frozen feature matrix required')
    return value.astype(np.float64, copy=False)


def _reduced_masks(masks):
    if (not isinstance(masks, np.ndarray) or masks.ndim != 3 or masks.dtype.kind not in 'fiu'
            or not 1 <= len(masks) <= baseline.MAX_RECORDS or masks.shape[1] not in (32, 64)
            or masks.shape[2] != masks.shape[1] or not np.isfinite(masks).all()
            or np.any((masks < 0) | (masks > 1))):
        raise ValueError('Bounded target mask coverage arrays required')
    stride = masks.shape[1]//GRID
    return masks.reshape(len(masks), GRID, stride, GRID, stride).mean(axis=(2, 4)).reshape(len(masks), -1)


def _ridge(x, y, alpha, weights=None, cancelled=lambda: False):
    """Weighted dual ridge with a fitted, unregularized intercept.

    Alpha regularizes the sum-of-squares normal equations, without dividing it
    by record count. Centering uses the exact same weights as the Gram matrix.
    """
    alpha = _alpha(alpha)
    x = _features(x)
    if (not isinstance(y, np.ndarray) or y.ndim != 2 or y.dtype.kind not in 'fiu'
            or y.shape[0] != len(x) or not 1 <= y.shape[1] <= GRID*GRID
            or not np.isfinite(y).all() or np.any(np.abs(y) > 10_000)):
        raise ValueError('Matching finite bounded ridge target matrix required')
    y = y.astype(np.float64, copy=False)
    n, d, rhs = len(x), x.shape[1], y.shape[1]
    memory = 8*(5*n*n+5*n*d+5*n*rhs+2*d*rhs)
    work = n*n*d+n*n*n+n*n*rhs+n*d*rhs
    if memory > MAX_FIT_MEMORY_BYTES or work > MAX_HEAD_WORK:
        raise ValueError('Ridge system exceeds bounded fitting work/memory')
    w = np.ones(len(x)) if weights is None else _array(weights, (len(x),), 'ridge sample weights', low=1e-12, high=baseline.MAX_RECORDS)
    _check(cancelled)
    xmean = np.average(x, axis=0, weights=w)
    ymean = np.average(y, axis=0, weights=w)
    root = np.sqrt(w)[:, None]
    xw, yw = (x-xmean)*root, (y-ymean)*root
    gram = xw@xw.T
    gram.flat[::len(x)+1] += alpha
    _check(cancelled)
    dual = np.linalg.solve(gram, yw)
    _check(cancelled)
    coefficients = xw.T@dual
    bias = ymean-xmean@coefficients
    if not np.isfinite(coefficients).all() or not np.isfinite(bias).all():
        raise ValueError('Finite ridge solution required')
    return coefficients, bias


def _fit(features, masks, labels, *, ridge_alpha=RIDGE_ALPHA, cancelled=lambda: False):
    alpha = _alpha(ridge_alpha)
    x = _features(features)
    target_masks = _reduced_masks(masks)
    if (not isinstance(labels, (list, tuple)) or len(labels) != len(x) or len(masks) != len(x)
            or any(not isinstance(label, str) or not 1 <= len(label) <= 80 for label in labels)):
        raise ValueError('One bounded component label and mask per frozen feature row required')
    classes = sorted(set(labels))
    if not 1 <= len(classes) <= 16:
        raise ValueError('One to sixteen fitting component classes required')
    mean, scale = x.mean(axis=0), np.maximum(x.std(axis=0), .1)
    z = (x-mean)/scale
    truth = np.asarray([classes.index(label) for label in labels])
    counts = np.bincount(truth, minlength=len(classes))
    weights = len(x)/(len(classes)*counts[truth])
    target_classes = np.eye(len(classes))[truth]
    class_w, class_b = _ridge(z, target_classes, alpha, weights, cancelled)
    mask_w, mask_b = _ridge(z, target_masks, alpha, cancelled=cancelled)
    initial_class_bias = np.average(target_classes, axis=0, weights=weights)
    initial_mask_bias = target_masks.mean(axis=0)
    initial = {'class_weights': np.zeros_like(class_w).tolist(), 'class_bias': initial_class_bias.tolist(),
        'mask_weights': np.zeros_like(mask_w).tolist(), 'mask_bias': initial_mask_bias.tolist()}
    def class_mse(predicted):
        return float(np.sum(weights[:, None]*(predicted-target_classes)**2)/(weights.sum()*len(classes)))
    initial_class, final_class = class_mse(initial_class_bias[None]), class_mse(z@class_w+class_b)
    initial_mask = float(np.mean((initial_mask_bias-target_masks)**2))
    final_mask = float(np.mean((z@mask_w+mask_b-target_masks)**2))
    parameters = {'class_weights': class_w.tolist(), 'class_bias': class_b.tolist(),
        'mask_weights': mask_w.tolist(), 'mask_bias': mask_b.tolist()}
    training = {'records': len(x), 'ridge_alpha': alpha, 'optimizer': 'weighted_dual_ridge_closed_form',
        'class_balanced': True, 'bias_regularized': False, 'encoder_weights_updated': False,
        'encoder_finetuned': False, 'head_weights_updated': bool(np.any(class_w != 0) or np.any(mask_w != 0)),
        'initial_parameters_sha256': digest(initial),
        'initial_class_loss': initial_class, 'final_class_loss': final_class,
        'initial_mask_loss': initial_mask, 'final_mask_loss': final_mask,
        'initial_loss': initial_class+initial_mask, 'final_loss': final_class+final_mask,
        'loss_semantics': 'Class-balanced mean squared one-hot error plus unweighted mean squared 16x16 mask coverage error; fitting statistics, not held-out quality.',
        'class_weighting': 'n/(number_of_training_classes * training_class_count)',
        'ridge_convention': 'alpha regularizes summed squared errors; intercept is weighted-centered and unregularized.'}
    return {'mean': mean.tolist(), 'scale': scale.tolist()}, parameters, training, classes


def _probabilities(scores):
    values = np.exp(scores-scores.max(axis=1, keepdims=True))
    return values/values.sum(axis=1, keepdims=True)


def _infer(model, features):
    x = _features(features)
    d, k = model['architecture']['feature_count'], len(model['classes'])
    if x.shape[1] != d:
        raise ValueError('Registered transfer feature count changed')
    parameters = _parameters(model['parameters'], d, k)
    mean = np.asarray(model['normalization']['mean'])
    scale = np.asarray(model['normalization']['scale'])
    z = (x-mean)/scale
    probabilities = _probabilities(z@parameters['class_weights']+parameters['class_bias'])
    masks = np.clip(z@parameters['mask_weights']+parameters['mask_bias'], 0., 1.).reshape(len(x), GRID, GRID)
    repeat = model['input_size']//GRID
    return probabilities, masks.repeat(repeat, axis=1).repeat(repeat, axis=2)


def _seal(model):
    model['artifact_sha256'] = digest({k: v for k, v in model.items() if k != 'artifact_sha256'})
    return model


def validate_model(model):
    if (not isinstance(model, dict) or model.get('version') != VERSION
            or model.get('artifact_sha256') != digest({k: v for k, v in model.items() if k != 'artifact_sha256'})
            or model.get('prediction_scope') != SCOPE
            or any(model.get(key) is not False for key in ('production_eligible', 'automatic_promotion',
                'geometry_generated', 'physical_acceptance', 'encoder_weights_updated', 'encoder_finetuned'))
            or model.get('mask_predictions_generated') is not True or model.get('encoder_weights_bundled') is not True
            or model.get('park_world_blocks_added') != 0):
        raise ValueError('Exact research-only frozen-encoder transfer checkpoint required')
    dataset_kind = model.get('dataset_kind')
    if not isinstance(dataset_kind, str) or not 1 <= len(dataset_kind) <= 256:
        raise ValueError('Pinned transfer dataset kind required')
    info = encoder.validate_info(model.get('encoder'), allow_synthetic=dataset_kind.startswith('synthetic'))
    if model.get('encoder_sha256') != info['sha256'] or model.get('encoder_file') != 'encoder.onnx':
        raise ValueError('Pinned portable encoder reference required')
    if 'encoder_pretrained' in model and model['encoder_pretrained'] is not (not info['synthetic']):
        raise ValueError('Exact pretrained versus synthetic encoder status required')
    classes = model.get('classes')
    if (not isinstance(classes, list) or not 1 <= len(classes) <= 16
            or any(not isinstance(c, str) or not 1 <= len(c) <= 80 for c in classes)
            or classes != sorted(set(classes))):
        raise ValueError('Bounded unique transfer component classes required')
    d = info['feature_count']
    architecture = {'feature_count': d, 'class_count': len(classes), 'mask_grid': GRID,
        'input_size': model.get('input_size'), 'head_kind': 'frozen_features_ridge_v1', 'mask_upsampling': 'nearest'}
    if type(model.get('input_size')) is not int or model['input_size'] not in (32, 64) or model.get('architecture') != architecture:
        raise ValueError('Exact bounded transfer head architecture required')
    norm = model.get('normalization')
    if not isinstance(norm, dict) or set(norm) != {'mean', 'scale'}:
        raise ValueError('Training-only transfer feature normalization required')
    _array(norm['mean'], (d,), 'feature mean', low=-10_000, high=10_000)
    _array(norm['scale'], (d,), 'feature scale', low=.1, high=10_000)
    _parameters(model.get('parameters'), d, len(classes))
    for key in ('dataset_id', 'dataset_file_sha256', 'training_input_sha256',
                'training_target_mask_sha256', 'training_features_sha256'):
        if not baseline._hash(model.get(key)):
            raise ValueError('Pinned transfer dataset and fitted feature lineage required')
    for key in ('training_sources', 'training_buildings', 'training_record_ids', 'training_group_ids'):
        values = model.get(key)
        if (not isinstance(values, list) or not 1 <= len(values) <= baseline.MAX_RECORDS
                or any(not isinstance(v, str) or not 1 <= len(v) <= 256 for v in values)
                or values != sorted(set(values))):
            raise ValueError('Bounded unique transfer lineage required')
        if key in ('training_sources', 'training_group_ids') and any(not baseline._hash(v) for v in values):
            raise ValueError('Pinned transfer source/group lineage required')
    training = model.get('training')
    if (not isinstance(training, dict) or training.get('records') != len(model['training_record_ids'])
            or training.get('optimizer') != 'weighted_dual_ridge_closed_form'
            or training.get('encoder_weights_updated') is not False or training.get('encoder_finetuned') is not False
            or type(training.get('head_weights_updated')) is not bool or training.get('bias_regularized') is not False
            or training.get('class_balanced') is not True or not baseline._hash(training.get('initial_parameters_sha256'))):
        raise ValueError('Exact fitted ridge-head training metadata required')
    _alpha(training.get('ridge_alpha'))
    for key in ('initial_loss', 'final_loss', 'initial_class_loss', 'final_class_loss', 'initial_mask_loss', 'final_mask_loss'):
        value = training.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100_000:
            raise ValueError('Finite transfer fitting loss metadata required')
    return model


def save_model(model, path):
    validate_model(model)
    path = Path(path)
    if path.exists():
        raise ValueError('Fresh transfer checkpoint file required')
    if len(json.dumps(model, indent=2, sort_keys=True, allow_nan=False).encode('utf-8')) > MAX_MODEL_BYTES:
        raise ValueError('Transfer checkpoint exceeds bounded JSON size')
    atomic_json(path, model)


def load_model(path):
    model, _ = baseline._json(path, MAX_MODEL_BYTES)
    return validate_model(model)


load = load_model
save = save_model


def predict(model, image, *, encoder_path, encoder_sha256):
    validate_model(model)
    if encoder_sha256 != model['encoder_sha256']:
        raise ValueError('Prediction requires the checkpoint exact registered encoder SHA-256')
    if isinstance(image, bytes):
        raw = image
    else:
        path = Path(image)
        if not path.is_file() or path.stat().st_size > baseline.MAX_IMAGE_BYTES:
            raise ValueError('Bounded source PNG required')
        raw = path.read_bytes()
    features = encoder.extract([raw], encoder_path, encoder_sha256,
        allow_synthetic=model['dataset_kind'].startswith('synthetic'))
    probabilities, masks = _infer(model, features)
    return {'kind': model['classes'][int(np.argmax(probabilities[0]))],
        'probabilities': dict(zip(model['classes'], map(float, probabilities[0]))),
        'mask_probabilities': masks[0].tolist(), 'mask_size': [model['input_size']]*2,
        'mask_threshold': MASK_THRESHOLD, 'model_sha256': model['artifact_sha256'],
        'input_sha256': baseline._sha(raw), 'encoder_sha256': encoder_sha256,
        'production_eligible': False, 'automatic_promotion': False, 'geometry_generated': False,
        'mask_predictions_generated': True, 'physical_acceptance': False,
        'encoder_weights_updated': False, 'encoder_finetuned': False,
        'park_world_blocks_added': 0, 'prediction_scope': SCOPE}


def _feature_pin(features):
    values = np.ascontiguousarray(features, dtype='<f4')
    return digest({'shape': list(values.shape), 'dtype': 'little-endian-float32', 'sha256': baseline._sha(values.tobytes())})


def _make_model(rows, features, masks, dataset, raw_pin, info, alpha, input_size, cancelled):
    norm, parameters, training, classes = _fit(features, masks, [r['kind'] for r in rows],
        ridge_alpha=alpha, cancelled=cancelled)
    return _seal({'version': VERSION, 'input_size': input_size, 'classes': classes,
        'architecture': {'feature_count': info['feature_count'], 'class_count': len(classes), 'mask_grid': GRID,
            'input_size': input_size, 'head_kind': 'frozen_features_ridge_v1', 'mask_upsampling': 'nearest'},
        'normalization': norm, 'parameters': parameters, 'training': training,
        'encoder': info, 'encoder_sha256': info['sha256'], 'encoder_file': 'encoder.onnx',
        'encoder_pretrained': not info['synthetic'],
        'encoder_weights_updated': False, 'encoder_finetuned': False, 'encoder_weights_bundled': True,
        'dataset_id': dataset['id'], 'dataset_kind': dataset['dataset_kind'], 'dataset_file_sha256': raw_pin,
        'training_sources': sorted({r['source']['document_sha256'] for r in rows}),
        'training_buildings': sorted({r['building_id'] for r in rows}),
        'training_record_ids': sorted(r['id'] for r in rows), 'training_group_ids': sorted({r['group_id'] for r in rows}),
        'training_input_sha256': digest([[r['id'], r['input_sha256']] for r in rows]),
        'training_target_mask_sha256': digest([[r['id'], dataset['output_sha256'][r['target_mask_file']]] for r in rows]),
        'training_features_sha256': _feature_pin(features), 'prediction_scope': SCOPE,
        'production_eligible': False, 'automatic_promotion': False, 'geometry_generated': False,
        'mask_predictions_generated': True, 'physical_acceptance': False, 'park_world_blocks_added': 0,
        'limitations': ['The source crop is supplied; full-page discovery and independent crop localization are unassessed.',
            ('Only linear class and 16x16 mask heads are fitted. The generic ImageNet encoder remains frozen.'
                if not info['synthetic'] else 'The RGB-mean encoder is an explicit synthetic runtime fixture, not pretrained visual AI. Only its linear heads are fitted.'),
            'The 16x16 mask decoder and nearest upsampling limit boundary resolution.',
            'Predicted masks are proposals, not accepted metric outlines, complete physical buildings or world placement.',
            'Previously inspected source traces are supervision, not independently authenticated physical ground truth.',
            'The final checkpoint fits all eligible records; evaluation uses separate source/building-disjoint fold heads.',
            'No reported quality result automatically promotes this model or accepts physical geometry.']})


def _work_plan(rows, folds, features, classes):
    counts = [sum(row['group_id'] not in fold for row in rows) for fold in folds]+[len(rows)]
    def one(n):
        # Two dual systems, with class and mask right-hand sides, plus final W.
        work = 2*n*n*features+2*n*n*n+n*n*(GRID*GRID+classes)+n*features*(GRID*GRID+classes)
        memory = 8*(5*n*n+5*n*features+5*n*(GRID*GRID+classes)+2*features*(GRID*GRID+classes))
        return {'dense_head_work_upper_bound': work, 'fit_memory_bytes_upper_bound': memory, 'records': n}
    fits = [one(n) for n in counts]
    work = sum(item['dense_head_work_upper_bound'] for item in fits)
    old_work = sum(counts[:-1])*BASELINE_EPOCHS*baseline.INPUT_SIZE**2*BASELINE_HIDDEN_UNITS
    if work > MAX_HEAD_WORK or old_work > MAX_BASELINE_WORK or any(item['fit_memory_bytes_upper_bound'] > MAX_FIT_MEMORY_BYTES for item in fits):
        raise ValueError('Frozen transfer head work/memory budget exceeded; reduce dataset or independent fold count')
    return {'estimated_dense_head_work': work, 'max_dense_head_work': MAX_HEAD_WORK,
        'estimated_baseline_work': old_work, 'max_baseline_work': MAX_BASELINE_WORK,
        'all_data_fit_work_estimate': fits[-1], 'max_fit_memory_bytes': MAX_FIT_MEMORY_BYTES,
        'max_records': baseline.MAX_RECORDS, 'max_features': MAX_FEATURES,
        'max_source_group_folds': baseline.MAX_GROUP_FOLDS, 'max_model_bytes': MAX_MODEL_BYTES,
        'max_output_bytes': MAX_OUTPUT_BYTES, 'encoder_feature_extraction_passes': 1}


def _bundle_encoder(stage, source, info):
    source = Path(source)
    if not source.is_file() or source.stat().st_size != info['bytes']:
        raise ValueError('Bounded frozen encoder changed before bundling')
    with source.open('rb') as stream:
        raw = stream.read(info['bytes']+1)
    if len(raw) != info['bytes'] or baseline._sha(raw) != info['sha256']:
        raise ValueError('Frozen encoder changed before bundling')
    (stage/'encoder.onnx').write_bytes(raw)
    atomic_json(stage/'encoder.json', info)
    for name, content in encoder.attribution_assets(info).items():
        path = baseline._asset(stage.resolve(), name)
        if len(content) > 256_000 or path.exists():
            raise ValueError('Bounded fresh encoder attribution asset required')
        path.write_bytes(content)
    (stage/'ENCODER-PROVENANCE.md').write_text('# Frozen visual encoder\n\n'+
        'Encoder weights are bundled unchanged and were not fine-tuned on this dataset.\n\n'+
        'The separate linear class and mask heads are fitted by weighted/unweighted ridge regression.\n\n'+
        'See encoder.json for the registered model SHA-256, preprocessing, upstream provenance and license pins.\n', encoding='utf-8')


def train(dataset_directory, output, *, encoder_path, encoder_sha256,
          ridge_alpha=RIDGE_ALPHA, input_size=64, cancelled=lambda: False, progress=lambda value: None):
    alpha = _alpha(ridge_alpha)
    if type(input_size) is not int or input_size not in (32, 64) or not callable(cancelled) or not callable(progress):
        raise ValueError('Bounded transfer mask size 32/64 and callbacks required')
    output = Path(output)
    if output.exists():
        raise ValueError('Fresh study transfer output required')
    _check(cancelled)
    dataset, rows, images, masks, x16, raw_pin = read_dataset(dataset_directory, input_size=input_size, cancelled=cancelled)
    classes = sorted({row['kind'] for row in rows})
    if not 2 <= len(classes) <= 16:
        raise ValueError('Two to sixteen source component classes required')
    metadata = context._audit_metadata(rows)
    info = encoder.encoder_info(encoder_path, encoder_sha256, allow_synthetic=dataset['dataset_kind'].startswith('synthetic'))
    info.pop('path', None)
    groups, folds, mode = context._folds(rows)
    limits = _work_plan(rows, folds, info['feature_count'], len(classes))
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output.parent).free < MAX_OUTPUT_BYTES:
        raise ValueError('At least 128 MB free disk required before transfer training')
    root = Path(dataset_directory).expanduser().resolve()
    source_pngs = []
    for row in rows:
        _check(cancelled)
        path = baseline._asset(root, row['input_file'])
        if not path.is_file() or path.stat().st_size > baseline.MAX_IMAGE_BYTES:
            raise ValueError('Bounded source PNG required before frozen feature extraction')
        with path.open('rb') as stream:
            raw = stream.read(baseline.MAX_IMAGE_BYTES+1)
        if len(raw) > baseline.MAX_IMAGE_BYTES or baseline._sha(raw) != row['input_sha256']:
            raise ValueError('Source PNG changed before frozen feature extraction')
        source_pngs.append(raw)
    features = encoder.extract(source_pngs, encoder_path, encoder_sha256,
        allow_synthetic=dataset['dataset_kind'].startswith('synthetic'), cancelled=cancelled,
        progress=lambda event: progress({**event, 'progress': .03+.17*event.get('progress', 0.)}))
    _features(features)
    if features.shape != (len(rows), info['feature_count']):
        raise ValueError('Registered frozen feature matrix dimensions changed')
    evaluation = {'status': mode, 'source_groups': len(groups), 'folds': [], 'predictions': [],
        **context._summarize([], classes), 'scope': 'Source/building-disjoint evaluation of supplied crops; frozen encoder shared, every fitted normalization/head uses training groups only.'}
    with tempfile.TemporaryDirectory(prefix='study-transfer-training-', dir=output.parent) as temporary:
        stage = Path(temporary)/'output'
        (stage/'predictions').mkdir(parents=True)
        _bundle_encoder(stage, encoder_path, info)
        for index, held_groups in enumerate(folds):
            _check(cancelled)
            train_indices = [i for i, row in enumerate(rows) if row['group_id'] not in held_groups]
            held_indices = [i for i, row in enumerate(rows) if row['group_id'] in held_groups]
            fitting, held = [rows[i] for i in train_indices], [rows[i] for i in held_indices]
            start, extent = .2+.62*index/max(1, len(folds)), .62/max(1, len(folds))
            progress({'progress': start, 'message': 'Fitting frozen-encoder heads for source-disjoint fold '+str(index+1)+' of '+str(len(folds)), 'fold': index+1, 'folds': len(folds)})
            model = _make_model(fitting, features[train_indices], masks[train_indices], dataset, raw_pin, info, alpha, input_size, cancelled)
            probability, predicted_masks = _infer(model, features[held_indices])
            guessed = [model['classes'][int(np.argmax(p))] for p in probability]
            majority = min(model['classes'], key=lambda kind: (-sum(row['kind'] == kind for row in fitting), kind))
            mean_mask = masks[train_indices].mean(axis=0)
            old_model = baseline._make_model(fitting, x16[train_indices], BASELINE_EPOCHS, BASELINE_HIDDEN_UNITS,
                index, dataset['id'], cancelled, context._progress(progress, start+extent*.15, extent*.85, 'Fitting fixed 16px baseline for transfer fold '+str(index+1)))
            old_p = baseline._probabilities(old_model, x16[held_indices])
            old_guessed = [old_model['classes'][int(np.argmax(p))] for p in old_p]
            eval_sources = {row['source']['document_sha256'] for row in held}
            if (set(model['training_sources']) & eval_sources or set(model['training_buildings']) & {row['building_id'] for row in held}
                    or set(model['training_record_ids']) & {row['id'] for row in held}):
                raise ValueError('Source/building/record leakage in frozen transfer evaluation')
            truth = [row['kind'] for row in held]
            unknown = sorted(set(truth)-set(model['classes']))
            per_masks = [vision._mask_metrics(masks[i], predicted) for i, predicted in zip(held_indices, predicted_masks)]
            per_prior = [vision._mask_metrics(masks[i], mean_mask) for i in held_indices]
            fold = {'id': index, 'held_out_group_ids': held_groups, 'training_group_ids': model['training_group_ids'],
                'training_buildings': model['training_buildings'], 'training_sources': model['training_sources'],
                'training_record_ids': model['training_record_ids'], 'evaluation_record_ids': sorted(row['id'] for row in held),
                'evaluation_buildings': sorted({row['building_id'] for row in held}), 'evaluation_sources': sorted(eval_sources),
                'training_records': len(fitting), 'evaluation_records': len(held), 'training_classes': model['classes'],
                'unknown_held_out_classes': unknown, 'unknown_class_records': sum(value in unknown for value in truth),
                'model_sha256': model['artifact_sha256'], 'normalization_sha256': digest(model['normalization']),
                'parameters_sha256': digest(model['parameters']), 'training_features_sha256': model['training_features_sha256'],
                'training': model['training'], 'encoder_sha256': encoder_sha256, 'encoder_weights_updated': False,
                'mean_mask_baseline_sha256': digest(mean_mask.tolist()), 'image16_baseline_model_sha256': old_model['artifact_sha256'],
                'image16_baseline_normalization_sha256': digest(old_model['input_normalization']),
                'image16_baseline_parameters_sha256': digest(old_model['parameters']),
                'metrics': baseline._metrics(truth, guessed, classes), 'mask_metrics': vision._mask_summary(per_masks),
                'majority_baseline_kind': majority, 'majority_baseline_metrics': baseline._metrics(truth, [majority]*len(held), classes),
                'mean_mask_baseline_metrics': vision._mask_summary(per_prior),
                'image16_baseline_metrics': baseline._metrics(truth, old_guessed, classes)}
            evaluation['folds'].append(fold)
            for item, (row, kind, p, mask, measured, prior, old_kind) in enumerate(zip(held, guessed, probability, predicted_masks, per_masks, per_prior, old_guessed)):
                _check(cancelled)
                stem = str(index).zfill(2)+'-'+str(item).zfill(4)
                prediction_file, mean_file = 'predictions/'+stem+'-predicted.png', 'predictions/'+stem+'-mean-template.png'
                prediction_pin, prior_pin = vision._save_mask(stage/prediction_file, mask), vision._save_mask(stage/mean_file, mean_mask)
                role, geometry_type = metadata[row['id']]
                evaluation['predictions'].append({'record_id': row['id'], 'group_id': row['group_id'], 'fold_id': index,
                    'input_file': row['input_file'], 'input_sha256': row['input_sha256'],
                    'target_mask_file': row['target_mask_file'], 'target_mask_sha256': dataset['output_sha256'][row['target_mask_file']],
                    'document_sha256': row['source']['document_sha256'], 'page': row['source']['page'],
                    'expected_kind': row['kind'], 'predicted_kind': kind, 'unknown_held_out_class': row['kind'] in unknown,
                    'geometry_role': role, 'geometry_type': geometry_type, 'probabilities': dict(zip(model['classes'], map(float, p))),
                    'majority_baseline_kind': majority, 'image16_baseline_kind': old_kind,
                    'mask_metrics': measured, 'mean_mask_baseline_metrics': prior,
                    'mask_prediction_file': prediction_file, 'mask_prediction_sha256': prediction_pin,
                    'predicted_mask_file': prediction_file, 'predicted_mask_sha256': prediction_pin,
                    'baseline_mask_file': mean_file, 'baseline_mask_sha256': prior_pin})
        predictions = sorted(evaluation['predictions'], key=lambda row: row['record_id'])
        evaluation.update(predictions=predictions, **context._summarize(predictions, classes),
            per_class_mask_metrics=context._stratified(predictions, 'expected_kind'),
            per_geometry_role_mask_metrics=context._stratified(predictions, 'geometry_role'),
            per_geometry_type_mask_metrics=context._stratified(predictions, 'geometry_type'),
            unknown_class_cases=[row['record_id'] for row in predictions if row['unknown_held_out_class']],
            unknown_class_evaluation=context._summarize([row for row in predictions if row['unknown_held_out_class']], classes),
            known_class_evaluation=context._summarize([row for row in predictions if not row['unknown_held_out_class']], classes))
        _check(cancelled)
        progress({'progress': .85, 'message': 'Fitting final all-data frozen-encoder ridge heads'})
        model = _make_model(rows, features, masks, dataset, raw_pin, info, alpha, input_size, cancelled)
        save_model(model, stage/'model.json')
        warnings = [value.replace('Context', 'Frozen-encoder head') for value in context._warnings(evaluation)]
        if info['synthetic']:
            warnings.append('This bundle uses the synthetic RGB-mean runtime fixture, not pretrained visual AI; its scores verify the runtime and head training only.')
        report = {'version': VERSION, 'status': 'exploratory_pretrained_transfer_trained',
            'dataset_id': dataset['id'], 'dataset_file_sha256': raw_pin, 'dataset_kind': dataset['dataset_kind'],
            'records': len(rows), 'record_ids': sorted(row['id'] for row in rows), 'classes': classes,
            'class_counts': {kind: sum(row['kind'] == kind for row in rows) for kind in classes},
            'input_size': input_size, 'ridge_alpha': alpha, 'settings_fixed_before_evaluation': True,
            'encoder': info, 'encoder_sha256': encoder_sha256, 'encoder_file': 'encoder.onnx',
            'encoder_pretrained': not info['synthetic'],
            'encoder_weights_bundled': True, 'encoder_weights_updated': False, 'encoder_finetuned': False,
            'frozen_features_sha256': _feature_pin(features), 'feature_extraction_passes': 1,
            'cross_source_evaluation': evaluation, 'model_file': 'model.json', 'model_sha256': model['artifact_sha256'],
            'model_weights_updated': model['training']['head_weights_updated'], 'head_weights_updated': model['training']['head_weights_updated'],
            'production_eligible': False, 'automatic_promotion': False, 'training_labels_generated': 0,
            'geometry_generated': False, 'mask_predictions_generated': True, 'park_world_blocks_added': 0,
            'physical_acceptance': False, 'prediction_scope': SCOPE,
            'input_features': ('Frozen registered ImageNet descriptors of full supplied RGB source PNGs; no IDs, geometry roles, reviewed masks or labels are encoder inputs.'
                if not info['synthetic'] else 'Explicit synthetic RGB-mean runtime fixture descriptors of full supplied source PNGs; not pretrained visual AI. No IDs, roles, reviewed masks or labels are encoder inputs.'),
            'mask_metric_semantics': {'soft': 'Fuzzy coverage intersection sum(min(target,prediction)), union sum(max(target,prediction)).',
                'target_resize': 'BOX average coverage preserved at the evaluation grid; mask ridge targets are further BOX-reduced to 16x16.',
                'decoder': 'Linear 16x16 coverage predictions clipped to [0,1], then nearest upsampled to the requested output grid.',
                'binary_threshold': MASK_THRESHOLD, 'binary_comparison': 'Both arrays >= threshold; fractional-only nonempty targets have unassessed binary IoU/Dice.',
                'support_comparison': 'Prediction >= threshold versus any target coverage >0.',
                'saved_prediction_png': 'Rounded probability*255; metrics use unrounded probabilities.'},
            'baseline_comparison': {'image16_epochs': BASELINE_EPOCHS, 'image16_hidden_units': BASELINE_HIDDEN_UNITS,
                'image16_input_size': baseline.INPUT_SIZE, 'same_source_group_folds': True,
                'image16_status': 'reproduced_fixed_baseline_on_exact_current_folds',
                'mask_template': 'Class-agnostic training-only mean target mask; no held-out masks or labels.'},
            'limits': limits, 'quality_warnings': warnings,
            'group_balanced_evaluation': context._balanced_evaluation(predictions, classes),
            'final_checkpoint_fit': 'all eligible records; no untouched final-model test', 'limitations': model['limitations']}
        report['quality_warnings'].extend(context._balanced_warnings(report['group_balanced_evaluation']))
        context._write_gallery(stage, report, rows, images, masks)
        gallery = stage/'index.html'
        html = gallery.read_text(encoding='utf-8')
        for old, new in (('Held-out whole-crop context review', 'Held-out frozen-encoder head review'),
                ('Context class accuracy:', 'Frozen-encoder head class accuracy:'),
                ('Context mean soft mask IoU:', 'Frozen-encoder head mean soft mask IoU:'),
                ('The context model scored below', 'The frozen-encoder heads scored below'),
                ('Context mask proposal', 'Frozen-encoder mask head proposal'),
                ('Out-of-fold context mask proposal', 'Out-of-fold frozen-encoder mask proposal'),
                ('Context soft IoU', 'Frozen-encoder head soft IoU')):
            html = html.replace(old, new)
        gallery.write_text(html, encoding='utf-8')
        report['output_sha256'] = {path.relative_to(stage).as_posix(): baseline._sha(path.read_bytes())
            for path in sorted(stage.rglob('*')) if path.is_file()}
        report['artifact_sha256'] = digest(report)
        if len(json.dumps(report, indent=2, sort_keys=True, allow_nan=False).encode('utf-8')) > MAX_REPORT_BYTES:
            raise ValueError('Transfer report exceeds bounded JSON size')
        atomic_json(stage/'report.json', report)
        if sum(path.stat().st_size for path in stage.rglob('*') if path.is_file()) > MAX_OUTPUT_BYTES:
            raise ValueError('Transfer output exceeds bounded byte budget')
        progress({'progress': .97, 'message': 'Rechecking immutable dataset and encoder assets'})
        _, current_rows, _, _, _, current_pin = read_dataset(dataset_directory, input_size=input_size, cancelled=cancelled)
        if current_pin != raw_pin or current_rows != rows:
            raise ValueError('Study dataset changed during frozen transfer training')
        encoder.encoder_info(encoder_path, encoder_sha256, allow_synthetic=dataset['dataset_kind'].startswith('synthetic'))
        bundled = stage/'encoder.onnx'
        if bundled.stat().st_size != info['bytes']:
            raise ValueError('Bundled frozen encoder size changed before publication')
        with bundled.open('rb') as stream:
            bundled_raw = stream.read(info['bytes']+1)
        if baseline._sha(bundled_raw) != encoder_sha256:
            raise ValueError('Bundled frozen encoder changed before publication')
        _check(cancelled)
        if output.exists():
            raise ValueError('Fresh study transfer output required')
        stage.rename(output)
    progress({'progress': 1., 'message': 'Frozen encoder bundle, fitted research heads and held-out proposals ready'})
    return report
