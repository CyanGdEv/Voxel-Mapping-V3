"""Offline original-crop review of wall-return corners and conditional positions."""
import argparse
import base64
import json
from pathlib import Path

import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import shape

from voxel_mapper.generation_cycles import file_hash


def render(components, views, output):
    components,views,output=Path(components),Path(views),Path(output)
    report=json.loads((components/'component-report.json').read_text());view_report=json.loads((views/'view-report.json').read_text())
    for root,pins in [(components,report['output_sha256']),(views,view_report['output_sha256'])]:
        for name,pin in pins.items():
            if file_hash(root/name)!=pin:raise ValueError('Source review artifact changed')
    if file_hash(views/'view-report.json')!=report['contract']['view_report_sha256']:raise ValueError('Matching source view pack required')
    returns=json.loads((components/report['wall_return_corners']['file']).read_text())
    buildings=json.loads((components/report['building_facade_links']['file']).read_text())
    levels=json.loads((components/report['elevation_level_context']['file']).read_text())
    source=json.loads((views/'view-candidates.json').read_text());source_views={v['id']:v for p in source['pages'] for v in p['views']}
    inventories={r['view_id']:json.loads((components/r['file']).read_text()) for r in report['results']};records={r['id']:r for r in buildings['frames']}
    needed={records[r['facade_record_id']]['plan_view_id'] for r in returns['frames']}
    needed.update(v for r in returns['frames'] for v in records[r['facade_record_id']]['target_elevation_view_ids'])
    payload={'returns':returns,'buildings':buildings,'levels':levels,'views':{}}
    for key in sorted(needed):
        view=source_views[key];inventory=inventories[key];receipt=json.loads((views/view['render']['receipt']).read_text())
        matrix=~pymupdf.Matrix(receipt['pixel_edge_to_pdf_native_matrix'])
        def path(geometry):
            g=affine_transform(shape(geometry),[matrix.a,matrix.c,matrix.b,matrix.d,matrix.e,matrix.f])
            return ' '.join('M'+' L'.join(f'{x:.6f},{y:.6f}' for x,y in ring.coords)+' Z'
                for part in (g.geoms if g.geom_type=='MultiPolygon' else [g]) for ring in [part.exterior,*part.interiors])
        def point(p):return [p[0]*matrix.a+p[1]*matrix.c+matrix.e,p[0]*matrix.b+p[1]*matrix.d+matrix.f]
        payload['views'][key]={'caption':inventory['caption'],'size':receipt['size_pixels'],
            'png':'data:image/png;base64,'+base64.b64encode((views/view['render']['png']).read_bytes()).decode(),
            'source_native_to_pixel_matrix':list(matrix),
            'family_paths':{f['id']:path(f['geometry_pdf_native']) for f in inventory['residual_raster_hypotheses']}}
        for row in returns['frames']:
            if records[row['facade_record_id']]['plan_view_id']!=key:continue
            for trace in row['paint_reviews']:
                for profile in [trace['base_profile'],*trace['return_profiles']]:profile['review_svg_path']=path(profile['geometry_pdf_native'])
                for pair in trace['corner_pairs']:
                    for corner in pair['corners']:
                        if corner['selected_vertex']:corner['review_pixel_point']=point(corner['selected_vertex']['point_pdf_native'])
    embedded=json.dumps(payload,separators=(',',':')).replace('<','\\u003c')
    html='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Original wall-return corner review</title>
<style>body{font:16px system-ui;margin:24px;background:#f7f8fa;color:#17212b}p{max-width:1250px;line-height:1.5}select{font:inherit;padding:7px}.controls{display:flex;gap:20px;flex-wrap:wrap}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:20px}article{background:white;padding:12px;border:1px solid #ccd2dc}h2{font-size:18px}svg{width:100%;height:auto}table{width:100%;border-collapse:collapse;margin:16px 0}th,td{padding:8px;text-align:left;border-bottom:1px solid #ccd2dc}.hold{color:#8c3a0c}#positions svg{height:150px}</style>
<h1>Original wall returns: conditional facade alignment</h1>
<p>Both paint-side corner recipes are retained before comparing any elevation width or opening. Corners are original exterior-ring vertices with adjacent original parallel-edge support and paint-side probes. Source paints, holes and disconnected parts remain unchanged; nearby source joints are never snapped or filled.</p>
<div class="controls"><label>Source facade segment <select id="frame"></select></label><label>Original paint-side corners <select id="corner"></select></label><label><input id="reverse" type="checkbox"> Reverse elevation position direction</label></div>
<p id="status"></p><table><thead><tr><th>Original paint side</th><th>Raw corner span</th><th>Layout diagnostic span</th><th>Elevation frame</th><th>Width result</th></tr></thead><tbody id="widths"></tbody></table>
<p class="hold">Position agreement is conditional on source corner identity, printed-marker semantics and the peripheral-text layout hypothesis. Artwork scale/application, physical exterior/opening roles, floor datum, state and registration remain unverified. Original below-level jamb runs survive. No world blocks or training labels are added.</p>
<p>Red: original facing paint. Cyan: whole perpendicular return paints. Orange points: selected original source vertices. Cyan elevation outline: surrounding source family. Orange elevation outlines: overlapping child alternatives, not separate accepted openings.</p>
<div id="positions"></div><main id="panels"></main><script type="application/json" id="data">PAYLOAD</script><script>
const data=JSON.parse(document.getElementById('data').textContent),frames=data.returns.frames,choice=document.getElementById('frame'),cornerChoice=document.getElementById('corner'),reverse=document.getElementById('reverse'),records=new Map(data.buildings.frames.map(r=>[r.id,r])),families=new Map(data.levels.views.flatMap(v=>v.families).map(f=>[f.id,f]));
for(let i=0;i<frames.length;i++){const row=frames[i],record=records.get(row.facade_record_id),option=document.createElement('option');option.value=i;option.textContent=record.target_elevation_view_ids.map(v=>data.views[v].caption).join(' / ')+' · '+row.frame_id.slice(0,10);choice.append(option)}
let initial=frames.findIndex(f=>data.returns.diagnostics.some(d=>d.frame_id===f.frame_id&&d.position_comparisons.some(p=>p.status==='all_witness_positions_compatible')));if(initial>=0)choice.value=initial;
function setup(){let row=frames[Number(choice.value)];cornerChoice.replaceChildren();for(const trace of row.paint_reviews)for(const pair of trace.corner_pairs){let o=document.createElement('option');o.value=pair.id;o.textContent=pair.paint_side.replaceAll('_',' ')+' · '+pair.id.slice(0,8);cornerChoice.append(o)}cornerChoice.disabled=!cornerChoice.options.length;draw()}
function draw(){let row=frames[Number(choice.value)],record=records.get(row.facade_record_id),trace=row.paint_reviews.find(t=>t.corner_pairs.some(p=>p.id===cornerChoice.value)),pair=trace?.corner_pairs.find(p=>p.id===cornerChoice.value),diagnostic=data.returns.diagnostics.find(d=>d.source_corner_pair_id===pair?.id),positions=(diagnostic?.position_comparisons||[]).filter(p=>p.elevation_x_reversed===reverse.checked),passing=positions.filter(p=>p.status==='all_witness_positions_compatible');
document.getElementById('status').textContent=pair?`${pair.paint_side.replaceAll('_',' ')}: ${passing.length} of ${positions.length} conditional position comparisons agree in this direction. No physical opening acceptance.`:'No paired original return corners for this source frame.';
let body=document.getElementById('widths');body.replaceChildren();for(const t of row.paint_reviews)for(const c of t.corner_pairs){let d=data.returns.diagnostics.find(d=>d.source_corner_pair_id===c.id),tr=document.createElement('tr'),raw=c.corners.every(c=>c.selected_vertex)?(c.corners[1].selected_vertex.along_pdf_points-c.corners[0].selected_vertex.along_pdf_points):null,unit=data.buildings.frames.find(r=>r.id===row.facade_record_id);let comparison=d?.layout_width_comparisons[0],rawComparison=d?.raw_width_comparisons[0],values=[c.paint_side.replaceAll('_',' '),rawComparison?rawComparison.nominal_plan_width_m.toFixed(3)+' m':'No width comparison',d?(d.layout_position_interval_m[1]-d.layout_position_interval_m[0]).toFixed(3)+' m':'Original vertex required',comparison?comparison.witnesses[0].nominal_elevation_width_m.toFixed(3)+' m':'No surrounding family comparison',comparison?comparison.status.replaceAll('_',' '):'No level-supported opening link'];for(const value of values){let td=document.createElement('td');td.textContent=value;tr.append(td)}body.append(tr)}
let ns='http://www.w3.org/2000/svg',plot=document.getElementById('positions');plot.replaceChildren();if(diagnostic&&positions.length){let svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 1000 140');let low=diagnostic.layout_position_interval_m[0],width=diagnostic.layout_position_interval_m[1]-low,x=v=>60+(v-low)/width*880;function line(interval,y,colour,cls){let l=document.createElementNS(ns,'line');l.setAttribute('x1',x(interval[0]));l.setAttribute('x2',x(interval[1]));l.setAttribute('y1',y);l.setAttribute('y2',y);l.setAttribute('stroke',colour);l.setAttribute('stroke-width',4);l.setAttribute('class',cls);svg.append(l)}line(diagnostic.layout_position_interval_m,20,'#008d99','extent-axis');line(positions[0].source_gap_projection.nominal_plan_position_interval_m,60,'#19733b','plan-gap-position');positions.forEach((p,i)=>line(p.witnesses[0].nominal_position_interval_m,90+i*6,p.status==='all_witness_positions_compatible'?'#d28c00':'#b23b35','elevation-gap-position'));plot.append(svg);let caption=document.createElement('p');caption.textContent='Shared diagnostic axis: cyan extent, green original plan-gap projection, orange compatible or red incompatible elevation intervals. All source-witness checks remain in the artifact.';plot.append(caption)}
let panels=document.getElementById('panels');panels.replaceChildren();for(const id of [record.plan_view_id,...record.target_elevation_view_ids]){let v=data.views[id];if(!v)continue;let article=document.createElement('article'),title=document.createElement('h2');title.textContent=v.caption;article.append(title);let svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`0 0 ${v.size.join(' ')}`);let image=document.createElementNS(ns,'image');image.setAttribute('href',v.png);image.setAttribute('width',v.size[0]);image.setAttribute('height',v.size[1]);svg.append(image);function path(d,colour,cls){let p=document.createElementNS(ns,'path');p.setAttribute('d',d);p.setAttribute('class',cls);p.setAttribute('fill','none');p.setAttribute('fill-rule','evenodd');p.setAttribute('stroke',colour);p.setAttribute('stroke-width',2);svg.append(p)}
if(id===record.plan_view_id&&trace){path(trace.base_profile.review_svg_path,'#d63e45','facing-paint');for(const p of trace.return_profiles)path(p.review_svg_path,'#008d99','return-paint');for(const c of pair.corners){if(!c.selected_vertex)continue;let circle=document.createElementNS(ns,'circle');circle.setAttribute('cx',c.review_pixel_point[0]);circle.setAttribute('cy',c.review_pixel_point[1]);circle.setAttribute('r',4);circle.setAttribute('fill','#d28c00');circle.setAttribute('class','source-corner');svg.append(circle)}}else if(diagnostic){for(const family of new Set(diagnostic.layout_width_comparisons.map(c=>c.parent_residual_family_id)))path(v.family_paths[family],'#008d99','parent-family');for(const family of new Set(positions.map(p=>families.get(p.child_family_review_id).residual_family_id)))path(v.family_paths[family],'#d28c00','child-family')}article.append(svg);panels.append(article)}}choice.addEventListener('change',setup);cornerChoice.addEventListener('change',draw);reverse.addEventListener('change',draw);setup();
</script></html>'''.replace('PAYLOAD',embedded)
    if len(html.encode())>64000000:raise ValueError('Review HTML budget exceeded')
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(html)
    return {'output':str(output),'bytes':output.stat().st_size,'source_crops':len(needed),'frame_options':len(returns['frames'])}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--components',type=Path,required=True);parser.add_argument('--views',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(render(args.components,args.views,args.output)))
