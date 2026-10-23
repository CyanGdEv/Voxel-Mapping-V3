"""Find exact drawing captions before artwork segmentation or measurement.

A caption link says a source label was found. It never certifies a view crop,
scale, physical component or reconstruction. Existing measurement links remain
separate so failed artwork segmentation cannot masquerade as a missing PDF.
"""
import json
from pathlib import Path
import re

import pymupdf

from . import drawing_side_references, drawing_views, glyph_visibility
from .generation_cycles import atomic_json, file_hash
from .numbered_elevation_captions import parse
from .reconstruction_evidence_queue import digest

VERSION = 'drawing-caption-inventory-v1'


def inventory(page, document_sha256, charge):
    """Retain every exact caption, including failed visibility/identity screens."""
    traces = page.get_texttrace()
    if len(traces) > 10000 or sum(len(s['chars']) for s in traces) > 500000:
        raise OverflowError('caption_text_budget')
    identity = drawing_views.sheet_identity(traces)
    screens = {}

    def screen(index):
        if index not in screens:
            charge()
            screens[index] = glyph_visibility.screen_span(page, traces[index])
        return screens[index]

    if identity:
        screen(identity['trace_index'])
    captions = []
    for index, span in enumerate(traces):
        charge()
        text = drawing_views.text(span)
        parsed = parse(text)
        if not parsed:
            continue
        visible = screen(index)['status'] == 'raster_consistent_candidate'
        header_visible = bool(identity and screens[identity['trace_index']]['status'] == 'raster_consistent_candidate')
        row = {'document_sha256': document_sha256, 'page': page.number + 1,
               'caption': text, 'title_trace_index': index, 'title_bbox_pdf_unrotated': list(span['bbox']),
               'printed_claim': parsed, 'sheet_identity_candidate': identity,
               'caption_glyph_status': screens[index]['status'],
               'header_glyph_status': screens[identity['trace_index']]['status'] if identity else 'missing_or_ambiguous',
               'status': 'source_caption_candidate' if visible and header_visible else 'caption_visibility_or_identity_held',
               'artwork_assignment_verified': False, 'scale_application_verified': False,
               'physical_identity_verified': False, 'geometry_export_authorized': False}
        if visible and header_visible:
            row['source_caption_key_candidate'] = [identity['project'], identity['sheet'], parsed['view_number']]
        row['id'] = digest([VERSION, row])
        captions.append(row)
        if len(captions) > 100:
            raise OverflowError('caption_count_budget')
    return {'document_sha256': document_sha256, 'page': page.number + 1,
            'native_rotation_degrees': page.rotation, 'captions': captions, 'glyph_screens': screens}


def link(references, captions, previous_links, charge):
    """Join exact keys only; duplicate source witnesses stay competing."""
    if len(references) > 500 or len(captions) > 3200:
        raise OverflowError('caption_join_budget')
    previous = {r['source_reference_id']: r for r in previous_links}
    result = []
    for reference in references:
        charge()
        key = reference.get('target_view_key_candidate')
        matches = []
        for caption in captions:
            charge()
            if key and caption.get('source_caption_key_candidate') == key:
                matches.append(caption)
        prior = previous.get(reference['id'])
        measurement_available = bool(prior and prior['status'] == 'unique_source_view_reference_candidate')
        row = {'source_reference_id': reference['id'], 'source_reference_sha256': digest(reference),
               'target_view_key_candidate': key, 'caption_candidates': [c['id'] for c in matches],
               'status': 'source_reference_visibility_or_identity_held' if not key else
                   'source_caption_missing' if not matches else 'unique_source_caption_candidate' if len(matches) == 1 else
                   'competing_source_caption_candidates',
               'previous_measurement_link': prior,
               'next_requirement': 'source_reference_visibility_or_identity' if not key else
                   'missing_source_caption' if not matches else 'disambiguate_source_captions' if len(matches) > 1 else
                   'physical_correspondence_and_dimensions' if measurement_available else 'artwork_assignment_and_scale',
               'artwork_assignment_verified': False, 'physical_identity_verified': False,
               'geometry_export_authorized': False}
        row['id'] = digest([VERSION, row]); result.append(row)
    return result


def build(references, source_catalogue, source_directory, output, *, max_checks=100000):
    """Replay original markers and glyph screens against checksum-pinned PDFs."""
    if type(max_checks) is not int or not 1 <= max_checks <= 100000:
        raise ValueError('Bounded caption work required')
    references, source_catalogue, source_directory, output = map(Path,
        (references, source_catalogue, source_directory, output))
    if references.stat().st_size > 32000000 or source_catalogue.stat().st_size > 1000000:
        raise ValueError('Bounded caption inputs required')
    pins = {references: file_hash(references), source_catalogue: file_hash(source_catalogue)}
    parent = json.loads(references.read_text())
    if parent['status'] != 'roof_reference_evidence_only' or len(parent['roof_page_references']) > 16:
        raise ValueError('Complete source reference review required')
    entries = json.loads(source_catalogue.read_text())['entries']
    if not 1 <= len(entries) <= 16 or len({e['sha256'] for e in entries}) != len(entries):
        raise ValueError('One to sixteen distinct original PDFs required')
    sources = {}; total_bytes = 0
    for entry in entries:
        sha = entry['sha256']
        if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha):
            raise ValueError('Original source digest required')
        path = source_directory / (sha + '.pdf')
        total_bytes += path.stat().st_size
        if path.stat().st_size > 20000000 or total_bytes > 64000000 or file_hash(path) != sha:
            raise ValueError('Original caption PDF checksum/size mismatch')
        pins[path] = sha; sources[sha] = path
    if any(p['document_sha256'] not in sources for p in parent['roof_page_references']):
        raise ValueError('Original reference PDF must be in the source catalogue')
    modules = [drawing_side_references, drawing_views, glyph_visibility]
    contract = {'version': VERSION, 'implementation_sha256': file_hash(Path(__file__)),
                'kernel_sha256': {m.__name__: file_hash(Path(m.__file__)) for m in modules},
                'caption_parser_sha256': file_hash(Path(__file__).with_name('numbered_elevation_captions.py')),
                'source_reference_review_sha256': pins[references], 'source_catalogue_sha256': pins[source_catalogue],
                'source_pdf_sha256': sorted(sources), 'max_checks': max_checks, 'pymupdf_version': pymupdf.VersionBind}
    root = output / digest(contract)
    result = {'contract': contract, 'status': 'source_caption_coverage_only', 'checks': 0,
              'pages': [], 'reference_links': [], 'source_references': [],
              'previous_source_holds_overridden': False, 'geometry_export_authorized': False,
              'world_geometry_additions': 0, 'training_labels_generated': 0,
              'limitations': ['Exact caption keys identify source labels, not physical objects.',
                             'Caption glyph consistency does not establish artwork visibility or a view crop.',
                             'Scale, datum, physical correspondence and shared-cap closure remain unresolved.']}

    def charge():
        result['checks'] += 1
        if result['checks'] > max_checks:
            raise OverflowError('caption_work_budget')

    try:
        for record in parent['roof_page_references']:
            charge()
            with pymupdf.open(sources[record['document_sha256']]) as doc:
                page = doc[record['page'] - 1]
                fresh = drawing_side_references.page_references(page)
                # Normalize integer trace keys exactly as the parent JSON writer.
                if digest(json.loads(json.dumps(fresh))) != digest(record['side_reference_review']):
                    raise ValueError('Original reference markers changed')
                for _ in range(fresh['checks']): charge()
                result['source_references'].extend(fresh['references'])
        for sha, path in sorted(sources.items()):
            with pymupdf.open(path) as doc:
                if len(doc) > 16 or len(result['pages']) + len(doc) > 32:
                    raise OverflowError('caption_page_budget')
                for page in doc:
                    charge(); result['pages'].append(inventory(page, sha, charge))
        captions = [c for p in result['pages'] for c in p['captions']]
        result['reference_links'] = link(result['source_references'], captions, parent['target_links'], charge)
    except OverflowError as error:
        result.update(status='source_caption_coverage_budget_withheld', reason=str(error),
                      pages=[], reference_links=[], source_references=[])
    for path, sha in pins.items():
        if file_hash(path) != sha:
            raise ValueError('Original caption input changed during build')
    result['counts'] = {'source_documents': len(sources), 'source_pages': len(result['pages']),
                        'captions': sum(len(p['captions']) for p in result['pages']),
                        'unique_caption_links': sum(l['status'] == 'unique_source_caption_candidate' for l in result['reference_links']),
                        'missing_captions': sum(l['status'] == 'source_caption_missing' for l in result['reference_links']),
                        'competing_caption_links': sum(l['status'] == 'competing_source_caption_candidates' for l in result['reference_links']),
                        'held_source_references': sum(l['status'] == 'source_reference_visibility_or_identity_held' for l in result['reference_links'])}
    result = json.loads(json.dumps(result))
    if len(json.dumps(result).encode()) > 32000000:
        raise ValueError('Caption output budget exceeded')
    target = root / 'drawing-caption-coverage.json'
    if target.exists():
        if digest(json.loads(target.read_text())) != digest(result):
            raise ValueError('Saved caption coverage changed')
    else:
        atomic_json(target, result)
    return {**result, 'directory': str(root)}
