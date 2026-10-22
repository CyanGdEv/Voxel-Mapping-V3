"""Original floor/roof artwork controls and held-out similarity review."""
import argparse
import base64
import json
from pathlib import Path

import pymupdf
from shapely.geometry import MultiPoint, shape

from voxel_mapper.generation_cycles import file_hash


def render(components,views,output):
    components,views,output=Path(components),Path(views),Path(output)
    report=json.loads((components/'component-report.json').read_text());view_report=json.loads((views/'view-report.json').read_text())
    for root,pins in [(components,report['output_sha256']),(views,view_report['output_sha256'])]:
        for name,pin in pins.items():
            if file_hash(root/name)!=pin:raise ValueError('Original artwork review changed')
    if file_hash(views/'view-report.json')!=report['contract']['view_report_sha256']:raise ValueError('Matching original views required')
    evidence=json.loads((components/report['artwork_scale_controls']['file']).read_text())
    source=json.loads((views/'view-candidates.json').read_text());page_views={(p['document_sha256'],p['page']):p['views'] for p in source['pages']}
    inventories={r['view_id']:json.loads((components/r['file']).read_text()) for r in report['results']}
    returns=json.loads((components/report['wall_return_corners']['file']).read_text())
    buildings=json.loads((components/report['building_facade_links']['file']).read_text())
    records={r['id']:r for r in buildings['frames']}
    labels={p['id']:inventories[records[f['facade_record_id']]['target_elevation_view_ids'][0]]['caption']+' · '+p['paint_side'].replace('_',' ')
        for f in returns['frames'] for trace in f['paint_reviews'] for p in trace['corner_pairs']}
    payload={'evidence':evidence,'views':{},'panels':{},'corner_labels':labels}
    for pair in evidence['pairs']:
        panels=[]
        for side,key in [('subject',pair['subject_page_key']),('reference',pair['reference_page_key'])]:
            controls=pair['controls']
            needed={i for r in controls for i in r[side+'_marker_ids']}
            page=next(p for p in evidence['pages'] if [p['document_sha256'],p['page']]==key)
            ids={v for m in page['markers'] if m['id'] in needed for v in m.get('whole_plan_view_ids',[])}
            if not ids:ids={v['id'] for v in page_views[tuple(key)] if v['id'] in inventories and v['printed_claim']['view_kind']=='plan'}
            for view in page_views[tuple(key)]:
                if view['id'] not in ids:continue
                receipt=json.loads((views/view['render']['receipt']).read_text());matrix=~pymupdf.Matrix(receipt['pixel_edge_to_pdf_native_matrix'])
                def point(p):return [p[0]*matrix.a+p[1]*matrix.c+matrix.e,p[0]*matrix.b+p[1]*matrix.d+matrix.f]
                def path(geometry):
                    g=shape(geometry)
                    rings=[g.exterior] if g.geom_type=='Polygon' else [g] if g.geom_type=='LineString' else []
                    return ' '.join('M'+' L'.join(','.join(str(v) for v in point(p)) for p in ring.coords)+(' Z' if g.geom_type=='Polygon' else '') for ring in rings)
                payload['views'][view['id']]={'caption':inventories[view['id']]['caption'],'size':receipt['size_pixels'],
                    'native_to_pixel_matrix':list(matrix),'source_crop_sha256':view['render']['png_sha256'],
                    'png':'data:image/png;base64,'+base64.b64encode((views/view['render']['png']).read_bytes()).decode()}
                marks=[{'key':r['key'],'role':r['role'],'native':r[side+'_center'],'pixel':point(r[side+'_center'])} for r in controls]
                all_hull=MultiPoint([r[side+'_center'] for r in controls]).convex_hull if controls else None
                fit_hull=MultiPoint([r[side+'_center'] for r in controls if r['role']=='fit']).convex_hull if controls else None
                targets=[d['source_points_pdf_native'] for d in evidence['diagnostics'] if d['pair_id']==pair['id']] if side=='subject' else []
                panels.append({'view_id':view['id'],'side':side,'marks':marks,'all_hull':path(all_hull.__geo_interface__) if all_hull is not None else '',
                    'fit_hull':path(fit_hull.__geo_interface__) if fit_hull is not None else '',
                    'targets':[[point(p) for p in points] for points in targets]})
        payload['panels'][pair['id']]=panels
    html='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Independent artwork controls</title>
<style>body{font:16px system-ui;margin:24px;background:#f7f8fa;color:#17212b}p{max-width:1260px;line-height:1.5}.controls{display:flex;gap:24px;align-items:center;flex-wrap:wrap}select{font:inherit;padding:8px}table{width:100%;border-collapse:collapse;margin:16px 0}th,td{padding:8px;text-align:left;border-bottom:1px solid #ccd2dc}.panels{display:grid;grid-template-columns:1fr 1fr;gap:20px}article{background:white;padding:12px;border:1px solid #ccd2dc}h2{font-size:18px}svg{width:100%;height:auto}.hold{color:#8c3a0c}@media(max-width:800px){.panels{grid-template-columns:1fr}}</style>
<h1>Independent artwork reference controls</h1><p>Printed non-target reference keys are discovered in both original plans. All Shop reference keys are excluded before roles are assigned. A four-parameter uniform scale/rotation model uses the fit controls; every held-out control checks the result. No building width, wall corner or opening participates in the fit. No residual outlier is removed.</p>
<div class="controls"><label>Original page pair <select id="pair"></select></label><label><input id="holdouts" type="checkbox" checked> Show held-out controls</label></div><p id="status"></p>
<p class="hold">This is artwork-layout evidence. Physical scale, application to the Shop outside the control hull, wall/aperture roles, opening bottoms, construction state and park registration remain unverified. No source geometry is corrected and no physical geometry, world blocks or training labels are added.</p>
<p>Blue: fit controls and fit baseline/hull. Orange: independent held-out controls. Grey dashed: hull of all eligible controls. Red on the floor plan: original corner endpoints, retained in both paint-side recipes. A span outside the grey hull still requires extrapolation.</p>
<table><thead><tr><th>Printed reference</th><th>Role</th><th>Original-marker residual</th><th>Font-size ratios</th></tr></thead><tbody id="controls"></tbody></table>
<details><summary id="excluded-summary"></summary><table><thead><tr><th>Excluded printed reference</th><th>Source reason</th></tr></thead><tbody id="excluded"></tbody></table></details>
<table><thead><tr><th>Original corner pair</th><th>Independent artwork span</th><th>Elevation width</th><th>Width result</th><th>Extrapolation</th></tr></thead><tbody id="widths"></tbody></table><div class="panels" id="panels"></div>
<script type="application/json" id="data">PAYLOAD</script><script>
const data=JSON.parse(document.getElementById('data').textContent),choice=document.getElementById('pair'),toggle=document.getElementById('holdouts'),ns='http://www.w3.org/2000/svg';for(let i=0;i<data.evidence.pairs.length;i++){let p=data.evidence.pairs[i],o=document.createElement('option');o.value=i;o.textContent=p.subject_page_key[0].slice(0,8)+' → '+p.reference_page_key[0].slice(0,8);choice.append(o)}
function table(body,rows){let target=document.getElementById(body);target.replaceChildren();for(let row of rows){let tr=document.createElement('tr');for(let value of row){let td=document.createElement('td');td.textContent=value;tr.append(td)}target.append(tr)}}
function draw(){let pair=data.evidence.pairs[Number(choice.value)];if(!pair)return;let controls=pair.controls.filter(r=>toggle.checked||r.role==='fit');document.getElementById('status').textContent=pair.status==='supported_non_target_artwork_layout_only'?`${pair.controls.length} eligible non-target controls: ${pair.fit_control_count} fit, ${pair.holdout_control_count} held out. Apparent artwork scale ${pair.apparent_subject_artwork_scale.toFixed(6)}; maximum held-out error ${pair.holdout_max_residual_pdf_points.toFixed(4)} PDF points.`:pair.status.replaceAll('_',' ');
table('controls',controls.map(r=>[r.key.join(' / '),r.role,r.residual_pdf_points===undefined?'Not fitted':r.residual_pdf_points.toFixed(4)+' PDF points',(r.font_ratios||[]).map(v=>v.toFixed(6)).join(' / ')]));table('excluded',pair.excluded_controls.map(r=>[r.key.join(' / '),r.reason.replaceAll('_',' ')]));document.getElementById('excluded-summary').textContent=`${pair.excluded_controls.length} excluded reference keys, retained with source reasons`;
let diagnostics=data.evidence.diagnostics.filter(d=>d.pair_id===pair.id);table('widths',diagnostics.map(d=>[data.corner_labels[d.source_corner_pair_id]||d.source_corner_pair_id.slice(0,10),d.nominal_span_m.toFixed(4)+' nominal m',d.width_comparisons[0]?d.width_comparisons[0].witnesses[0].nominal_elevation_width_m.toFixed(4)+' nominal m':'No level-supported family comparison',d.width_comparisons[0]?d.width_comparisons[0].status.replaceAll('_',' '):'Original source corners retained',d.outside_all_control_hull?'Outside all-control hull':'Inside all-control hull']));
let panels=document.getElementById('panels');panels.replaceChildren();for(const panel of data.panels[pair.id]){let view=data.views[panel.view_id],article=document.createElement('article'),title=document.createElement('h2');title.textContent=view.caption+' · '+panel.side;article.append(title);let svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`0 0 ${view.size.join(' ')}`);let image=document.createElementNS(ns,'image');image.setAttribute('href',view.png);image.setAttribute('width',view.size[0]);image.setAttribute('height',view.size[1]);svg.append(image);function path(d,color,cls,dashed=false){if(!d)return;let p=document.createElementNS(ns,'path');p.setAttribute('d',d);p.setAttribute('fill','none');p.setAttribute('stroke',color);p.setAttribute('stroke-width',2);p.setAttribute('class',cls);if(dashed)p.setAttribute('stroke-dasharray','6 4');svg.append(p)}path(panel.all_hull,'#777','all-control-hull',true);path(panel.fit_hull,'#2465c7','fit-control-hull');for(let mark of panel.marks){if(mark.role==='holdout'&&!toggle.checked)continue;let c=document.createElementNS(ns,'circle');c.setAttribute('cx',mark.pixel[0]);c.setAttribute('cy',mark.pixel[1]);c.setAttribute('r',5);c.setAttribute('fill',mark.role==='fit'?'#2465c7':'#d38300');c.setAttribute('class','control-mark '+mark.role);svg.append(c)}for(let points of panel.targets){path('M'+points.map(p=>p.join(',')).join(' L'),'#c73543','original-corner-span');for(let point of points){let c=document.createElementNS(ns,'circle');c.setAttribute('cx',point[0]);c.setAttribute('cy',point[1]);c.setAttribute('r',3);c.setAttribute('fill','#c73543');c.setAttribute('class','original-corner');svg.append(c)}}article.append(svg);panels.append(article)}}choice.addEventListener('change',draw);toggle.addEventListener('change',draw);draw();
</script></html>'''.replace('PAYLOAD',json.dumps(payload,separators=(',',':')).replace('<','\\u003c'))
    if len(html.encode())>64000000:raise ValueError('Artwork review output budget exceeded')
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(html)
    return {'output':str(output),'bytes':output.stat().st_size,'source_crops':len(payload['views']),'page_pairs':len(evidence['pairs'])}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('components','views','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();print(json.dumps(render(args.components,args.views,args.output)))
