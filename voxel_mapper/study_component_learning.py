"""CPU research classifier for already-proposed source crops, never world geometry."""
from concurrent.futures import CancelledError
from io import BytesIO
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile

import numpy as np
from PIL import Image

from .building_spec import digest
from .generation_cycles import atomic_json

VERSION = 'study-component-image-classifier-v1'
DATASET_VERSION = 'retained-study-dataset-v1'
INPUT_SIZE = 16
MAX_RECORDS = 2048
MAX_GROUP_FOLDS = 16
MAX_MANIFEST_BYTES = 16_000_000
MAX_ASSET_BYTES = 64_000_000
MAX_TOTAL_ASSET_BYTES = 512_000_000
MAX_IMAGE_BYTES = 1_000_000
MAX_DECODED_PIXELS = 64_000_000
MAX_TRAINING_WORK = 1_000_000_000
SCOPE = 'Component type for an already-proposed source crop; not object discovery or geometry generation.'


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _check(cancelled):
    if cancelled():
        raise CancelledError('Study component learning cancelled')


def _json(path, limit):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Bounded existing JSON input required')
    raw = path.read_bytes()
    def invalid(value):
        raise ValueError('Nonfinite JSON input: '+value)
    try:
        return json.loads(raw.decode('utf-8'), parse_constant=invalid), raw
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError('UTF-8 JSON input required') from error


def _identifier(value, name, limit=256):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('Bounded '+name+' required')
    return value


def _hash(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _asset(root, name):
    if not isinstance(name, str) or '\\' in name or ':' in name:
        raise ValueError('Safe relative dataset asset path required')
    relative = PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        raise ValueError('Safe relative dataset asset path required')
    path = (root/Path(*relative.parts)).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Dataset asset escapes its root')
    return path


def _groups(records):
    """Connected components of shared building identities or original PDF hashes."""
    parent = list(range(len(records)))
    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index
    owners = {}
    for index, row in enumerate(records):
        for key in (('building', row['building_id']), ('source', row['source']['document_sha256'])):
            if key in owners:
                a, b = find(index), find(owners[key])
                parent[max(a, b)] = min(a, b)
            else:
                owners[key] = index
    components = {}
    for index, row in enumerate(records):
        components.setdefault(find(index), []).append(row)
    groups = []
    for rows in components.values():
        identity = {'building_ids': sorted({r['building_id'] for r in rows}),
            'source_sha256': sorted({r['source']['document_sha256'] for r in rows})}
        groups.append({'group_id': digest(identity), **identity,
            'record_ids': sorted(r['id'] for r in rows)})
    return sorted(groups, key=lambda row: row['group_id'])


def _image(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError('Bounded PNG source crop required')
    try:
        with Image.open(BytesIO(raw)) as image:
            width, height = image.size
            if (image.format != 'PNG' or not 1 <= width <= 256 or not 1 <= height <= 256
                    or getattr(image, 'n_frames', 1) != 1):
                raise ValueError('Single-frame PNG source crop at most 256 by 256 required')
            if image.mode in ('RGBA', 'LA') or 'transparency' in image.info:
                rgba = image.convert('RGBA')
                background = Image.new('RGBA', image.size, 'white')
                background.alpha_composite(rgba)
                image = background.convert('L')
            else:
                image = image.convert('L')
            # Inputs are grayscale ink only; source IDs, geometry and target masks
            # never enter the feature vector. Resize keeps the supplied crop frame.
            small = image.resize((INPUT_SIZE, INPUT_SIZE), Image.Resampling.LANCZOS)
            values = 1.-np.asarray(small, dtype=np.float64).reshape(-1)/255.
            return values, width*height
    except (OSError, Image.DecompressionBombError) as error:
        raise ValueError('Valid bounded PNG source crop required') from error


def read_dataset(directory, *, cancelled=lambda: False, allow_reserved_evaluation=False):
    root = Path(directory).expanduser().resolve()
    manifest, raw = _json(root/'dataset.json', MAX_MANIFEST_BYTES)
    if (not isinstance(manifest, dict) or manifest.get('version') != DATASET_VERSION
            or manifest.get('id') != digest({k: v for k, v in manifest.items() if k != 'id'})):
        raise ValueError('Exact current retained-study dataset manifest required')
    reservation = manifest.get('site_reservation')
    if reservation is not None and not isinstance(reservation, dict):
        raise ValueError('Site reservation must be an explicit object')
    if reservation and reservation.get('evaluation_record_ids') and not allow_reserved_evaluation:
        raise ValueError('Reserved evaluation sites require the site-isolated trainer; all-data training is blocked')
    records = manifest.get('records')
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_RECORDS:
        raise ValueError('One to 2048 bounded study records required')
    ids = set()
    for row in records:
        if not isinstance(row, dict):
            raise ValueError('Study record object required')
        if ('record_sha256' in row and row['record_sha256']
                != digest({k: v for k, v in row.items() if k != 'record_sha256'})):
            raise ValueError('Study record proof changed')
        identifier = _identifier(row.get('id'), 'record identity')
        if identifier in ids:
            raise ValueError('Unique study record identities required')
        ids.add(identifier)
        _identifier(row.get('building_id'), 'building identity')
        _identifier(row.get('kind'), 'component kind', 80)
        source = row.get('source')
        if (not isinstance(source, dict) or not _hash(source.get('document_sha256'))
                or type(source.get('page')) is not int or source['page'] < 1
                or type(row.get('learning_eligible')) is not bool):
            raise ValueError('Pinned source page and explicit learning eligibility required')
    groups = _groups(records)
    supplied = manifest.get('groups')
    if not isinstance(supplied, list) or len(supplied) != len(groups):
        raise ValueError('Recomputed source-connected group inventory required')
    by_group = {g['group_id']: g for g in groups}
    normalized = []
    for group in supplied:
        if not isinstance(group, dict):
            raise ValueError('Source-connected group record required')
        normalized.append({k: group.get(k) for k in ('group_id', 'building_ids', 'source_sha256', 'record_ids')})
    if sorted(normalized, key=lambda row: str(row.get('group_id'))) != groups:
        raise ValueError('Source group labels changed or shared-source/building leakage')
    for row in records:
        group = by_group.get(row.get('group_id'))
        if not group or row['id'] not in group['record_ids']:
            raise ValueError('Record source group changed or shared-source/building leakage')
    files = manifest.get('output_sha256')
    if not isinstance(files, dict) or not 1 <= len(files) <= 16384:
        raise ValueError('Bounded dataset output hash manifest required')
    asset_bytes = 0
    for name, pin in files.items():
        _check(cancelled)
        if not _hash(pin):
            raise ValueError('Dataset asset checksum required')
        path = _asset(root, name)
        if not path.is_file() or path.stat().st_size > MAX_ASSET_BYTES:
            raise ValueError('Bounded existing dataset asset required')
        asset_bytes += path.stat().st_size
        if asset_bytes > MAX_TOTAL_ASSET_BYTES:
            raise ValueError('Dataset asset byte budget exceeded')
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != pin:
            raise ValueError('Dataset asset changed: '+name)
    rows, pixels, values = [], 0, []
    dataset_kind = _identifier(manifest.get('dataset_kind'), 'dataset kind')
    for row in sorted(records, key=lambda value: value['id']):
        _check(cancelled)
        if not row['learning_eligible']:
            continue
        level = row.get('evidence_level')
        if (level not in ('reviewed_source_trace', 'source_extracted_profile')
                and not (dataset_kind.startswith('synthetic') and isinstance(level, str) and level.startswith('synthetic'))):
            raise ValueError('Source-reviewed component evidence required; display hypotheses cannot train')
        name, pin = row.get('input_file'), row.get('input_sha256')
        if not _hash(pin) or files.get(name) != pin:
            raise ValueError('Exact pinned source crop input required')
        path = _asset(root, name)
        if path.stat().st_size > MAX_IMAGE_BYTES:
            raise ValueError('Bounded PNG source crop required')
        image_raw = path.read_bytes()
        if _sha(image_raw) != pin:
            raise ValueError('Source crop changed during reading')
        vector, count = _image(image_raw)
        pixels += count
        if pixels > MAX_DECODED_PIXELS:
            raise ValueError('Decoded source image pixel budget exceeded')
        rows.append(row)
        values.append(vector)
    if not rows:
        raise ValueError('No source-reviewed learning-eligible crops in dataset')
    return manifest, rows, np.asarray(values, dtype=np.float64), _sha(raw)


def _softmax(logits):
    shifted = logits-np.max(logits, axis=1, keepdims=True)
    values = np.exp(shifted)
    return values/values.sum(axis=1, keepdims=True)


def _fit(x, y, classes, epochs, hidden, seed, cancelled, progress):
    mean, scale = x.mean(axis=0), np.maximum(x.std(axis=0), .1)
    z = (x-mean)/scale
    random = np.random.default_rng(seed)
    w1 = random.normal(0, 1/np.sqrt(x.shape[1]), (x.shape[1], hidden))
    b1 = np.zeros(hidden)
    w2 = random.normal(0, 1/np.sqrt(hidden), (hidden, len(classes)))
    b2 = np.zeros(len(classes))
    truth = np.asarray([classes.index(value) for value in y])
    counts = np.bincount(truth, minlength=len(classes))
    weights = len(y)/(len(classes)*counts[truth])
    target = np.eye(len(classes))[truth]
    parameters = [w1, b1, w2, b2]
    first = [np.zeros_like(p) for p in parameters]
    second = [np.zeros_like(p) for p in parameters]
    def forward():
        h = np.tanh(z@w1+b1)
        probabilities = _softmax(h@w2+b2)
        loss = -float(np.mean(weights*np.log(np.maximum(probabilities[np.arange(len(y)), truth], 1e-12))))
        return h, probabilities, loss
    initial = forward()[2]
    for epoch in range(epochs):
        _check(cancelled)
        h, probabilities, loss = forward()
        delta = (probabilities-target)*weights[:, None]/len(y)
        hidden_delta = (delta@w2.T)*(1-h*h)
        gradients = [z.T@hidden_delta+1e-5*w1, hidden_delta.sum(axis=0),
            h.T@delta+1e-5*w2, delta.sum(axis=0)]
        for index, gradient in enumerate(gradients):
            first[index] = .9*first[index]+.1*gradient
            second[index] = .999*second[index]+.001*gradient*gradient
            parameters[index] -= .01*(first[index]/(1-.9**(epoch+1)))/(np.sqrt(second[index]/(1-.999**(epoch+1)))+1e-8)
            np.clip(parameters[index], -100, 100, out=parameters[index])
        if epoch == epochs-1 or epoch % 25 == 0:
            progress({'epoch': epoch+1, 'epochs': epochs, 'loss': loss})
    return {'mean': mean.tolist(), 'scale': scale.tolist()}, {
        'hidden_weights': w1.tolist(), 'hidden_bias': b1.tolist(),
        'output_weights': w2.tolist(), 'output_bias': b2.tolist()}, {
        'initial_loss': initial, 'final_loss': forward()[2]}


def _seal(model):
    model['artifact_sha256'] = digest({k: v for k, v in model.items() if k != 'artifact_sha256'})
    return model


def _make_model(rows, x, epochs, hidden, seed, dataset_id, cancelled, progress):
    classes = sorted({row['kind'] for row in rows})
    norm, parameters, losses = _fit(x, [r['kind'] for r in rows], classes, epochs, hidden, seed, cancelled, progress)
    return _seal({'version': VERSION, 'architecture': {'input_units': INPUT_SIZE**2,
        'input_width': INPUT_SIZE, 'input_height': INPUT_SIZE, 'hidden_units': hidden,
        'output_units': len(classes), 'hidden_activation': 'tanh', 'output_activation': 'softmax'},
        'classes': classes, 'input_normalization': norm, 'parameters': parameters,
        'training': {'epochs': epochs, 'records': len(rows), 'seed': seed,
            'class_balanced': True, 'optimizer': 'Adam', **losses},
        'dataset_id': dataset_id, 'training_buildings': sorted({r['building_id'] for r in rows}),
        'training_sources': sorted({r['source']['document_sha256'] for r in rows}),
        'training_record_ids': sorted(r['id'] for r in rows),
        'training_input_sha256': digest([[r['id'], r['input_sha256']] for r in rows]),
        'production_eligible': False, 'prediction_scope': SCOPE,
        'geometry_generated': False, 'physical_acceptance': False,
        'limitations': ['Research model from previously inspected source studies; no production promotion.',
            'Classifies an already-proposed crop; cannot discover objects, extract geometry or place park blocks.',
            'Study-derived labels and assumptions are dataset declarations, not authenticated physical ground truth.']})


def validate_model(model):
    if (not isinstance(model, dict) or model.get('version') != VERSION
            or model.get('artifact_sha256') != digest({k: v for k, v in model.items() if k != 'artifact_sha256'})
            or model.get('production_eligible') is not False or model.get('geometry_generated') is not False
            or model.get('physical_acceptance') is not False or model.get('prediction_scope') != SCOPE):
        raise ValueError('Exact research-only component image checkpoint required')
    a, classes = model.get('architecture'), model.get('classes')
    if (not isinstance(a, dict) or a.get('input_units') != INPUT_SIZE**2
            or a.get('input_width') != INPUT_SIZE or a.get('input_height') != INPUT_SIZE
            or type(a.get('hidden_units')) is not int or not 1 <= a['hidden_units'] <= 32
            or not isinstance(classes, list) or not 1 <= len(classes) <= 16
            or any(not isinstance(c, str) or not c or len(c) > 80 for c in classes)
            or classes != sorted(set(classes)) or a.get('output_units') != len(classes)
            or a.get('hidden_activation') != 'tanh' or a.get('output_activation') != 'softmax'):
        raise ValueError('Bounded component image architecture required')
    norm, parameters = model.get('input_normalization'), model.get('parameters')
    if (not isinstance(norm, dict) or set(norm) != {'mean', 'scale'}
            or not isinstance(parameters, dict) or set(parameters)
                != {'hidden_weights', 'hidden_bias', 'output_weights', 'output_bias'}):
        raise ValueError('Exact image normalization and parameter arrays required')
    shapes = {'hidden_weights': (INPUT_SIZE**2, a['hidden_units']), 'hidden_bias': (a['hidden_units'],),
        'output_weights': (a['hidden_units'], len(classes)), 'output_bias': (len(classes),)}
    for name, shape in shapes.items():
        value = parameters[name]
        if not isinstance(value, list) or len(value) != shape[0]:
            raise ValueError('Bounded component image parameter shape required')
        if len(shape) == 2:
            if any(not isinstance(row, list) or len(row) != shape[1] for row in value):
                raise ValueError('Bounded component image parameter shape required')
            values = [v for row in value for v in row]
        else:
            values = value
        if any(type(v) not in (int, float) or not np.isfinite(v) or abs(v) > 100 for v in values):
            raise ValueError('Finite bounded image parameters required')
    for key in ('mean', 'scale'):
        value = norm[key]
        if (not isinstance(value, list) or len(value) != INPUT_SIZE**2
                or any(type(v) not in (int, float) or not np.isfinite(v)
                    or not (0 <= v <= 1 if key == 'mean' else .1 <= v <= 1) for v in value)):
            raise ValueError('Finite bounded image normalization required')
    for key in ('training_sources', 'training_buildings', 'training_record_ids'):
        values = model.get(key)
        if not isinstance(values, list) or not values or len(values) > MAX_RECORDS or values != sorted(set(values)):
            raise ValueError('Bounded unique image model lineage required')
        for value in values:
            _identifier(value, 'model lineage')
        if key == 'training_sources' and any(not _hash(v) for v in values):
            raise ValueError('Pinned image model source lineage required')
    return model


def _probabilities(model, x):
    norm, p = model['input_normalization'], model['parameters']
    z = (x-np.asarray(norm['mean']))/np.asarray(norm['scale'])
    h = np.tanh(z@np.asarray(p['hidden_weights'])+np.asarray(p['hidden_bias']))
    return _softmax(h@np.asarray(p['output_weights'])+np.asarray(p['output_bias']))


def save_model(model, path):
    validate_model(model)
    path = Path(path)
    if path.exists():
        raise ValueError('Fresh image checkpoint file required')
    atomic_json(path, model)


def load_model(path):
    model, _ = _json(path, 2_000_000)
    return validate_model(model)


def predict(model, image):
    validate_model(model)
    if isinstance(image, bytes):
        raw = image
    else:
        path = Path(image)
        if not path.is_file() or path.stat().st_size > MAX_IMAGE_BYTES:
            raise ValueError('Bounded PNG source crop required')
        raw = path.read_bytes()
    values, _ = _image(raw)
    probabilities = _probabilities(model, values[None, :])[0]
    index = int(np.argmax(probabilities))
    return {'kind': model['classes'][index],
        'probabilities': dict(zip(model['classes'], map(float, probabilities))),
        'model_sha256': model['artifact_sha256'], 'input_sha256': _sha(raw),
        'production_eligible': False, 'prediction_scope': SCOPE}


def _metrics(truth, predicted, classes):
    matrix = [[sum(t == a and p == b for t, p in zip(truth, predicted)) for b in classes] for a in classes]
    per_class = {}
    for i, label in enumerate(classes):
        tp = matrix[i][i]
        actual, chosen = sum(matrix[i]), sum(row[i] for row in matrix)
        precision, recall = tp/chosen if chosen else 0., tp/actual if actual else 0.
        per_class[label] = {'support': actual, 'predicted': chosen, 'precision': precision,
            'recall': recall, 'f1': 2*precision*recall/(precision+recall) if precision+recall else 0.}
    assessed = [row['f1'] for row in per_class.values() if row['support'] or row['predicted']]
    return {'records': len(truth), 'accuracy': sum(t == p for t, p in zip(truth, predicted))/len(truth),
        'macro_f1': sum(assessed)/len(assessed) if assessed else None,
        'class_order': classes, 'confusion': matrix, 'per_class': per_class}


def train(dataset_directory, output, *, epochs=150, hidden_units=16,
          cancelled=lambda: False, progress=lambda value: None):
    if (type(epochs) is not int or not 1 <= epochs <= 300
            or type(hidden_units) is not int or not 1 <= hidden_units <= 32
            or not callable(cancelled) or not callable(progress)):
        raise ValueError('Bounded CPU image training settings required')
    output = Path(output)
    if output.exists():
        raise ValueError('Fresh component image training output required')
    _check(cancelled)
    dataset, rows, x, raw_pin = read_dataset(dataset_directory, cancelled=cancelled)
    classes = sorted({r['kind'] for r in rows})
    if not 2 <= len(classes) <= 16:
        raise ValueError('Two to sixteen source component classes required')
    group_ids = sorted({r['group_id'] for r in rows})
    if len(group_ids) <= MAX_GROUP_FOLDS:
        folds = [[group] for group in group_ids] if len(group_ids) > 1 else []
        mode = 'assessed_leave_one_group_out' if folds else 'unassessed_single_source_group'
    else:
        # Deterministic source-disjoint grouped folds; no image or label selects
        # the partition. A whole connected group always remains in one fold.
        folds = [group_ids[index::MAX_GROUP_FOLDS] for index in range(MAX_GROUP_FOLDS)]
        mode = 'assessed_grouped_cross_validation'
    work_rows = len(rows)+sum(sum(r['group_id'] not in fold for r in rows) for fold in folds)
    if work_rows*epochs*INPUT_SIZE**2*hidden_units > MAX_TRAINING_WORK:
        raise ValueError('CPU image training work budget exceeded; reduce epochs or dataset size')
    evaluation = {'status': mode, 'source_groups': len(group_ids), 'folds': [],
        'metrics': None, 'baseline_metrics': None, 'predictions': [],
        'scope': 'Source-group cross-validation of supplied crop types; no untouched test of the final all-data checkpoint.'}
    for index, held_groups in enumerate(folds):
        _check(cancelled)
        train_indices = [i for i, row in enumerate(rows) if row['group_id'] not in held_groups]
        test_indices = [i for i, row in enumerate(rows) if row['group_id'] in held_groups]
        fitting, held = [rows[i] for i in train_indices], [rows[i] for i in test_indices]
        progress({'progress': .05+.8*index/max(1, len(folds)),
            'message': 'Learning source-disjoint crop fold '+str(index+1)+' of '+str(len(folds))})
        model = _make_model(fitting, x[train_indices], epochs, hidden_units, index,
            dataset['id'], cancelled, lambda value: None)
        probabilities = _probabilities(model, x[test_indices])
        predictions = [model['classes'][int(np.argmax(p))] for p in probabilities]
        labels = [r['kind'] for r in held]
        baseline = min(model['classes'], key=lambda k: (-sum(r['kind'] == k for r in fitting), k))
        train_sources = set(model['training_sources'])
        test_sources = {r['source']['document_sha256'] for r in held}
        if train_sources & test_sources or set(model['training_buildings']) & {r['building_id'] for r in held}:
            raise ValueError('Component source/building leakage in evaluation')
        unknown = sorted(set(labels)-set(model['classes']))
        evaluation['folds'].append({'id': index, 'held_out_group_ids': held_groups,
            'training_group_ids': sorted(set(group_ids)-set(held_groups)),
            'training_buildings': model['training_buildings'], 'training_sources': model['training_sources'],
            'evaluation_buildings': sorted({r['building_id'] for r in held}),
            'evaluation_sources': sorted(test_sources), 'training_records': len(fitting),
            'evaluation_records': len(held), 'training_classes': model['classes'],
            'unknown_held_out_classes': unknown, 'unknown_class_records': sum(label in unknown for label in labels),
            'model_sha256': model['artifact_sha256'],
            'normalization_sha256': digest(model['input_normalization']),
            'parameters_sha256': digest(model['parameters']),
            'metrics': _metrics(labels, predictions, classes),
            'baseline_kind': baseline, 'baseline_metrics': _metrics(labels, [baseline]*len(held), classes)})
        for row, guessed, probabilities_row in zip(held, predictions, probabilities):
            evaluation['predictions'].append({'record_id': row['id'], 'group_id': row['group_id'],
                'fold_id': index, 'input_file': row['input_file'], 'input_sha256': row['input_sha256'],
                'document_sha256': row['source']['document_sha256'], 'page': row['source']['page'],
                'expected_kind': row['kind'], 'predicted_kind': guessed, 'baseline_kind': baseline,
                'unknown_held_out_class': row['kind'] in unknown,
                'probabilities': dict(zip(model['classes'], map(float, probabilities_row)))})
    if evaluation['predictions']:
        predictions = sorted(evaluation['predictions'], key=lambda row: row['record_id'])
        evaluation['predictions'] = predictions
        truth = [r['expected_kind'] for r in predictions]
        evaluation['metrics'] = _metrics(truth, [r['predicted_kind'] for r in predictions], classes)
        evaluation['baseline_metrics'] = _metrics(truth, [r['baseline_kind'] for r in predictions], classes)
    _check(cancelled)
    progress({'progress': .9, 'message': 'Fitting research checkpoint on all verified study crops'})
    model = _make_model(rows, x, epochs, hidden_units, 0, dataset['id'], cancelled,
        lambda value: progress({'progress': .9+.09*value['epoch']/epochs, **value}))
    validate_model(model)
    report = {'version': VERSION, 'status': 'exploratory_component_classifier_trained',
        'dataset_id': dataset['id'], 'dataset_file_sha256': raw_pin, 'dataset_kind': dataset['dataset_kind'],
        'records': len(rows), 'classes': classes, 'class_counts': {k: sum(r['kind'] == k for r in rows) for k in classes},
        'cross_source_evaluation': evaluation, 'model_file': 'model.json',
        'model_sha256': model['artifact_sha256'], 'model_weights_updated': True,
        'production_eligible': False, 'training_labels_generated': 0,
        'geometry_generated': False, 'park_world_blocks_added': 0, 'physical_acceptance': False,
        'prediction_scope': SCOPE, 'final_checkpoint_fit': 'all eligible dataset records; no untouched final-model test',
        'limits': {'max_records': MAX_RECORDS, 'max_epochs': 300, 'max_hidden_units': 32,
            'max_source_group_folds': MAX_GROUP_FOLDS, 'max_training_work': MAX_TRAINING_WORK},
        'limitations': model['limitations']}
    _check(cancelled)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='component-image-training-', dir=output.parent) as temporary:
        stage = Path(temporary)/'output'
        stage.mkdir()
        save_model(model, stage/'model.json')
        report['output_sha256'] = {'model.json': _sha((stage/'model.json').read_bytes())}
        atomic_json(stage/'report.json', report)
        # The dataset is an immutable training snapshot, not a live watch folder.
        # Recheck manifest, every pinned asset and crop before publishing weights.
        _, current_rows, _, current_pin = read_dataset(dataset_directory, cancelled=cancelled)
        if current_pin != raw_pin or [r['id'] for r in current_rows] != [r['id'] for r in rows]:
            raise ValueError('Study dataset changed during training')
        progress({'progress': 1., 'message': 'Research component image checkpoint ready; production use withheld'})
        _check(cancelled)
        if output.exists():
            raise ValueError('Fresh component image training output required')
        stage.rename(output)
    return report
