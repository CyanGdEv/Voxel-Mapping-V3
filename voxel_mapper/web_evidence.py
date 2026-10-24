"""Bounded public-web evidence, immutable cached bytes and explicit provenance."""
from concurrent.futures import CancelledError
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import socket
import time
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from .desktop_memory import digest
from .generation_cycles import atomic_json, file_hash

VERSION = 'public-web-evidence-v1'
MAX_BYTES = 8000000
MAX_TEXT = 12000
MAX_LINKS = 32
SEARCH_HOST = 'html.duckduckgo.com'
DEFAULT_HOSTS = ('publicaccess.staffsmoorlands.gov.uk', 'www.staffsmoorlands.gov.uk',
                 'www.altontowers.com', 'altontowers.com')


class WebError(ValueError):
    def __init__(self, code, message):
        self.code=code
        super().__init__(message)


class Budget:
    def __init__(self, limit=16000000):
        if type(limit) is not int or not 1<=limit<=32000000:
            raise ValueError('Bounded web byte budget required')
        self.limit=limit;self.spent=0

    def take(self, count):
        self.spent+=count
        if self.spent>self.limit: raise WebError('byte_budget','Web run byte budget exceeded')


def host(value):
    if not isinstance(value,str) or not 1<=len(value)<=253:
        raise ValueError('Bounded public hostname required')
    try: name=value.lower().rstrip('.').encode('idna').decode('ascii')
    except UnicodeError as error: raise ValueError('Valid public hostname required') from error
    if (not re.fullmatch(r'[a-z0-9.-]+',name) or '..' in name or
            name in ('localhost','metadata.google.internal') or
            name.endswith(('.localhost','.local','.internal'))):
        raise ValueError('Public hostname required')
    try:
        address=ipaddress.ip_address(name)
    except ValueError:
        if '.' not in name: raise ValueError('Fully qualified public hostname required')
    else:
        if not address.is_global: raise ValueError('Private or special addresses are not web sources')
    return name


def hosts(values):
    if not isinstance(values,list) or not 1<=len(values)<=32:
        raise ValueError('One to 32 explicitly approved public hosts required')
    names=[host(v) for v in values]
    if len(set(names))!=len(names): raise ValueError('Distinct approved hosts required')
    return names


def url(value, approved=None):
    if (not isinstance(value,str) or not 1<=len(value)<=2048 or
            any(ord(c)<=32 or ord(c)==127 for c in value) or '\\' in value):
        raise ValueError('Bounded public HTTP(S) URL required')
    parsed=urlsplit(value)
    if parsed.scheme not in ('https','http') or parsed.username is not None or parsed.password is not None:
        raise ValueError('Public HTTP(S) URL without credentials required')
    name=host(parsed.hostname or '')
    try: port=parsed.port
    except ValueError as error: raise ValueError('Valid web port required') from error
    if port not in (None,443 if parsed.scheme=='https' else 80):
        raise ValueError('Standard public web ports required')
    if approved is not None and name not in approved:
        raise ValueError('URL is outside the explicitly approved web hosts')
    return urlunsplit((parsed.scheme,name,parsed.path or '/',parsed.query,''))


def _public_dns(value, resolver):
    name=urlsplit(value).hostname
    try: addresses=sorted({item[4][0] for item in resolver(name,443,type=socket.SOCK_STREAM)})
    except OSError as error: raise WebError('dns_unavailable','Public source DNS lookup failed') from error
    if not addresses or any(not ipaddress.ip_address(v).is_global for v in addresses):
        raise WebError('nonpublic_address','Source resolves to a private or special address')
    return addresses


def _extract_content(data, content_type, source_url):
    links=[];truncated=False
    if data.startswith(b'%PDF-'):
        import pymupdf
        with pymupdf.open(stream=data,filetype='pdf') as document:
            if document.is_encrypted or len(document)>10000:
                raise WebError('unsupported_pdf','Encrypted or excessive-page PDF source')
            texts=[];page_truncated=False
            for i in range(min(len(document),3)):
                page_text=document[i].get_text();page_truncated|=len(page_text)>MAX_TEXT
                texts.append(page_text[:MAX_TEXT])
            text='\n'.join(texts);truncated=page_truncated or len(document)>3 or len(text)>MAX_TEXT
            title=(document.metadata or {}).get('title') or source_url.rsplit('/',1)[-1]
            pages=len(document)
        return {'format':'pdf','title':str(title)[:200],'text':text[:MAX_TEXT],
                'text_truncated':truncated,'pages':pages,'links':links,
                'text_status':'native_text' if text.strip() else 'no_native_text_ocr_required'}
    if 'html' in content_type or data.lstrip().lower().startswith((b'<!doctype html',b'<html')):
        soup=BeautifulSoup(data,'html.parser')
        title=soup.title.get_text(' ',strip=True)[:200] if soup.title else source_url
        for element in soup(['script','style','template','noscript','nav','header','footer']): element.decompose()
        content=soup.find('main') or soup.find(attrs={'role':'main'}) or soup
        for anchor in content.find_all('a',href=True,limit=2000):
            raw=anchor['href']
            legacy=re.fullmatch(r"javascript:AppBlobImage\(['\"]([0-9]{1,12})['\"]\);?",raw)
            if legacy and urlsplit(source_url).hostname=='publicaccess.staffsmoorlands.gov.uk':
                raw='/portal/servlets/AttachmentShowServlet?ImageName='+legacy[1]
            try: target=url(urljoin(source_url,raw))
            except ValueError: continue
            if target==source_url or any(r['url']==target for r in links): continue
            links.append({'url':target,'title':anchor.get_text(' ',strip=True)[:160]})
        # Council pages often put navigation before the actual attachments.
        # Retain those literal document URLs first, without inventing targets.
        links.sort(key=lambda item:(0 if (urlsplit(item['url']).path.lower().endswith('.pdf') or
            'attachmentshowservlet' in urlsplit(item['url']).path.lower()) else 1,
            0 if re.search(r'\b(plan|elevations?|sections?|surfacing|surfaces?)\b',item['title'],re.I) else 1))
        links=links[:MAX_LINKS]
        text=content.get_text(' ',strip=True)
        return {'format':'html','title':title[:200],'text':text[:MAX_TEXT],
                'text_truncated':len(text)>MAX_TEXT,'pages':None,'links':links,
                'text_status':'html_text_only_no_script_execution'}
    if content_type.startswith('text/plain'):
        text=data.decode('utf-8',errors='replace')
        return {'format':'text','title':source_url[:200],'text':text[:MAX_TEXT],
                'text_truncated':len(text)>MAX_TEXT,'pages':None,'links':[],
                'text_status':'plain_text'}
    raise WebError('unsupported_content','Only HTML, native PDF and plain-text web sources are supported')


def _extract(data, content_type, source_url):
    try: return _extract_content(data,content_type,source_url)
    except WebError: raise
    except Exception as error:
        raise WebError('unreadable_content','Web source could not be parsed: '+type(error).__name__) from error


def _body_path(cache, receipt):
    sha=receipt.get('body_sha256')
    if not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha):
        raise ValueError('Pinned cached web bytes required')
    if receipt.get('format') not in ('pdf','html','text'): raise ValueError('Known cached web format required')
    return cache/'objects'/(sha+('.pdf' if receipt['format']=='pdf' else '.bin'))


def _read_json(path):
    if path.stat().st_size>1000000: raise ValueError('Cached web receipt byte budget exceeded')
    return json.loads(path.read_text(encoding='utf-8'))


def cached(value, cache, approved):
    value=url(value,approved);cache=Path(cache)
    pointer=cache/'urls'/(digest(value)+'.json')
    if not pointer.exists(): return None
    pin=_read_json(pointer).get('artifact_sha256')
    if not isinstance(pin,str) or not re.fullmatch('[0-9a-f]{64}',pin): raise ValueError('Invalid cached source pointer')
    receipt=_read_json(cache/'snapshots'/(pin+'.json'))
    if (receipt.get('version')!=VERSION or receipt.get('artifact_sha256')!=pin or
            digest({k:v for k,v in receipt.items() if k!='artifact_sha256'})!=pin or
            receipt.get('requested_url')!=value or receipt.get('source_evidence_verified') is not False or
            receipt.get('training_labels_generated')!=0):
        raise ValueError('Cached web receipt changed')
    url(receipt['url'],approved)
    path=_body_path(cache,receipt)
    if path.stat().st_size>MAX_BYTES or path.stat().st_size!=receipt['body_bytes'] or file_hash(path)!=receipt['body_sha256']:
        raise ValueError('Cached web source bytes changed')
    # Reconstruct derived text/links from the original bytes, rather than
    # treating a resealed edited excerpt as original website evidence.
    derived=_extract(path.read_bytes(),receipt['content_type'],receipt['url'])
    if any(receipt.get(k)!=v for k,v in derived.items()): raise ValueError('Cached source extraction changed')
    return receipt


def _save(cache, receipt, data):
    cache=Path(cache);count=0;size=len(data)+1000000
    for entry in cache.rglob('*') if cache.exists() else ():
        count+=1
        if entry.is_file(): size+=entry.stat().st_size
        if count>2048 or size>256000000:
            raise WebError('cache_quota','Web cache quota reached; use another evidence cache')
    for name in ('objects','snapshots','urls'): (cache/name).mkdir(parents=True,exist_ok=True)
    path=_body_path(cache,receipt)
    if path.exists():
        if file_hash(path)!=receipt['body_sha256']: raise ValueError('Existing cached web bytes changed')
    else:
        temporary=path.with_suffix(path.suffix+'.partial');temporary.write_bytes(data);temporary.replace(path)
    pin=receipt['artifact_sha256'];snapshot=cache/'snapshots'/(pin+'.json')
    if snapshot.exists():
        if _read_json(snapshot)!=receipt: raise ValueError('Existing web snapshot changed')
    else: atomic_json(snapshot,receipt)
    atomic_json(cache/'urls'/(digest(receipt['requested_url'])+'.json'),{'artifact_sha256':pin})


class _NoOriginAuth(requests.auth.AuthBase):
    def __call__(self, request):
        request.headers.pop('Authorization',None)
        return request


def fetch(value, cache, approved, *, offline=False, refresh=True, budget=None,
          cancelled=lambda:False, deadline=None, session=None, resolver=socket.getaddrinfo):
    if cancelled(): raise CancelledError('Web retrieval cancelled')
    approved=hosts(list(approved));value=url(value,approved)
    if type(offline) is not bool or type(refresh) is not bool: raise ValueError('Explicit web cache settings required')
    prior=cached(value,cache,approved)
    if offline or (prior is not None and not refresh):
        if prior is None: raise WebError('offline_cache_miss','Original web source is absent from the offline cache')
        return {'source':prior,'retrieval':'cached','network_bytes':0,'network_error':None}
    budget=budget or Budget();deadline=deadline if deadline is not None else time.monotonic()+45
    start=budget.spent;client=session if session is not None else requests.Session()
    current=value;redirects=[]
    try:
        for _ in range(4):
            if cancelled(): raise CancelledError('Web retrieval cancelled')
            if time.monotonic()>=deadline: raise WebError('deadline','Web retrieval time budget exceeded')
            if budget.spent>=budget.limit: raise WebError('byte_budget','Web run byte budget exhausted')
            addresses=_public_dns(current,resolver)
            client.cookies.clear()
            response=client.get(current,stream=True,allow_redirects=False,auth=_NoOriginAuth(),
                headers={'User-Agent':'VoxelMapperV3 evidence reader','Accept':'text/html, application/pdf, text/plain'},
                timeout=(min(5,max(.1,deadline-time.monotonic())),min(15,max(.1,deadline-time.monotonic()))))
            try:
                if response.status_code in (301,302,303,307,308):
                    target=url(urljoin(current,response.headers.get('Location','')),approved)
                    if target==current: raise WebError('redirect_loop','Web source redirect loop')
                    redirects.append({'url':current,'status':response.status_code,'target':target});current=target;continue
                if response.status_code!=200: raise WebError('http_status','Web source returned HTTP '+str(response.status_code))
                data=bytearray()
                for chunk in response.iter_content(65536):
                    if cancelled(): raise CancelledError('Web retrieval cancelled')
                    if time.monotonic()>=deadline: raise WebError('deadline','Web retrieval time budget exceeded')
                    budget.take(len(chunk));data.extend(chunk)
                    if len(data)>MAX_BYTES: raise WebError('source_byte_budget','Web source byte budget exceeded')
                content_type=response.headers.get('Content-Type','').split(';',1)[0].strip().lower()
            finally: response.close()
            data=bytes(data);derived=_extract(data,content_type,current)
            receipt={'version':VERSION,'requested_url':value,'url':current,
                'retrieved_at_utc':datetime.now(timezone.utc).isoformat(),
                'content_type':content_type,'body_sha256':hashlib.sha256(data).hexdigest(),
                'body_bytes':len(data),'redirects':redirects,'dns_addresses_at_fetch':addresses,
                **derived,'source_evidence_verified':False,'training_labels_generated':0}
            receipt['citation_id']='W'+digest([current,receipt['body_sha256']])[:12]
            receipt['artifact_sha256']=digest(receipt);_save(cache,receipt,data)
            return {'source':receipt,'retrieval':'downloaded','network_bytes':budget.spent-start,'network_error':None}
        raise WebError('redirect_budget','Web source redirect budget exceeded')
    except (requests.RequestException,WebError) as error:
        if prior is not None:
            return {'source':prior,'retrieval':'cached_after_network_failure',
                'network_bytes':budget.spent-start,'network_error':str(error)}
        if isinstance(error,WebError): raise
        raise WebError('network_unavailable','Public web source request failed: '+type(error).__name__) from error
    finally:
        if session is None: client.close()


def search(query, cache, approved, **kwargs):
    if not isinstance(query,str) or not 1<=len(query.strip())<=300 or any(ord(c)<32 for c in query):
        raise ValueError('A bounded explicitly supplied public search query is required')
    source=fetch('https://'+SEARCH_HOST+'/html/?'+urlencode({'q':query}),cache,[SEARCH_HOST],**kwargs)
    # Parse actual result anchors; navigation, tracking and search-page text
    # never become a source document or an accuracy reference.
    record=source['source'];body=_body_path(Path(cache),record).read_bytes()
    soup=BeautifulSoup(body,'html.parser');results=[]
    for anchor in soup.select('a.result__a')[:32]:
        target=urljoin(record['url'],anchor.get('href',''))
        parsed=urlsplit(target)
        if parsed.hostname and (parsed.hostname=='duckduckgo.com' or parsed.hostname.endswith('.duckduckgo.com')):
            target=parse_qs(parsed.query).get('uddg',[''])[0]
        try: target=url(target,approved)
        except ValueError: continue
        if any(r['url']==target for r in results): continue
        results.append({'url':target,'title':anchor.get_text(' ',strip=True)[:160]})
    return {'query':query,'provider':'duckduckgo_html','results':results,
            'retrieval':source['retrieval'],'network_error':source['network_error'],
            'search_source_sha256':record['body_sha256'],
            'status':'scoped_results_found' if results else 'no_scoped_results_or_search_unavailable'}
