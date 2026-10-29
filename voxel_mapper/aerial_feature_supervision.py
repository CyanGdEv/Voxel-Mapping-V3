"""Per-image structural/landscape legends with sparse, clean-RGB supervision."""
import argparse
import json
from pathlib import Path
import shutil

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from scipy.spatial import cKDTree

from .generation_cycles import atomic_json, file_hash
from .horizontal_grid import OSTN15Transform
from .ride_aerial_supervision import register, project_pixels, height_features

LABELS = {'monorail': 1, 'roller_coaster_track': 2, 'theming_structure': 3,
          'support_structure': 4, 'fence_barrier': 5, 'path_trace': 6,
          'rock_boundary': 7, 'tree_feature': 8, 'grass_island_location': 9,
          'structure_trace': 10, 'paving_trace': 11,
          'unlabelled': 255}
COLOURS = {1: (255, 220, 0), 2: (220, 20, 220), 3: (255, 140, 15),
           4: (20, 220, 240), 5: (100, 50, 230), 6: (255, 40, 40),
           7: (220, 140, 240), 8: (20, 210, 30), 9: (160, 240, 70),
           10: (155, 35, 190), 11: (255, 100, 110)}


def extract(rgb, definition):
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.shape[0]*rgb.shape[1] > 4_000_000:
        raise ValueError('Bounded native RGB annotation required')
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    target = np.full(rgb.shape[:2], 255, np.uint8); review = []
    rules = definition['colour_rules']
    if not 1 <= len(rules) <= 12: raise ValueError('Bounded image-local colour legend required')
    for rule in rules:
        name = rule['label']
        if name not in LABELS or name == 'unlabelled': raise ValueError('Known explicitly declared semantic class required')
        mask = np.zeros(rgb.shape[:2], bool)
        for lower, upper in rule['hsv_ranges']:
            mask |= cv2.inRange(hsv, np.array(lower, np.uint8), np.array(upper, np.uint8)) != 0
        for x0, y0, x1, y1 in rule.get('exclude_boxes', []): mask[y0:y1, x0:x1] = False
        if rule.get('include_box'):
            x0, y0, x1, y1 = rule['include_box']; allowed = np.zeros(mask.shape, bool); allowed[y0:y1, x0:x1] = True; mask &= allowed
        components, _ = ndi.label(mask, np.ones((3, 3)))
        sizes = np.bincount(components.ravel()); mask &= sizes[components] >= 2
        if rule.get('max_component_radius_px'):
            radius = float(rule['max_component_radius_px'])
            if not .5 <= radius <= 16: raise ValueError('Bounded annotation stroke radius required')
            maxima = ndi.maximum(ndi.distance_transform_edt(mask), components, np.arange(len(sizes)))
            mask &= maxima[components] <= radius
        # Overlapping colour ranges are held rather than silently relabelled.
        conflict = mask & (target != 255) & (target != LABELS[name])
        if conflict.any(): raise ValueError('Image-local colour ranges overlap across classes')
        target[mask] = LABELS[name]
        review.append({'colour': rule['colour'], 'label': name, 'pixels': int(mask.sum())})
    green_review = None
    if definition.get('green_marker_policy'):
        r, g, b = rgb.astype(np.int16).transpose(2, 0, 1)
        tree_mask = (g > 135) & (r < 110) & (b < 110) & (g > 1.9*r) & (g > 1.9*b)
        components, _ = ndi.label(tree_mask, np.ones((3, 3))); sizes = np.bincount(components.ravel())
        tree_mask &= sizes[components] >= 2
        # Tiny compact isolated dots differ from the separate dashes comprising
        # a tree outline. Do not relabel every small outline dash as grass.
        candidates = (g > 170) & (g > 1.25*r) & (g > 1.8*b) & (b < 125)
        components, _ = ndi.label(candidates, np.ones((3, 3)))
        distance_to_tree = ndi.distance_transform_edt(~tree_mask)
        grass = np.zeros(tree_mask.shape, bool); locations = []
        for index, sl in enumerate(ndi.find_objects(components), 1):
            mask = components[sl] == index; area = int(mask.sum())
            height, width = mask.shape
            if not (2 <= area <= 40 and max(height, width) <= 8 and area/(height*width) >= .4): continue
            if np.min(distance_to_tree[sl][mask]) <= 20: continue
            grass[sl] |= mask
            yy, xx = np.nonzero(mask)
            locations.append([float(xx.mean()+sl[1].start), float(yy.mean()+sl[0].start)])
        target[tree_mask] = LABELS['tree_feature']; target[grass] = LABELS['grass_island_location']
        green_review = {'policy': definition['green_marker_policy'], 'tree_pixels': int(tree_mask.sum()),
            'small_grass_dot_pixels': int(grass.sum()), 'grass_dot_locations': locations,
            'digitisation_rule': 'Grass: isolated compact dot <=8 source pixels across, at least 20 pixels from tree ink. Larger dots and outline dashes remain tree features.',
            'grass_extent_inferred': False, 'tree_canopy_extent_inferred': False,
            'user_has_verified_pixel_size_threshold': False}
    return target, {'colours': review, 'green': green_review}


def filter_ink(reference, clean, matrix, labels, specification):
    """Reject naturally coloured objects that also occur in the clean image."""
    radius = specification.get('neighbourhood_radius_px', 2)
    threshold = specification.get('min_rms', 18)
    if type(radius) is not int or not 0 <= radius <= 4 or not 5 <= threshold <= 80:
        raise ValueError('Bounded source-ink colour residual settings required')
    expected = cv2.warpAffine(clean, np.asarray(matrix, np.float64), (reference.shape[1], reference.shape[0]),
        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REFLECT)
    padded = np.pad(expected.astype(np.float32), ((radius, radius), (radius, radius), (0, 0)), mode='edge')
    difference = np.full(labels.shape, np.inf, np.float32); ref = reference.astype(np.float32)
    for dy in range(2*radius+1):
        for dx in range(2*radius+1):
            other = padded[dy:dy+labels.shape[0], dx:dx+labels.shape[1]]
            difference = np.minimum(difference, np.sqrt(np.mean((ref-other)**2, axis=-1)))
    accepted = labels.copy(); accepted[(labels != 255) & (difference < threshold)] = 255
    return accepted, {'method': 'Minimum RGB RMS against locally aligned clean source',
        'minimum_rms': threshold, 'neighbourhood_radius_reference_pixels': radius,
        'before_pixels': int((labels != 255).sum()), 'after_pixels': int((accepted != 255).sum()),
        'natural_colour_candidates_rejected': int(np.count_nonzero((labels != 255) & (accepted == 255))),
        'automatic_extraction_human_verified': False}


def build(reference, clean, receipt_file, frame_file, legend_file, output, dtm=None, dsm=None):
    reference, clean, receipt_file, frame_file, legend_file, output = map(Path, (reference, clean, receipt_file, frame_file, legend_file, output))
    if output.exists(): raise ValueError('Fresh supervision output required')
    definition = json.loads(legend_file.read_text()); receipt = json.loads(receipt_file.read_text()); frame = json.loads(frame_file.read_text())
    if file_hash(reference) != definition['reference_sha256'] or file_hash(clean) != receipt['image_sha256'] or reference.resolve() == clean.resolve():
        raise ValueError('Separate pinned reference and clean RGB required')
    rgb = np.asarray(Image.open(reference).convert('RGB')); model_rgb = np.asarray(Image.open(clean).convert('RGB'))
    if list(Image.open(reference).size) != definition['reference_size'] or list(Image.open(clean).size) != [receipt['width'], receipt['height']]:
        raise ValueError('Native reference/clean dimensions differ')
    labels, extraction = extract(rgb, definition)
    # Mask all saturated potential ink during matching, including classes not
    # used as targets, so unlabelled annotation never becomes an image landmark.
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    registration_mask = labels.copy(); registration_mask[(hsv[:, :, 1] > 150) & (hsv[:, :, 2] > 140)] = 0
    matrix, alignment = register(rgb, model_rgb, registration_mask)
    if definition.get('ink_filter'):
        labels, extraction['source_ink_filter'] = filter_ink(rgb, model_rgb, matrix, labels, definition['ink_filter'])
    target = cv2.warpAffine(labels, matrix, (receipt['width'], receipt['height']), flags=cv2.INTER_NEAREST, borderValue=255)
    yy, xx = np.nonzero(labels != 255); codes = labels[yy, xx]
    groups = ((yy//4)*(rgb.shape[1]//4+1)+xx//4)*16+codes
    _, keep = np.unique(groups, return_index=True)
    xy = np.column_stack([xx[keep], yy[keep]]).astype(float); clean_xy = xy@matrix[:, :2].T+matrix[:, 2]
    project = OSTN15Transform(4326, 27700, {'method': 'ostn15-bng-v1', 'path': frame['datum_grid']['file'], 'sha256': frame['datum_grid']['sha256']})
    en = project_pixels(clean_xy, (receipt['width'], receipt['height']), receipt['extent_epsg3857'], project)
    points = [{'label': next(k for k, v in LABELS.items() if v == int(code)), 'reference_xy': a.tolist(),
               'clean_xy': b.tolist(), 'bng_en': c.tolist(), 'height_odn_m': None, 'annotation_role': 'sparse_positive_location_or_trace'}
              for code, a, b, c in zip(codes[keep], xy, clean_xy, en)]
    output.mkdir(parents=True)
    for src, name in [(reference, 'user-reference.jpg'), (clean, 'model-input.png'), (receipt_file, 'imagery-receipt.json'), (legend_file, 'legend.json')]: shutil.copy2(src, output/name)
    Image.fromarray(labels).save(output/'reference-labels.png'); Image.fromarray(target).save(output/'training-targets.png')
    overlay = model_rgb.copy()
    palette = dict(COLOURS)
    for rule in definition['colour_rules']:
        if rule.get('display_rgb'): palette[LABELS[rule['label']]] = tuple(rule['display_rgb'])
    for code, colour in palette.items(): overlay[target == code] = colour
    Image.fromarray(overlay).save(output/'registered-review.png')
    result = {'version': 'aerial-feature-supervision-v1', 'site': 'Alton Towers', 'reference_id': definition['id'],
        'task': 'sparse_site_feature_supervision', 'labels': LABELS, 'legend': definition,
        'extraction': extraction, 'registration': alignment,
        'source_pins': {k: file_hash(p) for k, p in {'reference': reference, 'clean': clean, 'receipt': receipt_file, 'frame': frame_file, 'legend': legend_file}.items()},
        'training_label_counts': {k: int((target == v).sum()) for k, v in LABELS.items()},
        'review_points': points, 'crossing_candidates': [],
        'policy': {'legend_scope': 'this pinned image only', 'marker_colours_in_model_input': False,
            'unmarked_pixels_are_background': False, 'pixel_extraction_human_verified': False,
            'filled_polygons_inferred': False, 'heights_inferred': False, 'xy_intersections_are_junctions': False,
            'model_weights_updated': False, 'world_blocks_generated': 0},
        'limitations': ['Colour semantics are user confirmed; automatic ink extraction remains a review candidate.',
            'Positive dots and traces do not establish complete polygons, dimensions, structural connectivity or elevations.',
            'Small green dots are grass-island locations; larger green dots and outlines are tree features, not grass polygons.',
            'Image matching is not independently surveyed physical registration.']}
    if dtm and dsm: result['height_context'] = height_features(output, dtm, dsm, frame_file)
    atomic_json(output/'review.json', result)
    atomic_json(output/'feature-points.geojson', {'type': 'FeatureCollection', 'crs': {'type': 'name', 'properties': {'name': 'EPSG:27700'}},
        'features': [{'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': p['bng_en']},
                      'properties': {k: v for k, v in p.items() if k != 'bng_en'}} for p in points]})
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('reference', 'clean', 'receipt', 'frame', 'legend', 'output'): p.add_argument('--'+key, required=True)
    p.add_argument('--dtm'); p.add_argument('--dsm'); a = p.parse_args()
    if bool(a.dtm) != bool(a.dsm): p.error('Both height rasters are required together')
    result = build(a.reference, a.clean, a.receipt, a.frame, a.legend, a.output, a.dtm, a.dsm)
    print(json.dumps({'id': result['reference_id'], 'inliers': result['registration']['inliers'], 'labels': result['training_label_counts']}))


if __name__ == '__main__': main()
