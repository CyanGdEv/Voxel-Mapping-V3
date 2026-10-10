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


def parse_application_results(html):
    """Read park-address matches and literal pagination fields from the portal."""
    if len(html)>2_000_000:raise ValueError('Application search HTML exceeds 2 MB budget')
    soup=BeautifulSoup(html,'html.parser');applications={}
    endpoint='https://'+HOST+'/portal/servlets/ApplicationSearchServlet'
    for anchor in soup.select('a[href]'):
        reference=anchor.get_text(' ',strip=True)
        if not re.fullmatch(r'SMD/\d{4}/\d{4}[A-Z]?',reference):continue
        parsed=urlparse(urljoin(endpoint,anchor['href']))
        if parsed.scheme not in ('http','https') or parsed.hostname!=HOST or parsed.port is not None:continue
        if parsed.path!='/portal/servlets/ApplicationSearchServlet':continue
        identifier=parse_qs(parsed.query).get('PKID',[''])[0]
        if not re.fullmatch(r'[0-9]+',identifier):continue
        row=anchor.find_parent('tr')
        if row is None:continue
        context=re.sub(r'\s+',' ',row.get_text(' ',strip=True))
        # Address-only discovery; references in proposal text are not site evidence.
        if not re.search(r'\balton\s+towers\b',context[:200],re.I):continue
        applications[reference]={'reference':reference,'url':endpoint+'?PKID='+identifier,
                                 'application_context':context}
    navigation=None
    for form in soup.select('form'):
        if not form.select_one('input[name="forward"]'):continue
        parsed=urlparse(urljoin(endpoint,form.get('action','')))
        if parsed.hostname!=HOST or parsed.scheme not in ('http','https') or parsed.path!='/portal/servlets/ApplicationSearchServlet':
            raise ValueError('External application search navigation')
        fields={n['name']:n.get('value','') for n in form.select('input[name]')}
        if set(fields)!={'LAST_ROW_ID','DIRECTION','RECORDS','forward'} or fields['DIRECTION']!='F':
            raise ValueError('Unexpected application pagination fields')
        if not fields['LAST_ROW_ID'].isdigit() or not fields['RECORDS'].isdigit() or not 1<=int(fields['RECORDS'])<=100:
            raise ValueError('Invalid application pagination budget')
        navigation=fields;break
    return list(applications.values()),navigation


def search_applications(session,output,max_pages=40,deadline=None):
    """Bounded address search; never claim all references or all dates are covered."""
    if not 1<=max_pages<=100:raise ValueError('Application search page budget must be 1–100')
    endpoint='https://'+HOST+'/portal/servlets/ApplicationSearchServlet'
    output=Path(output);(output/'files').mkdir(parents=True,exist_ok=True)
    result={'query':'FullAddress=Alton Towers','applications':[],'pages':[],
            'failures':[],'complete_search':False,'complete_council_discovery':False}
    applications={};navigation={'FullAddress':'Alton Towers','buttonSearch':'Search'};seen=set()
    for page in range(max_pages):
        try:
            if deadline and time.monotonic()>=deadline:raise ValueError('Application search deadline reached')
            key=json.dumps(navigation,sort_keys=True)
            if key in seen:raise ValueError('Repeated application pagination')
            seen.add(key)
            with session.post(endpoint,data=navigation,timeout=(5,15),stream=True,allow_redirects=False) as response:
                response.raise_for_status()
                if 300<=response.status_code<400:raise ValueError('Unexpected application search redirect')
                payload=bytearray()
                for chunk in response.iter_content(65536):
                    payload.extend(chunk)
                    if len(payload)>2_000_000:raise ValueError('Application search HTML exceeds 2 MB budget')
            rows,navigation=parse_application_results(bytes(payload))
            if not rows:raise ValueError('Search page contains no validated park results')
            digest=hashlib.sha256(payload).hexdigest();(output/'files'/f'{digest}.html').write_bytes(payload)
            for row in rows:applications[row['reference']]={**row,'search_page_sha256':digest}
            result['pages'].append({'page':page+1,'sha256':digest,'matched_park_rows':len(rows)})
            if navigation is None:result['complete_search']=True;break
        except (OSError,ValueError,requests.RequestException) as error:
            result['failures'].append({'page':page+1,'reason':str(error)});break
    result['applications']=list(applications.values())
    (output/'alton-application-search.json').write_text(json.dumps(result,indent=2))
    return result


def document_role(title):
    lower = re.sub(r'[_\s]+', ' ', title.lower())
    if re.search(r'arboricultur|ecolog|habitat|bat\b|bird\b|photo|assess?ment|statement|report|appraisal|tree (?:survey|schedule)|application.*(?:s\.?73|path proposals)|s\.?73.*application', lower):
        return 'context-report', 90
    if re.search(r'topograph|topolog|master land survey|\bsurvey\b', lower):
        return 'topographical-survey', 0
    if re.search(r'landscap|lanscap|planting|paving|surfacing|surface finish|hard finish', lower):
        return 'landscape-plan', 20
    if re.search(r'site (?:block |location )?plan|\bga\b|general arrangement|\blayout\b|path proposal|(?:existing|proposed) plans?\b', lower):
        return 'site-plan', 10
    if re.search(r'floor plan|\bgf plan\b|basement plan|roof plan|ancillary building plan|maintenance building', lower):
        return 'floor-plan', 30
    if re.search(r'block plan', lower):
        return 'site-plan', 10
    if re.fullmatch(r'(?:forms and )?plans?|maps?(?: of .*)?|drawings|documents and drawings|\d+',lower):
        return 'unclassified-drawing',50
    if re.search(r'(?:gardens?|bridge|dam) (?:area )?plan|(?:bridge|dam)/.*plan',lower):
        return 'site-plan',10
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


def discover_attachments(session, output, cache=None, deadline=None, application_references=None):
    seeds = json.loads((Path(__file__).parent/'data/alton-applications.json').read_text())
    if application_references:
        wanted = set(application_references)
        known = {a['reference'] for a in seeds['applications']}
        if wanted-known:
            raise ValueError('Application references absent from the Alton park catalogue: '+', '.join(sorted(wanted-known)))
        seeds['applications'] = [a for a in seeds['applications'] if a['reference'] in wanted]
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
            for key in ('role', 'state', 'priority', 'discovery_source'):
                if key in document:
                    by_url[document['url']][key] = document[key]
        else:
            by_url[document['url']] = dict(document)
    # Survey and actual geometry sheets precede reports, across applications.
    return sorted(by_url.values(), key=lambda e: (e.get('priority', document_role(e['title'])[1]), e['applicationReference'], e['title']))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Expand official Alton Towers address-search discovery')
    parser.add_argument('--output',required=True)
    parser.add_argument('--max-pages',type=int,default=40)
    args=parser.parse_args()
    with requests.Session() as session:
        result=search_applications(session,args.output,args.max_pages,time.monotonic()+600)
    print(json.dumps({k:result[k] for k in ('complete_search','complete_council_discovery','failures')},indent=2))
