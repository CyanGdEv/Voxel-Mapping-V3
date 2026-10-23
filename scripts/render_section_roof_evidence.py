"""Standalone original section crops and exact-source leader/roof overlays."""
import argparse
import base64
import hashlib
import json
from pathlib import Path

import pymupdf

from voxel_mapper.generation_cycles import file_hash


def render(evidence,source_directory,fascia_evidence,output):
    evidence,source_directory,fascia_evidence,output=map(Path,(evidence,source_directory,fascia_evidence,output))
    raw=(evidence/'section-roof-evidence.json').read_bytes();report=json.loads(raw)
    assert file_hash(fascia_evidence)==report['contract']['source_fascia_sha256']
    parent=json.loads(fascia_evidence.read_text());sources=[]
    for record in report['pages']:
        sha=record['document_sha256'];path=source_directory/(sha+'.pdf');assert file_hash(path)==sha
        with pymupdf.open(path) as doc:
            page=doc[0];scale=1800/max(page.rect.width,page.rect.height)
            png=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False).tobytes('png')
            crops=[]
            for word in record['numeric_words']:
                box=pymupdf.Rect(word['source_bbox_pdf_unrotated'])+(-180,-30,180,260);box &= page.rect
                pix=page.get_pixmap(matrix=pymupdf.Matrix(2,2),clip=box,alpha=False);data=pix.tobytes('png')
                crops.append({'word_id':word['id'],'png':'data:image/png;base64,'+base64.b64encode(data).decode(),
                    'png_sha256':hashlib.sha256(data).hexdigest(),'source_pixel_origin':[pix.x,pix.y],
                    'source_pixel_size':[pix.width,pix.height],'pixels_per_pdf_point':2})
        sources.append({'document_sha256':sha,'full_png':'data:image/png;base64,'+base64.b64encode(png).decode(),
                        'full_png_sha256':hashlib.sha256(png).hexdigest(),'crops':crops})
    models=[{k:m[k] for k in ('id','source_level_label','source_level_value_m_candidate','mesh','source_ink_threshold','source_gradient_contrast','source_pair_id')} for m in parent['models']]
    payload={'raw_base64':base64.b64encode(raw).decode(),'sources':sources,'models':models}
    data=json.dumps(payload).replace('<','\\u003c')
    html='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Section roof source evidence</title>
<style>body{font:16px system-ui;max-width:1450px;padding:20px;margin:auto;background:#edf3f5;color:#1d303a}h1{font-size:28px}.note{padding:14px;background:#fff1d2}button,select{font:inherit;padding:7px;max-width:95%}.controls{display:flex;gap:14px;flex-wrap:wrap;margin:16px 0}label{display:block}#canvas{position:relative;max-width:1000px;background:white}#crop{width:100%;display:block}#overlay{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}#full{width:100%;background:white}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:14px}summary{cursor:pointer;padding:12px}#status{font-weight:600}</style>
<h1>Original section roof leaders</h1><p id="summary"></p>
<p class="note">Height agreement assumes a common datum and the same physical roof. Section bearing, projection and the shared-cap face remain unresolved. The original source strokes are retained whole. No wall closure or world geometry is authorized.</p>
<button id="download">Download exact evidence JSON</button><div class="controls"><label>Source sheet<br><select id="page"></select></label><label>Numeric leader<br><select id="leader"></select></label><label>Original roof outline<br><select id="pair"></select></label><label>Existing roof model<br><select id="model"></select></label></div>
<label><input id="show" type="checkbox" checked> Show original stroke overlay: blue leader, cyan arrow, green closed outline, orange held outline</label><p id="status"></p>
<div id="canvas"><img id="crop" alt="Original section detail"><svg id="overlay"></svg></div><pre id="detail"></pre><details><summary>Original full sheet</summary><img id="full" alt="Original full section sheet"></details>
<script type="application/json" id="data">PAYLOAD</script><script>
const packed=JSON.parse(document.getElementById('data').textContent),bytes=Uint8Array.from(atob(packed.raw_base64),c=>c.charCodeAt(0)),report=JSON.parse(new TextDecoder().decode(bytes));
const el=id=>document.getElementById(id);const options=(id,rows)=>{el(id).replaceChildren();for(const [value,label] of rows){const o=document.createElement('option');o.value=value;o.textContent=label;el(id).append(o)}};
el('summary').textContent=`${report.counts.numeric_words} original numeric labels; ${report.counts.closed_section_roof_pairs} closed roof outline candidates; ${report.counts.held_section_roof_pairs} held alternatives; ${report.counts.agreeing_height_comparisons}/${report.counts.height_comparisons} conditional height comparisons agree.`;
options('page',report.pages.map((p,i)=>[i,p.source_title]));options('model',packed.models.map((m,i)=>[i,`${m.source_level_label}: ink ${m.source_ink_threshold}, contrast ${m.source_gradient_contrast}, ${m.id.slice(0,8)}`]));
function current(){const p=report.pages[+el('page').value],l=p.leaders[+el('leader').value],r=l?.roof_pairs[+el('pair').value],m=packed.models[+el('model').value],s=packed.sources[+el('page').value];return {p,l,r,m,s}}
function pageChanged(){const p=report.pages[+el('page').value];options('leader',p.leaders.map((l,i)=>[i,`${p.numeric_words.find(w=>w.id===l.word_id).text} · ${i+1}`]));leaderChanged()}
function leaderChanged(){const {l}=current();options('pair',(l?.roof_pairs||[]).map((p,i)=>[i,`${i+1}: ${p.status}`]));draw()}
function draw(){const {p,l,r,m,s}=current();el('full').src=s.full_png;const overlay=el('overlay');overlay.replaceChildren();overlay.style.display=el('show').checked?'block':'none';
if(!l){el('crop').style.display='none';el('status').textContent='No exact requested numeric label or leader in this source sheet.';el('detail').textContent=JSON.stringify({source:p.document_sha256,matching_labels:p.numeric_words.length,closure_authorized:false},null,2);return}el('crop').style.display='block';
const crop=s.crops.find(c=>c.word_id===l.word_id);el('crop').src=crop.png;overlay.setAttribute('viewBox',`0 0 ${crop.source_pixel_size[0]} ${crop.source_pixel_size[1]}`);
const ids=[[l.leader_source_id,'#1565db'],...l.source_arrow_head_pairs.flatMap(pair=>pair.map(id=>[id,'#00a8b0'])),...(r?.slope_source_ids||[]).map(id=>[id,r.status==='closed_original_section_triangle_candidate'?'#058554':'#df7a08']),...(r?.cap_source_ids||[]).map(id=>[id,'#058554'])];
for(const [id,color] of ids){const line=p.source_lines.find(l=>l.id===id);const a=line.source_endpoints_pdf_unrotated.map(q=>q.map((v,i)=>v*crop.pixels_per_pdf_point-crop.source_pixel_origin[i]));const node=document.createElementNS('http://www.w3.org/2000/svg','line');node.dataset.sourceId=id;for(const [key,value] of Object.entries({x1:a[0][0],y1:a[0][1],x2:a[1][0],y2:a[1][1],stroke:color,'stroke-width':2.5})){node.setAttribute(key,value)}overlay.append(node)}
const check=report.height_comparisons.find(c=>c.section_roof_pair_id===r?.id&&c.roof_model_id===m.id);el('status').textContent=check?check.status:r?.status||'No roof outline candidate';
el('detail').textContent=JSON.stringify({word:p.numeric_words.find(w=>w.id===l.word_id),original_outline:r,comparison:check||null,shared_cap_closure_authorized:false},null,2)}
el('page').onchange=pageChanged;el('leader').onchange=leaderChanged;el('pair').onchange=draw;el('model').onchange=draw;el('show').onchange=draw;
el('download').onclick=()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([bytes],{type:'application/json'}));a.download='section-roof-evidence.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};pageChanged();document.body.dataset.ready='true';
</script></html>'''.replace('PAYLOAD',data)
    output.write_text(html);return {'output':str(output),'full_sheets':len(sources),'detail_crops':sum(len(s['crops']) for s in sources),'evidence_sha256':hashlib.sha256(raw).hexdigest()}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('evidence','source-directory','fascia-evidence','output'):p.add_argument('--'+name,type=Path,required=True)
    print(json.dumps(render(**vars(p.parse_args()))))
