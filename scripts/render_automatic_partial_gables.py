"""Interactive original-pixel review of short, partly occluded gable evidence."""
import argparse
import base64
import json
from pathlib import Path
from PIL import Image

from voxel_mapper.generation_cycles import file_hash
from voxel_mapper.reconstruction_evidence_queue import digest


def render(partial, gable, views, output):
    partial, gable, views, output = map(Path, (partial, gable, views, output))
    evidence = json.loads((partial/'partial-gables.json').read_text())
    if evidence['status'] != 'conditional_partial_gable_review_only':
        raise ValueError('Complete partial gable source review required')
    if file_hash(gable/'gable-roof-review.json') != evidence['contract']['source_gable_review_sha256']:
        raise ValueError('Original parent gable review changed')
    parent = json.loads((gable/'gable-roof-review.json').read_text())
    if file_hash(views/'view-report.json') != parent['contract']['view_report_sha256']:
        raise ValueError('Original source view report changed')
    report = json.loads((views/'view-report.json').read_text())
    for name, pin in report['output_sha256'].items():
        if file_hash(views/name) != pin:
            raise ValueError('Original source view changed')
    source = json.loads((views/'view-candidates.json').read_text())
    lookup = {v['id']: v for page in source['pages'] for v in page['views']}
    payload = {'evidence': evidence, 'parent': parent,
        'review_sha256': file_hash(partial/'partial-gables.json'), 'images': {}}
    for row in evidence['views']:
        view = lookup[row['view_id']]; path = views/view['render']['png']
        if file_hash(path) != row['source_png_sha256']:
            raise ValueError('Original source crop changed')
        with Image.open(path) as im:
            size = list(im.size)
        payload['images'][row['view_id']] = {'size': size, 'source_png_sha256': row['source_png_sha256'],
            'png': 'data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode()}
    html = r'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Adjacent gable source review</title>
<style>body{margin:0;background:#eef2f5;color:#142c39;font:16px system-ui}main{max-width:1400px;margin:auto;padding:28px}h1{font-size:32px;margin:8px 0}h2{font-size:19px;margin:0 0 16px}p{line-height:1.55;max-width:1120px}.eyebrow{color:#4b6677;font-size:13px;letter-spacing:2px}.notice{padding:15px 20px;background:#fff2d1;border-left:4px solid #ab760e}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0}.metrics div,article{padding:20px;background:white;border:1px solid #d4dde3;border-radius:8px}.metrics b{display:block;font-size:30px}.metrics span{font-size:14px;color:#4c6574}.controls{display:flex;flex-wrap:wrap;align-items:end;gap:16px;margin:20px 0}label{display:block;font-size:14px}select,button{display:block;margin-top:6px;padding:9px;font:inherit;max-width:100%;border:1px solid #9baeba;border-radius:4px;background:white;color:#142c39}button{cursor:pointer;background:#163f52;color:white}.panels{display:grid;grid-template-columns:1fr 1fr;gap:18px}.panels svg{width:100%;height:360px;background:#fff}.small{font-size:14px;color:#506776}.legend{display:flex;gap:20px;flex-wrap:wrap}.blue{color:#2266b0}.orange{color:#ad6400}.red{color:#a9274a}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:10px 12px;text-align:left;border-bottom:1px solid #d4dde3}th{background:#e4ecf1}.tablewrap{overflow-x:auto;margin:24px 0}.conditional{color:#176551}.held{color:#8a4e12}#pair{max-width:490px}input{accent-color:#1b5c7a}@media(max-width:850px){main{padding:16px}.panels{grid-template-columns:1fr}.metrics{grid-template-columns:1fr 1fr}.panels svg{height:300px}}</style>
<main><div class="eyebrow">VOXEL MAPPER · ORIGINAL DRAWING EVIDENCE</div><h1>Adjacent gable · visible short edges</h1>
<p>The main roof hides part of the smaller gable. This review recovers short source strokes and compares them with previously unpaired long slopes. Every source pixel and competing intersection remains available.</p>
<p class="notice" id="notice"></p>
<div class="metrics"><div><b id="nlines"></b><span>short source strokes</span></div><div><b id="npairs"></b><span>partial-gable interpretations</span></div><div><b id="ngood"></b><span>conditional alternatives</span></div><div><b id="nstable"></b><span>views supported at both thresholds</span></div></div>
<div class="controls"><label>Original elevation<select id="view"></select></label><label>Raster threshold<select id="threshold"><option>220</option><option>235</option></select></label><label>Source interpretation<select id="pair"></select></label><button id="download">Download evidence JSON</button></div>
<p id="status"></p><div class="controls"><label><input id="points" type="checkbox" checked> Original fit/check pixels</label><label><input id="fits" type="checkbox" checked> Fitted support intervals</label><label><input id="all" type="checkbox"> Show every short proposal</label></div>
<div class="panels"><article><h2>Visible source support</h2><svg id="detail" role="img" aria-label="Original pixels around the selected partial gable"></svg><p class="legend small"><span class="blue">● Even columns: fit</span><span class="orange">● Odd columns: check</span><span class="red">◆ Inferred intersection</span></p><p class="small">Dashed lines span measured support intervals. Gaps remain recorded and unfilled. The red point is inferred from line equations; it is not an original source vertex or an established physical ridge.</p></article><article><h2>Untouched original elevation</h2><svg id="context" role="img" aria-label="Full original elevation with selected source area"></svg><p class="small">The blue rectangle marks the detail view. Source images are embedded unchanged. The displayed detail window follows the selected evidence; no window supplies extraction input.</p></article></div>
<p id="measurements"></p><p id="threshold-status" class="notice"></p><h2 style="margin-top:28px">All retained partial-gable checks</h2><p class="small">Support-end checks reject intersections through the interior of a stroke. The pitch comparison assumes similar slopes only for screening; it does not impose symmetry on geometry. No candidate is selected by a trained ranker.</p>
<div class="tablewrap"><table><thead><tr><th>Threshold</th><th>Source alternative</th><th>Result</th><th>Ridge above Shop Level</th><th>Pitch difference</th><th>Support-end distances</th></tr></thead><tbody id="checks"></tbody></table></div>
<p class="small">Nominal drawing units, source state unspecified. No complete wing mesh, wall, aperture, geographic transform, accepted physical component, world block or training label is generated. The semantic ranker remains untrained. Native/text exclusions inherited from the preceding review can also exclude physical native edges. Neighbouring-column checks measure raster consistency, not independent survey accuracy.</p><p class="small" id="hash"></p></main>
<script type="application/json" id="data">PAYLOAD</script><script>
const data=JSON.parse(document.getElementById('data').textContent),ns='http://www.w3.org/2000/svg',view=document.getElementById('view'),threshold=document.getElementById('threshold'),pair=document.getElementById('pair');
const byId=id=>document.getElementById(id);function el(tag,attrs,parent){const node=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))node.setAttribute(k,v);parent.append(node);return node}
function state(){const row=data.evidence.views.find(r=>r.view_id===view.value),scan=row.variants.find(s=>s.threshold===Number(threshold.value)),parent=data.parent.gable_views.find(r=>r.view_id===row.view_id),old=parent.variants.find(s=>s.threshold===scan.threshold);return{row,scan,old,p:scan.pairs.find(p=>p.id===pair.value)}}
function source(svg,image,box){svg.replaceChildren();svg.setAttribute('viewBox',`${box[0]} ${box[1]} ${box[2]-box[0]} ${box[3]-box[1]}`);el('image',{href:image.png,width:image.size[0],height:image.size[1]},svg)}
function choices(){const{scan}=state();pair.replaceChildren();let rows=[...scan.pairs].sort((a,b)=>Number(b.status==='conditional_partial_gable_source_support')-Number(a.status==='conditional_partial_gable_source_support'));let option=document.createElement('option');option.value='';option.textContent='All short proposals · no pair selected';pair.append(option);for(let p of rows){let o=document.createElement('option');o.value=p.id;o.textContent=`${scan.pairs.indexOf(p)+1} / ${rows.length} · ${p.status==='conditional_partial_gable_source_support'?'conditional source support':'held'}`;pair.append(o)}if(rows.length)pair.value=rows[0].id;draw()}
function draw(){const{row,scan,old,p}=state(),image=data.images[row.view_id],detail=byId('detail'),context=byId('context');let lines=[];
if(p&&!byId('all').checked){lines=[{kind:'long',...old.lines.find(l=>l.id===p.source_long_line_id)},{kind:'short',...scan.lines.find(l=>l.id===p.source_short_line_id)}]}else lines=scan.lines.map(l=>({kind:'short',...l}));
let points=lines.flatMap(l=>l.source_pixels),box=[0,0,...image.size];if(points.length){let xx=points.map(p=>p.x),yy=points.map(p=>p.y);box=[Math.max(0,Math.min(...xx)-22),Math.max(0,Math.min(...yy)-22),Math.min(image.size[0],Math.max(...xx)+23),Math.min(image.size[1],Math.max(...yy)+23)];if(p){box[0]=Math.max(0,Math.min(box[0],p.inferred_ridge_pixel[0]-22));box[1]=Math.max(0,Math.min(box[1],p.inferred_ridge_pixel[1]-22))}}
source(detail,image,box);source(context,image,[0,0,...image.size]);el('rect',{x:box[0],y:box[1],width:box[2]-box[0],height:box[3]-box[1],stroke:'#2266b0',fill:'none','stroke-width':2,class:'detail-box'},context);
for(let l of lines){if(byId('points').checked)for(let p of l.source_pixels)el('circle',{cx:p.x,cy:p.y,r:.65,fill:p.role==='fit'?'#2266b0':'#c07800',class:`source-pixel ${p.role} ${l.kind}`},detail);if(byId('fits').checked)el('polyline',{points:l.source_x_interval.map(x=>`${x},${l.slope*x+l.intercept}`).join(' '),stroke:l.kind==='long'?'#17657b':'#963d75',fill:'none','stroke-dasharray':'3 3','stroke-width':.8,class:'source-fit '+l.kind},detail)}
if(p)el('circle',{cx:p.inferred_ridge_pixel[0],cy:p.inferred_ridge_pixel[1],r:1.9,fill:'#b02c4a',class:'inferred-ridge'},detail);
byId('status').textContent=`${row.caption} · threshold ${scan.threshold}: ${scan.lines.length} short proposals; ${scan.pairs.length} partial intersections, ${scan.pairs.filter(p=>p.status==='conditional_partial_gable_source_support').length} conditional alternatives. Original long strokes are not refitted.`;
byId('measurements').textContent=p?`Selected interpretation: inferred ridge ${p.nominal_ridge_height_m.toFixed(4)} nominal m above printed Shop Level; pitches ${p.left_pitch_degrees.toFixed(3)}° / ${p.right_pitch_degrees.toFixed(3)}°. Distances from the inferred ridge to visible support ends: ${p.source_ridge_end_errors_pixels.map(v=>v.toFixed(2)).join(' / ')} source pixels. ${p.status==='conditional_partial_gable_source_support'?'Local checks pass conditionally.':'Source check held.'} No independent wing depth or eave endpoints are established.`:'No partial pair selected. Showing all short source proposals, including unrelated raster strokes. These are evidence candidates, not classified roof edges.';
byId('threshold-status').textContent=row.source_threshold_status==='conditional_source_threshold_support'?'Some conditional pairs agree across source thresholds; physical correspondence still requires independent evidence.':'Cross-threshold hold: no matching conditional partial-gable support is established at both source thresholds. No complete wing geometry is generated.';
const table=byId('checks');table.replaceChildren();for(let s of row.variants)for(let [i,q]of s.pairs.entries()){let tr=document.createElement('tr');tr.className=q.status==='conditional_partial_gable_source_support'?'conditional':'held';for(let value of[s.threshold,i+1,q.status==='conditional_partial_gable_source_support'?'Conditional':'Held',q.nominal_ridge_height_m.toFixed(4)+' nominal m',q.pitch_difference_degrees.toFixed(3)+'°',q.source_ridge_end_errors_pixels.map(v=>v.toFixed(2)+' px').join(' / ')]){let td=document.createElement('td');td.textContent=value;tr.append(td)}table.append(tr)}}
for(let row of data.evidence.views){let o=document.createElement('option');o.value=row.view_id;o.textContent=row.caption;view.append(o)}
let first=data.evidence.views.flatMap(row=>row.variants.map(scan=>({row,scan,n:scan.pairs.filter(p=>p.status==='conditional_partial_gable_source_support').length}))).sort((a,b)=>b.n-a.n)[0];if(first){view.value=first.row.view_id;threshold.value=first.scan.threshold}
const counts=data.evidence.counts;byId('notice').textContent=(counts.views_with_cross_threshold_support?'Conditional source support exists across thresholds. ':'Cross-threshold stability remains unresolved. ')+`${counts.conditional_partial_gable_pairs} alternatives pass local support-end and pitch checks; ${counts.views_with_cross_threshold_support} views have matching support at both thresholds. Wing depth, eaves, complete silhouette and physical identity remain held. The preceding main-roof model is unchanged.`;byId('nlines').textContent=counts.short_source_lines;byId('npairs').textContent=counts.partial_gable_pairs;byId('ngood').textContent=counts.conditional_partial_gable_pairs;byId('nstable').textContent=counts.views_with_cross_threshold_support;byId('hash').textContent='Evidence SHA-256: '+data.review_sha256;
view.addEventListener('change',choices);threshold.addEventListener('change',choices);pair.addEventListener('change',draw);for(let id of['points','fits','all'])byId(id).addEventListener('change',draw);byId('download').addEventListener('click',()=>{let url=URL.createObjectURL(new Blob([JSON.stringify(data.evidence,null,2)+'\n'],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='partial-gable-evidence.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)});if(data.evidence.views.length)choices();
</script></html>'''
    html = html.replace('PAYLOAD', json.dumps(payload,separators=(',',':')).replace('<','\u003c'))
    if len(html.encode()) > 64000000:
        raise ValueError('Partial gable HTML output budget exceeded')
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(html)
    return {'output':str(output),'source_images':len(payload['images']),'bytes':output.stat().st_size,
        'parent_models_sha256':digest(parent['models']),'new_models':0}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('partial','gable','views','output'):parser.add_argument('--'+key,type=Path,required=True)
    a=parser.parse_args();print(json.dumps(render(a.partial,a.gable,a.views,a.output)))
