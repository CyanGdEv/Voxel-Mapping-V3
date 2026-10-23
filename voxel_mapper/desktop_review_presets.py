"""Portable retained-study and synthetic inputs for visual desktop review.

Preparing a queue does not review a candidate or establish physical identity.
Original planning documents are read only from explicitly selected local data.
"""
from concurrent.futures import CancelledError
import hashlib
import json
from pathlib import Path
import shutil

from .building_spec import FRAME, VERSION as SPEC_VERSION, digest
from .generation_cycles import atomic_json

VERSION = 'desktop-review-preset-v1'
MODEL_PATH = 'evidence/wicker-shop-projection-model.json'
MAX_MODEL_BYTES = 32_000_000


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _check(cancelled):
    if cancelled():
        raise CancelledError()


def _progress(progress, value, message):
    if progress:
        progress({'progress': value, 'message': message})


def _fresh(output):
    root = Path(output).expanduser().resolve()
    if root.exists():
        raise ValueError('A fresh review output directory is required')
    return root


def _pinned_model():
    from .desktop_area import bundle
    root, manifest = bundle()
    pins = {row['sha256'] for preset in manifest['presets'] for row in preset['files']
            if row['path'] == MODEL_PATH and not row.get('external', False)}
    if len(pins) != 1:
        raise ValueError('The retained Wicker model needs one bundled source pin')
    pin = next(iter(pins))
    path = root / MODEL_PATH
    if not path.is_file() or path.stat().st_size > MAX_MODEL_BYTES or _sha(path) != pin:
        raise ValueError('The bundled Wicker review model is missing or changed')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != pin:
        raise ValueError('The bundled Wicker review model changed during reading')
    return path, pin, json.loads(raw)


def _pinned_diagnostics(model):
    """Read only diagnostics directly pinned by the model and retained bundle."""
    references = {}
    for key in ('input_sha256', 'vertical_input_sha256'):
        references.update(model.get(key, {}))
    if not references:
        return []
    from .desktop_area import bundle
    root, manifest = bundle()
    available = {}
    for preset in manifest['presets']:
        for row in preset['files']:
            if not row.get('external', False):
                available.setdefault(row['path'], set()).add(row['sha256'])
    diagnostics = []
    for relative, pin in sorted(references.items()):
        if available.get(relative) != {pin}:
            raise ValueError('A retained model diagnostic is not pinned in the data bundle')
        path = (root/relative).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError('Retained diagnostic path is outside the data bundle')
        if not path.is_file() or path.stat().st_size > MAX_MODEL_BYTES:
            raise ValueError('A retained model diagnostic is missing or too large')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != pin:
            raise ValueError('A retained model diagnostic changed')
        diagnostics.append((path, pin, json.loads(raw)))
    return diagnostics


def _report(root, *, preset, dataset_kind, required, found, feed_report, extras=None):
    verified = sorted(found)
    report = {
        'version': VERSION,
        'status': 'review_prepared_missing_sources' if set(required)-set(found) else 'review_prepared',
        'preset': preset,
        'dataset_kind': dataset_kind,
        'queue_path': str(root/'feed'/'review-queue.json'),
        'batch_path': str(root/'feed'/'buildings.json'),
        'source_paths': [str(root/'sources'/(pin+'.pdf')) for pin in verified],
        'verified_source_sha256': verified,
        'missing_source_sha256': sorted(set(required)-set(found)),
        'candidate_buildings': feed_report['candidate_buildings'],
        'training_labels_generated': 0,
        'physical_acceptance': False,
        'park_world_blocks_added': 0,
        'limitations': [
            'Original candidate geometry remains a provisional local study.',
            'Preparing a review queue does not establish physical identity or placement.',
            'No review outcomes, training labels or model promotions are generated.',
        ],
    }
    report.update(extras or {})
    atomic_json(root/'review-preset-report.json', report)
    return report


def prepare_wicker(output, *, evidence_directory=None, cache_directory=None,
                   cancelled=lambda: False, progress=None):
    """Prepare the real retained Wicker shop for review without downloading data."""
    from .desktop_area import _find_originals
    from .building_source_feed import VERSION as FEED_VERSION, _hashes, prepare
    root = _fresh(output)
    _check(cancelled)
    _progress(progress, .05, 'Checking the retained Wicker model')
    model_path, model_pin, model = _pinned_model()
    diagnostics = _pinned_diagnostics(model)
    wanted = _hashes(model)
    for _, _, diagnostic in diagnostics:
        wanted.update(_hashes(diagnostic))
    if not wanted:
        raise ValueError('The retained Wicker model has no original source references')
    found = {}
    if evidence_directory:
        found.update(_find_originals(evidence_directory, wanted, cancelled))
    if cache_directory and Path(cache_directory).is_dir() and wanted-set(found):
        found.update(_find_originals(cache_directory, wanted-set(found), cancelled))
    _check(cancelled)
    root.mkdir(parents=True)
    (root/'sources').mkdir()
    shutil.copyfile(model_path, root/'model.json')
    if _sha(root/'model.json') != model_pin or _sha(model_path) != model_pin:
        raise ValueError('The retained model changed while staging review inputs')
    staged_diagnostics = []
    for index, (path, pin, _) in enumerate(diagnostics):
        _check(cancelled)
        target = root/('diagnostic-'+str(index)+'.json')
        shutil.copyfile(path, target)
        if _sha(target) != pin or _sha(path) != pin:
            raise ValueError('A retained diagnostic changed while staging review inputs')
        staged_diagnostics.append({'path': target.name, 'sha256': pin})
    for index, (pin, source) in enumerate(sorted(found.items())):
        _check(cancelled)
        if source.stat().st_size > MAX_MODEL_BYTES or _sha(source) != pin:
            raise ValueError('Original planning PDF changed before staging')
        target = root/'sources'/(pin+'.pdf')
        shutil.copyfile(source, target)
        if _sha(target) != pin or _sha(source) != pin:
            raise ValueError('Original planning PDF changed while staging')
        _progress(progress, .1+.25*(index+1)/max(1, len(found)), 'Staged an original source PDF')
    config = {
        'version': FEED_VERSION,
        'buildings': [{
            'building_id': 'wicker-shop-provisional',
            'model': 'model.json', 'model_sha256': model_pin,
            'diagnostics': staged_diagnostics,
            'source_directories': ['sources'],
        }],
    }
    atomic_json(root/'source-feed-config.json', config)
    _check(cancelled)
    _progress(progress, .4, 'Preparing source-linked local geometry and review queue')
    _, feed_report = prepare(config, lambda value: (root/value).resolve(), root/'feed')
    _check(cancelled)
    if feed_report['candidate_buildings'] != 1:
        reasons = [entry.get('reason', 'No candidate prepared') for entry in feed_report['buildings']]
        raise ValueError('Could not prepare the retained Wicker candidate: '+'; '.join(reasons))
    report = _report(root, preset='wicker-shop', dataset_kind='retained_provisional',
                     required=wanted, found=found, feed_report=feed_report)
    _progress(progress, 1., 'Provisional Wicker review inputs are ready')
    return report


def prepare_demo(output, *, incorrect_geometry=False):
    """Make an offline synthetic drawing/spec pair without reviewed decisions."""
    import pymupdf
    from .building_learning import FEATURES, GATES
    root = _fresh(output)
    root.mkdir(parents=True)
    (root/'sources').mkdir()
    with pymupdf.open() as document:
        page = document.new_page(width=640, height=440)
        page.insert_text((28, 32), 'SYNTHETIC REVIEW DEMONSTRATION - NOT A REAL BUILDING', fontsize=13)
        page.insert_text((28, 55), 'Local front elevation: width 8 m; height 4 m. Window: x=1..2, z=1..2 m.', fontsize=11)
        page.draw_rect(pymupdf.Rect(100, 130, 500, 330), color=(.1, .2, .4), width=2)
        page.draw_rect(pymupdf.Rect(150, 230, 200, 280), color=(.1, .5, .7), width=2)
        page.insert_text((260, 355), '8 m', fontsize=14)
        page.insert_text((510, 240), '4 m', fontsize=14)
        page.insert_text((28, 390), 'Geometry and scale are explicit synthetic fixture inputs; no physical acceptance.', fontsize=10)
        pdf = document.tobytes(garbage=4, deflate=True, no_new_id=True)
    source_pin = hashlib.sha256(pdf).hexdigest()
    (root/'sources'/(source_pin+'.pdf')).write_bytes(pdf)
    spec = {
        'version': SPEC_VERSION, 'coordinate_frame': FRAME,
        'building_id': 'synthetic-review-hall',
        'sources': [{'id': 'synthetic-elevation', 'sha256': source_pin, 'state': 'proposed'}],
        'assumptions': ['Synthetic demonstration only; wall thickness is a display hypothesis.'],
        'components': [{
            'id': 'front-wall', 'role': 'wall', 'colour': '527fb0',
            'evidence': {'class': 'inferred', 'source_ids': ['synthetic-elevation'],
                         'description': 'Synthetic elevation geometry; not evidence about a real building.'},
            'geometry': {'kind': 'extrusion', 'axis': 1, 'interval_m': [0, .3],
                         'profile': [[0, 0], [8, 0], [8, 4], [0, 4]],
                         'holes': [[[1, 1], [2, 1], [2, 2], [1, 2]]]},
        }],
    }
    if type(incorrect_geometry) is not bool:raise ValueError('Demo geometry setting must be boolean')
    if incorrect_geometry:
        # Deliberately misread the horizontal scale of the explicitly synthetic
        # source. A width correction to the printed 8 m repairs the whole face.
        geometry=spec['components'][0]['geometry']
        for ring in [geometry['profile'],*geometry['holes']]:
            for point in ring:point[0]*=.75
    features = dict.fromkeys(FEATURES, 0.)
    features['source_coverage'] = 1.
    candidate = {
        'id': 'synthetic-original', 'spec': spec, 'features': features,
        'gates': dict.fromkeys(GATES, False),
        'source_feed': {'dataset_kind': 'synthetic', 'automatic_trace_discovery': False},
    }
    candidate['candidate_sha256'] = digest(candidate)
    batch = {'version': 'building-batch-v1', 'buildings': [{
        'building_id': spec['building_id'], 'candidates': [candidate]}]}
    queue = {'version': 'building-review-queue-v1', 'records': [{
        'building_id': spec['building_id'], 'candidate_id': candidate['id'],
        'candidate_sha256': candidate['candidate_sha256'], 'features': features,
        'source_sha256': [source_pin], 'outcome': None, 'review_basis': None,
        'review_scope': 'Synthetic local candidate only; no real source or physical correctness claim.',
    }]}
    queue['content_sha256'] = digest(queue)
    (root/'feed').mkdir()
    atomic_json(root/'feed'/'buildings.json', batch)
    atomic_json(root/'feed'/'review-queue.json', queue)
    extras={}
    if incorrect_geometry:
        from .reconstruction_benchmark import reference_digest
        reference={'version':'reconstruction-benchmark-v1','dataset_kind':'synthetic','coordinate_frame':FRAME,'units':'metres',
            'cases':[{'id':'synthetic-drawing-scale','building_id':spec['building_id'],'source_sha256':[source_pin],
                'reference':{'review_basis':'independent_review','review_reference':'Fixed synthetic drawing constants; no real park evidence.',
                    'geometry_definition':'projected_xy_bounds_origin_v1','component_id':'front-wall','opening_projection':'xz',
                    'geometry':{'footprint_m':[[0,0],[8,0],[8,.3],[0,.3]],'height_m':4,'position_m':[0,0,0],
                        'openings_m':[[[1,1],[2,1],[2,2],[1,2]]]}},'prediction':None}]}
        reference['reference_sha256']=reference_digest(reference)
        atomic_json(root/'synthetic-reference.json',reference)
        extras={'benchmark_path':str(root/'synthetic-reference.json'),
            'demo_instructions':'The source says width 8 m; the candidate deliberately uses 6 m. Add an X dimension correction of 8 m, save the draft and regenerate.'}
    report = _report(root, preset='synthetic-correction-demo' if incorrect_geometry else 'synthetic-demo', dataset_kind='synthetic',
                     required={source_pin}, found={source_pin: root/'sources'/(source_pin+'.pdf')},
                     feed_report={'candidate_buildings': 1},extras=extras)
    return report
