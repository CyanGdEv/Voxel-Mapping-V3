"""Bounded image-only tile atlas and conservative material-anchor region proposals.

Threshold regions are review evidence, never certified physical faces. No gap
closing, hatch removal, inferred view extent or world placement is performed.
"""
import hashlib
import math
import numpy as np
import pymupdf
import scipy
import rasterio
from scipy import ndimage
from rasterio.features import shapes
from affine import Affine

VERSION = 'raster-anchor-regions-v1'
ZOOM = 2
THRESHOLDS = (176, 192, 208, 216)
MAX_PIXELS = 20000000
BACKENDS = {'numpy': np.__version__, 'scipy': scipy.__version__, 'rasterio': rasterio.__version__}


def assemble(page):
    """Replay cardinal image placements without native text or annotation strokes.

    Placement clipping and optional-layer visibility remain unverified. Masks,
    skew and cropped pages are rejected explicitly. Overlaps retain paint order.
    """
    if page.cropbox != page.mediabox:
        raise ValueError('Offset/cropped image atlas unsupported')
    width, height = page.mediabox.width, page.mediabox.height
    if math.ceil(width * ZOOM) * math.ceil(height * ZOOM) > MAX_PIXELS:
        raise ValueError('Image atlas pixel budget exceeded')
    images = page.get_image_info(xrefs=True)
    if not images or len(images) > 1000:
        raise ValueError('Bounded image placements required')
    placements = []; overlaps = []; total_bytes = 0; total_source_pixels = 0
    for image in images:
        total_source_pixels += image['width'] * image['height']
        if image['width'] * image['height'] > MAX_PIXELS or total_source_pixels > 100000000:
            raise ValueError('Source image pixel budget exceeded')
        a, b, c, d, e, f = image['transform']
        # Factor a source horizontal reflection before a cardinal rotation.
        reflected = a*d-b*c < 0
        if reflected: a, b = -a, -b
        if abs(b) < 1e-5 and abs(c) < 1e-5 and a > 0 and d > 0: rotation = 0
        elif abs(a) < 1e-5 and abs(d) < 1e-5 and b < 0 and c > 0: rotation = 90
        elif abs(b) < 1e-5 and abs(c) < 1e-5 and a < 0 and d < 0: rotation = 180
        elif abs(a) < 1e-5 and abs(d) < 1e-5 and b > 0 and c < 0: rotation = 270
        else: raise ValueError('Non-cardinal image placement unsupported')
        if not image.get('xref') or image.get('has-mask', False):
            raise ValueError('Inline/masked image placement unsupported')
        rect = pymupdf.Rect(image['bbox'])
        if rect.is_empty or rect.x0 < -0.01 or rect.y0 < -0.01 or rect.x1 > width + .01 or rect.y1 > height + .01:
            raise ValueError('Image placement outside source page')
        for previous in placements:
            intersection = rect & pymupdf.Rect(previous['bbox'])
            if not intersection.is_empty and min(intersection.width, intersection.height) > .01:
                overlaps.append([previous['number'], image['number']])
        buffer = page.parent.extract_image(image['xref'])['image']
        total_bytes += len(buffer)
        if len(buffer) > 20000000 or total_bytes > 100000000: raise ValueError('Image byte budget exceeded')
        placements.append({'number': image['number'], 'xref': image['xref'],
                           'sha256': hashlib.sha256(buffer).hexdigest(),
                           'bbox': list(rect), 'transform': list(image['transform']),
                           'rotation': rotation, 'reflected_source_x': reflected, 'buffer': buffer})
    with pymupdf.open() as atlas:
        target = atlas.new_page(width=width, height=height)
        for placement in placements:
            arguments = {'stream': placement['buffer']}
            if placement['reflected_source_x']:
                source = pymupdf.Pixmap(placement['buffer'])
                source = pymupdf.Pixmap(pymupdf.csRGB, source)
                if source.alpha: raise ValueError('Alpha image unsupported')
                pixels = np.frombuffer(source.samples, dtype=np.uint8).reshape(source.height, source.width, 3)
                arguments = {'pixmap': pymupdf.Pixmap(pymupdf.csRGB, source.width, source.height,
                                                     pixels[:, ::-1].copy().tobytes(), False)}
            target.insert_image(pymupdf.Rect(placement['bbox']), **arguments,
                                rotate=placement['rotation'], keep_proportion=False)
        pixmap = target.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM), colorspace=pymupdf.csGRAY, alpha=False)
        gray = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width).copy()
    provenance = [{k: v for k, v in placement.items() if k != 'buffer'} for placement in placements]
    return gray, {'version': VERSION, 'zoom': ZOOM, 'pixel_shape': list(gray.shape),
                  'atlas_pixels_sha256': hashlib.sha256(gray.tobytes()).hexdigest(),
                  'placements': provenance, 'overlapping_image_pairs': overlaps,
                  'paint_order': 'source image occurrence order; native vector/text paints excluded',
                  'coordinate_basis': 'unrotated MuPDF page points; y down',
                  'clipping_verified': False, 'layer_visibility_verified': False,
                  'view_identity_verified': False}


def artwork_groups(gray):
    """Unclassified artwork review windows; rectangles never become faces/views.

    A coarse ink proximity grouping separates distant drawing artwork. Dilation
    is used only to propose review windows, never to repair component geometry.
    """
    step = 8
    ink = gray[::step, ::step] < 240
    nearby = ndimage.binary_dilation(ink, iterations=3)
    labels, _ = ndimage.label(nearby)
    windows = []
    for identity, slices in enumerate(ndimage.find_objects(labels), 1):
        if slices is None: continue
        inside = ink[slices] & (labels[slices] == identity)
        ys, xs = np.nonzero(inside)
        if not len(xs): continue
        x0=(slices[1].start+int(xs.min()))*step/ZOOM
        y0=(slices[0].start+int(ys.min()))*step/ZOOM
        x1=(slices[1].start+int(xs.max())+1)*step/ZOOM
        y1=(slices[0].start+int(ys.max())+1)*step/ZOOM
        if (x1-x0)*(y1-y0) < 256: continue
        windows.append({'id': f'artwork-group-{identity}', 'bbox_page_points': [x0,y0,x1,y1],
                        'ink_sample_count':len(xs), 'view_identity_verified':False,
                        'status':'unclassified_artwork_review_window'})
        if len(windows) > 1000: raise ValueError('Artwork group budget exceeded')
    return windows


def propose(gray, point, *, zoom=ZOOM, radius_points=160):
    """Require a bounded, broad region stable across all fixed thresholds.

    Full-page backgrounds, window leaks, ink-hit seeds and hatch strips receive
    explicit rejection receipts. Interior rings survive pixel polygonization.
    """
    if zoom != ZOOM or not 1 <= radius_points <= 160 or gray.ndim != 2 or gray.dtype != np.uint8 or gray.size > MAX_PIXELS:
        raise ValueError('Bounded uint8 raster review required')
    if len(point) != 2 or not all(math.isfinite(float(v)) for v in point):
        raise ValueError('Finite raster anchor required')
    x, y = [int(math.floor(float(v) * zoom)) for v in point]
    if not 0 <= x < gray.shape[1] or not 0 <= y < gray.shape[0]:
        return {'status': 'withheld_anchor_outside_atlas'}
    radius = int(radius_points * zoom)
    x0, x1 = max(0, x-radius), min(gray.shape[1], x+radius+1)
    y0, y1 = max(0, y-radius), min(gray.shape[0], y+radius+1)
    window = gray[y0:y1, x0:x1]
    masks = []; receipts = []
    for threshold in THRESHOLDS:
        labels, _ = ndimage.label(window >= threshold)  # Four-connected; no diagonal gap bridging.
        identity = int(labels[y-y0, x-x0])
        if not identity:
            receipts.append({'threshold': threshold, 'reason': 'anchor_on_dark_artwork'}); continue
        mask = labels == identity
        ys, xs = np.nonzero(mask)
        reason = None
        if mask[0].any() or mask[-1].any() or mask[:,0].any() or mask[:,-1].any(): reason = 'region_reaches_review_window_edge'
        elif min(xs.max()-xs.min()+1, ys.max()-ys.min()+1) < 8*zoom: reason = 'narrow_region_or_hatch_stripe'
        elif mask.sum() < 64*zoom*zoom: reason = 'region_too_small'
        receipts.append({'threshold': threshold, 'pixels': int(mask.sum()), 'reason': reason})
        if reason is None: masks.append(mask)
    result = {'status': 'withheld_unstable_or_unbounded_raster_region', 'threshold_receipts': receipts,
              'review_window_page_points': [x0/zoom, y0/zoom, x1/zoom, y1/zoom],
              'accepted_feature': False, 'world_geometry_additions': 0,
              'view_identity_verified': False, 'outline_identity_verified': False,
              'opening_identity_verified': False}
    if len(masks) != len(THRESHOLDS): return result
    intersection = np.logical_and.reduce(masks); union = np.logical_or.reduce(masks)
    stability = float(intersection.sum()/union.sum()); result['threshold_iou'] = stability
    if stability < .98: return result
    # Most conservative common pixels; never union fragments or repair openings.
    polygons = [geometry for geometry, value in shapes(intersection.astype('uint8'), mask=intersection,
                transform=Affine(1/zoom, 0, x0/zoom, 0, 1/zoom, y0/zoom)) if value == 1]
    if len(polygons) != 1:
        result['status'] = 'withheld_disconnected_threshold_intersection'; return result
    if sum(len(ring) for ring in polygons[0]['coordinates']) > 4096:
        result['status'] = 'withheld_complex_raster_boundary'; return result
    result.update(status='unverified_stable_raster_region_candidate', geometry=polygons[0],
                  opening_count_candidate=len(polygons[0]['coordinates'])-1,
                  limitations=['Hatch, shadow and physical boundary identities remain unresolved.',
                               'Drawing view extent and source clipping must be established independently.'])
    return result


def review(page, records):
    eligible = [r for r in records if r.get('raster_dependencies') and r.get('glyph_screen_status') == 'raster_consistent_candidate']
    if not eligible: return {'status': 'no_eligible_raster_anchors', 'version': VERSION}
    try: gray, receipt = assemble(page)
    except ValueError as error:
        for record in eligible: record['raster_region_review'] = {'status': 'withheld_atlas', 'reason': str(error)}
        return {'status': 'withheld_atlas', 'version': VERSION, 'reason': str(error)}
    groups = artwork_groups(gray)
    receipt['artwork_review_windows'] = groups
    counts = {}
    for record in eligible:
        proposal = propose(gray, record['target_page_point'])
        x,y=record['target_page_point']
        proposal['artwork_review_window_ids']=[g['id'] for g in groups
            if g['bbox_page_points'][0] < x < g['bbox_page_points'][2]
            and g['bbox_page_points'][1] < y < g['bbox_page_points'][3]]
        record['raster_region_review'] = proposal
        counts[proposal['status']] = counts.get(proposal['status'], 0)+1
    return {'status': 'unplaced_raster_review', 'atlas': receipt, 'region_statuses': counts,
            'world_geometry_additions': 0}
