"""Automatic native E/N label alignment hypotheses, kept out of world geometry."""
import math
import re

import numpy as np
from pyproj import Transformer
from shapely.geometry import box


def fit_axis_labels(labels, bounds, tolerance_m=.5):
    """Fit both axes with withheld-label checks; never imply surveyed attachment."""
    result = {'status': 'unavailable', 'registration_verified': False,
              'world_geometry_additions': 0, 'source_crs_hypothesis': 'EPSG:27700',
              'limitations': ['Label origins are not surveyed grid intersections',
                             'BNG coordinate system is a hypothesis until independently confirmed',
                             'Internal label consistency does not verify absolute position']}
    axes = {}
    try:
        if len(labels) > 64:
            raise ValueError('Coordinate-label budget exceeded')
        for axis in ('E', 'N'):
            group = [(float(l['position']), float(l['value'])) for l in labels if l['axis'] == axis]
            if any(not all(math.isfinite(v) for v in row) for row in group):
                raise ValueError('Finite coordinates required')
            # Opposite margins can repeat labels; disagreeing positions are not merged.
            group = sorted(set(group))
            if len({v for _, v in group}) < 3:
                raise ValueError('Three distinct labels per axis required')
            points = np.array(group)
            # Border labels can be shifted to avoid overlap. A bounded consensus
            # excludes those origins explicitly, rather than relaxing accuracy.
            rejected = []
            initial = np.column_stack((points[:, 0]-points[:, 0].mean(), np.ones(len(points))))
            initial_fit = np.linalg.lstsq(initial, points[:, 1], rcond=None)[0]
            if np.max(np.abs(initial@initial_fit-points[:, 1])) > tolerance_m/2:
                candidates = []
                for i in range(len(points)):
                    for j in range(i+1, len(points)):
                        delta = points[j, 0]-points[i, 0]
                        if abs(delta) < 1e-9:
                            continue
                        slope = (points[j, 1]-points[i, 1])/delta
                        if slope <= 0:
                            continue
                        intercept = points[i, 1]-slope*points[i, 0]
                        mask = np.abs(points[:, 0]*slope+intercept-points[:, 1]) <= tolerance_m/2
                        if len(set(points[mask, 1])) >= 4 and mask.mean() >= .7:
                            candidates.append(mask)
                if not candidates:
                    raise ValueError('No stable majority coordinate-label consensus')
                maximum = max(int(m.sum()) for m in candidates)
                masks = {tuple(m) for m in candidates if int(m.sum()) == maximum}
                if len(masks) != 1:
                    raise ValueError('Ambiguous coordinate-label consensus')
                mask = np.array(next(iter(masks)))
                rejected = points[~mask].tolist()
                points = points[mask]
            origin = float(points[:, 0].mean())
            design = np.column_stack((points[:, 0]-origin, np.ones(len(points))))
            if np.linalg.matrix_rank(design) != 2 or np.linalg.cond(design) > 10000:
                raise ValueError('Unstable axis labels')
            fit = np.linalg.lstsq(design, points[:, 1], rcond=None)[0]
            errors = []
            for i in range(len(points)):
                train = np.delete(design, i, axis=0)
                if np.linalg.matrix_rank(train) != 2:
                    raise ValueError('Insufficient withheld-label support')
                trial = np.linalg.lstsq(train, np.delete(points[:, 1], i), rcond=None)[0]
                errors.append(abs(float(design[i]@trial-points[i, 1])))
            if fit[0] <= 0 or max(errors) > tolerance_m:
                raise ValueError('Axis orientation or withheld residual rejected')
            axes[axis] = {'slope': float(fit[0]), 'intercept': float(fit[1]-origin*fit[0]),
                          'pdf_extent': [float(points[:, 0].min()), float(points[:, 0].max())],
                          'coordinate_extent': [float(points[:, 1].min()), float(points[:, 1].max())],
                          'max_withheld_error_nominal_m': max(errors), 'label_count': len(points),
                          'excluded_label_origins': rejected}
        e, n = axes['E']['coordinate_extent'], axes['N']['coordinate_extent']
        if e[1]-e[0] > 20000 or n[1]-n[0] > 20000:
            raise ValueError('Coordinate extent exceeds 20 km')
        transform = Transformer.from_crs(27700, 4326, always_xy=True)
        w, s, east, north = transform.transform_bounds(e[0], n[0], e[1], n[1])
        if not box(*bounds).intersects(box(w, s, east, north)):
            raise ValueError('Hypothesised BNG alignment misses requested park')
        return {**result, 'status': 'native_label_alignment_hypothesis', 'axes': axes,
                'wgs84_extent_hypothesis': [w, s, east, north],
                'coordinate_convention': 'Unrotated native PDF x/y; E/N axis label origins; no extrapolation'}
    except (ValueError, KeyError, TypeError, np.linalg.LinAlgError) as error:
        return {**result, 'reason': str(error)}


def inspect_axis_alignment(page, bounds):
    labels = []
    callbacks = 0

    def visit(text, cm, tm, font, size):
        nonlocal callbacks
        callbacks += 1
        if callbacks > 200000:
            raise ValueError('Native text callback budget exceeded')
        match = re.fullmatch(r'(\d{6})([EN])', text.strip(), re.I)
        if match:
            axis = match[2].upper()
            x = tm[4]*cm[0]+tm[5]*cm[2]+cm[4]
            y = tm[4]*cm[1]+tm[5]*cm[3]+cm[5]
            labels.append({'axis': axis, 'position': x if axis == 'E' else y, 'value': int(match[1])})
            if len(labels) > 64:
                raise ValueError('Coordinate-label budget exceeded')

    if int(page.get('/Rotate', 0)) % 360 or float(page.get('/UserUnit', 1)) != 1:
        return {'status': 'unsupported_page_coordinates', 'registration_verified': False}
    try:
        page.extract_text(visitor_text=visit)
        return fit_axis_labels(labels, bounds)
    except ValueError as error:
        return {'status': 'unavailable', 'reason': str(error), 'registration_verified': False}
