"""Bounded 2D courtyard extension, retaining every existing Wicker feature."""
from concurrent.futures import CancelledError
import hashlib
import json
import math
from pathlib import Path

from shapely.geometry import Polygon,Point,mapping,shape
from .building_spec import digest

VERSION='courtyard-plan-expansion-v1'
PROFILE_PATH=Path(__file__).with_name('data')/'mutiny-courtyard-expansion.json'
LIMITS={'max_features':32,'max_points':4096,'max_checks':200000,'max_new_cells':8192}


def profile():
    p=json.loads(PROFILE_PATH.read_text())
    if (p.get('version')!='mutiny-courtyard-source-profile-v1' or p.get('source_view_scale_denominator')!=100
            or p.get('source_raster_width')!=1800 or p.get('target_scale_denominator')!=250
            or p.get('physical_registration_verified') is not False):raise ValueError('Reviewed existing courtyard profile required')
    return p


def geometry(p=None):
    p=profile() if p is None else p;controls=p['controls'];unit=p['source_page_display_width_points']/p['source_raster_width']*100*.0254/72
    target_unit=250*.0254/72;first,second=[c for c in controls if c['use']=='fit']
    sx=(second['source_pixel'][0]-first['source_pixel'][0])*unit;sy=-(second['source_pixel'][1]-first['source_pixel'][1])*unit
    tx=(second['target_wicker_native'][0]-first['target_wicker_native'][0])*target_unit;ty=(second['target_wicker_native'][1]-first['target_wicker_native'][1])*target_unit
    angle=math.atan2(ty,tx)-math.atan2(sy,sx);co=math.cos(angle);si=math.sin(angle)
    def place(q):
        x=(q[0]-first['source_pixel'][0])*unit;y=-(q[1]-first['source_pixel'][1])*unit
        return [first['target_wicker_native'][0]*target_unit+co*x-si*y,first['target_wicker_native'][1]*target_unit+si*x+co*y]
    checks=[]
    for c in controls:
        x,y=place(c['source_pixel']);ex,ey=[v*target_unit for v in c['target_wicker_native']]
        checks.append({'id':c['id'],'use':c['use'],'residual_m':math.hypot(x-ex,y-ey)})
    if max(c['residual_m'] for c in checks)>.25:raise ValueError('Courtyard drawing correspondence changed')
    features=[];points=0
    if len(p['features'])>LIMITS['max_features']:raise ValueError('Courtyard feature budget exceeded')
    for row in p['features']:
        points+=len(row['pixel_ring'])
        if points>LIMITS['max_points']:raise ValueError('Courtyard source point budget exceeded')
        g=Polygon([place(q) for q in row['pixel_ring']])
        if not g.is_valid or g.is_empty:raise ValueError('Valid complete courtyard polygon required')
        features.append({'key':row['key'],'role':row['role'],'material':row['material'],'geometry_nominal_local':json.loads(json.dumps(mapping(g)))})
    return features,{'rotation_degrees':math.degrees(angle),'source_metres_per_pixel':unit,'printed_scale_retained':True,
        'control_checks':checks,'independent_registration_verified':False,'pose_scope':'courtyard source-local preview only'}


def verify_source(path):
    import pymupdf
    p=profile();raw=Path(path).read_bytes()
    if len(raw)>24000000 or hashlib.sha256(raw).hexdigest()!=p['source_pdf_sha256']:raise ValueError('Pinned existing courtyard PDF required')
    with pymupdf.open(stream=raw,filetype='pdf') as d:
        page=d[0];text=''.join(page.get_text().split())
        if "GroundFloorPlan'asexisting'" not in text or page.rect.width!=2384:raise ValueError('Reviewed existing ground-floor view required')
        pix=page.get_pixmap(matrix=pymupdf.Matrix(1800/page.rect.width,1800/page.rect.width))
        if hashlib.sha256(pix.samples).hexdigest()!=p['source_render_samples_sha256']:raise ValueError('Courtyard source raster differs from reviewed trace')
    return {'source_pdf_sha256':p['source_pdf_sha256'],'source_render_samples_sha256':p['source_render_samples_sha256'],'source_verified':True}


def request(source_proof,baseline_pins,layout):
    p=profile();features,pose=geometry(p)
    value={'version':VERSION,'profile_sha256':digest(p),'source_proof':source_proof,'baseline_source_pins':baseline_pins,
        'target_layout_sha256':digest(layout),'features':features,'pose':pose,'world_placement_eligible':False,'model_weights_updated':False}
    validate(value,baseline_pins,layout);return value


def validate(value,baseline_pins,layout):
    p=profile();features,pose=geometry(p)
    if (not isinstance(value,dict) or value.get('version')!=VERSION or value.get('profile_sha256')!=digest(p)
            or value.get('baseline_source_pins')!=baseline_pins or value.get('target_layout_sha256')!=digest(layout)
            or layout.get('document_sha256')!=p['target_document_sha256'] or value.get('features')!=json.loads(json.dumps(features))
            or value.get('pose')!=pose or value.get('world_placement_eligible') is not False or value.get('model_weights_updated') is not False
            or value.get('source_proof')!={'source_pdf_sha256':p['source_pdf_sha256'],'source_render_samples_sha256':p['source_render_samples_sha256'],'source_verified':True}):
        raise ValueError('Pinned source-local courtyard expansion required')
    target=[r for r in layout['candidates'] if r['id'].startswith(p['target_tavern_candidate_id']) and r['role']=='building']
    if len(target)!=1:raise ValueError('Retained Wicker Tavern correspondence absent')
    boundary=shape(target[0]['geometry_pdf_native']).boundary
    for c in p['controls']:
        if boundary.distance(Point(c['target_wicker_native']))>1e-5:raise ValueError('Wicker Tavern control changed')
    return value


def bounds(value):
    boxes=[shape(r['geometry_nominal_local']).bounds for r in value['features']]
    return [math.floor(min(b[0] for b in boxes))-4,math.floor(min(b[1] for b in boxes))-4,
            math.ceil(max(b[2] for b in boxes))+4,math.ceil(max(b[3] for b in boxes))+4]


def apply(value,ground,rocks,*,cancelled=lambda:False,max_checks=None):
    limit=LIMITS['max_checks'] if max_checks is None else max_checks
    if type(limit) is not int or not 1<=limit<=LIMITS['max_checks']:raise ValueError('Lower-only courtyard work budget required')
    preserved=dict(ground);protected=set(ground)|set(rocks);candidates={};priority={};checks=0;source_counts={};withheld={}
    order={'paving':0,'building_boundary':1,'passage':2}
    for row in value['features']:
        g=shape(row['geometry_nominal_local']);a,b,c,d=g.bounds;source_counts[row['key']]=0;withheld[row['key']]=0
        for x in range(math.floor(a),math.ceil(c)):
            if cancelled():raise CancelledError('Courtyard expansion cancelled')
            for z in range(math.floor(b),math.ceil(d)):
                checks+=1
                if checks>limit:raise ValueError('Courtyard sampling budget exceeded')
                q=Point(x+.5,z+.5)
                if not g.covers(q) or (row['role']=='building_boundary' and g.boundary.distance(q)>.85):continue
                key=x,z;source_counts[row['key']]+=1
                if key in protected:withheld[row['key']]+=1;continue
                if key not in priority or order[row['role']]>priority[key]:
                    candidates[key]={'material':row['material'],'role':row['role'],'feature_key':row['key']};priority[key]=order[row['role']]
                if len(candidates)>LIMITS['max_new_cells']:raise ValueError('Courtyard new-cell budget exceeded')
    if any(k in protected for k in candidates):raise ValueError('Courtyard overwrite of baseline feature')
    ground.update({k:r['material'] for k,r in candidates.items()})
    if any(ground[k]!=v for k,v in preserved.items()):raise ValueError('Wicker feature changed')
    counts={r['key']:0 for r in value['features']}
    for r in candidates.values():counts[r['feature_key']]+=1
    return candidates,{'profile_sha256':value['profile_sha256'],'source_pdf_sha256':value['source_proof']['source_pdf_sha256'],
        'mapped_wing_and_annex_sections':sum(r['role']=='building_boundary' for r in value['features']),
        'source_sample_cells':source_counts,'added_cells_by_feature':counts,'preserved_baseline_cells_by_feature':withheld,
        'added_cells':len(candidates),'sampling_checks':checks,'baseline_ground_feature_cells_preserved':len(preserved),
        'baseline_edging_columns_preserved':len(rocks),'baseline_features_preserved':True,'pose':value['pose'],
        'source_trace_basis':profile()['trace_basis'],'physical_registration_verified':False,'reconstructed_buildings':0}
