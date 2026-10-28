"""Evaluate frozen RGB/context label-correction candidates on one reserved area."""
import argparse
import copy
import datetime
import json
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image
from pyproj import Transformer

from . import paving_masks as masks, paving_binary_learning as binary
from . import paving_spatial_transfer as spatial, study_component_learning as safe
from .desktop_memory import digest
from .generation_cycles import atomic_json, file_hash

METHODS = ('baseline_rgb', 'corrected_rgb', 'baseline_context', 'corrected_context')


def correct(dataset, recipe_file, output):
    """Apply a pinned, literal source-only correction recipe without touching its parent."""
    root = Path(dataset).resolve(); manifest = masks.validate(root)
    recipe, _ = safe._json(Path(recipe_file), 2000000)
    if manifest.get('reserved_test_only') or recipe.get('version') != 'paving-source-correction-recipe-v1' or recipe.get('human_labels_verified') is not False:
        raise ValueError('Development-only provisional source corrections required')
    if recipe['parent_dataset_id'] != manifest['id'] or recipe['parent_annotation_sha256'] != manifest['annotation_sha256']:
        raise ValueError('Correction recipe must match the exact original labels')
    annotations, _ = safe._json(root/manifest['annotation_file'], 2000000)
    annotations = copy.deepcopy(annotations); cid = recipe['crop_id']
    if cid not in annotations['crops']: raise ValueError('Correction crop not present')
    annotations['crops'][cid].extend(recipe['add_traces'])
    items = []
    for row in manifest['records']:
        masks.rasterize(annotations['crops'][row['id']], tuple(row['image_size']), boundary_pixels=annotations['boundary_ignore_pixels'])
        items.append({**{k: row[k] for k in ('id','site_id','source_record_id','source_sha256','metadata_sha256','crop_pixels')},
            'source_file': str(root/row['source_file']), 'metadata_file': str(root/row['metadata_file'])})
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp)/'annotations.json'; atomic_json(path, annotations)
        return masks.build(items, path, output)


def adoption(scores, development):
    """Predeclared conservative gate; a single provisional test never proves general accuracy."""
    old, new = scores['baseline_rgb'], scores['corrected_rgb']; reasons = []
    for key in ('paving_iou', 'paving_precision', 'paving_recall'):
        if new[key] < old[key]: reasons.append(key+' decreased')
    for section, key in (('boundary', 'f1'), ('connections', 'recall')):
        a, b = old[section][key], new[section][key]
        if a is None or b is None: reasons.append(section+' evidence unavailable')
        elif b < a: reasons.append(section+' decreased')
    if development['corrected_rgb_macro_iou'] < development['baseline_rgb_macro_iou']:
        reasons.append('whole-park macro IoU decreased')
    return {'passes_numeric_gate': not reasons, 'reasons': reasons,
        'automatic_adoption': False, 'general_accuracy_claim_allowed': False,
        'human_labels_verified': False}


def evaluate(dataset, freeze_file, seal_file, protocol_file, development_file, output):
    output = Path(output)
    if output.exists(): raise ValueError('Fresh correction benchmark output required')
    root = Path(dataset).resolve(); manifest = masks.validate(root)
    if manifest.get('reserved_test_only') is not True:
        raise ValueError('Reserved-test-only masks required')
    freeze_file = Path(freeze_file).resolve()
    frozen, _ = safe._json(freeze_file, 2000000)
    protocol, _ = safe._json(Path(protocol_file), 2000000)
    seal, _ = safe._json(Path(seal_file), 2000000)
    development, _ = safe._json(Path(development_file), 2000000)
    if protocol.get('version') != 'paving-correction-test-protocol-v1' or protocol.get('score_threshold') != .5 or protocol.get('methods') != [*METHODS, 'always_paving']:
        raise ValueError('Predeclared correction comparison protocol required')
    if frozen['protocol_sha256'] != file_hash(protocol_file) or set(frozen['models']) != set(METHODS):
        raise ValueError('Frozen methods and protocol must match')
    if development['development_dataset_sha256'] != frozen['development_dataset_sha256']:
        raise ValueError('Development comparison must use the frozen training dataset')
    if len(manifest['records']) != 1 or manifest['records'][0]['id'] != protocol['test_crop_id']:
        raise ValueError('Exactly the predeclared reserved crop is required')
    annotations, _ = safe._json(root/manifest['annotation_file'], 2000000)
    if annotations['boundary_ignore_pixels'] != protocol['boundary_ignore_pixels']:
        raise ValueError('Test edge-ignore policy differs from the reservation')
    if seal['test_manifest_sha256'] != file_hash(root/'dataset.json') or seal['test_annotation_sha256'] != manifest['annotation_sha256'] or seal['frozen_models_sha256'] != file_hash(freeze_file) or seal['development_comparison_sha256'] != file_hash(development_file):
        raise ValueError('Test annotations, development scores and model freeze must remain sealed')
    when = lambda s: datetime.datetime.fromisoformat(s)
    if not when(protocol['reserved_at_utc']) <= when(frozen['frozen_at_utc']) <= when(seal['sealed_at_utc']):
        raise ValueError('Reservation, model freeze and annotation seal must be ordered')
    models = {}
    for name, entry in frozen['models'].items():
        path = safe._asset(freeze_file.parent, entry['file'])
        if file_hash(path) != entry['sha256']: raise ValueError('Frozen checkpoint changed')
        model, _ = safe._json(path, 2000000); binary.validate_model(model)
        expected_mode = 'rgb_only' if name.endswith('_rgb') else 'rgb_context'
        if model['feature_mode'] != expected_mode: raise ValueError('Frozen feature mode differs')
        if model['network']['settings'] != protocol['head_settings']:
            raise ValueError('Model settings differ from the predeclared comparison')
        if name.startswith('corrected') and model['dataset_sha256'] != frozen['development_dataset_sha256']:
            raise ValueError('Candidate does not use the frozen corrected development dataset')
        models[name] = model
    prepared = []
    for row in manifest['records']:
        if row['site_id'] != protocol['test_site_id'] or row['site_id'] in protocol.get('excluded_consumed_tests', []):
            raise ValueError('Reserved park differs from predeclared test')
        for model in models.values():
            if row['site_id'] in model['training_site_ids'] or row['source_sha256'] in model['training_source_sha256']:
                raise ValueError('Test park/source leaked into fitting')
        receipt, _ = safe._json(root/row['metadata_file'], 2000000)
        width, height = protocol['native_export_dimensions']
        if [receipt['width'], receipt['height']] != [width, height] or row['crop_pixels'] != [width//4, height//4, 3*width//4, 3*height//4]:
            raise ValueError('Predeclared native export and central-half crop required')
        project = Transformer.from_crs(4326, 3857, always_xy=True)
        west, south, east, north = protocol['bounds_wgs84']
        x0, y0 = project.transform(west, south); x1, y1 = project.transform(east, north)
        dx, dy = max(x1-x0, (y1-y0)*width/height), max(y1-y0, (x1-x0)*height/width)
        expected_extent = [(x0+x1-dx)/2, (y0+y1-dy)/2, (x0+x1+dx)/2, (y0+y1+dy)/2]
        if not np.allclose(receipt['extent_epsg3857'], expected_extent, rtol=0, atol=.01):
            raise ValueError('Test imagery extent differs from reserved geography')
        with Image.open(root/row['mask_file']) as image: target = np.array(image)
        probes = seal['connection_probes'].get(row['id'], [])
        spatial.connections(target, np.ones(target.shape, bool), probes)
        prepared.append((row, receipt, target, probes))
    key = digest({'freeze': frozen, 'seal': seal, 'protocol_sha256': file_hash(protocol_file)})
    marker = freeze_file.parent/'correction-test-consumed.json'; replay = marker.exists()
    if replay:
        previous, _ = safe._json(marker, 10000)
        if previous['evaluation_key'] != key: raise ValueError('Test consumed; changed inputs require a new area')
    else:
        with marker.open('x') as stream: json.dump({'evaluation_key': key}, stream)
    output.mkdir(parents=True); results = []
    for row, receipt, target, probes in prepared:
        with Image.open(root/row['source_file']) as image: rgb = np.array(image.convert('RGB'))
        features = binary._features(rgb, receipt, lambda: False)
        x0, y0, x1, y1 = row['crop_pixels']; features = features[y0:y1, x0:x1]; rgb = rgb[y0:y1, x0:x1]
        scores = {}
        for name in [*METHODS, 'always_paving']:
            p = np.ones(target.shape, np.float32) if name == 'always_paving' else binary.probabilities(features, models[name])[:, :, 1]
            positive = p >= .5
            scores[name] = {**spatial._score(target, positive),
                'boundary': spatial.boundary_f1(target, positive, protocol['boundary_tolerance_native_pixels']),
                'connections': spatial.connections(target, positive, probes)}
            folder = output/row['id']/name; folder.mkdir(parents=True)
            Image.fromarray(positive.astype(np.uint8)).save(folder/'score-mask.png')
            preview = positive.astype(np.uint8); preview[np.maximum(p, 1-p) < .6] = 255
            Image.fromarray(preview).save(folder/'preview-mask.png')
            overlay = rgb.copy(); selected = preview == 1
            overlay[selected] = (rgb[selected]*.45+np.array([35,165,255])*.55).astype(np.uint8)
            Image.fromarray(overlay).save(folder/'overlay.png')
        results.append({'id': row['id'], 'scores': scores, 'adoption_gate': adoption(scores, development)})
    report = {'version': 'paving-correction-test-v1', 'evaluation_key': key,
        'identical_sealed_input_replay': replay, 'results': results, 'test_manifest_sha256': file_hash(root/'dataset.json'),
        'development_comparison_sha256': file_hash(development_file), 'frozen_models_sha256': file_hash(freeze_file),
        'production_eligible': False, 'human_labels_verified': False, 'model_weights_updated_during_test': False,
        'limitations': ['One source-only assistant-labelled test area; not independent ground truth.',
            'Ignored edges may leave boundary F1 unavailable; this is insufficient evidence for adoption.',
            'Always-paving connection recall alone does not establish route quality.']}
    atomic_json(output/'report.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    change = sub.add_parser('correct')
    for name in ('dataset', 'recipe', 'output'): change.add_argument('--'+name, required=True)
    evaluate_parser = sub.add_parser('evaluate')
    for name in ('dataset', 'freeze', 'seal', 'protocol', 'development', 'output'):
        evaluate_parser.add_argument('--'+name, required=True)
    args = parser.parse_args(argv)
    if args.action == 'correct':
        result = correct(args.dataset, args.recipe, args.output)
        print(json.dumps({'dataset_id': result['id'], 'human_labels_verified': False}))
    else:
        result = evaluate(args.dataset, args.freeze, args.seal, args.protocol, args.development, args.output)
        print(json.dumps({'evaluation_key': result['evaluation_key'], 'results': result['results']}))


if __name__ == '__main__': main()
