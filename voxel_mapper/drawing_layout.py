"""Native paint-order visibility, drawing regions and outline review hints."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from shapely.geometry import box, mapping, shape
from shapely.strtree import STRtree

from .drawing_geometry import subpaths, validated_options
from .drawing_page_tools import native_inverse
from .drawing_footprints import fill_geometry

VERSION='drawing-layout-v1'
DEFAULTS={'max_paths':100000,'max_labels':20000,'max_masks':5000,'max_mask_points':50000,'max_regions':256}
SCALE=re.compile(r'\b1\s*[:/]\s*(\d{1,6})\b(?:\s*@\s*(A[0-6]))?',re.I)
PAPERS={'A0':(841,1189),'A1':(594,841),'A2':(420,594),'A3':(297,420),'A4':(210,297),'A5':(148,210),'A6':(105,148)}
PANEL=re.compile(r'\b(IMPORTANT NOTE|GENERAL NOTES|LEGEND|DRAWING NO|DRAWING NUMBER|REVISION|ARCHITECTS)\b|^KEY\s*:',re.I)
FAMILIES={'building':r'\b(building|hotel|restaurant|station)\b','path':r'\b(path|footpath|tarmac|paving)\b','wall':r'\bwall\b','fence':r'\bfence\b','water':r'\b(lake|water|pond)\b','rock':r'\b(rock|stone)\b','bridge':r'\bbridge\b'}


def options(values):
    if set(values)-set(DEFAULTS):raise ValueError('Unknown layout option')
    result={**DEFAULTS,**values}
    for key,value in result.items():
        if type(value) is not int or not 1<=value<=DEFAULTS[key]*2:raise ValueError('Invalid bounded layout option: '+key)
    return result


def contract_identity(opts):
    import pymupdf
    return hashlib.sha256(json.dumps({'version':VERSION,'reader':pymupdf.__version__,'options':opts},sort_keys=True).encode()).hexdigest()


def cached_page(corpus,page,sha,page_number,**overrides):
    opts=options(overrides);contract=contract_identity(opts)
    corpus.db.execute('CREATE TABLE IF NOT EXISTS layout_pages(sha TEXT,page INTEGER,contract TEXT,result TEXT,PRIMARY KEY(sha,page,contract))')
    cached=corpus.db.execute('SELECT result FROM layout_pages WHERE sha=? AND page=? AND contract=?',(sha,page_number,contract)).fetchone()
    if cached:return json.loads(cached[0])
    try:result=inspect_page(page,sha,page_number,**opts)
    except (ValueError,TypeError,KeyError) as exc:result={'status':'withheld','reason':str(exc),'labels':[],'regions':[],'world_geometry_additions':0}
    with corpus.db:corpus.db.execute('INSERT INTO layout_pages VALUES(?,?,?,?)',(sha,page_number,contract,json.dumps(result)))
    return result


def inspect_page(page,sha,page_number,**overrides):
    """Keep original coordinates and all uncertain/hidden labels for review."""
    import pymupdf
    opts=options(overrides);matrix=native_inverse(page);rotation=page.rotation
    try:
        page.set_rotation(0);frame=box(*(page.rect*matrix))
        paths=page.get_cdrawings(extended=True)
        if len(paths)>opts['max_paths']:return {'status':'withheld_path_budget','labels':[],'regions':[],'occluders':[],'world_geometry_additions':0}
        traces=page.get_texttrace()
        if len(traces)>opts['max_labels']*8 or sum(len(t['chars']) for t in traces)>1000000:raise ValueError('Text trace budget exceeded')
        trace_boxes=[box(*t['bbox']) for t in traces];trace_index=STRtree(trace_boxes)
        masks=[];regions=[];clips=[];groups=[];points=0;seq_by_ordinal={};regions_deferred=0
        def region(geom,kind,ordinal,seq):
            nonlocal regions_deferred
            if len(regions)>=opts['max_regions']:
                regions_deferred+=1;return
            digest=hashlib.sha256((sha+'/'+str(page_number)+'/'+kind+'/'+geom.normalize().wkb_hex).encode()).hexdigest()
            if not any(r['id']==digest for r in regions):regions.append({'id':digest,'kind':kind,'bbox':list(geom.bounds),'paint_ordinal':ordinal,'seqno':seq,'role':'unreviewed_drawing_region','scale_labels':[]})
        for ordinal,path in enumerate(paths):
            level=path.get('level',0);clips=[r for r in clips if r[0]<level];groups=[r for r in groups if r<level]
            if path['type']=='group':groups.append(level);continue
            seq=path.get('seqno');seq_by_ordinal[str(ordinal)]=seq
            if path['type']=='clip':
                try:
                    rings,_=subpaths(path,matrix,validated_options({}));rings=[p+[p[0]] if p[0]!=p[-1] else p for p in rings]
                    geom=fill_geometry(rings,path.get('even_odd',False),True)
                    if geom.is_empty or not geom.is_valid or not geom.equals(box(*geom.bounds)):raise ValueError('Unsupported clip')
                    clips.append((level,geom));
                    if geom.area<frame.area*.98:region(geom,'native_clip_rectangle',ordinal,seq)
                except (ValueError,TypeError,KeyError):clips.append((level,None))
                continue
            if 'f' not in path['type'] and path['type']!='s':continue
            if not path.get('rect') or not isinstance(seq,int):continue
            bounds=box(*(pymupdf.Rect(path['rect'])*matrix))
            if bounds.is_empty:continue
            supported=not groups and not path.get('layer') and all(c[1] is not None for c in clips)
            geom=None
            try:
                rings,_=subpaths(path,matrix,validated_options({}))
                if 'f' in path['type']:
                    rings=[p+[p[0]] if p[0]!=p[-1] else p for p in rings]
                    count=sum(len(r) for r in rings)
                    if points+count>opts['max_mask_points']:raise ValueError('Mask point budget')
                    geom=fill_geometry(rings,path.get('even_odd',False),True);points+=count
                elif len(rings)==1 and rings[0][0]==rings[0][-1]:geom=shape({'type':'Polygon','coordinates':rings})
                if geom is not None and (geom.is_empty or not geom.is_valid):geom=None
                if geom is not None and supported:
                    for _,clip in clips:geom=geom.intersection(clip)
                    if geom.is_empty:continue
                    if not geom.is_valid:geom=None
            except (ValueError,TypeError,KeyError):geom=None
            if 'f' in path['type']:
                if len(masks)>=opts['max_masks']:raise ValueError('Occluder budget exceeded')
                exact=supported and path.get('fill_opacity',1)==1 and geom is not None
                masks.append({'bbox':list(bounds.bounds),'geometry':mapping(geom) if exact else None,'seqno':seq,'paint_ordinal':ordinal,'status':'opaque_native_fill' if exact else 'possible_fill_occlusion','fill':path.get('fill')})
                if exact and geom.equals(box(*geom.bounds)) and geom.area>=max(1000,frame.area*.005) and geom.area<frame.area*.85 and path.get('fill')==(1.,1.,1.):region(geom,'opaque_white_rectangle',ordinal,seq)
            elif supported and geom is not None and geom.equals(box(*geom.bounds)) and frame.area*.03<=geom.area<frame.area*.9:region(geom,'stroked_frame_hypothesis',ordinal,seq)
        for seq,(kind,bounds) in enumerate(page.get_bboxlog()):
            if kind=='fill-image':
                if len(masks)>=opts['max_masks']:raise ValueError('Occluder budget exceeded')
                masks.append({'bbox':list((pymupdf.Rect(bounds)*matrix)),'geometry':None,'seqno':seq,'paint_ordinal':None,'status':'possible_image_occlusion','fill':None})
        mask_geometries=[shape(m['geometry']) if m['geometry'] else box(*m['bbox']) for m in masks];mask_index=STRtree(mask_geometries)
        labels=[]
        def normalized(text):return re.sub(r'\s+','',text).casefold()
        for block in page.get_text('dict',flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)['blocks']:
            for line in block.get('lines',[]):
                text=' '.join(s['text'] for s in line['spans']).strip()
                if not text:continue
                bbox=box(*line['bbox']);native=box(*(pymupdf.Rect(line['bbox'])*matrix))
                hits=[];bound_boxes={};parts=[]
                for i in sorted(int(i) for i in trace_index.query(bbox)):
                    x0,y0,x1,y1=line['bbox']
                    chars=[c for c in traces[i]['chars'] if x0-.01<=(c[3][0]+c[3][2])/2<=x1+.01 and y0-.01<=(c[3][1]+c[3][3])/2<=y1+.01]
                    part=''.join(chr(c[0]) for c in chars if 0<=c[0]<=0x10ffff)
                    if not normalized(part) or normalized(part) not in normalized(text):continue
                    hits.append(i);parts.append(part)
                    bound_boxes[i]=pymupdf.Rect(min(c[3][0] for c in chars),min(c[3][1] for c in chars),max(c[3][2] for c in chars),max(c[3][3] for c in chars))
                rendered=''.join(parts)
                status='visible_native_text' if hits and normalized(rendered)==normalized(text) else 'unverified_text_trace_binding'
                reasons=[]
                if status=='visible_native_text':
                    for i in hits:
                        trace=traces[i]
                        if trace.get('type')==3 or trace.get('opacity',1)!=1:
                            reasons.append('invisible_or_nonopaque_text');continue
                        area=box(*(bound_boxes[i]*matrix))
                        for j in mask_index.query(area):
                            m=masks[int(j)]
                            if m['seqno']<=trace['seqno'] or not mask_geometries[int(j)].intersects(area):continue
                            reasons.append('covered_by_later_opaque_fill' if m['geometry'] and mask_geometries[int(j)].covers(area) else 'partially_or_possibly_occluded')
                    if reasons:status='withheld_occluded_or_invisible_text'
                membership=[r['id'] for r in regions if box(*r['bbox']).covers(native)]
                scales=[{'denominator':int(m.group(1)),'paper':m.group(2).upper() if m.group(2) else None} for m in SCALE.finditer(text) if 1<=int(m.group(1))<=100000]
                labels.append({'text':text,'bbox':list(native.bounds),'local':list(native.centroid.coords[0]),'visibility_status':status,'visibility_reasons':sorted(set(reasons)),'trace_seqnos':sorted({traces[i]['seqno'] for i in hits}),'region_ids':membership,'scale_labels':scales,'origin':'native_text_box_center_unverified'})
                if len(labels)>opts['max_labels']:raise ValueError('Native label budget exceeded')
        for r in regions:
            contained=[l for l in labels if r['id'] in l['region_ids'] and l['visibility_status']=='visible_native_text']
            clues=[l['text'] for l in contained if PANEL.search(l['text'])]
            if clues and r['kind']=='opaque_white_rectangle':r.update(role='annotation_panel_hypothesis',annotation_clues=clues[:16])
            r['scale_labels']=[{**s,'label_bbox':l['bbox']} for l in contained for s in l['scale_labels']]
        mm=sorted([page.mediabox.width*25.4/72,page.mediabox.height*25.4/72]);paper=[k for k,v in PAPERS.items() if all(abs(a-b)<=3 for a,b in zip(mm,v))]
        return {'status':'layout_hypotheses_only','labels':labels,'regions':regions,'regions_deferred':regions_deferred,'occluders':masks,'paint_seqnos':seq_by_ordinal,'page_frame':list(frame.bounds),'paper_size_hypothesis':paper[0] if len(paper)==1 else None,'source_pdf_modified':False,'physical_identity_verified':False,'registration_verified':False,'world_geometry_additions':0}
    finally:page.set_rotation(rotation)


def outline_review(candidate,layout):
    """Triage original geometry; never accepts material, identity or registration."""
    return OutlineReview(layout).get(candidate)


class OutlineReview:
    def __init__(self,layout):
        self.layout=layout
        self.masks=layout.get('occluders',[])
        self.geometries=[shape(m['geometry']) if m['geometry'] else box(*m['bbox']) for m in self.masks]
        self.index=STRtree(self.geometries)
        self.panels=[r for r in layout['regions'] if r['role']=='annotation_panel_hypothesis']
        self.hints=[];self.label_boxes=[]
        for l in layout['labels']:
            if l['visibility_status']!='visible_native_text' or any(box(*r['bbox']).covers(box(*l['bbox'])) for r in self.panels):continue
            families=[k for k,pattern in FAMILIES.items() if re.search(pattern,l['text'],re.I)]
            if not families:continue
            self.hints.append({'families':families,'text':l['text'],'bbox':l['bbox'],'association':'native_label_proximity_hypothesis'})
            self.label_boxes.append(box(*l['bbox']))
        self.label_index=STRtree(self.label_boxes)

    def get(self,candidate):
        return self._get(candidate,self.layout)

    def _get(self,candidate,layout):
        geom=shape(candidate['geometry']);panels=self.panels;flags=[]
        regions=[r['id'] for r in layout['regions'] if r['kind'] in ('native_clip_rectangle','stroked_frame_hypothesis') and box(*r['bbox']).covers(geom)]
        if any(box(*r['bbox']).intersects(geom) for r in panels):flags.append('annotation_panel_overlap')
        paints=candidate.get('paint_references',[]);seqs=[layout.get('paint_seqnos',{}).get(str(p['ordinal'])) for p in paints]
        if not seqs or any(s is None for s in seqs):flags.append('paint_order_unverified')
        else:
            nearby=[int(i) for i in self.index.query(geom)]
            if all(any(self.masks[i]['seqno']>s and self.masks[i]['geometry'] and self.geometries[i].covers(geom) for i in nearby) for s in seqs):flags.append('all_original_paints_occluded')
        hints=[]
        if not flags:
            nearby=sorted(int(i) for i in self.label_index.query(box(*geom.bounds).buffer(3)))
            hints=[self.hints[i] for i in nearby if geom.distance(self.label_boxes[i])<=3][:16]
        return {'candidate_id':candidate['id'],'document_sha256':candidate['document_sha256'],'page':candidate['page'],'region_ids':regions,'review_flags':flags,'semantic_hints':hints,'status':'annotation_or_occluded_review' if flags else 'physical_outline_hypothesis' if hints else 'unclassified_outline','physical_identity_verified':False,'registration_verified':False,'world_geometry_additions':0}


def run(corpus,output,*,max_pages=10000,**overrides):
    import pymupdf
    opts=options(overrides)
    if type(max_pages) is not int or not 1<=max_pages<=100000:raise ValueError('Bounded page budget required')
    contract=contract_identity(opts)
    corpus.db.execute('CREATE TABLE IF NOT EXISTS layout_pages(sha TEXT,page INTEGER,contract TEXT,result TEXT,PRIMARY KEY(sha,page,contract))')
    output=Path(output);output.mkdir(parents=True,exist_ok=True);counts=Counter();processed=resumed=0;errors=[];valid=set()
    for sha, in corpus.db.execute("SELECT DISTINCT sha FROM downloads WHERE status='downloaded' ORDER BY sha").fetchall():
        try:
            path=corpus.root/'files'/f'{sha}.pdf'
            with path.open('rb') as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=sha:raise ValueError('PDF checksum mismatch')
            with pymupdf.open(path) as doc:
                valid.add(sha)
                for index,page in enumerate(doc):
                    cached=corpus.db.execute('SELECT result FROM layout_pages WHERE sha=? AND page=? AND contract=?',(sha,index+1,contract)).fetchone()
                    if cached:resumed+=1;continue
                    if processed>=max_pages:break
                    try:result=inspect_page(page,sha,index+1,**opts)
                    except (ValueError,TypeError,KeyError) as exc:result={'status':'withheld','reason':str(exc),'labels':[],'regions':[],'world_geometry_additions':0}
                    with corpus.db:corpus.db.execute('INSERT INTO layout_pages VALUES(?,?,?,?)',(sha,index+1,contract,json.dumps(result)))
                    processed+=1
        except Exception as exc:errors.append({'document_sha256':sha,'reason':str(exc)})
    pages=0
    with (output/'layout-pages.jsonl.partial').open('w') as stream:
        for sha,page,raw in corpus.db.execute('SELECT sha,page,result FROM layout_pages WHERE contract=? ORDER BY sha,page',(contract,)):
            if sha not in valid:continue
            result=json.loads(raw);pages+=1;counts[result['status']]+=1
            counts.update(l['visibility_status'] for l in result['labels']);counts.update(r['role'] for r in result['regions'])
            # Large paint/trace internals remain in the page cache, not the review feed.
            public={k:v for k,v in result.items() if k not in ('occluders','paint_seqnos')};public.update(document_sha256=sha,page=page)
            stream.write(json.dumps(public)+'\n')
    (output/'layout-pages.jsonl.partial').replace(output/'layout-pages.jsonl')
    with (output/'layout-pages.jsonl').open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    report={'version':VERSION,'contract':contract,'options':opts,'pages':pages,'run_pages':processed,'resumed_pages':resumed,'counts':dict(counts),'errors':errors,'output_sha256':digest,'world_geometry_additions':0}
    (output/'layout-report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def review_candidates(corpus,candidates,output,*,max_records=2500000):
    """Stream source-pinned candidates through a single bounded page reviewer."""
    import pymupdf
    from .drawing_footprints import retained_page_candidates
    from .footprint_matching import lines
    if type(max_records) is not int or not 1<=max_records<=2500000:raise ValueError('Record budget must be 1..2500000')
    output=Path(output);output.mkdir(parents=True,exist_ok=True);key=None;counts=Counter();count=0
    with (output/'outline-review.jsonl.partial').open('w') as stream:
        for candidate in lines(candidates):
            count+=1
            if count>max_records:raise ValueError('Outline review record budget exceeded')
            current=(candidate['document_sha256'],candidate['page'],candidate.get('extraction_kind'),candidate.get('extraction_contract'))
            if current!=key:
                sha,page=current[:2]
                if not re.fullmatch('[0-9a-f]{64}',sha):raise ValueError('Invalid PDF identity')
                path=corpus.root/'files'/f'{sha}.pdf'
                with path.open('rb') as source:
                    if hashlib.file_digest(source,'sha256').hexdigest()!=sha:raise ValueError('Source PDF checksum mismatch')
                retained={c['id']:c for c in retained_page_candidates(corpus,candidate)}
                with pymupdf.open(path) as doc:reviewer=OutlineReview(cached_page(corpus,doc[page-1],sha,page))
                key=current
            if retained.get(candidate['id'])!=candidate:raise ValueError('Candidate differs from retained page extraction')
            result=reviewer.get(candidate);counts[result['status']]+=1;counts.update(result['review_flags'])
            stream.write(json.dumps(result)+'\n')
    (output/'outline-review.jsonl.partial').replace(output/'outline-review.jsonl')
    with Path(candidates).open('rb') as source:source_hash=hashlib.file_digest(source,'sha256').hexdigest()
    with (output/'outline-review.jsonl').open('rb') as source:output_hash=hashlib.file_digest(source,'sha256').hexdigest()
    report={'version':VERSION,'contract':contract_identity(options({})),'candidates':count,'counts':dict(counts),'candidate_sha256':source_hash,'output_sha256':output_hash,'max_records':max_records,'world_geometry_additions':0}
    (output/'outline-report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    from .planning_bulk import Corpus
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',required=True);p.add_argument('--output',required=True);p.add_argument('--max-pages',type=int,default=10000);p.add_argument('--candidates');a=p.parse_args();corpus=Corpus(a.corpus)
    try:
        print(json.dumps(run(corpus,a.output,max_pages=a.max_pages),indent=2))
        if a.candidates:print(json.dumps(review_candidates(corpus,a.candidates,a.output),indent=2))
    finally:corpus.close()

if __name__=='__main__':main()
