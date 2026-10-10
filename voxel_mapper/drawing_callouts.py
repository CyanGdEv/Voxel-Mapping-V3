"""Trace explicit numbered material leaders in ordinary native drawings; no feature promotion."""
import argparse
from collections import Counter,defaultdict
import json
import math
from pathlib import Path
import re
import pymupdf
from shapely.geometry import Polygon,Point
from .drawing_annotations import contiguous_runs,file_hash

VERSION='numbered-material-leaders-v1'
LEGEND=re.compile(r'^(\d{1,2})\.\s+(Roof|Upper Section of walls|Lower sections? of walls)\s*-\s*(.*)$',re.I)


def text(run):return ''.join(chr(c[0]) for c in run['chars']).strip()
def node(p):return tuple(round(float(v),3) for v in p)


def legend_entries(runs):
    entries=defaultdict(list)
    for i,run in enumerate(runs):
        match=LEGEND.fullmatch(text(run))
        if not match:continue
        parts=[run];last=run;d=run['dir'];normal=(-d[1],d[0])
        for other in runs[i+1:i+4]:
            if not other['chars'] or not last['chars']:break
            delta=[other['chars'][0][2][k]-last['chars'][0][2][k] for k in (0,1)]
            along=sum(delta[k]*d[k] for k in (0,1));across=sum(delta[k]*normal[k] for k in (0,1))
            if (any(other.get(k)!=run.get(k) for k in ('dir','font','size','opacity','type','layer'))
                    or not 0<abs(across)<=1.8*run['size'] or abs(along)>.5*run['size']
                    or not 0<other['seqno']-last['seqno']<=4 or LEGEND.fullmatch(text(other))):break
            parts.append(other);last=other
        entries[match[1]].append({'number':match[1],'component_class_candidate':'roof_surface' if match[2].lower()=='roof' else 'wall_face',
                    'legend_text':' '.join(text(p) for p in parts),'trace_indices':[i for p in parts for i in p['trace_indices']],
                    'paint_seqnos':[s for p in parts for s in p['paint_seqnos']],
                    'span_boxes':[{'bbox':list(p['bbox']),'paint_seqnos':p['paint_seqnos']} for p in parts],
                    'text_rendering_supported':all(p.get('type') in (0,1) and p.get('opacity',0)>0 and not p.get('layer') for p in parts),
                    'visibility_verified':False,'material_as_built_verified':False})
    return entries


def page_callouts(page,sha,page_number,*,max_paths=100000,max_spans=10000):
    paths=page.get_drawings(extended=True);raw=page.get_texttrace()
    if len(paths)>max_paths or len(raw)>max_spans:raise ValueError('Material leader page budget exceeded')
    if sum(len(t['chars']) for t in raw)>500000:raise ValueError('Material leader text budget exceeded')
    runs=contiguous_runs(raw);legends=legend_entries(runs);graph=defaultdict(list);arrows=defaultdict(list);fills=[];counts=Counter()
    for path in paths:
        if path.get('level',0)!=0 or path.get('layer') or path['type'] not in ('s','f','fs'):continue
        if path['type']=='s' and path.get('stroke_opacity',1)>0 and path.get('dashes') in (None,'[] 0') and not path.get('closePath') and len(path['items'])==1 and path['items'][0][0]=='l':
            a,b=[node(p) for p in path['items'][0][1:3]]
            if a==b:continue
            graph[a].append((b,path['seqno']));graph[b].append((a,path['seqno']))
        if path['type'] in ('f','fs') and path.get('fill_opacity',1)>0:
            items=path['items'];points=None
            if len(items)==1 and items[0][0]=='re':
                r=items[0][1];points=[(r.x0,r.y0),(r.x1,r.y0),(r.x1,r.y1),(r.x0,r.y1)]
            elif all(item[0]=='l' for item in items) and 3<=len(items)<=100:
                if all(node(items[i][2])==node(items[(i+1)%len(items)][1]) for i in range(len(items))):points=[tuple(item[1]) for item in items]
            if not points:continue
            polygon=Polygon(points)
            if not polygon.is_valid or polygon.is_empty:continue
            if len(points)==3:
                lengths=[math.dist(points[(i+1)%3],points[(i+2)%3]) for i in range(3)]
                tip=min(range(3),key=lambda i:lengths[i]);base=lengths[tip]
                midpoint=[(points[(tip+1)%3][k]+points[(tip+2)%3][k])/2 for k in (0,1)]
                height=math.dist(points[tip],midpoint)
                if .5<=base<=8 and 2*base<=height<=20:
                    arrows[node(points[tip])].append({'paint_seqno':path['seqno'],'triangle_page_points':points})
            if polygon.area>=50:fills.append((path['seqno'],polygon))
    if len(graph)>40000:raise ValueError('Material leader segment budget exceeded')
    if sum(text(r) in legends for r in runs)>500:raise ValueError('Material leader callout budget exceeded')
    results=[]
    for run in runs:
        number=text(run)
        if number not in legends or not re.fullmatch(r'\d{1,2}',number):continue
        if run.get('type') not in (0,1) or run.get('opacity',0)<=0 or run.get('layer'):continue
        bbox=run['bbox'];tolerance=.8*run['size'];starts=[]
        for p,edges in graph.items():
            distance=math.hypot(max(bbox[0]-p[0],p[0]-bbox[2],0),max(bbox[1]-p[1],p[1]-bbox[3],0))
            if len(edges)==1 and distance<=tolerance:starts.append(p)
        candidates=[]
        for start in starts:
            current=start;previous=None;nodes=[start];seqs=[]
            for _ in range(4):
                choices=[(p,s) for p,s in graph[current] if p!=previous]
                if len(choices)!=1:break
                following,seq=choices[0];seqs.append(seq);nodes.append(following);previous,current=current,following
                if len(graph[current])==1:
                    if len(arrows[current])==1 and sum(math.dist(nodes[i],nodes[i+1]) for i in range(len(nodes)-1))<=1000:
                        candidates.append({'leader_points':nodes,'leader_paint_seqnos':seqs,'arrow':arrows[current][0]})
                    break
                if current in nodes[:-1]:break
        result={'document_sha256':sha,'page':page_number,'number':number,'label_bbox_page_points':list(bbox),
                'label_trace_indices':run['trace_indices'],'label_paint_seqnos':run['paint_seqnos'],
                'status':'withheld_ambiguous_or_missing_connection','legend_candidates':legends[number],
                'leader_candidates':candidates,'component_association_verified':False,'accepted_feature':False,
                'registration_verified':False,'world_geometry_additions':0}
        if len(candidates)==1 and len(legends[number])==1:
            match=candidates[0];tip=match['leader_points'][-1];start=pymupdf.Rect(bbox)
            # Filled background masks painted before text do not hide text. A later
            # overlapping fill does require a visibility-aware review.
            legend=legends[number][0]
            hazard=[]
            for path in paths:
                if path['type'] not in ('f','fs'):continue
                if path.get('seqno',-1)>max(run['paint_seqnos']) and path['rect'].intersects(start):hazard.append(path['seqno'])
                for span in legend['span_boxes']:
                    if path.get('seqno',-1)>max(span['paint_seqnos']) and path['rect'].intersects(pymupdf.Rect(span['bbox'])):hazard.append(path['seqno'])
            result['visibility_hazard_paint_seqnos']=hazard[:100]
            result['status']='withheld_label_or_legend_visibility' if hazard or not legend['text_rendering_supported'] else 'explicit_material_anchor_candidate'
            result['component_class_candidate']=legends[number][0]['component_class_candidate']
            result['target_page_point']=tip
            result['target_fill_paint_candidates']=[seq for seq,polygon in fills if polygon.contains(Point(tip))][:20]
            result['outline_identity_verified']=False
            result['connection_basis']='unique nearby terminal, unbranched native leader chain, explicit triangular arrow and exact numbered legend'
        results.append(result);counts[result['status']]+=1
    return results,{'document_sha256':sha,'page':page_number,'native_paths':len(paths),'legend_numbers':sorted(legends),'callout_statuses':dict(counts),
                    'coordinate_basis':'MuPDF unrotated page points; not metres or park-grid geometry'}


def run(documents_file,output,max_pages=10000):
    if type(max_pages) is not int or not 1<=max_pages<=10000:raise ValueError('Bounded material leader pages required')
    path=Path(documents_file);documents=json.loads(path.read_text());resolved=[]
    if not isinstance(documents,list) or not 1<=len(documents)<=1000:raise ValueError('Bounded pinned document list required')
    seen=set()
    for item in documents:
        if item['sha256'] in seen:raise ValueError('Distinct pinned PDFs required')
        seen.add(item['sha256'])
        pdf=(path.parent/item['file']).resolve()
        if pdf.stat().st_size>20000000 or file_hash(pdf)!=item['sha256']:raise ValueError('Bounded pinned PDF required')
        resolved.append((pdf,item))
    contract={'version':VERSION,'documents_sha256':file_hash(path),'pdf_sha256':[item['sha256'] for _,item in resolved],'max_pages':max_pages}
    output=Path(output)
    if output.exists():
        report=json.loads((output/'callout-report.json').read_text())
        if report['contract']!=contract or file_hash(output/'callouts.jsonl')!=report['callouts_sha256']:raise ValueError('Material leader inputs or output changed')
        return report
    partial=output.with_name(output.name+'.partial')
    if partial.exists():raise ValueError('Incomplete material leader run; use a fresh directory')
    partial.mkdir(parents=True);pages=[];counts=Counter();total=0
    with (partial/'callouts.jsonl').open('w') as stream:
        for pdf,item in resolved:
            with pymupdf.open(pdf) as document:
                if len(document)>1000 or len(pages)+len(document)>max_pages:raise ValueError('Material leader page budget exceeded')
                for n,page in enumerate(document,1):
                    try:records,receipt=page_callouts(page,item['sha256'],n)
                    except ValueError as error:records=[];receipt={'document_sha256':item['sha256'],'page':n,'status':'withheld','reason':str(error)}
                    for record in records:stream.write(json.dumps(record,sort_keys=True)+'\n');counts[record['status']]+=1
                    pages.append(receipt);total+=len(records)
    report={'status':'unplaced_component_anchor_evidence','contract':contract,'pages':pages,'callout_records':total,'callout_statuses':dict(counts),
            'callouts_sha256':file_hash(partial/'callouts.jsonl'),'accepted_controls':0,'accepted_checkpoints':0,'world_geometry_additions':0,
            'limitations':['Native leader connectivity is an unverified annotation association, not component outline or material identity verification.',
                           'Clipped/layered paths, branched chains, multiple legends/arrows and ambiguous starts are not resolved by nearest matching.',
                           'All visibility, drawing-state, metre-scale, datum and independent registration gates remain required.']}
    (partial/'callout-report.json').write_text(json.dumps(report,indent=2)+'\n');partial.replace(output);return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--documents',required=True);p.add_argument('--output',required=True);args=p.parse_args()
    print(json.dumps(run(args.documents,args.output),indent=2))


if __name__=='__main__':main()
