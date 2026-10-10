"""Periodic stroke hypotheses, conservative hatch suppression and edge evidence.

Edits produce unverified candidates only. Repeated fence rails, joints and
shadows can resemble hatches; none of these hypotheses certifies a face.
"""
import hashlib
import numpy as np
from scipy import ndimage
from rasterio.features import rasterize
from affine import Affine
from .raster_faces import ZOOM, region_screen

VERSION = 'periodic-hatch-boundaries-v1'
LINE_THRESHOLDS = (208, 224)
MAX_WINDOW_PIXELS = 2000000


def stroke_families(gray, threshold):
    """Detect at least five thin parallel runs at approximately regular spacing.

    Opening is only a stroke detector. Endpoints and perpendicular long strokes
    are protected from suppression. The first/last line of every family remains.
    """
    dark = gray < threshold
    directions = [ndimage.binary_opening(dark, structure=np.ones((1,32),bool)),
                  ndimage.binary_opening(dark, structure=np.ones((32,1),bool))]
    families = []; edit = np.zeros(gray.shape, bool)
    for axis, lines in enumerate(directions):
        labels, count = ndimage.label(lines)
        if count > 50000: raise ValueError('Stroke component budget exceeded')
        strokes = []
        for identity, slices in enumerate(ndimage.find_objects(labels), 1):
            if slices is None: continue
            cross, along = (slices[0],slices[1]) if axis == 0 else (slices[1],slices[0])
            if cross.stop-cross.start > 4 or along.stop-along.start < 32: continue
            strokes.append({'label':identity,'slices':slices,'center':(cross.start+cross.stop)/2,
                            'start':along.start,'end':along.stop})
        if len(strokes) > 10000: raise ValueError('Thin stroke budget exceeded')
        strokes.sort(key=lambda s:(s['center'],s['start']))
        # Greedy disjoint runs are only hypotheses; ambiguous branches are not merged.
        used=set(); comparisons=0
        perpendicular=ndimage.binary_dilation(directions[1-axis],iterations=2)
        for i, first in enumerate(strokes):
            if i in used: continue
            chain=[i]; gaps=[]
            while True:
                previous=strokes[chain[-1]]; matches=[]
                for j in range(chain[-1]+1,len(strokes)):
                    comparisons+=1
                    if comparisons>200000:raise ValueError('Hatch neighbor comparison budget exceeded')
                    other=strokes[j];gap=other['center']-previous['center']
                    if gap>20:break
                    if j in used or gap<2:continue
                    overlap=max(0,min(previous['end'],other['end'])-max(previous['start'],other['start']))
                    lengths=[s['end']-s['start'] for s in (previous,other)]
                    if overlap/min(lengths)<.8 or min(lengths)/max(lengths)<.6:continue
                    if gaps and abs(gap-float(np.median(gaps)))>max(1,.2*float(np.median(gaps))):continue
                    matches.append(j)
                if not matches:break
                closest=min(strokes[j]['center']-previous['center'] for j in matches)
                matches=[j for j in matches if abs(strokes[j]['center']-previous['center']-closest)<.5]
                if len(matches)!=1:break
                j=matches[0];gaps.append(strokes[j]['center']-previous['center']);chain.append(j)
            if len(chain)<5:continue
            used.update(chain)
            family=np.zeros(gray.shape,bool);boxes=[]
            for j in chain:
                stroke=strokes[j];ys,xs=stroke['slices'];boxes.append([xs.start,ys.start,xs.stop,ys.stop])
            for j in chain[1:-1]:
                stroke=strokes[j];ys,xs=stroke['slices']
                # Protect six source pixels at each end rather than extrapolating an outline.
                inside=(slice(ys.start,ys.stop),slice(xs.start+6,xs.stop-6)) if axis==0 else (slice(ys.start+6,ys.stop-6),slice(xs.start,xs.stop))
                family[inside]=labels[inside]==stroke['label']
            family &= ~perpendicular
            edit |= family
            families.append({'axis':'horizontal' if axis==0 else 'vertical','stroke_count':len(chain),
                             'spacing_pixels_candidate':float(np.median(gaps)), 'stroke_boxes_crop_pixels':boxes,
                             'edited_pixel_count':int(family.sum()),'hatch_identity_verified':False})
            if len(families)>256:raise ValueError('Hatch family budget exceeded')
    return edit, families


def prepare(gray, group):
    bbox=group['bbox_page_points'];h,w=gray.shape
    x0=max(0,int(np.floor(bbox[0]*ZOOM))-16);y0=max(0,int(np.floor(bbox[1]*ZOOM))-16)
    x1=min(w,int(np.ceil(bbox[2]*ZOOM))+16);y1=min(h,int(np.ceil(bbox[3]*ZOOM))+16)
    crop=gray[y0:y1,x0:x1]
    if not crop.size or crop.size>MAX_WINDOW_PIXELS or max(crop.shape)>4096:raise ValueError('Hatch review window budget exceeded')
    variants=[];receipts=[]
    for threshold in LINE_THRESHOLDS:
        mask,families=stroke_families(crop,threshold)
        filtered=crop.copy();filtered[mask]=255
        variants.append(filtered)
        receipts.append({'line_threshold':threshold,'families':families,'edited_pixels':int(mask.sum()),
                         'edit_mask_sha256':hashlib.sha256(mask.tobytes()).hexdigest()})
    return crop,variants,{'version':VERSION,'artwork_review_window_id':group['id'],
                         'origin_atlas_pixels':[x0,y0],'crop_shape_pixels':list(crop.shape),
                         'source_crop_sha256':hashlib.sha256(crop.tobytes()).hexdigest(),
                         'variants':receipts,'source_boundary_identity_verified':False}


def audit(prepared, point):
    crop,variants,receipt=prepared;x0,y0=receipt['origin_atlas_pixels']
    seed=(int(np.floor(point[0]*ZOOM))-x0,int(np.floor(point[1]*ZOOM))-y0)
    result={'version':VERSION,'accepted_feature':False,'world_geometry_additions':0,
            'outline_identity_verified':False,'opening_identity_verified':False,'view_identity_verified':False,
            'artwork_review_window_id':receipt['artwork_review_window_id'],
            'status':'withheld_no_periodic_hatch_hypothesis'}
    if any(not r['edited_pixels'] for r in receipt['variants']):return result
    candidates=[region_screen(filtered,seed,origin=(x0,y0)) for filtered in variants]
    result['suppression_region_statuses']=[c['status'] for c in candidates]
    result['suppression_region_checks']=[{key:value for key,value in c.items() if key in
        ('status','threshold_receipts','threshold_iou','review_window_page_points')} for c in candidates]
    if any(c['status']!='unverified_stable_raster_region_candidate' for c in candidates):
        result['status']='withheld_hatch_suppression_region';return result
    from shapely.geometry import shape, Polygon
    if any(not shape(c['geometry']).is_valid for c in candidates):
        result['status']='withheld_invalid_boundary_polygon';return result
    transform=Affine(1/ZOOM,0,x0/ZOOM,0,1/ZOOM,y0/ZOOM)
    masks=[rasterize([(c['geometry'],1)],out_shape=crop.shape,transform=transform,dtype='uint8').astype(bool) for c in candidates]
    union=masks[0]|masks[1]; intersection=masks[0]&masks[1]
    iou=float(intersection.sum()/union.sum());result['suppression_variant_iou']=iou
    if iou<.98:result['status']='withheld_hatch_suppression_disagreement';return result
    # Outline evidence must exist in the unedited artwork; edits cannot invent closure.
    boundary=masks[0] & ~ndimage.binary_erosion(masks[0])
    support=ndimage.binary_dilation(crop<224,iterations=2)
    result['original_ink_boundary_support']=float((boundary & support).sum()/boundary.sum())
    protected=np.zeros(crop.shape,bool)
    for variant in receipt['variants']:
        for family in variant['families']:
            for box in (family['stroke_boxes_crop_pixels'][0],family['stroke_boxes_crop_pixels'][-1]):
                bx0,by0,bx1,by1=box;protected[by0:by1,bx0:bx1]=True
    result['periodic_stroke_boundary_fraction_candidate']=float((boundary & ndimage.binary_dilation(protected,iterations=2)).sum()/boundary.sum())
    result['extent_completeness_verified']=False
    result['extent_ambiguity']='boundary_near_periodic_strokes' if result['periodic_stroke_boundary_fraction_candidate']>.02 else 'physical_extent_unverified'
    # Flat dark areas may be shadows, coatings or ground. Keep their semantic ambiguity explicit.
    removed=(variants[0]!=crop)|(variants[1]!=crop)
    dark_flat=(crop<208) & ~ndimage.binary_dilation((crop<128)|removed,iterations=2)
    result['dark_fill_fraction_candidate']=float((masks[0]&dark_flat).sum()/masks[0].sum())
    if result['original_ink_boundary_support']<.98:
        result['status']='withheld_unsupported_source_outline';return result
    if result['dark_fill_fraction_candidate']>.1:
        result['status']='withheld_shadow_or_dark_fill_ambiguity';return result
    if len(candidates[0]['geometry']['coordinates'])!=len(candidates[1]['geometry']['coordinates']):
        result['status']='withheld_opening_topology_disagreement';return result
    holes=[[Polygon(ring) for ring in c['geometry']['coordinates'][1:]] for c in candidates]
    for hole in holes[0]:
        matches=[other for other in holes[1] if hole.intersection(other).area/hole.union(other).area>=.98]
        if len(matches)!=1:
            result['status']='withheld_opening_geometry_disagreement';return result
    result.update(status='unverified_hatch_suppressed_boundary_candidate',geometry=candidates[0]['geometry'],
                  opening_count_candidate=len(candidates[0]['geometry']['coordinates'])-1,
                  limitations=['Periodic rails, joints and hatches are not semantically distinguished.',
                               'Shadow, clipping, drawing view and physical opening identities remain unverified.'])
    return result
