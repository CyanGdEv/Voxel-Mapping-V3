"""Acquire only site/section attachments observed in the retained SW8 page."""
import argparse, hashlib, html, json, re
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import fitz

PAGE_SHA = 'da203bc855a135f2cd6f2850db2b45cfac213a7d31ebf90e4f1eb8234f9a8bb3'
HOST = 'publicaccess.staffsmoorlands.gov.uk'
ATTACHMENTS = [160141,160143,160144,160145,*range(160146,160154),163927,163928,163929,163930,163931,163932,163933,163934]


def acquire(page_path, output):
    raw = Path(page_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != PAGE_SHA:
        raise ValueError('Pinned SW8 application page required')
    # The retained page declares UTF-8 but includes an invalid pound byte.
    # Match ASCII link structure in bytes, decoding only the attachment label.
    matches = {int(m[1]): html.unescape(m[2].decode('utf-8', errors='replace'))
               for m in re.finditer(rb"AppBlobImage\('([0-9]+)'\);[^>]*>([^<]+)</a>", raw)}
    dates = {int(m[2]): m[1].decode('ascii') for m in re.finditer(
        rb"<td>(\d{2}/\d{2}/\d{4})</td>\s*<td><a href=\"javascript:AppBlobImage\('([0-9]+)'\)", raw)}
    if not set(ATTACHMENTS) <= matches.keys():
        raise ValueError('Every requested attachment must be an observed link')
    out = Path(output); out.mkdir(parents=True, exist_ok=True)
    def fetch(i):
        url = f'http://{HOST}/portal/servlets/AttachmentShowServlet?ImageName={i}'
        row = {'attachment_id': i, 'attachment_label': matches[i], 'url': url,
               'upload_date_as_listed': dates.get(i)}
        try:
            with urlopen(Request(url, headers={'User-Agent':'Mozilla/5.0'}), timeout=30) as response:
                if urlparse(response.url).hostname != HOST:
                    raise ValueError('Unexpected document redirect host')
                data = response.read(20_000_001)
                if len(data) > 20_000_000 or not data.startswith(b'%PDF-'):
                    raise ValueError('Bounded PDF required')
                sha = hashlib.sha256(data).hexdigest()
                row.update(http_status=response.status, bytes=len(data), sha256=sha,
                           content_type=response.headers.get('Content-Type'), final_url=response.url)
            with fitz.open(stream=data, filetype='pdf') as document:
                if len(document) > 100:
                    raise ValueError('Document page budget exceeded')
                row['pages'] = len(document)
            path = out / (sha + '.pdf')
            if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('Existing content-addressed blob is corrupt')
            path.write_bytes(data)
            row['status'] = 'downloaded'
        except Exception as exc:
            row.update(status='failed', reason=str(exc))
        return row
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(fetch, ATTACHMENTS))
    result = {'application_reference':'SMD/2016/0315', 'application_page_sha256':PAGE_SHA,
              'retrieved_date':datetime.now(timezone.utc).date().isoformat(), 'documents':rows,
              'limits':{'concurrent_requests':4,'max_pdf_bytes':20_000_000,'max_pdf_pages':100},
              'limitations':['Attachment order/label does not establish final approval or as-built status.',
                             'Original and revised plans are separate source versions; no geometry is automatically accepted.']}
    (out / 'download-receipt.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--application-page', required=True); parser.add_argument('--output', required=True)
    args = parser.parse_args(); result = acquire(args.application_page, args.output)
    for row in result['documents']:
        print(row['attachment_id'], row['attachment_label'], row['status'], row.get('reason',''))

if __name__ == '__main__':
    main()
