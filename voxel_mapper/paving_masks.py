"""Source-pinned, explicitly traced binary paving masks for spatial-model research."""
import argparse
from html import escape
import json
import math
from pathlib import Path
import re
import shutil

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from shapely.geometry import Polygon

from .generation_cycles import atomic_json, file_hash
from .desktop_memory import digest
from . import study_component_learning as safe

VERSION = 'paving-mask-dataset-v1'
ANNOTATIONS = 'paving-mask-annotations-v1'
POLICY = 'assistant_visual_draft_requires_independent_review'
LABELS = {'non_paving': 0, 'paving': 1, 'unknown': 255}
REASONS = {'labelled': 0, 'not_reviewed': 1, 'explicit_unknown': 2,
           'boundary_margin': 3, 'conflicting_traces': 4, 'source_nodata': 5}


def _ring(value, size):
    if not isinstance(value, list) or not 3 <= len(value) <= 256:
        raise ValueError('Bounded literal polygon rings required')
    if any(not isinstance(p, list) or len(p) != 2 or any(type(v) not in (int, float)
            or not math.isfinite(v) or not 0 <= v <= size[i] for i, v in enumerate(p)) for p in value):
        raise ValueError('Finite in-crop trace coordinates required')
    return value


def rasterize(traces, size, *, boundary_pixels=1, opaque=None):
    """Explicit positives/negatives only; untraced holes are unknown, never negative."""
    if len(size) != 2 or any(type(v) is not int or not 16 <= v <= 2048 for v in size) or size[0]*size[1] > 1048576:
        raise ValueError('Bounded native crop size required')
    if type(boundary_pixels) is not int or not 0 <= boundary_pixels <= 4:
        raise ValueError('Bounded annotation boundary margin required')
    if not isinstance(traces, list) or not 1 <= len(traces) <= 256:
        raise ValueError('Explicit bounded paving traces required')
    shape = (size[1], size[0]); raw = [np.zeros(shape, bool) for _ in range(2)]
    interior = [np.zeros(shape, bool) for _ in range(2)]
    unknown = np.zeros(shape, bool); ids = set()
    for trace in traces:
        if not isinstance(trace, dict) or set(trace)-{'id', 'label', 'outer', 'holes', 'reason'}:
            raise ValueError('Known paving trace fields required')
        identifier = trace.get('id'); label = trace.get('label'); reason = trace.get('reason')
        if not isinstance(identifier, str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}', identifier) or identifier in ids:
            raise ValueError('Distinct bounded trace IDs required')
        ids.add(identifier)
        if label not in LABELS or not isinstance(reason, str) or not 1 <= len(reason) <= 300:
            raise ValueError('Explicit trace class and review reason required')
        outer = _ring(trace['outer'], size); holes = trace.get('holes', [])
        if not isinstance(holes, list) or len(holes) > 32:
            raise ValueError('Bounded literal polygon holes required')
        holes = [_ring(ring, size) for ring in holes]
        polygon = Polygon(outer, holes)
        if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
            raise ValueError('Valid non-self-intersecting trace polygon and holes required')
        canvas = Image.new('L', size, 0); draw = ImageDraw.Draw(canvas)
        draw.polygon([tuple(p) for p in outer], fill=1)
        for ring in holes:
            draw.polygon([tuple(p) for p in ring], fill=0)
        mask = np.asarray(canvas, dtype=bool)
        if label == 'unknown':
            unknown |= mask
        else:
            c = LABELS[label]; raw[c] |= mask
            interior[c] |= ndimage.binary_erosion(mask, iterations=boundary_pixels) if boundary_pixels else mask
    conflict = interior[0] & interior[1]
    boundary = (raw[0] | raw[1]) & ~(interior[0] | interior[1])
    labels = np.full(shape, 255, np.uint8); reasons = np.full(shape, REASONS['not_reviewed'], np.uint8)
    for c in (0, 1):
        labels[interior[c]] = c; reasons[interior[c]] = REASONS['labelled']
    # Every trace edge stays ignored, even where another overlapping polygon
    # has an interior. Disagreement never silently chooses a winning label.
    edges = np.zeros(shape, bool)
    if boundary_pixels:
        for c in (0, 1):
            edges |= raw[c] & ~interior[c]
    for mask, reason in [(boundary | edges, 'boundary_margin'), (conflict, 'conflicting_traces'), (unknown, 'explicit_unknown')]:
        labels[mask] = 255; reasons[mask] = REASONS[reason]
    if opaque is not None:
        if opaque.shape != shape or opaque.dtype != bool:
            raise ValueError('Matching boolean source opacity required')
        labels[~opaque] = 255; reasons[~opaque] = REASONS['source_nodata']
    return labels, reasons


def _crop(source, metadata, crop):
    with Image.open(source) as image:
        if image.width*image.height > 4000000 or image.width != metadata.get('width') or image.height != metadata.get('height'):
            raise ValueError('Pinned bounded original image dimensions required')
        if not isinstance(crop, list) or len(crop) != 4 or any(type(v) is not int for v in crop) or not 0 <= crop[0] < crop[2] <= image.width or not 0 <= crop[1] < crop[3] <= image.height:
            raise ValueError('In-source integer crop rectangle required')
        extent = metadata.get('extent_epsg3857')
        if not isinstance(extent, list) or len(extent) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in extent) or not extent[0] < extent[2] or not extent[1] < extent[3]:
            raise ValueError('Finite georeferenced original extent required')
        x0, y0, x1, y1 = crop
        dx = (extent[2]-extent[0])/image.width; dy = (extent[3]-extent[1])/image.height
        cropped_extent = [extent[0]+x0*dx, extent[3]-y1*dy, extent[0]+x1*dx, extent[3]-y0*dy]
        rgba = np.asarray(image.convert('RGBA').crop(crop)).copy()
    return rgba, cropped_extent


def build(items, annotations_file, output):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Fresh paving-mask dataset output required')
    annotations, _ = safe._json(Path(annotations_file), 2000000)
    if annotations.get('version') != ANNOTATIONS or annotations.get('review_policy') != POLICY:
        raise ValueError('Explicit provisional paving-mask annotation policy required')
    if not isinstance(items, list) or not 1 <= len(items) <= 16:
        raise ValueError('One to sixteen source-pinned paving crops required')
    output.mkdir(parents=True)
    for name in ('originals', 'metadata', 'images', 'masks', 'ignore-reasons', 'overlays'):
        (output/name).mkdir()
    shutil.copy2(annotations_file, output/'annotations.json'); rows = []; seen = set()
    for item in items:
        identifier = item['id']; site = item['site_id']
        if any(not isinstance(s, str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,79}', s) for s in (identifier, site)) or identifier in seen:
            raise ValueError('Distinct safe crop IDs and park IDs required')
        seen.add(identifier); source = Path(item['source_file']); receipt_path = Path(item['metadata_file'])
        if source.stat().st_size > 16000000 or file_hash(source) != item['source_sha256'] or file_hash(receipt_path) != item['metadata_sha256']:
            raise ValueError('Original paving source or metadata changed')
        receipt, _ = safe._json(receipt_path, 2000000)
        if receipt.get('image_sha256') != item['source_sha256']:
            raise ValueError('Paving imagery metadata source pin differs')
        rgba, extent = _crop(source, receipt, item['crop_pixels']); size = (rgba.shape[1], rgba.shape[0])
        traces = annotations['crops'][identifier]
        labels, reasons = rasterize(traces, size, boundary_pixels=annotations['boundary_ignore_pixels'], opaque=rgba[:, :, 3] == 255)
        row = {'id': identifier, 'site_id': site, 'source_record_id': item['source_record_id'],
            'crop_pixels': item['crop_pixels'], 'image_size': list(size), 'extent_epsg3857': extent,
            'split_group': site, 'split_role': 'development_annotation_review',
            'review_policy': POLICY, 'human_labels_verified': False,
            'research_training_eligible': True, 'production_training_eligible': False,
            'pixel_counts': {k: int((labels == v).sum()) for k, v in LABELS.items()},
            'ignore_reason_counts': {k: int((reasons == v).sum()) for k, v in REASONS.items()},
            'trace_count': len(traces)}
        assets = {'source': 'originals/'+identifier+'.bin', 'metadata': 'metadata/'+identifier+'.json',
            'image': 'images/'+identifier+'.png', 'mask': 'masks/'+identifier+'.png',
            'ignore_reasons': 'ignore-reasons/'+identifier+'.png'}
        shutil.copy2(source, output/assets['source']); shutil.copy2(receipt_path, output/assets['metadata'])
        Image.fromarray(rgba[:, :, :3]).save(output/assets['image'])
        Image.fromarray(labels).save(output/assets['mask']); Image.fromarray(reasons).save(output/assets['ignore_reasons'])
        for key, name in assets.items():
            row[key+'_file'] = name; row[key+'_sha256'] = file_hash(output/name)
        if row['source_sha256'] != item['source_sha256'] or row['metadata_sha256'] != item['metadata_sha256']:
            raise ValueError('Source changed while retaining paving evidence')
        rows.append(row)
    manifest = {'version': VERSION, 'labels': LABELS, 'ignore_reasons': REASONS,
        'annotation_file': 'annotations.json', 'annotation_sha256': file_hash(output/'annotations.json'),
        'review_policy': POLICY, 'human_labels_verified': False, 'geometry_verified': False,
        'production_eligible': False, 'world_blocks_generated': 0, 'records': rows}
    manifest['id'] = digest(manifest); atomic_json(output/'dataset.json', manifest)
    validate(output); review(output)
    return manifest


def validate(directory):
    root = Path(directory).resolve(); manifest, _ = safe._json(root/'dataset.json', 2000000)
    if manifest.get('version') != VERSION or manifest.get('labels') != LABELS or manifest.get('ignore_reasons') != REASONS or manifest.get('review_policy') != POLICY or manifest.get('id') != digest({k: v for k, v in manifest.items() if k != 'id'}):
        raise ValueError('Pinned binary paving-mask dataset required')
    if manifest.get('human_labels_verified') is not False or manifest.get('production_eligible') is not False or manifest.get('geometry_verified') is not False or manifest.get('world_blocks_generated') != 0:
        raise ValueError('Provisional research paving-mask policy required')
    annotation_path = safe._asset(root, manifest['annotation_file'])
    if file_hash(annotation_path) != manifest['annotation_sha256']:
        raise ValueError('Original paving traces changed')
    annotations, _ = safe._json(annotation_path, 2000000)
    if annotations.get('version') != ANNOTATIONS or annotations.get('review_policy') != POLICY:
        raise ValueError('Provisional paving trace policy changed')
    rows = manifest['records']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 16 or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Bounded distinct paving crops required')
    total = 0; source_sites = {}
    for row in rows:
        if any(not isinstance(row.get(k), str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,79}', row[k]) for k in ('id', 'site_id')) or row['split_group'] != row['site_id'] or row['split_role'] != 'development_annotation_review':
            raise ValueError('Whole-park development grouping required')
        if row.get('human_labels_verified') is not False or row.get('production_training_eligible') is not False or row.get('research_training_eligible') is not True or row.get('review_policy') != POLICY:
            raise ValueError('Provisional crop review policy changed')
        assets = {}
        for key in ('source', 'metadata', 'image', 'mask', 'ignore_reasons'):
            path = safe._asset(root, row[key+'_file'])
            if path.stat().st_size > 16000000 or file_hash(path) != row[key+'_sha256']:
                raise ValueError('Pinned paving '+key+' asset changed')
            assets[key] = path
        receipt, _ = safe._json(assets['metadata'], 2000000)
        if receipt.get('image_sha256') != row['source_sha256']:
            raise ValueError('Original paving receipt pin differs')
        if source_sites.setdefault(row['source_sha256'], row['site_id']) != row['site_id']:
            raise ValueError('One source cannot cross park split groups')
        rgba, extent = _crop(assets['source'], receipt, row['crop_pixels'])
        size = (rgba.shape[1], rgba.shape[0]); total += size[0]*size[1]
        if total > 2097152 or row['image_size'] != list(size) or row['extent_epsg3857'] != extent:
            raise ValueError('Crop geometry or dataset pixel budget changed')
        expected, reasons = rasterize(annotations['crops'][row['id']], size,
            boundary_pixels=annotations['boundary_ignore_pixels'], opaque=rgba[:, :, 3] == 255)
        if row['trace_count'] != len(annotations['crops'][row['id']]):
            raise ValueError('Paving trace count changed')
        for key, array, mode in [('image', rgba[:, :, :3], 'RGB'), ('mask', expected, 'L'), ('ignore_reasons', reasons, 'L')]:
            with Image.open(assets[key]) as image:
                if image.format != 'PNG' or image.mode != mode or image.size != size or not np.array_equal(np.asarray(image), array):
                    raise ValueError('Paving '+key+' differs from original crop/traces')
        if row['pixel_counts'] != {k: int((expected == v).sum()) for k, v in LABELS.items()} or row['ignore_reason_counts'] != {k: int((reasons == v).sum()) for k, v in REASONS.items()}:
            raise ValueError('Paving label counts changed')
    from shapely.geometry import box
    for i, row in enumerate(rows):
        for other in rows[i+1:]:
            if row['site_id'] != other['site_id'] and box(*row['extent_epsg3857']).intersection(box(*other['extent_epsg3857'])).area > 0:
                raise ValueError('Overlapping imagery cannot cross park split groups')
    return manifest


def review(directory):
    root = Path(directory).resolve(); manifest = validate(root)
    page = '<!doctype html><meta charset="utf-8"><title>Paving mask review</title><style>body{font:16px system-ui;max-width:1200px;margin:30px auto}img{max-width:48%;vertical-align:top}td,th{padding:8px}</style><h1>Paving masks — provisional visual drafts</h1><p>Blue: visible paving (1). Red: explicitly traced non-paving (0). Untinted: unknown (255). Boundary margins, canopy, unclear shadows and untraced ground stay ignored. These are assistant visual drafts, not independent human ground truth or accepted world geometry.</p><p>Compare source and overlay below. Masks retain original crop dimensions; no enlargement or synthetic detail. Same park = same split group. These existing sources are development data, not an untouched test.</p>'
    for row in manifest['records']:
        rgb = np.asarray(Image.open(root/row['image_file'])); labels = np.asarray(Image.open(root/row['mask_file'])); overlay = rgb.copy()
        for value, colour in [(1, [35, 165, 255]), (0, [240, 65, 70])]:
            selected = labels == value; overlay[selected] = (rgb[selected]*.5+np.array(colour)*.5).astype(np.uint8)
        name = 'overlays/'+row['id']+'.png'; Image.fromarray(overlay).save(root/name)
        reasons = np.asarray(Image.open(root/row['ignore_reasons_file']))
        reason_rgb = np.zeros((*labels.shape, 3), np.uint8)
        for value, colour in [(0, [40, 120, 70]), (1, [120, 120, 120]), (2, [255, 180, 50]),
                (3, [245, 245, 245]), (4, [190, 60, 200]), (5, [0, 0, 0])]:
            reason_rgb[reasons == value] = colour
        reason_name = 'overlays/'+row['id']+'-ignore.png'; Image.fromarray(reason_rgb).save(root/reason_name)
        page += '<h2>'+escape(row['id'])+'</h2><p>'+escape(json.dumps(row['pixel_counts']))+'</p><img src="'+row['image_file']+'"><img src="'+name+'"><p><a href="'+row['mask_file']+'">Native mask</a> · <a href="'+row['ignore_reasons_file']+'">Ignore-reason raster</a></p>'
        page += '<details><summary>Why pixels are ignored</summary><p>Green: labelled; grey: unreviewed; amber: explicit uncertainty; white: boundary margin; purple: conflicting traces; black: nodata.</p><img src="'+reason_name+'"></details>'
    page += '<p><a href="annotations.json">Literal trace polygons and reasons</a> · <a href="dataset.json">Sources, crop coordinates and hashes</a></p><p>Esri World Imagery and its imagery providers. Retained original receipts carry attribution and imagery observations.</p>'
    (root/'index.html').write_text(page, encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='action', required=True)
    create = sub.add_parser('build')
    for key in ('sources', 'annotations', 'output'):
        create.add_argument('--'+key, required=True)
    check = sub.add_parser('validate'); check.add_argument('--dataset', required=True)
    args = parser.parse_args(argv)
    if args.action == 'build':
        sources = Path(args.sources).resolve(); items = json.loads(sources.read_text())
        for item in items:
            for key in ('source_file', 'metadata_file'):
                item[key] = str((sources.parent/item[key]).resolve())
        result = build(items, args.annotations, args.output)
    else:
        result = validate(args.dataset)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
