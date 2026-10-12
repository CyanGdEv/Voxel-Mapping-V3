"""Source-mesh building adapters for the normal park compiler and chunk exporter."""
import copy
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from .model import EvidenceMissing
from .registration import apply_registration,require_accepted_review

VERSION='local-building-park-v2'


def canonical_hash(model):
    return hashlib.sha256(json.dumps(model,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def rotate_model(model,angle):
    result=copy.deepcopy(model);r=math.radians(angle);c,s=math.cos(r),math.sin(r)
    def point(p):return [c*p[0]-s*p[1],s*p[0]+c*p[1],p[2]]
    for key in ('wall_mesh','roof_mesh','projection_mesh'):
        if key in result:result[key]['vertices']=[point(p) for p in result[key]['vertices']]
    result['outer_wall_base_outline']=[point(p) for p in result['outer_wall_base_outline']]
    for opening in result['opening_base_segments']:opening['endpoints']=[point(p) for p in opening['endpoints']]
    return result


def local_building(feature,geom,ctx):
    if geom.geom_type!='Point':raise EvidenceMissing('Local building requires registered anchor')
    if feature.value('assembly_identity_verified',ctx.sources,ctx.allow_estimates) != 'accepted':
        raise EvidenceMissing('Proposed local assembly has not been verified against the park building')
    placement=ctx.sources[feature.geometry_source]
    review=placement.metadata.get('horizontal_registration_review')
    try:require_accepted_review(review)
    except ValueError as error:raise EvidenceMissing(str(error)) from error
    matrix=np.asarray(review['matrix'],dtype=float)
    if matrix.shape!=(2,2) or not np.allclose(matrix.T@matrix,np.eye(2),atol=1e-8) or np.linalg.det(matrix)<0:
        raise EvidenceMissing('1:1 building placement requires rotation without stretch or reflection')
    anchor=apply_registration([[0,0]],review)[0]
    if math.dist(anchor,[geom.x,geom.y])>1e-7:raise EvidenceMissing('Building anchor differs from reviewed local-origin transform')
    model=feature.value('local_model',ctx.sources,ctx.allow_estimates)
    profile=ctx.sources[feature.parameters['local_model']['source']]
    if canonical_hash(model)!=profile.metadata.get('canonical_model_sha256'):
        raise EvidenceMissing('Pinned local building model changed')
    base=feature.value('base_elevation_m',ctx.sources,ctx.allow_estimates)
    elevation=ctx.sources[feature.parameters['base_elevation_m']['source']]
    if elevation.vertical_datum!=ctx.vertical_datum or not ctx.vertical_datum:
        raise EvidenceMissing('Building floor datum differs from park terrain')
    if isinstance(base,bool) or not isinstance(base,(int,float)) or not math.isfinite(base) or abs(base)>10000:
        raise EvidenceMissing('Finite bounded floor elevation required')
    # Rasterize the rotated source mesh, rather than rotating the completed
    # voxel lattice. Snap the assembly origin/floor to the nearest metre,
    # retaining the original placement and bounded grid offsets in the feed.
    angle=math.degrees(math.atan2(matrix[1,0],matrix[0,0]))
    from ..shop_slabs import assemble
    from ..shop_wall_details import decorate
    rotated=rotate_model(model,angle);cells,_=assemble(rotated);cells,_=decorate(rotated,cells)
    if 'foundation_mode' in feature.parameters:
        if feature.value('foundation_mode',ctx.sources,ctx.allow_estimates) != 'level_pad':
            raise EvidenceMissing('Unsupported estimated building foundation mode')
        from ..shop_foundations import level_pad
        try:foundations,_=level_pad(rotated,cells,anchor,base,ctx.ground)
        except ValueError as error:raise EvidenceMissing(str(error)) from error
        cells={**foundations,**cells}
    # Every emitted block must remain inside the independently checked domain.
    from .registration import registration_domain
    from shapely.geometry import box
    domain=registration_domain(review)
    for (x,y,z),material in sorted(cells.items()):
        wx,wz=x+round(anchor[0]),z+round(anchor[1])
        if not domain.buffer(1e-7).covers(box(wx,wz,wx+1,wz+1)):
            raise EvidenceMissing('Building extends outside validated registration domain')
        terrain=ctx.ground(wx+.5,wz+.5)
        if terrain is None or not math.isfinite(terrain):raise EvidenceMissing('Building lacks park terrain coverage')
        if y+round(base)<=math.floor(terrain):raise EvidenceMissing('Building intersects terrain; floor/grading review required')
        # Park rows use northing-positive Z; native export negates Z.
        if material.endswith('_trapdoor_north'):material=material.removesuffix('_north')+'_south'
        elif material.endswith('_trapdoor_south'):material=material.removesuffix('_south')+'_north'
        yield (wx,y+round(base),wz),material


def prepare_feed(entries,manifest,resolve,output):
    """Pin assets and create normal Feature JSONL records; no placement promotion."""
    if not isinstance(entries,list) or len(entries)>1000:raise ValueError('Bounded local building list required')
    sources={s['id']:s for s in manifest['sources']};records=[];contracts=[]
    for entry in entries:
        raw=resolve(entry['model']).read_bytes();digest=hashlib.sha256(raw).hexdigest()
        if digest!=entry['model_sha256']:raise ValueError('Local building model checksum mismatch')
        model=json.loads(raw);placement_raw=resolve(entry['placement']).read_bytes();placement=json.loads(placement_raw)
        profile=sources.get(placement['profile_source'])
        if profile is None or profile.get('sha256')!=digest or profile.get('metadata',{}).get('canonical_model_sha256')!=canonical_hash(model):
            raise ValueError('Manifest profile source must pin raw and canonical model hashes')
        if any(sources[k]['crs']!=manifest['crs'] for k in (placement['geometry_source'],placement['elevation_source'])):
            raise ValueError('Building placement source CRS differs from park manifest')
        records.append({'id':placement['id'],'family':'local_building','geometry':{'type':'Point','coordinates':placement['anchor_xy']},
            'geometry_source':placement['geometry_source'],'parameters':{
                'local_model':{'value':model,'source':placement['profile_source'],'status':'estimated'},
                'assembly_identity_verified':{'value':'accepted' if placement.get('assembly_identity_verified') is True else 'unverified','source':placement['geometry_source'],'status':'documented'},
                'base_elevation_m':{'value':placement['base_elevation_m'],'source':placement['elevation_source'],'status':placement.get('floor_status','estimated')}},
            'metadata':{'adapter_version':VERSION,'model_sha256':digest,'placement_sha256':hashlib.sha256(placement_raw).hexdigest(),
                        'style':'slabs-fences-trapdoors-1to1','source_placement_eligible':model.get('world_placement_eligible'),
                        'grid_quantization':{'rule':'nearest metre origin/floor; at most 0.5 m per axis',
                            'anchor_offset_xy':[round(v)-v for v in placement['anchor_xy']],
                            'floor_offset_m':round(placement['base_elevation_m'])-placement['base_elevation_m']}}})
        if placement.get('foundation_mode') is not None:
            records[-1]['parameters']['foundation_mode']={'value':placement['foundation_mode'],'source':placement['profile_source'],'status':'estimated'}
        contracts.append(records[-1]['metadata'])
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    data=''.join(json.dumps(r,sort_keys=True)+'\n' for r in records).encode()
    temporary=output.with_suffix('.partial');temporary.write_bytes(data);temporary.replace(output)
    return {'version':VERSION,'feature_count':len(records),'assets':contracts,'output_sha256':hashlib.sha256(data).hexdigest()}
