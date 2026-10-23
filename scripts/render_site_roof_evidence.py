"""Standalone original-plan comparison with all compound-roof registrations."""
import argparse
import base64
import hashlib
import json
from pathlib import Path

import pymupdf

from voxel_mapper.drawing_page_tools import native_inverse
from voxel_mapper.generation_cycles import file_hash


def image_record(path,native_points):
    with pymupdf.open(path) as doc:
        p=doc[0];full=p.get_pixmap(matrix=pymupdf.Matrix(1600/max(p.rect.width,p.rect.height),1600/max(p.rect.width,p.rect.height)),alpha=False).tobytes('png')
        p.set_rotation(0);matrix=~native_inverse(p);xs=[v[0] for v in native_points];ys=[v[1] for v in native_points]
        box=pymupdf.Rect(min(xs)-40,min(ys)-40,max(xs)+40,max(ys)+40)*matrix;box &= p.rect
        pix=p.get_pixmap(matrix=pymupdf.Matrix(2,2),clip=box,alpha=False);png=pix.tobytes('png')
        return {'document_sha256':file_hash(path),'full_png':'data:image/png;base64,'+base64.b64encode(full).decode(),
            'full_png_sha256':hashlib.sha256(full).hexdigest(),'crop_png':'data:image/png;base64,'+base64.b64encode(png).decode(),
            'crop_png_sha256':hashlib.sha256(png).hexdigest(),'native_to_pixel_matrix':list(matrix*pymupdf.Matrix(2,2)),
            'pixel_origin':[pix.x,pix.y],'pixel_size':[pix.width,pix.height]}


def render(evidence,pyramid_evidence,adjoining_evidence,source_directory,roof_plan_pdf,output):
    evidence,pyramid_evidence,adjoining_evidence,source_directory,roof_plan_pdf,output=map(Path,(evidence,pyramid_evidence,adjoining_evidence,source_directory,roof_plan_pdf,output))
    raw=(evidence/'site-roof-evidence.json').read_bytes();r=json.loads(raw);pins=r['contract']['input_sha256']
    for p in (pyramid_evidence,adjoining_evidence,roof_plan_pdf):assert file_hash(p)==pins[p.name]
    pyramid=json.loads(pyramid_evidence.read_text());adjoining=json.loads(adjoining_evidence.read_text());sources=[]
    plans=[c for g in pyramid['plan_graphs'] for c in g['candidates']]
    for page in r['source_pages']:
        graph=page['graph'];registrations=[rg for rg in r['registrations'] if any(c['id']==rg['site_plan_candidate_id'] for c in graph['candidates'])]
        points=[p for rg in registrations for p in rg['predicted_site_corners_pdf_native']+rg['predicted_site_ridge_endpoints_pdf_native']]
        points += [p for l in graph['original_lines'] if any(l['id']==c['site_source_line_id'] for s in r['registration_support'] for c in s['supported_whole_ridge_matches']) for p in l['source_endpoints_pdf_native']]
        if not points:points=[[100,100],[500,500]]
        source=image_record(source_directory/(page['document_sha256']+'.pdf'),points)
        source.update(title=page['source_title'],candidate_ids=[c['id'] for c in graph['candidates']]);sources.append(source)
    arch_points=[p for c in plans for p in c['source_corners_pdf_native']]+[p for model in adjoining['plan_ridges'] for p in model['original_ridge']['source_endpoints_pdf_native']]
    packed={'raw_base64':base64.b64encode(raw).decode(),'sources':sources,'architecture':image_record(roof_plan_pdf,arch_points),
        'plans':plans,'plan_ridges':adjoining['plan_ridges']}
    payload=json.dumps(packed).replace('<','\\u003c')
    html='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Original site roof correspondence</title>
<style>body{font:16px system-ui;background:#eff4f6;color:#1c313c;max-width:1480px;margin:auto;padding:24px}h1{font-size:28px}.note{padding:14px;background:#fff0d2}.controls{display:flex;gap:20px;flex-wrap:wrap;margin:18px 0}select,button{font:inherit;padding:8px;max-width:100%}.panels{display:grid;grid-template-columns:1.2fr 1fr;gap:20px}.image{position:relative;background:white}.image img{display:block;width:100%}.image svg{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}pre{background:white;padding:15px;white-space:pre-wrap;overflow-wrap:anywhere}details img{width:100%}@media(max-width:900px){.panels{grid-template-columns:1fr}}</style>
<h1>Architectural roof ↔ original site plan</h1><p id="summary"></p><p class="note">Matching corners and an adjoining ridge provide conditional drawing correspondence. Both mirrored registrations remain available. A nearby Station label supplies source context; it does not assign a physical roof role. Geographic registration, datum, section cut direction and wall closure remain unresolved.</p>
<button id="download">Download exact evidence JSON</button><div class="controls"><label>Original site plan<br><select id="page"></select></label><label>Corner correspondence<br><select id="registration"></select></label><label>Conditional section camera<br><select id="camera"></select></label></div><label><input id="show" type="checkbox" checked> Show original vectors (green), projected architectural roof (orange) and conditional viewer arrow (blue)</label><p id="status"></p>
<div class="panels"><section><h2>Original site plan</h2><div class="image"><img id="siteCrop" alt="Original site-plan detail"><svg id="siteOverlay"></svg></div></section><section><h2>Original architectural roof plan</h2><div class="image"><img id="archCrop" alt="Original architectural roof detail"><svg id="archOverlay"></svg></div></section></div><pre id="detail"></pre><details><summary>Original full site sheet</summary><img id="siteFull" alt="Original full site sheet"></details><details><summary>Original full roof sheet</summary><img id="archFull" alt="Original full roof sheet"></details>
<script type="application/json" id="data">PAYLOAD</script><script>
const packed=JSON.parse(document.getElementById('data').textContent),bytes=Uint8Array.from(atob(packed.raw_base64),c=>c.charCodeAt(0)),report=JSON.parse(new TextDecoder().decode(bytes));const el=id=>document.getElementById(id);
function options(id,rows){el(id).replaceChildren();for(const [value,text] of rows){const o=document.createElement('option');o.value=value;o.textContent=text;el(id).append(o)}}
function siteCurrent(){const source=packed.sources[+el('page').value],page=report.source_pages.find(p=>p.document_sha256===source?.document_sha256),registrations=report.registrations.filter(r=>source?.candidate_ids.includes(r.site_plan_candidate_id)),registration=registrations[+el('registration').value],support=report.registration_support.find(s=>s.registration_id===registration?.id),target=page?.graph.candidates.find(c=>c.id===registration?.site_plan_candidate_id),plan=packed.plans.find(c=>c.id===registration?.architectural_plan_candidate_id),ridge=packed.plan_ridges.find(r=>r.pyramid_candidate_id===plan?.id),cameras=report.section_site_camera_candidates.filter(c=>c.registration_id===registration?.id),camera=cameras[+el('camera').value];return {source,page,registrations,registration,support,target,plan,ridge,cameras,camera}}
function pageChanged(){const {registrations}=siteCurrent();options('registration',registrations.map((r,i)=>[i,`${i+1}: ${r.reflection_candidate?'reflected':'rotated'}`]));registrationChanged()}
function registrationChanged(){const {cameras}=siteCurrent();options('camera',cameras.map((c,i)=>[i,`${i+1}: section ${c.source_group_id.slice(0,10)}…`]));el('camera').disabled=!cameras.length;draw()}
function pixel(image,p){const [a,b,c,d,e,f]=image.native_to_pixel_matrix;return [a*p[0]+c*p[1]+e-image.pixel_origin[0],b*p[0]+d*p[1]+f-image.pixel_origin[1]]}
function segment(svg,image,a,b,color,kind,id){const p=pixel(image,a),q=pixel(image,b),l=document.createElementNS('http://www.w3.org/2000/svg','line');for(const [key,v] of Object.entries({x1:p[0],y1:p[1],x2:q[0],y2:q[1],stroke:color,'stroke-width':kind==='projected'?2:2.5})){l.setAttribute(key,v)}if(kind==='projected')l.setAttribute('stroke-dasharray','8 5');l.setAttribute('class',kind);l.dataset.identity=id;svg.append(l)}
function draw(){const s=siteCurrent(),{source,page,registration:r,support,target,plan,ridge,camera}=s;el('siteFull').src=source?.full_png||'';el('archFull').src=packed.architecture.full_png;el('siteCrop').src=source?.crop_png||'';el('archCrop').src=packed.architecture.crop_png;
for(const [id,img] of [['siteOverlay',source],['archOverlay',packed.architecture]]){el(id).replaceChildren();el(id).style.display=el('show').checked?'block':'none';if(img)el(id).setAttribute('viewBox',`0 0 ${img.pixel_size[0]} ${img.pixel_size[1]}`)}
if(!r){el('status').textContent='No complete original source roof candidate in the checked label neighbourhood.';el('detail').textContent=JSON.stringify({world_export_authorized:false},null,2);return}
const ids=new Set([...target.source_perimeter_ids_per_edge.flat(),...target.source_spoke_ids_per_corner.flat(),...support.supported_whole_ridge_matches.map(c=>c.site_source_line_id)]);for(const line of page.graph.original_lines){if(ids.has(line.id))segment(el('siteOverlay'),source,...line.source_endpoints_pdf_native,'#15874e','original-site',line.id)}
const corners=r.predicted_site_corners_pdf_native,A=r.original_site_apex_anchor_pdf_native;for(let i=0;i<4;i++){segment(el('siteOverlay'),source,corners[i],corners[(i+1)%4],'#e47d12','projected','edge-'+i);segment(el('siteOverlay'),source,A,corners[i],'#e47d12','projected','spoke-'+i)}segment(el('siteOverlay'),source,...r.predicted_site_ridge_endpoints_pdf_native,'#e47d12','projected','ridge');
const ac=plan.source_corners_pdf_native,aa=plan.source_apex_pdf_native;for(let i=0;i<4;i++){segment(el('archOverlay'),packed.architecture,ac[i],ac[(i+1)%4],'#15874e','original-architecture','edge-'+i);segment(el('archOverlay'),packed.architecture,aa,ac[i],'#15874e','original-architecture','spoke-'+i)}segment(el('archOverlay'),packed.architecture,...ridge.original_ridge.source_endpoints_pdf_native,'#15874e','original-architecture','ridge');
if(camera){const n=camera.candidate_viewer_direction_site_native_xy,end=[A[0]+n[0]*50,A[1]+n[1]*50];segment(el('siteOverlay'),source,A,end,'#1765cb','camera','viewer');for(const sign of [-1,1])segment(el('siteOverlay'),source,end,[end[0]-n[0]*7+sign*n[1]*4,end[1]-n[1]*7-sign*n[0]*4],'#1765cb','camera','arrow-'+sign)}
el('status').textContent=`${support.status}; ${r.reflection_candidate?'reflected':'rotated'} hypothesis; maximum corner error ${(r.maximum_corner_residual_nominal_m*100).toFixed(2)} cm. Source coordinates and source scales unchanged.`;const {ridge_comparisons,...compact}=r;el('detail').textContent=JSON.stringify({registration:compact,support,conditional_section_camera:camera||null,nearby_label_assigns_physical_role:false,world_export_authorized:false},null,2)}
options('page',packed.sources.map((s,i)=>[i,s.title]));el('summary').textContent=`${report.counts.original_site_roof_candidates} original site roof candidate; ${report.counts.registrations} registrations retained; ${report.counts.supported_registrations} supported compound correspondences; ${report.counts.section_site_camera_candidates} conditional section-camera combinations.`;
el('page').onchange=pageChanged;el('registration').onchange=registrationChanged;el('camera').onchange=draw;el('show').onchange=draw;el('download').onclick=()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([bytes],{type:'application/json'}));a.download='site-roof-evidence.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};pageChanged();document.body.dataset.ready='true';
</script></html>'''.replace('PAYLOAD',payload)
    output.write_text(html);return {'output':str(output),'review_sha256':file_hash(evidence/'site-roof-evidence.json'),'original_full_sheets':len(sources)+1,'original_crops':len(sources)+1}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('evidence','pyramid-evidence','adjoining-evidence','source-directory','roof-plan-pdf','output'):p.add_argument('--'+name,type=Path,required=True)
    print(json.dumps(render(**vars(p.parse_args()))))
