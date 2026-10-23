"""Source-bound desktop corrections and independently reviewed candidate outcomes.

Corrections are immutable annotations on an original candidate. They do not
change its geometry, features, source state, acceptance gates or model scores.
"""
import copy
import hashlib
import json
import math
from pathlib import Path
import re

from .building_learning import _features, _records
from .building_source_feed import feedback_from_reviews
from .building_spec import FRAME, VERSION as SPEC_VERSION, digest

VERSION = 'desktop-review-session-v1'
MAX_JSON_BYTES = 16_000_000
MAX_PDF_BYTES = 32_000_000
MAX_RECORDS = 10000
MAX_CORRECTIONS = 256
MAX_POINTS = 4096
PLACEMENT_CONVENTION = ('Rotate about the local origin first, then apply local XYZ translation in metres. '
                        'rotation_degrees is counterclockwise about the positive local Z axis, viewed from above.')


def _pin(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('A source or candidate SHA256 is required')
    return value


def _text(value, label, limit=1000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('A bounded nonempty '+label+' is required')
    return value


def _read(path, limit=MAX_JSON_BYTES):
    try:
        path = Path(path).expanduser().resolve()
    except (TypeError, ValueError) as error:
        raise ValueError('An existing input file path is required') from error
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError('A bounded existing input file is required')
    with path.open('rb') as stream:
        raw = stream.read(limit+1)
    if len(raw) > limit:
        raise ValueError('Input byte budget exceeded')
    return raw, hashlib.sha256(raw).hexdigest()


def _json(path):
    raw, pin = _read(path)
    def invalid(value):
        raise ValueError('Nonfinite JSON constant: '+value)
    value = json.loads(raw.decode('utf-8-sig'), parse_constant=invalid)
    if not isinstance(value, dict):
        raise ValueError('A versioned input JSON object is required')
    return value, pin


def _seal(value):
    value['content_sha256'] = digest({k: v for k, v in value.items() if k != 'content_sha256'})
    return value


def _queue_rows(queue):
    if (queue.get('version') != 'building-review-queue-v1'
            or queue.get('content_sha256') != digest({k: v for k, v in queue.items() if k != 'content_sha256'})):
        raise ValueError('The pinned review queue changed or has an unsupported version')
    rows = queue.get('records')
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_RECORDS:
        raise ValueError('One to 10000 review queue records are required')
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Review queue records must be objects')
        key = (_text(row.get('building_id'), 'building ID'), _pin(row.get('candidate_sha256')))
        if key in seen:
            raise ValueError('Duplicate review queue candidate')
        seen.add(key)
        _text(row.get('candidate_id'), 'candidate ID')
        _features(row.get('features'))
        sources = row.get('source_sha256')
        if not isinstance(sources, list) or not 1 <= len(sources) <= 1024:
            raise ValueError('A bounded original source inventory is required')
        for source in sources:
            _pin(source)
        if len(set(sources)) != len(sources):
            raise ValueError('Duplicate original source references')
    return rows


def _batch_index(batch):
    if batch.get('version') != 'building-batch-v1':
        raise ValueError('A building-batch-v1 document is required')
    buildings = batch.get('buildings')
    if not isinstance(buildings, list) or not 1 <= len(buildings) <= 1000:
        raise ValueError('A bounded building batch is required')
    index = {}; building_ids = set()
    for building in buildings:
        if not isinstance(building, dict):
            raise ValueError('Building batch entries must be objects')
        identifier = _text(building.get('building_id'), 'building ID')
        if identifier in building_ids:
            raise ValueError('Duplicate batch building')
        building_ids.add(identifier)
        candidates = building.get('candidates')
        if not isinstance(candidates, list) or not 1 <= len(candidates) <= MAX_RECORDS:
            raise ValueError('A bounded candidate inventory is required')
        candidate_ids = set()
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise ValueError('Candidate entries must be objects')
            cid = _text(candidate.get('id'), 'candidate ID')
            if cid in candidate_ids:
                raise ValueError('Duplicate batch candidate ID')
            candidate_ids.add(cid)
            actual = digest({k: v for k, v in candidate.items() if k != 'candidate_sha256'})
            if 'candidate_sha256' in candidate and candidate['candidate_sha256'] != actual:
                raise ValueError('Candidate content hash changed')
            spec = candidate.get('spec')
            if (not isinstance(spec, dict) or spec.get('version') != SPEC_VERSION
                    or spec.get('coordinate_frame') != FRAME or spec.get('building_id') != identifier):
                raise ValueError('Candidate must contain a matching local-metre building specification')
            components = spec.get('components')
            if not isinstance(components, list) or not 1 <= len(components) <= 4096:
                raise ValueError('A bounded candidate component inventory is required')
            component_ids = [_text(c.get('id'), 'component ID') for c in components if isinstance(c, dict)]
            if len(component_ids) != len(components) or len(set(component_ids)) != len(components):
                raise ValueError('Unique candidate component IDs are required')
            key = (identifier, actual)
            if key in index:
                raise ValueError('Duplicate batch candidate content')
            index[key] = candidate
            if len(index) > MAX_RECORDS:
                raise ValueError('Candidate review budget exceeded')
    return index


def load_session(queue_path, batch_path=None):
    """Open a hash-bound queue and its unchanged candidate specifications."""
    queue_path = Path(queue_path).expanduser().resolve()
    if batch_path is None:
        siblings = [queue_path.parent/name for name in ('buildings.json', 'building-batch.json')]
        matches = [p for p in siblings if p.is_file()]
        if len(matches) != 1:
            raise ValueError('Choose the candidate batch explicitly when no unique sibling batch exists')
        batch_path = matches[0]
    batch_path = Path(batch_path).expanduser().resolve()
    queue, queue_pin = _json(queue_path); batch, batch_pin = _json(batch_path)
    rows = _queue_rows(queue); index = _batch_index(batch); records = []
    for row in rows:
        key = (row['building_id'], row['candidate_sha256'])
        candidate = index.get(key)
        if candidate is None or candidate['id'] != row['candidate_id'] or candidate.get('features') != row['features']:
            raise ValueError('Review queue does not match the exact candidate batch')
        declared_sources = None
        for name in ('source_feed', 'cross_view'):
            metadata = candidate.get(name)
            if isinstance(metadata, dict) and 'original_pdf_sha256' in metadata:
                declared_sources = metadata['original_pdf_sha256']
        if declared_sources is None:
            declared_sources = [s.get('sha256') for s in candidate['spec'].get('sources', []) if isinstance(s, dict)]
        if (not isinstance(declared_sources, list) or not declared_sources
                or any(not isinstance(s, str) for s in declared_sources)
                or set(declared_sources) != set(row['source_sha256'])):
            raise ValueError('Review queue source inventory does not match the candidate')
        records.append({**copy.deepcopy(row), 'candidate': copy.deepcopy(candidate)})
    return _seal({'version': VERSION, 'queue_path': str(queue_path), 'batch_path': str(batch_path),
                  'queue_sha256': queue_pin, 'batch_sha256': batch_pin,
                  'queue': queue, 'batch': batch, 'records': records, 'resolved_sources': {}})


def _session(session):
    if (not isinstance(session, dict) or session.get('version') != VERSION
            or session.get('content_sha256') != digest({k: v for k, v in session.items() if k != 'content_sha256'})):
        raise ValueError('The review session changed')
    _text(session.get('queue_path'), 'review queue path', 32768)
    _text(session.get('batch_path'), 'candidate batch path', 32768)
    fresh = load_session(session.get('queue_path'), session.get('batch_path'))
    for key in ('queue_sha256', 'batch_sha256', 'queue', 'batch', 'records'):
        if session.get(key) != fresh[key]:
            raise ValueError('Review inputs changed; open a new review session')
    resolved = session.get('resolved_sources')
    if not isinstance(resolved, dict) or len(resolved) > 1024:
        raise ValueError('A bounded resolved source inventory is required')
    sources = {h for row in fresh['records'] for h in row['source_sha256']}
    for sha, entry in resolved.items():
        if sha not in sources or not isinstance(entry, dict) or entry.get('sha256') != sha:
            raise ValueError('Resolved PDF does not belong to this review queue')
        actual = _pdf(entry.get('path'))
        if actual != entry:
            raise ValueError('A bound original source PDF changed')
    return fresh


def _pdf(path):
    raw, sha = _read(path, MAX_PDF_BYTES)
    if not raw.startswith(b'%PDF-'):
        raise ValueError('A source PDF is required')
    import pymupdf
    try:
        with pymupdf.open(stream=raw, filetype='pdf') as doc:
            if doc.needs_pass or not 1 <= doc.page_count <= 10000:
                raise ValueError('An unencrypted PDF with a bounded page count is required')
            pages = doc.page_count
    except (RuntimeError, pymupdf.FileDataError) as error:
        raise ValueError('The original PDF could not be opened') from error
    return {'path': str(Path(path).expanduser().resolve()), 'sha256': sha, 'bytes': len(raw), 'pages': pages}


def bind_source(session, source_path):
    """Return a new session after matching an original PDF by its exact bytes."""
    _session(session)
    entry = _pdf(source_path)
    sources = {h for row in session['records'] for h in row['source_sha256']}
    if entry['sha256'] not in sources:
        raise ValueError('This PDF checksum is not an original source in the review queue')
    result = copy.deepcopy(session)
    result['resolved_sources'][entry['sha256']] = entry
    return _seal(result)


def _number(value, low=-10000, high=10000):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Finite bounded metre coordinates or dimensions are required')
    return value


def _corrections(values, row, session):
    if not isinstance(values, list) or len(values) > MAX_CORRECTIONS:
        raise ValueError('At most 256 correction annotations are supported')
    components = {c['id'] for c in row['candidate']['spec']['components']}
    total_points = 0
    for value in values:
        if not isinstance(value, dict):
            raise ValueError('Correction annotations must be objects')
        kind = value.get('type')
        common = {'type', 'source_sha256', 'source_page'}
        fields = {'outline': {'component_id', 'projection', 'points_m'},
                  'opening': {'component_id', 'projection', 'points_m'},
                  'dimension': {'component_id', 'value_m', 'axis'},
                  'placement': {'translation_m', 'rotation_degrees'}}
        if kind not in fields or set(value) - common - fields[kind]:
            raise ValueError('Unsupported correction annotation fields or type')
        if not (common | fields[kind]) <= set(value):
            raise ValueError('Required correction annotation fields are missing')
        sha = _pin(value['source_sha256'])
        if sha not in row['source_sha256']:
            raise ValueError('Correction source is not used by this candidate')
        bound = session['resolved_sources'].get(sha)
        if bound is None:
            raise ValueError('Bind the original PDF before annotating its geometry')
        page = value['source_page']
        if type(page) is not int or not 1 <= page <= bound['pages']:
            raise ValueError('Correction source page is outside the bound original PDF')
        if kind != 'placement' and value.get('component_id') not in components:
            raise ValueError('Correction names an unknown candidate component')
        if kind in ('outline', 'opening'):
            if value['projection'] not in ('xy', 'xz', 'yz'):
                raise ValueError('A local XY, XZ or YZ correction projection is required')
            points = value['points_m']
            if not isinstance(points, list) or not 3 <= len(points) <= MAX_POINTS:
                raise ValueError('A bounded polygon with at least three points is required')
            total_points += len(points)
            if total_points > MAX_POINTS:
                raise ValueError('Whole-review correction point budget exceeded')
            for point in points:
                if not isinstance(point, list) or len(point) != 2:
                    raise ValueError('Correction polygon points need two metre coordinates')
                for coordinate in point:
                    _number(coordinate)
            from shapely.geometry import Polygon
            polygon = Polygon(points)
            if not polygon.is_valid or polygon.area <= 1e-8:
                raise ValueError('Correction polygon must be simple with nonzero area')
        elif kind == 'dimension':
            _number(value['value_m'], 1e-6, 10000)
            if value['axis'] not in ('x', 'y', 'z'):
                raise ValueError('A supported dimension axis is required')
        else:
            translation = value['translation_m']
            if not isinstance(translation, list) or len(translation) != 3:
                raise ValueError('A three-coordinate local translation is required')
            for coordinate in translation:
                _number(coordinate)
            _number(value['rotation_degrees'], -360, 360)
    return copy.deepcopy(values)


def _write(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n')


def save_review(session, *, building_id, candidate_sha256, outcome, review_basis,
                review_reference, corrections, output_directory):
    """Retain draft corrections or an explicit review of the original candidate."""
    _session(session)
    row = next((r for r in session['records'] if r['building_id'] == building_id
                and r['candidate_sha256'] == candidate_sha256), None)
    if row is None:
        raise ValueError('Select an exact candidate from this review session')
    annotations = _corrections(corrections, row, session)
    draft = outcome is None
    if draft:
        if review_basis is not None or review_reference not in ('', None) or not annotations:
            raise ValueError('A correction draft needs annotations and no correctness decision')
        decisions = None; feedback = None
    else:
        if outcome not in ('accepted', 'rejected') or review_basis not in ('independent_review', 'source_verified'):
            raise ValueError('An explicit independently reviewed outcome is required')
        _text(review_reference, 'external review reference', 4000)
        if annotations and outcome != 'rejected':
            raise ValueError('A candidate needing geometry corrections cannot be labelled accepted')
        decisions = {'version': 'building-review-decisions-v1', 'records': [{
            'building_id': building_id, 'candidate_sha256': candidate_sha256,
            'outcome': outcome, 'review_basis': review_basis, 'review_reference': review_reference}]}
        feedback = feedback_from_reviews(session['queue'], decisions)
        _records(feedback['records'])
    annotation_document = _seal({'version': 'building-correction-annotations-v1',
        'building_id': building_id, 'candidate_sha256': candidate_sha256,
        'queue_sha256': session['queue_sha256'], 'batch_sha256': session['batch_sha256'],
        'coordinate_frame': FRAME, 'corrections': annotations,
        'placement_convention': PLACEMENT_CONVENTION,
        'source_sha256': list(row['source_sha256']),
        'corrected_geometry_verified': False, 'geometry_modified': False,
        'world_placement_eligible': False, 'training_labels_generated': 0})
    output = Path(output_directory).expanduser().resolve()
    if output.exists():
        raise ValueError('A fresh immutable review output directory is required')
    # Recheck after annotation/decision validation, immediately before publishing.
    _session(session)
    output.mkdir(parents=True, exist_ok=False)
    _write(output/'corrections.json', annotation_document)
    _write(output/'original-candidate.json', row['candidate'])
    context = _seal({'version': 'desktop-review-context-v1',
        'queue_record': {k: v for k, v in row.items() if k != 'candidate'},
        'queue_path': session['queue_path'], 'batch_path': session['batch_path'],
        'queue_sha256': session['queue_sha256'], 'batch_sha256': session['batch_sha256'],
        'bound_sources': {sha: entry for sha, entry in session['resolved_sources'].items()
                          if sha in row['source_sha256']}})
    _write(output/'review-context.json', context)
    if feedback is not None:
        _write(output/'decisions.json', decisions)
        _write(output/'feedback.json', feedback)
    report = _seal({'version': 'desktop-review-result-v1',
        'status': 'correction_draft_saved' if draft else 'reviewed_candidate_saved',
        'output_directory': str(output), 'corrections_path': str(output/'corrections.json'),
        'candidate_path': str(output/'original-candidate.json'),
        'context_path': str(output/'review-context.json'),
        'feedback_path': str(output/'feedback.json') if feedback is not None else None,
        'decision_path': str(output/'decisions.json') if decisions is not None else None,
        'building_id': building_id, 'candidate_sha256': candidate_sha256,
        'reviewed_records': 0 if draft else 1, 'correction_count': len(annotations),
        'corrections_sha256': annotation_document['content_sha256'],
        'context_sha256': context['content_sha256'],
        'queue_sha256': session['queue_sha256'], 'batch_sha256': session['batch_sha256'],
        'geometry_modified': False, 'corrected_geometry_verified': False,
        'world_placement_eligible': False, 'training_labels_generated': 0,
        'review_provenance': 'Declared external review references are audit pointers, not authenticated signatures.'})
    _write(output/'report.json', report)
    return report


def _saved_document(path, version):
    value, pin = _json(path)
    if (value.get('version') != version
            or value.get('content_sha256') != digest({k: v for k, v in value.items() if k != 'content_sha256'})):
        raise ValueError('Saved review content changed: '+Path(path).name)
    return value, pin


def _unapproved(value):
    if (any(value.get(key) is not False for key in
            ('geometry_modified', 'corrected_geometry_verified', 'world_placement_eligible'))
            or type(value.get('training_labels_generated')) is not int
            or value['training_labels_generated'] != 0):
        raise ValueError('Saved corrections cannot authorize geometry or generate labels')


def resume_review(output_directory):
    """Reopen saved corrections only when their exact original inputs remain.

    No source relocation, geometry change, correctness label, feedback import or
    new output is implicit. Returned PDF bindings have been rechecked by bytes.
    """
    root = Path(output_directory).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('An existing saved review directory is required')
    report, report_pin = _saved_document(root/'report.json', 'desktop-review-result-v1')
    context, context_pin = _saved_document(root/'review-context.json', 'desktop-review-context-v1')
    annotations, annotation_pin = _saved_document(root/'corrections.json', 'building-correction-annotations-v1')
    original, candidate_pin = _json(root/'original-candidate.json')
    _unapproved(report); _unapproved(annotations)
    expected_paths = {'output_directory': root, 'corrections_path': root/'corrections.json',
                      'candidate_path': root/'original-candidate.json', 'context_path': root/'review-context.json'}
    if any(report.get(key) != str(path) for key, path in expected_paths.items()):
        raise ValueError('Saved review directory paths changed; relocation is not supported')
    if report.get('corrections_sha256') != annotations['content_sha256']:
        raise ValueError('Saved correction annotation hash differs from its report')
    if report.get('context_sha256') != context['content_sha256']:
        raise ValueError('Saved review context hash differs from its report')
    if (annotations.get('coordinate_frame') != FRAME
            or annotations.get('placement_convention') != PLACEMENT_CONVENTION):
        raise ValueError('Saved correction coordinate or placement convention changed')
    try:
        session = load_session(context['queue_path'], context['batch_path'])
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError('Original review queue or batch is missing or changed; restore the exact inputs before reopening') from error
    for key in ('queue_sha256', 'batch_sha256'):
        if any(document.get(key) != session[key] for document in (context, report, annotations)):
            raise ValueError('Original review queue or batch checksum changed')
    building_id = _text(report.get('building_id'), 'saved building ID')
    candidate_sha256 = _pin(report.get('candidate_sha256'))
    row = next((r for r in session['records'] if r['building_id'] == building_id
                and r['candidate_sha256'] == candidate_sha256), None)
    if row is None or original != row['candidate']:
        raise ValueError('Saved original candidate differs from the exact source batch')
    if (annotations.get('building_id') != building_id or annotations.get('candidate_sha256') != candidate_sha256
            or annotations.get('source_sha256') != row['source_sha256']
            or context.get('queue_record') != {k: v for k, v in row.items() if k != 'candidate'}):
        raise ValueError('Saved correction context belongs to a different candidate or source inventory')
    sources = context.get('bound_sources')
    if not isinstance(sources, dict) or len(sources) > 1024:
        raise ValueError('A bounded saved source inventory is required')
    for sha, entry in sources.items():
        if sha not in row['source_sha256'] or not isinstance(entry, dict) or entry.get('sha256') != sha:
            raise ValueError('Saved source binding is not part of the original candidate')
        try:
            session = bind_source(session, entry.get('path'))
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ValueError('A bound original source PDF is missing or changed; restore its exact saved path and bytes') from error
        if session['resolved_sources'].get(sha) != entry:
            raise ValueError('Saved source binding metadata differs from the original PDF')
    corrections = _corrections(annotations.get('corrections'), row, session)
    if type(report.get('correction_count')) is not int or report['correction_count'] != len(corrections):
        raise ValueError('Saved correction count differs from its report')
    if type(report.get('reviewed_records')) is not int:
        raise ValueError('An explicit saved reviewed-record count is required')
    draft = report.get('status') == 'correction_draft_saved'
    decision = None; extra_pins = {}
    if draft:
        if (not corrections or report.get('reviewed_records') != 0
                or report.get('feedback_path') is not None or report.get('decision_path') is not None
                or (root/'feedback.json').exists() or (root/'decisions.json').exists()):
            raise ValueError('A correction draft cannot contain reviewed feedback')
    elif report.get('status') == 'reviewed_candidate_saved':
        if (report.get('reviewed_records') != 1
                or report.get('feedback_path') != str(root/'feedback.json')
                or report.get('decision_path') != str(root/'decisions.json')):
            raise ValueError('Saved reviewed decision paths or counts changed')
        decisions, extra_pins['decisions.json'] = _json(root/'decisions.json')
        feedback, extra_pins['feedback.json'] = _json(root/'feedback.json')
        if not isinstance(decisions.get('records'), list) or len(decisions['records']) != 1:
            raise ValueError('Exactly one saved original candidate decision is required')
        decision = decisions['records'][0]
        if (not isinstance(decision, dict) or decision.get('building_id') != building_id
                or decision.get('candidate_sha256') != candidate_sha256):
            raise ValueError('Saved review decision belongs to a different original candidate')
        _text(decision.get('review_reference'), 'external review reference', 4000)
        expected = feedback_from_reviews(session['queue'], decisions)
        _records(expected['records'])
        if expected != feedback or (corrections and decision['outcome'] != 'rejected'):
            raise ValueError('Saved feedback changed or incorrectly accepts geometry needing corrections')
    else:
        raise ValueError('Unsupported saved review status')
    # Recheck both originals and saved files after reconstruction, before returning.
    _session(session)
    pins = {'report.json': report_pin, 'review-context.json': context_pin,
            'corrections.json': annotation_pin, 'original-candidate.json': candidate_pin, **extra_pins}
    for name, expected in pins.items():
        _, actual = _read(root/name)
        if actual != expected:
            raise ValueError('Saved review changed while reopening')
    return {'session': session, 'building_id': building_id, 'candidate_sha256': candidate_sha256,
            'corrections': copy.deepcopy(corrections), 'decision': copy.deepcopy(decision),
            'report': copy.deepcopy(report)}
