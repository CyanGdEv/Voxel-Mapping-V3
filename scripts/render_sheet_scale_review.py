"""Offline original-sheet review of automatic peripheral-text scale evidence."""
import argparse
import base64
import hashlib
import json
from pathlib import Path

import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import shape

from voxel_mapper.drawing_page_tools import native_to_render_pixels
from voxel_mapper.generation_cycles import file_hash


def render(components, corpus, output):
    components,corpus,output=Path(components),Path(corpus),Path(output)
    report=json.loads((components/'component-report.json').read_text())
    for name,pin in report['output_sha256'].items():
        if file_hash(components/name)!=pin:raise ValueError('Component review artifact changed')
    scale=json.loads((components/report['sheet_scale_evidence']['file']).read_text())
    alignment=json.loads((components/report['facade_alignment']['file']).read_text())
    pages={(p['document_sha256'],p['page']):p for p in scale['pages']};images={}
    inventories={r['view_id']:json.loads((components/r['file']).read_text()) for r in report['results']}
    def path(geometry,matrix):
        geometry=affine_transform(shape(geometry),[matrix.a,matrix.c,matrix.b,matrix.d,matrix.e,matrix.f])
        return ' '.join('M'+' L'.join(f'{x:.6f},{y:.6f}' for x,y in ring.coords)+' Z'
            for part in (geometry.geoms if geometry.geom_type=='MultiPolygon' else [geometry])
            for ring in [part.exterior,*part.interiors])
    for pair in scale['pairs']:
        if pair['status']!='supported_furniture_layout_correspondence_only':continue
        for field in ('subject_page_key','reference_page_key'):
            key=tuple(pair[field]);label=json.dumps(list(key),separators=(',',':'))
            if label in images:continue
            source=corpus/'files'/(key[0]+'.pdf')
            if file_hash(source)!=key[0]:raise ValueError('Original source PDF changed')
            with pymupdf.open(source) as document:
                page=document[key[1]-1];factor=1200/page.rect.width
                image=page.get_pixmap(matrix=pymupdf.Matrix(factor,factor),alpha=False)
                png=image.tobytes('png');matrix=pymupdf.Matrix(native_to_render_pixels(page,1200))
            shapes=[];seen=set()
            for row in alignment['frames']:
                inventory=inventories[row['plan_view_id']]
                if (inventory['document_sha256'],inventory['page'])!=key:continue
                for review in row['frame_reviews']:
                    for extent in review['plan_extents']:
                        digest=hashlib.sha256(json.dumps(extent['geometry_pdf_native'],sort_keys=True).encode()).hexdigest()
                        if digest in seen:continue
                        seen.add(digest);shapes.append({'d':path(extent['geometry_pdf_native'],matrix),
                            'kind':extent['source_kind'],'holes':extent['source_hole_count']})
            images[label]={'size':[image.width,image.height],'png':'data:image/png;base64,'+base64.b64encode(png).decode(),
                'png_sha256':hashlib.sha256(png).hexdigest(),'source_native_to_pixels_matrix':list(matrix),
                'document_sha256':key[0],'page':key[1],'source_extents':shapes}
            if file_hash(source)!=key[0]:raise ValueError('Source changed during review render')
    payload={'scale':scale,'alignment':alignment,'images':images}
    embedded=json.dumps(payload,separators=(',',':')).replace('<','\\u003c')
    html='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Independent page-layout scale evidence</title>
<style>body{font:16px system-ui;margin:24px;background:#f7f8fa;color:#17212b}p{line-height:1.5;max-width:1200px}select{font:inherit;padding:7px}table{width:100%;border-collapse:collapse;margin:16px 0}th,td{padding:8px;border-bottom:1px solid #ccd2dc;text-align:left}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:20px}article{background:white;padding:12px;border:1px solid #ccd2dc}h2{font-size:18px}svg{width:100%;height:auto}small{overflow-wrap:anywhere}.hold{color:#8c3a0c}</style>
<h1>Independent page-layout scale evidence</h1>
<p>Repeated peripheral text supplies a page-layout comparison independently of building dimensions and opening positions. Text roles are assigned in lexical order before fitting; every third term is held out. Missing, duplicated and unreadable terms are recorded before role assignment. No residual outliers are removed.</p>
<label>Source sheet pair <select id="pair"></select></label><p id="summary"></p>
<p class="hold">This is a layout diagnostic. Applying it to building artwork requires extrapolation and remains unverified. No physical scale, facade origin, world blocks or training labels are accepted. Independent figured dimensions and matching exterior corners are still required.</p>
<table><thead><tr><th>Plan source</th><th>Raw nominal span</th><th>Layout diagnostic span</th><th>Elevation frame</th><th>Remaining difference</th></tr></thead><tbody id="widths"></tbody></table>
<p>Blue points: fitted text anchors. Orange points: held-out anchors. Cyan outlines: original named enclosures, preserving holes. Red outlines: whole original near-ray paints. Original sheets and source geometry are unchanged.</p>
<main id="panels"></main><p><label><input id="all" type="checkbox"> Show fitted anchors as well as holdouts</label></p><table><thead><tr><th>Original shared text</th><th>Role</th><th>Residual in PDF points</th></tr></thead><tbody id="anchors"></tbody></table>
<script type="application/json" id="data">PAYLOAD</script><script>
const data=JSON.parse(document.getElementById('data').textContent),choice=document.getElementById('pair'),toggle=document.getElementById('all'),pairs=data.scale.pairs.filter(p=>p.status==='supported_furniture_layout_correspondence_only');
for(let i=0;i<pairs.length;i++){let o=document.createElement('option');o.value=i;o.textContent=pairs[i].subject_page_key[0].slice(0,12)+' → '+pairs[i].reference_page_key[0].slice(0,12);choice.append(o)}
function cells(body,values){let tr=document.createElement('tr');for(const value of values){let td=document.createElement('td');td.textContent=value;tr.append(td)}body.append(tr)}
function draw(){if(!pairs.length){document.getElementById('summary').textContent='No supported layout pair; additional source evidence is required.';return}let pair=pairs[Number(choice.value)],fit=pair.layout_fit;
document.getElementById('summary').textContent=`${fit.fit_anchor_count} fitted anchors; ${fit.holdout_anchor_count} holdouts. Apparent subject layout scale ${(fit.apparent_subject_layout_scale*100).toFixed(3)}%. Maximum holdout residual ${fit.holdout_max_residual_pdf_points.toFixed(4)} PDF points. Physical scale remains unverified.`;
let widths=document.getElementById('widths');widths.replaceChildren();for(const d of data.scale.diagnostics.filter(d=>d.pair_id===pair.id)){let extents=new Map(d.extents.map(e=>[e.id,e])),raw=data.alignment.frames.flatMap(r=>r.frame_reviews).flatMap(r=>r.plan_extents);for(const c of d.width_comparisons){let e=extents.get(c.plan_extent_id),source=raw.find(r=>r.id===e.source_extent_id),values=c.witnesses.map(w=>w.nominal_elevation_width_m),deltas=c.witnesses.map(w=>w.elevation_minus_plan_width_m);cells(widths,[source.source_kind.replaceAll('_',' '),(source.nominal_plan_position_interval_m[1]-source.nominal_plan_position_interval_m[0]).toFixed(3)+' m',c.nominal_plan_width_m.toFixed(3)+' m',Math.min(...values).toFixed(3)+' m',Math.max(...deltas.map(Math.abs)).toFixed(3)+' m · '+c.status.replaceAll('_',' ')])}}
let panels=document.getElementById('panels');panels.replaceChildren();for(const [role,key] of [['Subject',pair.subject_page_key],['Reference',pair.reference_page_key]]){let v=data.images[JSON.stringify(key)],m=v.source_native_to_pixels_matrix,article=document.createElement('article'),title=document.createElement('h2');title.textContent=role+' original sheet';article.append(title);let ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`0 0 ${v.size.join(' ')}`);let image=document.createElementNS(ns,'image');image.setAttribute('href',v.png);image.setAttribute('width',v.size[0]);image.setAttribute('height',v.size[1]);svg.append(image);
for(const extent of v.source_extents){let path=document.createElementNS(ns,'path');path.setAttribute('d',extent.d);path.setAttribute('class',extent.kind);path.setAttribute('fill','none');path.setAttribute('fill-rule','evenodd');path.setAttribute('stroke',extent.kind==='named_enclosure'?'#008d99':'#d63e45');path.setAttribute('stroke-width',1.5);svg.append(path)}
for(const row of fit.rows){let p=role==='Subject'?row.subject_origin:row.reference_origin,circle=document.createElementNS(ns,'circle');circle.setAttribute('cx',p[0]*m[0]+p[1]*m[2]+m[4]);circle.setAttribute('cy',p[0]*m[1]+p[1]*m[3]+m[5]);circle.setAttribute('r',3);circle.setAttribute('fill',row.role==='fit'?'#245bbb':'#d15c14');circle.setAttribute('class','anchor '+row.role);let title=document.createElementNS(ns,'title');title.textContent=row.text+' · '+row.role+' · '+row.residual_pdf_points.toFixed(4)+' PDF points';circle.append(title);svg.append(circle)}article.append(svg);let receipt=document.createElement('small');receipt.textContent=`Original PDF ${v.document_sha256} · page ${v.page}`;article.append(receipt);panels.append(article)}
let anchors=document.getElementById('anchors');anchors.replaceChildren();for(const row of fit.rows.filter(r=>toggle.checked||r.role==='holdout'))cells(anchors,[row.text,row.role,row.residual_pdf_points.toFixed(4)])}
choice.addEventListener('change',draw);toggle.addEventListener('change',draw);draw();
</script></html>'''.replace('PAYLOAD',embedded)
    if len(html.encode())>64000000:raise ValueError('Review output budget exceeded')
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(html)
    return {'output':str(output),'bytes':output.stat().st_size,'original_sheets':len(images),
            'supported_pairs':sum(p['status']=='supported_furniture_layout_correspondence_only' for p in scale['pairs'])}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--components',type=Path,required=True);parser.add_argument('--corpus',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(render(args.components,args.corpus,args.output)))
