"""Source-pinned requirements for reconstruction; never authorizes geometry."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from .generation_cycles import atomic_json, file_hash

VERSION = 'reconstruction-evidence-queue-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def build(area_id, pages, *, max_tasks=10000):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', area_id):
        raise ValueError('Bounded area identity required')
    if type(max_tasks) is not int or not 1 <= max_tasks <= 100000:
        raise ValueError('Bounded evidence task budget required')
    tasks = {}; source_pages = []; seen = set(); exhausted = False

    def add(kind, target, proof, requirement, searches, dependencies=()):
        nonlocal exhausted
        identity = {'area_id': area_id, 'kind': kind, 'target': target}
        identifier = digest(identity)
        if identifier not in tasks and len(tasks) >= max_tasks:
            exhausted = True
            return identifier
        tasks[identifier] = {**identity, 'id': identifier, 'status': 'missing_evidence',
            'proof': proof, 'requirement': requirement, 'search_terms': searches,
            'depends_on': sorted(dependencies), 'physical_identity_verified': False,
            'geometry_export_authorized': False}
        return identifier

    for index, page in enumerate(pages):
        if index >= 10000:
            raise ValueError('Bounded evidence page inventory required')
        sha = page['document_sha256']; number = page['page']
        if not re.fullmatch('[0-9a-f]{64}', sha) or type(number) is not int or not 1 <= number <= 1000:
            raise ValueError('Pinned source page identity required')
        key = (sha, number)
        if key in seen:raise ValueError('Unique source evidence pages required')
        seen.add(key)
        pin = digest(page)
        source_pages.append({'document_sha256': sha, 'page': number, 'record_sha256': pin})
        target = {'document_sha256': sha, 'page': number}
        proof = {'page_record_sha256': pin, 'path': '/'}
        scope = add('view_scope', target, proof,
            'Separate the relevant view and support its own scale/state before measurement.',
            ['existing site plan', 'ground floor plan', 'drawing view scale', 'key plan'])
        registration = add('horizontal_registration', target, proof,
            'Establish physical landmark identities, independent checkpoints and a validated placement domain.',
            ['survey control', 'topographical survey', 'site location plan'])
        perimeter = page.get('wall_perimeter_coverage', {})
        if perimeter.get('status') == 'source_region_perimeter_coverage_only':
            if perimeter['document_sha256'] != sha or perimeter['page'] != number:
                raise ValueError('Perimeter evidence must belong to the original page')
            traces = perimeter['region_traces']
            if len(traces) > 20000:raise ValueError('Bounded perimeter requirements required')
            if len({t['face_id'] for t in traces}) != len(traces):
                raise ValueError('Unique source region requirements required')
            for position, trace in enumerate(traces):
                region_target = {**target, 'source_region_id': trace['face_id']}
                region_proof = {'page_record_sha256': pin,
                    'path': f'/wall_perimeter_coverage/region_traces/{position}',
                    'source_face_sha256': trace['source_face_sha256']}
                segments = trace['segments']
                if len(segments)>100000:raise ValueError('Bounded source boundary required')
                unsupported = [{'ring_index': s['ring_index'], 'segment_index': s['segment_index'],
                    'ring_role': s['ring_role'], 'status': s['status']} for s in segments
                    if s['status'] != 'whole_source_segment_paired']
                exterior = add('physical_exterior', region_target, region_proof,
                    'Identify the physical exterior across plans/elevations; a source region ring is not a building footprint.',
                    ['existing floor plan', 'existing roof plan', 'courtyard elevation', 'building section'], [scope])
                if exterior in tasks:
                    tasks[exterior]['unpaired_source_segments'] = unsupported
                    tasks[exterior]['source_hole_count'] = trace['hole_count']
                    tasks[exterior]['paired_boundary_fraction'] = trace['coverage_fraction']
                correspondence = add('plan_elevation_correspondence', region_target, region_proof,
                    'Bind the same physical wing, walls, openings and roof between source views.',
                    ['existing elevation', 'section', 'archway', 'roof plan'], [scope, exterior])
                add('relative_dimensions', region_target, region_proof,
                    'Bind printed dimensions and floor/eaves/ridge levels to the matched physical component.',
                    ['dimensioned section', 'floor level', 'eaves level', 'ridge level'], [correspondence])
                add('vertical_datum', region_target, region_proof,
                    'Resolve the absolute floor datum and terrain contact without assuming drawing zero equals terrain.',
                    ['survey benchmark', 'finished floor level', 'Ordnance Datum', 'site levels'], [registration])
        if exhausted:break
    if exhausted:tasks = {}
    ordered = sorted(tasks.values(), key=lambda t: t['id'])
    for task in ordered:
        if any(i not in tasks for i in task['depends_on']):raise ValueError('Complete evidence dependencies required')
    return {'version': VERSION, 'area_id': area_id,
        'status': 'evidence_budget_withheld' if exhausted else 'missing_evidence_worklist',
        'source_pages': sorted(source_pages, key=lambda p: (p['document_sha256'], p['page'])),
        'tasks': ordered, 'max_tasks': max_tasks, 'counts': dict(Counter(t['kind'] for t in ordered)),
        'world_geometry_additions': 0, 'geometry_export_authorized': False,
        'limitations': ['Source region IDs identify diagnostic candidates, not physical building objects.',
            'Search terms are a worklist; discovery, download and evidence acceptance are separate stages.',
            'No task status establishes dimensions, datum, registration or reconstruction completeness.']}


def run(area_id, architecture_directory, output):
    """Reuse an unchanged pinned worklist; reject edited inputs or outputs."""
    architecture_directory = Path(architecture_directory); output = Path(output)
    report_path = architecture_directory / 'architectural-report.json'
    pages_path = architecture_directory / 'architectural-pages.jsonl'
    report = json.loads(report_path.read_text())
    if file_hash(pages_path) != report['output_sha256']:
        raise ValueError('Architectural evidence output changed')
    contract = {'version': VERSION, 'area_id': area_id,
        'architecture_report_sha256': file_hash(report_path), 'source_pages_sha256': file_hash(pages_path)}
    if output.exists():
        retained = json.loads((output / 'queue-report.json').read_text())
        if retained['contract'] != contract:raise ValueError('Evidence queue inputs changed; use a fresh run')
        if file_hash(output / 'missing-evidence.json') != retained['output_sha256']:
            raise ValueError('Evidence queue output changed')
        return {**retained, 'run_tasks': 0, 'reused_tasks': retained['task_count']}
    with pages_path.open() as stream:
        worklist = build(area_id, (json.loads(line) for line in stream))
    if file_hash(report_path) != contract['architecture_report_sha256'] or file_hash(pages_path) != contract['source_pages_sha256']:
        raise ValueError('Architectural evidence changed during queue preparation')
    output.mkdir(parents=True)
    atomic_json(output / 'missing-evidence.json', worklist)
    retained = {'contract': contract, 'status': worklist['status'], 'counts': worklist['counts'],
        'task_count': len(worklist['tasks']), 'output_sha256': file_hash(output / 'missing-evidence.json'),
        'world_geometry_additions': 0, 'geometry_export_authorized': False}
    atomic_json(output / 'queue-report.json', retained)
    return {**retained, 'run_tasks': retained['task_count'], 'reused_tasks': 0}
