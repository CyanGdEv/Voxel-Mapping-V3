"""Location plausibility for scanned grids; never a registration certificate."""
import math

from pyproj import CRS, Transformer
from pyproj.exceptions import ProjError
from shapely.geometry import box


def inspect_grid_location(labels, reference_notes, bounds=None):
    report = {'status': 'not_checked', 'registration_verified': False,
              'world_geometry_additions': 0, 'controls_exported': False,
              'limitations': ['Grid extent overlap is not independent alignment or survey accuracy',
                             'An inferred British National Grid CRS remains a hypothesis',
                             'No raster transform, physical polygon or height datum is established']}
    if bounds is None:
        return {**report, 'reason': 'Requested geographic bounds unavailable'}
    try:
        if len(bounds) != 4 or not all(math.isfinite(v) for v in bounds):
            raise ValueError('Finite requested bounds required')
        west, south, east, north = bounds
        if not -180 <= west < east <= 180 or not -90 <= south < north <= 90:
            raise ValueError('Ordered WGS84 requested bounds required')
        if len(labels) > 64:
            raise ValueError('Coordinate label budget exceeded')
        values = {'E': [], 'N': []}
        for label in labels:
            axis, value = label['axis'], label['value']
            if axis not in values or isinstance(value, bool) or not math.isfinite(value):
                raise ValueError('Finite E/N labels required')
            values[axis].append(value)
        if any(len(set(v)) < 2 for v in values.values()):
            return {**report, 'status': 'insufficient_grid_extent'}
        if any(max(v)-min(v) > 20_000 for v in values.values()):
            raise ValueError('Drawing coordinate extent budget exceeded')
        codes = reference_notes.get('explicit_epsg_candidates', [])
        if len(codes) > 1:
            return {**report, 'status': 'ambiguous_crs_claim'}
        if codes:
            crs = CRS.from_epsg(codes[0])
            origin = 'explicit_ocr_claim_unverified'
        elif reference_notes.get('national_grid_claim') is True:
            crs = CRS.from_epsg(27700)
            origin = 'british_national_grid_hypothesis'
        else:
            return {**report, 'status': 'missing_crs_claim'}
        if not crs.is_projected or len(crs.axis_info) != 2 or any(
                a.unit_name.lower() not in ('metre', 'meter') for a in crs.axis_info):
            return {**report, 'status': 'unsupported_crs_units'}
        # Geographic area of use helps reject a misidentified country/grid.
        area = crs.area_of_use
        if area is None or not box(area.west, area.south, area.east, area.north).intersects(box(*bounds)):
            return {**report, 'status': 'requested_area_outside_crs_domain'}
        transform = Transformer.from_crs(4326, crs, always_xy=True)
        metric_bounds = transform.transform_bounds(west, south, east, north, densify_pts=21, errcheck=True)
        if not all(math.isfinite(v) for v in metric_bounds):
            raise ValueError('Nonfinite transformed bounds')
        drawing = box(min(values['E']), min(values['N']), max(values['E']), max(values['N']))
        requested = box(*metric_bounds)
        overlap = drawing.intersection(requested).area
        return {**report, 'status': 'candidate_grid_intersects_requested_area' if overlap > 0 else 'grid_outside_requested_area',
                'metric_crs_candidate': crs.to_string(), 'crs_candidate_origin': origin,
                'grid_extent_overlap_fraction': overlap/drawing.area,
                'distinct_eastings': len(set(values['E'])), 'distinct_northings': len(set(values['N']))}
    except (ValueError, TypeError, KeyError, ProjError) as error:
        return {**report, 'status': 'rejected_location_check', 'reason': str(error)}
