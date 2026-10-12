"""Deterministic supervised candidate ranker. Scores never establish evidence."""
import copy
import math
from .building_spec import digest

VERSION = 'building-candidate-ranker-v1'
FEATURES = ('boundary_support', 'view_agreement', 'dimension_agreement',
            'opening_support', 'topology_quality', 'source_coverage')
GATES = ('source_verified', 'identity_verified', 'dimensions_verified', 'topology_verified')
MAX_RECORDS = 100000


def _features(values):
    if not isinstance(values, dict) or set(values) != set(FEATURES):
        raise ValueError('Exact ranker feature schema required')
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in values.values()):
        raise ValueError('Finite normalized feature values required')
    return [values[k] for k in FEATURES]


def _seal(model):
    model['artifact_sha256'] = digest({k: v for k, v in model.items() if k != 'artifact_sha256'})
    return model


def baseline():
    return _seal({'version': VERSION, 'features': list(FEATURES), 'weights': [0.0]*len(FEATURES),
                  'bias': 0.0, 'iteration': 0, 'training_buildings': [], 'training_sources': [],
                  'status': 'untrained_baseline', 'production_eligible': False})


def validate_model(model):
    if model.get('version') != VERSION or model.get('features') != list(FEATURES):
        raise ValueError('Ranker model version/schema mismatch')
    if model.get('artifact_sha256') != digest({k: v for k, v in model.items() if k != 'artifact_sha256'}):
        raise ValueError('Ranker checkpoint changed')
    if len(model.get('weights', [])) != len(FEATURES) or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 100 for v in [*model['weights'], model['bias']]):
        raise ValueError('Bounded finite ranker parameters required')


def score(model, values):
    validate_model(model)
    z = model['bias'] + sum(w*x for w, x in zip(model['weights'], _features(values)))
    return 1/(1+math.exp(-max(-60, min(60, z))))


def rank(candidates, model=None):
    """Rank local candidates only; failed evidence gates can never be selected."""
    model = model or baseline(); validate_model(model)
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 10000:
        raise ValueError('Bounded candidate batch required')
    ids, rows = set(), []
    for candidate in candidates:
        identifier = candidate.get('id')
        if not isinstance(identifier, str) or not identifier or identifier in ids:
            raise ValueError('Unique candidate IDs required')
        ids.add(identifier)
        failures = [gate for gate in GATES if candidate.get('gates', {}).get(gate) is not True]
        rows.append({'id': identifier, 'score': score(model, candidate['features']),
                     'eligible_local_candidate': not failures, 'failed_gates': failures})
    rows.sort(key=lambda r: (-r['score'], r['id']))
    eligible = [r for r in rows if r['eligible_local_candidate']]
    return {'version': VERSION, 'model_sha256': model['artifact_sha256'], 'ranking': rows,
            'selected_id': eligible[0]['id'] if eligible else None,
            'selection_scope': 'local candidate priority only; not physical acceptance or park placement',
            'model_production_eligible': model['production_eligible']}


def _records(records):
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_RECORDS:
        raise ValueError('Bounded reviewed feedback dataset required')
    seen, candidates = set(), set()
    for row in records:
        if not isinstance(row.get('id'), str) or not row['id'] or row['id'] in seen:
            raise ValueError('Duplicate or missing feedback ID')
        seen.add(row['id'])
        if not isinstance(row.get('building_id'), str) or not row['building_id']:
            raise ValueError('Feedback building identity required')
        if row.get('outcome') not in ('accepted', 'rejected') or row.get('review_basis') not in ('independent_review', 'source_verified'):
            raise ValueError('Independently reviewed outcomes required; generated predictions are not labels')
        sources = row.get('source_sha256')
        import re
        if not isinstance(sources, list) or not sources or any(not isinstance(s, str) or not re.fullmatch('[0-9a-f]{64}', s) for s in sources):
            raise ValueError('Feedback source hashes required')
        candidate_hash = row.get('candidate_sha256')
        if not isinstance(candidate_hash, str) or not re.fullmatch('[0-9a-f]{64}', candidate_hash):
            raise ValueError('Pinned reviewed candidate hash required')
        key = (row['building_id'], candidate_hash)
        if key in candidates:
            raise ValueError('Duplicate feedback for the same building candidate')
        candidates.add(key)
        _features(row['features'])
    return records


def _metrics(model, rows):
    scores = [(score(model, r['features']), r['outcome'] == 'accepted') for r in rows]
    predicted = [(p, y) for p, y in scores if p >= .8]
    return {'count': len(rows), 'brier': sum((p-int(y))**2 for p, y in scores)/len(rows),
            'accept_precision': sum(y for p, y in predicted)/len(predicted) if predicted else None,
            'high_confidence_count': len(predicted)}


def train(records, training_buildings, evaluation_buildings, parent=None, epochs=300,
          min_training_records=100, min_evaluation_records=20):
    """Warm-start from prior weights; evaluation buildings/sources never train."""
    records = _records(records); parent = parent or baseline(); validate_model(parent)
    if (not isinstance(training_buildings, list) or not isinstance(evaluation_buildings, list)
            or not training_buildings or not evaluation_buildings
            or any(not isinstance(b, str) or not b for b in training_buildings+evaluation_buildings)
            or len(set(training_buildings)) != len(training_buildings)
            or len(set(evaluation_buildings)) != len(evaluation_buildings)):
        raise ValueError('Explicit unique training and evaluation building splits required')
    train_ids, eval_ids = set(training_buildings), set(evaluation_buildings)
    if train_ids & eval_ids or set(parent['training_buildings']) & eval_ids:
        raise ValueError('Building leakage between training and evaluation')
    if set(r['building_id'] for r in records) != train_ids | eval_ids:
        raise ValueError('Every feedback building must belong to an explicit split')
    training = sorted((r for r in records if r['building_id'] in train_ids), key=lambda r: r['id'])
    evaluation = sorted((r for r in records if r['building_id'] in eval_ids), key=lambda r: r['id'])
    train_sources = {s for r in training for s in r['source_sha256']} | set(parent['training_sources'])
    eval_sources = {s for r in evaluation for s in r['source_sha256']}
    if train_sources & eval_sources:
        raise ValueError('Shared-source leakage between training and evaluation')
    if any({r['outcome'] for r in rows} != {'accepted', 'rejected'} for rows in (training, evaluation)):
        raise ValueError('Both reviewed classes required in each split')
    if type(epochs) is not int or not 1 <= epochs <= 1000 or len(training)*epochs > 10000000:
        raise ValueError('Training work budget exceeded')
    if any(type(n) is not int or n < 1 for n in (min_training_records, min_evaluation_records)):
        raise ValueError('Positive promotion sample limits required')
    model = copy.deepcopy(parent); model.pop('artifact_sha256')
    xs = [_features(r['features']) for r in training]
    ys = [int(r['outcome'] == 'accepted') for r in training]
    for epoch in range(epochs):
        gradients = [0.0]*len(FEATURES); bias_gradient = 0.0
        for x, y in zip(xs, ys):
            z = model['bias'] + sum(w*v for w, v in zip(model['weights'], x))
            error = 1/(1+math.exp(-max(-60, min(60, z))))-y
            bias_gradient += error
            for i, value in enumerate(x): gradients[i] += error*value
        for i in range(len(FEATURES)):
            model['weights'][i] -= .5*(gradients[i]/len(xs)+.001*model['weights'][i])
        model['bias'] -= .5*bias_gradient/len(xs)
    model.update(iteration=parent['iteration']+1, parent_sha256=parent['artifact_sha256'],
                 dataset_sha256=digest(sorted(records, key=lambda r: r['id'])),
                 training_buildings=sorted(train_ids | set(parent['training_buildings'])),
                 training_sources=sorted(train_sources), evaluation_buildings=sorted(eval_ids),
                 status='trained_candidate', production_eligible=False)
    _seal(model)
    previous, current = _metrics(parent, evaluation), _metrics(model, evaluation)
    reasons = []
    if len(train_ids) < 5 or len(eval_ids) < 5:
        reasons.append('insufficient_independent_buildings')
    if len(training) < min_training_records or len(evaluation) < min_evaluation_records:
        reasons.append('insufficient_reviewed_samples')
    if current['brier'] >= previous['brier']-1e-6:
        reasons.append('no_held_out_brier_improvement')
    if current['high_confidence_count'] < max(2, min_evaluation_records//4):
        reasons.append('insufficient_high_confidence_predictions')
    if current['accept_precision'] is None or current['accept_precision'] < max(.95, previous['accept_precision'] or 0):
        reasons.append('held_out_accept_precision_below_policy')
    model.update(production_eligible=not reasons, status='promotion_eligible' if not reasons else 'candidate_withheld',
                 evaluation={'previous': previous, 'candidate': current, 'reasons': reasons,
                             'min_training_records': min_training_records, 'min_evaluation_records': min_evaluation_records,
                             'policy': 'brier improves; accept precision >=95% and no regression; sufficient samples'})
    return _seal(model)
