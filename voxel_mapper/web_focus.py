"""Site/location/tag-guided views derived from immutable downloaded source bytes."""
import hashlib
from pathlib import Path
import re

from bs4 import BeautifulSoup

from . import web_evidence as web
from .desktop_memory import digest
from .generation_cycles import file_hash


def profile(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value)-{'site', 'location', 'tags', 'applications', 'exclude_tags'}:
        raise ValueError('Known site research profile fields required')
    result = {'site': value.get('site', ''), 'location': value.get('location', '')}
    for key, maximum in [('site',128), ('location',160)]:
        text = result[key]
        if not isinstance(text,str) or len(text)>maximum or any(ord(c)<32 for c in text):
            raise ValueError('Bounded public site/location text required')
    for key, count in [('tags',16), ('applications',8), ('exclude_tags',16)]:
        values = value.get(key, [])
        if (not isinstance(values,list) or len(values)>count
                or any(not isinstance(v,str) or not 1<=len(v.strip())<=80 or any(ord(c)<32 for c in v) for v in values)):
            raise ValueError('Bounded public research tags/application references required')
        result[key] = list(dict.fromkeys(values))
    if not result['site'].strip():
        raise ValueError('Explicit public site name required for focused research')
    return result


def score(text, scope):
    text = text.casefold()
    return (sum(5 for v in scope['tags'] if v.casefold() in text)
        +sum(8 for v in scope['applications'] if v.casefold() in text)
        +int(scope['site'].casefold() in text)*2
        +int(bool(scope['location']) and scope['location'].casefold() in text)
        -sum(50 for v in scope['exclude_tags'] if v.casefold() in text))


def inspect(source, cache, scope, *, cancelled=lambda:False, deadline=None):
    """Additional search views do not overwrite original cache receipts or accept geometry."""
    import time
    from concurrent.futures import CancelledError
    def check():
        if cancelled():
            raise CancelledError('Focused source processing cancelled')
        if deadline is not None and time.monotonic() >= deadline:
            raise web.WebError('deadline', 'Focused source processing deadline reached')
    check()
    path = web._body_path(Path(cache), source)
    if not path.is_file() or path.stat().st_size>web.MAX_BYTES or file_hash(path)!=source['body_sha256']:
        raise ValueError('Pinned original source required for focused processing')
    text = source['text']
    links = source['links']
    selected = []
    scanned = 0
    scan_truncated = False
    structured_views = []
    if source['format'] == 'pdf':
        import pymupdf
        candidates = []
        with pymupdf.open(path) as document:
            if document.is_encrypted or len(document)>10000:
                raise ValueError('Readable bounded PDF source required')
            # Native text only. Raster-only pages remain explicit OCR gaps.
            for index in range(min(len(document),80)):
                check()
                raw = document[index].get_text()
                text_pin=hashlib.sha256(raw.encode()).hexdigest()
                if len(raw)>64000:
                    scan_truncated = True
                raw = raw[:64000]
                candidates.append((score(raw,scope), index+1, raw, text_pin))
            scanned = len(candidates)
            scan_truncated |= len(document)>scanned
        ranked = sorted(candidates,key=lambda row:(-row[0],row[1]))[:6]
        chunks = []
        for relevance, page, raw, text_pin in ranked:
            if not raw.strip():
                continue
            # Take a source-local window around the first query tag, preserving
            # literal text and offsets instead of summarizing measurements.
            hits = next(([m.start() for m in re.finditer(re.escape(tag),raw,re.I)] for tag in scope['tags'] if re.search(re.escape(tag),raw,re.I)),[])
            start = max(0,min(hits)-80) if hits else 0
            excerpt = raw[start:start+1600]
            selected.append({'page':page, 'score':relevance, 'text_start':start,
                'text':excerpt, 'page_text_sha256': text_pin,
                'page_text_truncated':len(raw)==64000})
            chunks.append('[PDF page '+str(page)+'] '+excerpt)
        text = '\n'.join(chunks)[:web.MAX_TEXT]
    elif source['format'] == 'html':
        soup = BeautifulSoup(path.read_bytes(),'html.parser')
        from .research_sources import html_views
        structured_views,embedded_links = html_views(soup,source['url'])
        found = {r['url']:r for r in embedded_links}
        for element in soup(['script','style','template','noscript']):
            element.decompose()
        for anchor in soup.find_all('a',href=True,limit=2000):
            raw = anchor['href']
            legacy = re.fullmatch(r"javascript:\s*AppBlobImage\(\s*['\"]([0-9]{1,12})['\"]\s*\);?",raw,re.I)
            if legacy and web.urlsplit(source['url']).hostname=='publicaccess.staffsmoorlands.gov.uk':
                raw='/portal/servlets/AttachmentShowServlet?ImageName='+legacy[1]
            try: target=web.url(web.urljoin(source['url'],raw))
            except ValueError: continue
            found.setdefault(target,{'url':target,'title':anchor.get_text(' ',strip=True)[:160]})
        for img in soup.find_all('img',src=True,limit=128):
            if str(img.get('width',''))=='1' or str(img.get('height',''))=='1':
                continue
            try: target=web.url(web.urljoin(source['url'],img['src']))
            except ValueError: continue
            found.setdefault(target,{'url':target,'title':str(img.get('alt','Image'))[:160],'media_type':'image'})
        if structured_views:
            text=('\n'.join(v['text'] for v in structured_views)+'\n'+text)[:web.MAX_TEXT]
        links=sorted(found.values(),key=lambda row:(-score(row['title'],scope),
            0 if '.pdf' in row['url'].lower() or 'attachmentshowservlet' in row['url'].lower() else 1,row['url']))[:128]
    result={'version':'site-focused-source-view-v2','citation_id':source['citation_id'],
        'source_body_sha256':source['body_sha256'],'profile':scope,'text':text,
        'structured_html_views':structured_views,'selected_pdf_pages':selected,'pdf_pages_scanned':scanned,'scan_truncated':scan_truncated,
        'links':links,'relevance_score':score(text,scope),'relevance_is_identity_verification':False,
        'source_evidence_verified':False,'training_labels_generated':0,
        'limitations':['Site, location and tag matches are retrieval hints, not physical identity or datum proof.',
            'PDF view scans at most 80 pages and retains six literal source-local excerpts; image-only sources require visual/OCR review.']}
    check()
    if file_hash(path)!=source['body_sha256']:
        raise ValueError('Original source changed during focused processing')
    result['artifact_sha256']=digest(result)
    return result
