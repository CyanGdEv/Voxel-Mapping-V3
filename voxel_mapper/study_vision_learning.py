"""CPU research learning of component classes and masks from supplied source crops.

Target masks supervise training only. They never enter prediction inputs. Source
and building connected groups remain intact throughout cross-validation.
"""
from concurrent.futures import CancelledError
import base64
from html import escape
from io import BytesIO
import hashlib
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image

from . import study_component_learning as baseline
from .building_spec import digest
from .generation_cycles import atomic_json

VERSION = 'study-component-vision-learning-v1'
SCOPE = 'Provided-crop component class and source-trace mask proposal; not full-page discovery, physical geometry or park placement.'
MAX_FORWARD_WORK = 24_000_000_000
MAX_BASELINE_WORK = 2_000_000_000
MAX_EPOCHS = 100
BASELINE_EPOCHS = 150
BASELINE_HIDDEN_UNITS = 16
MASK_THRESHOLD = .5


def _check(cancelled):
    if cancelled():
        raise CancelledError('Study vision learning cancelled')


def _network():
    from . import study_vision_network
    return study_vision_network


def _source_image(raw, size):
    if not isinstance(raw, bytes) or len(raw) > baseline.MAX_IMAGE_BYTES:
        raise ValueError('Bounded PNG source crop required')
    try:
        with Image.open(BytesIO(raw)) as original:
            width, height = original.size
            if (original.format != 'PNG' or not 1 <= width <= 256 or not 1 <= height <= 256
                    or getattr(original, 'n_frames', 1) != 1):
                raise ValueError('Single-frame source PNG at most 256 by 256 required')
            if original.mode in ('RGBA', 'LA') or 'transparency' in original.info:
                rgba = original.convert('RGBA')
                image = Image.new('RGBA', original.size, 'white')
                image.alpha_composite(rgba)
                image = image.convert('L')
            else:
                image = original.convert('L')
            small = image.resize((size, size), Image.Resampling.LANCZOS)
            return 1.-np.asarray(small, dtype=np.float64)/255., (width, height)
    except (OSError, Image.DecompressionBombError) as error:
        raise ValueError('Valid bounded source crop required') from error


def _target_mask(raw, size, source_size):
    if not isinstance(raw, bytes) or len(raw) > baseline.MAX_IMAGE_BYTES:
        raise ValueError('Bounded PNG target mask required')
    try:
        with Image.open(BytesIO(raw)) as image:
            if (image.format != 'PNG' or image.mode not in ('L', '1')
                    or image.size != source_size or getattr(image, 'n_frames', 1) != 1
                    or 'transparency' in image.info):
                raise ValueError('Opaque grayscale PNG target mask matching source dimensions required')
            # BOX preserves fractional foreground coverage of sub-grid traces.
            small = image.convert('L').resize((size, size), Image.Resampling.BOX)
            return np.asarray(small, dtype=np.float64)/255.
    except (OSError, Image.DecompressionBombError) as error:
        raise ValueError('Valid bounded target mask required') from error


def read_dataset(directory, *, input_size=64, cancelled=lambda: False):
    if type(input_size) is not int or input_size not in (32, 64):
        raise ValueError('Study vision input size must be 32 or 64')
    manifest, rows, x16, raw_pin = baseline.read_dataset(directory, cancelled=cancelled)
    root = Path(directory).expanduser().resolve()
    sources, masks = [], []
    for row in rows:
        _check(cancelled)
        path = baseline._asset(root, row['input_file'])
        raw = path.read_bytes()
        if baseline._sha(raw) != row['input_sha256']:
            raise ValueError('Source crop changed during vision dataset reading')
        source, dimensions = _source_image(raw, input_size)
        if 'input_size_pixels' in row and row['input_size_pixels'] != list(dimensions):
            raise ValueError('Declared source crop dimensions changed')
        name = row.get('target_mask_file')
        pin = manifest['output_sha256'].get(name)
        if (not baseline._hash(pin)
                or ('target_mask_sha256' in row and row['target_mask_sha256'] != pin)):
            raise ValueError('Exact pinned eligible target mask required')
        target_path = baseline._asset(root, name)
        if not target_path.is_file() or target_path.stat().st_size > baseline.MAX_IMAGE_BYTES:
            raise ValueError('Bounded existing target mask required')
        target_raw = target_path.read_bytes()
        if baseline._sha(target_raw) != pin:
            raise ValueError('Target mask changed during vision dataset reading')
        masks.append(_target_mask(target_raw, input_size, dimensions))
        sources.append(source)
    return manifest, rows, np.asarray(sources), np.asarray(masks), x16, raw_pin


def _seal(model):
    model['artifact_sha256'] = digest({k: v for k, v in model.items() if k != 'artifact_sha256'})
    return model


def validate_model(model):
    if (not isinstance(model, dict) or model.get('version') != VERSION
            or model.get('artifact_sha256') != digest({k: v for k, v in model.items() if k != 'artifact_sha256'})
            or model.get('prediction_scope') != SCOPE
            or model.get('production_eligible') is not False or model.get('geometry_generated') is not False
            or model.get('physical_acceptance') is not False or model.get('mask_predictions_generated') is not True
            or model.get('park_world_blocks_added') != 0):
        raise ValueError('Exact research-only component vision checkpoint required')
    network = _network().validate(model.get('network'))
    architecture = network['architecture']
    if model.get('input_size') != architecture['input_size'] or model.get('classes') != network['classes']:
        raise ValueError('Vision checkpoint network/class schema changed')
    if not baseline._hash(model.get('dataset_id')) or not baseline._hash(model.get('dataset_file_sha256')):
        raise ValueError('Pinned vision training dataset required')
    for key in ('training_sources', 'training_buildings', 'training_record_ids'):
        values = model.get(key)
        if (not isinstance(values, list) or not 1 <= len(values) <= baseline.MAX_RECORDS
                or any(not isinstance(v, str) or not v or len(v) > 256 for v in values)
                or values != sorted(set(values))):
            raise ValueError('Bounded unique vision model lineage required')
        if key == 'training_sources' and any(not baseline._hash(v) for v in values):
            raise ValueError('Pinned vision source lineage required')
    return model


def save_model(model, path):
    validate_model(model)
    path = Path(path)
    if path.exists():
        raise ValueError('Fresh vision checkpoint file required')
    atomic_json(path, model)


def load_model(path):
    value, _ = baseline._json(path, 2_000_000)
    return validate_model(value)


def predict(model, image):
    validate_model(model)
    if isinstance(image, bytes):
        raw = image
    else:
        path = Path(image)
        if not path.is_file() or path.stat().st_size > baseline.MAX_IMAGE_BYTES:
            raise ValueError('Bounded PNG source crop required')
        raw = path.read_bytes()
    values, _ = _source_image(raw, model['input_size'])
    probabilities, masks = _network().infer(model['network'], values[None])
    probabilities, mask = probabilities[0], masks[0]
    if mask.shape != (model['input_size'], model['input_size']):
        raise ValueError('Vision mask output grid changed')
    return {'kind': model['classes'][int(np.argmax(probabilities))],
        'probabilities': dict(zip(model['classes'], map(float, probabilities))),
        'mask_probabilities': mask.tolist(), 'mask_size': [model['input_size']]*2,
        'mask_threshold': MASK_THRESHOLD, 'model_sha256': model['artifact_sha256'],
        'input_sha256': baseline._sha(raw), 'production_eligible': False,
        'geometry_generated': False, 'mask_predictions_generated': True,
        'physical_acceptance': False, 'park_world_blocks_added': 0, 'prediction_scope': SCOPE}


def _mask_metrics(target, predicted):
    if (target.shape != predicted.shape or not np.isfinite(predicted).all()
            or np.any((predicted < 0) | (predicted > 1))):
        raise ValueError('Finite target-grid mask probabilities required')
    minimum, maximum = float(np.minimum(target, predicted).sum()), float(np.maximum(target, predicted).sum())
    total = float(target.sum()+predicted.sum())
    soft_iou, soft_dice = (minimum/maximum if maximum else 1.), (2*minimum/total if total else 1.)
    chosen, expected, support = predicted >= MASK_THRESHOLD, target >= MASK_THRESHOLD, target > 0
    def binary(a, b):
        intersection, union = int(np.count_nonzero(a & b)), int(np.count_nonzero(a | b))
        count = int(np.count_nonzero(a))+int(np.count_nonzero(b))
        return (intersection/union if union else 1.), (2*intersection/count if count else 1.)
    thin = bool(np.any(support) and not np.any(expected))
    biou, bdice = (None, None) if thin else binary(chosen, expected)
    siou, sdice = binary(chosen, support)
    return {'soft_iou': soft_iou, 'soft_dice': soft_dice, 'binary_iou': biou, 'binary_dice': bdice,
        'support_iou': siou, 'support_dice': sdice, 'thin_target': thin,
        'target_coverage_sum': float(target.sum()), 'target_positive_pixels': int(support.sum()),
        'target_binary_pixels': int(expected.sum()), 'predicted_binary_pixels': int(chosen.sum())}


def _mask_summary(rows):
    result = {'records': len(rows), 'thin_target_records': sum(r['thin_target'] for r in rows),
        'binary_assessed_records': sum(r['binary_iou'] is not None for r in rows)}
    for key in ('soft_iou', 'soft_dice', 'binary_iou', 'binary_dice', 'support_iou', 'support_dice'):
        values = [r[key] for r in rows if r[key] is not None]
        result['mean_'+key] = float(np.mean(values)) if values else None
    return result


def _save_mask(path, values):
    pixels = np.rint(np.clip(values, 0, 1)*255).astype(np.uint8)
    Image.fromarray(pixels, mode='L').save(path, format='PNG')
    return baseline._sha(path.read_bytes())


def _make_model(rows, x, masks, dataset, raw_pin, epochs, channels, input_size, seed, cancelled, progress):
    network = _network().fit(x, masks, [r['kind'] for r in rows], epochs=epochs,
        channels=channels, seed=seed, batch_size=4, cancelled=cancelled, progress=progress)
    return _seal({'version': VERSION, 'network': network, 'input_size': input_size,
        'classes': network['classes'], 'training': network['training'],
        'dataset_id': dataset['id'], 'dataset_file_sha256': raw_pin,
        'training_buildings': sorted({r['building_id'] for r in rows}),
        'training_sources': sorted({r['source']['document_sha256'] for r in rows}),
        'training_record_ids': sorted(r['id'] for r in rows),
        'training_input_sha256': digest([[r['id'], r['input_sha256']] for r in rows]),
        'training_target_mask_sha256': digest([[r['id'], dataset['output_sha256'][r['target_mask_file']]] for r in rows]),
        'production_eligible': False, 'prediction_scope': SCOPE, 'geometry_generated': False,
        'mask_predictions_generated': True, 'physical_acceptance': False, 'park_world_blocks_added': 0,
        'limitations': ['Research training on previously inspected, supplied source crops and reviewed trace masks.',
            'The crop frame is supplied by the dataset; full-page object discovery and independent crop localization are unassessed.',
            'Predicted raster masks are proposals, not accepted outlines, metric geometry, physical 3D buildings or world blocks.',
            'Study label provenance is retained; it is not authenticated physical ground truth.',
            'Final weights fit all eligible records; cross-validation assesses separate fold models, not an untouched final checkpoint.']})



def _write_gallery(root, report, rows, images, masks):
    """Offline held-out predictions, always separated from source and supervision."""
    lookup = {row['id']: i for i, row in enumerate(rows)}
    evaluation = report['cross_source_evaluation']
    def number(value):
        return 'unassessed' if value is None else f'{100*value:.1f}%'
    def metric(name, key):
        return (evaluation.get(name) or {}).get(key)
    def data_uri(values):
        stream = BytesIO()
        Image.fromarray(np.rint(np.clip(values, 0, 1)*255).astype(np.uint8)).save(stream, format='PNG')
        return 'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode('ascii')
    body = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>Held-out component vision review</title><style>body{font:16px system-ui;margin:2rem;color:#203040}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccd3da;padding:.6rem;vertical-align:top}img{width:128px;max-width:100%;image-rendering:pixelated}small{overflow-wrap:anywhere}.notice{padding:1rem;background:#fff0da}caption{text-align:left;margin:1rem 0}</style>',
        '<h1>Held-out component vision review</h1><p class="notice">Research only. These predictions come from models fitted without the displayed source/building group. '
        'The separate final model.json checkpoint fits all eligible records; this gallery is not an untouched test of that final checkpoint. '
        'Predicted masks are proposals, with no accepted geometry, complete buildings or park placement.</p>',
        '<p>CNN class accuracy: '+number(metric('metrics', 'accuracy'))+
        '; majority class: '+number(metric('majority_baseline_metrics', 'accuracy'))+
        '; 16px classifier: '+number(metric('image16_baseline_metrics', 'accuracy'))+
        '. CNN mean soft mask IoU: '+number(metric('mask_metrics', 'mean_soft_iou'))+
        '; training-only template: '+number(metric('mean_mask_baseline_metrics', 'mean_soft_iou'))+'.</p>']
    comparisons = [(metric('metrics', 'accuracy'), metric('image16_baseline_metrics', 'accuracy')),
        (metric('mask_metrics', 'mean_soft_iou'), metric('mean_mask_baseline_metrics', 'mean_soft_iou'))]
    if any(a is not None and b is not None and a < b for a, b in comparisons):
        body.append('<p class="notice"><strong>The CNN scored below comparison baselines on these held-out study crops. No accuracy improvement or production readiness is established.</strong></p>')
    body.append('<p><a href="report.json">Exact metrics and lineage</a> · <a href="model.json">Final all-data research checkpoint</a>. '
        'Source identifiers are displayed for audit only and never enter image inputs. Source and target pictures are resized grayscale arrays; target gray levels retain fractional coverage.</p>')
    if not evaluation['predictions']:
        body.append('<p>No held-out predictions: at least two independent source/building groups are needed.</p>')
    else:
        body.append('<table><caption>Out-of-fold predictions. Source pixels, reviewed supervision and generated masks are separate.</caption>'
            '<thead><tr><th>Source crop</th><th>Reviewed target coverage</th><th>CNN mask proposal</th><th>Training-only mean template</th></tr></thead><tbody>')
    size = sum(len(part.encode('utf-8')) for part in body)
    for row in evaluation['predictions']:
        index = lookup[row['record_id']]
        source = data_uri(1.-images[index]); target = data_uri(masks[index])
        text = ('<tr><td><img alt="Resized unmarked source crop" src="'+source+'"><p>'+escape(row['expected_kind'])+
            '</p><small>'+escape(row['record_id'])+'<br>Source '+escape(row['document_sha256'])+
            ', page '+str(row['page'])+', held-out fold '+str(row['fold_id'])+'</small></td>'+
            '<td><img alt="Resized reviewed target coverage, not an input" src="'+target+'"></td>'+
            '<td><img alt="Out-of-fold CNN mask proposal" src="'+escape(row['predicted_mask_file'], quote=True)+
            '"><p>Predicted class: '+escape(row['predicted_kind'])+'<br>Soft IoU '+number(row['mask_metrics']['soft_iou'])+
            '</p></td><td><img alt="Mean target mask from training groups only" src="'+escape(row['baseline_mask_file'], quote=True)+
            '"><p>Soft IoU '+number(row['mean_mask_baseline_metrics']['soft_iou'])+'</p></td></tr>')
        size += len(text.encode('utf-8'))
        if size > 16_000_000-100:
            raise ValueError('Study vision review gallery exceeds 16 MB output budget')
        body.append(text)
    body.append('</tbody></table></html>' if evaluation['predictions'] else '</html>')
    (root/'index.html').write_text(''.join(body), encoding='utf-8')


def train(dataset_directory, output, *, epochs=30, channels=4, input_size=64,
          cancelled=lambda: False, progress=lambda value: None):
    if (type(epochs) is not int or not 1 <= epochs <= MAX_EPOCHS
            or type(channels) is not int or channels not in (4, 8)
            or type(input_size) is not int or input_size not in (32, 64)
            or not callable(cancelled) or not callable(progress)):
        raise ValueError('Bounded CPU vision settings required: epochs 1–100, channels 4/8, input size 32/64')
    output = Path(output)
    if output.exists():
        raise ValueError('Fresh study vision training output required')
    _check(cancelled)
    dataset, rows, x, masks, x16, raw_pin = read_dataset(dataset_directory, input_size=input_size, cancelled=cancelled)
    classes = sorted({r['kind'] for r in rows})
    if not 2 <= len(classes) <= 16:
        raise ValueError('Two to sixteen source component classes required')
    group_ids = sorted({r['group_id'] for r in rows})
    if len(group_ids) <= baseline.MAX_GROUP_FOLDS:
        folds = [[g] for g in group_ids] if len(group_ids) > 1 else []
        mode = 'assessed_leave_one_group_out' if folds else 'unassessed_single_source_group'
    else:
        folds = [group_ids[i::baseline.MAX_GROUP_FOLDS] for i in range(baseline.MAX_GROUP_FOLDS)]
        mode = 'assessed_grouped_cross_validation'
    fitting_rows = len(rows)+sum(sum(r['group_id'] not in fold for r in rows) for fold in folds)
    core = _network()
    unit_work = core.estimate_work(1, input_size=input_size, channels=channels,
        classes=len(classes), epochs=epochs, batch_size=4)
    final_work = core.estimate_work(len(rows), input_size=input_size, channels=channels,
        classes=len(classes), epochs=epochs, batch_size=4)
    # The all-data fit bounds every individual fold; global class count is a
    # conservative work bound when a held-out class is absent from a fold.
    forward_work = fitting_rows*unit_work['forward_macs']
    mlp_work = (fitting_rows-len(rows))*BASELINE_EPOCHS*baseline.INPUT_SIZE**2*BASELINE_HIDDEN_UNITS
    if (forward_work > MAX_FORWARD_WORK or mlp_work > MAX_BASELINE_WORK
            or final_work['forward_macs'] > core.MAX_FIT_FORWARD_MACS
            or final_work['activation_bytes_upper_bound'] > core.MAX_ACTIVATION_BYTES):
        raise ValueError('Study vision training work budget exceeded; reduce epochs, channels, input size or dataset')
    evaluation = {'status': mode, 'source_groups': len(group_ids), 'folds': [], 'predictions': [],
        'metrics': None, 'mask_metrics': None, 'majority_baseline_metrics': None,
        'mean_mask_baseline_metrics': None, 'image16_baseline_metrics': None,
        'scope': 'Source/building-group cross-validation of already-supplied crops and trace masks; no untouched final-model test.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='study-vision-training-', dir=output.parent) as temporary:
        stage = Path(temporary)/'output'
        stage.mkdir()
        predictions_dir = stage/'predictions'
        predictions_dir.mkdir()
        for index, held_groups in enumerate(folds):
            _check(cancelled)
            fitting_indices = [i for i, row in enumerate(rows) if row['group_id'] not in held_groups]
            held_indices = [i for i, row in enumerate(rows) if row['group_id'] in held_groups]
            fitting, held = [rows[i] for i in fitting_indices], [rows[i] for i in held_indices]
            progress({'progress': .03+.8*index/max(1, len(folds)),
                'message': 'Training source-disjoint vision fold '+str(index+1)+' of '+str(len(folds))})
            model = _make_model(fitting, x[fitting_indices], masks[fitting_indices], dataset, raw_pin,
                epochs, channels, input_size, index, cancelled, lambda value: None)
            probability, predicted_masks = _network().infer(model['network'], x[held_indices])
            guessed = [model['classes'][int(np.argmax(p))] for p in probability]
            truth = [r['kind'] for r in held]
            majority = min(model['classes'], key=lambda k: (-sum(r['kind'] == k for r in fitting), k))
            mean_mask = masks[fitting_indices].mean(axis=0)
            mean_mask_pin = digest(mean_mask.tolist())
            old_model = baseline._make_model(fitting, x16[fitting_indices], BASELINE_EPOCHS,
                BASELINE_HIDDEN_UNITS, index, dataset['id'], cancelled, lambda value: None)
            old_probabilities = baseline._probabilities(old_model, x16[held_indices])
            old_guessed = [old_model['classes'][int(np.argmax(p))] for p in old_probabilities]
            train_sources = set(model['training_sources'])
            eval_sources = {r['source']['document_sha256'] for r in held}
            if (train_sources & eval_sources
                    or set(model['training_buildings']) & {r['building_id'] for r in held}):
                raise ValueError('Vision source/building leakage in evaluation')
            unknown = sorted(set(truth)-set(model['classes']))
            per_masks = [_mask_metrics(masks[i], m) for i, m in zip(held_indices, predicted_masks)]
            baseline_masks = [_mask_metrics(masks[i], mean_mask) for i in held_indices]
            fold = {'id': index, 'held_out_group_ids': held_groups,
                'training_group_ids': sorted(set(group_ids)-set(held_groups)),
                'training_buildings': model['training_buildings'], 'training_sources': model['training_sources'],
                'training_record_ids': model['training_record_ids'],
                'evaluation_record_ids': sorted(r['id'] for r in held),
                'evaluation_buildings': sorted({r['building_id'] for r in held}), 'evaluation_sources': sorted(eval_sources),
                'training_records': len(fitting), 'evaluation_records': len(held), 'training_classes': model['classes'],
                'unknown_held_out_classes': unknown, 'unknown_class_records': sum(t in unknown for t in truth),
                'model_sha256': model['artifact_sha256'], 'normalization_sha256': digest(model['network']['normalization']),
                'parameters_sha256': digest(model['network']['parameters']), 'training': model['training'],
                'mean_mask_baseline_sha256': mean_mask_pin, 'image16_baseline_model_sha256': old_model['artifact_sha256'],
                'image16_baseline_normalization_sha256': digest(old_model['input_normalization']),
                'image16_baseline_parameters_sha256': digest(old_model['parameters']),
                'metrics': baseline._metrics(truth, guessed, classes), 'mask_metrics': _mask_summary(per_masks),
                'majority_baseline_kind': majority,
                'majority_baseline_metrics': baseline._metrics(truth, [majority]*len(held), classes),
                'mean_mask_baseline_metrics': _mask_summary(baseline_masks),
                'image16_baseline_metrics': baseline._metrics(truth, old_guessed, classes)}
            evaluation['folds'].append(fold)
            for record_index, (row, kind, p, predicted_mask, measured, measured_baseline, old_kind) in enumerate(
                    zip(held, guessed, probability, predicted_masks, per_masks, baseline_masks, old_guessed)):
                _check(cancelled)
                stem = str(index).zfill(2)+'-'+str(record_index).zfill(4)
                prediction_file = 'predictions/'+stem+'-predicted.png'
                mean_file = 'predictions/'+stem+'-mean-template.png'
                prediction_pin = _save_mask(stage/prediction_file, predicted_mask)
                baseline_pin = _save_mask(stage/mean_file, mean_mask)
                evaluation['predictions'].append({'record_id': row['id'], 'group_id': row['group_id'], 'fold_id': index,
                    'input_file': row['input_file'], 'input_sha256': row['input_sha256'],
                    'target_mask_file': row['target_mask_file'],
                    'target_mask_sha256': dataset['output_sha256'][row['target_mask_file']],
                    'document_sha256': row['source']['document_sha256'], 'page': row['source']['page'],
                    'expected_kind': row['kind'], 'predicted_kind': kind, 'unknown_held_out_class': row['kind'] in unknown,
                    'probabilities': dict(zip(model['classes'], map(float, p))),
                    'majority_baseline_kind': majority, 'image16_baseline_kind': old_kind,
                    'mask_metrics': measured, 'mean_mask_baseline_metrics': measured_baseline,
                    'mask_prediction_file': prediction_file, 'mask_prediction_sha256': prediction_pin,
                    'predicted_mask_file': prediction_file, 'predicted_mask_sha256': prediction_pin,
                    'baseline_mask_file': mean_file, 'baseline_mask_sha256': baseline_pin})
        predictions = sorted(evaluation['predictions'], key=lambda row: row['record_id'])
        evaluation['predictions'] = predictions
        if predictions:
            truth = [r['expected_kind'] for r in predictions]
            evaluation.update(metrics=baseline._metrics(truth, [r['predicted_kind'] for r in predictions], classes),
                majority_baseline_metrics=baseline._metrics(truth, [r['majority_baseline_kind'] for r in predictions], classes),
                image16_baseline_metrics=baseline._metrics(truth, [r['image16_baseline_kind'] for r in predictions], classes),
                mask_metrics=_mask_summary([r['mask_metrics'] for r in predictions]),
                mean_mask_baseline_metrics=_mask_summary([r['mean_mask_baseline_metrics'] for r in predictions]))
        _check(cancelled)
        progress({'progress': .85, 'message': 'Fitting final research vision checkpoint on eligible crops and masks'})
        model = _make_model(rows, x, masks, dataset, raw_pin, epochs, channels, input_size, 0, cancelled,
            lambda value: progress({'progress': .9, 'message': 'Fitting final vision checkpoint', **value}))
        validate_model(model)
        save_model(model, stage/'model.json')
        report = {'version': VERSION, 'status': 'exploratory_component_vision_trained',
            'dataset_id': dataset['id'], 'dataset_file_sha256': raw_pin, 'dataset_kind': dataset['dataset_kind'],
            'records': len(rows), 'classes': classes, 'class_counts': {k: sum(r['kind'] == k for r in rows) for k in classes},
            'input_size': input_size, 'channels': channels, 'epochs': epochs,
            'cross_source_evaluation': evaluation, 'model_file': 'model.json', 'model_sha256': model['artifact_sha256'],
            'model_weights_updated': True, 'production_eligible': False, 'training_labels_generated': 0,
            'geometry_generated': False, 'mask_predictions_generated': True, 'park_world_blocks_added': 0,
            'physical_acceptance': False, 'prediction_scope': SCOPE,
            'mask_metric_semantics': {'soft': 'Fuzzy coverage: intersection sum(min(target,prediction)); union sum(max(target,prediction)); Dice uses twice intersection over both masses.',
                'target_resize': 'BOX average coverage; fractional nonzero target pixels are retained, not thresholded before training.',
                'binary_threshold': MASK_THRESHOLD, 'binary_comparison': 'Both arrays >= threshold; nonempty fractional-only targets have unassessed binary IoU/Dice.',
                'support_comparison': 'Prediction >= threshold versus any target coverage >0; retains thin-line support separately.',
                'saved_prediction_png': 'Rounded probability*255, never a source or target overlay; metrics use unrounded probabilities.'},
            'baseline_comparison': {'image16_epochs': BASELINE_EPOCHS, 'image16_hidden_units': BASELINE_HIDDEN_UNITS,
                'image16_input_size': baseline.INPUT_SIZE, 'same_source_group_folds': True,
                'mask_template': 'Class-agnostic mean of training-only target masks, independent of held-out labels and masks.'},
            'limits': {'max_epochs': MAX_EPOCHS, 'max_forward_work': MAX_FORWARD_WORK,
                'max_baseline_work': MAX_BASELINE_WORK,
                'max_per_fit_forward_work': core.MAX_FIT_FORWARD_MACS,
                'max_activation_bytes': core.MAX_ACTIVATION_BYTES,
                'estimated_forward_work': forward_work, 'estimated_baseline_work': mlp_work,
                'estimated_forward_backward_work': 3*forward_work,
                'all_data_fit_work_estimate': final_work,
                'max_source_group_folds': baseline.MAX_GROUP_FOLDS},
            'final_checkpoint_fit': 'all eligible records; no untouched final-model test', 'limitations': model['limitations']}
        _write_gallery(stage, report, rows, x, masks)
        report['output_sha256'] = {p.relative_to(stage).as_posix(): baseline._sha(p.read_bytes())
            for p in sorted(stage.rglob('*')) if p.is_file()}
        atomic_json(stage/'report.json', report)
        # No model is published from a changing dataset. This reopens every pinned
        # asset and independently revalidates source and target pixel contracts.
        _, current_rows, _, _, _, current_pin = read_dataset(dataset_directory, input_size=input_size, cancelled=cancelled)
        if current_pin != raw_pin or [r['id'] for r in current_rows] != [r['id'] for r in rows]:
            raise ValueError('Study dataset changed during vision training')
        _check(cancelled)
        if output.exists():
            raise ValueError('Fresh study vision training output required')
        stage.rename(output)
    progress({'progress': 1., 'message': 'Research vision checkpoint and held-out mask proposals ready'})
    return report
