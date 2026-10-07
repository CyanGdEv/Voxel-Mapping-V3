"""Runnymede public document adapter. Consultation evidence is not world geometry."""
import hashlib
import datetime
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
from .survey_reference import inspect_reference_notes
from .drawing_vectors import extract_vectors
from .drawing_evidence import evidence_candidates, document_category, inspection_order
from .drawing_associations import extract_associations
from .drawing_controls import inspect_coordinate_labels
from .drawing_polygons import polygon_candidates
from .drawing_ocr import inspect_scanned_page
from .raster_grid import inspect_native_suffix_grid
from .dotted_grid import inspect_dotted_grid

SEARCH = 'https://planning.runnymede.gov.uk/Northgate/PlanningExplorer/GeneralSearch.aspx'
DOCS = 'https://docs.runnymede.gov.uk/PublicAccess_Live'
TERMS = 'https://www.runnymede.gov.uk/planning-permission/view-object-support-application-1'
REFERENCE = re.compile(r'\bRU\.\d{2}/\d{4}\b', re.I)
SOURCE = {'id':'runnymede-planning', 'url':TERMS, 'license':'copyright-consultation-only',
          'attribution':'Runnymede public planning records; drawings remain copyright of their owners'}


def recent_references(references, current_year=None):
    """Prioritise recent reference years within the last century, not construction."""
    current_year = current_year or datetime.datetime.now(datetime.timezone.utc).year
    def rank(reference):
        year,serial = reference[3:].split('/')
        expanded = current_year//100*100+int(year)
        if expanded>current_year:
            expanded-=100
        return expanded,int(serial)
    return sorted(set(references),key=rank,reverse=True)


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


def parse_results(html, base_url=SEARCH):
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
    next_links = []
    for anchor in soup.select('a[href]'):
        labels = [anchor.get_text(' ',strip=True),anchor.get('title',''),anchor.get('aria-label','')]
        labels.extend(image.get('alt','') for image in anchor.select('img'))
        if any(label.strip().lower() in ('next','next page','go to next page','>') for label in labels):
            target = urljoin(base_url,anchor['href'])
            if urlparse(target).scheme not in ('http','https'):
                raise ValueError('Unsupported council pagination link')
            next_links.append(target)
    return references, next_links[0] if next_links else None


def application_context(html, max_rows=500, target_names=()):
    """Read named result cells, preserving proposal references as candidates.

    A referenced permission is worth inspecting, but does not establish that
    either application describes the current built site.
    """
    soup = BeautifulSoup(html, 'html.parser')
    rows = soup.select('tr')
    if len(rows) > max_rows:
        raise ValueError('Council result row budget exceeded')
    contexts = []
    for row in rows:
        description = row.select_one('[title="Development Description"]')
        if description is None:
            continue
        identities = {a.get_text(' ', strip=True).upper() for a in row.select('a[href]')
                      if REFERENCE.fullmatch(a.get_text(' ', strip=True))}
        if len(identities) != 1:
            continue
        reference = identities.pop()
        text = description.get_text(' ', strip=True)
        if len(text) > 10_000:
            raise ValueError('Council proposal text budget exceeded')
        related = sorted({r.upper() for r in REFERENCE.findall(text)} - {reference})
        contexts.append({'reference': reference, 'related_references': related,
                         'target_name_matches': [name for name in target_names
                             if re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',text,re.I)],
                         'materials_candidate': bool(re.search(r'\bmaterial|\bpaving|\bfinish', text, re.I)),
                         'relationship': 'proposal_mentions_unverified'})
    return contexts


def application_order(references, contexts):
    """Inspect mentioned parent permissions before unrelated recent filings."""
    related = {r for c in contexts for r in c['related_references']}
    targeted = {c['reference'] for c in contexts if c.get('target_name_matches')}
    target_parents = {r for c in contexts if c.get('target_name_matches') for r in c['related_references']}
    priority = targeted | target_parents
    materials = {c['reference'] for c in contexts if c['materials_candidate']}
    all_refs = set(references) | related
    return (recent_references(target_parents) + recent_references(targeted - target_parents) + recent_references(related - priority) +
            recent_references(materials - related - priority) +
            recent_references(all_refs - related - materials - priority))


def building_search_names(features):
    """Exact scoped building names; no guessed application identifiers."""
    names=set()
    for feature in features or []:
        properties=feature.get('properties',{})
        name=properties.get('name')
        if properties.get('kind')=='building' and properties.get('source_id')=='osm' and isinstance(name,str):
            name=re.sub(r'^the\s+','',name.strip(),flags=re.I)
            if 3<=len(name)<=100:names.add(name)
    return sorted(names)[:64]


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


def inspect_pdf(payload, max_pages=12, bounds=None, document_title=None, max_ocr_pages=2, reference_features=None):
    if not payload.startswith(b'%PDF-'):
        raise ValueError('Document is not a PDF')
    reader = PdfReader(io.BytesIO(payload), strict=False)
    if reader.is_encrypted:
        raise ValueError('Encrypted PDF cannot be inspected automatically')
    if not 0 <= max_ocr_pages <= 2:
        raise ValueError('OCR page budget must be between zero and two')
    pages, total_text, ocr_pages = [], 0, 0
    for index, page in enumerate(reader.pages[:max_pages]):
        # Guard oversized decompressed content before invoking text extraction.
        contents = page.get_contents()
        content_size = len(contents.get_data()) if contents is not None else 0
        if content_size > 10_000_000:
            raise ValueError('PDF page content exceeds inspection budget')
        text = page.extract_text() or ''
        total_text += len(text)
        if total_text > 500_000:
            raise ValueError('PDF text exceeds inspection budget')
        scales = sorted(set(int(s) for s in re.findall(r'\b1\s*:\s*(\d{2,6})\b',text)))
        revisions = sorted(set(re.findall(r'\b(?i:REV(?:ISION)?)\s*[:.]?\s+([A-Z]{1,3}\d{0,3}|\d{1,3})\b',text)))[:20]
        revision_dates = re.findall(r'\b(P\d{1,3}|[A-Z])\s+(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b',text)[:30]
        registration = inspect_registration(page,bounds)
        vectors = extract_vectors(page,registration,reuse_allowed=False)
        polygons = polygon_candidates(vectors)
        ocr = {'status':'not_needed_native_text', 'world_geometry_additions':0}
        if len(text.strip()) < 20:
            if not content_size:
                ocr['status'] = 'empty_page'
            elif ocr_pages >= max_ocr_pages:
                ocr['status'] = 'page_budget_omitted'
            else:
                ocr_pages += 1
                ocr = inspect_scanned_page(payload, index+1, bounds, reference_features)
        native_grid=inspect_native_suffix_grid(page) if text.strip() else {'status':'no_native_text'}
        # Runnymede location permits a BNG hypothesis for diagnostics only.
        dotted_grid=(inspect_dotted_grid(page,reference_features,27700) if native_grid['status']=='consistent_label_layout_unverified'
                     else {'status':'no_consistent_native_grid_labels','world_geometry_additions':0})
        pages.append({'page':index+1, 'size_points':[float(page.mediabox.width),float(page.mediabox.height)],
                      'scale_denominator_candidates':scales, 'revision_label_candidates':revisions,
                      'revision_date_candidates':[{'revision':revision,'date_raw':date} for revision,date in revision_dates],
                      'has_viewport_metadata':bool(page.get('/VP')), 'has_lgi_metadata':bool(page.get('/LGIDict')),
                      'registration':registration,
                      'survey_reference_notes':inspect_reference_notes(text),
                      'coordinate_label_registration':inspect_coordinate_labels(page,bounds,reuse_allowed=False),
                      'survey_mark_registration':inspect_coordinate_labels(page,bounds,reuse_allowed=False,require_marks=True),
                      'grid_registration':inspect_coordinate_labels(page,bounds,reuse_allowed=False,require_grid=True),
                      'native_suffix_grid_inspection':native_grid,
                      'dotted_grid_inspection':dotted_grid,
                      'vector_extraction':vectors,
                      'polygon_extraction':polygons,
                      'semantic_associations':extract_associations(page,registration,polygons,reuse_allowed=False),
                      'semantic_evidence':evidence_candidates(text,material_context=bool(document_title and document_category(document_title)=='materials')),
                      'scanned_page_inspection':ocr,
                      'has_text':bool(text.strip())})
    return {'status':'inspected_consultation_only', 'sha256':hashlib.sha256(payload).hexdigest(),
            'bytes':len(payload), 'page_count':len(reader.pages), 'pages_inspected':len(pages), 'pages':pages,
            'truncated':len(reader.pages)>max_pages, 'alignment_status':'unverified',
            'limitations':['Scale/revision labels are candidates, not verified dimensions or coordinates',
                           'Embedded control consistency is not independent surveyed registration',
                           'Bounded OCR labels are unplaced candidates, not registration or physical geometry',
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
                    max_search_pages=12, max_documents=500, max_pdf_inspections=6, bounds=None, reference_features=None):
    result = {'provider':SOURCE['id'], 'status':'not_supported', 'application_search':'not_attempted',
              'applications':[], 'documents':[], 'failures':[], 'terms_url':TERMS,
              'reuse_status':'consultation_only', 'geometry_replacements':0,
              'limitations':['Runnymede only; address search is not a verified spatial association',
                             'PDFs are inspected temporarily for consultation, not redistributed or used as world geometry']}
    if not any(a.get('reference') == 'E60000275' for a in authorities):
        return result
    result['status'] = 'checked'
    references = []
    contexts = []
    target_names = building_search_names(reference_features)
    result['building_search_names'] = target_names
    for record in planning_records:
        for match in REFERENCE.findall(str(record.get('reference',''))):
            if match.upper() not in references:
                references.append(match.upper())
    with requests.Session() as session:
        session.headers.update({'User-Agent':USER_AGENT})
        if site_name:
            try:
                initial = session.get(SEARCH,timeout=(10,30)); initial.raise_for_status()
                response = session.post(SEARCH,data=search_form(initial.text,site_name),
                    headers={'Referer':SEARCH},timeout=(10,30))
                visited=set()
                result['search_pages_inspected']=0
                for page in range(max_search_pages):
                    response.raise_for_status()
                    found, next_url = parse_results(response.text,base_url=response.url)
                    result['search_pages_inspected']+=1
                    contexts.extend(application_context(response.text,target_names=target_names))
                    references.extend(ref for ref in found if ref not in references)
                    if not next_url:
                        result['application_search']='completed_address_candidates'
                        break
                    if page == max_search_pages-1:
                        result['application_search']='truncated'
                        break
                    if urlparse(next_url).hostname != 'planning.runnymede.gov.uk':
                        raise ValueError('Unexpected council pagination host')
                    if next_url in visited:
                        raise ValueError('Repeated council pagination URL')
                    visited.add(next_url)
                    response = session.get(next_url,headers={'Referer':response.url},timeout=(10,30))
            except (requests.RequestException,ValueError) as error:
                result['application_search']='blocked_or_unavailable'
                result['failures'].append({'stage':'application_search','reason':str(error)})
        else:
            result['application_search']='site_name_unavailable'
        references = application_order(references, contexts)
        result['application_context'] = contexts
        result['application_priority']='named_buildings_and_related_permissions_then_other_parents_materials_recent'
        result['application_candidates'] = references
        result['uninspected_application_references'] = references[max_applications:]
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
        named_applications={c['reference'] for c in contexts if c.get('target_name_matches')}
        named_applications.update(r for c in contexts if c.get('target_name_matches') for r in c['related_references'])
        candidates = inspection_order(result['documents'],priority_applications=named_applications)
        for document in candidates[:max_pdf_inspections]:
            try:
                document['inspection']=inspect_pdf(read_pdf(session,document['url']),bounds=bounds,document_title=document['title'],reference_features=reference_features)
                registrations=[p['registration']['status'] for p in document['inspection']['pages']]
                fitted_grids=[grid for p in document['inspection']['pages']
                              if (grid:=p.get('scanned_page_inspection',{}).get('border_grid_inspection',{}))
                              .get('grid_mark_registration',{}).get('status')=='internally_consistent_grid_marks_unverified']
                offsite={'grid_outside_requested_area','requested_area_outside_crs_domain'}
                drawing_grid_fit=any(grid.get('grid_location_check',{}).get('status') not in offsite
                                     for grid in fitted_grids)
                document['alignment_status']=('candidate_alignment' if 'candidate_alignment' in registrations else
                    'candidate_drawing_grid_fit_unverified' if drawing_grid_fit else
                    'drawing_grid_outside_requested_area' if fitted_grids else 'unavailable_or_rejected')
            except (requests.RequestException,ValueError,PdfReadError,TypeError,KeyError) as error:
                document['inspection']={'status':'unavailable_or_rejected','reason':str(error)}
        result['inspection_budget_omitted']=max(0,len(candidates)-max_pdf_inspections)
    (output/'council-drawings.json').write_text(json.dumps(result,indent=2))
    return result
