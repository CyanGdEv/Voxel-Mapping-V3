"""Original section review with conditional whole adjoining ridge comparisons."""
import argparse
import base64
import json
from pathlib import Path
import tempfile

from scripts.render_section_projection_evidence import render as render_parent
from voxel_mapper.generation_cycles import file_hash


def render(evidence,projection_evidence,section_evidence,pyramid_evidence,source_directory,output):
    evidence,projection_evidence,section_evidence,pyramid_evidence,source_directory,output=map(Path,(evidence,projection_evidence,section_evidence,pyramid_evidence,source_directory,output))
    raw=(evidence/'section-adjoining-evidence.json').read_bytes();r=json.loads(raw)
    assert file_hash(projection_evidence)==r['contract']['source_projection_sha256']
    with tempfile.TemporaryDirectory() as tmp:
        parent=Path(tmp);(parent/'section-projection-evidence.json').write_bytes(projection_evidence.read_bytes())
        page=parent/'review.html';render_parent(parent,section_evidence,pyramid_evidence,source_directory,page);html=page.read_text()
    payload=json.dumps({'raw_base64':base64.b64encode(raw).decode()}).replace('<','\\u003c')
    html=html.replace('Section-to-plan projection candidates','Whole adjoining-ridge camera checks').replace('<title>Section projection candidates</title>','<title>Adjoining ridge evidence</title>')
    html=html.replace('<p class="note">','<p class="note">Green adjoining strokes show whole endpoint agreement. This is conditional on the same adjoining roof being visible; an absent match does not rule out an occluded roof. No physical identity is established. ')
    html=html.replace('<p id="status"></p>','<p id="status"></p><label>Original horizontal stroke <select id="ridgeLine"></select></label><p id="ridgeStatus"></p>')
    extra='''<script type="application/json" id="adjoiningData">PAYLOAD</script><script>
const adjoiningBytes=Uint8Array.from(atob(JSON.parse(el('adjoiningData').textContent).raw_base64),c=>c.charCodeAt(0)),adjoining=JSON.parse(new TextDecoder().decode(adjoiningBytes));
function adjoiningCurrent(){const p=current(),check=adjoining.projection_ridge_checks.find(r=>r.parent_projection_id===p.pose?.id),constraint=adjoining.conditional_face_constraints.find(r=>r.source_group_id===p.group?.id),planRidge=adjoining.plan_ridges.find(r=>r.pyramid_candidate_id===p.plan?.id),sourceLine=adjoining.source_horizontal_lines.find(l=>l.id===el('ridgeLine').value);return {...p,check,constraint,planRidge,sourceLine}}
const parentDraw=draw;let previousGroup=null;
draw=function(){parentDraw();let state=adjoiningCurrent();const {group,check,constraint,planRidge}=state;
if(previousGroup!==group?.id){const lines=adjoining.source_horizontal_lines.filter(l=>l.source_group_ids.includes(group?.id));options('ridgeLine',lines.map((l,i)=>[l.id,`${i+1}: source path ${l.path_index}, item ${l.item_index}`]));const matches=adjoining.projection_ridge_checks.filter(r=>r.source_group_id===group?.id).flatMap(r=>r.comparisons.filter(c=>c.endpoints_compatible));if(matches.length)el('ridgeLine').value=matches[0].source_line_id;previousGroup=group?.id;state=adjoiningCurrent()}
const {sourceLine}=state;el('ridgeLine').disabled=!check;
if(check&&sourceLine){const crop=state.source.crops.find(c=>c.source_leader_id===group.source_leader_id),sp=p=>p.map((v,i)=>v*2-crop.source_pixel_origin[i]),points=sourceLine.source_endpoints_pdf_unrotated,y=points[0][1],match=check.comparisons.find(c=>c.source_line_id===sourceLine.id),pixel=adjoining.source_line_pixel_checks.find(p=>p.line_id===sourceLine.id),supported=match?.endpoints_compatible&&pixel?.all_samples_supported;
line(el('overlay'),sp(points[0]),sp(points[1]),'#138448','ridge-source','ridge-original');line(el('overlay'),sp([check.projected_original_ridge_endpoint_x_pdf_points[0],y]),sp([check.projected_original_ridge_endpoint_x_pdf_points[1],y]),supported?'#138448':'#c33d2f','candidate','ridge-projected');
el('ridgeStatus').textContent=`${supported?'Whole endpoint match with sampled source colour support':'No supported whole endpoint match for this stroke/camera'}. ${constraint.conditionally_supported_projection_count} conditional orientations. Projection row uses this original stroke height for comparing horizontal stations only.`;
}else el('ridgeStatus').textContent=check?'No whole horizontal stroke in the checked source region.':'Source group remains held; adjoining comparison unavailable.';
if(state.plan&&planRidge){const c=state.plan.source_corners_pdf_native,ysum=Math.min(...c.map(p=>p[1]))+Math.max(...c.map(p=>p[1])),point=p=>[p[0],ysum-p[1]],ridge=planRidge.original_ridge.source_endpoints_pdf_native;
line(el('plan'),point(ridge[0]),point(ridge[1]),'#138448','native-ridge','adjoining-ridge');const all=[...c,...ridge].map(point),xs=all.map(p=>p[0]),ys=all.map(p=>p[1]);el('plan').setAttribute('viewBox',`${Math.min(...xs)-60} ${Math.min(...ys)-60} ${Math.max(...xs)-Math.min(...xs)+120} ${Math.max(...ys)-Math.min(...ys)+120}`)}
el('detail').textContent=JSON.stringify({conditional_constraint:constraint||null,original_source_line:sourceLine||null,ridge_projection:check?{...check,comparisons:check.comparisons.filter(c=>c.source_line_id===sourceLine?.id)}:null,physical_correspondence_verified:false,wall_closure_authorized:false},null,2)};
el('summary').textContent=`${report.counts.projection_candidates} parent cameras retained; ${adjoining.counts.conditionally_supported_projections} whole-ridge-supported conditional orientations. Green line in plan: unchanged original adjoining ridge.`;
el('ridgeLine').onchange=draw;el('download').onclick=()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([adjoiningBytes],{type:'application/json'}));a.download='section-adjoining-evidence.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
el('pose').onchange=draw;el('show').onchange=draw;draw();document.body.dataset.adjoiningReady='true';
</script>'''.replace('PAYLOAD',payload)
    output.write_text(html.replace('</html>',extra+'</html>'))
    return {'output':str(output),'review_sha256':file_hash(evidence/'section-adjoining-evidence.json')}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('evidence','projection-evidence','section-evidence','pyramid-evidence','source-directory','output'):p.add_argument('--'+name,type=Path,required=True)
    print(json.dumps(render(**vars(p.parse_args()))))
