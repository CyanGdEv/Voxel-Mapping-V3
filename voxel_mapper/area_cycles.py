"""Automatic, checkpointed area handoffs with ten disjoint chunk workers."""
import argparse
import json
import os
import re
import shutil
from pathlib import Path

from .area_reconstruction import run
from .generation_cycles import CyclePlan, atomic_json, file_hash
from .generation_cycle_export import worker, worker_directory, safe_file

VERSION = 'resort-area-cycles-v6'

def load(job):
    job = Path(job).resolve()
    config = json.loads(job.read_text())
    ids = [a['id'] for a in config['areas']]
    if not 1 <= len(ids) <= 64 or len(set(ids)) != len(ids) or any(
            not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', i) for i in ids):
        raise ValueError('Unique bounded area identifiers required')
    root = (job.parent / config['work_directory']).resolve()
    contract = {'version': VERSION, 'job_sha256': file_hash(job),
        'catalogue_sha256': file_hash(job.parent / config['catalogue']),
        'supplements': {p: file_hash(job.parent / p) for p in config.get('supplemental_catalogues', [])},
        'recipes': {a['id']: file_hash(job.parent / a['reconstruction_job'])
                    for a in config['areas'] if a.get('reconstruction_job')}}
    if config.get('initial_base_world'):
        if file_hash(job.parent / config['initial_base_world'] / 'park.mcworld') != config.get('initial_base_sha256'):
            raise ValueError('Initial area baseline checksum mismatch')
    from .automatic_reconstruction import input_contract
    automatic_contract = input_contract(config, lambda p: (job.parent / p).resolve())
    if automatic_contract is not None:
        contract['automatic_reconstruction'] = automatic_contract
    from .registration_qualification import input_contract as qualification_contract
    frames = qualification_contract(config, lambda p: (job.parent / p).resolve())
    if frames is not None:
        contract['registration_qualification'] = frames
    from .survey_landmark_discovery import input_contract as station_contract
    stations = station_contract(config, lambda p: (job.parent / p).resolve())
    if stations is not None:
        contract['survey_landmark_discovery'] = stations
    path = root / 'auto-cycle-state.json'
    state = json.loads(path.read_text()) if path.exists() else {
        'contract': contract, 'cursor': 0, 'areas': {}, 'status': 'running',
        'published_cycles': 0, 'active_cycle': None}
    if state['contract'] != contract:
        raise ValueError('Automatic area inputs changed; use a fresh work directory')
    return job, config, root, path, state


def save(path, state):
    atomic_json(path, state)
    summary = ['# Automatic resort cycles', '', f"Status: {state['status']}", '',
               f"Verified native cycles published: {state['published_cycles']}", '',
               '| Area | Result |', '|---|---|']
    summary += [f"| {area} | {r['status']} |" for area, r in state['areas'].items()]
    summary += ['', 'Blocked areas remain incomplete. Planning association and PDF extraction are not world generation.', '']
    (path.parent / 'auto-cycle-summary.md').write_text('\n'.join(summary))


def prepare(job, publication_budget=10000):
    """Skip recorded blockers, but finish every ready area's chunks before advancing."""
    job, config, root, path, state = load(job)
    if type(publication_budget) is not int or not 1 <= publication_budget <= 10000:
        raise ValueError('Bounded positive publication budget required')
    if state['status'] == 'paused_cycle_budget' and state['published_cycles'] < publication_budget:
        state['status'] = 'running'
    if (state['status'] == 'running' and state['cursor'] < len(config['areas'])
            and state['published_cycles'] >= publication_budget):
        state['status'] = 'paused_cycle_budget'
        save(path, state)
        return state
    if state['status'] != 'running':
        return state
    # Recover publication if a process stopped between the native commit and
    # controller checkpoint. Never dispatch that completed cycle twice.
    if state.get('active_cycle'):
        receipt = state['active_cycle']
        plan = CyclePlan(receipt['plan'])
        try:
            plan.validate_inputs(receipt['geometry'], receipt['base_world'])
            if plan.identity != receipt['plan_identity']:
                raise ValueError('Prepared cycle identity changed')
            committed = any(c['id'] == receipt['cycle'] and c['status'] == 'complete'
                            for c in plan.report()['cycles'])
        finally:
            plan.close()
        if committed:
            entry = run(job, 'finish', 1, receipt['area_id'])['areas'][receipt['area_id']]
            record_assembly(path, state, receipt, entry)
            if state['cursor'] < len(config['areas']) and state['published_cycles'] >= publication_budget:
                state['status'] = 'paused_cycle_budget'
                save(path, state)
                return state
    while state['cursor'] < len(config['areas']):
        area = config['areas'][state['cursor']]
        try:
            result = run(job, 'prepare', 1, area['id'])
            entry = result['areas'][area['id']]
            state['areas'][area['id']] = {k: entry[k] for k in (
                'status', 'missing_components', 'missing_component_ids', 'latest_preview',
                'world_sha256', 'base_world', 'document_records', 'automatic_reconstruction') if k in entry}
            state['areas'][area['id']]['blockers'] = [label for key, label in (
                ('reconstruction_job', 'No source-bound reconstruction recipe'),
                ('bounds', 'No accepted area boundary'),
                ('required_component_ids', 'No bound physical component inventory'))
                if not area.get(key)
                and not (key == 'reconstruction_job' and entry.get('reconstruction_recipe_configured'))
                and not (key == 'required_component_ids' and entry.get('component_inventory_bound'))]
            automatic = entry.get('automatic_reconstruction', {})
            if automatic.get('status') not in (None, 'recipe_ready'):
                state['areas'][area['id']]['blockers'].append(automatic['status'])
            if automatic.get('status') == 'recipe_ready' and not area.get('required_component_ids'):
                state['areas'][area['id']]['blockers'].append('Complete area inventory remains unverified')
            if entry['status'] == 'awaiting_applications':
                state['areas'][area['id']]['blockers'].append('No associated planning applications')
            if entry['status'] == 'ready_for_cycle':
                plan_path = root / area['id'] / 'cycles.sqlite'
                plan = CyclePlan(plan_path)
                try:
                    inputs = entry['generation_inputs']
                    plan.validate_inputs(inputs['geometry'], inputs['base_world'])
                    cycle = plan.next_cycle()
                    if cycle is None:
                        raise ValueError('Ready area has no pending cycle')
                    state['active_cycle'] = {'area_id': area['id'], 'cycle': cycle,
                        'plan': str(plan_path), 'plan_identity': plan.identity, **inputs}
                finally:
                    plan.close()
                save(path, state)
                return state
        except Exception as exc:
            state['areas'][area['id']] = {'status': 'area_error', 'error': str(exc)}
        # A completed partial preview is retained, but never marked complete.
        state['active_cycle'] = None
        state['cursor'] += 1
        save(path, state)
    state['status'] = ('complete' if all(r['status'] == 'complete' for r in state['areas'].values())
                       else 'completed_with_blockers')
    save(path, state)
    return state


def active(job):
    _, _, _, _, state = load(job)
    receipt = state.get('active_cycle')
    if not receipt:
        raise ValueError('No prepared area cycle')
    plan = CyclePlan(receipt['plan'])
    try:
        plan.validate_inputs(receipt['geometry'], receipt['base_world'])
        if plan.identity != receipt['plan_identity'] or plan.next_cycle() != receipt['cycle']:
            raise ValueError('Prepared cycle identity changed or was already assembled')
    finally:
        plan.close()
    return receipt


def produce(job, number):
    receipt = active(job)
    plan = CyclePlan(receipt['plan'])
    try:
        return worker(plan, receipt['geometry'], receipt['cycle'], number,
                      worker_directory(receipt['output'], receipt['cycle'], number))
    finally:
        plan.close()


def collect(job, source):
    receipt = active(job)
    for number in range(10):
        origin = Path(source) / f'area-cycle-worker-{number}'
        target = worker_directory(receipt['output'], receipt['cycle'], number)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(origin, target)


def record_assembly(path, state, receipt, entry):
    preview = entry.get('latest_preview')
    if not preview or not any(c['id'] == receipt['cycle'] and c['status'] == 'complete'
                             for c in entry['chunk_cycles']['cycles']):
        raise ValueError('Assembler did not verify the prepared native cycle')
    if preview['cycle'] != receipt['cycle'] or file_hash(
            safe_file(receipt['output'], preview['file'])) != preview['sha256']:
        raise ValueError('Verified area preview changed')
    state['areas'][receipt['area_id']] = {k: entry[k] for k in (
        'status', 'missing_components', 'missing_component_ids', 'latest_preview',
        'world_sha256', 'base_world', 'document_records', 'automatic_reconstruction') if k in entry}
    state['latest_preview'] = {**preview, 'area_id': receipt['area_id'],
        'download_artifact': f"area-preview-{receipt['area_id']}-cycle-{receipt['cycle']:04d}"}
    atomic_json(safe_file(receipt['output'], preview['file']).parent / 'area-cycle-preview-report.json',
                state['latest_preview'])
    state['published_cycles'] += 1
    state['active_cycle'] = None
    if entry['status'] in ('complete', 'partial_area_preview'):
        state['cursor'] += 1
    save(path, state)
    return state


def assemble(job):
    receipt = active(job)
    job, config, root, path, state = load(job)
    # Missing/corrupt workers fail before the single native writer publishes.
    result = run(job, 'assemble', 1, receipt['area_id'])
    return record_assembly(path, state, receipt, result['areas'][receipt['area_id']])


def run_local(job, max_cycles=1):
    if type(max_cycles) is not int or not 1 <= max_cycles <= 10000:
        raise ValueError('Bounded positive cycle count required')
    for _ in range(max_cycles):
        state = prepare(job)
        if not state.get('active_cycle'):
            return state
        for number in range(10):
            produce(job, number)
        assemble(job)
    return load(job)[-1]


def validate_bundle(job, root):
    """Actions input paths must survive transfer to the same runner workspace."""
    root = Path(root).resolve()
    job = Path(job).resolve()
    if not job.is_relative_to(root):
        raise ValueError('Area job must be inside its input bundle')
    keys = {'catalogue', 'work_directory', 'initial_base_world', 'reconstruction_job',
            'manifest', 'terrain_config', 'base_world', 'feature_records', 'references',
            'reviews', 'documents', 'file', 'model', 'placement', 'cache', 'sheets',
            'bindings', 'mentions', 'candidates', 'corpus', 'feature_reviews', 'path',
            'source_directories', 'supplemental_catalogues'}
    visited = set()
    def inspect(path):
        if path in visited:
            return
        visited.add(path)
        def walk(value, key=None):
            if isinstance(value, dict):
                for k, v in value.items():
                    walk(v, k)
            elif isinstance(value, list):
                for v in value:
                    walk(v, key)
            elif key in keys and isinstance(value, str):
                target = (path.parent / value).resolve()
                if Path(value).is_absolute() or not target.is_relative_to(root):
                    raise ValueError('Nonportable Actions input path: ' + value)
                if target.is_file() and target.suffix == '.json':
                    inspect(target)
        walk(json.loads(path.read_text()))
    inspect(job)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare', 'worker', 'collect', 'assemble', 'local'])
    parser.add_argument('--job', required=True)
    parser.add_argument('--worker', type=int)
    parser.add_argument('--source')
    parser.add_argument('--max-cycles', type=int, default=1)
    parser.add_argument('--bundle-root')
    parser.add_argument('--max-publications', type=int, default=10000)
    args = parser.parse_args()
    if args.bundle_root:
        validate_bundle(args.job, args.bundle_root)
    if args.stage == 'prepare':
        state = prepare(args.job, args.max_publications)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as out:
                out.write('ready=' + str(bool(state.get('active_cycle'))).lower() + '\n')
    elif args.stage == 'worker':
        if args.worker is None:
            parser.error('worker requires --worker')
        produce(args.job, args.worker)
        state = load(args.job)[-1]
        if os.environ.get('GITHUB_OUTPUT'):
            r = active(args.job)
            with open(os.environ['GITHUB_OUTPUT'], 'a') as out:
                out.write('directory=' + str(worker_directory(r['output'], r['cycle'], args.worker)) + '\n')
    elif args.stage == 'collect':
        if not args.source:
            parser.error('collect requires --source')
        collect(args.job, args.source)
        state = load(args.job)[-1]
    elif args.stage == 'assemble':
        state = assemble(args.job)
        if os.environ.get('GITHUB_OUTPUT'):
            preview = state['latest_preview']
            _, _, root, _, _ = load(args.job)
            directory = root / preview['area_id'] / 'output' / Path(preview['file']).parent
            with open(os.environ['GITHUB_OUTPUT'], 'a') as out:
                out.write('preview_directory=' + str(directory) + '\n')
                out.write(f"preview_artifact=area-preview-{preview['area_id']}-cycle-{preview['cycle']:04d}\n")
    else:
        state = run_local(args.job, args.max_cycles)
    print(json.dumps(state, indent=2))


if __name__ == '__main__':
    main()
