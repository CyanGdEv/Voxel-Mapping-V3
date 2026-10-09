"""Source-linked embedded/grid anchor audit; application coordinates remain location hints."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from .alton_registration import fit_axis_labels
from .drawing_page_tools import native_inspection_page,native_lines
from .drawing_controls import inspect_coordinate_labels
from .geopdf import inspect_registration

VERSION='anchor-audit-v2'
LOCATION=re.compile(r'\bEasting\s*:\s*(\d{1,9}(?:\.\d+)?)\s*Northing\s*:\s*(\d{1,9}(?:\.\d+)?)(?![\d.])',re.I)
AXIS=re.compile(r'^\s*(\d{6})\s*([EN])\s*$',re.I)


def page_audit(native_page,rendered_page,bounds):
    text=rendered_page.get_text()
    if len(text)>500000:raise ValueError('Anchor native-text budget exceeded')
    locations=[{'easting':float(m[1]),'northing':float(m[2]),'crs':None,'status':'application_location_hint; no drawing-point attachment','registration_eligible':False} for m in LOCATION.finditer(text)]
    if len(locations)>64:raise ValueError('Application location hint budget exceeded')
    native,frame=native_inspection_page(native_page);embedded=inspect_registration(native,bounds)
    explicit={}
    has_explicit_labels=bool(re.search(r'\bEPSG\s*[:=]?\s*\d{4,6}\b',text,re.I)) and bool(re.search(r'\b(?:E|N|Easting|Northing)\s*[:=]\s*[+-]?\d',text,re.I))
    if embedded['status']=='metadata_missing' and has_explicit_labels:
        for mode in ('crosshair','grid'):
            explicit[mode]=inspect_coordinate_labels(native,bounds,reuse_allowed=True,require_marks=mode=='crosshair',require_grid=mode=='grid')
    if embedded['status']=='metadata_missing' and not has_explicit_labels:
        explicit={'preflight':{'status':'not_attempted','reason':'Native text lacks explicit EPSG plus coordinate labels; no inferred CRS or geometry search'}}
    labels=[]
    for line in native_lines(rendered_page):
        match=AXIS.fullmatch(line['text'])
        if match:
            labels.append({'axis':match[2].upper(),'value':int(match[1]),'position':line['local'][0 if match[2].upper()=='E' else 1],'local':line['local'],'origin':'native_text_box_center; not a measured grid intersection'})
    if len(labels)>64:raise ValueError('Axis label budget exceeded')
    axis=fit_axis_labels(labels,bounds)
    return {'status':'anchor_candidates_only','page_frame':frame,'embedded_registration':embedded,'explicit_mark_grid':explicit,'axis_label_count':len(labels),'axis_labels':labels,'axis_alignment':axis,'application_location_hints':locations,'registration_verified':False,'world_geometry_additions':0}


def run(corpus,output,bounds,*,max_pages=10000):
    import pymupdf
    from pypdf import PdfReader
    if type(max_pages)!=int or not 1<=max_pages<=100000:raise ValueError('Positive bounded page budget required')
    if len(bounds)!=4 or not -180<=bounds[0]<bounds[2]<=180 or not -90<bounds[1]<bounds[3]<90:raise ValueError('Valid WGS84 audit bounds required')
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    contract=hashlib.sha256(json.dumps({'version':VERSION,'bounds':bounds},sort_keys=True).encode()).hexdigest()
    corpus.db.execute('CREATE TABLE IF NOT EXISTS anchor_pages(sha TEXT,page INTEGER,contract TEXT,result TEXT,PRIMARY KEY(sha,page,contract))')
    valid=set();processed=resumed=0;errors=[]
    for (sha,) in corpus.db.execute("SELECT DISTINCT sha FROM downloads WHERE status='downloaded' ORDER BY sha").fetchall():
        try:
            path=corpus.root/'files'/f'{sha}.pdf'
            with path.open('rb') as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=sha:raise ValueError('PDF checksum mismatch')
            with pymupdf.open(path) as doc:
                valid.add(sha);reader=None
                for i in range(len(doc)):
                    if corpus.db.execute('SELECT 1 FROM anchor_pages WHERE sha=? AND page=? AND contract=?',(sha,i+1,contract)).fetchone():resumed+=1;continue
                    if processed>=max_pages:break
                    try:
                        if reader is None:reader=PdfReader(path)
                        result=page_audit(reader.pages[i],doc[i],bounds)
                    except Exception as exc:result={'status':'withheld','reason':str(exc),'registration_verified':False,'world_geometry_additions':0}
                    with corpus.db:corpus.db.execute('INSERT INTO anchor_pages VALUES(?,?,?,?)',(sha,i+1,contract,json.dumps(result,sort_keys=True)))
                    processed+=1
        except Exception as exc:errors.append({'document_sha256':sha,'error':str(exc)})
    counts=Counter();temporary=output/'anchor-candidates.jsonl.partial';digest=hashlib.sha256()
    with temporary.open('wb') as stream:
        for sha in sorted(valid):
            records=[json.loads(r) for (r,) in corpus.db.execute('SELECT record FROM documents JOIN downloads USING(url) WHERE downloads.sha=? ORDER BY documents.id',(sha,))]
            refs=sorted({r.get('applicationReference',r.get('application_reference','')) for r in records})
            contexts=sorted({r.get('application_context','') for r in records})
            for page,raw in corpus.db.execute('SELECT page,result FROM anchor_pages WHERE sha=? AND contract=? ORDER BY page',(sha,contract)):
                row=json.loads(raw);counts['pages']+=1;counts[row['status']]+=1
                counts['application_location_hints']+=len(row.get('application_location_hints',[]));counts['pages_with_axis_labels']+=int(bool(row.get('axis_label_count')))
                counts['embedded_candidates']+=int(row.get('embedded_registration',{}).get('status')=='candidate_alignment')
                counts['explicit_mark_grid_candidates']+=sum(r['status']=='candidate_alignment' for r in row.get('explicit_mark_grid',{}).values())
                counts['axis_hypotheses']+=int(row.get('axis_alignment',{}).get('status')=='native_label_alignment_hypothesis')
                row.update(document_sha256=sha,page=page,application_references=refs,application_contexts=contexts,park_membership_verified=False)
                encoded=(json.dumps(row,sort_keys=True)+'\n').encode();stream.write(encoded);digest.update(encoded)
    temporary.replace(output/'anchor-candidates.jsonl')
    report={'version':VERSION,'contract':contract,'status':'unverified_anchor_audit','bounds_wgs84':bounds,'counts':dict(counts),'validated_pdf_blobs':len(valid),'run_pages':processed,'resumed_pages':resumed,'errors':errors,'output_sha256':digest.hexdigest(),'verified_registrations':0,'world_geometry_additions':0}
    (output/'anchor-report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    from .planning_bulk import Corpus
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',required=True);p.add_argument('--output',required=True);p.add_argument('--bounds',type=float,nargs=4,required=True);p.add_argument('--max-pages',type=int,default=10000);a=p.parse_args();corpus=Corpus(a.corpus)
    try:print(json.dumps(run(corpus,a.output,a.bounds,max_pages=a.max_pages),indent=2))
    finally:corpus.close()

if __name__=='__main__':main()
