"""Spatial native-PDF annotation evidence; never an automatically placed feature feed."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import pymupdf
import numpy as np

VERSION='native-annotation-evidence-v1'
LEVEL=re.compile(r'\b(?:level|lvl|bridge|ridge|parapet|FFL|eaves|trough|HP\d+)\b.*?([+-]?\s*\d{2,3}\.\d{1,3})\s*$',re.I)
DIMENSION=re.compile(r'^([0-9]+(?:\.[0-9]+)?)\s*(mm|m)\s*$',re.I)
SLOPE=re.compile(r'^1\s*:\s*(\d+(?:\.\d+)?)\s+Slope\s+(Up|Down)$',re.I)
MATERIAL=re.compile(r'\b(?:timber|thatch(?:ed)?|metal|steel|concrete|brick|sandstone|asphalt|cladding|boarding|sheeting)\b',re.I)
VIEW=re.compile(r'\b(?:Elevation\s+\d+|Section\s+[A-Z]{1,3}|Floor Plan|Roof Plan)\b',re.I)


def file_hash(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def categories(text):
    result=[]
    if m:=LEVEL.search(text):result.append({'kind':'level','value_m_candidate':float(m[1].replace(' ','')),'vertical_datum_verified':False})
    if m:=DIMENSION.fullmatch(text):
        value=float(m[1]);result.append({'kind':'explicit_dimension','value_m_candidate':value/(1000 if m[2].lower()=='mm' else 1),'printed_units':m[2].lower()})
    elif re.fullmatch(r'\d{3,6}',text):result.append({'kind':'untyped_numeric','printed_value':int(text),'units_verified':False})
    if m:=SLOPE.fullmatch(text):
        denominator=float(m[1])
        if denominator>0:result.append({'kind':'slope_ratio','rise_per_run_candidate':(1 if m[2].lower()=='up' else -1)/denominator,'axes_verified':False})
    if m:=re.fullmatch(r'GIA\s+(\d+(?:\.\d+)?)\s*m(?:2|²)',text,re.I):
        result.append({'kind':'area','value_m2_candidate':float(m[1]),'footprint_identity_verified':False})
    if MATERIAL.search(text):result.append({'kind':'material_note','terms':sorted({m[0].lower() for m in MATERIAL.finditer(text)}),'component_identity_verified':False})
    if VIEW.search(text):result.append({'kind':'view_label','view_identity_verified':False})
    if re.search(r'\b(?:existing|proposed|planning)\b',text,re.I):result.append({'kind':'state_wording','drawing_state_verified':False})
    return result


def contiguous_runs(traces):
    """Join only adjacent collinear native fragments; preserve each paint/glyph identity."""
    groups=[]
    for index,t in enumerate(traces):
        current={**t,'chars':list(t['chars']),'trace_indices':[index],'paint_seqnos':[t['seqno']]}
        if groups and t['chars']:
            last=groups[-1];d=t['dir'];n=(-d[1],d[0]);size=t['size']
            def project(point,axis):return point[0]*axis[0]+point[1]*axis[1]
            def along_bounds(bbox):
                x0,y0,x1,y1=bbox
                return sorted(project(p,d) for p in [(x0,y0),(x0,y1),(x1,y0),(x1,y1)])
            gap=along_bounds(t['bbox'])[0]-along_bounds(last['bbox'])[-1]
            same_style=all(t.get(k)==last.get(k) for k in ('dir','font','size','opacity','type','layer','color'))
            if (same_style and last['chars'] and 0<=t['seqno']-last['paint_seqnos'][-1]<=4
                    and abs(project(t['chars'][0][2],n)-project(last['chars'][-1][2],n))<=.15*size
                    and -.1*size<=gap<=1.5*size):
                if gap>.15*size:last['chars'].append((32,0,t['chars'][0][2],t['chars'][0][3]))
                last['chars'].extend(t['chars']);last['bbox']=list(pymupdf.Rect(last['bbox'])|pymupdf.Rect(t['bbox']))
                last['trace_indices'].append(index);last['paint_seqnos'].append(t['seqno']);continue
        groups.append(current)
    return groups


def page_annotations(page,sha,page_number,*,max_spans=10000,max_paints=500000):
    """Retain actual glyph origins, orientations and paint sequence. Visibility is screened, not certified."""
    traces=page.get_texttrace();paints=page.get_bboxlog()
    if len(traces)>max_spans or len(paints)>max_paints:raise ValueError('Native annotation page budget exceeded')
    if sum(len(t['chars']) for t in traces)>500000:raise ValueError('Native annotation character budget exceeded')
    records=[]
    occluding_paints=[(i,bbox) for i,(kind,bbox) in enumerate(paints) if kind in ('fill-path','fill-image','fill-shade')]
    paint_ids=np.asarray([i for i,_ in occluding_paints],dtype=np.int64)
    paint_boxes=np.asarray([b for _,b in occluding_paints],dtype=float).reshape(-1,4)
    for index,t in enumerate(contiguous_runs(traces)):
        text=''.join(chr(c[0]) for c in t['chars']).strip();claims=categories(text)
        if not claims:continue
        bbox=list(t['bbox']);direction=list(t['dir']);size=float(t['size']);seq=t['seqno']
        if not all(math.isfinite(v) for v in [*bbox,*direction,size]):raise ValueError('Finite native text geometry required')
        overlaps=(paint_ids>seq)&(paint_boxes[:,0]<bbox[2])&(paint_boxes[:,2]>bbox[0])&(paint_boxes[:,1]<bbox[3])&(paint_boxes[:,3]>bbox[1])
        occluders=paint_ids[overlaps].tolist()
        reasons=[]
        if t.get('type') not in (0,1) or t.get('opacity',0)<=0:reasons.append('invisible_or_unsupported_text_rendering')
        if t.get('layer'):reasons.append('optional_layer_visibility_unverified')
        if occluders:reasons.append('later_fill_overlap_visibility_review_required')
        identity=hashlib.sha256(f'{sha}:{page_number}:{index}:{text}'.encode()).hexdigest()
        records.append({'id':identity,'document_sha256':sha,'page':page_number,'text':text,'bbox_page_points':bbox,
                        'direction':direction,'font_size_points':size,'paint_seqno':seq,'trace_indices':t['trace_indices'],'paint_seqnos':t['paint_seqnos'],
                        'glyph_origins_page_points':[list(c[2]) for c in t['chars']],
                        'claims':claims,'visibility_screen':'withheld' if reasons else 'no_detected_visibility_hazard',
                        'visibility_verified':False,'visibility_reasons':reasons,'later_fill_overlap_seqnos':occluders[:100],
                        'overlap_list_truncated':len(occluders)>100,'component_association_verified':False,
                        'registration_verified':False,'accepted_feature':False})
    # Candidate links are orientation-aware, not nearest-text snapping. Keep every
    # compatible numeric span and require a unique candidate before comparing values.
    for record in records:
        level=next((c for c in record['claims'] if c['kind']=='level'),None)
        if level is None or record['visibility_screen']=='withheld':continue
        d=record['direction'];normal=[-d[1],d[0]]
        def ranges(r):
            x0,y0,x1,y1=r['bbox_page_points'];corners=[(x0,y0),(x0,y1),(x1,y0),(x1,y1)]
            a=[x*d[0]+y*d[1] for x,y in corners];b=[x*normal[0]+y*normal[1] for x,y in corners]
            return min(a),max(a),min(b),max(b)
        a0,a1,b0,b1=ranges(record);possible=[]
        for other in records:
            numeric=next((c for c in other['claims'] if c['kind']=='untyped_numeric'),None)
            if numeric is None or other['visibility_screen']=='withheld' or math.dist(other['direction'],d)>1e-6:continue
            c0,c1,e0,e1=ranges(other);gap=max(b0-e1,e0-b1,0)
            if gap<=2*record['font_size_points'] and min(a1,c1)>=max(a0,c0):possible.append((other,numeric))
        record['adjacent_numeric_candidates']=[o['id'] for o,_ in possible]
        if len(possible)==1:
            other,numeric=possible[0];delta=abs(numeric['printed_value']/1000-level['value_m_candidate'])
            record['numeric_level_comparison']={'status':'conflicting_candidate_values' if delta>.005 else 'consistent_candidate_values',
                        'numeric_annotation_id':other['id'],'assumed_numeric_units':'mm_unverified','difference_m_candidate':delta,
                        'association_verified':False,'automatic_geometry_allowed':False}
    return records,{'page':page_number,'rotation_degrees':page.rotation,'mediabox_page_points':list(page.mediabox),
                    'coordinate_basis':'MuPDF unrotated page points; not metres or the park grid',
                    'native_text_spans':len(traces),'annotation_records':len(records)}


def run(documents_file,output,*,max_pages=10000):
    if type(max_pages) is not int or not 1<=max_pages<=10000:raise ValueError('Bounded page budget required')
    path=Path(documents_file);documents=json.loads(path.read_text())
    if not isinstance(documents,list) or not 1<=len(documents)<=1000:raise ValueError('One to 1000 pinned document records required')
    resolved=[];seen=set()
    for item in documents:
        pdf=(path.parent/item['file']).resolve()
        if pdf.stat().st_size>20000000:raise ValueError('Native annotation PDF byte budget exceeded')
        sha=file_hash(pdf)
        if sha!=item['sha256'] or sha in seen:raise ValueError('Distinct pinned PDF bytes required')
        seen.add(sha);resolved.append((pdf,item))
    contract={'version':VERSION,'documents_sha256':file_hash(path),'pdf_sha256':[item['sha256'] for _,item in resolved],'max_pages':max_pages}
    output=Path(output)
    if output.exists():
        report=json.loads((output/'annotation-report.json').read_text())
        if report['contract']!=contract:raise ValueError('Native annotation inputs changed')
        if file_hash(output/'annotations.jsonl')!=report['annotations_sha256']:raise ValueError('Native annotation output checksum mismatch')
        return report
    partial=output.with_name(output.name+'.partial')
    if partial.exists():raise ValueError('Incomplete native annotation run; use a fresh output directory')
    partial.mkdir(parents=True);pages=[];counts=Counter();visibility=Counter();comparisons=Counter();total=0
    with (partial/'annotations.jsonl').open('w') as stream:
        for pdf,item in resolved:
            with pymupdf.open(pdf) as document:
                if len(document)>1000 or len(pages)+len(document)>max_pages:raise ValueError('Native annotation page budget exceeded')
                for n,page in enumerate(document,1):
                    records,receipt=page_annotations(page,item['sha256'],n)
                    for r in records:
                        r['source_context']={k:item[k] for k in ('url','attachment_label','source_state','upload_date_as_listed') if k in item}
                        stream.write(json.dumps(r,sort_keys=True)+'\n');counts.update(c['kind'] for c in r['claims']);visibility[r['visibility_screen']]+=1
                        if 'numeric_level_comparison' in r:comparisons[r['numeric_level_comparison']['status']]+=1
                    pages.append({'document_sha256':item['sha256'],**receipt});total+=len(records)
    report={'status':'unplaced_native_annotation_evidence','contract':contract,'documents':len(documents),'pages':pages,
            'annotation_records':total,'claim_counts':dict(counts),'visibility_counts':dict(visibility),'numeric_level_comparisons':dict(comparisons),
            'annotations_sha256':file_hash(partial/'annotations.jsonl'),'accepted_controls':0,'accepted_checkpoints':0,'world_geometry_additions':0,
            'limitations':['Text and proximity candidates are not verified component dimensions or survey controls.',
                           'Paint overlap screening is conservative; absence of overlap does not certify visible text.',
                           'Page coordinates and level candidates have no verified horizontal registration or vertical datum.',
                           'Source revision/as-built status and material identity require evidence before feature promotion.']}
    (partial/'annotation-report.json').write_text(json.dumps(report,indent=2)+'\n');partial.replace(output);return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--documents',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();print(json.dumps(run(args.documents,args.output),indent=2))


if __name__=='__main__':main()
