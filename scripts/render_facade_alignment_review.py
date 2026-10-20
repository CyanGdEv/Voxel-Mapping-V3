"""Render source crops and independent facade comparisons in an offline HTML review."""
import argparse
import base64
import json
from pathlib import Path

import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import shape

from voxel_mapper.generation_cycles import file_hash
from voxel_mapper.reconstruction_evidence_queue import digest


def render(components, views, output):
    components, views, output = Path(components), Path(views), Path(output)
    report = json.loads((components/'component-report.json').read_text())
    view_report = json.loads((views/'view-report.json').read_text())
    for root, pins in [(components, report['output_sha256']), (views, view_report['output_sha256'])]:
        for name, pin in pins.items():
            if file_hash(root/name) != pin: raise ValueError('Review source artifact changed')
    if (file_hash(views/'view-report.json') != report['contract']['view_report_sha256']
            or file_hash(views/'view-candidates.json') != report['contract']['view_candidates_sha256']):
        raise ValueError('Matching source view pack required')
    alignment = json.loads((components/report['facade_alignment']['file']).read_text())
    buildings = json.loads((components/report['building_facade_links']['file']).read_text())
    levels = json.loads((components/report['elevation_level_context']['file']).read_text())
    source = json.loads((views/'view-candidates.json').read_text())
    source_views = {v['id']: v for p in source['pages'] for v in p['views']}
    inventories = {r['view_id']: json.loads((components/r['file']).read_text()) for r in report['results']}
    needed = {r['plan_view_id'] for r in alignment['frames']}
    needed.update(v for r in alignment['frames'] for v in r['target_elevation_view_ids'])
    payload = {'alignment': alignment, 'buildings': buildings, 'levels': levels, 'views': {}}
    for key in sorted(needed):
        view = source_views[key]; inventory = inventories[key]
        if digest(view) != inventory['source_view_sha256']: raise ValueError('Source view changed')
        receipt = json.loads((views/view['render']['receipt']).read_text())
        if file_hash(views/view['render']['png']) != receipt['png_sha256']: raise ValueError('Source crop changed')
        matrix = ~pymupdf.Matrix(receipt['pixel_edge_to_pdf_native_matrix'])
        def path(geometry):
            geometry = affine_transform(shape(geometry), [matrix.a,matrix.c,matrix.b,matrix.d,matrix.e,matrix.f])
            return ' '.join('M'+' L'.join(f'{x:.6f},{y:.6f}' for x,y in ring.coords)+' Z'
                for part in (geometry.geoms if geometry.geom_type=='MultiPolygon' else [geometry])
                for ring in [part.exterior,*part.interiors])
        payload['views'][key] = {'caption': inventory['caption'], 'size': receipt['size_pixels'],
            'document_sha256': inventory['document_sha256'], 'page': inventory['page'],
            'png': 'data:image/png;base64,'+base64.b64encode((views/view['render']['png']).read_bytes()).decode(),
            'family_paths': {f['id']: path(f['geometry_pdf_native']) for f in inventory['residual_raster_hypotheses']}}
        for row in alignment['frames']:
            if row['plan_view_id'] == key:
                for review in row['frame_reviews']:
                    for extent in review['plan_extents']: extent['review_svg_path'] = path(extent['geometry_pdf_native'])
    embedded = json.dumps(payload,separators=(',',':')).replace('<','\\u003c')
    html = '''<!doctype html><html lang="en"><meta charset="utf-8"><title>Independent facade extent review</title>
<style>body{font:16px system-ui;margin:24px;color:#17212b;background:#f7f8fa}p{max-width:1200px;line-height:1.5}.controls{display:flex;gap:24px;flex-wrap:wrap}select{font:inherit;padding:7px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(400px,1fr));gap:18px}article{background:white;border:1px solid #ccd2dc;padding:12px}h2{font-size:18px}svg{width:100%;height:auto}table{border-collapse:collapse;margin:18px 0;width:100%}td,th{padding:9px;text-align:left;border-bottom:1px solid #ccd2dc}.hold{color:#8c3a0c}small{overflow-wrap:anywhere}.legend{font-size:14px}</style>
<h1>Independent facade extent review</h1>
<p>Compare unmodified plan extents with surrounding elevation jamb/head families. Positions are tested only when every original extent-width witness agrees within 0.25 nominal metres. Rejected widths remain visible in the table. Select a numbered elevation and its source-facing segment to inspect the evidence.</p>
<p>No translation or scale is fitted to an opening. A width discrepancy can reflect extent identity or nominal scale; it does not establish which is wrong. Physical walls/openings, construction state and registration remain unverified. This step adds no world blocks or training labels.</p>
<div class="controls"><label>Numbered elevation <select id="facade"></select></label><label>Source-facing segment <select id="frame"></select></label></div>
<p id="status" class="hold"></p><table><thead><tr><th>Independent plan source</th><th>Plan span</th><th>Elevation frame span</th><th>Extent result</th></tr></thead><tbody id="comparisons"></tbody></table>
<p class="legend">Blue: complete named plan enclosure, preserving holes. Red: complete nearby source paint, preserving disconnected parts. Cyan: surrounding elevation family bounds. Amber: original level-supported child family bounds. Extent spans do not establish physical continuity; original below-level runs remain unchanged.</p>
<main id="panels"></main><script type="application/json" id="data">PAYLOAD</script><script>
const data=JSON.parse(document.getElementById('data').textContent),facade=document.getElementById('facade'),frame=document.getElementById('frame'),rows=data.alignment.frames,projections=new Map(data.buildings.projected_gaps.map(p=>[p.id,p])),levelFamilies=new Map(data.levels.views.flatMap(v=>v.families).map(f=>[f.id,f]));
for(let i=0;i<rows.length;i++){let o=document.createElement('option');o.value=i;o.textContent=rows[i].target_elevation_view_ids.map(v=>data.views[v].caption).join(' / ')||'No unique target';facade.append(o)}
let initial=rows.findIndex(r=>r.frame_reviews.some(f=>f.parent_child_relations.length));if(initial>=0)facade.value=initial;
const words=s=>s.replaceAll('_',' '),span=xs=>Math.min(...xs).toFixed(3)+(Math.min(...xs)===Math.max(...xs)?'':'–'+Math.max(...xs).toFixed(3))+' nominal m';
function setup(){let row=rows[Number(facade.value)];frame.replaceChildren();row.frame_reviews.forEach((r,i)=>{let o=document.createElement('option');o.value=i;o.textContent=`${i+1}. ${r.frame_id.slice(0,12)}`;frame.append(o)});frame.disabled=!row.frame_reviews.length;draw()}
function draw(){let row=rows[Number(facade.value)],review=row.frame_reviews[Number(frame.value)],body=document.getElementById('comparisons');body.replaceChildren();let comparisons=review?review.extent_comparisons:[];
document.getElementById('status').textContent=review?`${review.parent_child_relations.length} parent/child relations; ${comparisons.length} independent extent comparisons; ${review.position_comparisons.length} conditional position comparisons. No verified facade alignment.`:words(row.status)+'. No origin hypothesis.';
for(const e of review?review.plan_extents:[]){let matches=comparisons.filter(c=>c.plan_extent_id===e.id);if(!matches.length)matches=[null];for(const c of matches){let tr=document.createElement('tr'),values=[words(e.source_kind)+` · ${e.source_part_count} part(s), ${e.source_hole_count} hole(s)`,span([e.nominal_plan_position_interval_m[1]-e.nominal_plan_position_interval_m[0]]),c?span(c.witnesses.map(w=>w.nominal_elevation_width_m)):'No eligible surrounding frame',c?words(c.status):'No eligible level-supported link'];for(const v of values){let td=document.createElement('td');td.textContent=v;tr.append(td)}body.append(tr)}}
const parents=new Set((review?review.parent_child_relations:[]).map(r=>levelFamilies.get(r.parent_family_review_id).residual_family_id)),children=new Set((review?review.parent_child_relations:[]).map(r=>levelFamilies.get(r.child_family_review_id).residual_family_id));
let panels=document.getElementById('panels');panels.replaceChildren();for(const id of [row.plan_view_id,...row.target_elevation_view_ids]){const v=data.views[id];if(!v)continue;let article=document.createElement('article'),h=document.createElement('h2');h.textContent=v.caption;article.append(h);let ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`0 0 ${v.size.join(' ')}`);let image=document.createElementNS(ns,'image');image.setAttribute('href',v.png);image.setAttribute('width',v.size[0]);image.setAttribute('height',v.size[1]);svg.append(image);
function overlay(d,colour,cls){let p=document.createElementNS(ns,'path');p.setAttribute('d',d);p.setAttribute('class',cls);p.setAttribute('fill','none');p.setAttribute('fill-rule','evenodd');p.setAttribute('stroke',colour);p.setAttribute('stroke-width',2);svg.append(p)}
if(id===row.plan_view_id){for(const e of review?review.plan_extents:[])overlay(e.review_svg_path,e.source_kind==='named_enclosure'?'#245bbb':'#d63e45','plan-extent '+e.source_kind)}else{for(const id of parents)overlay(v.family_paths[id],'#008d99','parent-family');for(const id of children)overlay(v.family_paths[id],'#d28c00','child-family')}
article.append(svg);let receipt=document.createElement('small');receipt.textContent=`Original PDF ${v.document_sha256} · page ${v.page}`;article.append(receipt);panels.append(article)}}facade.addEventListener('change',setup);frame.addEventListener('change',draw);setup();
</script></html>'''.replace('PAYLOAD',embedded)
    if len(html.encode()) > 64000000: raise ValueError('Review HTML budget exceeded')
    output.parent.mkdir(parents=True,exist_ok=True); output.write_text(html)
    return {'output':str(output),'bytes':output.stat().st_size,'source_crops':len(needed),'facade_records':len(alignment['frames'])}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--components',type=Path,required=True); parser.add_argument('--views',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); print(json.dumps(render(args.components,args.views,args.output)))
