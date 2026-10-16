"""Source-bound horizontal frame qualification before component reconstruction.

Visible scale and a contextual fit are insufficient. Qualification recomputes
the existing named-mark or source-bound independent-survey checks.
"""
import argparse
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import re
from pyproj import CRS
from pypdf import PdfReader
from .generation_cycles import atomic_json, file_hash
from .evidence_memory import EvidenceMemory, identity
from .mapped_alignment_checks import printed_scale_review, VERSION as SCALE_VERSION
from .reconstruction.model import Source
from .reconstruction.registration import registration_domain

VERSION = 'drawing-frame-qualification-v4'


def qualify_page(pdf, page_number, source, references, sources, *, scale_review=None):
    """Recheck a frame without accepting its view, state or physical components."""
    from .coordinate_text import coordinate_runs
    from .drawing_marks import extract_marks
    from .drawing_registration_bridge import named_registration
    if (source.kind not in ('planning', 'cad') or not re.fullmatch('[0-9a-f]{64}', str(source.sha256))
            or file_hash(pdf) != source.sha256):
        raise ValueError('Pinned source PDF checksum mismatch')
    if (source.metadata.get('reuse_allowed') is not True or source.license == 'copyright-consultation-only'
            or source.metadata.get('reuse_status') == 'consultation_only'):
        raise ValueError('Source geometry reuse is not permitted')
    crs = CRS.from_user_input(source.crs)
    if not crs.is_projected or any(abs(a.unit_conversion_factor-1) > 1e-9 for a in crs.axis_info[:2]):
        raise ValueError('Projected metre target CRS required')
    reader = PdfReader(pdf)
    if type(page_number) is not int or not 1 <= page_number <= len(reader.pages) or len(reader.pages) > 1000:
        raise ValueError('Bounded source page required')
    page = reader.pages[page_number-1]
    content = page.get_contents()
    if content is not None and any(op in (b'BMC', b'BDC') or (op == b'Tr' and int(args[0]) == 3) for args, op in content.operations):
        raise ValueError('Invisible or layered text requires a separate visibility-aware adapter')
    actual_scale = printed_scale_review(pdf, page_number)
    if scale_review is not None and json.dumps(scale_review,sort_keys=True)!=json.dumps(actual_scale,sort_keys=True):
        raise ValueError('Supplied scale review differs from original source page')
    scale_review = actual_scale
    if (scale_review['status'] != 'one_visible_printed_scale'
            or scale_review['document_sha256'] != source.sha256 or scale_review['page'] != page_number):
        raise ValueError('One unambiguous printed scale with verified visibility required')
    if (source.metadata.get('semantic_annotation_contract') == 'ordinary_surface_labels_v1'
            or 'registration_coordinate_frame' in source.metadata):
        from .ordinary_surfaces import accepted_alignment
        alignment = accepted_alignment(source, page_number, references, sources, set(scale_review['denominators']))
        method = 'source-bound native points checked against independent survey registry'
    else:
        runs = coordinate_runs(page)
        marks = extract_marks(page, reuse_allowed=True)
        alignment = named_registration(runs, marks, references, sources, source,
            expected_scale=scale_review['expected_metres_per_pdf_point'])
        method = alignment['correspondence_method']
    from shapely.geometry import mapping
    domain = mapping(registration_domain(alignment))
    qualified = replace(source, registration_status='accepted', metadata={**source.metadata,
        'registration_document_sha256': source.sha256, 'registration_page': page_number,
        'horizontal_registration_review': alignment, 'registration_qualification_version': VERSION})
    return qualified, {'status': 'qualified_horizontal_frame', 'version': VERSION,
        'document_sha256': source.sha256, 'page': page_number, 'registration': alignment,
        'checked_domain': domain, 'coordinate_frame': 'pdf_native_points_y_up',
        'correspondence_method': method, 'scale_review': scale_review,
        'world_geometry_additions': 0, 'physical_components_accepted': 0,
        'remaining_component_requirements': ['verified_source_view_scope', 'existing_or_as_built_state',
            'physical_component_identity', 'source_bound_dimensions_and_materials', 'terrain_and_vertical_datum']}


def input_contract(config, resolve):
    settings = config.get('registration_qualification', {})
    automatic = config.get('automatic_reconstruction', {})
    if not settings.get('enabled', automatic.get('enabled', False)):
        return None
    return {'version': VERSION, 'scale_version': SCALE_VERSION,
            'inputs': {key: file_hash(resolve(settings.get(key, automatic.get(key))))
                       for key in ('manifest', 'references') if settings.get(key, automatic.get(key))}}


def run(corpus, geometry, store, output, *, manifest=None, references=None, max_pages=1000):
    if type(max_pages) is not int or not 1 <= max_pages <= 10000:
        raise ValueError('Bounded qualification page budget required')
    extraction = json.loads((Path(geometry)/'geometry-report.json').read_text())
    pages = corpus.db.execute('SELECT sha,page FROM geometry_pages WHERE version=? AND contract=? ORDER BY sha,page',
        (extraction['version'], extraction['contract'])).fetchall()
    if len(pages) != extraction['pages']:
        raise ValueError('Qualification extraction page inventory changed')
    if len(pages) > max_pages: raise ValueError('Qualification page budget exceeded')
    policy = json.loads(Path(manifest).read_text()) if manifest else {'sources': []}
    sources = {s['id']: Source(**s) for s in policy['sources']}
    if len(sources) != len(policy['sources']) or len(sources) > 10000:
        raise ValueError('Distinct bounded qualification sources required')
    refs = json.loads(Path(references).read_text())['landmarks'] if references else []
    if not isinstance(refs, list) or len(refs) > 1000: raise ValueError('Bounded qualification survey references required')
    by_sha = {}
    for source in sources.values():
        if source.kind in ('planning', 'cad'): by_sha.setdefault(source.sha256, []).append(source)
    pins = {key: file_hash(path) for key, path in [('manifest', manifest), ('references', references)] if path}
    contract = {'version': VERSION, 'scale_version': SCALE_VERSION, 'policy_sha256': pins,
                'pages': pages, 'max_pages': max_pages}
    run_id = identity(contract); output = Path(output)/run_id
    records = []; facts = []; computed = reused = 0
    with EvidenceMemory(store) as memory:
        for sha, page in pages:
            pdf = corpus.root/'files'/f'{sha}.pdf'
            if not re.fullmatch('[0-9a-f]{64}', sha) or file_hash(pdf) != sha:
                raise ValueError('Pinned source PDF checksum mismatch')
            policies = by_sha.get(sha, [])
            relevant_ids = {s.id for s in policies} | {r.get('source_id') for r in refs}
            relevant = [sources[i].__dict__ for i in sorted(i for i in relevant_ids if isinstance(i, str) and i in sources)]
            parents = [memory.put('source_policy', s, s) for s in relevant]
            inputs = {'version': VERSION, 'scale_version': SCALE_VERSION, 'document_sha256': sha,
                      'page': page, 'target_crs': policy.get('crs'),
                      'sources_sha256': identity(relevant), 'references_sha256': identity(refs)}
            cached = memory.get('drawing_frame_qualification', inputs, parents)
            if cached is not None: record = cached['payload']; reused += 1
            else:
                try:
                    scale = printed_scale_review(pdf, page)
                except (ValueError, RuntimeError) as error:
                    if file_hash(pdf) != sha:
                        raise ValueError('Pinned source PDF checksum mismatch') from error
                    scale = {'status': 'withheld_scale_review_error', 'document_sha256': sha,
                             'page': page, 'reason': str(error), 'denominators': [],
                             'expected_metres_per_pdf_point': None}
                missing = []
                if len(policies) != 1: missing.append('unique_checksum_bound_source_policy')
                if scale['status'] != 'one_visible_printed_scale': missing.append('visible_unambiguous_printed_scale')
                if not refs: missing.append('independent_survey_reference_bundle')
                record = {'document_sha256': sha, 'page': page, 'status': 'awaiting_registration_evidence',
                          'missing_requirements': missing, 'scale_review': scale,
                          'world_geometry_additions': 0, 'physical_components_accepted': 0, 'source': None}
                if len(policies) == 1 and not missing:
                    try:
                        if CRS.from_user_input(policies[0].crs) != CRS.from_user_input(policy['crs']):
                            raise ValueError('Drawing and qualification manifest CRS mismatch')
                        source, qualification = qualify_page(pdf, page, policies[0], refs, sources, scale_review=scale)
                        record.update(qualification, source=source.__dict__)
                    except (ValueError, KeyError, TypeError) as error:
                        record['missing_requirements'].append('independently_qualified_horizontal_frame')
                        record['reason'] = str(error)
                computed += 1
            identifier = memory.put('drawing_frame_qualification', inputs, record, parents)
            records.append(record); facts.append({'id': identifier, 'inputs': inputs, 'parents': parents})
        payload = ''.join(json.dumps(r, sort_keys=True)+'\n' for r in records)
        from hashlib import sha256
        digest = sha256(payload.encode()).hexdigest()
        if len(payload.encode()) > 128000000: raise ValueError('Qualification output byte budget exceeded')
        report = {'contract': contract, 'run_id': run_id, 'pages': len(records),
            'page_statuses': dict(Counter(r['status'] for r in records)),
            'missing_requirements': dict(Counter(v for r in records for v in r.get('missing_requirements', []))),
            'qualified_frames': sum(r['status'] == 'qualified_horizontal_frame' for r in records),
            'page_facts': facts, 'output_sha256': digest, 'world_geometry_additions': 0,
            'physical_components_accepted': 0}
        if output.exists():
            previous = json.loads((output/'qualification-report.json').read_text())
            if previous != json.loads(json.dumps(report)) or file_hash(output/'page-frames.jsonl') != digest:
                raise ValueError('Qualification inputs or outputs changed')
        else:
            output.mkdir(parents=True)
            (output/'page-frames.jsonl').write_bytes(payload.encode('utf-8'))
        # Recheck original bytes and ancestry before publishing/reusing a receipt.
        for sha in {sha for sha, _ in pages}:
            if file_hash(corpus.root/'files'/f'{sha}.pdf') != sha: raise ValueError('Qualification source PDF changed')
        for key, path in [('manifest', manifest), ('references', references)]:
            if path and file_hash(path) != pins[key]: raise ValueError('Qualification policy changed')
        for fact in facts:
            if memory.get('drawing_frame_qualification', fact['inputs'], fact['parents']) is None:
                raise ValueError('Qualification evidence changed before report commit')
        atomic_json(output/'qualification-report.json', report)
        return {**report, 'run_pages': computed, 'reused_pages': reused}


def main():
    from .planning_bulk import Corpus
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('corpus', 'geometry', 'store', 'output'): parser.add_argument('--'+key, required=True)
    for key in ('manifest', 'references'): parser.add_argument('--'+key)
    parser.add_argument('--max-pages',type=int,default=1000)
    args = parser.parse_args(); corpus = Corpus(args.corpus)
    try:
        report = run(corpus, args.geometry, args.store, args.output, manifest=args.manifest, references=args.references,max_pages=args.max_pages)
        print(json.dumps({k: report[k] for k in ('pages','qualified_frames','missing_requirements','run_pages','reused_pages')}))
    finally: corpus.close()


if __name__ == '__main__': main()
