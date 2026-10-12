"""Checksum-bound original-source bundles and portable, network-free inspection."""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import tempfile
import uuid
import zipfile

from .source_archive import (MAX_ARCHIVE_BYTES, MAX_HTML_BYTES, MAX_METADATA_BYTES,
                             MAX_PDF_BYTES, MAX_RECORDS, application_records,
                             checked_archive, load_json, pdf_records, pinned_sha,
                             read_member, retain)

CONTRACT = 'voxel_mapper.planning_source_bundle/v1'
MAX_INVENTORY_BYTES = 64_000_000
MAX_CATALOGUES = 32
MAX_INVENTORIES = 32


class IncompleteBundle(ValueError):
    def __init__(self, report):
        super().__init__('Bundle source files absent or metadata-only; explicit partial mode required')
        self.report = report


def _encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def _bounded_file(path, limit):
    path = Path(path)
    if path.stat().st_size > limit:
        raise ValueError('Source file byte budget exceeded: ' + path.name)
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Source file changed/exceeded byte budget')
    return data


def _descriptor(kind, data, prefix='metadata', extension='json'):
    sha = hashlib.sha256(data).hexdigest()
    return {'kind': kind, 'member': f'{prefix}/{kind}-{sha}.{extension}', 'sha256': sha, 'size': len(data)}


def _catalogue_records(catalogues, hosts):
    documents, applications = [], []
    for kind, data in catalogues:
        if kind == 'pdf_catalogue':
            documents.extend(pdf_records(load_json(data), hosts, allow_unpinned=True))
        elif kind == 'application_catalogue':
            applications.extend(application_records(load_json(data), hosts, allow_unpinned=True))
        else:
            raise ValueError('Unsupported source catalogue kind')
    if len(documents) > MAX_RECORDS or len(applications) > MAX_RECORDS:
        raise ValueError('Combined source catalogue record budget exceeded')
    urls, references = {}, {}
    for record in documents:
        pin = record.get('sha256')
        previous = urls.get(record['url'])
        if pin and previous and pin != previous:
            raise ValueError('Conflicting PDF hashes for one official URL')
        if pin:
            urls[record['url']] = pin
    for record in applications:
        identity = (record['url'], record.get('cached_page_sha256'))
        if record['reference'] in references and references[record['reference']] != identity:
            raise ValueError('Conflicting application snapshots')
        references[record['reference']] = identity
    return documents, applications


def _expected_sources(documents, applications):
    expected = {r['file']: {'member': r['file'], 'sha256': r['sha256'], 'kind': 'pdf'}
                for r in documents if r.get('sha256')}
    expected.update({r['cached_page']: {'member': r['cached_page'], 'sha256': r['cached_page_sha256'],
                                      'kind': 'application_html'}
                     for r in applications if r.get('cached_page_sha256')})
    return expected


def _inventory(data, pdf_shas):
    if len(data) > MAX_INVENTORY_BYTES:
        raise ValueError('Inspection inventory byte budget exceeded')
    seen, sources = set(), set()
    allowed = {'document_sha256', 'page', 'document_pages', 'frame', 'width_points', 'height_points',
               'rotation', 'native_text_sha256', 'native_text_excerpt', 'raw_vector_path_count',
               'status', 'world_geometry_additions'}
    for line in data.splitlines():
        if not line.strip():
            continue
        if len(line) > 1_000_000 or len(seen) >= 100_000:
            raise ValueError('Inspection row/page budget exceeded')
        row = load_json(line)
        if not isinstance(row, dict) or set(row) - allowed:
            raise ValueError('Portable page inventory fields required; no local paths or approvals')
        sha = pinned_sha(row.get('document_sha256'))
        page, count = row.get('page'), row.get('document_pages')
        if (sha not in pdf_shas or type(page) is not int or type(count) is not int
                or not 1 <= page <= count <= 100_000 or (sha, page) in seen
                or row.get('status') != 'page_inventory_only' or row.get('world_geometry_additions') != 0):
            raise ValueError('Source-bound unverified page inventory required')
        seen.add((sha, page))
        sources.add(sha)
    return sorted(sources), len(seen)


def _completeness(documents, applications, files):
    missing = [{**f, 'status': 'missing'} for f in files if f['status'] == 'missing']
    metadata_only = ([{'kind': 'pdf', 'url': r['url'], 'status': 'metadata_only'}
                      for r in documents if not r.get('sha256')]
                     + [{'kind': 'application_html', 'url': r['url'], 'reference': r['reference'],
                         'status': 'metadata_only'} for r in applications if not r.get('cached_page_sha256')])
    counts = {'catalogue_records': len(documents), 'application_records': len(applications),
              'metadata_only_records': len(metadata_only)}
    for kind, label in (('pdf', 'pdf_blobs'), ('application_html', 'application_pages')):
        counts['expected_' + label] = sum(f['kind'] == kind for f in files)
        counts['retained_' + label] = sum(f['kind'] == kind and f['status'] == 'retained' for f in files)
        counts['missing_' + label] = sum(f['kind'] == kind and f['status'] == 'missing' for f in files)
    return {'status': 'partial_sources' if missing or metadata_only else 'catalogued_sources_complete',
            'counts': counts, 'missing_sources': missing, 'metadata_only_sources': metadata_only,
            'discovery_completeness': 'Not implied by bundle completion; catalogue scope and dates still apply',
            'world_geometry_additions': 0, 'live_downloads': 0}


def _require_complete(report, allow_partial):
    if type(allow_partial) is not bool:
        raise ValueError('allow_partial must be a boolean')
    if report['status'] == 'partial_sources' and not allow_partial:
        raise IncompleteBundle(report)


def _zip_write(target, name, data):
    # Deterministic ZIP metadata makes copies with the same evidence share a pin.
    item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    item.compress_type = zipfile.ZIP_DEFLATED
    item.external_attr = 0o100644 << 16
    target.writestr(item, data)


def create_bundle(source, archive, hosts, *, catalogues, applications=(), provenance,
                  inventories=(), allow_partial=False):
    """Package exact catalogue bytes, pinned originals, provenance and JSONL inventories."""
    hosts = set(hosts)
    if not hosts or not 1 <= len(catalogues) + len(applications) <= MAX_CATALOGUES:
        raise ValueError('Explicit portal hosts and bounded catalogues required')
    if len(inventories) > MAX_INVENTORIES:
        raise ValueError('Inspection inventory count budget exceeded')
    provenance_data = provenance if isinstance(provenance, bytes) else _encoded(provenance)
    provenance = load_json(provenance_data)
    if (not isinstance(provenance, dict) or provenance.get('evidence_kind') not in
            ('real', 'fixture', 'metadata_only', 'mixed') or not isinstance(provenance.get('origin'), str)
            or not provenance['origin'].strip()):
        raise ValueError('Provenance requires evidence_kind and a nonempty origin')
    source = Path(source).resolve()
    metadata, descriptors, raw_catalogues = {}, [], []
    for kind, paths in (('pdf_catalogue', catalogues), ('application_catalogue', applications)):
        for path in paths:
            data = _bounded_file(path, MAX_METADATA_BYTES)
            descriptor = _descriptor(kind, data)
            if descriptor['member'] not in metadata:
                descriptors.append(descriptor)
                metadata[descriptor['member']] = data
                raw_catalogues.append((kind, data))
    documents, app_records = _catalogue_records(raw_catalogues, hosts)
    expected = _expected_sources(documents, app_records)
    files, originals = [], {}
    total = sum(len(data) for data in metadata.values())
    for name, record in sorted(expected.items()):
        limit = MAX_PDF_BYTES if record['kind'] == 'pdf' else MAX_HTML_BYTES
        candidates = [source / name]
        if record['kind'] == 'pdf':
            candidates.append(source / 'planning-documents' / Path(name).name)
        path = next((p for p in candidates if p.exists()), None)
        if path is None:
            files.append({**record, 'status': 'missing', 'size': None})
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError('Original source path escapes input directory or is a link')
        data = _bounded_file(path, limit)
        if hashlib.sha256(data).hexdigest() != record['sha256']:
            raise ValueError('Corrupt original source; checksum mismatch: ' + name)
        if record['kind'] == 'pdf' and not data.startswith(b'%PDF-'):
            raise ValueError('Original PDF header mismatch')
        files.append({**record, 'status': 'retained', 'size': len(data)})
        originals[name] = path
        total += len(data)
        if total > MAX_ARCHIVE_BYTES:
            raise ValueError('Bundle expanded-byte budget exceeded')
    inspections = []
    for path in inventories:
        data = _bounded_file(path, MAX_INVENTORY_BYTES)
        sources, pages = _inventory(data, {r['sha256'] for r in files if r['kind'] == 'pdf'})
        descriptor = {**_descriptor('page_inventory', data, 'inspection', 'jsonl'),
                      'source_sha256s': sources, 'pages': pages, 'authority': 'derived_evidence_only'}
        if descriptor['member'] not in metadata:
            inspections.append(descriptor)
            metadata[descriptor['member']] = data
            total += len(data)
    if len(provenance_data) > MAX_METADATA_BYTES:
        raise ValueError('Provenance byte budget exceeded')
    provenance_descriptor = _descriptor('provenance', provenance_data)
    metadata[provenance_descriptor['member']] = provenance_data
    report = _completeness(documents, app_records, files)
    _require_complete(report, allow_partial)
    manifest = {'schema_version': 1, 'contract': CONTRACT, 'catalogues': descriptors,
                'files': files, 'provenance': provenance_descriptor, 'inspections': inspections}
    manifest_data = _encoded(manifest)
    if len(manifest_data) > MAX_METADATA_BYTES or total + len(provenance_data) + len(manifest_data) > MAX_ARCHIVE_BYTES:
        raise ValueError('Bundle manifest/expanded-byte budget exceeded')
    archive = Path(archive)
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.is_symlink():
        raise ValueError('Bundle output cannot be a link')
    temporary = archive.with_suffix('.' + uuid.uuid4().hex + '.partial')
    try:
        with zipfile.ZipFile(temporary, 'w') as target:
            _zip_write(target, 'bundle.json', manifest_data)
            for name, data in sorted(metadata.items()):
                _zip_write(target, name, data)
            for record in files:
                if record['status'] != 'retained':
                    continue
                name = record['member']
                data = _bounded_file(originals[name], MAX_PDF_BYTES if record['kind'] == 'pdf' else MAX_HTML_BYTES)
                if len(data) != record['size'] or hashlib.sha256(data).hexdigest() != record['sha256']:
                    raise ValueError('Original source changed while creating bundle')
                _zip_write(target, name, data)
        with temporary.open('rb') as stream:
            pin = hashlib.file_digest(stream, 'sha256').hexdigest()
        # Exercise the reader against the completed temporary archive before publication.
        verify_bundle(temporary, pin, hosts, allow_partial=allow_partial)
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    report.update(contract=CONTRACT, archive_sha256=pin, archive_bytes=archive.stat().st_size,
                  evidence_kind=provenance['evidence_kind'], inspection_inventories=len(inspections))
    archive.with_suffix(archive.suffix + '.sha256').write_text(pin + '  ' + archive.name + '\n', encoding='utf-8')
    archive.with_suffix(archive.suffix + '.report.json').write_bytes(_encoded(report))
    return report


def _read_descriptor(source, index, descriptor, kind, prefix='metadata', extension='json', limit=MAX_METADATA_BYTES):
    if not isinstance(descriptor, dict) or descriptor.get('kind') != kind:
        raise ValueError('Bundle member descriptor kind mismatch')
    sha = pinned_sha(descriptor.get('sha256'))
    name = f'{prefix}/{kind}-{sha}.{extension}'
    if descriptor.get('member') != name or type(descriptor.get('size')) is not int:
        raise ValueError('Content-addressed bounded bundle descriptor required')
    if name not in index:
        raise ValueError('Required bundle metadata/inspection member absent: ' + name)
    data = read_member(source, index[name], limit, sha)
    if len(data) != descriptor['size']:
        raise ValueError('Bundle descriptor size mismatch')
    return data


def _read_bundle(source, index, hosts):
    if 'bundle.json' not in index or not hosts:
        raise ValueError('Bundle manifest and explicit official hosts required')
    manifest = load_json(read_member(source, index['bundle.json'], MAX_METADATA_BYTES))
    if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int
            or manifest.get('schema_version') != 1 or manifest.get('contract') != CONTRACT):
        raise ValueError('Unsupported original-source bundle contract')
    catalogues, files, inspections = (manifest.get(k) for k in ('catalogues', 'files', 'inspections'))
    if (not isinstance(catalogues, list) or not 1 <= len(catalogues) <= MAX_CATALOGUES
            or not isinstance(files, list) or len(files) > 2 * MAX_RECORDS
            or not isinstance(inspections, list) or len(inspections) > MAX_INVENTORIES):
        raise ValueError('Bounded bundle catalogue/file/inspection lists required')
    raw, selected = [], {'bundle.json'}
    for descriptor in catalogues:
        kind = descriptor.get('kind') if isinstance(descriptor, dict) else None
        if kind not in ('pdf_catalogue', 'application_catalogue'):
            raise ValueError('Unsupported bundle catalogue')
        data = _read_descriptor(source, index, descriptor, kind)
        if descriptor['member'] in selected:
            raise ValueError('Duplicate bundle descriptor')
        selected.add(descriptor['member'])
        raw.append((kind, data))
    documents, applications = _catalogue_records(raw, set(hosts))
    expected = _expected_sources(documents, applications)
    actual = {}
    for record in files:
        if not isinstance(record, dict) or record.get('member') not in expected or record['member'] in actual:
            raise ValueError('Unexpected/duplicate bundle source descriptor')
        name = record['member']
        if any(record.get(k) != v for k, v in expected[name].items()):
            raise ValueError('Bundle source descriptor differs from pinned catalogue')
        if record.get('status') not in ('missing', 'retained'):
            raise ValueError('Bundle original retention state required')
        if record['status'] == 'missing':
            if record.get('size') is not None or name in index:
                raise ValueError('Missing source descriptor has retained bytes or size')
        else:
            if type(record.get('size')) is not int or record['size'] <= 0:
                raise ValueError('Retained source size required')
            if name in index:
                limit = MAX_PDF_BYTES if record['kind'] == 'pdf' else MAX_HTML_BYTES
                data = read_member(source, index[name], limit, record['sha256'])
                if len(data) != record['size'] or (record['kind'] == 'pdf' and not data.startswith(b'%PDF-')):
                    raise ValueError('Retained source size/PDF header mismatch')
                selected.add(name)
            else:
                record = {**record, 'status': 'missing', 'absence': 'declared_retained_member_absent'}
        actual[name] = record
    if set(actual) != set(expected):
        raise ValueError('Bundle source inventory omits catalogue pins')
    provenance_descriptor = manifest.get('provenance')
    provenance = load_json(_read_descriptor(source, index, provenance_descriptor, 'provenance'))
    if (not isinstance(provenance, dict) or provenance.get('evidence_kind') not in ('real', 'fixture', 'metadata_only', 'mixed')
            or not isinstance(provenance.get('origin'), str) or not provenance['origin'].strip()):
        raise ValueError('Bundle evidence provenance required')
    selected.add(provenance_descriptor['member'])
    retained_shas = {r['sha256'] for r in actual.values() if r['kind'] == 'pdf' and r['status'] == 'retained'}
    inspection_reports = []
    for descriptor in inspections:
        data = _read_descriptor(source, index, descriptor, 'page_inventory', 'inspection', 'jsonl', MAX_INVENTORY_BYTES)
        sources, pages = _inventory(data, {r['sha256'] for r in actual.values() if r['kind'] == 'pdf'})
        if (descriptor.get('source_sha256s') != sources or descriptor.get('pages') != pages
                or descriptor.get('authority') != 'derived_evidence_only' or descriptor['member'] in selected):
            raise ValueError('Inspection inventory source binding mismatch')
        selected.add(descriptor['member'])
        inspection_reports.append({**descriptor, 'unavailable_original_sha256s': sorted(set(sources) - retained_shas)})
    if set(index) != selected:
        raise ValueError('Unlisted bundle members are not allowed')
    report = _completeness(documents, applications, list(actual.values()))
    report.update(contract=CONTRACT, evidence_kind=provenance['evidence_kind'], provenance=provenance,
                  application_catalogue_supplied=any(d['kind'] == 'application_catalogue' for d in catalogues),
                  bundled_inspections=inspection_reports)
    return manifest, documents, applications, actual, report


@contextmanager
def _validated(archive, pin, hosts, allow_partial):
    with checked_archive(archive, pin) as (source, index):
        result = _read_bundle(source, index, hosts)
        result[-1]['archive_sha256'] = pin
        _require_complete(result[-1], allow_partial)
        yield source, index, result


def verify_bundle(archive, expected_sha256, hosts, *, allow_partial=False):
    with _validated(archive, expected_sha256, hosts, allow_partial) as (_, _, result):
        return result[-1]


def import_bundle(corpus, archive, expected_sha256, hosts, *, allow_partial=False):
    with _validated(archive, expected_sha256, hosts, allow_partial) as (source, index, result):
        manifest, documents, applications, files, report = result
        corpus.validate_applications(applications, hosts)
        records = [{**r, 'retained_archive_sha256': expected_sha256,
                    'acquisition_provenance': ('checksum_verified_retained_bundle; no live download'
                                               if r.get('file') in files and files[r['file']]['status'] == 'retained'
                                               else 'retained_bundle_catalogue_only; PDF_not_retained')} for r in documents]
        corpus.ingest(records, hosts)
        corpus.ingest_applications(applications, hosts)
        copied = resumed = html_copied = html_resumed = 0
        for name, record in files.items():
            if record['status'] != 'retained':
                continue
            data = read_member(source, index[name], MAX_PDF_BYTES if record['kind'] == 'pdf' else MAX_HTML_BYTES, record['sha256'])
            changed = retain(corpus.root, name, data, record['sha256'])
            with corpus.db:
                if record['kind'] == 'pdf':
                    copied += int(changed)
                    resumed += int(not changed)
                    corpus.db.execute("UPDATE downloads SET status='downloaded',sha=?,size=?,error=NULL WHERE expected_sha=?",
                                      (record['sha256'], len(data), record['sha256']))
                else:
                    html_copied += int(changed)
                    html_resumed += int(not changed)
                    corpus.db.execute("UPDATE applications SET status='retained',sha=?,error=NULL WHERE expected_sha=?",
                                      (record['sha256'], record['sha256']))
        for descriptor in [*manifest['catalogues'], manifest['provenance'], *manifest['inspections']]:
            name = descriptor['member']
            data = read_member(source, index[name], MAX_INVENTORY_BYTES if name.startswith('inspection/') else MAX_METADATA_BYTES,
                               descriptor['sha256'])
            retain(corpus.root, f'bundles/{expected_sha256}/{name}', data, descriptor['sha256'])
        data = read_member(source, index['bundle.json'], MAX_METADATA_BYTES)
        retain(corpus.root, f'bundles/{expected_sha256}/bundle.json', data, hashlib.sha256(data).hexdigest())
    report = {**report, 'import_status': 'retained_bundle_imported', 'copied_blobs': copied, 'resumed_blobs': resumed,
              'copied_application_pages': html_copied, 'resumed_application_pages': html_resumed, 'allow_partial': allow_partial}
    (corpus.root / f'archive-{expected_sha256}.json').write_bytes(_encoded(report))
    return report


def replay_bundle(archive, expected_sha256, hosts, corpus_path, output, *,
                  allow_partial=False, max_pages=10_000, inspect=True):
    """Import pinned evidence, parse retained Alton pages and export native inventory offline."""
    from .planning_bulk import Corpus
    from .alton_discovery import HOST, parse_attachments
    if type(max_pages) is not int or not 1 <= max_pages <= 100_000 or type(inspect) is not bool:
        raise ValueError('Bounded replay page budget and boolean inspection mode required')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    # Preflight before creating or changing corpus records.
    verify_bundle(archive, expected_sha256, hosts, allow_partial=allow_partial)
    corpus = Corpus(corpus_path)
    try:
        imported = import_bundle(corpus, archive, expected_sha256, hosts, allow_partial=allow_partial)
        bundled_inspections = []
        for descriptor in imported['bundled_inspections']:
            path = corpus.root / 'bundles' / expected_sha256 / descriptor['member']
            data = _bounded_file(path, MAX_INVENTORY_BYTES)
            member = f"bundled-inspections/{descriptor['sha256']}.jsonl"
            retain(output, member, data, descriptor['sha256'])
            bundled_inspections.append({**descriptor, 'exported_file': member})
        applications = {'parsed_pages': 0, 'attachment_links': 0, 'failures': []}
        for reference, raw, sha in corpus.db.execute('SELECT reference,record,sha FROM applications ORDER BY reference').fetchall():
            record = json.loads(raw)
            if not sha:
                continue
            path = corpus.root / 'files' / f'{sha}.html'
            try:
                from .source_archive import official_url
                official_url(record['url'], [HOST])
                data = _bounded_file(path, MAX_HTML_BYTES)
                if hashlib.sha256(data).hexdigest() != sha:
                    raise ValueError('Retained application HTML corrupt; checksum mismatch')
                documents = parse_attachments(data, record)
                for document in documents:
                    known = corpus.db.execute('SELECT expected_sha,sha FROM downloads WHERE url=?',
                                              (document['url'],)).fetchone()
                    pin = (known[0] or known[1]) if known else None
                    if pin:
                        # Re-parsing a page must not erase the original PDF pin
                        # when updating its attachment title/context record.
                        document.update(sha256=pin, file=f'files/{pin}.pdf',
                                        hash_provenance='preserved_retained_catalogue_pin')
                corpus.ingest(documents, [HOST])
                with corpus.db:
                    corpus.db.execute("UPDATE applications SET status='discovered',error=NULL WHERE reference=?", (reference,))
                applications['parsed_pages'] += 1
                applications['attachment_links'] += len(documents)
            except (OSError, ValueError, KeyError) as error:
                applications['failures'].append({'reference': reference, 'reason': str(error)})
        availability = corpus.acquire(offline=True)
        inspection = corpus.inspect(max_pages) if inspect else {'status': 'not_run', 'inspection_errors': []}
        exported = corpus.export_inspection(output / 'page-inventory.jsonl')
        progress = []
        for (sha,) in corpus.db.execute("SELECT DISTINCT sha FROM downloads WHERE status='downloaded' ORDER BY sha"):
            summaries = [json.loads(r) for (r,) in corpus.db.execute('SELECT summary FROM pages WHERE sha=?', (sha,))]
            total = max((r['document_pages'] for r in summaries), default=None)
            progress.append({'document_sha256': sha, 'inspected_pages': len(summaries), 'document_pages': total,
                             'status': ('not_inspected' if not summaries else
                                        'complete' if len(summaries) == total else 'partial')})
        rows = [json.loads(r) for (r,) in corpus.db.execute('SELECT record FROM documents ORDER BY id')]
        for row in rows:
            # Files are always addressed relative to the replay corpus, never the old machine.
            if row.get('sha256'):
                row['file'] = f"files/{row['sha256']}.pdf"
            row.pop('local_pdf', None)
        (output / 'replayed-catalogue.json').write_bytes(_encoded({'schema_version': 1, 'entries': rows}))
        app_rows = [json.loads(r) for (r,) in corpus.db.execute('SELECT record FROM applications ORDER BY reference')]
        (output / 'replayed-applications.json').write_bytes(_encoded({'schema_version': 1, 'applications': app_rows}))
        report = {'status': 'offline_source_replay', 'archive_sha256': expected_sha256,
                  'sources': imported, 'availability': availability, 'application_replay': applications,
                  'inspection': inspection, 'exported_inventory': exported,
                  'inspection_complete_for_retained_pdfs': inspect and all(r['status'] == 'complete' for r in progress),
                  'inspection_progress': progress,
                  'inspection_page_budget_reached': inspection.get('run_inspected_pages', 0) >= max_pages,
                  'inspection_mode': 'recomputed_from_originals' if inspect else 'bundled_inventory_preserved_without_renderer',
                  'bundled_inspections': bundled_inspections,
                  'complete_council_discovery': False, 'verified_registrations': 0,
                  'world_geometry_additions': 0, 'live_downloads': 0}
        (output / 'replay-report.json').write_bytes(_encoded(report))
        return report
    finally:
        corpus.close()


def capture_acquisition(source, archive, hosts, *, origin, inventory=None, evidence_kind='real'):
    """Retain generator originals even when the subsequent geometry gate fails."""
    source = Path(source)
    data_root = Path(__file__).parent / 'data'
    catalogue_path, applications_path = (data_root / name for name in
                                        ('alton-planning-catalogue.json', 'alton-applications.json'))
    catalogue = load_json(_bounded_file(catalogue_path, MAX_METADATA_BYTES))
    applications = load_json(_bounded_file(applications_path, MAX_METADATA_BYTES))
    provenance = {'evidence_kind': evidence_kind, 'origin': origin,
                  'hash_policy': 'historical pins or observed original bytes; no independent source/geometry qualification',
                  'historical_catalogue_sha256': hashlib.sha256(catalogue_path.read_bytes()).hexdigest(),
                  'historical_applications_sha256': hashlib.sha256(applications_path.read_bytes()).hexdigest()}
    inspection_path = source / 'alton-planning-inspection.json'
    if inspection_path.is_file():
        inspection_data = _bounded_file(inspection_path, MAX_INVENTORY_BYTES)
        inspection = load_json(inspection_data)
        provenance['acquisition_report_sha256'] = hashlib.sha256(inspection_data).hexdigest()
        # Keep the recovered catalogue and all newly observed original attachments.
        by_url = {r['url']: r['sha256'] for r in catalogue['entries']}
        for row in inspection.get('documents', []):
            if row.get('sha256'):
                sha = pinned_sha(row['sha256'])
                if row['url'] in by_url and by_url[row['url']] != sha:
                    raise ValueError('Acquisition conflicts with historical PDF pin; recatalogue explicitly')
                if row['url'] not in by_url:
                    keys = ('url', 'title', 'applicationReference', 'application_context', 'role', 'state', 'hash_provenance')
                    catalogue['entries'].append({**{k: row[k] for k in keys if k in row},
                                                 'sha256': sha, 'file': f'files/{sha}.pdf'})
                    by_url[row['url']] = sha
    discovery_path = source / 'alton-planning-discovery.json'
    if discovery_path.is_file():
        raw = _bounded_file(discovery_path, MAX_INVENTORY_BYTES)
        provenance['application_discovery_report_sha256'] = hashlib.sha256(raw).hexdigest()
        observed = {r['reference']: r for r in load_json(raw).get('applications', [])}
        for row in applications['applications']:
            if row['reference'] in observed:
                sha = pinned_sha(observed[row['reference']]['page_sha256'])
                row['historical_cached_page_sha256'] = row.get('cached_page_sha256')
                row.update(cached_page_sha256=sha, cached_page=f'files/{sha}.html',
                           snapshot_provenance=observed[row['reference']].get('acquisition_method', 'observed_retained_page'))
    archive = Path(archive)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=archive.parent) as temp:
        root = Path(temp)
        (root / 'catalogue.json').write_bytes(_encoded(catalogue))
        (root / 'applications.json').write_bytes(_encoded(applications))
        return create_bundle(source, archive, hosts, catalogues=[root / 'catalogue.json'],
                             applications=[root / 'applications.json'], provenance=provenance,
                             inventories=[inventory] if inventory else [], allow_partial=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    stages = parser.add_subparsers(dest='stage', required=True)
    for stage in ('create', 'capture', 'verify', 'replay'):
        p = stages.add_parser(stage)
        p.add_argument('--bundle', required=True)
        p.add_argument('--official-host', action='append', required=True)
        if stage in ('create', 'capture'):
            p.add_argument('--source', required=True)
        if stage == 'create':
            p.add_argument('--catalogue', action='append', required=True)
            p.add_argument('--applications', action='append', default=[])
            p.add_argument('--provenance', required=True, help='JSON object with evidence_kind and origin')
            p.add_argument('--inventory', action='append', default=[])
        if stage == 'capture':
            p.add_argument('--origin', required=True)
            p.add_argument('--inventory')
            p.add_argument('--evidence-kind', choices=('real', 'fixture', 'metadata_only', 'mixed'), default='real')
        else:
            p.add_argument('--allow-partial', action='store_true')
        if stage in ('verify', 'replay'):
            p.add_argument('--sha256', required=True)
            p.add_argument('--output', required=True)
        if stage == 'replay':
            p.add_argument('--corpus', required=True)
            p.add_argument('--max-pages', type=int, default=10_000)
            p.add_argument('--no-inspect', action='store_true', help='Preserve bundled inventory without rendering originals')
    args = parser.parse_args()
    try:
        if args.stage == 'create':
            report = create_bundle(args.source, args.bundle, args.official_host, catalogues=args.catalogue,
                                   applications=args.applications, provenance=_bounded_file(args.provenance, MAX_METADATA_BYTES),
                                   inventories=args.inventory, allow_partial=args.allow_partial)
        elif args.stage == 'capture':
            report = capture_acquisition(args.source, args.bundle, args.official_host, origin=args.origin,
                                         inventory=args.inventory, evidence_kind=args.evidence_kind)
        elif args.stage == 'verify':
            report = verify_bundle(args.bundle, args.sha256, args.official_host, allow_partial=args.allow_partial)
            Path(args.output).mkdir(parents=True, exist_ok=True)
            (Path(args.output) / 'verify-report.json').write_bytes(_encoded(report))
        else:
            report = replay_bundle(args.bundle, args.sha256, args.official_host, args.corpus, args.output,
                                   allow_partial=args.allow_partial, max_pages=args.max_pages, inspect=not args.no_inspect)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        report = {'status': 'rejected', 'reason': str(error), 'live_downloads': 0, 'world_geometry_additions': 0}
        if isinstance(error, IncompleteBundle):
            report['source_diagnostics'] = error.report
        if getattr(args, 'output', None):
            Path(args.output).mkdir(parents=True, exist_ok=True)
            (Path(args.output) / 'rejection-report.json').write_bytes(_encoded(report))
        print(json.dumps(report, indent=2))
        raise SystemExit(2)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
