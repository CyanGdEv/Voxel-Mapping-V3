"""Map-seeded visible paving; deliberately separate from RGB-only neural inference."""
import time

import numpy as np
from scipy import ndimage

VERSION = 'map-seeded-visible-paving-v1'


def refine(rgb, valid, blocked, references, affine, ground_scale, *,
           max_growth_m=3., colour_distance=18., cancelled=lambda: False, deadline=None):
    """Return RGB-supported pedestrian surfaces, never an image-only class guess.

    References are projected map polygons/lines, not target annotations. Growth
    is bounded per reference. Buildings, water, parking, vegetation and nodata
    remain barriers even during small-gap closing. Hidden paving is not filled.
    """
    from . import aerial_material_research as aerial
    from .imagery_geometry_research import _mask

    deadline = deadline or time.monotonic() + 180
    if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.shape[0]*rgb.shape[1] > 4000000:
        raise ValueError('Bounded RGB paving raster required')
    if valid.shape != rgb.shape[:2] or blocked.shape != valid.shape:
        raise ValueError('Matching paving validity and barrier masks required')
    if not 0 < ground_scale <= 1 or not .25 <= max_growth_m <= 8 or not 5 <= colour_distance <= 35:
        raise ValueError('Bounded paving ground scale and growth settings required')
    if len(references) > 512:
        raise ValueError('Paving reference budget exceeded')
    aerial._check(cancelled, deadline)
    pixel = max(abs(affine.a), abs(affine.e))
    ground_pixel = pixel * ground_scale
    values = ndimage.median_filter(rgb, size=(3, 3, 1)).astype(np.float32)
    green = (values[:, :, 1] > values[:, :, 0]*1.06) & (values[:, :, 1] > values[:, :, 2]*1.05)
    luminance = values @ np.array([.2126, .7152, .0722], np.float32)
    available = valid & ~blocked & ~green & (luminance >= 45)
    lab = aerial._lab(values).astype(np.float32)
    aerial._check(cancelled, deadline)
    result = np.zeros(valid.shape, bool)
    used = []; withheld = []
    for reference in sorted(references, key=lambda r: r['id']):
        aerial._check(cancelled, deadline)
        if reference['kind'] not in ('paving', 'queue'):
            continue
        tags = reference.get('tags', {})
        if tags.get('covered') in ('yes', 'true', '1') or tags.get('tunnel', 'no') not in ('no', 'false', '0', ''):
            withheld.append({'id': reference['id'], 'reason': 'covered_reference'})
            continue
        geom = reference['geometry']
        if geom.geom_type not in ('Polygon', 'MultiPolygon', 'LineString', 'MultiLineString'):
            continue
        is_line = 'LineString' in geom.geom_type
        # A line's neighbourhood is a search limit, not an asserted path width.
        seed_geom = geom.buffer(max(ground_pixel, .5)/ground_scale) if is_line else geom
        window_geom = geom.buffer((max_growth_m + (.5 if is_line else 0))/ground_scale)
        seed = _mask([seed_geom], valid.shape, affine) & available
        core = ndimage.binary_erosion(seed, iterations=max(1, round(.5/ground_pixel)))
        if core.sum() < 8:
            core = seed
        if core.sum() < 8:
            withheld.append({'id': reference['id'], 'reason': 'insufficient_visible_seed_pixels'})
            continue
        # Several source-derived prototypes retain mixed brick/stone tones.
        # No learned target mask or evaluation label enters this operation.
        colours = lab[core]; levels = colours[:, 0]
        edges = np.quantile(levels, [0, .25, .5, .75, 1])
        prototypes = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            samples = colours[(levels >= lo) & (levels <= hi)]
            if len(samples):
                prototypes.append(np.median(samples, axis=0))
        window = _mask([window_geom], valid.shape, affine) & available
        allowed = np.zeros(valid.shape, bool)
        for prototype in prototypes:
            aerial._check(cancelled, deadline)
            allowed |= np.linalg.norm(lab-prototype, axis=2) <= colour_distance
        allowed &= window
        grown = ndimage.binary_propagation(core & allowed, mask=allowed)
        # Close pedestrian-sized visual speckle only. Reapply every barrier,
        # colour constraint and search bound so grass holes cannot be filled.
        grown = ndimage.binary_closing(grown, iterations=max(1, min(3, round(.5/ground_pixel)))) & allowed
        grown = ndimage.binary_propagation(core & grown, mask=grown)
        if grown.any():
            result |= grown
            used.append(reference['id'])
    return result, {'version': VERSION, 'reference_ids': used,
        'withheld_references': withheld, 'visible_pixels': int(result.sum()),
        'vegetation_pixels_excluded': int((valid & green).sum()),
        'map_guided': True, 'neural_weights_updated': False,
        'width_verified': False, 'hidden_surfaces_filled': False,
        'training_labels_generated': 0, 'production_eligible': False}
