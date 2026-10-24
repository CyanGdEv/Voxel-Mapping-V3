"""Source-group coverage diagnostics and independent intake requests, not scores."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path

from .building_spec import digest
from .study_component_learning import read_dataset

VERSION = 'study-training-coverage-v1'
MAX_MIN_GROUPS = 64


def _identities(rows):
    site, named, footprints, other = set(), set(), set(), set()
    for row in rows:
        identifier = row['building_id']
        if row.get('entity_type') == 'site_detail' or identifier.startswith('alton-site-details-'):
            site.add(identifier)
        elif identifier.startswith('planning-building-'):
            footprints.add(identifier)
        elif identifier.startswith(('wickerman-', 'mutiny-', 'prospect-')):
            named.add(identifier)
        else:
            other.add(identifier)
    # Categories are declared catalogue identity scopes, not verified buildings.
    return {'named_study_building_ids': sorted(named),
        'additional_reviewed_building_footprint_ids': sorted(footprints),
        'site_detail_context_ids': sorted(site), 'unclassified_identity_ids': sorted(other)}


def report(directory, min_groups=3):
    """Verify all dataset assets before counting source-local labels and groups."""
    if type(min_groups) is not int or not 2 <= min_groups <= MAX_MIN_GROUPS:
        raise ValueError('Choose an independent acquisition target of two to 64 groups')
    manifest, rows, unused_features, manifest_pin = read_dataset(directory)
    del unused_features  # Image features are never used by this diagnostic.
    classes = sorted({r['kind'] for r in rows})
    grouped = {g['group_id']: g for g in manifest['groups']}
    active = sorted({r['group_id'] for r in rows})
    by_class, group_rows = {}, []
    for kind in classes:
        members = [r for r in rows if r['kind'] == kind]
        ids = sorted({r['group_id'] for r in members})
        by_class[kind] = {'examples': len(members), 'source_group_ids': ids,
            'source_groups': len(ids), 'source_sha256': sorted({r['source']['document_sha256'] for r in members}),
            'identity_ids': sorted({r['building_id'] for r in members}),
            'target_roles': dict(sorted(Counter(r.get('target_role', 'unspecified') for r in members).items())),
            'additional_independent_groups_requested': max(0, min_groups-len(ids)),
            'meets_requested_group_count': len(ids) >= min_groups}
    unknown_cases = []
    for group_id in active:
        members = [r for r in rows if r['group_id'] == group_id]
        absent = sorted({r['kind'] for r in members if by_class[r['kind']]['source_groups'] == 1})
        unknown_ids = sorted(r['id'] for r in members if r['kind'] in absent)
        group_rows.append({**grouped[group_id], 'eligible_examples': len(members),
            'kinds': dict(sorted(Counter(r['kind'] for r in members).items())),
            'geometry_kinds': dict(sorted(Counter(r.get('target_geometry', {}).get('type', 'unspecified') for r in members).items()))})
        if unknown_ids:
            unknown_cases.append({'held_out_group_id': group_id, 'unseen_in_training_classes': absent,
                'record_ids': unknown_ids, 'examples': len(unknown_ids),
                'reason': 'Every reviewed example of these classes belongs to this held-out source-connected group.'})
    identities = _identities(rows)
    total_unknown = sum(c['examples'] for c in unknown_cases)
    missing_surfaces = [kind for kind in ('path', 'plaza') if kind not in by_class]
    requests = []
    for kind in missing_surfaces:
        requests.append({'priority': 1, 'kind': kind, 'request_type': 'missing_component_class',
            'current_source_groups': 0, 'additional_independent_groups_requested': min_groups,
            'required_evidence': ['Original PDF hash/page and unchanged source crop.',
                'Explicitly reviewed source-local footprint and path or plaza role.',
                'Different building/site and no shared PDF with another intake group.'],
            'note': 'Existing reviewed paving must retain its actual role; a surface or road is not automatically a plaza.'})
    for kind, coverage in sorted(by_class.items(), key=lambda item: (item[1]['source_groups'], -item[1]['examples'], item[0])):
        if not coverage['additional_independent_groups_requested']:
            continue
        requests.append({'priority': 2 if coverage['source_groups'] == 1 else 3,
            'kind': kind, 'request_type': 'independent_component_examples',
            'current_source_groups': coverage['source_groups'],
            'additional_independent_groups_requested': coverage['additional_independent_groups_requested'],
            'required_evidence': ['Reviewed same-task drawing geometry with uncertainty retained.',
                'New physical identity and source PDF group, not another crop, scale or variant of an existing building.',
                'Keep all related views and shared PDFs together for held-out evaluation.'],
            'note': 'Group count is an acquisition target, not a prediction-quality or readiness guarantee.'})
    requests.extend([
        {'priority': 4, 'kind': 'metric_component_height', 'request_type': 'new_training_task',
            'additional_independent_groups_requested': min_groups,
            'required_evidence': ['Source-bound figured height or explicitly qualified relative measurement.',
                'The same component, its floor/reference datum and uncertainty across views.'],
            'note': 'Existing source-pixel height traces do not provide a general metric 3D height target.'},
        {'priority': 4, 'kind': 'multi_view_correspondence', 'request_type': 'new_training_task',
            'additional_independent_groups_requested': min_groups,
            'required_evidence': ['Reviewed plan/elevation/section links to the same component.',
                'Original view coordinates, scale/revision and unresolved alternatives.',
                'Different buildings and PDF groups reserved for evaluation.'],
            'note': 'The current crop labels do not supervise full 3D assembly or unknown-view matching.'},
    ])
    result = {'version': VERSION, 'status': 'coverage_diagnostics_only',
        'dataset_id': manifest['id'], 'dataset_manifest_sha256': manifest_pin,
        'dataset_version': manifest['version'], 'dataset_kind': manifest['dataset_kind'],
        'acquisition_target_min_groups': min_groups, 'group_target_is_readiness_guarantee': False,
        'summary': {'eligible_component_examples': len(rows), 'source_connected_groups': len(active),
            'pinned_source_document_identities': len({r['source']['document_sha256'] for r in rows}),
            'component_classes': len(classes), 'named_study_building_identities': len(identities['named_study_building_ids']),
            'additional_reviewed_building_footprint_identities': len(identities['additional_reviewed_building_footprint_ids']),
            'site_detail_context_identities': len(identities['site_detail_context_ids']),
            'unclassified_identities': len(identities['unclassified_identity_ids']),
            'single_group_classes': sum(c['source_groups'] == 1 for c in by_class.values()),
            'classes_below_requested_group_count': sum(c['source_groups'] < min_groups for c in by_class.values())},
        'identities': identities, 'classes': by_class, 'source_groups': group_rows,
        'single_group_classes': sorted(k for k, c in by_class.items() if c['source_groups'] == 1),
        'leave_one_group_out_class_availability': {
            'examples_with_unseen_training_class': total_unknown,
            'examples_with_class_available_in_training': len(rows)-total_unknown,
            'unseen_class_cases': unknown_cases,
            'scope': 'Label availability only; no accuracy, model features, predictions or physical geometry are evaluated.'},
        'task_coverage': {'missing_path_plaza_classes': missing_surfaces,
            'source_pixel_height_trace_examples': sum(r.get('target_role') == 'elevation_height_trace' for r in rows),
            'metric_3d_height_task': 'not_supervised_by_source_crop_classification_schema',
            'multi_view_correspondence_task': 'not_supervised_by_source_crop_classification_schema',
            'complete_building_generation': 'not_assessed'},
        'prioritized_independent_intake_requests': requests,
        'production_eligible': False, 'world_placement_eligible': False, 'physical_geometry_verified': False,
        'training_labels_generated': 0, 'model_weights_updated': False,
        'limitations': ['Component rows, crops and mesh variants are not independent buildings.',
            'Identity labels describe retained study/footprint scope; they do not establish complete or as-built reconstruction.',
            'A shared PDF or building identity connects the whole group even when many crops or named buildings are present.',
            'The strict reader verifies packaged data assets; this diagnostic does not reacquire or independently authenticate the original PDFs.',
            'Class coverage and requested acquisition counts do not establish learned quality, 3D accuracy or autonomous readiness.']}
    result['id'] = digest(result)
    return result


def write(directory, output, min_groups=3):
    """Write a fresh portable JSON report without replacing any existing file."""
    output = Path(output)
    if output.exists():
        raise ValueError('Fresh training coverage report path required')
    value = report(directory, min_groups)
    body = json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n'
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation retains the fresh-output guarantee under concurrent use.
    created = False
    try:
        with output.open('x', encoding='utf-8', newline='\n') as stream:
            created = True
            stream.write(body); stream.flush(); os.fsync(stream.fileno())
    except BaseException:
        if created:
            output.unlink(missing_ok=True)
        raise
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--min-groups', type=int, default=3)
    args = parser.parse_args()
    result = write(args.dataset, args.output, args.min_groups)
    print(json.dumps({'status': result['status'], 'id': result['id'], **result['summary']}))


if __name__ == '__main__':
    main()
