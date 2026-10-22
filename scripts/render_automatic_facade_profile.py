"""Interactive original-source overlays and lossless unplaced facade profile meshes."""
import argparse
import base64
import json
from pathlib import Path
from voxel_mapper.generation_cycles import file_hash
from voxel_mapper.reconstruction_evidence_queue import digest


def render(profile,preview,components,views,output):
    profile,preview,components,views,output=map(Path,(profile,preview,components,views,output))
    evidence=json.loads((profile/'facade-profile.json').read_text());contract=evidence['contract']
    for path,pin in [(preview/'facade-preview.json',contract['source_preview_sha256']),
        (components/'component-report.json',contract['component_report_sha256']),(views/'view-report.json',contract['view_report_sha256'])]:
        if file_hash(path)!=pin:raise ValueError('Facade profile source report changed')
    for group in evidence['profiles']:
        for variant in group['variants']:
            for name in ('roof','wall'):
                receipt=variant.get(name+'_mask_receipt')
                if receipt and file_hash(profile/receipt['file'])!=receipt['png_sha256']:raise ValueError('Facade profile mask changed')
    report=json.loads((views/'view-report.json').read_text())
    for name,pin in report['output_sha256'].items():
        if file_hash(views/name)!=pin:raise ValueError('Original facade profile source changed')
    source=json.loads((views/'view-candidates.json').read_text());source_views={v['id']:v for p in source['pages'] for v in p['views']}
    payload={'evidence':evidence,'views':{},'opening_choices':{}}
    for group in evidence['profiles']:
        view=source_views[group['view_id']];receipt=json.loads((views/view['render']['receipt']).read_text())
        payload['views'][group['view_id']]={'size':receipt['size_pixels'],'png_sha256':view['render']['png_sha256'],
            'png':'data:image/png;base64,'+base64.b64encode((views/view['render']['png']).read_bytes()).decode()}
        choices={}
        for opening in group['source_opening_alternatives']:
            choices.setdefault(digest(opening['mesh']),{'opening':opening,'source_ids':[]})['source_ids'].append(opening['id'])
        payload['opening_choices'][group['id']]=list(choices.values())
    html='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Automatic facade wall and roof profiles</title>
<style>body{font:16px system-ui;margin:24px;background:#f3f6f9;color:#17212b}h1{margin-bottom:8px}p{max-width:1200px;line-height:1.5}.notice{background:#fff3d8;border-left:4px solid #b57500;padding:14px}.controls{display:flex;gap:18px;flex-wrap:wrap;align-items:center;margin:16px 0}select{font:inherit;padding:6px}.panels{display:grid;grid-template-columns:1fr 1fr;gap:20px}article{background:white;border:1px solid #cbd3df;padding:14px}h2{font-size:19px}svg{width:100%;height:380px}.small{font-size:14px;color:#485969}table{border-collapse:collapse;width:100%;margin:16px 0}td,th{padding:9px;border-bottom:1px solid #cbd3df;text-align:left}@media(max-width:850px){.panels{grid-template-columns:1fr}}</style>
<h1>Façade · recovered wall and roof projections</h1><p id="summary"></p><p class="notice">Provisional drawing geometry. These are exact selected raster cells on a zero-thickness elevation plane. Roof depth and pitch, wall thickness, material, floor/threshold roles, physical scale, construction state and placement remain unverified. Raster holes and callout gaps are retained; they are not verified roof openings. The adjacent gable remains outside this main projection.</p>
<div class="controls"><label>Source profile <select id="group"></select></label><label>Raster threshold <select id="threshold"></select></label><label>Door alternative <select id="opening"></select></label><label>View angle <input id="yaw" type="range" min="-60" max="60" value="20"></label></div>
<div class="controls"><label><input type="checkbox" id="roof" checked> Roof projection</label><label><input type="checkbox" id="wall" checked> Wall profile</label><label><input type="checkbox" id="overlay" checked> Source overlays</label><label><input type="checkbox" id="raw" checked> Raw jamb extent</label><label><input type="checkbox" id="base" checked> Separate base envelope</label><label><input type="checkbox" id="old"> Previous rectangle</label></div>
<p id="measurements"></p><div class="panels"><article><h2>Unplaced façade mesh</h2><svg id="mesh" viewBox="0 0 800 380" role="img" aria-label="Unplaced source wall and roof profile meshes"></svg><p class="small">Dark blue: roof projection. Teal: wall profile down to the source shaded-band interface. Orange: two ends of the separate doorway base envelope. Red dashes: original raw jamb extent. No aperture is carved.</p></article><article><h2>Original drawing with exact cell overlays</h2><svg id="source" role="img" aria-label="Original elevation with source-cell wall and roof overlays"></svg><p class="small">Toggle overlays to compare against the untouched original. All source coordinates, small steps, holes and threshold differences are retained. The uneven drawn ground boundary is not assigned as a finished floor.</p></article></div>
<table><thead><tr><th>Raster threshold</th><th>Roof source cells / gaps</th><th>Wall source cells / gaps</th><th>Roof–wall overlap</th><th>Ground columns supported</th></tr></thead><tbody id="variants"></tbody></table><p id="comparison"></p><p>Both original threshold variants are retained separately. No best-fit variant, merged outline, smoothed edge, repaired joint or filled raster gap is substituted. Roof and wall share any original overlapping cells without snapping them together. Small mask gaps remain source uncertainty.</p>
<script type="application/json" id="data">PAYLOAD</script><script>
const data=JSON.parse(document.getElementById('data').textContent),ns='http://www.w3.org/2000/svg',group=document.getElementById('group'),threshold=document.getElementById('threshold'),opening=document.getElementById('opening'),yaw=document.getElementById('yaw');
function el(tag,attrs,parent){let e=document.createElementNS(ns,tag);for(let [k,v]of Object.entries(attrs))e.setAttribute(k,v);parent.append(e);return e}function line(svg,points,color,cls,dash=false,width=2){let p=el('polyline',{points:points.map(p=>p.join(',')).join(' '),stroke:color,fill:'none','stroke-width':width,class:cls},svg);if(dash)p.setAttribute('stroke-dasharray','5 4');return p}function on(id){return document.getElementById(id).checked}
for(let i=0;i<data.evidence.profiles.length;i++){let o=document.createElement('option');o.value=i;o.textContent=data.evidence.profiles[i].caption;group.append(o)}
function selectGroup(){let g=data.evidence.profiles[Number(group.value)];threshold.replaceChildren();opening.replaceChildren();if(!g)return;for(let i=0;i<g.variants.length;i++){let o=document.createElement('option');o.value=i;o.textContent=String(g.variants[i].threshold);threshold.append(o)}for(let i=0;i<data.opening_choices[g.id].length;i++){let o=document.createElement('option');o.value=i;o.textContent=`${i+1} of ${data.opening_choices[g.id].length}`;opening.append(o)}draw()}
function draw(){let g=data.evidence.profiles[Number(group.value)];if(!g)return;let v=g.variants[Number(threshold.value)],view=data.views[g.view_id],item=data.opening_choices[g.id][Number(opening.value)],door=item.opening,mesh=document.getElementById('mesh'),source=document.getElementById('source');mesh.replaceChildren();source.replaceChildren();let counts=data.evidence.counts;document.getElementById('summary').textContent=`${counts.source_profile_groups} source profile, ${counts.supported_profile_variants} supported threshold variants, ${counts.source_opening_alternatives} retained opening witness links. Zero accepted physical components or world blocks.`;
if(v.status!=='source_profile_masks_only'){document.getElementById('measurements').textContent=v.status.replaceAll('_',' ');return}let parent=g.source_parent_bounds_pixels,mpp=g.nominal_metres_per_source_pixel,level=g.printed_level_pixel,width=(parent[2]-parent[0])*mpp,angle=Number(yaw.value)*Math.PI/180;function project(p){let x=p[0]-width/2;return [400+x*Math.cos(angle)*33,330-p[2]*33+x*Math.sin(angle)*5]}function sourcePoint(p){return [p[0]/mpp+parent[0],level-p[2]/mpp]}
for(let [name,color]of [['roof','#526980'],['wall','#82bbb2']]){if(!on(name))continue;let s=v[name+'_surface'];for(let triangle of s.triangles){let points=triangle.map(i=>project(s.vertices_nominal_local_m[i]));el('polygon',{points:points.map(p=>p.join(',')).join(' '),fill:color,'shape-rendering':'crispEdges',class:'mesh-triangle '+name},mesh)}}
let points=door.mesh.opening_outline_vertices;if(on('raw'))line(mesh,[...points,points[0]].map(project),'#b53043','raw-opening',true);let interval=door.base_band_relative_to_printed_level_nominal_m;if(on('base')&&interval){for(let z of interval){let p=[[points[0][0],0,z],[points[1][0],0,z],points[2],points[3],[points[0][0],0,z]];line(mesh,p.map(project),'#b67a00','base-envelope',false,1.5)}}if(on('old'))line(mesh,[...door.mesh.context_vertices,door.mesh.context_vertices[0]].map(project),'#3077bd','old-context',true,1);line(mesh,[project([0,0,0]),project([width,0,0])],'#3077bd','printed-level',true,1);
let roofPolys=v.roof_surface.source_polygons_pixels,ys=roofPolys.flatMap(p=>p.coordinates[0].map(p=>p[1])),top=Math.max(0,Math.min(...ys)-30),end=Math.min(view.size[1],parent[3]+70);source.setAttribute('viewBox',`0 ${top} ${view.size[0]} ${end-top}`);el('image',{href:view.png,width:view.size[0],height:view.size[1]},source);if(on('overlay'))for(let [name,color]of [['roof','#526980'],['wall','#18897a']]){if(!on(name))continue;let d=v[name+'_surface'].source_polygons_pixels.map(p=>p.coordinates.map(r=>'M'+r.map(p=>p.join(',')).join(' L')+' Z').join(' ')).join(' ');el('path',{d,fill:color,opacity:.3,'fill-rule':'evenodd',stroke:color,'stroke-width':.5,class:'source-profile '+name},source)}
if(on('raw'))line(source,[...points,points[0]].map(sourcePoint),'#b53043','source-raw-opening',true,1);if(on('base')&&interval)for(let z of interval){line(source,[[points[0][0],0,z],[points[1][0],0,z],points[2],points[3],[points[0][0],0,z]].map(sourcePoint),'#b67a00','source-base-envelope',false,1)}if(on('old'))line(source,[...door.mesh.context_vertices,door.mesh.context_vertices[0]].map(sourcePoint),'#3077bd','source-old-context',true,1);
let xyz=v.roof_surface.vertices_nominal_local_m,z=xyz.map(p=>p[2]),x=xyz.map(p=>p[0]);document.getElementById('measurements').textContent=`Observed roof projection width ${(Math.max(...x)-Math.min(...x)).toFixed(3)} nominal m; top ${Math.max(...z).toFixed(3)} m above printed Shop Level. Main wall span ${width.toFixed(3)} nominal m. Physical roof pitch, wall thickness and doorway bottom remain unset. Printed drawing state: ${g.printed_state}.`;
let table=document.getElementById('variants');table.replaceChildren();for(let r of g.variants){let tr=document.createElement('tr'),values=r.roof_surface?[r.threshold,r.roof_surface.source_cell_count+' / '+r.roof_surface.source_hole_count,r.wall_surface.source_cell_count+' / '+r.wall_surface.source_hole_count,r.source_roof_wall_overlap_cells+' cells; unrepaired',r.ground_columns.filter(c=>c.supported).length+' / '+r.ground_columns.length]:[r.threshold,r.status.replaceAll('_',' '),'','',''];for(let value of values){let td=document.createElement('td');td.textContent=value;tr.append(td)}table.append(tr)}let c=g.threshold_comparison;document.getElementById('comparison').textContent=c?`Roof variants: ${(100*c.roof.intersection_over_union).toFixed(3)}% cell overlap, ${c.roof.different_cells} different cells. Wall variants: ${c.wall.different_cells} different cells. Variants remain separate.`:'Both source variants are required for a comparison.';
}group.addEventListener('change',selectGroup);for(let id of ['threshold','opening','roof','wall','overlay','raw','base','old'])document.getElementById(id).addEventListener('change',draw);yaw.addEventListener('input',draw);selectGroup();
</script></html>'''.replace('PAYLOAD',json.dumps(payload,separators=(',',':')).replace('<','\\u003c'))
    if len(html.encode())>64000000:raise ValueError('Facade profile HTML output budget exceeded')
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(html)
    return {'output':str(output),'source_profiles':len(evidence['profiles']),'source_images':len(payload['views']),
        'opening_choices':sum(len(v) for v in payload['opening_choices'].values())}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('profile','preview','components','views','output'):p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();print(json.dumps(render(a.profile,a.preview,a.components,a.views,a.output)))
