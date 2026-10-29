"""Sample pinned clean imagery and explicit partial surface guides into BNG cells.

Sparse dotted guides and model predictions are not surface masks. These layers
are provisional source-assisted interiors, with unknown and canopy left unknown.
"""
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.transform import from_origin
from scipy import ndimage as ndi
from shapely.geometry import shape

from .generation_cycles import file_hash

VERSION = 'world-source-surface-layers-v1'
LABELS = {'paving': 0, 'building_structure': 1, 'grass_island': 2, 'water': 3, 'unknown': 255}


def _asset(base, entry, key):
    path = (base / entry[key]).resolve()
    if file_hash(path) != entry[key + '_sha256']:
        raise ValueError('Supplemental surface asset checksum differs: ' + key)
    return path


def load_manifest(path):
    path = Path(path)
    data = json.loads(path.read_text())
    if data.get('version') != VERSION or data.get('labels') != LABELS:
        raise ValueError('Explicit source-surface layer version and legend required')
    if not 1 <= len(data['layers']) <= 12 or len({x['id'] for x in data['layers']}) != len(data['layers']):
        raise ValueError('Bounded distinct supplemental layers required')
    layers = []
    for entry in data['layers']:
        if entry.get('role') not in ('clean_rgb_only', 'partial_source_assisted_surface_interiors'):
            raise ValueError('Sparse traces and predictions cannot become world surfaces')
        receipt_path = _asset(path.parent, entry, 'receipt')
        image_path = _asset(path.parent, entry, 'image')
        receipt = json.loads(receipt_path.read_text())
        with Image.open(image_path) as im:
            size = im.size
        extent = np.asarray(receipt['extent_epsg3857'], float)
        if (receipt['image_sha256'] != entry['image_sha256'] or list(size) != [receipt['width'], receipt['height']]
                or min(size) < 8 or size[0]*size[1] > 4_000_000 or extent.shape != (4,)
                or not np.isfinite(extent).all() or extent[0] >= extent[2] or extent[1] >= extent[3]):
            raise ValueError('Bounded georeferenced clean RGB and receipt required')
        layer = {'entry': entry, 'receipt': receipt, 'image_path': image_path}
        if entry.get('exclusions'):
            exclusions = json.loads(_asset(path.parent, entry, 'exclusions').read_text())
            if (exclusions.get('role') != 'source_assisted_user_outlined_nonpaving_islands'
                    or exclusions.get('crs', {}).get('properties', {}).get('name') != 'EPSG:27700'
                    or not 1 <= len(exclusions['features']) <= 32):
                raise ValueError('Bounded explicit nonpaving island exclusions required')
            for feature in exclusions['features']:
                g = shape(feature['geometry'])
                if g.geom_type != 'Polygon' or not g.is_valid or not 1 <= g.area <= 10000:
                    raise ValueError('Valid bounded nonpaving polygon required')
            layer['exclusions'] = exclusions
        if entry['role'] == 'partial_source_assisted_surface_interiors':
            if entry.get('independent_human_review') is not False or entry.get('inferred_canopy_ground_included') is not False:
                raise ValueError('Explicit draft status and exclusion of inferred hidden ground required')
            mask_path = _asset(path.parent, entry, 'mask')
            with Image.open(mask_path) as im:
                a = np.array(im)
                if im.mode != 'L' or im.size != size or not set(np.unique(a)) <= set(LABELS.values()):
                    raise ValueError('Matching explicit ground mask required')
            layer['mask_path'] = mask_path
        layers.append(layer)
    return layers, file_hash(path)


def _coordinates(layers, receipt):
    """Only project the small world window intersecting each returned extent."""
    left, bottom, right, top = receipt['extent_epsg3857']
    xx = np.array([left, right, right, left]); yy = np.array([bottom, bottom, top, top])
    lon, lat = Transformer.from_crs(3857, 4326, always_xy=True).transform(xx, yy)
    ee, nn = layers.project.transform(lon, lat)
    c0 = max(0, math.floor(float(np.min(ee))-layers.e0)-2)
    c1 = min(layers.width, math.ceil(float(np.max(ee))-layers.e0)+2)
    r0 = max(0, math.floor(layers.n1-float(np.max(nn)))-2)
    r1 = min(layers.height, math.ceil(layers.n1-float(np.min(nn)))+2)
    if r0 >= r1 or c0 >= c1:
        return None
    rs, cs = slice(r0, r1), slice(c0, c1)
    lon, lat = layers.project.inverse(layers.ee[rs, cs], layers.nn[rs, cs])
    x, y = Transformer.from_crs(4326, 3857, always_xy=True).transform(lon, lat)
    width, height = receipt['width'], receipt['height']
    px = (x-left)/(right-left)*width-.5
    py = (top-y)/(top-bottom)*height-.5
    # Local source pixels per BNG metre, retaining projection rotation/scale.
    lon_e, lat_e = layers.project.inverse(layers.ee[rs, cs]+1, layers.nn[rs, cs])
    xe, ye = Transformer.from_crs(4326, 3857, always_xy=True).transform(lon_e, lat_e)
    lon_n, lat_n = layers.project.inverse(layers.ee[rs, cs], layers.nn[rs, cs]+1)
    xn, yn = Transformer.from_crs(4326, 3857, always_xy=True).transform(lon_n, lat_n)
    dx = ((xe-x)/(right-left)*width, -(ye-y)/(top-bottom)*height)
    dn = ((xn-x)/(right-left)*width, -(yn-y)/(top-bottom)*height)
    scale = np.sqrt(dx[0]**2+dx[1]**2)
    return rs, cs, px, py, dx, dn, scale


def _samples(px, py, dx, dn):
    # Sixteen equal subcells sample actual metre coverage, not image dot size.
    for north in (-.375, -.125, .125, .375):
        for east in (-.375, -.125, .125, .375):
            yield py + east*dx[1] + north*dn[1], px + east*dx[0] + north*dn[0]


def merge_rgb(layers, sources, manifest_sha256, base_sampling=None):
    quality = (np.full(layers.dtm.shape, np.inf, np.float32) if base_sampling is None
               else np.asarray(base_sampling, np.float32).copy())
    if quality.shape != layers.dtm.shape or np.any(quality <= 0) or np.isnan(quality).any():
        raise ValueError('Positive matching base sampling required')
    owner = np.zeros(layers.dtm.shape, np.uint8)
    review = []
    # Coarser views first; a later coarser overlapping image cannot replace fine RGB.
    sources = sorted(sources, key=lambda x: -(x['receipt']['extent_epsg3857'][2]-x['receipt']['extent_epsg3857'][0])/x['receipt']['width'])
    for index, source in enumerate(sources, 1):
        receipt, entry = source['receipt'], source['entry']
        coords = _coordinates(layers, receipt)
        record = {'id': entry['id'], 'receipt': receipt, 'image_sha256': entry['image_sha256'], 'columns_sampled': 0}
        review.append(record)
        if coords is None: continue
        rs, cs, px, py, dx, dn, scale = coords
        metres_per_pixel = 1/scale
        margin = np.minimum.reduce([px+.5, py+.5, receipt['width']-.5-px, receipt['height']-.5-py])*metres_per_pixel
        weight = np.clip((margin-1)/3, 0, 1)
        eligible = (weight > 0) & (metres_per_pixel < quality[rs, cs])
        if not eligible.any(): continue
        rgb = np.asarray(Image.open(source['image_path']).convert('RGB'), np.float32)
        averaged = np.zeros((*px.shape, 3), np.float32)
        for sy, sx in _samples(px, py, dx, dn):
            for channel in range(3):
                averaged[..., channel] += ndi.map_coordinates(rgb[..., channel], [sy, sx], order=1, mode='nearest')/16
        blend = weight[..., None]*averaged+(1-weight[..., None])*layers.rgb[rs, cs]
        layers.rgb[rs, cs][eligible] = blend[eligible]
        quality[rs, cs][eligible] = metres_per_pixel[eligible]
        owner[rs, cs][eligible] = index
        record.update(columns_sampled=int(eligible.sum()),
                      export_sampling_ground_median_m=float(np.median(metres_per_pixel[eligible])),
                      intrinsic_resolution_improved_claimed=False)
    for index, record in enumerate(review, 1): record['final_owned_columns'] = int((owner == index).sum())
    layers.audit['aerial_mosaic'] = {'version': VERSION, 'manifest_sha256': manifest_sha256,
        'layers': review, 'supplemental_columns': int((owner > 0).sum()),
        'resampling': '16 bilinear subcell samples per native 1 m cell, 3 m edge feather; finest export sampling wins',
        'accuracy': 'Provider georeferencing; image registration is not independently surveyed physical accuracy'}


def surface_coverage(layers, sources):
    """Require ten of sixteen subcells of one explicit class; unknown is abstention."""
    candidate = np.full(layers.dtm.shape, 255, np.uint8)
    conflict = np.zeros(layers.dtm.shape, bool)
    review = []
    for source in sources:
        if 'mask_path' not in source: continue
        coords = _coordinates(layers, source['receipt'])
        if coords is None: continue
        rs, cs, px, py, dx, dn, _ = coords
        mask = np.array(Image.open(source['mask_path']))
        votes = np.zeros((4, *px.shape), np.uint8)
        for sy, sx in _samples(px, py, dx, dn):
            sampled = ndi.map_coordinates(mask, [sy, sx], order=0, mode='nearest')
            outside = (sx < -.5) | (sx >= mask.shape[1]-.5) | (sy < -.5) | (sy >= mask.shape[0]-.5)
            sampled[outside] = 255
            for label in range(4): votes[label] += sampled == label
        labels = votes.argmax(axis=0).astype(np.uint8)
        labels[votes.max(axis=0) < 10] = 255
        new = labels != 255
        old = candidate[rs, cs]
        conflict[rs, cs] |= new & (old != 255) & (old != labels)
        old[new & (old == 255)] = labels[new & (old == 255)]
        review.append({'id': source['entry']['id'], 'mask_sha256': source['entry']['mask_sha256'],
            'role': source['entry']['role'], 'independent_human_review': False,
            'inferred_canopy_ground_included': False,
            'accepted_columns': {name: int((labels == code).sum()) for name, code in LABELS.items() if code != 255}})
    candidate[conflict] = 255
    return candidate, conflict, review


def apply_surfaces(layers, sources, manifest_sha256):
    candidate, conflict, review = surface_coverage(layers, sources)
    exclusion_features = [f for s in sources for f in s.get('exclusions', {}).get('features', [])]
    nonpaving = (rasterize([(f['geometry'], 1) for f in exclusion_features],
                    out_shape=layers.dtm.shape, transform=from_origin(layers.e0, layers.n1, 1, 1), dtype='uint8') > 0
                 if exclusion_features else np.zeros(layers.dtm.shape, bool))
    # Actual roof-class returns screen new paving; they do not invent footprints.
    roof = np.isfinite(layers.cloud['roof']) & (layers.cloud['roof'] > layers.dtm+2)
    # A broad provisional plaza trace can include both lawn and tree crowns.
    # Green RGB screens additions regardless of height; existing mapped paths
    # below canopy are retained rather than replaced by this appearance test.
    vegetation = layers.green
    blocked = layers.footprints | layers.protected | (layers.water > -32768)
    paving = (candidate == 0) & ~blocked & ~roof & ~vegetation & ~nonpaving & ~conflict
    grass = (candidate == 2) & ~blocked & (layers.bridge == -32768) & ~conflict
    before = layers.family > 0
    added = paving & ~before
    removed = grass & before
    layers.family[added] = 3
    layers.surface_source[paving] = 4
    layers.family[grass] = 0
    layers.surface_source[grass] = 5
    layers.guide_exclusions = ((candidate != 255) & (candidate != 0)) | conflict | nonpaving
    layers.guide_added, layers.guide_removed = added, removed
    layers.audit['surface_guides'] = {'version': VERSION, 'manifest_sha256': manifest_sha256,
        'layers': review, 'new_paving_columns': int(added.sum()), 'cleared_paving_for_grass_columns': int(removed.sum()),
        'paving_rejected_on_classified_roof_columns': int(((candidate == 0) & roof).sum()),
        'paving_screened_by_green_rgb_columns': int(((candidate == 0) & vegetation).sum()),
        'explicit_nonpaving_islands': len(exclusion_features), 'explicit_nonpaving_island_columns': int(nonpaving.sum()),
        'paving_screened_by_explicit_island_columns': int(((candidate == 0) & nonpaving).sum()),
        'nonpaving_exclusion_sources': [{'id': s['entry']['id'], 'sha256': s['entry']['exclusions_sha256'],
            'source': s['exclusions']['source'], 'ground_materials_or_heights_inferred': False}
            for s in sources if 'exclusions' in s],
        'conflicting_source_columns_unchanged': int(conflict.sum()),
        'rule': 'At least 10/16 subcell coverage of explicit source-assisted interiors; unknown/canopy and sparse dots do not define surfaces',
        'new_structures_created': 0, 'water_boundaries_changed': False,
        'neural_predictions_used': False, 'physical_registration_verified': False}
