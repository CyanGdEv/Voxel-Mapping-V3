"""Relative alignment diagnostics and source-pinned boundary review windows."""
import argparse
import base64
from concurrent.futures import CancelledError
from io import BytesIO
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from pyproj import Geod, Transformer
from rasterio.features import rasterize
from rasterio.transform import from_bounds
from scipy import ndimage
from scipy.spatial import cKDTree
from shapely.geometry import box, mapping, shape
from shapely.ops import transform

from . import mapping_layers as layers
from .aerial_material_research import _lab
from .desktop_memory import digest
from .generation_cycles import atomic_json, file_hash

VERSION = 'boundary-alignment-review-v1'
REASONS = {
    'path_prediction_miss': 'A labelled narrow path is missing from the park-held-out prediction.',
    'grass_predicted_paving': 'The prediction crosses a labelled grass separator near paving.',
    'path_building_overlap': 'Labelled paving overlaps a generalised OS building and elevated LiDAR returns.',
    'path_canopy_check': 'Path evidence and overhead vegetation coincide; check ground and canopy separately.',
    'water_map_disagreement': 'A known surface label and mapped water disagree; check dates, alignment and generalisation.',
    'unknown_path_margin': 'Unknown pixels beside a labelled path have similar RGB and low valid LiDAR height.',
    'inferred_tree_path': 'An established path footprint was inferred under canopy; it is not observed ground truth.',
}


def ground_sampling(extent, size):
    """Local ground sampling for distances, not a claim about source accuracy."""
    convert = Transformer.from_crs(3857, 4326, always_xy=True)
    x, y = (extent[0]+extent[2])/2, (extent[1]+extent[3])/2
    origin = convert.transform(x, y)
    east = convert.transform(x+(extent[2]-extent[0])/size[0], y)
    north = convert.transform(x, y+(extent[3]-extent[1])/size[1])
    geod = Geod(ellps='WGS84')
    return [abs(geod.inv(*origin, *east)[2]), abs(geod.inv(*origin, *north)[2])]


def translation_review(source, reference, sampling):
    """Fit only spatial training cells; report residuals on untouched check cells."""
    source = np.asarray(source, float); reference = np.asarray(reference, float)
    if source.shape!=reference.shape or source.ndim!=2 or source.shape[1]!=2 or len(source)>5000 or not np.isfinite(source).all() or not np.isfinite(reference).all():
        raise ValueError('Bounded finite correspondence pairs required')
    scale = np.asarray(sampling, float)
    if scale.shape!=(2,) or not np.isfinite(scale).all() or (scale<=0).any():
        raise ValueError('Positive ground sampling required')
    cells = np.floor(reference*scale/24).astype(int)
    # Four-metre guard separates feature centres across cell edges. Large SIFT
    # descriptors may still share context; these are not independent controls.
    within = np.mod(reference*scale, 24)
    allowed = ((within>=4)&(within<=20)).all(axis=1)
    check = allowed&((cells[:, 0]+cells[:, 1])%3==0)
    fit = allowed&~check
    result = {'status': 'insufficient_spatial_support', 'matches': len(source),
              'fit_matches': int(fit.sum()), 'check_matches': int(check.sum()),
              'fit_and_check_guard_m': 4, 'cell_size_m': 24,
              'registration_verified': False, 'absolute_accuracy_established': False,
              'automatic_transform_applied': False,
              'descriptor_support_independence_established': False,
              'points': [{'source_xy': s.tolist(), 'reference_xy': r.tolist(),
                          'role': 'check' if c else 'fit' if f else 'guard_excluded'}
                         for s, r, c, f in zip(source, reference, check, fit)]}
    if fit.sum()<12 or check.sum()<8 or len(np.unique(cells[fit], axis=0))<3 or len(np.unique(cells[check], axis=0))<2:
        return result
    delta = reference-source
    tree = cKDTree(delta[fit]*scale)
    counts = tree.query_ball_point(delta[fit]*scale, 1.5, return_length=True)
    mode = tree.query_ball_point((delta[fit]*scale)[int(np.argmax(counts))], 1.5)
    shift = np.median(delta[fit][mode], axis=0)
    fit_error = np.linalg.norm((delta[fit]-shift)*scale, axis=1)
    inliers = fit_error<=1.5
    if inliers.sum()<12:
        return result
    shift = np.median(delta[fit][inliers], axis=0)
    check_before = np.linalg.norm(delta[check]*scale, axis=1)
    check_after = np.linalg.norm((delta[check]-shift)*scale, axis=1)
    acceptable = bool(np.median(check_after)<=1 and np.percentile(check_after, 95)<=2 and np.linalg.norm(shift*scale)<=30)
    result.update(status='relative_translation_supported' if acceptable else 'relative_fit_requires_review',
        fit_inliers=int(inliers.sum()), shift_source_to_reference_pixels=shift.tolist(),
        shift_east_north_ground_m=[float(shift[0]*scale[0]), float(-shift[1]*scale[1])],
        check_before_p50_m=float(np.median(check_before)), check_after_p50_m=float(np.median(check_after)),
        check_after_p95_m=float(np.percentile(check_after, 95)),
        physical_control_points=0, check_scope='Spatially separated image correspondences, not independent surveyed controls')
    return result


def match_images(source, reference, sampling, stable_mask=None):
    try:
        import cv2
    except ImportError:
        return {'status': 'optional_opencv_unavailable', 'registration_verified': False,
                'automatic_transform_applied': False, 'points': []}
    cv2.setNumThreads(2)
    # Compare at about the reported optical source scale, rather than treating
    # every fine exported pixel as a separate observation.
    factor = min(1., min(sampling)/.5)
    size = tuple(max(32, round(v*factor)) for v in reference.size)
    sift = cv2.SIFT_create(nfeatures=4000, contrastThreshold=.02)
    descriptors = []
    for index, image in enumerate((source, reference)):
        gray = cv2.cvtColor(np.array(image.convert('RGB')), cv2.COLOR_RGB2GRAY)
        gray = cv2.resize(gray, size, interpolation=cv2.INTER_AREA)
        mask = cv2.resize(stable_mask.astype(np.uint8)*255, size, interpolation=cv2.INTER_NEAREST) if index==1 and stable_mask is not None else None
        descriptors.append(sift.detectAndCompute(gray, mask))
    (sk, sd), (rk, rd) = descriptors
    if sd is None or rd is None or len(sd)<2 or len(rd)<2:
        return {'status': 'insufficient_image_features', 'registration_verified': False,
                'automatic_transform_applied': False, 'points': []}
    matcher = cv2.BFMatcher()
    forward = {a.queryIdx: a.trainIdx for a, b in matcher.knnMatch(sd, rd, k=2) if a.distance<.78*b.distance}
    reverse = {a.queryIdx: a.trainIdx for a, b in matcher.knnMatch(rd, sd, k=2) if a.distance<.78*b.distance}
    inverse = np.array(reference.size)/size
    pairs = [(np.array(sk[i].pt)*inverse, np.array(rk[j].pt)*inverse)
             for i, j in sorted(forward.items()) if reverse.get(j)==i]
    if not pairs:
        return {'status': 'insufficient_image_features', 'registration_verified': False,
                'automatic_transform_applied': False, 'points': []}
    return {**translation_review(np.array([p[0] for p in pairs]), np.array([p[1] for p in pairs]), sampling),
            'opencv_version': cv2.__version__, 'comparison_size': list(size),
            'method': 'Mutual SIFT ratio matches near mapped buildings; robust translation and spatial fit/check groups',
            'reference_candidate_scope': 'Within six ground metres of generalised OS buildings, excluding green-coloured pixels; not identified surveyed corners'}


def source_mask(root, area, identity):
    row = next((r for r in area['layers'] if r['id']==identity and r['status']=='ready'), None)
    mask = np.zeros((area['size'][1], area['size'][0]), bool)
    if row is None:
        return mask, {'available': False}
    relative = Path(row['source_file'])
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Retained local source path required')
    path = root/relative if relative.parts[0]=='imports' else root/area['id']/relative
    if file_hash(path)!=row['source_file_sha256']:
        raise ValueError('Comparison vector source changed')
    collection = layers._read(path)
    project = Transformer.from_crs(4326 if identity=='os_openmap' else 3857, 3857, always_xy=True)
    geometries = []
    for feature in collection['features']:
        g = shape(feature['geometry'])
        if not g.is_valid:
            raise ValueError('Valid retained polygon geometry required')
        if g.geom_type in ('Polygon', 'MultiPolygon'):
            geometries.append((mapping(transform(project.transform, g)), 1))
    if geometries:
        mask = rasterize(geometries, out_shape=mask.shape, transform=from_bounds(*area['extent_epsg3857'], *area['size']), fill=0).astype(bool)
    return mask, {'available': True, 'source_sha256': row['source_file_sha256'],
                  'independence_group': 'ordnance-survey', 'geometry_verified': False}


def disagreement_masks(rgb, ground, canopy, fields, prediction, buildings, water, sampling, inferred=None):
    shape_ = ground.shape
    if (ground.ndim!=2 or ground.size>1048576 or rgb.shape!=(*shape_, 3) or canopy.shape!=shape_ or fields.shape!=(*shape_, 4)
            or prediction.shape!=shape_ or buildings.shape!=shape_ or water.shape!=shape_ or not np.isfinite(fields).all()):
        raise ValueError('Matching bounded review grids required')
    if not np.isin(ground, [0, 1, 2, 3, 255]).all() or not np.isin(canopy, [0, 1, 255]).all() or not np.isin(prediction, [0, 1, 2, 3, 255]).all():
        raise ValueError('Known surface/canopy classes required')
    gx, gy = sampling
    valid = fields[:, :, 3]>.5
    high = valid&(fields[:, :, 0]*30>=3)
    green = (rgb[:, :, 1]>rgb[:, :, 0]*1.08)&(rgb[:, :, 1]>rgb[:, :, 2]*1.05)
    path = ground==0
    distance, nearest = ndimage.distance_transform_edt(~path, sampling=(gy, gx), return_indices=True)
    inside_distance = ndimage.distance_transform_edt(path, sampling=(gy, gx))
    masks = {
        'path_prediction_miss': path&(prediction!=0)&(prediction!=255)&(inside_distance<=2),
        'grass_predicted_paving': (ground==2)&(prediction==0)&(distance<=3),
        'path_building_overlap': path&buildings&high&~green&(canopy!=1),
        'path_canopy_check': path&((canopy==1)|(high&green)),
        'water_map_disagreement': (ground!=255)&((ground==3)^water) if water.any() else np.zeros(shape_, bool),
    }
    if path.any():
        lab = _lab(rgb)
        colour_distance = np.linalg.norm(lab-lab[nearest[0], nearest[1]], axis=2)
        masks['unknown_path_margin'] = (ground==255)&(distance<=1.5)&(colour_distance<=12)&~green&~buildings&~water&valid&~high&(canopy!=1)
    else:
        masks['unknown_path_margin'] = np.zeros(shape_, bool)
    if inferred is not None:
        if inferred.shape!=shape_:
            raise ValueError('Matching inferred ground footprint required')
        masks['inferred_tree_path'] = inferred>0
    else:
        masks['inferred_tree_path'] = np.zeros(shape_, bool)
    return masks


def components(masks, sampling, limit=48, include_stats=False):
    gx, gy = sampling
    result = []
    for category, mask in masks.items():
        labels, count = ndimage.label(mask, structure=np.ones((3, 3)))
        slices = ndimage.find_objects(labels)
        for identity, sl in enumerate(slices, 1):
            selected = labels[sl]==identity
            area = int(selected.sum())*gx*gy
            if area<.5:
                continue
            y, x = sl
            result.append({'category': category, 'pixel_box': [x.start, y.start, x.stop, y.stop],
                           'evidence_pixels': int(selected.sum()), 'evidence_area_m2': float(area),
                           'priority': 1 if category in ('path_prediction_miss', 'path_building_overlap', 'grass_predicted_paving') else 2 if category in ('water_map_disagreement', 'inferred_tree_path') else 3})
    # Keep category diversity: a large set of model misses cannot hide all
    # water, grass or canopy issues. Windows are prompts, not inferred polygons.
    ordered = sorted(result, key=lambda r: (r['priority'], -r['evidence_area_m2'], r['category'], r['pixel_box']))
    selected = []
    for category in masks:
        selected.extend([r for r in ordered if r['category']==category][:4])
    for row in ordered:
        if row not in selected:
            selected.append(row)
        if len(selected)>=limit:
            break
    selected = sorted(selected[:limit], key=lambda r: (r['priority'], -r['evidence_area_m2'], r['category']))
    stats = {'eligible_components':len(result), 'queued_windows':len(selected), 'omitted_by_window_limit':max(0,len(result)-len(selected)),
             'minimum_component_area_m2':.5, 'window_limit':limit, 'categories':{k:sum(r['category']==k for r in result) for k in masks}}
    return (selected,stats) if include_stats else selected


def prediction_lineage(model, entry, area_id, image_sha256):
    if (model.get('version')!='layered-surface-cpu-model-v1' or not model.get('training_record_ids')
            or not model.get('training_site_ids') or not entry.get('site_id')
            or area_id in model['training_record_ids'] or entry['site_id'] in model['training_site_ids']
            or image_sha256 in model.get('training_source_sha256', [])):
        raise ValueError('Held-out prediction must exclude its image and declared park')


def validate_notes(notes, queue):
    """Bind review decisions to exact immutable windows; never apply corrections."""
    if (notes.get('version')!='boundary-alignment-review-notes-v1' or notes.get('queue_id')!=queue['id']
            or notes.get('source_comparison_sha256')!=queue['source_comparison_sha256']
            or notes.get('automatically_approved') is not False or notes.get('training_labels_changed')!=0
            or notes.get('transforms_applied')!=0 or not isinstance(notes.get('notes'),list)
            or len(notes['notes'])>len(queue['items'])):
        raise ValueError('Review notes must match the exact queue without automatic acceptance')
    items = {r['id']:r for r in queue['items']}; seen = set()
    for note in notes['notes']:
        row = items.get(note.get('item_id'))
        if (row is None or note['item_id'] in seen or note.get('area_id')!=row['area_id']
                or note.get('reference_sha256')!=row['reference_sha256'] or note.get('parent_ground_sha256')!=row['parent_ground_sha256']
                or note.get('decision') not in ('unreviewed','keep_draft','correction_needed','source_conflict')
                or not isinstance(note.get('notes'),str) or len(note['notes'])>4000):
            raise ValueError('Review note source, identity or decision differs')
        seen.add(note['item_id'])
    return {'valid_notes':len(seen),'training_labels_changed':0,'transforms_applied':0,'independent_review_established':False}


def _decode(uri, size):
    if not isinstance(uri, str) or len(uri)>24_000_000 or not uri.startswith('data:image/'):
        raise ValueError('Bounded embedded image required')
    with Image.open(BytesIO(base64.b64decode(uri.split(',', 1)[1], validate=True))) as image:
        if image.size!=tuple(size):
            raise ValueError('Comparison image dimensions changed')
        return image.convert('RGB')


def comparison_image(root, area, row):
    relative = Path(row['source_file'])
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Retained comparison image path required')
    path = root/area['id']/relative
    if file_hash(path)!=row['source_file_sha256']:
        raise ValueError('Historical comparison image changed')
    with Image.open(path) as image:
        if image.size!=tuple(area['size']):
            raise ValueError('Historical comparison image grid differs')
        return image.convert('RGB')


def _preview(rgb, ground, prediction, fields, buildings, water):
    colors = np.array([[35,160,255], [235,65,85], [65,200,80], [35,65,240]], np.uint8)
    def paint(labels):
        out = rgb.copy(); known = labels!=255
        out[known] = (out[known]*.45+colors[labels[known]]*.55).astype(np.uint8)
        return Image.fromarray(out)
    context = rgb.copy(); high = (fields[:, :, 3]>.5)&(fields[:, :, 0]>=.1)
    context[high] = (context[high]*.5+np.array([230,180,40])*.5).astype(np.uint8)
    edge = buildings&~ndimage.binary_erosion(buildings)
    context[edge] = [220,65,230]
    edge = water&~ndimage.binary_erosion(water)
    context[edge] = [20,200,240]
    return {'rgb': Image.fromarray(rgb), 'labels': paint(ground), 'prediction': paint(prediction), 'context': Image.fromarray(context)}


def run(config, output, *, base='.', cancelled=lambda: False, progress=lambda v: None):
    if config.get('version')!=VERSION or set(config)-{'version', 'comparison_file', 'comparison_file_sha256', 'source_config_file', 'source_config_file_sha256', 'predictions', 'inferred', 'priority_areas'}:
        raise ValueError('Versioned pinned boundary review request required')
    comparison_file = layers._asset(base, config, 'comparison_file')
    source_config_file = layers._asset(base, config, 'source_config_file')
    comparison = layers._read(comparison_file, 64_000_000)
    source_config = layers._read(source_config_file)
    layers.validate(source_config)
    if comparison.get('version')!=layers.VERSION or not 1<=len(comparison.get('areas', []))<=8:
        raise ValueError('Known bounded source comparison required')
    inputs = {a['id']: a for a in source_config['areas']}
    if set(inputs)!={a['id'] for a in comparison['areas']}:
        raise ValueError('Source comparison area inventory differs')
    predictions = {p['area_id']: p for p in config['predictions']}
    if set(predictions)!=set(inputs) or len(predictions)!=len(config['predictions']):
        raise ValueError('One declared prediction per area required')
    inferred_inputs = {p['area_id']: p for p in config.get('inferred', [])}
    out = Path(output)
    if out.exists():
        raise ValueError('Fresh boundary review output required')
    out.mkdir(parents=True)
    analyses = []; items = []; geo = []
    for index, area in enumerate(comparison['areas']):
        if cancelled():
            raise CancelledError('Boundary review cancelled')
        entry = inputs[area['id']]
        def source(field): return layers._asset(source_config_file.parent, entry, field)
        image = Image.open(source('image_file')).convert('RGB'); rgb = np.array(image)
        receipt = layers._read(source('receipt_file'))
        if (image.size!=tuple(area['size']) or receipt['image_sha256']!=area['reference_receipt']['image_sha256']
                or receipt['extent_epsg3857']!=area['extent_epsg3857'] or entry['label_source_image_sha256']!=receipt['image_sha256']
                or file_hash(source('image_file'))!=receipt['image_sha256']
                or ('reference' in area and not np.array_equal(np.array(_decode(area['reference'], area['size'])), rgb))):
            raise ValueError('Reference image differs from comparison snapshot')
        ground = np.array(Image.open(source('ground_mask_file')))
        canopy = np.array(Image.open(source('canopy_mask_file')))
        with np.load(source('lidar_features_file'), allow_pickle=False) as archive:
            fields = archive['features']
        lidar_receipt = layers._read(source('lidar_receipt_file'))
        if lidar_receipt['image_sha256']!=receipt['image_sha256'] or lidar_receipt['features_sha256']!=entry['lidar_features_file_sha256']:
            raise ValueError('LiDAR context is not pinned to this source image')
        pred_entry = predictions[area['id']]
        if pred_entry.get('scope')!='park_held_out' or pred_entry.get('source_image_sha256')!=receipt['image_sha256']:
            raise ValueError('Explicit source-pinned park-held-out prediction required')
        prediction = np.array(Image.open(layers._asset(base, pred_entry, 'path')))
        model_path = layers._asset(base, pred_entry, 'model_file')
        model = layers._read(model_path)
        prediction_lineage(model,pred_entry,area['id'],receipt['image_sha256'])
        if area['id'] in inferred_inputs and inferred_inputs[area['id']].get('source_image_sha256')!=receipt['image_sha256']:
            raise ValueError('Inferred footprint source image differs')
        inferred = np.array(Image.open(layers._asset(base, inferred_inputs[area['id']], 'path'))) if area['id'] in inferred_inputs else None
        sampling = ground_sampling(area['extent_epsg3857'], area['size'])
        buildings, building_source = source_mask(comparison_file.parent, area, 'os_openmap')
        water, water_source = source_mask(comparison_file.parent, area, 'import-gb-topographic-water')
        alignment = []
        green = (rgb[:, :, 1]>rgb[:, :, 0]*1.08)&(rgb[:, :, 1]>rgb[:, :, 2]*1.05)
        near_buildings = ndimage.distance_transform_edt(~buildings, sampling=(sampling[1],sampling[0]))<=6 if buildings.any() else np.zeros(ground.shape,bool)
        stable = near_buildings&~green
        for row in area['layers']:
            if row['family']=='wayback' and row['status']=='ready':
                matched = match_images(comparison_image(comparison_file.parent,area,row), image, sampling, stable)
                ref_dates = [m.get('DATE (YYYYMMDD)') for m in receipt.get('point_source_metadata', [])]
                target_dates = [m.get('attributes', {}).get('SRC_DATE') for m in row['metadata'].get('point_metadata', {}).get('results', [])]
                shared = bool(set(v for v in ref_dates if v and v!='Null')&set(v for v in target_dates if v and v!='Null'))
                alignment.append({'layer_id': row['id'], 'title': row['title'], 'source_metadata': row['metadata'],
                    'shared_capture_date_at_sample': shared, 'independent_verification': False,
                    'date_scope': 'Centre-point metadata only; not proof of a single acquisition across the whole mosaic', **matched})
        valid = fields[:, :, 3]>.5
        high = valid&(fields[:, :, 0]>=.1)
        edge = buildings&~ndimage.binary_erosion(buildings)
        high_edge = high&~ndimage.binary_erosion(high)
        distance = ndimage.distance_transform_edt(~high_edge, sampling=(sampling[1], sampling[0]))
        evaluated = edge&valid
        lidar_check = {'os_boundary_samples': int(evaluated.sum()), 'valid_fraction': float(valid.mean()),
            'nearest_elevated_edge_p50_m': float(np.median(distance[evaluated])) if evaluated.any() and high_edge.any() else None,
            'nearest_elevated_edge_p95_m': float(np.percentile(distance[evaluated],95)) if evaluated.any() and high_edge.any() else None,
            'scope': 'Nearest DSM-height edge can be a tree, roof or another object; not an identity-matched offset estimate.',
            'native_lidar_resolution_m': 1, 'surveyed_control_points': 0, 'registration_verified': False}
        masks = disagreement_masks(rgb, ground, canopy, fields, prediction, buildings, water, sampling, inferred)
        candidates, queue_stats = components(masks, sampling, include_stats=True)
        frames = _preview(rgb, ground, prediction, fields, buildings, water)
        area_report = {'id': area['id'], 'title': area['title'], 'sampling_ground_m': sampling,
            'reference_sha256': receipt['image_sha256'], 'ground_sha256': entry['ground_mask_file_sha256'],
            'prediction_sha256': pred_entry['path_sha256'], 'prediction_model_sha256': pred_entry['model_file_sha256'],
            'prediction_scope': 'park held out, against provisional draft labels', 'alignment': alignment,
            'model_training_ground_counts':model.get('training',{}).get('ground_counts'),
            'unseen_training_classes':[name for name,count in zip(('paving','structure','grass','water'),model.get('training',{}).get('ground_counts',[])) if count==0],
            'lidar_map_check': lidar_check, 'building_source': building_source, 'water_source': water_source,
            'queue_windows': len(candidates), 'queue_selection':queue_stats,
            'issue_pixels': {k:int(v.sum()) for k,v in masks.items()}}
        analyses.append(area_report)
        for candidate in candidates:
            x0,y0,x1,y1 = candidate['pixel_box']; pad = max(12, round(4/min(sampling)))
            crop = [max(0,x0-pad), max(0,y0-pad), min(image.width,x1+pad), min(image.height,y1+pad)]
            identity = digest([VERSION, area['id'], entry['ground_mask_file_sha256'], pred_entry['path_sha256'], candidate])[:18]
            row = {**candidate, 'id': identity, 'area_id': area['id'], 'title': area['title'],
                'reason': REASONS[candidate['category']], 'crop_pixels': crop, 'status':'needs_review',
                'reference_sha256': receipt['image_sha256'], 'parent_ground_sha256': entry['ground_mask_file_sha256'],
                'training_eligible':False, 'geometry_verified':False,
                'views': {}}
            for name,frame in frames.items():
                preview = frame.crop(crop)
                draw = ImageDraw.Draw(preview)
                draw.rectangle([x0-crop[0],y0-crop[1],x1-crop[0]-1,y1-crop[1]-1],outline=(255,70,70),width=2)
                # Display previews only. Original RGB, masks and numeric inputs
                # remain pinned and lossless in the reproduction inputs.
                stream = BytesIO();preview.save(stream,format='JPEG',quality=88,subsampling=0)
                row['views'][name] = 'data:image/jpeg;base64,'+base64.b64encode(stream.getvalue()).decode('ascii')
            items.append(row)
            e = area['extent_epsg3857']; w,h = area['size']
            rectangle = box(e[0]+x0/w*(e[2]-e[0]),e[3]-y1/h*(e[3]-e[1]),e[0]+x1/w*(e[2]-e[0]),e[3]-y0/h*(e[3]-e[1]))
            project = Transformer.from_crs(3857,4326,always_xy=True)
            geo.append({'type':'Feature','id':identity,'geometry':mapping(transform(project.transform,rectangle)),
                'properties':{k:v for k,v in row.items() if k not in ('views',)}|{'geometry_role':'review_window_not_boundary'}})
        progress((index+1)/len(comparison['areas']))
    priority = config.get('priority_areas', [])
    items.sort(key=lambda r: (r['area_id'] not in priority, r['priority'], -r['evidence_area_m2'], r['id']))
    report = {'version':VERSION,'source_comparison_sha256':config['comparison_file_sha256'],
        'source_config_sha256':config['source_config_file_sha256'],'areas':analyses,'items':items,
        'queue_windows':len(items),'training_labels_changed':0,'transforms_applied':0,'models_retrained':False,
        'training_readiness':{'ready':False,'scope':'Automatic correction and independent accuracy claims',
            'research_refit_requires':'An explicit source-bound correction recipe and frozen comparison; this diagnostic changes no training targets.',
            'reason':'Image matches and source conflicts do not establish corrected boundaries. Existing four images remain development data; independent survey controls and unseen evaluation data are not available.'},
        'independent_registration_established':False}
    report['id'] = digest(report)
    atomic_json(out/'queue.json',report)
    atomic_json(out/'review-windows.geojson',{'type':'FeatureCollection','features':geo})
    summary = {**report,'items':[{k:v for k,v in row.items() if k!='views'} for row in items]}
    atomic_json(out/'report.json',summary)
    atomic_json(out/'request.json',config)
    template = Path(__file__).with_name('boundary_alignment_review.html').read_text()
    (out/'index.html').write_text(template.replace('__DATA__',json.dumps(report,allow_nan=False).replace('<','\\u003c')),encoding='utf-8')
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',required=True);p.add_argument('--output',required=True)
    args = p.parse_args(argv);path = Path(args.config).resolve()
    result = run(layers._read(path),args.output,base=path.parent)
    print(json.dumps({'queue_windows':result['queue_windows'],'id':result['id']}))


if __name__=='__main__':
    main()
