"""Bounded official application attachment discovery, including legacy JS links."""
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup
import requests

HOST = 'publicaccess.staffsmoorlands.gov.uk'


def document_role(title):
    lower = title.lower()
    if re.search(r'arboricultur|ecolog|bat\b|bird\b|photo|assessment|statement|report', lower):
        return 'context-report', 90
    if re.search(r'topograph|topolog|master land survey|\bsurvey\b', lower):
        return 'topographical-survey', 0
    if re.search(r'landscap|planting', lower):
        return 'landscape-plan', 20
    if re.search(r'site plan|\bga\b|general arrangement|ride layout|track layout|path proposal', lower):
        return 'site-plan', 10
    if re.search(r'floor plan', lower):
        return 'floor-plan', 30
    if re.search(r'elevation|section', lower):
        return 'elevations', 40
    return 'unknown', 80


def parse_attachments(html, application, max_documents=2000):
    if len(html) > 2_000_000:
        raise ValueError('Application HTML exceeds 2 MB budget')
    soup = BeautifulSoup(html, 'html.parser')
    if application['reference'] not in soup.get_text(' ', strip=True):
        raise ValueError('Application page does not contain expected reference')
    documents = {}
    for anchor in soup.select('a[href]'):
        href = anchor['href'].strip()
        legacy = re.fullmatch(r"javascript:\s*AppBlobImage\(\s*['\"]([0-9]+)['\"]\s*\);?", href, re.I)
        if legacy:
            url = 'https://'+HOST+'/portal/servlets/AttachmentShowServlet?ImageName='+legacy[1]
        else:
            url = urljoin(application['url'], href)
            parsed = urlparse(url)
            if (parsed.scheme != 'https' or parsed.hostname != HOST or
                    parsed.path != '/portal/servlets/AttachmentShowServlet' or
                    not re.fullmatch(r'[0-9]+', parse_qs(parsed.query).get('ImageName', [''])[0])):
                continue
        title = anchor.get_text(' ', strip=True)[:1000]
        if not title:
            continue
        role, priority = document_role(title)
        lower = title.lower()
        state = ('existing' if re.search(r'\bexisting\b|\bextg\b', lower) else
                 'proposed' if re.search(r'\bproposed\b|\bproposal', lower) else 'unknown')
        documents.setdefault(url, {'url': url, 'title': title, 'role': role, 'priority': priority,
                                  'state': state, 'applicationReference': application['reference'],
                                  'application_context': application['application_context'],
                                  'discovery_source': application['url']})
        if len(documents) > max_documents:
            raise ValueError('Application attachment budget exceeded')
    return sorted(documents.values(), key=lambda d: (d['priority'], d['title'], d['url']))


def discover_attachments(session, output, cache=None, deadline=None):
    seeds = json.loads((Path(__file__).parent/'data/alton-applications.json').read_text())
    result = {'status': 'checked', 'applications': [], 'documents': [], 'failures': [],
              'historical_seed_date': seeds['acquired_at'], 'complete_council_discovery': False}
    cache = Path(cache).resolve() if cache else None
    consecutive_failures = 0
    for application in seeds['applications']:
        if deadline and time.monotonic() >= deadline:
            result['failures'].append({'reason': 'Application discovery deadline reached'})
            break
        try:
            if cache:
                if not application['cached_page']:
                    raise ValueError('Application HTML not present in recovered cache')
                path = (cache/application['cached_page']).resolve()
                if not path.is_relative_to(cache) or path.stat().st_size > 2_000_000:
                    raise ValueError('Invalid cached application HTML')
                html = path.read_bytes()
                if hashlib.sha256(html).hexdigest() != application['cached_page_sha256']:
                    raise ValueError('Application HTML checksum mismatch')
            else:
                parsed = urlparse(application['url'])
                if parsed.scheme != 'https' or parsed.hostname != HOST:
                    raise ValueError('Official HTTPS application URL required')
                response = session.get(application['url'], timeout=(5, 10), stream=True, allow_redirects=False)
                try:
                    response.raise_for_status()
                    if 300 <= response.status_code < 400:
                        raise ValueError('Unexpected application redirect')
                    chunks, size = [], 0
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > 2_000_000:
                            raise ValueError('Application HTML exceeds 2 MB budget')
                        chunks.append(chunk)
                    html = b''.join(chunks)
                finally:
                    response.close()
            documents = parse_attachments(html, application)
            result['documents'].extend(documents)
            result['applications'].append({'reference': application['reference'],
                                           'attachment_count': len(documents), 'page_sha256': hashlib.sha256(html).hexdigest()})
            consecutive_failures = 0
        except (OSError, ValueError, requests.RequestException) as error:
            result['failures'].append({'reference': application['reference'], 'reason': str(error)})
            consecutive_failures += 1
            if not cache and consecutive_failures >= 3:
                break
    result['applications_omitted'] = len(seeds['applications'])-len(result['applications'])-sum('reference' in f for f in result['failures'])
    if result['failures'] or result['applications_omitted']:
        result['status'] = 'partial'
    (Path(output)/'alton-planning-discovery.json').write_text(json.dumps(result, indent=2))
    return result


def merge_discovered(recovered, discovery):
    by_url = {e['url']: dict(e) for e in recovered}
    for document in discovery['documents']:
        if document['url'] in by_url:
            by_url[document['url']]['priority'] = document['priority']
            by_url[document['url']]['discovery_source'] = document['discovery_source']
        else:
            by_url[document['url']] = dict(document)
    # Survey and actual geometry sheets precede reports, across applications.
    return sorted(by_url.values(), key=lambda e: (e.get('priority', document_role(e['title'])[1]), e['applicationReference'], e['title']))
