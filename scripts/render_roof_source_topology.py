"""Offline original-source junction and relative-position review."""
import argparse
import base64
import gzip
import json
from pathlib import Path

import pymupdf
from PIL import Image

from voxel_mapper.generation_cycles import file_hash


def render(topology, source_gradient, gable, views, output):
    topology, source_gradient, gable, views, output = map(Path, (topology, source_gradient, gable, views, output))
    path = topology / 'roof-source-topology.json'; raw = path.read_bytes(); evidence = json.loads(raw)
    if evidence['status'] != 'roof_source_topology_review_only':
        raise ValueError('Complete topology review required')
    if file_hash(source_gradient / 'source-gradient-gables.json') != evidence['contract']['source_gradient_sha256']:
        raise ValueError('Original gradient review changed')
    source = json.loads((source_gradient / 'source-gradient-gables.json').read_text())
    gable_pin = source['contract']['source_partial_contract']['source_gable_review_sha256']
    if file_hash(gable / 'gable-roof-review.json') != gable_pin:
        raise ValueError('Original main roof review changed')
    parent = json.loads((gable / 'gable-roof-review.json').read_text())
    report = json.loads((views / 'view-report.json').read_text())
    if file_hash(views / 'view-report.json') != parent['contract']['view_report_sha256']:
        raise ValueError('Original view report changed')
    for name, pin in report['output_sha256'].items():
        if file_hash(views / name) != pin: raise ValueError('Original view output changed')
    lookup = {v['id']: v for p in json.loads((views / 'view-candidates.json').read_text())['pages'] for v in p['views']}
    needed = {t['view_id'] for t in evidence['topologies']}; pairs = {}
    originals = {v['view_id']: v for v in parent['gable_views']}
    for row in source['views']:
        for scan in row['variants']:
            for anchor in scan['anchor_reviews']:
                old = next(v for v in originals[row['view_id']]['variants'] if v['threshold'] == anchor['source_parent_ink_threshold'])
                for pair in anchor['pairs']:
                    if pair['status'] != 'conditional_partial_gable_source_support': continue
                    needed.add(row['view_id'])
                    pairs[pair['id']] = {'pair': pair, 'view_id': row['view_id'],
                        'long': next(l for l in old['lines'] if l['id'] == pair['source_long_line_id']),
                        'short': next(l for l in scan['lines'] if l['id'] == pair['source_short_line_id'])}
    payload = {'gzip_json': base64.b64encode(gzip.compress(raw, mtime=0)).decode(),
        'review_sha256': file_hash(path), 'pairs': pairs, 'images': {}}
    for key in sorted(needed):
        view = lookup[key]; image_path = views / view['render']['png']
        if file_hash(image_path) != view['render']['png_sha256']: raise ValueError('Original PNG changed')
        receipt = json.loads((views / view['render']['receipt']).read_text())
        with Image.open(image_path) as image: size = list(image.size)
        payload['images'][key] = {'size': size, 'caption': view['caption_text'],
            'native_to_pixel_matrix': list(~pymupdf.Matrix(receipt['pixel_edge_to_pdf_native_matrix'])),
            'source_png_sha256': file_hash(image_path),
            'png': 'data:image/png;base64,' + base64.b64encode(image_path.read_bytes()).decode()}
    html = r'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Roof source junctions</title>
<style>body{margin:0;background:#edf2f4;color:#193544;font:16px system-ui}main{max-width:1400px;padding:28px;margin:auto}h1{font-size:32px;margin:8px 0}h2{font-size:20px}p{line-height:1.5}.notice{background:#fff0cc;border-left:4px solid #ae780b;padding:16px}.metrics,.panels{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin:20px 0}.metrics{grid-template-columns:repeat(4,1fr)}article,.metric{background:white;border:1px solid #d1dde3;border-radius:8px;padding:18px}.metric b{display:block;font-size:27px}.small{color:#536c79;font-size:13px}.controls{display:flex;gap:16px;flex-wrap:wrap}label{font-size:14px}select,button{display:block;font:inherit;padding:8px;margin:6px 0;max-width:100%;background:white;border:1px solid #94a9b5;border-radius:4px}button{background:#164b63;color:white;cursor:pointer}svg{width:100%;height:390px}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:9px;border-bottom:1px solid #dce4e8;text-align:left;vertical-align:top}td{word-break:break-word}pre{white-space:pre-wrap;font-size:12px}details{margin:20px 0}summary{cursor:pointer;padding:10px;font-weight:600}@media(max-width:850px){.panels,.metrics{grid-template-columns:1fr}main{padding:16px}}</style>
<main><div class="small">VOXEL MAPPER / ORIGINAL DRAWING EVIDENCE</div><h1>Roof junctions & relative position</h1><p>Whole native roof lines are connected before any elevation comparison. Every original endpoint, junction gap, competing template and source tail remains reviewable.</p><p class="notice">A source-position agreement is conditional. Near-balanced gable templates can also describe drawing hatching. Physical building identity, eave heights, complete depth and independent second-view edge support remain held. No new roof mesh or world placement.</p><div class="metrics" id="metrics"></div>
<div class="controls"><label>Connected source candidate<select id="candidate"></select></label><label>Conditional elevation alternative<select id="pair"></select></label><label>Original alignment hypothesis<select id="check"></select></label></div><div class="controls"><label><input type="checkbox" id="full"> Full original drawings</label><label><input type="checkbox" id="all"> All 28 source candidates</label><button id="download">Export full evidence JSON</button></div>
<p id="status"></p><div class="panels"><article><h2>Untouched roof plan · source junctions</h2><svg id="plan"></svg><p class="small">Gold: candidate ridge. Blue: whole outer rails, including tails. Magenta: whole original cap strokes. Circle: endpoint under comparison. Junction tolerance 0.25 PDF point; no snapping, trimming or inferred closure.</p></article><article><h2 id="caption">Original elevation</h2><svg id="elevation"></svg><p class="small">Original long and short fit spans only; red cross: inferred intersection. Shared source variants are not independent survey controls. Both original end anchors and both orientation signs remain separate.</p></article></div>
<article><h2>Original rail lengths & tails</h2><div id="tails"></div><h2>Every alignment for this candidate and source pair</h2><div style="overflow:auto"><table><thead><tr><th>Orientation</th><th>Pixel anchor</th><th>Native anchor</th><th>Ridge end</th><th>Error (nominal m)</th><th>Result</th></tr></thead><tbody id="checks"></tbody></table></div></article>
<details><summary>Exact native junction receipts</summary><pre id="junctions"></pre></details><details><summary>All connected source candidates, including disagreements</summary><div id="candidates"></div></details><p class="small" id="hash"></p></main><script type="application/json" id="data">PAYLOAD</script><script>
const packed=JSON.parse(document.getElementById('data').textContent),byId=id=>document.getElementById(id),ns='http://www.w3.org/2000/svg';let data,raw,state;
function node(tag,attrs,parent){let e=document.createElementNS(ns,tag);for(let[k,v]of Object.entries(attrs))e.setAttribute(k,v);parent.append(e);return e}
function option(select,value,label){let o=document.createElement('option');o.value=value;o.textContent=label;select.append(o)}
function source(svg,im,bounds){svg.replaceChildren();svg.setAttribute('viewBox',bounds.join(' '));node('image',{href:im.png,x:0,y:0,width:im.size[0],height:im.size[1]},svg)}
function mapPoint(p,im){let m=im.native_to_pixel_matrix;return[p[0]*m[0]+p[1]*m[2]+m[4],p[0]*m[1]+p[1]*m[3]+m[5]]}
function draw(){let candidate=data.candidates.find(c=>c.id===byId('candidate').value),record=packed.pairs[byId('pair').value],checks=data.evidence.position_checks.filter(c=>c.candidate_id===candidate.id&&c.source_pair_id===record.pair.id),check=checks.find(c=>c.id===byId('check').value)||checks[0],top=data.evidence.topologies.find(t=>t.candidates.some(c=>c.id===candidate.id)),lines=new Map(top.lines.map(l=>[l.source_component_id,l])),im=packed.images[top.view_id],svg=byId('plan');state={candidate,record,checks,check,top};let capIds=[...new Set(candidate.source_junctions.flatMap(j=>j.rail_contacts.flatMap(r=>r.alternatives.map(a=>a.cap_source_id))))],ids=[candidate.ridge_source_id,...candidate.rail_source_ids,...capIds],points=ids.flatMap(id=>lines.get(id).source_endpoints_pdf_native.map(p=>mapPoint(p,im))),xs=points.map(p=>p[0]),ys=points.map(p=>p[1]),bounds=[Math.min(...xs)-35,Math.min(...ys)-35,Math.max(...xs)-Math.min(...xs)+70,Math.max(...ys)-Math.min(...ys)+70];source(svg,im,byId('full').checked?[0,0,...im.size]:bounds);
function line(id,color,width,kind){node('polyline',{points:lines.get(id).source_endpoints_pdf_native.map(p=>mapPoint(p,im).join(',')).join(' '),fill:'none',stroke:color,'stroke-width':width,class:kind,'data-source-id':id},svg)}if(byId('all').checked)for(let c of top.candidates)line(c.ridge_source_id,'#90a4af',1,'other-ridge');for(let id of candidate.rail_source_ids)line(id,'#1475ad',2,'source-rail');for(let id of capIds)line(id,'#aa3b8a',1.5,'source-cap');line(candidate.ridge_source_id,'#c58c00',3,'source-ridge');if(check){let point=mapPoint(lines.get(candidate.ridge_source_id).source_endpoints_pdf_native[check.ridge_endpoint_index],im);node('circle',{cx:point[0],cy:point[1],r:5,fill:'none',stroke:'#d13227','stroke-width':2,class:'source-endpoint'},svg)}
let eim=packed.images[record.view_id],esvg=byId('elevation'),ridge=record.pair.inferred_ridge_pixel;source(esvg,eim,byId('full').checked?[0,0,...eim.size]:[ridge[0]-130,ridge[1]-55,260,210]);for(let[key,color]of[['long','#2069ac'],['short','#c08600']]){let l=record[key];node('polyline',{points:l.source_x_interval.map(x=>[x,l.slope*x+l.intercept].join(',')).join(' '),fill:'none',stroke:color,'stroke-width':2,class:'source-fit','data-role':key},esvg)}node('path',{d:`M${ridge[0]-5} ${ridge[1]}h10M${ridge[0]} ${ridge[1]-5}v10`,stroke:'#d13227',class:'inferred-ridge'},esvg);byId('caption').textContent=eim.caption;
byId('status').textContent=check?`${check.status.replaceAll('_',' ')} · signed error ${check.signed_position_error_nominal_m.toFixed(4)} nominal m. ${checks.filter(c=>c.status==='relative_source_position_agrees').length}/${checks.length} retained alignments agree for this pair. This does not establish a physical roof match.`:'No supported main-roof projection context; no relative-position check.';byId('checks').replaceChildren();for(let c of checks){let tr=document.createElement('tr');for(let s of[c.source_axis_sign_hypothesis===1?'Forward':'Reversed',c.anchor_source_pixel,c.anchor_source_component_id.slice(0,12),c.ridge_endpoint_index,c.signed_position_error_nominal_m.toFixed(5),c.status.replaceAll('_',' ')]){let td=document.createElement('td');td.textContent=s;tr.append(td)}byId('checks').append(tr)}byId('tails').textContent=`Native ridge ${candidate.nominal_ridge_length_m.toFixed(5)} m; whole rail lengths ${candidate.nominal_rail_lengths_m.map(v=>v.toFixed(5)).join(' / ')} m. Untrimmed tail intervals: ${candidate.source_rail_tails.map(t=>t.nominal_source_tails_m.map(v=>v.toFixed(5)).join(' + ')).join(' / ')} m. Values are nominal printed-scale diagnostics.`;byId('junctions').textContent=JSON.stringify(candidate.source_junctions,null,2)}
function choices(){let rows=data.evidence.position_checks.filter(c=>c.candidate_id===byId('candidate').value&&c.source_pair_id===byId('pair').value),select=byId('check');select.replaceChildren();for(let c of rows)option(select,c.id,`${c.source_axis_sign_hypothesis===1?'Forward':'Reversed'} · pixel ${c.anchor_source_pixel} · anchor ${c.anchor_source_component_id.slice(0,8)} · ridge end ${c.ridge_endpoint_index} · ${c.signed_position_error_nominal_m.toFixed(3)} m`);let good=rows.find(c=>c.status==='relative_source_position_agrees');if(good)select.value=good.id;draw()}
async function start(){raw=await new Response(new Blob([Uint8Array.from(atob(packed.gzip_json),c=>c.charCodeAt(0))]).stream().pipeThrough(new DecompressionStream('gzip'))).text();let evidence=JSON.parse(raw);data={evidence,candidates:evidence.topologies.flatMap(t=>t.candidates)};for(let[k,v]of Object.entries(evidence.counts)){if(k==='new_roof_models')continue;let div=document.createElement('div');div.className='metric';let b=document.createElement('b');b.textContent=v.toLocaleString();div.append(b,document.createTextNode(k.replaceAll('_',' ')));byId('metrics').append(div)}let good=evidence.position_checks.find(c=>c.status==='relative_source_position_agrees');for(let c of data.candidates)option(byId('candidate'),c.id,`${c.ridge_source_id.slice(0,12)} · ${c.nominal_ridge_length_m.toFixed(2)} m`);for(let[id,r]of Object.entries(packed.pairs))option(byId('pair'),id,`Contrast ${r.pair.source_gradient_cutoff} · parent ${r.pair.source_parent_ink_threshold} · ${id.slice(0,10)}`);if(good){byId('candidate').value=good.candidate_id;byId('pair').value=good.source_pair_id}let summary=document.createElement('pre');summary.textContent=data.candidates.map(c=>`${c.ridge_source_id} | ${c.nominal_ridge_length_m.toFixed(5)} m | ${evidence.position_checks.filter(p=>p.candidate_id===c.id&&p.status==='relative_source_position_agrees').length} agreeing alignments`).join('\n');byId('candidates').append(summary);byId('hash').textContent='Full original evidence SHA-256: '+packed.review_sha256;for(let id of['candidate','pair'])byId(id).addEventListener('change',choices);for(let id of['check','full','all'])byId(id).addEventListener('change',draw);byId('download').addEventListener('click',()=>{let url=URL.createObjectURL(new Blob([raw],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='roof-source-topology.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)});choices();document.body.dataset.ready='true'}start().catch(e=>{byId('status').textContent=String(e);throw e});
</script></html>'''.replace('PAYLOAD', json.dumps(payload, separators=(',', ':')).replace('<', '\u003c'))
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(html)
    return {'output': str(output), 'bytes': output.stat().st_size, 'source_images': len(needed)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('topology', 'source-gradient', 'gable', 'views', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    print(json.dumps(render(**vars(parser.parse_args()))))
