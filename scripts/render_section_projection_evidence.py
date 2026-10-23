"""Review every camera hypothesis against original section and plan coordinates."""
import argparse
import base64
import hashlib
import json
from pathlib import Path

import pymupdf

from voxel_mapper.generation_cycles import file_hash


def render(evidence,section_evidence,pyramid_evidence,source_directory,output):
    evidence,section_evidence,pyramid_evidence,source_directory,output=map(Path,(evidence,section_evidence,pyramid_evidence,source_directory,output))
    raw=(evidence/'section-projection-evidence.json').read_bytes();report=json.loads(raw)
    assert file_hash(section_evidence)==report['contract']['source_section_sha256']
    assert file_hash(pyramid_evidence)==report['contract']['source_pyramid_sha256']
    section=json.loads(section_evidence.read_text());pyramid=json.loads(pyramid_evidence.read_text());sources=[]
    for record in section['pages']:
        sha=record['document_sha256'];path=source_directory/(sha+'.pdf');assert file_hash(path)==sha
        with pymupdf.open(path) as doc:
            page=doc[0];scale=1800/max(page.rect.width,page.rect.height)
            full=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False).tobytes('png');crops=[]
            for leader in record['leaders']:
                word=next(w for w in record['numeric_words'] if w['id']==leader['word_id'])
                clip=pymupdf.Rect(word['source_bbox_pdf_unrotated'])+(-180,-30,180,260);clip &= page.rect
                pix=page.get_pixmap(matrix=pymupdf.Matrix(2,2),clip=clip,alpha=False);png=pix.tobytes('png')
                crops.append({'source_leader_id':leader['id'],'png':'data:image/png;base64,'+base64.b64encode(png).decode(),
                    'png_sha256':hashlib.sha256(png).hexdigest(),'source_pixel_origin':[pix.x,pix.y],'source_pixel_size':[pix.width,pix.height]})
        sources.append({'document_sha256':sha,'title':record['source_title'],'full_png':'data:image/png;base64,'+base64.b64encode(full).decode(),
            'full_png_sha256':hashlib.sha256(full).hexdigest(),'crops':crops})
    payload={'raw_base64':base64.b64encode(raw).decode(),'sources':sources,
             'plans':[{**c,'nominal_metres_per_pdf_point':g['nominal_metres_per_pdf_point']} for g in pyramid['plan_graphs'] for c in g['candidates']]}
    data=json.dumps(payload).replace('<','\\u003c')
    html='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Section projection candidates</title>
<style>body{font:16px system-ui;max-width:1450px;margin:auto;padding:22px;background:#eff4f6;color:#1c313c}h1{font-size:28px}.note{padding:14px;background:#fff0d2}select,button{font:inherit;padding:8px;max-width:95%}.controls{display:flex;gap:15px;flex-wrap:wrap;margin:18px 0}.panels{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:20px}#imageBox{position:relative;background:white}#crop{display:block;width:100%}#overlay{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}#plan{width:100%;background:white;border:1px solid #b5c5cd}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:14px}#full{width:100%}summary{cursor:pointer;padding:12px}@media(max-width:900px){.panels{grid-template-columns:1fr}}</style>
<h1>Section-to-plan projection candidates</h1><p id="summary"></p><p class="note">All supported orientations remain candidates. The shared-cap face, physical roof correspondence, section bearing and datum remain unresolved. A candidate camera arrow is a model hypothesis in the plan's native axes. Wall closure remains unauthorized.</p>
<button id="download">Download exact evidence JSON</button><div class="controls"><label>Original section<br><select id="page"></select></label><label>Source spoke group<br><select id="group"></select></label><label>Camera hypothesis<br><select id="pose"></select></label></div>
<label><input id="show" type="checkbox" checked> Show unchanged original section strokes (cyan) and candidate projections (dashed orange)</label><p id="status"></p><div class="panels"><section><h2>Original section</h2><div id="imageBox"><img id="crop" alt="Original section detail"><svg id="overlay"></svg></div></section><section><h2>Original roof plan</h2><svg id="plan" viewBox="0 0 500 500"></svg><p>Red: original shared cap. Purple: candidate visible perimeter. Blue arrow: candidate viewing direction.</p></section></div><pre id="detail"></pre><details><summary>Original full section sheet</summary><img id="full" alt="Original full section sheet"></details>
<script type="application/json" id="data">PAYLOAD</script><script>
const packed=JSON.parse(document.getElementById('data').textContent),bytes=Uint8Array.from(atob(packed.raw_base64),c=>c.charCodeAt(0)),report=JSON.parse(new TextDecoder().decode(bytes));const el=id=>document.getElementById(id);
function options(id,rows){el(id).replaceChildren();for(const [value,title] of rows){const o=document.createElement('option');o.value=value;o.textContent=title;el(id).append(o)}}
function groups(){return report.source_groups.filter(g=>g.source_document_sha256===packed.sources[+el('page').value].document_sha256)}
function current(){const source=packed.sources[+el('page').value],group=groups()[+el('group').value],poses=report.projection_candidates.filter(p=>p.source_group_id===group?.id),pose=poses[+el('pose').value],plan=packed.plans.find(p=>p.id===pose?.original_plan_candidate_id);return {source,group,poses,pose,plan}}
function pageChanged(){options('group',groups().map((g,i)=>[i,`${i+1}: ${g.status}`]));groupChanged()}
function groupChanged(){const {poses}=current();options('pose',poses.map((p,i)=>[i,`${i+1}: shared cap ${p.shared_cap_candidate_visible?'visible':'hidden'}`]));draw()}
function line(svg,a,b,color,css,id){const node=document.createElementNS('http://www.w3.org/2000/svg','line');for(const [k,v] of Object.entries({x1:a[0],y1:a[1],x2:b[0],y2:b[1],stroke:color,'stroke-width':css==='candidate'?2:2.5})){node.setAttribute(k,v)}if(css==='candidate')node.setAttribute('stroke-dasharray','7 5');node.setAttribute('class',css);if(id)node.dataset.identity=id;svg.append(node);return node}
function draw(){const {source,group,pose,plan}=current();el('full').src=source.full_png;const overlay=el('overlay'),diagram=el('plan');overlay.replaceChildren();diagram.replaceChildren();overlay.style.display=el('show').checked?'block':'none';
if(!group||!pose){const crop=source.crops.find(c=>c.source_leader_id===group?.source_leader_id);el('crop').src=crop?.png||source.full_png;el('status').textContent=group?'Original source base or spoke group remains held; no camera generated.':'No requested numeric/spoke group in this source sheet.';el('detail').textContent=JSON.stringify({source_group:group||null,wall_closure_authorized:false},null,2);return}
const crop=source.crops.find(c=>c.source_leader_id===group.source_leader_id);el('crop').src=crop.png;overlay.setAttribute('viewBox',`0 0 ${crop.source_pixel_size[0]} ${crop.source_pixel_size[1]}`);const sourcePoint=p=>p.map((v,i)=>v*2-crop.source_pixel_origin[i]);const apex=group.source_apex_pdf_unrotated,base=group.source_roof_spokes.map(s=>s.source_base_vertex_pdf_unrotated);line(overlay,sourcePoint(base[0]),sourcePoint(base[2]),'#009f9a','source','whole-base');for(const [i,p]of base.entries())line(overlay,sourcePoint(apex),sourcePoint(p),'#009f9a','source','spoke-'+i);
for(const ci of pose.source_left_middle_right_plan_corner_indices)line(overlay,sourcePoint(apex),sourcePoint([pose.projected_original_plan_corner_x_pdf_points[ci],base[0][1]]),'#e88b18','candidate','projected-'+ci);
const corners=plan.source_corners_pdf_native,A=plan.source_apex_pdf_native;const minX=Math.min(...corners.map(p=>p[0]))-110,maxX=Math.max(...corners.map(p=>p[0]))+110,minY=Math.min(...corners.map(p=>p[1]))-110,maxY=Math.max(...corners.map(p=>p[1]))+110;diagram.setAttribute('viewBox',`${minX} ${minY} ${maxX-minX} ${maxY-minY}`);const planPoint=p=>[p[0],maxY+minY-p[1]];
for(let i=0;i<4;i++){const shared=i===pose.shared_cap_original_edge_index;line(diagram,planPoint(corners[i]),planPoint(corners[(i+1)%4]),shared?'#d6453a':pose.candidate_visible_original_edge_indices.includes(i)?'#8a42ba':'#9aa9b2','native-perimeter','edge-'+i);line(diagram,planPoint(A),planPoint(corners[i]),'#647d8e','native-spoke','corner-'+i)}
const n=pose.candidate_viewer_direction_native_xy,end=[A[0]+n[0]*100,A[1]+n[1]*100];line(diagram,planPoint(A),planPoint(end),'#1765cb','camera','viewer');const e=planPoint(end),a=planPoint(A),v=[e[0]-a[0],e[1]-a[1]],size=Math.hypot(...v),u=v.map(x=>x/size);for(const sign of [-1,1])line(diagram,e,[e[0]-u[0]*12+sign*u[1]*6,e[1]-u[1]*12-sign*u[0]*6],'#1765cb','camera');
const gate=report.face_ambiguity.find(a=>a.source_group_id===group.id);el('status').textContent=`${pose.status}; ${gate.supported_projection_count} orientations retained; shared cap ${pose.shared_cap_candidate_visible?'visible':'hidden'} in this hypothesis.`;el('detail').textContent=JSON.stringify({source_group_id:group.id,projection:pose,face_ambiguity:gate},null,2)}
el('summary').textContent=`${report.counts.supported_source_groups} supported source groups; ${report.counts.supported_projection_candidates} camera candidates; ${report.counts.shared_cap_visible_candidates} shared-cap-visible and ${report.counts.shared_cap_hidden_candidates} shared-cap-hidden candidates.`;
options('page',packed.sources.map((s,i)=>[i,s.title]));el('page').onchange=pageChanged;el('group').onchange=groupChanged;el('pose').onchange=draw;el('show').onchange=draw;el('download').onclick=()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([bytes],{type:'application/json'}));a.download='section-projection-evidence.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};pageChanged();document.body.dataset.ready='true';
</script></html>'''.replace('PAYLOAD',data)
    output.write_text(html);return {'output':str(output),'source_full_sheets':len(sources),'source_detail_crops':sum(len(s['crops']) for s in sources),'review_sha256':hashlib.sha256(raw).hexdigest()}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('evidence','section-evidence','pyramid-evidence','source-directory','output'):p.add_argument('--'+name,type=Path,required=True)
    print(json.dumps(render(**vars(p.parse_args()))))
