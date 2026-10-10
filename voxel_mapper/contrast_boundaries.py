"""Local-contrast stroke proposals with unmodified-source outline/shadow checks.

This is an additional evidence channel, not a relaxation of the raw gray or
periodic-threshold screens. Contrast-normalized pixels never establish datum,
component, opening or drawing-view identity.
"""
import hashlib
import numpy as np
from scipy import ndimage
from .raster_boundaries import crop_window,stroke_families,audit as boundary_audit

VERSION='local-contrast-boundaries-v1'
GAINS=(2,3)


def prepare(gray,group):
    crop,origin=crop_window(gray,group)
    local_max=ndimage.maximum_filter(crop,size=9).astype('int16')
    variants=[];masks=[];recipes=[]
    for gain in GAINS:
        contrast=np.clip(255-gain*(local_max-crop.astype('int16')),0,255).astype('uint8')
        digest=hashlib.sha256(contrast.tobytes()).hexdigest()
        mask,families=stroke_families(contrast,224)
        contrast[mask]=255
        variants.append(contrast);masks.append(mask)
        recipes.append({'gain':gain,'line_threshold':224,'families':families,'edited_pixels':int(mask.sum()),
                        'contrast_pixels_sha256':digest,'edit_mask_sha256':hashlib.sha256(mask.tobytes()).hexdigest()})
    receipt={'version':VERSION,'artwork_review_window_id':group['id'],'origin_atlas_pixels':list(origin),
             'crop_shape_pixels':list(crop.shape),'source_crop_sha256':hashlib.sha256(crop.tobytes()).hexdigest(),
             'local_max_filter_size_pixels':9,'variants':recipes,'source_boundary_identity_verified':False}
    return (crop,variants,receipt),masks


def audit(prepared,point):
    windows,masks=prepared
    result=boundary_audit(windows,point,edit_masks=masks)
    result['version']=VERSION
    result['evidence_channel']='local-contrast; original gray and periodic reviews retained separately'
    if result['status']=='unverified_hatch_suppressed_boundary_candidate':
        result['status']='unverified_contrast_boundary_candidate'
    return result


def check_material_regions(records):
    """Withhold a region containing differently numbered source material anchors."""
    from shapely.geometry import shape,Point
    for record in records:
        result=record.get('raster_contrast_boundary_review',{})
        if result.get('status')!='unverified_contrast_boundary_candidate':continue
        polygon=shape(result['geometry'])
        inside=[other for other in records if other.get('glyph_screen_status')=='raster_consistent_candidate'
                and other.get('document_sha256')==record.get('document_sha256')
                and other.get('page')==record.get('page') and other.get('target_page_point')
                and polygon.covers(Point(other['target_page_point']))]
        result['containing_material_anchor_numbers']=sorted({other['number'] for other in inside})
        if len(result['containing_material_anchor_numbers'])>1:
            result['status']='withheld_contrast_mixed_material_anchors'
            result['rejected_region_geometry']=result.pop('geometry')
            result['reason']='Suppression joins source anchors for different material regions.'
