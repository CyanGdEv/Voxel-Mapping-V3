"""Conditional local row-group solids from visible design-statement dimensions."""
from concurrent.futures import CancelledError
from html import escape
import json
import math
from pathlib import Path
import re

from . import building_spec, planning_design_dimensions, study_mesh_export
from .building_spec import digest

VERSION = 'planning-design-massing-v1'
LIMITS = {'max_alternatives': 64, 'max_checks': 8192, 'max_output_bytes': 8000000}


def review_pages(pages, *, options=None, cancelled=lambda: False):
    options = {} if options is None else options
    if not isinstance(options, dict) or set(options)-set(LIMITS):
        raise ValueError('Known design massing limits required')
    limits = {**LIMITS, **options}
    if (not isinstance(pages, list) or len(pages) > 512
            or any(type(v) is not int or not 1 <= v <= LIMITS[k] for k, v in limits.items())
            or limits['max_output_bytes'] < 16384):
        raise ValueError('Bounded lower-only design massing policy required')
    result = {'version': VERSION, 'status': 'conditional_local_design_massing_only',
        'analysis_complete': True, 'source_pages': {}, 'alternatives': [], 'withheld': [],
        'source_height_claims': [],
        'limits': limits, 'checks': 0, 'physical_height_verified': False,
        'ground_datum_verified': False, 'world_placement_eligible': False,
        'world_geometry_additions': 0, 'training_labels_generated': 0, 'model_weights_updated': False,
        'limitations': ['Group envelopes are conditional interpretations of printed design dimensions.',
            'Both clear-gap and row-centre meanings of apart are retained; neither is selected.',
            'Row groups are not segmented into individual cabins and have no physical component correspondence.',
            'The display ground zero and along/across axes are assumed local coordinates, not a surveyed datum.',
            'Ridge claims do not define a dome profile; no roof, openings, paths or park placement are invented.']}

    def check():
        if cancelled():
            raise CancelledError('Design massing cancelled')

    def finish(reason=None):
        if reason:
            result.update(status='design_massing_withheld', analysis_complete=False,
                reason=reason, alternatives=[],source_height_claims=[])
        result['summary'] = {'conditional_design_massing_alternatives': len(result['alternatives']),
            'conditional_design_row_groups': 2*len(result['alternatives']),
            'physical_design_buildings_verified': 0}
        if len(json.dumps(result, indent=2, allow_nan=False).encode())+80 > limits['max_output_bytes']:
            result.update(status='design_massing_withheld', analysis_complete=False,
                reason='design_massing_output_budget_exceeded', alternatives=[], source_pages={}, withheld=[],source_height_claims=[])
            result['summary'] = dict.fromkeys(result['summary'], 0)
        check()
        result['id'] = digest(result)
        return result

    unique = {}
    for page in pages:
        check()
        if (page.get('version') != planning_design_dimensions.VERSION
                or page.get('id') != digest({k: v for k, v in page.items() if k != 'id'})
                or not re.fullmatch('[0-9a-f]{64}', str(page.get('document_sha256')))
                or type(page.get('page')) is not int or page['page'] < 1):
            raise ValueError('Exact current design-dimension page evidence required')
        key = page['document_sha256']+':'+str(page['page'])
        if key in unique and unique[key] != page:
            raise ValueError('Conflicting design-dimension source page')
        unique[key] = page
        result['source_pages'][key] = {'sha256': digest(page),
            'analysis_complete': page['analysis_complete'], 'reason': page.get('reason')}
    retained_bytes = 0
    for page in unique.values():
        check()
        if not page['analysis_complete']:
            result['withheld'].append({'document_sha256': page['document_sha256'],
                'page': page['page'], 'reason': 'complete_dimension_page_required'})
            continue
        for height in page.get('height_claims',[]):
            check()
            result['checks'] += 1
            if result['checks'] > limits['max_checks']:
                return finish('design_massing_work_budget_exceeded')
            record={'document_sha256':page['document_sha256'],'page':page['page'],
                'source_page_sha256':digest(page),'claim':height,
                'same_physical_component_verified':False}
            retained_bytes += len(json.dumps(record,allow_nan=False).encode())
            if retained_bytes > limits['max_output_bytes']-2048:
                return finish('design_massing_output_budget_exceeded')
            result['source_height_claims'].append(record)
        for claim in page['claims']:
            check()
            result['checks'] += 1
            if result['checks'] > limits['max_checks']:
                return finish('design_massing_work_budget_exceeded')
            if claim.get('kind') != 'paired_row_design_dimensions':
                continue
            if claim.get('row_count') != 2 or claim.get('spacing_semantics') != 'unspecified_apart':
                raise ValueError('Two source rows and explicit unresolved apart semantics required')
            values = [claim.get(k) for k in ('length_m', 'width_m', 'eaves_height_m', 'spacing_m')]
            if not all(type(v) in (int, float) and math.isfinite(v) and 0 < v <= 999 for v in values):
                raise ValueError('Finite positive bounded source design dimensions required')
            if not all(.05 <= v <= 500 for v in values):
                result['withheld'].append({'claim_id':claim['id'],
                    'reason':'source_dimensions_outside_supported_massing_range'})
                continue
            length, width, height, spacing = values
            state = claim.get('printed_state', 'unknown')
            if state not in ('proposed', 'existing', 'unknown'):
                raise ValueError('Explicit source design state required')
            for interpretation, second_row in (('clear_gap', width+spacing), ('row_centre_separation', spacing)):
                check()
                result['checks'] += 1
                if result['checks'] > limits['max_checks']:
                    return finish('design_massing_work_budget_exceeded')
                if second_row <= width:
                    result['withheld'].append({'claim_id': claim['id'], 'interpretation': interpretation,
                        'reason': 'source_rows_would_overlap_or_touch'})
                    continue
                if len(result['alternatives']) >= limits['max_alternatives']:
                    return finish('design_massing_alternative_budget_exceeded')
                identifier = digest([VERSION, page['document_sha256'], page['page'], claim['id'], interpretation])
                assumptions = [*result['limitations'],
                    'For this alternative, apart is interpreted as '+interpretation.replace('_', ' ')+'.',
                    'Row groups are solid display envelopes, not wall construction, floor plates or complete physical buildings.']
                spec = {'version': building_spec.VERSION, 'coordinate_frame': building_spec.FRAME,
                    'building_id': 'design-row-groups:'+identifier,
                    'preview_scope': 'conditional_unplaced_design_row_group_massing',
                    'sources': [{'id': 'design_statement', 'sha256': page['document_sha256'], 'state': state,
                        'page': page['page'], 'source_evidence_sha256': digest(page), 'claim_id': claim['id']}],
                    'assumptions': assumptions, 'components': []}
                for index, y in enumerate((0., second_row)):
                    spec['components'].append({'id': 'source_row_group_'+str(index+1), 'role': 'detail',
                        'colour': '6a91ae' if index == 0 else '9aacc1',
                        'geometry': {'kind': 'extrusion', 'axis': 2, 'interval_m': [0., height],
                            'profile': [[0., y], [length, y], [length, y+width], [0., y+width]]},
                        'evidence': {'class': 'inferred', 'source_ids': ['design_statement'],
                            'description': 'Unplaced row-group envelope from visible design dimensions; '+interpretation+' spacing assumption.',
                            'source_claim_id': claim['id'], 'physical_component_identity_verified': False}})
                model = building_spec.build(spec)
                if (len(model['components']) != 2 or any(not c['mesh']['watertight'] for c in model['components'])
                        or model['world_placement_eligible'] or model['park_world_blocks_added']):
                    raise ValueError('Two closed unplaced group-envelope meshes required')
                row = {'id': identifier, 'document_sha256': page['document_sha256'], 'page': page['page'],
                    'source_claim_id': claim['id'], 'source_claim_sha256': digest(claim),
                    'source_page_sha256': digest(page), 'source_claim': claim,
                    'spacing_interpretation': interpretation, 'overall_nominal_extents_m': [length, second_row+width, height],
                    'clear_row_gap_m': second_row-width, 'spec': spec, 'spec_sha256': digest(spec),
                    'physical_height_verified': False, 'local_ground_zero_assumed': True,
                    'ground_datum_verified': False, 'ridge_geometry_generated': False,
                    'individual_cabins_generated': False, 'world_placement_eligible': False}
                retained_bytes += len(json.dumps(row, allow_nan=False).encode())
                if retained_bytes > limits['max_output_bytes']-2048:
                    return finish('design_massing_output_budget_exceeded')
                result['alternatives'].append(row)
    return finish()


def write_review(root, review, *, cancelled=lambda: False):
    if review.get('version') != VERSION or review.get('id') != digest({k: v for k, v in review.items() if k != 'id'}):
        raise ValueError('Exact current design massing review required')
    root = Path(root)
    body = ['<!doctype html><html lang="en"><meta charset="utf-8"><title>Conditional design massing</title>',
        '<style>body{font:16px system-ui;max-width:1150px;margin:2rem auto;padding:0 1rem;color:#253244}canvas{width:100%;height:460px;background:#edf1f5;touch-action:none}select{font:inherit;padding:.5rem}li{margin:.5rem 0}</style>',
        '<h1>Conditional design massing</h1><p>Source-linked row-group envelopes. Drag the preview to rotate; use the wheel to zoom. '
        'Each source keeps its existing, proposed or unknown state, with an assumed local ground zero. '
        'No individual cabin identity, complete roof, surveyed position or park placement is established.</p>',
        '<p><a href="design-massing.json">Exact source claims and assumptions</a> · <a href="review.html">Original-page evidence</a></p>']
    models = []
    if not review['analysis_complete']:
        body.append('<p>Preview withheld: '+escape(review.get('reason', 'incomplete evidence'))+'</p>')
    if review['alternatives']:
        body.append('<label for="choice">Spacing interpretation</label> <select id="choice">')
    for index, row in enumerate(review['alternatives']):
        if cancelled():
            raise CancelledError('Design massing export cancelled')
        if row['spec_sha256'] != digest(row['spec']):
            raise ValueError('Exact massing specification required')
        directory = root/('design-massing-'+str(index).zfill(3))
        directory.mkdir(exist_ok=True)
        model = building_spec.build(row['spec'])
        (directory/'spec.json').write_text(json.dumps(row['spec'], indent=2, allow_nan=False), encoding='utf-8')
        (directory/'model.json').write_text(json.dumps(model, indent=2, allow_nan=False), encoding='utf-8')
        study_mesh_export.write_glb(model, directory/'model.glb')
        (directory/'preview.svg').write_text(_svg(model,row['overall_nominal_extents_m']),encoding='utf-8')
        models.append({'name': row['spacing_interpretation'].replace('_', ' '),
            'extents': row['overall_nominal_extents_m'], 'components': model['components']})
        extent=' × '.join(f'{v:.3f}' for v in row['overall_nominal_extents_m'])
        body.append('<option value="'+str(index)+'">'+escape(row['spacing_interpretation'].replace('_', ' '))+
            ' — '+extent+' m</option>')
    if models:
        body.append('</select><p id="dimensions"></p><canvas id="view" width="1100" height="460" aria-label="Interactive conditional row-group massing"></canvas><noscript><img alt="Conditional row-group massing" src="design-massing-000/preview.svg"></noscript><ul>')
        for index, row in enumerate(review['alternatives']):
            body.append('<li>'+escape(row['spacing_interpretation'].replace('_', ' '))+': <a href="design-massing-'+str(index).zfill(3)+'/model.glb">3D GLB</a> · <a href="design-massing-'+str(index).zfill(3)+'/preview.svg">Static 3D view</a> · <a href="design-massing-'+str(index).zfill(3)+'/spec.json">Source-linked specification</a></li>')
        body.append('</ul>')
        payload=json.dumps(models, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c')
        body.append('<script>const models='+payload+';'+_VIEWER+'</script>')
    else:
        body.append('<p>No complete visible paired-row design dimensions were recovered.</p>')
    if review.get('source_height_claims'):
        body.append('<h2>Other printed height claims</h2><p>Source roles and component correspondence remain unresolved. '
            'These values do not select or construct a roof.</p><ul>')
        for row in review['source_height_claims']:
            claim=row['claim']
            body.append('<li>'+escape(str(claim.get('height_m')))+' m; '+
                escape(claim.get('dimension_role','unspecified'))+'; page '+str(row['page'])+
                '; source '+escape(row['document_sha256'][:16])+'.</li>')
        body.append('</ul>')
    body.append('<p>Ridge heights remain source claims. A dome shape and ground survey cannot be recovered from these row dimensions alone. '
        'No world geometry or training label is generated.</p></html>')
    (root/'design-massing.html').write_text(''.join(body), encoding='utf-8')
    (root/'design-massing.json').write_text(json.dumps(review, indent=2, allow_nan=False), encoding='utf-8')
    if cancelled():
        raise CancelledError('Design massing export cancelled')


def _svg(model, extents):
    length,width,height=extents
    yaw=-.6;pitch=.65
    def rotate(v):
        x,y,z=v[0]-length/2,v[1]-width/2,v[2]-height/2
        a=x*math.cos(yaw)-y*math.sin(yaw);b=x*math.sin(yaw)+y*math.cos(yaw)
        return [a,b*math.sin(pitch)-z*math.cos(pitch),
            b*math.cos(pitch)+z*math.sin(pitch)]
    points=[rotate(v) for c in model['components'] for v in c['mesh']['vertices']]
    x0,y0=[min(v[k] for v in points) for k in (0,1)]
    x1,y1=[max(v[k] for v in points) for k in (0,1)]
    scale=min(1020/(x1-x0),370/(y1-y0))
    def project(v):
        x,y,z=rotate(v)
        return [550+(x-(x0+x1)/2)*scale,220+(y-(y0+y1)/2)*scale,z]
    faces=[]
    for component in model['components']:
        projected=[project(v) for v in component['mesh']['vertices']]
        faces.extend(([projected[i] for i in triangle],component['colour']) for triangle in component['mesh']['triangles'])
    faces.sort(key=lambda row:sum(p[2] for p in row[0]))
    parts=['<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="500" viewBox="0 0 1100 500"><rect width="1100" height="500" fill="#edf1f5"/>']
    for points,colour in faces:
        coordinates=' '.join(f'{p[0]:.3f},{p[1]:.3f}' for p in points)
        parts.append(f'<polygon points="{coordinates}" fill="#{colour}" stroke="#3e5266" stroke-width=".6"/>')
    caption='Conditional row envelopes: '+' × '.join(f'{v:.3f}' for v in extents)+' m. Roof omitted; local zero assumed.'
    parts.append('<text x="30" y="480" font-family="sans-serif" font-size="18">'+escape(caption)+'</text></svg>')
    return ''.join(parts)


_VIEWER = r'''
const canvas=document.getElementById('view'),ctx=canvas.getContext('2d'),choice=document.getElementById('choice');
let yaw=-.6,pitch=.65,zoom=1,drag=null;
function draw(){const m=models[Number(choice.value)],e=m.extents;
ctx.clearRect(0,0,1100,460);const rotate=v=>{let x=v[0]-e[0]/2,y=v[1]-e[1]/2,z=v[2]-e[2]/2;
const a=x*Math.cos(yaw)-y*Math.sin(yaw),b=x*Math.sin(yaw)+y*Math.cos(yaw);
return[a,b*Math.sin(pitch)-z*Math.cos(pitch),b*Math.cos(pitch)+z*Math.sin(pitch)];};
const all=m.components.flatMap(c=>c.mesh.vertices.map(rotate)),lo=[0,1].map(k=>Math.min(...all.map(v=>v[k]))),hi=[0,1].map(k=>Math.max(...all.map(v=>v[k])));
const scale=Math.min(1020/(hi[0]-lo[0]),400/(hi[1]-lo[1]))*zoom;
const project=v=>{const p=rotate(v);return[550+(p[0]-(lo[0]+hi[0])/2)*scale,230+(p[1]-(lo[1]+hi[1])/2)*scale,p[2]];};
const faces=[];for(const c of m.components){const p=c.mesh.vertices.map(project);for(const t of c.mesh.triangles)faces.push({p:t.map(i=>p[i]),colour:'#'+c.colour});}
faces.sort((a,b)=>a.p.reduce((s,p)=>s+p[2],0)-b.p.reduce((s,p)=>s+p[2],0));
for(const f of faces){ctx.beginPath();f.p.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));ctx.closePath();ctx.fillStyle=f.colour;ctx.fill();ctx.strokeStyle='#3e5266';ctx.lineWidth=.6;ctx.stroke();}
document.getElementById('dimensions').textContent=e.map(v=>v.toFixed(3)).join(' × ')+' m; '+m.name+'. Local zero assumed; roof omitted.';}
choice.onchange=draw;canvas.onpointerdown=e=>{drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);};
canvas.onpointermove=e=>{if(!drag)return;yaw+=(e.clientX-drag[0])*.01;pitch=Math.max(-1.4,Math.min(1.4,pitch+(e.clientY-drag[1])*.01));drag=[e.clientX,e.clientY];draw();};
canvas.onpointerup=()=>drag=null;canvas.onpointercancel=()=>drag=null;
canvas.onwheel=e=>{e.preventDefault();zoom=Math.max(.3,Math.min(3,zoom*Math.exp(-e.deltaY*.001)));draw();};draw();
'''
