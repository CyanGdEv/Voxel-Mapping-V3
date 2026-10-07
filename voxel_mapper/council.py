"""Runnymede public document adapter. Consultation evidence is not world geometry."""
import hashlib
import io
import json
import re
from urllib.parse import urljoin, urlparse, urlencode

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .acquisition import USER_AGENT
from .geopdf import inspect_registration
from .drawing_vectors import extract_vectors
from .drawing_evidence import evidence_candidates, document_category, inspection_order

SEARCH = 'https://planning.runnymede.gov.uk/Northgate/PlanningExplorer/GeneralSearch.aspx'
DOCS = 'https://docs.runnymede.gov.uk/PublicAccess_Live'
TERMS = 'https://www.runnymede.gov.uk/planning-permission/view-object-support-application-1'
REFERENCE = re.compile(r'\bRU\.\d{2}/\d{4}\b', re.I)
SOURCE = {'id':'runnymede-planning', 'url':TERMS, 'license':'copyright-consultation-only',
          'attribution':'Runnymede public planning records; drawings remain copyright of their owners'}


def search_form(html, site_name):
    soup = BeautifulSoup(html, 'html.parser')
    if not soup.select_one('input[name="txtSiteAddress"]'):
        raise ValueError('Council search form changed or unavailable')
    data = {}
    for tag in soup.select('input[name]'):
        kind = tag.get('type', 'text')
        if kind not in ('radio','checkbox') or tag.has_attr('checked'):
            data[tag['name']] = tag.get('value','')
    for tag in soup.select('select[name]'):
        option = tag.select_one('option[selected]') or tag.select_one('option')
        if option:
            data[tag['name']] = option.get('value','')
    data['txtSiteAddress'] = site_name
    data['csbtnSearch'] = 'Search'
    return data


def parse_results(html):
    soup = BeautifulSoup(html, 'html.parser')
    references = []
    for anchor in soup.select('a[href]'):
        match = REFERENCE.fullmatch(anchor.get_text(' ', strip=True))
        if match:
            ref = match[0].upper()
            if ref not in references:
                references.append(ref)
    # Do not treat an unexpected HTML page as proof of no applications.
    if not references and not re.search(r'no (?:records|results|applications)\b', soup.get_text(' ',strip=True), re.I):
        raise ValueError('Unrecognised council results page')
    next_links = [urljoin(SEARCH,a['href']) for a in soup.select('a[href]')
                  if a.get_text(' ',strip=True).lower() in ('next','next page','>')]
    return references, next_links[0] if next_links else None


def parse_document_list(html, reference):
    marker = re.search(r'\bvar\s+model\s*=\s*', html)
    if not marker:
        raise ValueError('Unrecognised document list')
    model, _ = json.JSONDecoder().raw_decode(html[marker.end():])
    if reference.upper() not in str(model.get('PageHeader','')).upper() or not isinstance(model.get('Rows'),list):
        raise ValueError('Document list does not match requested application')
    documents, seen = [], set()
    for row in model['Rows']:
        # Keep portal identifiers opaque; never regenerate or normalise them.
        identity = str(row.get('Guid',''))
        if not re.fullmatch(r'[A-Za-z0-9-]{16,64}',identity):
            raise ValueError('Invalid council document identifier')
        if identity in seen:
            continue
        seen.add(identity)
        title, kind = str(row.get('Doc_Ref2','')), str(row.get('Doc_Type',''))
        if 'plan' not in kind.lower() and not re.search(r'\b(?:plan|elevation|drawing|section|survey|materials?|finishes|surface|paving|bathymetry|topographic|flood|drainage)\b',title,re.I):
            continue
        documents.append({'id':identity, 'application_reference':reference, 'title':title,
                          'type':kind, 'received_date_raw':row.get('Date_Received'),
                          'evidence_category':document_category(title),
                          'url':DOCS+'/Document/ViewDocument?'+urlencode({'id':identity}),
                          'reuse_status':'consultation_only', 'geometry_action':'unchanged',
                          'construction_status':'not_verified', 'alignment_status':'not_inspected'})
    return documents


def inspect_pdf(payload, max_pages=12, bounds=None):
    if not payload.startswith(b'%PDF-'):
        raise ValueError('Document is not a PDF')
    reader = PdfReader(io.BytesIO(payload), strict=False)
    if reader.is_encrypted:
        raise ValueError('Encrypted PDF cannot be inspected automatically')
    pages, total_text = [], 0
    for index, page in enumerate(reader.pages[:max_pages]):
        # Guard oversized decompressed content before invoking text extraction.
        contents = page.get_contents()
        if contents and len(contents.get_data()) > 10_000_000:
            raise ValueError('PDF page content exceeds inspection budget')
        text = page.extract_text() or ''
        total_text += len(text)
        if total_text > 500_000:
            raise ValueError('PDF text exceeds inspection budget')
        scales = sorted(set(int(s) for s in re.findall(r'\b1\s*:\s*(\d{2,6})\b',text)))
        revisions = sorted(set(re.findall(r'\b(?i:REV(?:ISION)?)\s*[:.]?\s+([A-Z]{1,3}\d{0,3}|\d{1,3})\b',text)))[:20]
        revision_dates = re.findall(r'\b(P\d{1,3}|[A-Z])\s+(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b',text)[:30]
        registration = inspect_registration(page,bounds)
        pages.append({'page':index+1, 'size_points':[float(page.mediabox.width),float(page.mediabox.height)],
                      'scale_denominator_candidates':scales, 'revision_label_candidates':revisions,
                      'revision_date_candidates':[{'revision':revision,'date_raw':date} for revision,date in revision_dates],
                      'has_viewport_metadata':bool(page.get('/VP')), 'has_lgi_metadata':bool(page.get('/LGIDict')),
                      'registration':registration,
                      'vector_extraction':extract_vectors(page,registration,reuse_allowed=False),
                      'semantic_evidence':evidence_candidates(text),
                      'has_text':bool(text.strip())})
    return {'status':'inspected_consultation_only', 'sha256':hashlib.sha256(payload).hexdigest(),
            'bytes':len(payload), 'page_count':len(reader.pages), 'pages_inspected':len(pages), 'pages':pages,
            'truncated':len(reader.pages)>max_pages, 'alignment_status':'unverified',
            'limitations':['Scale/revision labels are candidates, not verified dimensions or coordinates',
                           'Embedded control consistency is not independent surveyed registration',
                           'No OCR, drawing vectorisation or construction verification',
                           'Original PDF is not retained or redistributed in output']}


def read_pdf(session, url, max_bytes=10_000_000):
    if urlparse(url).hostname != 'docs.runnymede.gov.uk':
        raise ValueError('Unexpected document host')
    response = session.get(url, timeout=(10,30), stream=True)
    try:
        response.raise_for_status()
        if urlparse(response.url).hostname != 'docs.runnymede.gov.uk':
            raise ValueError('Unexpected document redirect')
        chunks, size = [], 0
        for chunk in response.iter_content(64*1024):
            size += len(chunk)
            if size > max_bytes:
                raise ValueError('PDF download exceeds byte budget')
            chunks.append(chunk)
        return b''.join(chunks)
    finally:
        response.close()


def acquire_council(authorities, planning_records, site_name, output, max_applications=10,
                    max_search_pages=3, max_documents=500, max_pdf_inspections=6, bounds=None):
    result = {'provider':SOURCE['id'], 'status':'not_supported', 'application_search':'not_attempted',
              'applications':[], 'documents':[], 'failures':[], 'terms_url':TERMS,
              'reuse_status':'consultation_only', 'geometry_replacements':0,
              'limitations':['Runnymede only; address search is not a verified spatial association',
                             'PDFs are inspected temporarily for consultation, not redistributed or used as world geometry']}
    if not any(a.get('reference') == 'E60000275' for a in authorities):
        return result
    result['status'] = 'checked'
    references = []
    for record in planning_records:
        for match in REFERENCE.findall(str(record.get('reference',''))):
            if match.upper() not in references:
                references.append(match.upper())
    with requests.Session() as session:
        session.headers.update({'User-Agent':USER_AGENT})
        if site_name:
            try:
                initial = session.get(SEARCH,timeout=(10,30)); initial.raise_for_status()
                response = session.post(SEARCH,data=search_form(initial.text,site_name),timeout=(10,30))
                for page in range(max_search_pages):
                    response.raise_for_status()
                    found, next_url = parse_results(response.text)
                    references.extend(ref for ref in found if ref not in references)
                    if not next_url:
                        result['application_search']='completed_address_candidates'
                        break
                    if page == max_search_pages-1:
                        result['application_search']='truncated'
                        break
                    if urlparse(next_url).hostname != 'planning.runnymede.gov.uk':
                        raise ValueError('Unexpected council pagination host')
                    response = session.get(next_url,timeout=(10,30))
            except (requests.RequestException,ValueError) as error:
                result['application_search']='blocked_or_unavailable'
                result['failures'].append({'stage':'application_search','reason':str(error)})
        else:
            result['application_search']='site_name_unavailable'
        result['applications_truncated']=len(references)>max_applications
        for reference in references[:max_applications]:
            result['applications'].append(reference)
            try:
                response = session.get(DOCS+'/SearchResult/RunThirdPartySearch',
                    params={'FOLDER1_REF':reference,'FileSystemId':'PL'},timeout=(10,30))
                response.raise_for_status()
                documents = parse_document_list(response.text,reference)
                space = max_documents-len(result['documents'])
                result['documents'].extend(documents[:space])
                if len(documents)>space:
                    result['documents_truncated']=True
                    break
            except (requests.RequestException,ValueError,TypeError,AttributeError) as error:
                result['failures'].append({'stage':'document_list','application':reference,'reason':str(error)})
        # Stable prioritisation; raw dates can have ambiguous portal formatting.
        candidates = inspection_order(result['documents'])
        for document in candidates[:max_pdf_inspections]:
            try:
                document['inspection']=inspect_pdf(read_pdf(session,document['url']),bounds=bounds)
                registrations=[p['registration']['status'] for p in document['inspection']['pages']]
                document['alignment_status']='candidate_alignment' if 'candidate_alignment' in registrations else 'unavailable_or_rejected'
            except (requests.RequestException,ValueError,PdfReadError,TypeError,KeyError) as error:
                document['inspection']={'status':'unavailable_or_rejected','reason':str(error)}
        result['inspection_budget_omitted']=max(0,len(candidates)-max_pdf_inspections)
    (output/'council-drawings.json').write_text(json.dumps(result,indent=2))
    return result
