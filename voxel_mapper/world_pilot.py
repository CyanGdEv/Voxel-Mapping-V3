"""Offline small-area world builds with explicit planning omissions and pinned inputs."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import shutil

from pyproj import Geod

from .bedrock import export_world
from .cli import build, validate_config

VERSION = 'world-pilot-v1'
MAX_AREA_M2 = 40_000
MAX_JSON_BYTES = 16_000_000
MAX_RECORDS = 10_000


def _sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _json(path):
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError('Pilot JSON byte budget exceeded')
    def invalid_constant(value):
        raise ValueError('Nonfinite JSON value: ' + value)
    return json.loads(path.read_text(encoding='utf-8'), parse_constant=invalid_constant)


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')


def _prepare(job_path):
    job = _json(job_path)
    if job.get('version') != VERSION or not isinstance(job.get('name'), str) or not job['name'].strip():
        raise ValueError('Named world-pilot-v1 job required')
    pins = [(job_path, _sha(job_path))]
    assets = []

    def asset(descriptor, directory, role):
        if (not isinstance(descriptor, dict) or not isinstance(descriptor.get('file'), str)
                or not isinstance(descriptor.get('sha256'), str)
                or not re.fullmatch('[0-9a-f]{64}', descriptor['sha256'])):
            raise ValueError('Pinned file and SHA256 required for ' + role)
        path = (directory / descriptor['file']).resolve()
        if _sha(path) != descriptor['sha256']:
            raise ValueError('Input checksum mismatch: ' + role)
        pins.append((path, descriptor['sha256']))
        assets.append({'role': role, 'file': descriptor['file'], 'sha256': descriptor['sha256']})
        return path

    config_path = asset(job.get('config'), job_path.parent, 'config')
    feature_path = asset(job.get('features'), job_path.parent, 'features')
    review_path = asset(job.get('planning_review'), job_path.parent, 'planning_review')
    references = job.get('evidence', [])
    if not isinstance(references, list) or len(references) > 100:
        raise ValueError('Bounded supplementary evidence list required')
    for index, descriptor in enumerate(references):
        asset(descriptor, job_path.parent, 'evidence:' + str(index))
    config, collection, reviews = _json(config_path), _json(feature_path), _json(review_path)
    west, south, east, north, resolution = validate_config(config)
    area = abs(Geod(ellps='WGS84').polygon_area_perimeter(
        [west, east, east, west], [south, south, north, north])[0])
    if resolution != 1 or not math.isfinite(area) or area > MAX_AREA_M2:
        raise ValueError('Pilot requires one block per metre and at most 40,000 square metres')
    for key, limit in [('max_area_m2', MAX_AREA_M2), ('max_voxels', 1_000_000), ('max_column_checks', 1_000_000)]:
        value = config.get(key, limit)
        if type(value) is not int or not 1 <= value <= limit:
            raise ValueError('Invalid pilot budget: ' + key)
        config[key] = value
    if not config.get('terrain') or config['terrain'].get('emit_surface', True) is not True:
        raise ValueError('Pilot requires terrain with surface emission enabled')
    if config.get('point_cloud_evidence'):
        raise ValueError('Point-cloud inputs are not supported by this pilot contract')
    operation = job.get('horizontal_operation')
    grid = None
    if operation is not None:
        from .horizontal_grid import VERSION as GRID_VERSION, ORIGINAL_SHA256, SOURCE_URL
        if not isinstance(operation, dict) or operation.get('method') != GRID_VERSION:
            raise ValueError('Unsupported pilot horizontal operation')
        grid_path = asset(operation.get('grid'), job_path.parent, 'horizontal_grid')
        proof_path = asset(operation.get('provenance'), job_path.parent, 'horizontal_grid_provenance')
        proof = _json(proof_path)
        if (proof.get('original_sha256') != ORIGINAL_SHA256
                or proof.get('crop_sha256') != operation['grid']['sha256']):
            raise ValueError('Horizontal grid provenance mismatch')
        grid = {'method': GRID_VERSION, 'path': str(grid_path), 'sha256': operation['grid']['sha256']}
        if any(source.get('id') == 'pilot-ostn15-grid' for source in config.get('sources', [])):
            raise ValueError('Reserved pilot datum-grid source identity')
        config.setdefault('sources', []).append({'id': 'pilot-ostn15-grid', 'kind': 'datum_grid',
            'url': SOURCE_URL, 'license': 'BSD-2-Clause', 'sha256': grid['sha256'],
            'attribution': 'Derived from Ordnance Survey OSTN15 via PROJ-data; exact regional grid samples.'})
    for key in ('terrain', 'surface', 'surface_fallback', 'bathymetry'):
        if config.get(key):
            specification = config[key]
            if specification.get('horizontal_operation'):
                raise ValueError('Declare horizontal operations in the pinned pilot job')
            descriptor = {'file': specification.get('path'), 'sha256': specification.get('sha256')}
            specification['path'] = str(asset(descriptor, config_path.parent, key))
            if grid:
                specification['horizontal_operation'] = dict(grid)
    sources = config.get('sources', [])
    if (not isinstance(sources, list) or any(not isinstance(s, dict) or not s.get('id') for s in sources)
            or len({s['id'] for s in sources}) != len(sources)):
        raise ValueError('Unique registered pilot sources required')
    sources = {s['id']: s for s in sources}
    features = collection.get('features')
    records = collection.get('planning_geometry_records', [])
    if any(not isinstance(rows, list) or len(rows) > limit
           for rows, limit in ((features, MAX_RECORDS), (records, 1000), (reviews, 1000))):
        raise ValueError('Bounded feature, planning record and review lists required')
    identifiers = set()
    for feature in features:
        identifier = feature.get('id')
        properties = feature.get('properties', {})
        source = sources.get(properties.get('source_id'), {})
        if not isinstance(identifier, str) or not identifier or identifier in identifiers or identifier.startswith('planning/'):
            raise ValueError('Unique geographic feature IDs outside the planning namespace required')
        identifiers.add(identifier)
        if source.get('kind') not in ('osm', 'geographic') or any(
                key in properties for key in ('planning_geometry_evidence', 'planning_semantic_kind')):
            raise ValueError('Planning geometry must use planning_geometry_records and its acceptance checks')
    for rows in (records, reviews):
        ids = [row.get('id') for row in rows]
        if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('Unique planning record/review identities required')
    tasks = []
    for row in reviews:
        requirements = row.get('required_evidence')
        evidence = row.get('evidence')
        if (not isinstance(row.get('title'), str) or not row['title'].strip()
                or not isinstance(requirements, list) or not 1 <= len(requirements) <= 20
                or any(not isinstance(v, str) or not v.strip() for v in requirements)
                or not isinstance(evidence, list) or not 1 <= len(evidence) <= 20):
            raise ValueError('Review tasks require a title, missing evidence and pinned evidence files')
        for index, descriptor in enumerate(evidence):
            asset(descriptor, review_path.parent, 'review:' + row['id'] + ':' + str(index))
        tasks.append({'id': row['id'], 'title': row['title'], 'status': 'awaiting_evidence',
                      'required_evidence': requirements, 'evidence': evidence})
    return job, config, collection, tasks, pins, {'job_sha256': pins[0][1], 'assets': assets}


def run(job_path, output):
    """Publish only after native readback and a second check of every input hash."""
    job_path, output = Path(job_path).resolve(), Path(output).resolve()
    staging = output.with_name(output.name + '.partial')
    if output.exists() or staging.exists():
        raise ValueError('Use a fresh pilot output directory; existing output is never overwritten')
    job, config, collection, tasks, pins, inputs = _prepare(job_path)
    staging.mkdir(parents=True)
    try:
        _write(staging / 'inputs.json', inputs)
        _write(staging / 'resolved-config.json', config)
        quality = build(config, collection, staging)
        accuracy = (quality.get('terrain') or {}).get('coordinate_transform', {}).get('accuracy_m', -1)
        if accuracy < 0 or accuracy > 1:
            quality['issues'].append({'severity': 'warning', 'reason': 'Terrain coordinate operation has unknown or greater-than-one-metre advertised accuracy; no independent placement accuracy established.',
                                      'coordinate_operation_accuracy_m': accuracy})
        counts, kinds = Counter(), Counter()
        with (staging / 'voxels.jsonl').open(encoding='utf-8') as stream:
            for line in stream:
                row = json.loads(line)
                counts[row.get('feature')] += 1
                kinds[row['kind']] += 1
        planning = []
        for decision in quality['planning_geometry_decisions']:
            row = dict(decision)
            row['adapter_status'] = row.pop('status')
            row['emitted_voxel_records'] = counts['planning/' + row['id']]
            row['status'] = ('withheld' if row['adapter_status'] == 'withheld' else
                             'voxelized_for_export' if row['emitted_voxel_records'] else 'no_voxels')
            if row['status'] == 'no_voxels':
                row['reason'] = 'Adapter checks passed, but no voxel records were produced; inspect quality-report.json'
            planning.append(row)
        planning_count = sum(row['status'] == 'voxelized_for_export' for row in planning)
        readiness = {
            'planning_components_voxelized': planning_count,
            'planning_components_withheld': sum(row['status'] != 'voxelized_for_export' for row in planning),
            'planning_records': planning, 'pending_review_tasks': tasks,
            'planning_status': ('awaiting_evidence' if tasks or any(row['status'] != 'voxelized_for_export' for row in planning)
                                else 'adapter_components_voxelized' if planning_count else 'no_planning_input'),
            'scope': 'Draft terrain and geographic features, plus only planning records passing existing adapter checks.',
            'learning': 'Not run; no training labels or model promotion generated.',
            'complete_building_verification': 'Not established by this pilot.',
        }
        quality.update(quality_status='draft_unverified', pilot_readiness=readiness)
        world = None
        if quality['voxel_records']:
            world = export_world(staging / 'voxels.jsonl', staging, quality, job['name'], max_blocks=4_000_000)
            quality['world'] = world
        comparison = None
        if world:
            from .pilot_comparison import write as compare_placement
            comparison = compare_placement(staging, quality, world)
        _write(staging / 'quality-report.json', quality)
        report = {
            'version': VERSION, 'name': job['name'],
            'status': 'completed_draft' if world else 'awaiting_exportable_geometry',
            'inputs': inputs, 'bbox': config['bbox'], 'world': world, 'readiness': readiness,
            'generated_voxel_records_by_kind': dict(sorted(kinds.items())),
            'geographic_features': [{'id': feature['id'], 'emitted_voxel_records': counts[feature['id']],
                                     'status': 'voxelized_for_export' if counts[feature['id']] else 'no_voxels'}
                                    for feature in collection['features']],
            'terrain': quality['terrain'], 'issues': quality['issues'],
            'placement_comparison': comparison,
            'generation_errors': sum(issue.get('severity') == 'error' for issue in quality['issues']),
            'validation': {'native_readback': world['round_trip_validation'] if world else 'not_run',
                           'minecraft_visual_inspection': 'not_performed',
                           'repeatability': 'Compare input hashes, voxel SHA256 and readiness across fresh outputs; package bytes may differ.'},
        }
        description = [job['name'], '', 'Status: ' + report['status'], '',
                       'Open park.mcworld in Minecraft Bedrock to inspect this draft.' if world else
                       'No world was exported because no exportable voxel records were generated.', '',
                       'Planning components voxelized: ' + str(planning_count),
                       'Pending planning review tasks: ' + str(len(tasks)),
                       'Planning records withheld or producing no voxels: ' + str(readiness['planning_components_withheld']), '',
                       'Reported generation errors: ' + str(report['generation_errors']),
                       'See pilot-report.json for missing evidence and quality-report.json for generation decisions.',
                       'Open placement-comparison.svg to compare projected source boundaries and saved block materials.' if comparison else '',
                       'Voxel counts describe inputs to composition; overlapping records can share the same final block.',
                       'Native block readback does not establish visual fidelity, a complete building or surveyed accuracy.']
        if world:
            description += ['', 'Minecraft spawn: ' + ', '.join(map(str, world['spawn']))]
        for task in tasks:
            description += ['', task['title'] + ':', *['- ' + value for value in task['required_evidence']]]
        (staging / 'README.txt').write_text('\n'.join(description) + '\n', encoding='utf-8')
        for path, expected in pins:
            if _sha(path) != expected:
                raise ValueError('Pilot input changed during generation: ' + path.name)
        artifacts = ['inputs.json', 'resolved-config.json', 'voxels.jsonl', 'features-local.geojson',
                     'quality-report.json', 'README.txt'] + (['park.mcworld'] if world else [])
        if comparison:
            artifacts += ['placement-comparison.json', 'placement-comparison.svg']
        report['output_sha256'] = {name: _sha(staging / name) for name in artifacts}
        _write(staging / 'pilot-report.json', report)
        staging.rename(output)
        return report
    except Exception as error:
        (staging / 'park.mcworld').unlink(missing_ok=True)
        shutil.rmtree(staging / 'bedrock-world', ignore_errors=True)
        _write(staging / 'failure.json', {'status': 'failed', 'error': str(error)})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = run(args.job, args.output)
    print(json.dumps({'status': report['status'], 'world': str(args.output / 'park.mcworld') if report['world'] else None,
                      'planning_components_voxelized': report['readiness']['planning_components_voxelized'],
                      'generation_errors': report['generation_errors'],
                      'pending_review_tasks': len(report['readiness']['pending_review_tasks'])}))


if __name__ == '__main__':
    main()
