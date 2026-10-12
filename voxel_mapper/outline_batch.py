"""Resumable source-pinned outline review and alignment-work prioritisation."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .drawing_layout import OutlineReview, cached_page, contract_identity, options
from .drawing_footprints import retained_page_candidates
from .footprint_matching import lines

VERSION='outline-batch-v1'


def file_hash(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def priority(row):
    """Rank review effort only; labels and counts cannot establish controls."""
    if row['layout_status']!='layout_hypotheses_only':return 5
    if row['hinted_polygons']>=3:return 0
    if row['hinted_polygons']:return 1
    if row['unflagged_polygons']>=3:return 2
    if row['hinted_candidates']:return 3
    return 4


def check_index(db):
    try:
        if db.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:raise ValueError('Outline checkpoint failed integrity check; use a fresh output directory')
    except sqlite3.DatabaseError as exc:raise ValueError('Outline checkpoint failed integrity check; use a fresh output directory') from exc


def run(corpus,candidates,output,*,max_records=2500000):
    import pymupdf
    if type(max_records) is not int or not 1<=max_records<=2500000:raise ValueError('Record budget must be 1..2500000')
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    contract={'version':VERSION,'candidate_sha256':file_hash(candidates),'layout_contract':contract_identity(options({})),'max_records':max_records}
    db=sqlite3.connect(output/'outline-index.sqlite')
    try:
        check_index(db)
        db.execute('PRAGMA journal_mode=WAL')
    except Exception:
        db.close();raise
    db.executescript('CREATE TABLE IF NOT EXISTS metadata(contract TEXT NOT NULL); CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY,result TEXT NOT NULL); CREATE TEMP TABLE seen(id TEXT PRIMARY KEY);')
    previous=db.execute('SELECT contract FROM metadata').fetchone()
    if previous and json.loads(previous[0])!=contract:
        db.close();raise ValueError('Outline review inputs changed; use a fresh output directory')
    if not previous:
        with db:db.execute('INSERT INTO metadata VALUES(?)',(json.dumps(contract),))
    key=None;count=resumed=processed=0;counts=Counter();pages={}
    try:
        with (output/'outline-review.jsonl.partial').open('w') as stream:
            for candidate in lines(candidates):
                count+=1
                if count>max_records:raise ValueError('Outline review record budget exceeded')
                try:db.execute('INSERT INTO seen VALUES(?)',(candidate['id'],))
                except sqlite3.IntegrityError as exc:raise ValueError('Duplicate candidate identity') from exc
                current=(candidate['document_sha256'],candidate['page'],candidate.get('extraction_kind'),candidate.get('extraction_contract'))
                if current!=key:
                    sha,page=current[:2]
                    if not re.fullmatch('[0-9a-f]{64}',sha):raise ValueError('Invalid PDF identity')
                    path=corpus.root/'files'/f'{sha}.pdf'
                    if file_hash(path)!=sha:raise ValueError('Source PDF checksum mismatch')
                    retained={c['id']:c for c in retained_page_candidates(corpus,candidate)}
                    with pymupdf.open(path) as doc:layout=cached_page(corpus,doc[page-1],sha,page)
                    reviewer=OutlineReview(layout);key=current
                    page_key=(sha,page)
                    if page_key not in pages:
                        if len(pages)>=10000:raise ValueError('Review page-summary budget exceeded')
                        records=[json.loads(raw) for raw, in corpus.db.execute('SELECT DISTINCT documents.record FROM documents JOIN downloads USING(url) WHERE downloads.sha=? ORDER BY documents.record LIMIT 65',(sha,))]
                        scale_labels=[{'text':l['text'],'bbox':l['bbox'],'scales':l['scale_labels']} for l in layout['labels'] if l['visibility_status']=='visible_native_text' and l['scale_labels']]
                        pages[page_key]={'document_sha256':sha,'page':page,'layout_status':layout['status'],'candidates':0,'polygons':0,'unflagged_polygons':0,'hinted_candidates':0,'hinted_polygons':0,'flagged_candidates':0,'families':Counter(),'flags':Counter(),'paper_size_hypothesis':layout.get('paper_size_hypothesis'),'regions':len(layout['regions']),'native_scale_labels':scale_labels[:256],'deferred_scale_labels':max(0,len(scale_labels)-256),'sources':[{'title':r.get('title'),'drawing_state':r.get('state','unknown'),'application_reference':r.get('applicationReference',r.get('application_reference')),'url':r['url']} for r in records[:64]],'source_metadata_truncated':len(records)>64,'registration_verified':False,'world_geometry_additions':0}
                if retained.get(candidate['id'])!=candidate:raise ValueError('Candidate differs from retained page extraction')
                cached=db.execute('SELECT result FROM reviews WHERE id=?',(candidate['id'],)).fetchone()
                if cached:result=json.loads(cached[0]);resumed+=1
                else:
                    result=reviewer.get(candidate);processed+=1
                    db.execute('INSERT INTO reviews VALUES(?,?)',(candidate['id'],json.dumps(result)))
                if count%1000==0:db.commit()
                counts[result['status']]+=1;counts.update(result['review_flags'])
                stream.write(json.dumps(result)+'\n')
                row=pages[(current[0],current[1])];polygon=candidate['geometry']['type'] in ('Polygon','MultiPolygon')
                row['candidates']+=1;row['polygons']+=int(polygon);row['flagged_candidates']+=int(bool(result['review_flags']))
                row['unflagged_polygons']+=int(polygon and not result['review_flags'])
                row['hinted_candidates']+=int(bool(result['semantic_hints']));row['hinted_polygons']+=int(polygon and bool(result['semantic_hints']))
                row['families'].update(sorted({f for hint in result['semantic_hints'] for f in hint['families']}));row['flags'].update(result['review_flags'])
            db.commit()
        check_index(db)
        if file_hash(candidates)!=contract['candidate_sha256']:raise ValueError('Candidate feed changed during review')
        (output/'outline-review.jsonl.partial').replace(output/'outline-review.jsonl')
        ranked=sorted(pages.values(),key=lambda r:(priority(r),-r['hinted_polygons'],-r['hinted_candidates'],-r['unflagged_polygons'],r['document_sha256'],r['page']))
        with (output/'alignment-priority.jsonl.partial').open('w') as stream:
            for rank,row in enumerate(ranked,1):
                row.update(rank=rank,review_priority_tier=priority(row),status='alignment_work_queue_only',required_next=['review viewport and physical outline identity','independent surveyed control and checkpoint evidence','confirm current as-built state, reuse permission, dimensions and materials'])
                stream.write(json.dumps(row,sort_keys=True)+'\n')
        (output/'alignment-priority.jsonl.partial').replace(output/'alignment-priority.jsonl')
        report={**contract,'candidates':count,'run_candidates':processed,'resumed_candidates':resumed,'pages_with_candidates':len(pages),'counts':dict(counts),'priority_tiers':dict(Counter(priority(r) for r in ranked)),'file_sha256':{f:file_hash(output/f) for f in ('outline-review.jsonl','alignment-priority.jsonl')},'physical_identity_verified':False,'registration_verified':False,'world_geometry_additions':0}
        (output/'outline-batch-report.json').write_text(json.dumps(report,indent=2)+'\n');return report
    finally:db.close()


def main():
    from .planning_bulk import Corpus
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('corpus','candidates','output'):p.add_argument('--'+name,required=True)
    p.add_argument('--max-records',type=int,default=2500000);a=p.parse_args();corpus=Corpus(a.corpus)
    try:print(json.dumps(run(corpus,a.candidates,a.output,max_records=a.max_records),indent=2))
    finally:corpus.close()

if __name__=='__main__':main()
