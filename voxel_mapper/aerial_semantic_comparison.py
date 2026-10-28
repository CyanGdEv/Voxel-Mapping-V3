"""Compare park-excluded checkpoints on one frozen set of visual annotations."""
import argparse
from html import escape
import json
from pathlib import Path

import numpy as np

from . import aerial_semantic_learning as learning, aerial_semantic_network as net
from .generation_cycles import atomic_json, file_hash


def _fold(directory, site, manifest, rows, pin):
    path = Path(directory)/'folds'/site/'model.json'
    model = learning.load_model(path)
    fitting = [r['record'] for r in rows if r['record']['site_id'] != site]
    expected = {
        'dataset_id': manifest['id'], 'dataset_sha256': pin,
        'training_record_ids': sorted(r['id'] for r in fitting),
        'training_site_ids': sorted({r['site_id'] for r in fitting}),
        'training_source_sha256': sorted({r['source_sha256'] for r in fitting}),
    }
    for key, value in expected.items():
        actual = sorted(model[key]) if isinstance(value, list) else model[key]
        if actual != value:
            raise ValueError('Comparison requires the matching park-excluded checkpoint: '+site)
    return path, model


def _scores(matrix):
    result = learning._metrics(matrix)
    tp = int(matrix[0, 0]); predicted = int(matrix[:, 0].sum())
    result['paving_precision'] = tp/predicted if predicted else 0.
    result['paving_recall'] = result['per_class'][0]['recall']
    return result


def compare(reference_dataset, candidate_dataset, previous_models, candidate_models, output,
            *, cancelled=lambda: False):
    """Targets and source RGB always come from reference_dataset, never predictions.

    Candidate annotations may expand, but both models are scored on exactly the
    same original pixels. Every park is wholly excluded from its scoring model.
    These reused development labels do not become an untouched final test.
    """
    output = Path(output)
    if output.exists():
        raise ValueError('Fresh frozen-comparison output required')
    original, rows, old_pin = learning.read_dataset(reference_dataset, cancelled=cancelled)
    expanded, new_rows, new_pin = learning.read_dataset(candidate_dataset, cancelled=cancelled)
    new_records = {r['record']['id']: r['record'] for r in new_rows}
    for item in rows:
        row = item['record']; new = new_records.get(row['id'], {})
        if any(new.get(k) != row[k] for k in ('source_sha256', 'site_id')):
            raise ValueError('Candidate dataset must retain the original sources and park grouping')
    totals = [np.zeros((5, 5), np.int64), np.zeros((5, 5), np.int64)]
    records = []; folds = []
    for site in sorted({r['record']['site_id'] for r in rows}):
        net.check(cancelled)
        before_path, before = _fold(previous_models, site, original, rows, old_pin)
        after_path, after = _fold(candidate_models, site, expanded, new_rows, new_pin)
        if before['network']['settings'] != after['network']['settings']:
            raise ValueError('Frozen data-expansion comparison requires unchanged optimizer settings')
        matrices = [np.zeros((5, 5), np.int64), np.zeros((5, 5), np.int64)]
        for item in rows:
            row = item['record']
            if row['site_id'] != site:
                continue
            labels = item['labels'].reshape(-1); valid = labels != 255
            features = item['features'].reshape(-1, net.FEATURE_COUNT)[valid]
            scores = []
            for model, total, matrix in zip((before, after), totals, matrices):
                predicted = net.predict(features, model, cancelled=cancelled).argmax(axis=1)
                local = np.zeros((5, 5), np.int64)
                np.add.at(local, (labels[valid], predicted), 1)
                total += local; matrix += local; scores.append(_scores(local))
            records.append({'id': row['id'], 'site_id': site,
                'source_sha256': row['source_sha256'], 'frozen_mask_sha256': row['mask_sha256'],
                'previous': scores[0], 'candidate': scores[1]})
        folds.append({'held_out_site': site,
            'previous_model_sha256': file_hash(before_path), 'candidate_model_sha256': file_hash(after_path),
            'previous_training_sites': before['training_site_ids'], 'candidate_training_sites': after['training_site_ids'],
            'previous': _scores(matrices[0]), 'candidate': _scores(matrices[1])})
    report = {'version': 'aerial-semantic-frozen-comparison-v1',
        'reference_dataset_id': original['id'], 'reference_dataset_sha256': old_pin,
        'candidate_dataset_id': expanded['id'], 'candidate_dataset_sha256': new_pin,
        'label_policy': learning.POLICY, 'same_frozen_targets': True, 'whole_park_exclusion': True,
        'optimizer_settings_unchanged': True, 'previous': _scores(totals[0]), 'candidate': _scores(totals[1]),
        'folds': folds, 'records': records, 'production_eligible': False, 'world_blocks_generated': 0,
        'limitations': ['Sparse assistant visual labels are provisional, not independent human or survey truth.',
            'Existing development targets have been inspected before; this is not a blind final test.',
            'Only originally annotated pixels are scored. Unlabelled false positives and boundary completeness are unmeasured.',
            'Expanded-data folds are evaluated separately; final all-data model has no untouched final test.']}
    output.mkdir(parents=True)
    atomic_json(output/'report.json', report)
    table = ''
    for i, name in enumerate(net.CLASSES):
        values = [r['per_class'][i]['iou'] for r in (report['previous'], report['candidate'])]
        table += '<tr><td>'+escape(name)+'</td>'+''.join('<td>'+('n/a' if x is None else f'{100*x:.2f}%')+'</td>' for x in values)+'</tr>'
    (output/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Frozen semantic comparison</title>'
        '<style>body{font:16px system-ui;margin:30px auto;max-width:1000px}td,th{padding:10px;text-align:left}</style>'
        '<h1>Same-pixel development comparison</h1><p>Each model excludes the whole scored park. '
        'Targets are unchanged provisional assistant visual labels. This is not a blind final test or full-image accuracy.</p>'
        '<table><tr><th>Class</th><th>Previous IoU</th><th>Expanded-data IoU</th></tr>'+table+'</table>'
        '<p><a href="report.json">All records, folds, confusion matrices and source pins</a></p>', encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('reference-dataset', 'candidate-dataset', 'previous-models', 'candidate-models', 'output'):
        parser.add_argument('--'+key, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(compare(args.reference_dataset, args.candidate_dataset,
        args.previous_models, args.candidate_models, args.output)))


if __name__ == '__main__':
    main()
