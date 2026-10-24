"""Source-disjoint CPU learning of whole-crop component masks.

The supplied source PNG is the only prediction input. Reviewed masks supervise
training; source identities and geometry roles are retained for audits only.
"""
from concurrent.futures import CancelledError
from html import escape
import json
from pathlib import Path
import shutil
import tempfile

import numpy as np

from . import study_component_learning as baseline
from . import study_vision_learning as vision
from .building_spec import digest
from .generation_cycles import atomic_json

VERSION = 'study-component-context-learning-v1'
SCOPE = vision.SCOPE
MAX_EPOCHS = 100
MAX_FORWARD_WORK = 24_000_000_000
MAX_BASELINE_WORK = 2_000_000_000
MAX_MODEL_BYTES = 8_000_000
MAX_REPORT_BYTES = 24_000_000
MAX_OUTPUT_BYTES = 96_000_000
BASELINE_EPOCHS = 150
BASELINE_HIDDEN_UNITS = 16
MASK_THRESHOLD = vision.MASK_THRESHOLD

# Keep the strict, independently re-opened PNG and manifest contracts shared.
read_dataset = vision.read_dataset
_mask_metrics = vision._mask_metrics
_mask_summary = vision._mask_summary
_save_mask = vision._save_mask


def _check(cancelled):
    if cancelled():
        raise CancelledError('Study context learning cancelled')


def _network():
    from . import study_context_network
    return study_context_network


def _seal(model):
    model['artifact_sha256'] = digest({k: v for k, v in model.items() if k != 'artifact_sha256'})
    return model


def validate_model(model):
    if (not isinstance(model, dict) or model.get('version') != VERSION
            or model.get('artifact_sha256') != digest({k: v for k, v in model.items() if k != 'artifact_sha256'})
            or model.get('prediction_scope') != SCOPE
            or model.get('production_eligible') is not False
            or model.get('automatic_promotion') is not False
            or model.get('geometry_generated') is not False
            or model.get('physical_acceptance') is not False
            or model.get('mask_predictions_generated') is not True
            or model.get('park_world_blocks_added') != 0):
        raise ValueError('Exact research-only component context checkpoint required')
    network = _network().validate(model.get('network'))
    if (model.get('input_size') != network['architecture']['input_size']
            or model.get('classes') != network['classes']
            or model.get('training') != network['training']):
        raise ValueError('Context checkpoint network/class schema changed')
    for key in ('dataset_id', 'dataset_file_sha256', 'training_input_sha256',
                'training_target_mask_sha256', 'training_mask_prior_sha256'):
        if not baseline._hash(model.get(key)):
            raise ValueError('Pinned context training dataset and mask lineage required')
    if model['training_mask_prior_sha256'] != digest(network['mask_prior']):
        raise ValueError('Context mask prior lineage changed')
    for key in ('training_sources', 'training_buildings', 'training_record_ids', 'training_group_ids'):
        values = model.get(key)
        if (not isinstance(values, list) or not 1 <= len(values) <= baseline.MAX_RECORDS
                or any(not isinstance(v, str) or not v or len(v) > 256 for v in values)
                or values != sorted(set(values))):
            raise ValueError('Bounded unique context model lineage required')
        if key in ('training_sources', 'training_group_ids') and any(not baseline._hash(v) for v in values):
            raise ValueError('Pinned source/group context lineage required')
    if network['training']['records'] != len(model['training_record_ids']):
        raise ValueError('Context training record count changed')
    return model


def save_model(model, path):
    validate_model(model)
    path = Path(path)
    if path.exists():
        raise ValueError('Fresh context checkpoint file required')
    if len(json.dumps(model, indent=2, sort_keys=True, allow_nan=False).encode('utf-8')) > MAX_MODEL_BYTES:
        raise ValueError('Context checkpoint exceeds bounded JSON size')
    atomic_json(path, model)


def load_model(path):
    model, _ = baseline._json(path, MAX_MODEL_BYTES)
    return validate_model(model)


def predict(model, image):
    validate_model(model)
    if isinstance(image, bytes):
        raw = image
    else:
        path = Path(image)
        if not path.is_file() or path.stat().st_size > baseline.MAX_IMAGE_BYTES:
            raise ValueError('Bounded PNG source crop required')
        raw = path.read_bytes()
    pixels, _ = vision._source_image(raw, model['input_size'])
    probabilities, masks = _network().infer(model['network'], pixels[None])
    p, mask = probabilities[0], masks[0]
    if mask.shape != (model['input_size'], model['input_size']):
        raise ValueError('Context output mask grid changed')
    return {'kind': model['classes'][int(np.argmax(p))],
        'probabilities': dict(zip(model['classes'], map(float, p))),
        'mask_probabilities': mask.tolist(), 'mask_size': [model['input_size']]*2,
        'mask_threshold': MASK_THRESHOLD, 'model_sha256': model['artifact_sha256'],
        'input_sha256': baseline._sha(raw), 'prediction_scope': SCOPE,
        'production_eligible': False, 'automatic_promotion': False,
        'geometry_generated': False, 'mask_predictions_generated': True,
        'physical_acceptance': False, 'park_world_blocks_added': 0}


# Convenient aliases for callers that treat the checkpoint as an open artifact.
load = load_model
save = save_model


def _make_model(rows, images, masks, dataset, raw_pin, epochs, channels, input_size,
                seed, cancelled, progress):
    network = _network().fit(images, masks, [r['kind'] for r in rows], epochs=epochs,
        channels=channels, seed=seed, batch_size=4, cancelled=cancelled, progress=progress)
    return _seal({'version': VERSION, 'network': network, 'input_size': input_size,
        'classes': network['classes'], 'training': network['training'],
        'dataset_id': dataset['id'], 'dataset_file_sha256': raw_pin,
        'training_buildings': sorted({r['building_id'] for r in rows}),
        'training_sources': sorted({r['source']['document_sha256'] for r in rows}),
        'training_record_ids': sorted(r['id'] for r in rows),
        'training_group_ids': sorted({r['group_id'] for r in rows}),
        'training_input_sha256': digest([[r['id'], r['input_sha256']] for r in rows]),
        'training_target_mask_sha256': digest([[r['id'], dataset['output_sha256'][r['target_mask_file']]] for r in rows]),
        'training_mask_prior_sha256': digest(network['mask_prior']),
        'production_eligible': False, 'automatic_promotion': False,
        'prediction_scope': SCOPE, 'geometry_generated': False,
        'mask_predictions_generated': True, 'physical_acceptance': False,
        'park_world_blocks_added': 0,
        'limitations': [
            'Research training on previously inspected, supplied source crops and reviewed trace masks.',
            'The crop frame is supplied; full-page discovery and independent crop localization are unassessed.',
            'Predicted masks are proposals, not accepted outlines, metric geometry, complete buildings or world blocks.',
            'Study label provenance is retained; it is not authenticated physical ground truth.',
            'The final checkpoint fits all eligible records; evaluation uses separate source/building-disjoint fold models.',
            'No quality result automatically promotes this model or accepts physical geometry.']})


def _folds(rows):
    groups = sorted({r['group_id'] for r in rows})
    if len(groups) <= baseline.MAX_GROUP_FOLDS:
        folds = [[group] for group in groups] if len(groups) > 1 else []
        mode = 'assessed_leave_one_group_out' if folds else 'unassessed_single_source_group'
    else:
        folds = [groups[i::baseline.MAX_GROUP_FOLDS] for i in range(baseline.MAX_GROUP_FOLDS)]
        mode = 'assessed_grouped_cross_validation'
    return groups, folds, mode


def _summarize(predictions, classes):
    if not predictions:
        return {'metrics': None, 'mask_metrics': None, 'majority_baseline_metrics': None,
            'mean_mask_baseline_metrics': None, 'image16_baseline_metrics': None}
    truth = [r['expected_kind'] for r in predictions]
    return {'metrics': baseline._metrics(truth, [r['predicted_kind'] for r in predictions], classes),
        'majority_baseline_metrics': baseline._metrics(truth, [r['majority_baseline_kind'] for r in predictions], classes),
        'image16_baseline_metrics': baseline._metrics(truth, [r['image16_baseline_kind'] for r in predictions], classes),
        'mask_metrics': _mask_summary([r['mask_metrics'] for r in predictions]),
        'mean_mask_baseline_metrics': _mask_summary([r['mean_mask_baseline_metrics'] for r in predictions])}


def _stratified(predictions, key):
    return {value: {'mask_metrics': _mask_summary([r['mask_metrics'] for r in predictions if r[key] == value]),
        'mean_mask_baseline_metrics': _mask_summary([r['mean_mask_baseline_metrics'] for r in predictions if r[key] == value])}
        for value in sorted({r[key] for r in predictions})}


def _audit_metadata(rows):
    result = {}
    for row in rows:
        geometry = row.get('target_geometry')
        role = row.get('target_role', 'unspecified')
        kind = geometry.get('type', 'unspecified') if isinstance(geometry, dict) else 'unspecified'
        if any(not isinstance(value, str) or not 1 <= len(value) <= 256 for value in (role, kind)):
            raise ValueError('Bounded geometry role/type audit metadata required')
        result[row['id']] = (role, kind)
    return result


def _balanced_evaluation(predictions, classes):
    """Give each held-out source/building group one vote, regardless of size."""
    groups = []
    for group_id in sorted({row['group_id'] for row in predictions}):
        chosen = [row for row in predictions if row['group_id'] == group_id]
        groups.append({'group_id': group_id, 'records': len(chosen),
            'record_ids': sorted(row['record_id'] for row in chosen),
            **_summarize(chosen, classes)})
    result = {'status': 'assessed_equal_source_group_weight' if groups else 'unassessed_no_held_out_predictions',
        'source_groups': len(groups), 'records': len(predictions), 'groups': groups,
        'weighting': 'Arithmetic mean of within-group metrics: each source/building-connected group has equal weight. No oracle selection or model selection.',
        'binary_semantics': 'Within-group binary means omit fractional-only thin targets; equal-group binary means omit groups with no assessed binary targets.',
        'comparison_tolerance': 1e-12}
    for key in ('metrics', 'majority_baseline_metrics', 'image16_baseline_metrics'):
        result[key] = {'accuracy': float(np.mean([group[key]['accuracy'] for group in groups])) if groups else None}
    for key in ('mask_metrics', 'mean_mask_baseline_metrics'):
        summary, assessed = {}, {}
        for metric in ('soft_iou', 'soft_dice', 'binary_iou', 'binary_dice', 'support_iou', 'support_dice'):
            values = [group[key]['mean_'+metric] for group in groups if group[key]['mean_'+metric] is not None]
            summary['mean_'+metric] = float(np.mean(values)) if values else None
            assessed[metric] = len(values)
        result[key] = {**summary, 'assessed_groups': assessed}
    for metric in ('soft_iou', 'binary_iou'):
        differences = [group['mask_metrics']['mean_'+metric]-group['mean_mask_baseline_metrics']['mean_'+metric]
            for group in groups if group['mask_metrics']['mean_'+metric] is not None
            and group['mean_mask_baseline_metrics']['mean_'+metric] is not None]
        result['groups_beating_template_'+metric] = sum(value > 1e-12 for value in differences)
        result['groups_below_template_'+metric] = sum(value < -1e-12 for value in differences)
        result['groups_tied_template_'+metric] = sum(abs(value) <= 1e-12 for value in differences)
        result['groups_with_assessed_'+metric+'_comparison'] = len(differences)
    return result


def _balanced_warnings(balanced):
    warnings = []
    for metric, label in (('soft_iou', 'soft'), ('binary_iou', 'binary')):
        measured = balanced['mask_metrics']['mean_'+metric]
        template = balanced['mean_mask_baseline_metrics']['mean_'+metric]
        if measured is not None and template is not None and measured < template:
            warnings.append('Equal-group '+label+' mask IoU is below the training-only mean template. Larger source groups can make the record-averaged result look better; improvement across source groups is not established for this metric.')
    return warnings


def _warnings(evaluation):
    if not evaluation['predictions']:
        return ['Held-out quality is unassessed: at least two independent source/building groups are needed.']
    warnings = []
    accuracy = evaluation['metrics']['accuracy']
    for name, title in (('majority_baseline_metrics', 'training-only majority classifier'),
                        ('image16_baseline_metrics', 'fixed 16px image classifier')):
        if accuracy <= evaluation[name]['accuracy']:
            warnings.append('Context class accuracy does not exceed the '+title+' on these held-out crops.')
    if evaluation['mask_metrics']['mean_soft_iou'] <= evaluation['mean_mask_baseline_metrics']['mean_soft_iou']:
        warnings.append('Context soft mask IoU does not exceed the training-only mean template on these held-out crops.')
    if any(r['unknown_held_out_class'] for r in evaluation['predictions']):
        warnings.append('Some held-out component classes never occur in the corresponding training fold; those cases remain included in all reported scores.')
    return warnings


def _write_gallery(root, report, rows, images, masks):
    # Reuse the bounded, escaped, offline PNG gallery. Replace its fixed labels,
    # leaving its source/target separation and bad-result warning intact.
    vision._write_gallery(root, report, rows, images, masks)
    path = root/'index.html'
    html = path.read_text(encoding='utf-8')
    for old, new in (
        ('Held-out component vision review', 'Held-out whole-crop context review'),
        ('<p>CNN class accuracy:', '<p>Context class accuracy:'),
        ('. CNN mean soft mask IoU:', '. Context mean soft mask IoU:'),
        ('<strong>The CNN scored below', '<strong>The context model scored below'),
        ('<th>CNN mask proposal</th>', '<th>Context mask proposal</th>'),
        ('alt="Out-of-fold CNN mask proposal"', 'alt="Out-of-fold context mask proposal"')):
        html = html.replace(old, new)
    balanced = report.get('group_balanced_evaluation')
    if balanced is not None:
        def percentage(value):
            return 'unassessed' if value is None else f'{100*value:.1f}%'
        paragraph = ('<p><strong>Equal-group evaluation ('+str(balanced['source_groups'])+' source groups):</strong> '
            'class accuracy '+percentage(balanced['metrics']['accuracy'])+
            '; soft mask IoU '+percentage(balanced['mask_metrics']['mean_soft_iou'])+
            '; training-only template '+percentage(balanced['mean_mask_baseline_metrics']['mean_soft_iou'])+
            '; binary mask IoU '+percentage(balanced['mask_metrics']['mean_binary_iou'])+
            '; training-only template binary IoU '+percentage(balanced['mean_mask_baseline_metrics']['mean_binary_iou'])+
            '. Each source group has equal weight; no oracle or model selection.</p>')
        paragraph += ''.join('<p class="notice"><strong>'+escape(warning)+'</strong></p>'
            for warning in _balanced_warnings(balanced))
        html = html.replace('<p>Context class accuracy:', paragraph+'<p>Context class accuracy:', 1)
    notices = ''.join('<p class="notice"><strong>'+escape(warning)+'</strong></p>' for warning in report['quality_warnings'])
    table = ['<table><caption>Mask quality by reviewed geometry role (audit metadata, never image inputs).</caption>',
        '<tr><th>Geometry role</th><th>Records</th><th>Context soft IoU</th><th>Training-only template soft IoU</th></tr>']
    for role, metrics in report['cross_source_evaluation']['per_geometry_role_mask_metrics'].items():
        measured, prior = metrics['mask_metrics'], metrics['mean_mask_baseline_metrics']
        table.append('<tr><td>'+escape(role)+'</td><td>'+str(measured['records'])+'</td><td>'
            +f"{measured['mean_soft_iou']:.4f}"+'</td><td>'+f"{prior['mean_soft_iou']:.4f}"+'</td></tr>')
    html = html.replace('</html>', notices+''.join(table)+'</table></html>')
    if len(html.encode('utf-8')) > 16_000_000:
        raise ValueError('Context review gallery exceeds 16 MB output budget')
    path.write_text(html, encoding='utf-8')


def _progress(progress, start, extent, message):
    def update(value):
        event = dict(value)
        fraction = event.get('epoch', 0)/max(1, event.get('epochs', 1))
        event.update(progress=start+extent*min(1., max(0., fraction)), message=message)
        progress(event)
    return update


def _work_plan(rows, folds, *, input_size, channels, epochs, classes):
    core = _network()
    fitting_counts = [sum(row['group_id'] not in fold for row in rows) for fold in folds]+[len(rows)]
    work = [core.estimate_work(count, input_size=input_size, channels=channels,
        classes=classes, epochs=epochs, batch_size=4) for count in fitting_counts]
    forward = sum(item['forward_macs'] for item in work)
    old_work = sum(fitting_counts[:-1])*BASELINE_EPOCHS*baseline.INPUT_SIZE**2*BASELINE_HIDDEN_UNITS
    if (forward > MAX_FORWARD_WORK or old_work > MAX_BASELINE_WORK
            or any(item['forward_macs'] > core.MAX_FIT_FORWARD_MACS
                   or item['activation_bytes_upper_bound'] > core.MAX_ACTIVATION_BYTES for item in work)):
        raise ValueError('Context training work budget exceeded; reduce epochs, channels, input size or dataset')
    return {'estimated_forward_work': forward, 'estimated_baseline_work': old_work,
        'estimated_forward_backward_work': 3*forward, 'all_data_fit_work_estimate': work[-1],
        'max_forward_work': MAX_FORWARD_WORK, 'max_baseline_work': MAX_BASELINE_WORK,
        'max_per_fit_forward_work': core.MAX_FIT_FORWARD_MACS,
        'max_activation_bytes': core.MAX_ACTIVATION_BYTES, 'max_epochs': MAX_EPOCHS,
        'max_source_group_folds': baseline.MAX_GROUP_FOLDS, 'max_output_bytes': MAX_OUTPUT_BYTES}


def train(dataset_directory, output, *, epochs=40, channels=4, input_size=64,
          cancelled=lambda: False, progress=lambda value: None):
    if (type(epochs) is not int or not 1 <= epochs <= MAX_EPOCHS
            or type(channels) is not int or channels not in (4, 8)
            or type(input_size) is not int or input_size not in (32, 64)
            or not callable(cancelled) or not callable(progress)):
        raise ValueError('Bounded CPU context settings required: epochs 1–100, channels 4/8, input size 32/64')
    output = Path(output)
    if output.exists():
        raise ValueError('Fresh study context training output required')
    _check(cancelled)
    dataset, rows, images, masks, x16, raw_pin = read_dataset(dataset_directory,
        input_size=input_size, cancelled=cancelled)
    classes = sorted({r['kind'] for r in rows})
    if not 2 <= len(classes) <= 16:
        raise ValueError('Two to sixteen source component classes required')
    audit_metadata = _audit_metadata(rows)
    groups, folds, mode = _folds(rows)
    limits = _work_plan(rows, folds, input_size=input_size, channels=channels, epochs=epochs, classes=len(classes))
    evaluation = {'status': mode, 'source_groups': len(groups), 'folds': [], 'predictions': [],
        'per_class_mask_metrics': {}, 'per_geometry_role_mask_metrics': {}, 'unknown_class_cases': [],
        **_summarize([], classes),
        'scope': 'Source/building-group cross-validation of supplied crops and reviewed masks; no untouched final-model test.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output.parent).free < MAX_OUTPUT_BYTES:
        raise ValueError('At least 96 MB free disk space required before context training')
    with tempfile.TemporaryDirectory(prefix='study-context-training-', dir=output.parent) as temporary:
        stage = Path(temporary)/'output'
        (stage/'predictions').mkdir(parents=True)
        for index, held_groups in enumerate(folds):
            _check(cancelled)
            train_indices = [i for i, row in enumerate(rows) if row['group_id'] not in held_groups]
            held_indices = [i for i, row in enumerate(rows) if row['group_id'] in held_groups]
            fitting, held = [rows[i] for i in train_indices], [rows[i] for i in held_indices]
            message = 'Training source-disjoint context fold '+str(index+1)+' of '+str(len(folds))
            start, extent = .03+.78*index/max(1, len(folds)), .78/max(1, len(folds))
            progress({'progress': start, 'message': message, 'fold': index+1, 'folds': len(folds)})
            model = _make_model(fitting, images[train_indices], masks[train_indices], dataset, raw_pin,
                epochs, channels, input_size, index, cancelled, _progress(progress, start, extent*.9, message))
            probability, predicted_masks = _network().infer(model['network'], images[held_indices])
            guessed = [model['classes'][int(np.argmax(p))] for p in probability]
            truth = [r['kind'] for r in held]
            majority = min(model['classes'], key=lambda kind: (-sum(r['kind'] == kind for r in fitting), kind))
            mean_mask = masks[train_indices].mean(axis=0)
            old_model = baseline._make_model(fitting, x16[train_indices], BASELINE_EPOCHS,
                BASELINE_HIDDEN_UNITS, index, dataset['id'], cancelled,
                _progress(progress, start+extent*.9, extent*.1, 'Fitting fixed 16px baseline for fold '+str(index+1)))
            old_probabilities = baseline._probabilities(old_model, x16[held_indices])
            old_guessed = [old_model['classes'][int(np.argmax(p))] for p in old_probabilities]
            eval_sources = {r['source']['document_sha256'] for r in held}
            if (set(model['training_sources']) & eval_sources
                    or set(model['training_buildings']) & {r['building_id'] for r in held}
                    or set(model['training_record_ids']) & {r['id'] for r in held}):
                raise ValueError('Source/building/record leakage in context evaluation')
            unknown = sorted(set(truth)-set(model['classes']))
            per_masks = [_mask_metrics(masks[i], predicted) for i, predicted in zip(held_indices, predicted_masks)]
            baseline_masks = [_mask_metrics(masks[i], mean_mask) for i in held_indices]
            fold = {'id': index, 'held_out_group_ids': held_groups,
                'training_group_ids': model['training_group_ids'],
                'training_buildings': model['training_buildings'], 'training_sources': model['training_sources'],
                'training_record_ids': model['training_record_ids'], 'evaluation_record_ids': sorted(r['id'] for r in held),
                'evaluation_buildings': sorted({r['building_id'] for r in held}), 'evaluation_sources': sorted(eval_sources),
                'training_records': len(fitting), 'evaluation_records': len(held), 'training_classes': model['classes'],
                'unknown_held_out_classes': unknown, 'unknown_class_records': sum(t in unknown for t in truth),
                'model_sha256': model['artifact_sha256'], 'normalization_sha256': digest(model['network']['normalization']),
                'parameters_sha256': digest(model['network']['parameters']),
                'mask_prior_sha256': digest(model['network']['mask_prior']), 'training': model['training'],
                'mean_mask_baseline_sha256': digest(mean_mask.tolist()),
                'image16_baseline_model_sha256': old_model['artifact_sha256'],
                'image16_baseline_normalization_sha256': digest(old_model['input_normalization']),
                'image16_baseline_parameters_sha256': digest(old_model['parameters']),
                'metrics': baseline._metrics(truth, guessed, classes), 'mask_metrics': _mask_summary(per_masks),
                'majority_baseline_kind': majority,
                'majority_baseline_metrics': baseline._metrics(truth, [majority]*len(held), classes),
                'mean_mask_baseline_metrics': _mask_summary(baseline_masks),
                'image16_baseline_metrics': baseline._metrics(truth, old_guessed, classes)}
            evaluation['folds'].append(fold)
            for record_index, (row, kind, p, predicted, measured, prior_metric, old_kind) in enumerate(
                    zip(held, guessed, probability, predicted_masks, per_masks, baseline_masks, old_guessed)):
                _check(cancelled)
                stem = str(index).zfill(2)+'-'+str(record_index).zfill(4)
                prediction_file = 'predictions/'+stem+'-predicted.png'
                mean_file = 'predictions/'+stem+'-mean-template.png'
                prediction_pin = _save_mask(stage/prediction_file, predicted)
                baseline_pin = _save_mask(stage/mean_file, mean_mask)
                role, geometry_type = audit_metadata[row['id']]
                evaluation['predictions'].append({'record_id': row['id'], 'group_id': row['group_id'], 'fold_id': index,
                    'input_file': row['input_file'], 'input_sha256': row['input_sha256'],
                    'target_mask_file': row['target_mask_file'],
                    'target_mask_sha256': dataset['output_sha256'][row['target_mask_file']],
                    'document_sha256': row['source']['document_sha256'], 'page': row['source']['page'],
                    'expected_kind': row['kind'], 'predicted_kind': kind, 'unknown_held_out_class': row['kind'] in unknown,
                    'geometry_role': role, 'geometry_type': geometry_type,
                    'probabilities': dict(zip(model['classes'], map(float, p))),
                    'majority_baseline_kind': majority, 'image16_baseline_kind': old_kind,
                    'mask_metrics': measured, 'mean_mask_baseline_metrics': prior_metric,
                    'mask_prediction_file': prediction_file, 'mask_prediction_sha256': prediction_pin,
                    'predicted_mask_file': prediction_file, 'predicted_mask_sha256': prediction_pin,
                    'baseline_mask_file': mean_file, 'baseline_mask_sha256': baseline_pin})
        predictions = sorted(evaluation['predictions'], key=lambda row: row['record_id'])
        evaluation.update(predictions=predictions, **_summarize(predictions, classes),
            per_class_mask_metrics=_stratified(predictions, 'expected_kind'),
            per_geometry_role_mask_metrics=_stratified(predictions, 'geometry_role'),
            per_geometry_type_mask_metrics=_stratified(predictions, 'geometry_type'),
            unknown_class_cases=[r['record_id'] for r in predictions if r['unknown_held_out_class']])
        evaluation['unknown_class_evaluation'] = _summarize(
            [row for row in predictions if row['unknown_held_out_class']], classes)
        evaluation['known_class_evaluation'] = _summarize(
            [row for row in predictions if not row['unknown_held_out_class']], classes)
        _check(cancelled)
        message = 'Fitting final all-data research context checkpoint'
        progress({'progress': .83, 'message': message})
        model = _make_model(rows, images, masks, dataset, raw_pin, epochs, channels, input_size, 0,
            cancelled, _progress(progress, .83, .13, message))
        save_model(model, stage/'model.json')
        report = {'version': VERSION, 'status': 'exploratory_component_context_trained',
            'dataset_id': dataset['id'], 'dataset_file_sha256': raw_pin, 'dataset_kind': dataset['dataset_kind'],
            'records': len(rows), 'record_ids': sorted(r['id'] for r in rows), 'classes': classes,
            'class_counts': {kind: sum(r['kind'] == kind for r in rows) for kind in classes},
            'input_size': input_size, 'channels': channels, 'epochs': epochs,
            'settings_fixed_before_evaluation': True, 'cross_source_evaluation': evaluation,
            'model_file': 'model.json', 'model_sha256': model['artifact_sha256'],
            'model_weights_updated': True, 'production_eligible': False, 'automatic_promotion': False,
            'training_labels_generated': 0, 'geometry_generated': False, 'mask_predictions_generated': True,
            'park_world_blocks_added': 0, 'physical_acceptance': False, 'prediction_scope': SCOPE,
            'input_features': 'Only grayscale ink pixels in the supplied source crop. No IDs, geometry roles or reviewed target pixels enter prediction.',
            'mask_metric_semantics': {
                'soft': 'Fuzzy coverage: intersection sum(min(target,prediction)); union sum(max(target,prediction)); Dice uses twice intersection over both masses.',
                'target_resize': 'BOX average coverage; fractional nonzero pixels are retained for training and scoring.',
                'binary_threshold': MASK_THRESHOLD, 'binary_comparison': 'Both arrays >= threshold; nonempty fractional-only targets have unassessed binary IoU/Dice.',
                'support_comparison': 'Prediction >= threshold versus any target coverage >0.',
                'saved_prediction_png': 'Rounded probability*255; metrics use unrounded probabilities.'},
            'baseline_comparison': {'image16_epochs': BASELINE_EPOCHS,
                'image16_hidden_units': BASELINE_HIDDEN_UNITS, 'image16_input_size': baseline.INPUT_SIZE,
                'same_source_group_folds': True, 'image16_status': 'reproduced_fixed_baseline_on_exact_current_folds',
                'mask_template': 'Class-agnostic mean of training-only target masks; independent of held-out labels and masks.',
                'prior': 'Training-only downsampled mean mask initializes a trainable whole-crop decoder; no held-out target contributes.'},
            'limits': limits, 'group_balanced_evaluation': _balanced_evaluation(predictions, classes),
            'quality_warnings': _warnings(evaluation),
            'final_checkpoint_fit': 'all eligible records; no untouched final-model test', 'limitations': model['limitations']}
        report['quality_warnings'].extend(_balanced_warnings(report['group_balanced_evaluation']))
        _write_gallery(stage, report, rows, images, masks)
        report['output_sha256'] = {path.relative_to(stage).as_posix(): baseline._sha(path.read_bytes())
            for path in sorted(stage.rglob('*')) if path.is_file()}
        report['artifact_sha256'] = digest(report)
        if len(json.dumps(report, indent=2, sort_keys=True, allow_nan=False).encode('utf-8')) > MAX_REPORT_BYTES:
            raise ValueError('Context report exceeds bounded JSON size')
        atomic_json(stage/'report.json', report)
        if sum(path.stat().st_size for path in stage.rglob('*') if path.is_file()) > MAX_OUTPUT_BYTES:
            raise ValueError('Context training output byte budget exceeded')
        # Reopen and hash every manifest asset and independently decode every
        # source/mask before exposing any result, including non-learning assets.
        _, current_rows, _, _, _, current_pin = read_dataset(dataset_directory,
            input_size=input_size, cancelled=cancelled)
        if current_pin != raw_pin or current_rows != rows:
            raise ValueError('Study dataset changed during context training')
        _check(cancelled)
        if output.exists():
            raise ValueError('Fresh study context training output required')
        stage.rename(output)
    progress({'progress': 1., 'message': 'Research context checkpoint and held-out proposals ready'})
    return report
