"""Image-specific ride trace supervision, independent of ground surface masks.

User ink provides sparse positive locations, not track widths, elevations or
route connectivity. Clean, separately acquired RGB is the model input.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import zipfile

import cv2
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point, box, mapping

from .generation_cycles import atomic_json, file_hash
from .horizontal_grid import OSTN15Transform

VERSION = 'ride-aerial-supervision-v1'
LABELS = {'monorail': 1, 'roller_coaster_track': 2, 'unlabelled': 255}
LEGEND = {'yellow': 'monorail', 'purple': 'roller_coaster_track'}
COLOURS = {1: (255, 215, 0), 2: (230, 20, 240)}


def extract(rgb, legend):
    """Read the explicit local legend; never reinterpret another purple image."""
    if legend != LEGEND:
        raise ValueError('Explicit image-local yellow monorail / purple coaster legend required')
    if not isinstance(rgb, np.ndarray) or rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.shape[0]*rgb.shape[1] > 4_000_000:
        raise ValueError('Bounded native RGB reference required')
    r, g, b = rgb.astype(np.int16).transpose(2, 0, 1)
    masks = {1: (r > 165) & (g > 130) & (b < 130) & (np.minimum(r, g) > 1.5*b),
             2: (r > 140) & (b > 140) & (g < 140) & (np.minimum(r, b) > 1.55*g)}
    labels = np.full(rgb.shape[:2], 255, np.uint8)
    summary = {}
    for code, mask in masks.items():
        components, count = ndi.label(mask, structure=np.ones((3, 3)))
        sizes = np.bincount(components.ravel())
        accepted = mask & (sizes[components] >= 2)
        labels[accepted] = code
        summary[next(k for k, v in LABELS.items() if v == code)] = {
            'annotated_pixels': int(accepted.sum()),
            'source_components': int(sum(sizes[1:] >= 2)),
            'isolated_single_pixels_rejected': int(sum(sizes[1:] == 1))}
    if any(not np.any(labels == code) for code in (1, 2)):
        raise ValueError('Both explicitly labelled ride classes must be present')
    return labels, summary


def register(reference, clean, labels):
    """Similarity fit from unpainted image texture; OSM never moves the ink."""
    if clean.dtype != np.uint8 or clean.ndim != 3 or clean.shape[2] != 3 or clean.shape[0]*clean.shape[1] > 4_000_000:
        raise ValueError('Bounded separately acquired clean RGB required')
    mask = (~ndi.binary_dilation(labels != 255, iterations=5)).astype(np.uint8)*255
    sift = cv2.SIFT_create(nfeatures=8000, contrastThreshold=.015)
    kp1, desc1 = sift.detectAndCompute(cv2.cvtColor(reference, cv2.COLOR_RGB2GRAY), mask)
    kp2, desc2 = sift.detectAndCompute(cv2.cvtColor(clean, cv2.COLOR_RGB2GRAY), None)
    if desc1 is None or desc2 is None or min(len(kp1), len(kp2)) < 24: raise ValueError('Image texture unavailable for registration')
    matches = [a for a, b in cv2.BFMatcher().knnMatch(desc1, desc2, k=2) if a.distance < .72*b.distance]
    if len(matches) < 24: raise ValueError('Insufficient unpainted image matches')
    source = np.float32([kp1[m.queryIdx].pt for m in matches])
    target = np.float32([kp2[m.trainIdx].pt for m in matches])
    cv2.setRNGSeed(0)
    matrix, inliers = cv2.estimateAffinePartial2D(source, target, method=cv2.RANSAC,
        ransacReprojThreshold=2, maxIters=10000, confidence=.999)
    if matrix is None: raise ValueError('Image registration failed')
    selected = inliers.ravel().astype(bool)
    error = np.linalg.norm(source@matrix[:, :2].T+matrix[:, 2]-target, axis=1)
    p95 = float(np.percentile(error[selected], 95))
    span = np.ptp(source[selected], axis=0)/[reference.shape[1], reference.shape[0]]
    if selected.sum() < 24 or p95 > 2 or span.min() < .25 or not .04 <= np.linalg.det(matrix[:, :2]) <= 25:
        raise ValueError('Registration lacks sufficient low-residual spatial coverage')
    review = {'method': 'unpainted SIFT matches and RANSAC similarity; no OSM snapping',
        'reference_to_clean': matrix.tolist(), 'ratio_matches': len(matches), 'inliers': int(selected.sum()),
        'inlier_error_clean_pixels_median': float(np.median(error[selected])),
        'inlier_error_clean_pixels_p95': p95, 'inlier_span_fraction_xy': span.tolist(),
        'reference_rotation_degrees': float(np.degrees(np.arctan2(matrix[1, 0], matrix[0, 0]))),
        'scale_clean_per_reference': float(np.hypot(matrix[0, 0], matrix[1, 0])),
        'physical_registration_verified': False,
        'control_pairs': [{'reference_xy': a.tolist(), 'clean_xy': b.tolist(), 'error_clean_px': float(e)}
                          for a, b, e in zip(source[selected], target[selected], error[selected])]}
    return matrix, review


def project_pixels(xy, image_size, extent, project):
    xy = np.asarray(xy, np.float64)
    if xy.ndim != 2 or xy.shape[1] != 2 or not np.isfinite(xy).all(): raise ValueError('Finite image locations required')
    width, height = image_size
    left, bottom, right, top = extent
    from pyproj import Transformer
    mercator_x = left+(xy[:, 0]+.5)/width*(right-left)
    mercator_y = top-(xy[:, 1]+.5)/height*(top-bottom)
    lon, lat = Transformer.from_crs(3857, 4326, always_xy=True).transform(mercator_x, mercator_y)
    e, n = project.transform(lon, lat)
    return np.column_stack([e, n])


def osm_tracks(path, project, scope):
    root = ET.parse(path).getroot()
    nodes = {n.attrib['id']: (float(n.attrib['lon']), float(n.attrib['lat'])) for n in root.findall('node')}
    rows = []
    for way in root.findall('way'):
        tags = {t.attrib['k']: t.attrib['v'] for t in way.findall('tag')}
        kind = 'monorail' if tags.get('railway') == 'monorail' else 'roller_coaster_track' if tags.get('roller_coaster') == 'track' else None
        if kind is None or any(k.startswith(('disused:', 'abandoned:')) for k in tags): continue
        geometry = LineString([project.transform(*nodes[n.attrib['ref']]) for n in way.findall('nd')])
        if not geometry.intersects(scope): continue
        # Keep each original way and its layer/tunnel attributes. No XY noding.
        rows.append({'id': 'osm/way/'+way.attrib['id'], 'geometry': geometry, 'kind': kind, 'tags': tags})
    return rows


def crossing_candidates(labels):
    """Potential image crossings; proximity is never converted into a junction."""
    if not np.any(labels == 1) or not np.any(labels == 2): return []
    near = (ndi.distance_transform_edt(labels != 1) <= 10) & (labels == 2)
    components, _ = ndi.label(ndi.binary_dilation(near, iterations=12))
    points = []
    for index, sl in enumerate(ndi.find_objects(components), 1):
        mask = (components[sl] == index) & near[sl]
        if not mask.any(): continue
        yy, xx = np.nonzero(mask)
        points.append({'reference_xy': [float(xx.mean()+sl[1].start), float(yy.mean()+sl[0].start)],
            'kind': 'monorail_coaster_projected_crossing_candidate', 'connected': False,
            'height_order': 'unresolved', 'height_odn_m': None})
    return points


def build(reference, clean, imagery_receipt, frame_file, osm_file, legend_file, output):
    reference, clean, imagery_receipt, frame_file, osm_file, legend_file, output = map(Path,
        (reference, clean, imagery_receipt, frame_file, osm_file, legend_file, output))
    if output.exists(): raise ValueError('Fresh supervision output required')
    legend = json.loads(legend_file.read_text()); receipt = json.loads(imagery_receipt.read_text()); frame = json.loads(frame_file.read_text())
    if file_hash(reference) != legend['reference_sha256'] or file_hash(clean) != receipt['image_sha256'] or reference.resolve() == clean.resolve():
        raise ValueError('Pinned separate annotated and clean images required')
    rgb = np.asarray(Image.open(reference).convert('RGB')); model_rgb = np.asarray(Image.open(clean).convert('RGB'))
    if list(Image.open(reference).size) != legend['reference_size'] or list(Image.open(clean).size) != [receipt['width'], receipt['height']]:
        raise ValueError('Native source image dimensions differ')
    labels, summary = extract(rgb, legend['legend'])
    matrix, alignment = register(rgb, model_rgb, labels)
    target = cv2.warpAffine(labels, matrix, (model_rgb.shape[1], model_rgb.shape[0]),
        flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=255)
    project = OSTN15Transform(4326, 27700, {'method': 'ostn15-bng-v1', 'path': frame['datum_grid']['file'], 'sha256': frame['datum_grid']['sha256']})
    yy, xx = np.nonzero(labels != 255)
    # Every marked pixel stays in the loss mask. A sparse review point set is
    # separate, with a maximum of one point per four-pixel source cell and class.
    codes = labels[yy, xx]
    groups = ((yy//4)*(rgb.shape[1]//4+1)+xx//4)*3+codes
    _, keep = np.unique(groups, return_index=True)
    xy = np.column_stack([xx[keep], yy[keep]]).astype(np.float64)
    clean_xy = xy@matrix[:, :2].T+matrix[:, 2]
    bng = project_pixels(clean_xy, (receipt['width'], receipt['height']), receipt['extent_epsg3857'], project)
    scope = box(bng[:, 0].min()-15, bng[:, 1].min()-15, bng[:, 0].max()+15, bng[:, 1].max()+15)
    tracks = osm_tracks(osm_file, project, scope)
    points, agreements = [], {}
    for code, name in ((1, 'monorail'), (2, 'roller_coaster_track')):
        rows = [r for r in tracks if r['kind'] == name]
        selected = np.flatnonzero(codes[keep] == code); distances = []
        for i in selected:
            point = Point(bng[i]); distance = min((point.distance(r['geometry']) for r in rows), default=float('inf'))
            if np.isfinite(distance): distances.append(distance)
            points.append({'id': name+'-'+str(i), 'label': name, 'reference_xy': xy[i].tolist(),
                'clean_xy': clean_xy[i].tolist(), 'bng_en': bng[i].tolist(), 'height_odn_m': None,
                'osm_nearest_distance_m': distance if np.isfinite(distance) else None,
                'trace_width_measured': False, 'training_role': 'sparse_positive_projected_trace_location'})
        agreements[name] = {'comparison_ways': len(rows), 'points': len(selected),
            'distance_median_p95_m': np.percentile(distances, [50, 95]).tolist() if distances else None,
            'metric_role': 'map agreement only; not surveyed accuracy; no snapping'}
    crossings = crossing_candidates(labels)
    for crossing in crossings:
        cxy = np.asarray(crossing['reference_xy'])@matrix[:, :2].T+matrix[:, 2]
        crossing['bng_en'] = project_pixels([cxy], (receipt['width'], receipt['height']), receipt['extent_epsg3857'], project)[0].tolist()
    output.mkdir(parents=True)
    Image.fromarray(labels).save(output/'reference-labels.png'); Image.fromarray(target).save(output/'training-targets.png')
    shutil.copy2(clean, output/'model-input.png'); shutil.copy2(reference, output/'user-reference.jpg')
    shutil.copy2(imagery_receipt, output/'imagery-receipt.json'); shutil.copy2(legend_file, output/'legend.json')
    overlay = model_rgb.copy()
    for code, colour in COLOURS.items(): overlay[target == code] = colour
    im = Image.fromarray(overlay); draw = ImageDraw.Draw(im)
    for crossing in crossings:
        xy_ = np.asarray(crossing['reference_xy'])@matrix[:, :2].T+matrix[:, 2]; x, y = xy_
        draw.ellipse((x-10, y-10, x+10, y+10), outline='white', width=2)
    im.save(output/'registered-review.png')
    review = {'version': VERSION, 'site': 'Alton Towers', 'ride_identity_candidate': 'Galactica',
        'legend': legend['legend'], 'labels': LABELS, 'task': 'projected_ride_trace_classification',
        'source_pins': {str(k): file_hash(v) for k, v in {'reference': reference, 'clean_rgb': clean, 'imagery_receipt': imagery_receipt, 'osm': osm_file, 'frame': frame_file, 'legend': legend_file}.items()},
        'source_image': {'reference_size': legend['reference_size'], 'clean_size': [receipt['width'], receipt['height']]},
        'extraction': summary, 'registration': alignment, 'map_agreement': agreements,
        'training_label_counts': {name: int((target == code).sum()) for name, code in LABELS.items()},
        'review_points': points, 'crossing_candidates': crossings,
        'osm_source_ways': [{'id': r['id'], 'kind': r['kind'], 'tags': r['tags']} for r in tracks],
        'training_policy': {'marker_colours_in_model_input': False, 'unmarked_pixels_are_background': False,
            'model_weights_updated': False, 'height_targets_created': False, 'track_width_targets_created': False,
            'xy_crossings_are_junctions': False, 'underlying_ground_classes_changed': False,
            'purple_meaning_global': False, 'world_blocks_generated': 0},
        'limitations': ['The image-local legend defines ride classes; earlier purple building labels remain unchanged.',
            'Painted dots/strokes are sparse projected trace supervision, not complete route, measured width or background negatives.',
            'Image matching residuals and OSM agreement do not establish absolute physical accuracy.',
            'Elevated track may overlap paths, vegetation and other tracks. Preserve each layer; heights and connectivity need separate evidence.',
            'The labelled image is not used as RGB model input. No model was trained or world changed by this intake.']}
    atomic_json(output/'review.json', review)
    atomic_json(output/'ride-points.geojson', {'type': 'FeatureCollection', 'crs': {'type': 'name', 'properties': {'name': 'EPSG:27700'}},
        'features': [{'type': 'Feature', 'id': p['id'], 'geometry': {'type': 'Point', 'coordinates': p['bng_en']},
                      'properties': {k: v for k, v in p.items() if k != 'bng_en'}} for p in points]})
    atomic_json(output/'osm-routes.geojson', {'type': 'FeatureCollection', 'crs': {'type': 'name', 'properties': {'name': 'EPSG:27700'}},
        'features': [{'type': 'Feature', 'id': r['id'], 'geometry': mapping(r['geometry']),
                      'properties': {'kind': r['kind'], **r['tags'], 'xy_crossings_are_junctions': False}} for r in tracks]})
    return review


def height_features(output, dtm_file, dsm_file, frame_file):
    import rasterio
    output = Path(output); frame = json.loads(Path(frame_file).read_text())
    receipt = json.loads((output/'imagery-receipt.json').read_text())
    width, height = receipt['width'], receipt['height']
    yy, xx = np.indices((height, width))
    project = OSTN15Transform(4326, 27700, {'method': 'ostn15-bng-v1', 'path': frame['datum_grid']['file'], 'sha256': frame['datum_grid']['sha256']})
    locations = project_pixels(np.column_stack([xx.ravel(), yy.ravel()]), (width, height), receipt['extent_epsg3857'], project)
    arrays = {}
    for name, file in [('dtm_odn_m', dtm_file), ('dsm_odn_m', dsm_file)]:
        with rasterio.open(file) as ds:
            if ds.crs.to_epsg() != 27700 or ds.res != (1, 1): raise ValueError('Native BNG metre height grids required')
            rr = np.floor((ds.bounds.top-locations[:, 1])/ds.res[1]).astype(int)
            cc = np.floor((locations[:, 0]-ds.bounds.left)/ds.res[0]).astype(int)
            valid = (rr >= 0) & (rr < ds.height) & (cc >= 0) & (cc < ds.width)
            data = ds.read(1, masked=True).filled(np.nan); values = np.full(len(rr), np.nan, np.float32)
            values[valid] = data[rr[valid], cc[valid]]
            arrays[name] = values.reshape(height, width)
    arrays['surface_above_ground_m'] = np.maximum(0, arrays['dsm_odn_m']-arrays['dtm_odn_m'])
    np.savez_compressed(output/'height-context.npz', **arrays)
    return {'native_resolution_m': 1, 'dtm_sha256': file_hash(Path(dtm_file)), 'dsm_sha256': file_hash(Path(dsm_file)), 'height_context_sha256': file_hash(output/'height-context.npz'), 'height_targets_created': False}


def attach_lidar(output, archive, cloud_receipt, dtm_file, dsm_file, frame_file):
    """Retain raw crossing context and native height features, never height labels."""
    import laspy
    import rasterio
    from .point_cloud import is_bng
    output, archive = Path(output), Path(archive)
    review = json.loads((output/'review.json').read_text())
    source = json.loads(Path(cloud_receipt).read_text())
    frame = json.loads(Path(frame_file).read_text())
    if file_hash(archive) != source['archive_sha256'] or source['crs'] != 'EPSG:27700' or source['vertical_datum'] != 'ODN':
        raise ValueError('Pinned BNG/ODN native cloud required')
    en = np.array([p['bng_en'] for p in review['review_points']])
    left, bottom = en.min(axis=0)-3; right, top = en.max(axis=0)+3
    xyz, classes, scanned = [], [], 0
    with zipfile.ZipFile(archive) as z:
        entries = [i for i in z.infolist() if i.filename.lower().endswith('.laz')]
        if len(entries) != 1: raise ValueError('One native cloud entry required')
        with z.open(entries[0]) as stream, laspy.open(stream) as reader:
            if not is_bng(reader.header.parse_crs()): raise ValueError('Native BNG cloud required')
            for points in reader.chunk_iterator(500000):
                scanned += len(points)
                x, y, zz = np.asarray(points.x), np.asarray(points.y), np.asarray(points.z)
                eligible = ~np.asarray(points.withheld, bool) & ~np.asarray(points.synthetic, bool)
                selected = eligible & (x >= left) & (x <= right) & (y >= bottom) & (y <= top) & np.isfinite(zz)
                if selected.any():
                    xyz.append(np.column_stack([x[selected], y[selected], zz[selected]]))
                    classes.append(np.asarray(points.classification)[selected])
    if not xyz: raise ValueError('No eligible raw returns in the registered trace region')
    xyz, classes = np.concatenate(xyz), np.concatenate(classes)
    np.savez_compressed(output/'lidar-returns.npz', bng_e_n_odn=xyz, classification=classes)
    tree = cKDTree(xyz[:, :2])
    for crossing in review['crossing_candidates']:
        indices = np.asarray(tree.query_ball_point(crossing['bng_en'], 2), np.int64)
        heights = xyz[indices, 2]; codes = classes[indices]
        order = np.argsort(heights); groups = np.split(order, np.flatnonzero(np.diff(heights[order]) > 1)+1) if len(order) else []
        crossing['lidar_context'] = {'radius_m': 2, 'eligible_returns': len(indices),
            'classes': dict(Counter(map(str, codes.tolist()))),
            'height_groups': [{'returns': len(g), 'odn_min_median_max_m': np.percentile(heights[g], [0, 50, 100]).tolist(),
                              'classes': dict(Counter(map(str, codes[g].tolist())))} for g in groups if len(g) >= 2],
            'selected_track_height_m': None, 'reason': 'Raw mixed returns may include ground, track, supports, canopy and buildings; no group has verified track identity.'}
    height_features(output, dtm_file, dsm_file, frame_file)
    review['lidar_context'] = {'source_url': source['url'], 'archive_sha256': source['archive_sha256'],
        'crs': 'EPSG:27700', 'vertical_datum': 'ODN', 'survey_date': '2022-01-05',
        'scanned_returns': scanned, 'cropped_eligible_returns': len(xyz), 'crop_bounds_bng': [left, bottom, right, top],
        'classes': dict(Counter(map(str, classes.tolist()))), 'withheld_and_synthetic_excluded': True,
        'raw_returns_sha256': file_hash(output/'lidar-returns.npz'), 'native_height_resolution_m': 1,
        'height_context_sha256': file_hash(output/'height-context.npz'),
        'dtm_sha256': file_hash(Path(dtm_file)), 'dsm_sha256': file_hash(Path(dsm_file)),
        'height_feature_sampling': 'Nearest native metre cell at clean RGB pixel centre; no finer measured height resolution claimed',
        'annotation_height_targets_created': False, 'crossing_height_order_verified': False,
        'attribution': 'Contains Environment Agency information © Environment Agency and/or database right, OGL-UK-3.0'}
    atomic_json(output/'review.json', review)
    return review


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('reference', 'clean', 'imagery-receipt', 'frame', 'osm', 'legend', 'output'): p.add_argument('--'+key, required=True)
    for key in ('cloud-archive', 'cloud-receipt', 'dtm', 'dsm'): p.add_argument('--'+key)
    a = p.parse_args()
    context = [a.cloud_archive, a.cloud_receipt, a.dtm, a.dsm]
    if any(context) and not all(context): p.error('Cloud archive/receipt and both terrain rasters are required together')
    result = build(a.reference, a.clean, a.imagery_receipt, a.frame, a.osm, a.legend, a.output)
    if all(context): result = attach_lidar(a.output, *context, a.frame)
    print(json.dumps({'labels': result['training_label_counts'], 'registration_inliers': result['registration']['inliers'], 'crossings': len(result['crossing_candidates'])}))


if __name__ == '__main__': main()
