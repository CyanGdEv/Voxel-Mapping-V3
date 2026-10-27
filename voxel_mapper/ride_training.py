"""Source-bound ride component learning, separate from estimated 3D reconstruction."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import tempfile

from shapely.geometry import LineString, mapping, shape
from shapely.ops import polygonize

from .building_spec import digest
from .generation_cycles import atomic_json
from . import study_component_learning as reader
from . import study_dataset as pairs

VERSION = 'ride-source-review-v1'
KINDS = {'centreline_span': 'ride_track_centreline',
         'support_line': 'ride_support_crossline', 'support_symbol': 'ride_support_footprint'}


def source_geometry(markings, selections):
    """Resolve exact native selectors; never close a track or invent support ends."""
    roles = {}
    for row in markings['records']:
        roles.setdefault(row['role'], []).append(row['geometry_pdf_native'])
    if len(roles.get('track_centre', [])) != 1 or len(roles.get('support_boundaries', [])) != 1:
        raise ValueError('Unique source track and support geometry required')
    centre = shape(roles['track_centre'][0])
    lines = shape(roles['support_boundaries'][0])
    if centre.geom_type != 'LineString' or lines.geom_type != 'MultiLineString':
        raise ValueError('Native track LineString and support MultiLineString required')
    if len(centre.coords) > 20_000 or len(lines.geoms) > 100_000:
        raise ValueError('Ride source geometry exceeds work budget')
    polygons = list(polygonize(lines)) if any(s['type'] == 'support_symbol' for s in selections) else []
    result = []
    for selection in selections:
        kind = selection.get('type')
        if kind == 'centreline_span':
            start, end = selection.get('start_vertex'), selection.get('end_vertex')
            if type(start) is not int or type(end) is not int or not 0 <= start < end < len(centre.coords):
                raise ValueError('Original ordered centreline vertex span required')
            geometry = LineString(list(centre.coords)[start:end+1])
        elif kind in ('support_line', 'support_symbol'):
            index = selection.get('index')
            inventory = lines.geoms if kind == 'support_line' else polygons
            if type(index) is not int or not 0 <= index < len(inventory):
                raise ValueError('Existing native support selector required')
            geometry = inventory[index]
        else:
            raise ValueError('Only native source 2D ride selectors are eligible')
        result.append(json.loads(json.dumps(mapping(geometry))))
    return result


def build(review_path, markings_path, source_directory, output, *, cancelled=lambda: False):
    review_path, markings_path, output = Path(review_path), Path(markings_path), Path(output)
    review, review_raw = reader._json(review_path, 8_000_000)
    markings, markings_raw = reader._json(markings_path, 32_000_000)
    if output.exists():
        raise ValueError('Fresh ride dataset output required')
    if review.get('version') != VERSION or review.get('coordinate_frame') != 'pdf_native_points_y_up':
        raise ValueError('Native ride source review contract required')
    rows = review.get('records')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 512:
        raise ValueError('One to 512 explicit ride reviews required')
    source = review.get('source', {})
    for key in ['ride_id', 'site_id', 'review_basis']:
        reader._identifier(review.get(key), key)
    if (reader._sha(markings_raw) != source.get('markings_sha256')
            or markings.get('document_sha256') != source.get('document_sha256')
            or markings.get('page') != source.get('page')
            or markings.get('coordinate_frame') != review['coordinate_frame']):
        raise ValueError('Original source markings or page pin changed')
    document = source.get('document_sha256')
    if not reader._hash(document) or not source.get('rights_advisory') or source.get('state') not in ['proposed', 'existing', 'unknown']:
        raise ValueError('Pinned source PDF, rights advisory and source state required')
    if not isinstance(source.get('url'), str) or not source['url'].startswith('https://'):
        raise ValueError('Original source URL required')
    pdf = Path(source_directory)/(document+'.pdf')
    if not pdf.is_file() or pdf.stat().st_size > pairs.MAX_PDF_BYTES or pairs.file_hash(pdf) != document:
        raise ValueError('Exact original ride PDF bytes required')
    reader._check(cancelled)
    geometries = source_geometry(markings, [r['selector'] for r in rows])
    records = []
    review_pin = reader._sha(review_raw)
    for index, (row, geometry) in enumerate(zip(rows, geometries)):
        reader._check(cancelled)
        reader._identifier(row.get('id'), 'ride review id')
        if row.get('review_status') != 'reviewed_source_selection' or digest(geometry) != row.get('geometry_sha256'):
            raise ValueError('Reviewed source selection and exact native geometry pin required')
        if row.get('physical_geometry_verified') is not False:
            raise ValueError('Drawing supervision cannot imply physical verification')
        uncertainty = row.get('trace_uncertainty_pdf_points')
        if type(uncertainty) not in (int, float) or not 0 < uncertainty <= 10:
            raise ValueError('Explicit bounded source trace uncertainty required')
        records.append({'id': row['id'], 'building_id': 'ride-'+review['ride_id'],
            'ride_id': review['ride_id'], 'site_id': review['site_id'],
            'kind': KINDS[row['selector']['type']], 'source_state': source['state'],
            'source': {'document_sha256': document, 'page': source['page'],
                'coordinate_frame': 'native_y_up', 'render_width_pixels': source.get('render_width_pixels', 3200)},
            'target_geometry': geometry, 'source_selector': copy.deepcopy(row['selector']),
            'evidence_level': 'source_extracted_profile', 'trace_uncertainty_pdf_points': uncertainty,
            'review_refs': [{'path': 'ride-review.json', 'sha256': review_pin, 'pointer': '/records/'+str(index)}],
            'assumptions': [review['review_basis'],
                '2D planning drawing component only; no source-to-track branch, physical footing size, 3D brace, height or as-built identity inferred.',
                'Original ordered track span stays open; no estimated circuit closure is a target.']})
    catalogue = {'records': records, 'documents': [{'document_sha256': document, 'url': source['url'],
        'source_state': source['state'], 'rights_advisory': source['rights_advisory']}],
        'input_sha256': {'ride-review.json': review_pin}}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ride-pairs-', dir=output.parent) as tmp:
        root = Path(tmp)
        (root/'ride-review.json').write_bytes(review_raw)
        stage = root/'dataset'
        manifest = pairs.build(catalogue, source_directory, stage, repo_root=root, cancelled=cancelled)
        if manifest['withheld'] or len(manifest['records']) != len(rows):
            raise ValueError('Every ride target must pair with the unchanged original PDF')
        contract = {'version': 'ride-learning-scope-v1', 'source_review_sha256': review_pin,
            'markings_sha256': reader._sha(markings_raw), 'ride_id': review['ride_id'],
            'site_id': review['site_id'], 'target_dimensions': 2,
            'independent_rides': 1, 'held_ride_accuracy': None,
            'metric_height_targets': 0, 'verified_3d_support_targets': 0,
            'lidar_role': 'reference_context_only; return classification does not identify hidden track or timbers',
            'world_variants_are_training_targets': False, 'production_eligible': False,
            'next_tasks': ['Independent ride plans with the same reviewed component classes.',
                'Reviewed plan/section correspondence and height datum with explicit branch ambiguity.',
                'Verified support-foot to track-visit bindings before training 3D support placement.',
                'Separate user material/style preferences from geometry truth.']}
        atomic_json(stage/'ride-scope.json', contract)
        manifest['dataset_kind'] = 'ride_source_components_2d'
        manifest['ride_learning_scope'] = contract
        manifest['output_sha256']['ride-scope.json'] = pairs.file_hash(stage/'ride-scope.json')
        manifest['id'] = digest({k: v for k, v in manifest.items() if k != 'id'})
        atomic_json(stage/'dataset.json', manifest)
        reader.read_dataset(stage, cancelled=cancelled)
        reader._check(cancelled)
        shutil.move(stage, output)
    return manifest


def train(directory, output, *, encoder_path, encoder_sha256, cancelled=lambda: False):
    """Fit only explicit ride component pairs; retain the shared-source folds."""
    from . import study_transfer_learning as transfer
    manifest, rows, _, _ = reader.read_dataset(directory, cancelled=cancelled)
    if (manifest.get('dataset_kind') not in ['ride_source_components_2d', 'multi_source_reviewed_study_intake']
            or any(not row['kind'].startswith('ride_') or not row['building_id'].startswith('ride-') for row in rows)):
        raise ValueError('Explicit ride-only component dataset required')
    return transfer.train(directory, output, encoder_path=encoder_path,
        encoder_sha256=encoder_sha256, cancelled=cancelled)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    make = commands.add_parser('build')
    for key in ['review', 'markings', 'sources', 'output']:
        make.add_argument('--'+key, required=True)
    fit = commands.add_parser('train')
    for key in ['dataset', 'output', 'encoder', 'encoder-sha256']:
        fit.add_argument('--'+key, required=True)
    args = parser.parse_args(argv)
    if args.command == 'build':
        result = build(args.review, args.markings, args.sources, args.output)
        print(json.dumps(result['summary']))
    else:
        result = train(args.dataset, args.output, encoder_path=args.encoder,
            encoder_sha256=args.encoder_sha256)
        print(json.dumps({'records': result['records'], 'head_weights_updated': result['head_weights_updated'],
            'evaluation_status': result['cross_source_evaluation']['status'], 'production_eligible': False}))


if __name__ == '__main__':
    main()
