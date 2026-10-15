"""Competing material separators made only by undoing source-stroke suppression."""
import hashlib
import math

import numpy as np
from scipy import ndimage
from shapely.geometry import Point,shape

from .building_spec import digest
from .contrast_boundaries import audit
from .raster_faces import ZOOM,THRESHOLDS

VERSION='source-stroke-restoration-v2'
MAX_TRIALS=128
MAX_PIXEL_WORK=768000000


def review(prepared,anchors,*,max_trials=MAX_TRIALS,max_pixel_work=MAX_PIXEL_WORK):
    """Keep every qualifying single-stroke restoration, with no physical selection."""
    if type(max_trials) is not int or not 1<=max_trials<=MAX_TRIALS:
        raise ValueError('Bounded restoration trial count required')
    if type(max_pixel_work) is not int or not 1<=max_pixel_work<=MAX_PIXEL_WORK:
        raise ValueError('Bounded restoration pixel work required')
    if not 2<=len(anchors)<=32:raise ValueError('Bounded conflicting material anchors required')
    windows,masks=prepared;crop,variants,receipt=windows
    if len(variants)!=2 or len(masks)!=2 or len(receipt['variants'])!=2 or crop.ndim!=2 or crop.dtype!=np.uint8 or crop.size>2000000:
        raise ValueError('Two bounded source contrast variants required')
    origin=receipt['origin_atlas_pixels']
    for anchor in anchors:
        point=anchor['target_page_point']
        if len(point)!=2 or not all(math.isfinite(float(v)) for v in point):
            raise ValueError('Finite original anchor point required')
    boxes=sorted({tuple(b) for variant in receipt['variants'] for family in variant['families']
                  for b in family['stroke_boxes_crop_pixels'][1:-1]})
    result={'version':VERSION,'artwork_review_window_id':receipt['artwork_review_window_id'],
        'source_crop_sha256':receipt['source_crop_sha256'],'coordinate_frame':'unrotated_mupdf_page_points_y_down',
        'anchors':[{'number':a['number'],'target_page_point':a['target_page_point']} for a in anchors],
        'trial_count':len(boxes),'trials':[],'alternatives':[],'pixel_work':0,'geometry_coordinate_count':0,
        'source_contrast_recipe_sha256':digest(receipt),
        'selected_physical_boundary_id':None,'accepted_feature':False,'world_geometry_additions':0,
        'recipe':'restore original contrast pixels inside one detected interior stroke box in both gains; no new ink',
        'complete_facade_identity_verified':False}
    def withheld(reason):
        return {**result,'status':'restoration_budget_withheld','reason':reason,'trials':[],'alternatives':[]}
    if len(boxes)>max_trials:return withheld('stroke_trial_count_budget')
    def charge(amount):
        result['pixel_work']+=amount
        if result['pixel_work']>max_pixel_work:raise OverflowError
    try:
        local_max=ndimage.maximum_filter(crop,size=9).astype('int16');originals=[]
        for variant in receipt['variants']:
            original=np.clip(255-variant['gain']*(local_max-crop.astype('int16')),0,255).astype('uint8')
            if hashlib.sha256(original.tobytes()).hexdigest()!=variant['contrast_pixels_sha256']:
                raise ValueError('Original contrast recipe checksum mismatch')
            originals.append(original)
        for box in boxes:
            x0,y0,x1,y1=box
            if not 0<=x0<x1<=crop.shape[1] or not 0<=y0<y1<=crop.shape[0]:
                raise ValueError('Source stroke box outside original crop')
            restored=[];remaining=[];recipes=[]
            for image,mask,original,recipe in zip(variants,masks,originals,receipt['variants']):
                charge(crop.size)
                changed=image.copy();changed[y0:y1,x0:x1]=original[y0:y1,x0:x1]
                kept=mask.copy();kept[y0:y1,x0:x1]=False
                restored.append(changed);remaining.append(kept)
                recipes.append({**recipe,'edited_pixels':int(kept.sum())})
            trial={'restored_stroke_box_crop_pixels':list(box),'status':'no_supported_material_separation',
                'source_stroke_references':[{'variant_index':vi,'family_index':fi,'stroke_index':si}
                    for vi,v in enumerate(receipt['variants']) for fi,f in enumerate(v['families'])
                    for si,b in enumerate(f['stroke_boxes_crop_pixels']) if tuple(b)==box]}
            result['trials'].append(trial)
            # Cheap necessary condition only. Full four-threshold/two-gain
            # boundary audit and all-anchor exclusion remain mandatory below.
            charge(crop.size);labels,_=ndimage.label(restored[0]>=max(THRESHOLDS))
            identities=[]
            for anchor in anchors:
                x,y=[int(math.floor(anchor['target_page_point'][i]*ZOOM))-origin[i] for i in (0,1)]
                identities.append(int(labels[y,x]) if 0<=y<crop.shape[0] and 0<=x<crop.shape[1] else 0)
            if not all(identities) or any(identities[i]==identities[j] and anchors[i]['number']!=anchors[j]['number']
                for i in range(len(anchors)) for j in range(i)):continue
            checks=[]
            for anchor in anchors:
                charge(16*crop.size)
                checks.append(audit(((crop,restored,{**receipt,'variants':recipes}),remaining),anchor['target_page_point']))
            trial['boundary_statuses']=[c['status'] for c in checks]
            if any(c['status']!='unverified_contrast_boundary_candidate' for c in checks):continue
            if any(shape(check['geometry']).covers(Point(other['target_page_point']))
                for anchor,check in zip(anchors,checks) for other in anchors if other['number']!=anchor['number']):continue
            result['geometry_coordinate_count']+=sum(len(ring) for c in checks for ring in c['geometry']['coordinates'])
            if result['geometry_coordinate_count']>100000:return withheld('restoration_geometry_budget')
            trial['status']='competing_source_stroke_separator_candidate'
            alternative={'restored_stroke_box_crop_pixels':list(box),
                'source_stroke_references':trial['source_stroke_references'],
                'periodic_source_witnesses':[{'variant_index':ref['variant_index'],
                    'family_index':ref['family_index'],'stroke_index':ref['stroke_index'],
                    'axis':receipt['variants'][ref['variant_index']]['families'][ref['family_index']]['axis'],
                    'stroke_count':receipt['variants'][ref['variant_index']]['families'][ref['family_index']]['stroke_count'],
                    'spacing_pixels_candidate':receipt['variants'][ref['variant_index']]['families'][ref['family_index']]['spacing_pixels_candidate'],
                    'neighbor_stroke_boxes_crop_pixels':receipt['variants'][ref['variant_index']]['families'][ref['family_index']]['stroke_boxes_crop_pixels'][max(0,ref['stroke_index']-1):ref['stroke_index']+2],
                    'physical_hatch_identity_verified':False} for ref in trial['source_stroke_references']],
                'restored_stroke_box_page_points':[(x0+origin[0])/ZOOM,(y0+origin[1])/ZOOM,
                    (x1+origin[0])/ZOOM,(y1+origin[1])/ZOOM],
                'regions':[{'number':a['number'],'target_page_point':a['target_page_point'],'boundary_review':c}
                    for a,c in zip(anchors,checks)],'physical_boundary_identity_verified':False,
                'complete_facade_identity_verified':False}
            alternative['id']=digest(alternative);result['alternatives'].append(alternative)
        result['status']='competing_source_stroke_separator_hypotheses' if result['alternatives'] else 'withheld_no_supported_source_stroke_separator'
        return result
    except OverflowError:return withheld('restoration_pixel_work_budget')
