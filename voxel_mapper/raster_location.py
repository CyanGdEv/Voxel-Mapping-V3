"""Location plausibility for scanned grids; never a registration certificate."""
import math

from pyproj import CRS, Transformer
from pyproj.exceptions import ProjError
from shapely.geometry import box, shape
from shapely.ops import transform as transform_geometry


def inspect_reference_coverage(labels, reference_features, metric_crs):
    """Audit independent footprints against label extent, not survey accuracy."""
    report = {'status': 'reference_coverage_only', 'features': [],
              'world_geometry_additions': 0, 'registration_verified': False,
              'limitations': ['Label extent is not necessarily the fitted control hull',
                             'Footprint containment does not verify raster feature correspondence',
                             'Reference footprints may have unknown position uncertainty']}
    if len(reference_features) > 5000 or len(labels) > 64:
        return {**report, 'status': 'reference_budget_exceeded'}
    axes = {a: [v['value'] for v in labels if v['axis']==a] for a in ('E','N')}
    if any(len(set(v)) < 2 or not all(math.isfinite(x) for x in v) for v in axes.values()):
        return {**report, 'status': 'insufficient_grid_extent'}
    extent = box(min(axes['E']), min(axes['N']), max(axes['E']), max(axes['N']))
    transformer = Transformer.from_crs(4326, metric_crs, always_xy=True)
    vertices = 0
    for feature in reference_features:
        properties = feature.get('properties', {})
        if properties.get('kind') != 'building' or properties.get('source_id') != 'osm':
            continue
        entry = {'feature_id': feature.get('id'), 'source_id': 'osm'}
        try:
            geom = shape(feature['geometry'])
            if geom.geom_type not in ('Polygon','MultiPolygon') or geom.is_empty or not geom.is_valid:
                raise ValueError('Valid building polygon required')
            polygons = [geom] if geom.geom_type=='Polygon' else list(geom.geoms)
            vertices += sum(len(p.exterior.coords)+sum(len(r.coords) for r in p.interiors) for p in polygons)
            if vertices > 100_000:
                return {**report, 'status': 'reference_vertex_budget_exceeded'}
            if not all(math.isfinite(v) for v in geom.bounds) or not (
                    -180<=geom.bounds[0]<=geom.bounds[2]<=180 and -90<=geom.bounds[1]<=geom.bounds[3]<=90):
                raise ValueError('WGS84 footprint required')
            projected = transform_geometry(lambda x,y: transformer.transform(x,y,errcheck=True), geom)
            entry['status'] = ('inside_grid_label_extent' if extent.covers(projected) else
                               'crosses_grid_label_extent' if extent.intersects(projected) else
                               'outside_grid_label_extent')
        except (ValueError, TypeError, KeyError, ProjError) as error:
            entry.update(status='rejected_reference',reason=str(error))
        report['features'].append(entry)
    report['checked_building_count'] = len(report['features'])
    report['contained_building_count'] = sum(f['status']=='inside_grid_label_extent' for f in report['features'])
    report['reference_availability'] = ('insufficient_contained_buildings' if report['contained_building_count']<3
                                        else 'contained_buildings_require_correspondence_checks')
    return report


def inspect_grid_location(labels, reference_notes, bounds=None, reference_features=None):
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
        result = {**report, 'status': 'candidate_grid_intersects_requested_area' if overlap > 0 else 'grid_outside_requested_area',
                'metric_crs_candidate': crs.to_string(), 'crs_candidate_origin': origin,
                'grid_extent_overlap_fraction': overlap/drawing.area,
                'distinct_eastings': len(set(values['E'])), 'distinct_northings': len(set(values['N']))}
        if reference_features is not None:
            result['reference_footprint_coverage'] = inspect_reference_coverage(labels,reference_features,crs)
        return result
    except (ValueError, TypeError, KeyError, ProjError) as error:
        return {**report, 'status': 'rejected_location_check', 'reason': str(error)}
