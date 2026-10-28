"""Offline source-only polygon review; retain corrections as provisional evidence."""
import argparse
import base64
import copy
import json
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image

from . import paving_masks as masks
from .generation_cycles import atomic_json, file_hash
from . import study_component_learning as safe

VERSION = 'paving-label-review-v1'


def payload(dataset):
    root = Path(dataset).resolve(); manifest = masks.validate(root)
    if manifest.get('reserved_test_only'):
        raise ValueError('Reserved test cannot enter development label review')
    annotations, _ = safe._json(root/manifest['annotation_file'], 2000000)
    return {'version': VERSION, 'dataset_id': manifest['id'],
        'annotation_sha256': manifest['annotation_sha256'],
        'source_pins': {r['id']: {k: r[k] for k in
            ('source_sha256', 'metadata_sha256', 'image_sha256', 'crop_pixels')} for r in manifest['records']},
        'reviewer': '', 'attestation': False, 'decisions': {},
        'annotations': copy.deepcopy(annotations)}


def create(dataset, output):
    root = Path(dataset).resolve(); data = payload(root); manifest = masks.validate(root)
    images = {r['id']: 'data:image/png;base64,'+base64.b64encode((root/r['image_file']).read_bytes()).decode()
        for r in manifest['records']}
    template = Path(__file__).with_name('paving_label_review.html').read_text(encoding='utf-8')
    # Literal data only; a trace reason must never terminate the script element.
    packed = json.dumps({'review': data, 'images': images}, ensure_ascii=True).replace('<', '\\u003c')
    page = template.replace('/* REVIEW_DATA */', packed)
    Path(output).write_text(page, encoding='utf-8')
    return {'crops': len(images), 'traces': sum(len(t) for t in data['annotations']['crops'].values()),
        'dataset_id': data['dataset_id'], 'human_labels_verified': False}


def apply(dataset, review_file, output):
    root = Path(dataset).resolve(); expected = payload(root)
    review, _ = safe._json(Path(review_file), 2000000)
    if set(review) != set(expected) or any(review[k] != expected[k] for k in
            ('version', 'dataset_id', 'annotation_sha256', 'source_pins')):
        raise ValueError('Review must match the exact original dataset and sources')
    reviewer = review['reviewer']
    if not isinstance(reviewer, str) or not 1 <= len(reviewer.strip()) <= 120 or review['attestation'] is not True:
        raise ValueError('Named reviewer and explicit source-only review attestation required')
    old = expected['annotations']; new = review['annotations']
    if not isinstance(new, dict) or set(new) != set(old) or any(new[k] != old[k] for k in old if k != 'crops'):
        raise ValueError('Review cannot change the annotation contract or boundary margin')
    if not isinstance(new['crops'], dict) or set(new['crops']) != set(old['crops']):
        raise ValueError('Review cannot change crop identities')
    decisions = review['decisions']
    if not isinstance(decisions, dict) or set(decisions) != set(old['crops']):
        raise ValueError('Explicit decision for every crop required')
    manifest = masks.validate(root); changes = []; items = []
    for row in manifest['records']:
        cid = row['id']; before = {t['id']: t for t in old['crops'][cid]}
        traces = new['crops'][cid]
        # Rasterizer validates polygon bounds, holes, IDs and semantic classes.
        masks.rasterize(traces, tuple(row['image_size']), boundary_pixels=new['boundary_ignore_pixels'])
        after = {t['id']: t for t in traces}; decision = decisions[cid]
        if not set(before) <= set(after) or not isinstance(decision, dict) or set(decision) != set(after):
            raise ValueError('Retain original IDs; explicitly mark uncertain traces unknown')
        for tid, trace in after.items():
            action = decision[tid]
            if action not in ('keep', 'correct', 'unknown'):
                raise ValueError('Every trace needs keep/correct/unknown decision')
            if action == 'keep' and trace != before.get(tid):
                raise ValueError('Changed or added trace cannot be marked keep')
            if action == 'unknown' and trace['label'] != 'unknown':
                raise ValueError('Unknown decision must retain unknown pixels')
        items.append({**{k: row[k] for k in ('id', 'site_id', 'source_record_id', 'source_sha256',
            'metadata_sha256', 'crop_pixels')}, 'source_file': str(root/row['source_file']),
            'metadata_file': str(root/row['metadata_file'])})
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Fresh reviewed dataset output required')
    with tempfile.TemporaryDirectory() as temp:
        annotations = Path(temp)/'annotations.json'; atomic_json(annotations, new)
        result = masks.build(items, annotations, output)
    for oldrow, newrow in zip(manifest['records'], result['records']):
        with Image.open(root/oldrow['mask_file']) as image: a = np.array(image)
        with Image.open(output/newrow['mask_file']) as image: b = np.array(image)
        changes.append({'id': oldrow['id'], 'changed_pixels': int((a != b).sum()),
            'unknown_to_labelled_pixels': int(((a == 255) & (b != 255)).sum()),
            'labelled_to_unknown_pixels': int(((a != 255) & (b == 255)).sum()),
            'class_flips': int(((a != 255) & (b != 255) & (a != b)).sum())})
    atomic_json(output/'review-receipt.json', review)
    report = {'version': VERSION, 'parent_dataset_id': manifest['id'], 'dataset_id': result['id'],
        'review_file_sha256': file_hash(output/'review-receipt.json'),
        'reviewer_attested': reviewer.strip(), 'review_identity_independently_verified': False,
        'human_labels_verified': False, 'production_eligible': False, 'training_run': False,
        'source_pixels_unchanged': True, 'changes': changes}
    atomic_json(output/'review-report.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ('create', 'apply'):
        cmd = sub.add_parser(action); cmd.add_argument('--dataset', required=True)
        cmd.add_argument('--output', required=True)
        if action == 'apply': cmd.add_argument('--review', required=True)
    args = parser.parse_args(argv)
    result = create(args.dataset, args.output) if args.action == 'create' else apply(args.dataset, args.review, args.output)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
