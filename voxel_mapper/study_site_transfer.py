"""Site-isolated evaluation of frozen visual features and fitted research heads."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile

import numpy as np

from . import study_component_learning as baseline
from . import study_pretrained_encoder as encoder
from . import study_transfer_learning as transfer
from . import study_vision_learning as vision
from .generation_cycles import atomic_json
from .study_intake import reservation


def train(directory, output, *, encoder_path, encoder_sha256,
          ridge_alpha=transfer.RIDGE_ALPHA, cancelled=lambda: False):
    """Keep reserved-site masks, labels and features outside every fitted head."""
    output = Path(output)
    if output.exists():
        raise ValueError('Fresh site transfer output required')
    alpha = transfer._alpha(ridge_alpha)
    manifest, rows, _, pin = baseline.read_dataset(
        directory, cancelled=cancelled, allow_reserved_evaluation=True)
    saved = manifest.get('site_reservation')
    if not isinstance(saved, dict):
        raise ValueError('Explicit site reservation required')
    actual = reservation(rows, saved['evaluation_sites'], manifest.get('context_assets', []))
    if actual != saved:
        raise ValueError('Site reservation changed or includes ineligible records')
    if actual['status'] != 'site_reservation_ready':
        raise ValueError('An independent evaluation site is required before training')
    synthetic = manifest['dataset_kind'].startswith('synthetic')
    info = encoder.encoder_info(encoder_path, encoder_sha256, allow_synthetic=synthetic)
    info.pop('path', None)
    source_pngs, masks = [], []
    root = Path(directory).resolve()
    for row in rows:
        baseline._check(cancelled)
        source = baseline._asset(root, row['input_file'])
        if not source.is_file() or source.stat().st_size > baseline.MAX_IMAGE_BYTES:
            raise ValueError('Bounded source crop required')
        with source.open('rb') as stream:
            raw = stream.read(baseline.MAX_IMAGE_BYTES + 1)
        if len(raw) > baseline.MAX_IMAGE_BYTES or baseline._sha(raw) != row['input_sha256']:
            raise ValueError('Source crop changed before frozen extraction')
        _, dimensions = vision._source_image(raw, 64)
        if 'input_size_pixels' in row and row['input_size_pixels'] != list(dimensions):
            raise ValueError('Declared source crop dimensions changed')
        name = row.get('target_mask_file')
        mask_pin = manifest['output_sha256'].get(name)
        path = baseline._asset(root, name)
        if not baseline._hash(mask_pin) or path.stat().st_size > baseline.MAX_IMAGE_BYTES:
            raise ValueError('Bounded pinned target mask required')
        with path.open('rb') as stream:
            target = stream.read(baseline.MAX_IMAGE_BYTES + 1)
        if (len(target) > baseline.MAX_IMAGE_BYTES or baseline._sha(target) != mask_pin
                or row.get('target_mask_sha256', mask_pin) != mask_pin):
            raise ValueError('Target mask changed before fitting')
        masks.append(vision._target_mask(target, 64, dimensions))
        source_pngs.append(raw)
    features = encoder.extract(source_pngs, encoder_path, encoder_sha256,
        allow_synthetic=synthetic, cancelled=cancelled)
    transfer._features(features)
    if features.shape != (len(rows), info['feature_count']):
        raise ValueError('Registered frozen feature dimensions changed')
    masks = np.asarray(masks)
    train_ids = set(saved['training_record_ids'])
    held_ids = set(saved['evaluation_record_ids'])
    a = [i for i, row in enumerate(rows) if row['id'] in train_ids]
    b = [i for i, row in enumerate(rows) if row['id'] in held_ids]
    fitting, held = [rows[i] for i in a], [rows[i] for i in b]
    if not 2 <= len({row['kind'] for row in fitting}) <= 16:
        raise ValueError('Two to sixteen training component classes required')
    baseline._check(cancelled)
    model = transfer._make_model(fitting, features[a], masks[a], manifest, pin,
        info, alpha, 64, cancelled)
    model['site_reservation'] = saved
    model['limitations'] = [s for s in model['limitations'] if not s.startswith('The final checkpoint fits')]
    model['limitations'].append('Checkpoint fits training sites only; reserved sites are excluded from normalization and heads. No all-data refit.')
    transfer._seal(model)
    transfer.validate_model(model)
    probabilities, predicted_masks = transfer._infer(model, features[b])
    truth = [row['kind'] for row in held]
    predicted = [model['classes'][int(np.argmax(p))] for p in probabilities]
    classes = sorted(set(truth) | set(model['classes']))
    majority = min(model['classes'], key=lambda k: (-sum(r['kind'] == k for r in fitting), k))
    template = masks[a].mean(axis=0)
    predictions = []
    for index, row, expected, prediction, mask in zip(b, held, truth, predicted, predicted_masks):
        predictions.append({'record_id': row['id'], 'group_id': row['group_id'],
            'expected': expected, 'predicted': prediction,
            'mask_metrics': vision._mask_metrics(masks[index], mask),
            'template_mask_metrics': vision._mask_metrics(masks[index], template)})
    report = {'version': 'site-isolated-study-transfer-v1', 'dataset_id': manifest['id'],
        'dataset_manifest_sha256': pin, 'training_sites': saved['training_sites'],
        'evaluation_sites': saved['evaluation_sites'], 'training_records': len(a), 'evaluation_records': len(b),
        'training_sources': model['training_sources'],
        'evaluation_sources': sorted({r['source']['document_sha256'] for r in held}),
        'metrics': baseline._metrics(truth, predicted, classes),
        'majority_baseline_metrics': baseline._metrics(truth, [majority]*len(held), classes),
        'predictions': predictions, 'ridge_alpha': alpha, 'encoder_sha256': info['sha256'],
        'encoder_weights_updated': False, 'head_weights_updated': True,
        'evaluation_classes_absent_from_training': saved['evaluation_classes_absent_from_training'],
        'model_sha256': model['artifact_sha256'],
        'final_checkpoint_fit': 'training sites only; evaluation sites excluded from normalization and optimizer',
        'production_eligible': False, 'physical_acceptance': False, 'geometry_generated': False,
        'limitations': model['limitations'] + ['Evaluation site is now inspected development evidence; reserve a fresh site before tuning.',
            'All models use supplied reviewed crops. Automatic page discovery is not evaluated.',
            'One held site cannot establish broad park reconstruction quality.']}
    baseline._check(cancelled)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='site-transfer-', dir=output.parent) as tmp:
        stage = Path(tmp)/'result'
        stage.mkdir()
        transfer._bundle_encoder(stage, encoder_path, info)
        transfer.save_model(model, stage/'model.json')
        atomic_json(stage/'report.json', report)
        baseline._check(cancelled)
        shutil.move(stage, output)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--encoder', required=True)
    parser.add_argument('--encoder-sha256', required=True)
    args = parser.parse_args(argv)
    result = train(args.dataset, args.output, encoder_path=args.encoder, encoder_sha256=args.encoder_sha256)
    print(json.dumps({k: result[k] for k in ['training_records', 'evaluation_records', 'metrics', 'production_eligible']}))


if __name__ == '__main__':
    main()
