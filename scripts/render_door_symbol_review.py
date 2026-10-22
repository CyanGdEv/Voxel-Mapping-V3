"""Interactive original-crop review of source door leaves and segmented swings."""
import argparse
import base64
import json
from pathlib import Path

import pymupdf
from shapely.geometry import shape

from voxel_mapper.generation_cycles import file_hash


def render(components,views,output):
    components,views,output=Path(components),Path(views),Path(output)
    report=json.loads((components/'component-report.json').read_text());view_report=json.loads((views/'view-report.json').read_text())
    for root,pins in [(components,report['output_sha256']),(views,view_report['output_sha256'])]:
        for name,pin in pins.items():
            if file_hash(root/name)!=pin:raise ValueError('Original review artifact changed')
    if file_hash(views/'view-report.json')!=report['contract']['view_report_sha256']:raise ValueError('Matching original view pack required')
    evidence=json.loads((components/report['door_symbol_evidence']['file']).read_text())
    source=json.loads((views/'view-candidates.json').read_text());source_views={v['id']:v for p in source['pages'] for v in p['views']}
    inventories={r['view_id']:json.loads((components/r['file']).read_text()) for r in report['results']}
    edges={e['id']:e for p in evidence['pages'] for e in p['edges']}
    payload={'items':[],'views':{},'wording':[n['text'] for p in evidence['pages'] for n in p['illustrative_wording']]}
    for review in evidence['views']:
        key=review['view_id'];view=source_views[key];receipt=json.loads((views/view['render']['receipt']).read_text())
        matrix=~pymupdf.Matrix(receipt['pixel_edge_to_pdf_native_matrix'])
        def point(p):return [p[0]*matrix.a+p[1]*matrix.c+matrix.e,p[0]*matrix.b+p[1]*matrix.d+matrix.f]
        payload['views'][key]={'caption':inventories[key]['caption'],'size':receipt['size_pixels'],
            'native_to_pixel_matrix':list(matrix),'source_crop_sha256':view['render']['png_sha256'],
            'png':'data:image/png;base64,'+base64.b64encode((views/view['render']['png']).read_bytes()).decode()}
        gaps={g['id']:g for g in inventories[key]['plan_gap_review']['gaps']}
        for gap in review['gaps']:
            for symbol in gap['symbols']:
                links=[l for l in evidence['conditional_position_links'] if any(s['symbol_id']==symbol['id'] and s['plan_view_id']==key for s in l['symbol_candidates'])]
                points=[*edges[symbol['leaf_edge_id']]['points_pdf_native'],*symbol['arc_vertices_pdf_native'],*shape(gaps[gap['source_gap_id']]['geometry_pdf_native']).exterior.coords]
                pixels=[point(p) for p in points];lo=[min(p[i] for p in pixels)-16 for i in (0,1)];hi=[max(p[i] for p in pixels)+16 for i in (0,1)]
                payload['items'].append({'view_id':key,'symbol':symbol,'conditional_position_links':len(links),
                    'leaf_pixels':[point(p) for p in edges[symbol['leaf_edge_id']]['points_pdf_native']],
                    'arc_pixels':[point(p) for p in symbol['arc_vertices_pdf_native']],
                    'gap_pixels':[point(p) for p in shape(gaps[gap['source_gap_id']]['geometry_pdf_native']).exterior.coords],
                    'zoom_box':[lo[0],lo[1],hi[0]-lo[0],hi[1]-lo[1]]})
    embedded=json.dumps(payload,separators=(',',':')).replace('<','\\u003c')
    html='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Original plan door-symbol evidence</title>
<style>body{font:16px system-ui;margin:24px;color:#17212b;background:#f7f8fa}p{line-height:1.5;max-width:1250px}select{font:inherit;padding:8px;max-width:100%}.controls{display:flex;gap:24px;align-items:center;flex-wrap:wrap}.panels{display:grid;grid-template-columns:1fr 1fr;gap:20px}article{background:white;border:1px solid #ccd2dc;padding:12px}h2{font-size:18px}svg{width:100%;height:auto}#zoom svg{height:500px}table{width:100%;border-collapse:collapse;margin:20px 0}th,td{padding:8px;text-align:left;border-bottom:1px solid #ccd2dc}.hold{color:#8c3a0c}@media(max-width:800px){.panels{grid-template-columns:1fr}}</style>
<h1>Original plan door symbols</h1><p>Each candidate uses an original leaf endpoint as its hinge and follows exact connected source line segments around it. The hinge and circle are never fitted. The full supported source arc must terminate; it is never cut at a convenient quarter turn. All competing source candidates remain available.</p>
<div class="controls"><label>Source gap and swing <select id="symbol"></select></label><label><input id="overlay" type="checkbox" checked> Show source evidence overlays</label></div><p id="status"></p>
<table><thead><tr><th>Original arc segments</th><th>Sweep</th><th>Leaf radius</th><th>Maximum radial residual</th><th>Conditional elevation alternatives</th></tr></thead><tbody id="measurements"></tbody></table>
<p class="hold">These are source door-symbol candidates. Physical aperture/wall identity, artwork scale/application, opening bottoms, construction state and park registration remain unverified. No accepted physical geometry, world blocks or training labels are added.</p><p id="wording"></p>
<p>Green: original leaf. Orange: complete original segmented swing. Orange point: original hinge. Cyan: original fill-gap corridor. The enlarged panel shows the same original source crop through a smaller viewing window.</p><div class="panels"><article><h2 id="sheet-title"></h2><div id="sheet"></div></article><article><h2>Original source detail</h2><div id="zoom"></div></article></div>
<script type="application/json" id="data">PAYLOAD</script><script>
const data=JSON.parse(document.getElementById('data').textContent),select=document.getElementById('symbol'),overlay=document.getElementById('overlay'),ns='http://www.w3.org/2000/svg';
for(let i=0;i<data.items.length;i++){let item=data.items[i],o=document.createElement('option');o.value=i;o.textContent=`${item.symbol.source_gap_id.slice(0,12)} · ${item.symbol.arc_edge_ids.length} original arc segments${item.conditional_position_links?' · NW correspondence':''}`;select.append(o)}let initial=data.items.findIndex(i=>i.conditional_position_links);if(initial>=0)select.value=initial;
function draw(){let item=data.items[Number(select.value)];if(!item){document.getElementById('status').textContent='No whole original leaf-and-swing candidate found.';return}let s=item.symbol,view=data.views[item.view_id];document.getElementById('status').textContent=`${data.items.length} source swing candidates retained. This candidate supports ${item.conditional_position_links} conditional elevation alternatives; these are overlapping interpretations, not additional doors.`;document.getElementById('sheet-title').textContent=view.caption;document.getElementById('wording').textContent='Original page wording: '+(data.wording.length?data.wording.join(' / '):'No illustrative or indicative wording found by this bounded pass.');let tr=document.createElement('tr');for(let value of [s.arc_edge_ids.length,Math.abs(s.sweep_degrees).toFixed(3)+'°',s.radius_pdf_points.toFixed(4)+' PDF points',s.maximum_radius_residual_pdf_points.toFixed(4)+' PDF points',item.conditional_position_links]){let td=document.createElement('td');td.textContent=value;tr.append(td)}document.getElementById('measurements').replaceChildren(tr);
for(const target of ['sheet','zoom']){let svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',target==='zoom'?item.zoom_box.join(' '):`0 0 ${view.size.join(' ')}`);let image=document.createElementNS(ns,'image');image.setAttribute('href',view.png);image.setAttribute('width',view.size[0]);image.setAttribute('height',view.size[1]);svg.append(image);if(overlay.checked){function path(points,color,cls,closed=false){let p=document.createElementNS(ns,'path');p.setAttribute('d','M'+points.map(p=>p.join(',')).join(' L')+(closed?' Z':''));p.setAttribute('stroke',color);p.setAttribute('fill','none');p.setAttribute('stroke-width',target==='zoom'?.65:2);p.setAttribute('class',cls);svg.append(p)}path(item.gap_pixels,'#008c99','source-gap',true);path(item.leaf_pixels,'#187643','source-leaf');path(item.arc_pixels,'#d38300','source-swing');let point=item.leaf_pixels[s.hinge_endpoint_index],circle=document.createElementNS(ns,'circle');circle.setAttribute('cx',point[0]);circle.setAttribute('cy',point[1]);circle.setAttribute('r',target==='zoom'?1:3);circle.setAttribute('fill','#d38300');circle.setAttribute('class','source-hinge');svg.append(circle)}document.getElementById(target).replaceChildren(svg)}}select.addEventListener('change',draw);overlay.addEventListener('change',draw);draw();
</script></html>'''.replace('PAYLOAD',embedded)
    if len(html.encode())>64000000:raise ValueError('Door review output budget exceeded')
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(html)
    return {'output':str(output),'bytes':output.stat().st_size,'symbol_options':len(payload['items']),'source_crops':len(payload['views'])}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('components','views','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();print(json.dumps(render(args.components,args.views,args.output)))
