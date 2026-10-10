"""Recover and inspect the historical official Alton planning corpus automatically.

Historical catalogue entries are not proof of current or as-built geometry.
"""
import hashlib
import io
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .acquisition import USER_AGENT

HOST = 'publicaccess.staffsmoorlands.gov.uk'
SOURCE = {'id': 'staffordshire-moorlands-planning',
          'url': 'https://' + HOST + '/portal/',
          'license': 'unconfirmed-drawing-reuse',
          'attribution': 'Staffordshire Moorlands planning records; individual drawing authors'}


def is_park_application(entry):
    # References to staff accommodation elsewhere are not park-site evidence.
    address_context = entry.get('application_context', '')[:200]
    return bool(re.search(r'\balton\s+towers\b', address_context, re.I)
                and re.search(r'\bfarley\s+lane\b', address_context, re.I))


def download_pdf(session, url, max_bytes=10_000_000):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != HOST:
        raise ValueError('Expected an official HTTPS drawing URL')
    response = session.get(url, timeout=(10, 30), stream=True, allow_redirects=False)
    try:
        response.raise_for_status()
        if 300 <= response.status_code < 400:
            raise ValueError('Drawing redirects require recataloguing')
        chunks, size = [], 0
        for chunk in response.iter_content(64*1024):
            size += len(chunk)
            if size > max_bytes:
                raise ValueError('Document exceeds 10 MB inspection budget')
            chunks.append(chunk)
        payload = b''.join(chunks)
        if not payload.startswith(b'%PDF-'):
            raise ValueError('Official endpoint did not return a PDF')
        return payload
    finally:
        response.close()


def acquire_alton(output, bounds=None, cache=None, max_documents=153, max_pages=2, application_references=None):
    # Import lazily: council owns the common bounded PDF inspection routine.
    from .council import inspect_pdf
    from .alton_registration import inspect_axis_alignment
    from .alton_discovery import discover_attachments, merge_discovered
    catalogue = json.loads((Path(__file__).parent/'data/alton-planning-catalogue.json').read_text())
    result = {'provider': SOURCE['id'], 'source': SOURCE, 'status': 'checked',
              'application_search': 'recovered_historical_catalogue',
              'catalogue_acquired_at': catalogue['acquired_at'],
              'applications': sorted({e['applicationReference'] for e in catalogue['entries']}),
              'documents': [], 'failures': [], 'geometry_records': [],
              'reuse_status': 'not_confirmed', 'geometry_replacements': 0,
              'limitations': [catalogue['coverage'],
                             'Approval is not as-built verification',
                             'Report vectors and PDF labels are not physical footprints']}
    cache = Path(cache).resolve() if cache else None
    relevant = [e for e in catalogue['entries'] if is_park_application(e)]
    if application_references:
        relevant = [e for e in relevant if e['applicationReference'] in set(application_references)]
        result['requested_application_references'] = sorted(set(application_references))
    result['applications'] = sorted({e['applicationReference'] for e in relevant})
    result['excluded_other_site_documents'] = [
        {'applicationReference': e['applicationReference'], 'url': e['url'],
         'reason': 'Recovered application context does not identify the Alton Towers park site'}
        for e in catalogue['entries'] if not is_park_application(e)]
    deadline = time.monotonic()+900
    with requests.Session() as session:
        session.headers.update({'User-Agent': USER_AGENT})
        discovery = discover_attachments(session, output, cache, deadline, application_references)
        result['attachment_discovery'] = {k: v for k, v in discovery.items() if k != 'documents'}
        result['application_search'] = 'historical_seed_full_attachment_pages'
        relevant = merge_discovered(relevant, discovery)
        result['discovered_document_count'] = len(relevant)
        result['uncached_discovered_documents'] = sum('file' not in e for e in relevant) if cache else 0
        # A recovered cache supplements live acquisition; it must not permanently
        # exclude section/elevation attachments missing from the old prefetch.
        def acquisition_priority(item):
            index, entry = item
            if cache and entry.get('file'):
                return (0, 0, 0, 0, index)
            role_priority = {'elevations': 0, 'floor-plan': 1}.get(entry.get('role'), 2)
            proposed = entry.get('state') == 'proposed' or bool(re.search(r'\bprop(?:osed)?\b', entry['title'], re.I))
            revised = bool(re.search(r'\b\d{3}[-/]\d{2}[-/]\d+[A-Z]\b', entry['title'], re.I))
            return (1, role_priority, 0 if proposed else 1, 0 if revised else 1, index)
        eligible = [entry for _, entry in sorted(enumerate(relevant), key=acquisition_priority)]
        network_failures = 0
        result['missing_download_attempts'] = 0
        result['documents_deferred_council_outage'] = 0
        entries = eligible[:max_documents]
        result['documents_omitted_by_budget'] = len(eligible)-len(entries)
        for entry in entries:
            if time.monotonic() > deadline:
                result['documents_omitted_by_budget'] = len(eligible)-len(result['documents'])
                result['failures'].append({'reason': '15-minute planning acquisition budget reached'})
                break
            row = dict(entry)
            downloading = False
            download_pending = False
            try:
                url = urlparse(entry['url'])
                if url.scheme != 'https' or url.hostname != HOST:
                    raise ValueError('Expected an official HTTPS drawing URL')
                if cache and entry.get('file'):
                    path = (cache/entry['file']).resolve()
                    if not path.is_relative_to(cache):
                        raise ValueError('Cache path escapes corpus directory')
                    if path.stat().st_size > 10_000_000:
                        raise ValueError('Document exceeds 10 MB inspection budget')
                    payload = path.read_bytes()
                else:
                    if network_failures >= 3:
                        row.update(status='deferred_council_outage',
                                   reason='Three consecutive official drawing download failures')
                        result['documents_deferred_council_outage'] += 1
                        result['documents'].append(row)
                        continue
                    downloading = True
                    download_pending = True
                    result['missing_download_attempts'] += 1
                    payload = download_pdf(session, entry['url'])
                    download_pending = False
                    network_failures = 0
                checksum = hashlib.sha256(payload).hexdigest()
                if entry.get('sha256') and checksum != entry['sha256']:
                    raise ValueError('Recovered document checksum mismatch; changed document needs recataloguing')
                row['sha256'] = checksum
                document_path = Path(output)/'planning-documents'/f'{checksum}.pdf'
                document_path.parent.mkdir(parents=True, exist_ok=True)
                document_path.write_bytes(payload)
                row['local_pdf'] = str(document_path.resolve())
                row['acquisition_method'] = 'official_download' if downloading else 'hash_checked_cache'
                row['hash_provenance'] = entry.get('hash_provenance',
                    'matches_recovered_document' if entry.get('sha256') else 'observed_current_download_only')
                row['inspection'] = inspect_pdf(payload, max_pages=max_pages, bounds=bounds,
                                                document_title=entry['title'], max_ocr_pages=0)
                for page in row['inspection']['pages']:
                    for reference in page['survey_reference_notes'].get('external_drawing_references', []):
                        # A matching attachment title is only a discovery candidate.
                        matches = [d['url'] for d in discovery['documents'] if
                                   re.search(r'\b'+re.escape(reference['drawing_number'])+r'\b', d['title']) and
                                   'survey' in d['title'].lower()]
                        reference['attachment_title_candidates'] = matches
                        reference['status'] = 'attachment_candidates_not_verified' if matches else 'not_listed_in_discovered_attachment_titles'
                if entry['role'] in ('site-plan', 'landscape-plan', 'floor-plan'):
                    try:
                        from .plan_boundaries import inspect_plan_boundaries
                        for page in row['inspection']['pages']:
                            page['plan_boundaries'] = inspect_plan_boundaries(payload, page['page']-1)
                    except (ImportError, ValueError, RuntimeError) as error:
                        row['boundary_extraction_failure'] = str(error)
                if bounds and entry['role'] in ('site-plan', 'landscape-plan', 'topographical-survey', 'terrain-or-drainage'):
                    reader = None
                    for page in row['inspection']['pages']:
                        if sum(a.get('label_count', 0) for a in page['native_suffix_grid_inspection'].get('axis_checks', {}).values()) >= 6:
                            reader = reader or PdfReader(io.BytesIO(payload))
                            page['native_axis_alignment'] = inspect_axis_alignment(reader.pages[page['page']-1], bounds)
                row['status'] = 'inspected'
            except (OSError, ValueError, PdfReadError, requests.RequestException) as error:
                if download_pending:
                    network_failures += 1
                row['status'] = 'unavailable'
                row['reason'] = str(error)
                result['failures'].append({'url': entry['url'], 'reason': str(error)})
            result['documents'].append(row)
    result['status'] = 'partial' if (result['failures'] or result['documents_omitted_by_budget'] or
                                   result['documents_deferred_council_outage'] or discovery['status'] == 'partial') else 'checked'
    from .mutiny_bay import source_inventory
    result['mutiny_bay'] = source_inventory(result['documents'])
    (Path(output)/'alton-planning-inspection.json').write_text(json.dumps(result, indent=2))
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Automatically inspect recovered Alton Towers planning PDFs')
    parser.add_argument('--cache', help='Recovered planning-prefetch-selected directory; otherwise fetch official URLs')
    parser.add_argument('--output', required=True)
    parser.add_argument('--max-documents', type=int, default=153)
    args = parser.parse_args()
    if not 1 <= args.max_documents <= 153:
        parser.error('max-documents must be between 1 and 153')
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    report = acquire_alton(output, [-1.913, 52.9765, -1.87, 53], args.cache, args.max_documents)
    print(json.dumps({'documents': len(report['documents']), 'failures': len(report['failures']),
                      'physical_geometry_records': len(report['geometry_records'])}))


if __name__ == '__main__':
    main()
