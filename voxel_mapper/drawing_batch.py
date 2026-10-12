"""Source-linked drawing triage and horizontal registration review; no geometry insertion."""
import argparse
from collections import Counter
import hashlib
import math
import json
from pathlib import Path
import re
import time

from .drawing_evidence import evidence_candidates
from .geopdf import inspect_registration
from .drawing_controls import inspect_coordinate_labels
from .reconstruction.registration import review_registration,registration_domain
from .drawing_page_tools import native_inspection_page,inspect_ocr_page,native_lines,match_landmarks,reference_landmarks

VERSION='drawing-batch-v5'
RULES={
 'site_plan':r'\b(site plan|site layout|general arrangement|masterplan)\b',
 'ride_layout':r'\b(track layout|ride layout|roller coaster|coaster layout)\b',
 'elevation_section':r'\b(elevations?|cross section|sections?)\b',
 'landscape_paths':r'\b(landscape|landscaping|paving|footpath|paths|plaza)\b',
 'structural_detail':r'\b(structural|foundation|steelwork|support detail|construction detail)\b',
 'survey':r'\b(topographic|topographical|land survey|measured survey|bathymetric)\b',
 'water_drainage':r'\b(drainage|flood|water level|lake|watercourse)\b',
 'report':r'\b(report|statement|assessment|appraisal)\b',
 'location_plan':r'\b(location plan|block plan)\b',
}
SCALE=re.compile(r'\b1\s*[:/]\s*(\d{1,6})(?![\d.])')


def classify(titles,text):
    candidates=[]
    for category,pattern in RULES.items():
        title_hits=[t for t in titles if re.search(pattern,t,re.I)]
        body_hits=len(re.findall(pattern,text,re.I))
        if title_hits or body_hits:candidates.append({'category':category,'score':3*len(title_hits)+min(body_hits,3),'title_matches':title_hits,'body_matches':body_hits})
    candidates.sort(key=lambda r:(-r['score'],r['category']))
    primary=candidates[0]['category'] if candidates and (len(candidates)==1 or candidates[0]['score']>candidates[1]['score']) else 'unclassified' if not candidates else 'ambiguous'
    return {'primary':primary,'candidates':candidates,'status':'heuristic_triage; not physical-object classification'}


def construction_state(records,text):
    declared=sorted({r.get('state','unknown') for r in records})
    labels=[]
    for label,pattern in [('proposed',r'\bproposed\b'),('existing',r'\bexisting\b'),('as_built',r'\bas[ -]built\b')]:
        if re.search(pattern,text,re.I):labels.append(label)
    known=set(declared+labels)-{'unknown',''}
    return {'candidate':'mixed' if len(known)>1 else next(iter(known)) if known else 'unknown','declared_states':declared,'text_labels':labels,'authoritative_current_state':False}


def reviewed_alignment(spec,page):
    from pyproj import CRS
    if spec.get('local_frame')!='pdf_native_points_y_up' or spec.get('landmark_identity_reviewed') is not True:
        raise ValueError('Explicit native PDF frame and reviewed landmark identity required')
    crs=CRS.from_user_input(spec['target_crs'])
    if not crs.is_projected or any(abs(a.unit_conversion_factor-1)>1e-9 for a in crs.axis_info[:2]):raise ValueError('Projected metre review target required')
    left,bottom,right,top=map(float,page.cropbox)
    for row in spec['controls']+spec['checkpoints']:
        if not row.get('source_id') or not row.get('source_sha256') or not re.fullmatch('[0-9a-f]{64}',row['source_sha256']):raise ValueError('Control/checkpoint source identity and SHA256 required')
        x,y=row['local']
        if not left<=x<=right or not bottom<=y<=top:raise ValueError('Review point outside page crop')
    if any(r.get('independent') is not True for r in spec['checkpoints']):raise ValueError('Independent checkpoint provenance required')
    control_sources={(r['source_id'],r['source_sha256']) for r in spec['controls']}
    if any((r['source_id'],r['source_sha256']) in control_sources for r in spec['checkpoints']):raise ValueError('Checkpoints share control source')
    report=review_registration(spec['controls'],spec['checkpoints'],tolerance_m=spec.get('tolerance_m',1),expected_scale=spec['expected_metres_per_pdf_point'],scale_tolerance=spec.get('scale_tolerance',.02))
    if report['status']=='accepted_horizontal_fit':
        from shapely.geometry import mapping
        report['validated_domain']=mapping(registration_domain(report))
    return {**report,'target_crs':crs.to_string(),'local_frame':spec['local_frame'],'authorization':'horizontal review only; construction state and vertical datum remain separate'}


def analyze(corpus,*,max_pages=10000,registration=True,reviews=None,ocr=True,max_ocr_pages=50,max_ocr_seconds=180,landmarks=None):
    import pymupdf
    from pypdf import PdfReader
    if isinstance(max_pages,bool) or not isinstance(max_pages,int) or not 1<=max_pages<=100000:raise ValueError('Invalid analysis page budget')
    if not isinstance(max_ocr_pages,int) or isinstance(max_ocr_pages,bool) or not 0<=max_ocr_pages<=1000 or not math.isfinite(max_ocr_seconds) or not 0<=max_ocr_seconds<=3600:raise ValueError('Invalid OCR run budget')
    landmarks=landmarks or []
    if len(landmarks)>5000:raise ValueError('Named landmark budget exceeded')
    reviews=reviews or []
    if not isinstance(reviews,list) or len(reviews)>100000:raise ValueError('Bounded review list required')
    review_map={}
    for spec in reviews:
        if not isinstance(spec,dict) or not re.fullmatch('[0-9a-f]{64}',str(spec.get('document_sha256',''))) or isinstance(spec.get('page'),bool) or not isinstance(spec.get('page'),int) or spec['page']<1:
            raise ValueError('Review requires PDF SHA256 and positive page number')
        key=(spec['document_sha256'],spec['page'])
        if key in review_map:raise ValueError('Duplicate page review')
        review_map[key]=spec
    options={'version':VERSION,'registration':registration,'reviews':reviews,'ocr':ocr,'landmarks':landmarks}
    contract=hashlib.sha256(json.dumps(options,sort_keys=True).encode()).hexdigest()
    corpus.db.execute('CREATE TABLE IF NOT EXISTS drawing_analysis(sha TEXT,page INTEGER,contract TEXT,result TEXT,PRIMARY KEY(sha,page,contract))')
    processed=resumed=0;errors=[];matched_reviews=set();valid_blobs=set();ocr_attempts=0;ocr_seconds=0
    blobs=corpus.db.execute("SELECT DISTINCT sha FROM downloads WHERE status='downloaded' ORDER BY sha").fetchall()
    for (sha,) in blobs:
        records=[json.loads(r) for (r,) in corpus.db.execute('SELECT documents.record FROM documents JOIN downloads USING(url) WHERE downloads.sha=? AND downloads.status=\'downloaded\' ORDER BY documents.id',(sha,))]
        titles=sorted({r.get('title','') for r in records})
        # Classification depends on catalogue state/titles as well as PDF bytes.
        document_contract=hashlib.sha256((contract+json.dumps(records,sort_keys=True)).encode()).hexdigest()
        path=corpus.root/'files'/f'{sha}.pdf'
        try:
            with path.open('rb') as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=sha:raise ValueError('Retained PDF checksum mismatch')
            with pymupdf.open(path) as pdf:
                valid_blobs.add(sha)
                reader=None
                for index in range(len(pdf)):
                    key=(sha,index+1)
                    if key in review_map:matched_reviews.add(key)
                    cached=corpus.db.execute('SELECT result FROM drawing_analysis WHERE sha=? AND page=? AND contract=?',(sha,index+1,document_contract)).fetchone()
                    retry_ocr=cached and json.loads(cached[0]).get('ocr',{}).get('status') in ('deferred','unavailable') and ocr and ocr_attempts<max_ocr_pages and ocr_seconds<max_ocr_seconds
                    if cached and not retry_ocr:resumed+=1;continue
                    if processed>=max_pages:break
                    page=pdf[index];text=page.get_text();truncated=len(text)>500000;text=text[:500000]
                    ocr_result={'status':'disabled' if not ocr else 'native_text_sufficient'};ocr_labels=[]
                    if ocr and len(text.strip())<80:
                        if ocr_attempts>=max_ocr_pages or ocr_seconds>=max_ocr_seconds:ocr_result={'status':'deferred','reason':'OCR run budget exhausted; resume later'}
                        else:
                            start=time.monotonic();ocr_attempts+=1
                            ocr_result,ocr_labels=inspect_ocr_page(page,timeout=min(20,max_ocr_seconds-ocr_seconds))
                            ocr_seconds+=time.monotonic()-start
                    classification=classify(titles,text+'\n'+'\n'.join(line['text'] for line in ocr_labels))
                    result={'document_sha256':sha,'page':index+1,'document_pages':len(pdf),'titles':titles,'application_references':sorted({r.get('applicationReference',r.get('application_reference','unknown')) for r in records}),
                            'classification':classification,'construction_state':construction_state(records,text),'native_text_truncated':truncated,'ocr':ocr_result,
                            'scale_denominator_candidates':sorted({int(v) for v in SCALE.findall(text) if 1<=int(v)<=100000}|set(ocr_result.get('printed_scale_candidates',[]))),
                            'evidence_candidates':evidence_candidates(text),'page_frame':{'kind':'pymupdf_points_y_down','cropbox':list(page.cropbox),'rotation':page.rotation},
                            'horizontal_alignment':{'status':'not_inspected'},'world_geometry_additions':0}
                    if registration or key in review_map:
                        try:
                            if reader is None:reader=PdfReader(path,strict=False)
                            native,rotation_review=native_inspection_page(reader.pages[index])
                            result['rotation_normalization']=rotation_review
                            result['registration_frame']={'kind':'pdf_native_points_y_up','cropbox':list(map(float,native.cropbox))}
                            if key in review_map:result['horizontal_alignment']=reviewed_alignment(review_map[key],native)
                            elif registration:
                                embedded=inspect_registration(native)
                                attempts={'embedded':embedded}
                                if embedded['status']=='metadata_missing':
                                    contents=native.get_contents()
                                    if contents is not None and len(contents.get_data())>2000000:raise ValueError('Registration content budget exceeded')
                                    attempts['crosshairs']=inspect_coordinate_labels(native,reuse_allowed=True,require_marks=True)
                                    attempts['grid']=inspect_coordinate_labels(native,reuse_allowed=True,require_grid=True)
                                candidate=any(r['status']=='candidate_alignment' for r in attempts.values())
                                result['horizontal_alignment']={'status':'candidate_alignment' if candidate else 'needs_controls','attempts':attempts,'independent_accuracy':'not_verified'}
                        except Exception as exc:result['horizontal_alignment']={'status':'withheld','reason':str(exc)}
                    if landmarks:
                        try:result['landmark_matching']=match_landmarks(native_lines(page)+ocr_labels,landmarks,result['scale_denominator_candidates'])
                        except Exception as exc:result['landmark_matching']={'status':'withheld','reason':str(exc),'registration_verified':False}
                    with corpus.db:corpus.db.execute('INSERT OR REPLACE INTO drawing_analysis VALUES(?,?,?,?)',(sha,index+1,document_contract,json.dumps(result,sort_keys=True)))
                    processed+=1
        except Exception as exc:errors.append({'document_sha256':sha,'error':str(exc)})
    # Export the current result for each page, preserving prior analysis versions in SQLite.
    output=corpus.root/'drawing-analysis.jsonl';temporary=output.with_suffix('.partial');categories=Counter();alignments=Counter();states=Counter();ocr_statuses=Counter();count=0;rotated=0;landmark_matches=0
    with temporary.open('w') as stream:
        for (sha,) in blobs:
            if sha not in valid_blobs:continue
            records=[json.loads(r) for (r,) in corpus.db.execute('SELECT documents.record FROM documents JOIN downloads USING(url) WHERE downloads.sha=? AND downloads.status=\'downloaded\' ORDER BY documents.id',(sha,))]
            document_contract=hashlib.sha256((contract+json.dumps(records,sort_keys=True)).encode()).hexdigest()
            for (raw,) in corpus.db.execute('SELECT result FROM drawing_analysis WHERE sha=? AND contract=? ORDER BY page',(sha,document_contract)):
                result=json.loads(raw);stream.write(raw+'\n');count+=1;categories[result['classification']['primary']]+=1;alignments[result['horizontal_alignment']['status']]+=1;states[result['construction_state']['candidate']]+=1
                ocr_statuses[result.get('ocr',{}).get('status','unknown')]+=1
                rotated+=int(bool(result.get('rotation_normalization',{}).get('original_rotation_degrees',0)))
                landmark_matches+=len(result.get('landmark_matching',{}).get('matches',[]))
    temporary.replace(output)
    with output.open('rb') as stream:output_hash=hashlib.file_digest(stream,'sha256').hexdigest()
    report={'status':'drawing_triage_only','contract':contract,'validated_pdf_blobs':len(valid_blobs),'analyzed_pages':count,'run_analyzed_pages':processed,'resumed_pages':resumed,'categories':dict(categories),'alignment_statuses':dict(alignments),'construction_state_candidates':dict(states),'errors':errors,'unmatched_review_pages':[{'document_sha256':k[0],'page':k[1]} for k in sorted(set(review_map)-matched_reviews)],'world_geometry_additions':0,'output':output.name,'output_sha256':output_hash}
    report.update(ocr_statuses=dict(ocr_statuses),run_ocr_attempts=ocr_attempts,run_ocr_seconds=ocr_seconds,normalized_rotated_pages=rotated,named_landmark_matches=landmark_matches)
    (corpus.root/'drawing-analysis-report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    from .planning_bulk import Corpus
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',required=True);p.add_argument('--max-pages',type=int,default=10000);p.add_argument('--classification-only',action='store_true');p.add_argument('--reviews')
    p.add_argument('--no-ocr',action='store_true');p.add_argument('--max-ocr-pages',type=int,default=50);p.add_argument('--max-ocr-seconds',type=float,default=180)
    p.add_argument('--landmarks');p.add_argument('--landmark-crs');p.add_argument('--target-crs');a=p.parse_args()
    references=None
    if a.landmarks:
        if not a.landmark_crs or not a.target_crs:p.error('Landmarks require explicit source and target CRS')
        data=Path(a.landmarks).read_bytes();references=reference_landmarks(json.loads(data),a.landmark_crs,a.target_crs,hashlib.sha256(data).hexdigest())
    corpus=Corpus(a.corpus)
    try:print(json.dumps(analyze(corpus,max_pages=a.max_pages,registration=not a.classification_only,reviews=json.loads(Path(a.reviews).read_text()) if a.reviews else None,ocr=not a.no_ocr,max_ocr_pages=a.max_ocr_pages,max_ocr_seconds=a.max_ocr_seconds,landmarks=references),indent=2))
    finally:corpus.close()

if __name__=='__main__':main()
