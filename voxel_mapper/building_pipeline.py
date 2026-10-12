"""CLI for shared building studies, candidate selection and reviewed learning."""
import argparse
import hashlib
import json
from pathlib import Path
from . import building_learning as learning
from .building_spec import build, from_study, digest
from .generation_cycles import atomic_json
from .study_mesh_export import write_glb


def _read(path):
    path = Path(path)
    if path.stat().st_size > 100000000:
        raise ValueError('Building input file budget exceeded')
    return json.loads(path.read_text())


def run(job, output, model=None, exploratory=False):
    """Build independent local candidates; never insert them into a park world."""
    if job.get('version') != 'building-batch-v1':
        raise ValueError('Versioned building batch required')
    buildings = job.get('buildings')
    if not isinstance(buildings, list) or not 1 <= len(buildings) <= 1000:
        raise ValueError('Bounded building batch required')
    native_mode=job.get('native_output','none')
    if native_mode not in ('none','cells','world'):raise ValueError('Supported native output mode required')
    quality_policy=job.get('native_quality','report')
    if quality_policy not in ('report','require_pass'):raise ValueError('Supported native quality policy required')
    model = model or learning.baseline(); learning.validate_model(model)
    if model['iteration'] > 0 and not model['production_eligible'] and not exploratory:
        raise ValueError('Unpromoted learned checkpoint requires explicit exploratory mode')
    root = Path(output)
    if root.exists():
        raise ValueError('Fresh output directory required; existing results are immutable')
    ids = [b.get('building_id') for b in buildings]
    if any(not isinstance(b, str) or not b for b in ids) or len(set(ids)) != len(ids):
        raise ValueError('Unique building IDs required')
    # Freeze the data and model contract before generating any geometry.
    root.mkdir(parents=True)
    contract = {'job_sha256': digest(job), 'model_sha256': model['artifact_sha256'],
                'exploratory': exploratory, 'world_placement_eligible': False}
    atomic_json(root/'contract.json', contract)
    results = []
    for index, building in enumerate(buildings):
        directory = root/f'building-{index:04d}'; directory.mkdir()
        result = {'building_id': building['building_id'], 'status': 'awaiting_eligible_candidate',
                  'park_world_blocks_added': 0}
        try:
            candidates = building['candidates']
            ranking = learning.rank(candidates, model)
            atomic_json(directory/'ranking.json', ranking)
            if ranking['selected_id'] is not None:
                # A ranker cannot authorize invalid geometry. If the preferred
                # candidate fails construction, retain the failure and try the next.
                failures = []
                for row in ranking['ranking']:
                    if not row['eligible_local_candidate']:
                        continue
                    candidate = next(c for c in candidates if c['id'] == row['id'])
                    try:
                        if candidate['spec']['building_id'] != building['building_id']:
                            raise ValueError('Candidate belongs to a different building')
                        geometry = build(candidate['spec'])
                        if native_mode!='none' or quality_policy=='require_pass':
                            from .building_native import compile_spec
                            _,native_audit=compile_spec(candidate['spec'])
                            structural=native_audit['structural_review']
                            if quality_policy=='require_pass' and structural['status']!='passed_native_checks':
                                failures.append({'candidate_id':row['id'],'reason':'native_structural_checks_failed','structural_review':structural})
                                continue
                    except (ValueError, KeyError, TypeError) as error:
                        failures.append({'candidate_id': row['id'], 'reason': str(error)})
                        continue
                    atomic_json(directory/'building-spec.json', candidate['spec'])
                    atomic_json(directory/'model.json', geometry)
                    exported = write_glb(geometry, directory/'model.glb')
                    if native_mode!='none':
                        from .building_native import export_preview
                        native_report=export_preview(candidate['spec'],directory/'native',world=native_mode=='world')
                        result['native_output']={'mode':native_mode,'surface_cells':native_report['native_audit']['surface_cells'],
                            'protected_air_verified':native_report['native_audit']['protected_air_verified'],
                            'world_exported':'world' in native_report,
                            'structural_review':native_report['native_audit']['structural_review']}
                    result.update(status='local_preview_built', selected_id=row['id'],
                                  spec_sha256=geometry['spec_sha256'], export=exported,
                                  world_placement_eligible=False)
                    break
                if result['status'] != 'local_preview_built': result['status'] = 'awaiting_valid_geometry'
                result['construction_failures'] = failures
        except (ValueError, KeyError, TypeError) as error:
            result.update(status='invalid_building_input', reason=str(error))
        atomic_json(directory/'result.json', result); results.append(result)
    report = {'version': 'building-batch-v1', 'contract': contract, 'buildings': results,
              'built': sum(r['status'] == 'local_preview_built' for r in results),
              'park_world_blocks_added': 0,
              'training_labels_generated': 0,
              'feedback_policy': 'Construction success is not an independently reviewed correctness label.'}
    atomic_json(root/'report.json', report)
    return report



def iterate(job, feedback, split, output, parent=None):
    """Train, evaluate, choose the eligible checkpoint and build a pinned batch."""
    parent = parent or learning.baseline()
    learning.validate_model(parent)
    if parent['iteration'] > 0 and not parent['production_eligible']:
        raise ValueError('Iteration parent must be the last eligible model or baseline')
    if feedback.get('version') != 'building-feedback-v1':
        raise ValueError('Versioned reviewed feedback required')
    root = Path(output)
    if root.exists(): raise ValueError('Fresh iteration directory required')
    candidate = learning.train(feedback['records'], split['training_buildings'],
                               split['evaluation_buildings'], parent)
    selected = candidate if candidate['production_eligible'] else parent
    root.mkdir(parents=True)
    atomic_json(root/'candidate-model.json', candidate)
    atomic_json(root/'selected-model.json', selected)
    report = run(job, root/'batch', selected)
    iteration = {'version': 'building-learning-iteration-v1',
                 'feedback_sha256': digest(feedback), 'split_sha256': digest(split),
                 'job_sha256': digest(job), 'parent_sha256': parent['artifact_sha256'],
                 'candidate_sha256': candidate['artifact_sha256'],
                 'selected_sha256': selected['artifact_sha256'],
                 'promoted': candidate['production_eligible'],
                 'evaluation': candidate['evaluation'], 'built': report['built'],
                 'park_world_blocks_added': 0, 'training_labels_generated': 0}
    atomic_json(root/'iteration.json', iteration)
    return iteration


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    migrate = commands.add_parser('import-study')
    migrate.add_argument('--model', required=True); migrate.add_argument('--building-id', required=True)
    migrate.add_argument('--output', required=True); migrate.add_argument('--display-floor',action='store_true')
    train = commands.add_parser('train')
    train.add_argument('--feedback', required=True); train.add_argument('--split', required=True)
    train.add_argument('--parent'); train.add_argument('--output', required=True)
    batch = commands.add_parser('batch')
    batch.add_argument('--job', required=True); batch.add_argument('--model')
    batch.add_argument('--exploratory', action='store_true'); batch.add_argument('--output', required=True)
    iteration = commands.add_parser('iterate')
    for key in ('job', 'feedback', 'split', 'output'): iteration.add_argument('--'+key, required=True)
    iteration.add_argument('--parent')
    feed = commands.add_parser('prepare-feed')
    feed.add_argument('--config', required=True); feed.add_argument('--output', required=True)
    reviews = commands.add_parser('collect-feedback')
    reviews.add_argument('--queue', required=True); reviews.add_argument('--decisions', required=True); reviews.add_argument('--output', required=True)
    native = commands.add_parser('compile-native')
    native.add_argument('--spec',required=True); native.add_argument('--output',required=True)
    native.add_argument('--world',action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'compile-native':
        from .building_native import export_preview
        report=export_preview(_read(args.spec),args.output,world=args.world)
        print(json.dumps({'surface_cells':report['native_audit']['surface_cells'],
                          'world_exported':'world' in report,'park_world_blocks_added':0}))
        return
    if args.command == 'prepare-feed':
        from .building_source_feed import prepare
        base = Path(args.config).resolve().parent
        job, report = prepare(_read(args.config), lambda p: (base/p).resolve(), args.output)
        print(json.dumps({'candidate_buildings': report['candidate_buildings'], 'training_labels_generated': 0}))
        return
    if args.command == 'collect-feedback':
        from .building_source_feed import feedback_from_reviews
        if Path(args.output).exists(): raise ValueError('Fresh feedback output required')
        feedback = feedback_from_reviews(_read(args.queue), _read(args.decisions))
        atomic_json(Path(args.output), feedback)
        print(json.dumps({'reviewed_records': len(feedback['records'])}))
        return
    if args.command == 'iterate':
        report = iterate(_read(args.job), _read(args.feedback), _read(args.split), args.output,
                         _read(args.parent) if args.parent else None)
        print(json.dumps({'built': report['built'], 'promoted': report['promoted'],
                          'park_world_blocks_added': 0}))
        return
    if args.command == 'batch':
        report = run(_read(args.job), args.output, _read(args.model) if args.model else None, args.exploratory)
        print(json.dumps({'built': report['built'], 'total': len(report['buildings']), 'park_world_blocks_added': 0}))
        return
    if Path(args.output).exists(): raise ValueError('Fresh output path required')
    if args.command == 'import-study':
        source = Path(args.model)
        result = from_study(_read(source), args.building_id, hashlib.sha256(source.read_bytes()).hexdigest(),display_floor=args.display_floor)
    else:
        feedback = _read(args.feedback); split = _read(args.split)
        if feedback.get('version') != 'building-feedback-v1': raise ValueError('Versioned reviewed feedback required')
        result = learning.train(feedback['records'], split['training_buildings'], split['evaluation_buildings'],
                                _read(args.parent) if args.parent else None)
    atomic_json(Path(args.output), result)
    print(json.dumps({'output': str(args.output), 'version': result['version'],
                      'production_eligible': result.get('production_eligible', False)}))


if __name__ == '__main__':
    main()
