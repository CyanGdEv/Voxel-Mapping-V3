"""Recover and inspect the historical official Alton planning corpus automatically.

Historical catalogue entries are not proof of current or as-built geometry.
"""
import hashlib
import io
import json
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


def acquire_alton(output, bounds=None, cache=None, max_documents=153, max_pages=2):
    # Import lazily: council owns the common bounded PDF inspection routine.
    from .council import inspect_pdf
    from .alton_registration import inspect_axis_alignment
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
    entries = catalogue['entries'][:max_documents]
    deadline = time.monotonic()+900
    result['documents_omitted_by_budget'] = len(catalogue['entries'])-len(entries)
    with requests.Session() as session:
        session.headers.update({'User-Agent': USER_AGENT})
        for entry in entries:
            if time.monotonic() > deadline:
                result['documents_omitted_by_budget'] = len(catalogue['entries'])-len(result['documents'])
                result['failures'].append({'reason': '15-minute planning acquisition budget reached'})
                break
            row = dict(entry)
            try:
                url = urlparse(entry['url'])
                if url.scheme != 'https' or url.hostname != HOST:
                    raise ValueError('Expected an official HTTPS drawing URL')
                if cache:
                    path = (cache/entry['file']).resolve()
                    if not path.is_relative_to(cache):
                        raise ValueError('Cache path escapes corpus directory')
                    if path.stat().st_size > 10_000_000:
                        raise ValueError('Document exceeds 10 MB inspection budget')
                    payload = path.read_bytes()
                else:
                    payload = download_pdf(session, entry['url'])
                if hashlib.sha256(payload).hexdigest() != entry['sha256']:
                    raise ValueError('Recovered document checksum mismatch; changed document needs recataloguing')
                row['inspection'] = inspect_pdf(payload, max_pages=max_pages, bounds=bounds,
                                                document_title=entry['title'], max_ocr_pages=0)
                if bounds and entry['role'] in ('site-plan', 'landscape-plan', 'topographical-survey', 'terrain-or-drainage'):
                    reader = None
                    for page in row['inspection']['pages']:
                        if sum(a.get('label_count', 0) for a in page['native_suffix_grid_inspection'].get('axis_checks', {}).values()) >= 6:
                            reader = reader or PdfReader(io.BytesIO(payload))
                            page['native_axis_alignment'] = inspect_axis_alignment(reader.pages[page['page']-1], bounds)
                row['status'] = 'inspected'
            except (OSError, ValueError, PdfReadError, requests.RequestException) as error:
                row['status'] = 'unavailable'
                row['reason'] = str(error)
                result['failures'].append({'url': entry['url'], 'reason': str(error)})
            result['documents'].append(row)
    result['status'] = 'partial' if result['failures'] or result['documents_omitted_by_budget'] else 'checked'
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
