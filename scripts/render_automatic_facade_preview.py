"""Offline interactive source comparison and orbitable unplaced facade context."""
import argparse
import base64
import json
from pathlib import Path

from voxel_mapper.generation_cycles import file_hash
from voxel_mapper.reconstruction_evidence_queue import digest


def render(preview, components, views, output):
    preview,components,views,output=map(Path,(preview,components,views,output))
    evidence=json.loads((preview/'facade-preview.json').read_text());contract=evidence['contract']
    if file_hash(components/'component-report.json')!=contract['component_report_sha256'] or file_hash(views/'view-report.json')!=contract['view_report_sha256']:
        raise ValueError('Matching source preview reports required')
    report=json.loads((components/'component-report.json').read_text());vr=json.loads((views/'view-report.json').read_text())
    for root,pins in ((components,report['output_sha256']),(views,vr['output_sha256'])):
        for name,pin in pins.items():
            if file_hash(root/name)!=pin:raise ValueError('Original preview review artifact changed')
    payload={'evidence':evidence,'crops':{},'views':{},'choices':[]}
    for receipt in evidence['source_crop_receipts']:
        path=preview/receipt['file']
        if file_hash(path)!=receipt['png_sha256']:raise ValueError('Original preview crop changed')
        payload['crops'][receipt['id']]={**receipt,'png':'data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode()}
    levels=json.loads((components/report['elevation_level_context']['file']).read_text())
    payload['level_labels']={}
    for page in levels['pages']:
        for record in page['level_review']['records']:
            label=record.get('label');key=record.get('view_key_candidate')
            if label and key and key[0]=='automatic_view':payload['level_labels'].setdefault(key[1],[]).append(label['text'])
    source=json.loads((views/'view-candidates.json').read_text())
    source_views={v['id']:v for p in source['pages'] for v in p['views']}
    inventories={r['view_id']:json.loads((components/r['file']).read_text()) for r in report['results']}
    grouped={}
    for row in evidence['previews']:grouped.setdefault(digest(row['mesh']),[]).append(row)
    for rows in grouped.values():payload['choices'].append({'preview':rows[0],'source_alternative_ids':[r['id'] for r in rows]})
    for row in evidence['previews']:
        key=row['view_id']
        if key in payload['views']:continue
        v=source_views[key];receipt=json.loads((views/v['render']['receipt']).read_text());inv=inventories[key]
        if inv['raster_coordinate_receipt']['quarter_turns_counterclockwise']!=0:raise ValueError('Unrotated source preview comparison required')
        payload['views'][key]={'size':receipt['size_pixels'],'png_sha256':v['render']['png_sha256'],
            'png':'data:image/png;base64,'+base64.b64encode((views/v['render']['png']).read_bytes()).decode()}
    html='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Unplaced facade preview</title>
<style>body{font:16px system-ui;margin:24px;background:#f4f6f9;color:#17212b}h1{margin-bottom:8px}p{max-width:1150px;line-height:1.5}.notice{background:#fff3d5;padding:14px;border-left:4px solid #b97700}.controls{display:flex;gap:24px;flex-wrap:wrap;align-items:center}select{font:inherit;padding:8px}table{width:100%;border-collapse:collapse;margin:16px 0}th,td{padding:8px;text-align:left;border-bottom:1px solid #cbd3dd}.panels{display:grid;grid-template-columns:1fr 1fr;gap:20px}article{background:white;padding:16px;border:1px solid #cbd3dd}article h2{font-size:18px}svg{width:100%;height:auto}#detail{max-height:520px}#context{height:340px}.wide{margin-top:20px;background:white;padding:16px}.small{font-size:14px;color:#485969}@media(max-width:800px){.panels{grid-template-columns:1fr}}</style>
<h1>Façade · unplaced source preview</h1><p id="summary"></p>
<p class="notice">Drawing hypotheses only. The grey plane is an observed raster rectangle, with no verified exterior-wall boundary, thickness or roof. The red opening outline keeps its original jamb bounds; its bottom stays unresolved. Gold marks a separately detected base band. Physical measurements, construction state and park placement remain unverified.</p>
<div class="controls"><label>Opening alternative <select id="choice"></select></label><label>View angle <input id="yaw" type="range" min="-65" max="65" value="25"></label><label><input type="checkbox" id="bands" checked> Show source base band</label></div>
<p id="measurements"></p><div class="panels"><article><h2>3D drawing context · zero thickness</h2><svg id="context" viewBox="0 0 760 340" role="img" aria-label="Orbitable unplaced facade context"></svg><p class="small">x runs from the original parent’s left edge; z is relative to printed Shop Level. Drag the view-angle control to rotate the display plane. No aperture is carved.</p></article><article><h2>Original PDF detail · automatic crop</h2><svg id="detail" role="img" aria-label="Original opening source detail"></svg><p class="small">Red dashes retain the raw candidate bottom through the ground shading. Gold shows every qualifying band at both dark thresholds. Source base-band identity is unverified.</p></article></div>
<section class="wide"><h2>Original elevation and level labels</h2><p id="level-context"></p><p>A printed level leader alone does not establish a physical threshold. The separate base band retains its original drawing position.</p><svg id="source" role="img" aria-label="Original elevation with candidate bounds"></svg></section>
<h2>Target annotations · check fixed fit only</h2><table><thead><tr><th>Reference</th><th>Result</th><th>Residual</th><th>Fit use</th></tr></thead><tbody id="markers"></tbody></table><p>All Shop references were excluded before fitting the non-Shop layout. These checks never refit that model. Agreement at annotations does not verify the building’s physical scale; the wall corners still lie outside the non-target control hull.</p>
<script id="data" type="application/json">PAYLOAD</script><script>
const data=JSON.parse(document.getElementById('data').textContent),ns='http://www.w3.org/2000/svg',choice=document.getElementById('choice'),yaw=document.getElementById('yaw'),bands=document.getElementById('bands');
function el(tag,attrs,parent){let e=document.createElementNS(ns,tag);for(let [k,v]of Object.entries(attrs))e.setAttribute(k,v);parent.append(e);return e}
function line(svg,points,color,cls,dash=false,width=2){let e=el('polyline',{points:points.map(p=>p.join(',')).join(' '),fill:'none',stroke:color,'stroke-width':width,class:cls},svg);if(dash)e.setAttribute('stroke-dasharray','6 4');return e}
function image(svg,png,size){el('image',{href:png,width:size[0],height:size[1]},svg)}
for(let i=0;i<data.choices.length;i++){let o=document.createElement('option');o.value=i;o.textContent=`${i+1} of ${data.choices.length} · ${data.choices[i].source_alternative_ids.length} source witness links`;choice.append(o)}
let count=data.evidence.counts;document.getElementById('summary').textContent=`${count.unique_meshes} distinct opening outlines from ${count.source_linked_alternatives} source witness combinations, in overlapping source families. ${count.positions_compatible} of ${count.position_checks} orientation/position checks agree. No world blocks or accepted physical components.`;
for(let row of data.evidence.target_marker_checks){let tr=document.createElement('tr');for(let value of [row.key.join(' / '),row.status==='fixed_non_target_layout_agrees_at_target_annotation'?'Agrees with fixed fit':row.status==='whole_visible_unique_target_references_required'?'Held: source visibility/uniqueness':'Mismatch',row.residual_pdf_points===undefined?'Withheld':row.residual_pdf_points.toFixed(4)+' PDF points','Excluded; check only']){let td=document.createElement('td');td.textContent=value;tr.append(td)}document.getElementById('markers').append(tr)}
function draw(){let item=data.choices[Number(choice.value)];if(!item)return;let row=item.preview,mesh=row.mesh,receipt=data.crops[row.source_crop_receipt_id],source=data.views[row.view_id],context=document.getElementById('context'),detail=document.getElementById('detail'),full=document.getElementById('source');context.replaceChildren();detail.replaceChildren();full.replaceChildren();
let width=mesh.context_vertices[1][0],angle=Number(yaw.value)*Math.PI/180;function project(p){let x=p[0]-width/2,z=p[2];return [380+x*Math.cos(angle)*40,220-z*40+x*Math.sin(angle)*7]}
let vertices=mesh.context_vertices.map(project);el('polygon',{points:vertices.map(p=>p.join(',')).join(' '),fill:'#dce4ed',stroke:'#8090a3','stroke-width':1,class:'context-plane'},context);let opening=mesh.opening_outline_vertices.map(project);line(context,[opening[3],opening[2],opening[1]],'#ba3343','opening-sides');line(context,[opening[0],opening[3]],'#ba3343','opening-side');line(context,[opening[0],opening[1]],'#ba3343','unresolved-bottom',true);line(context,[project([0,0,0]),project([width,0,0])],'#2365b6','printed-level',true,1);
let interval=row.base_band_relative_to_printed_level_nominal_m;if(bands.checked&&interval){for(let z of interval)line(context,[project([mesh.opening_outline_vertices[0][0],0,z]),project([mesh.opening_outline_vertices[1][0],0,z])],'#b47a00','candidate-base-band',false,3)}
detail.setAttribute('viewBox',`0 0 ${receipt.size_pixels.join(' ')}`);image(detail,receipt.png,receipt.size_pixels);let b=row.bottom_review.source_opening_bounds_display,m=receipt.pixel_edge_to_display_matrix;function cropPoint(p){return [(p[0]-m[4])/m[0],(p[1]-m[5])/m[3]]};let rect=[[b[0],b[3]],[b[2],b[3]],[b[2],b[1]],[b[0],b[1]]].map(cropPoint);line(detail,[rect[0],rect[3],rect[2],rect[1]],'#ba3343','original-opening');line(detail,[rect[0],rect[1]],'#ba3343','raw-bottom',true);if(bands.checked)for(let band of row.bottom_review.bands){let [lo,start,hi,end]=row.bottom_review.search_pixel_interval,y=band.row_interval_pixels;el('rect',{x:lo,y:y[0],width:hi-lo,height:y[1]-y[0],fill:'#e5ad20',opacity:.6,class:'source-base-band'},detail)}
full.setAttribute('viewBox',`0 0 ${source.size.join(' ')}`);image(full,source.png,source.size);let outer=row.source_parent_bounds_pixels,child=row.source_child_bounds_pixels;for(let [r,color,cls]of [[outer,'#566e8a','parent-bounds'],[child,'#ba3343','child-bounds']])el('rect',{x:r[0],y:r[1],width:r[2]-r[0],height:r[3]-r[1],fill:'none',stroke:color,'stroke-width':2,class:cls},full);
document.getElementById('level-context').textContent='Original printed references: '+[...new Set(data.level_labels[row.view_id]||[])].join(' · ')+'.';
let ow=mesh.opening_outline_vertices[1][0]-mesh.opening_outline_vertices[0][0],head=mesh.opening_outline_vertices[3][2],raw=mesh.opening_outline_vertices[0][2];document.getElementById('measurements').textContent=`Observed opening width ${ow.toFixed(3)} nominal m; head ${head.toFixed(3)} m above printed Shop Level. Raw jamb bottom ${raw.toFixed(3)} m. ${interval?'Base-band interval '+interval.map(v=>v.toFixed(3)).join(' to ')+' nominal m relative to Shop Level.':'Source base band unresolved.'} Physical bottom and opening height remain unset.`;
}choice.addEventListener('change',draw);yaw.addEventListener('input',draw);bands.addEventListener('change',draw);draw();
</script></html>'''.replace('PAYLOAD',json.dumps(payload,separators=(',',':')).replace('<','\\u003c'))
    if len(html.encode())>64000000:raise ValueError('Facade HTML output budget exceeded')
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(html)
    return {'output':str(output),'choices':len(payload['choices']),'source_alternatives':len(evidence['previews']),'source_crops':len(payload['crops'])+len(payload['views'])}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('preview','components','views','output'):p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();print(json.dumps(render(a.preview,a.components,a.views,a.output)))
