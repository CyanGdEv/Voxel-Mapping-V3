"""Bounded NHLE discovery. Listing geometry is never a reconstruction mesh."""
import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import requests
from pyproj import CRS, Transformer
from shapely.geometry import MultiPoint, shape
from shapely.ops import transform

SERVICE = 'https://services-eu1.arcgis.com/ZOdPfBS3aqqDYPUQ/arcgis/rest/services/National_Heritage_List_for_England_NHLE_v02_VIEW/FeatureServer'
ATTRIBUTION = '© Historic England 2026. Contains Ordnance Survey data © Crown copyright and database right 2026.'


def validate_response(data):
    if data.get('error') or data.get('exceededTransferLimit'):
        raise ValueError('NHLE query failed or truncated; no partial inventory accepted')
    reference = data.get('spatialReference', {})
    if reference.get('latestWkid', reference.get('wkid')) != 27700:
        raise ValueError('NHLE discovery requires EPSG:27700')
    if len(data.get('features', [])) > 1000:
        raise ValueError('NHLE record budget exceeded')


def acquire(bounds, session=None):
    if len(bounds) != 4 or not all(math.isfinite(v) for v in bounds):
        raise ValueError('Finite BNG envelope required')
    x0, y0, x1, y1 = bounds
    if x1 <= x0 or y1 <= y0 or (x1-x0)*(y1-y0) > 25_000_000:
        raise ValueError('NHLE discovery envelope must be positive and at most 25 km²')
    session = session or requests.Session()
    layers = {}
    for layer in (0, 3):
        response = session.get(f'{SERVICE}/{layer}/query', params={
            'f': 'json', 'where': '1=1', 'geometry': ','.join(map(str, bounds)),
            'geometryType': 'esriGeometryEnvelope', 'inSR': 27700, 'outSR': 27700,
            'spatialRel': 'esriSpatialRelIntersects', 'outFields': '*',
            'returnGeometry': 'true', 'resultRecordCount': 1000}, timeout=60)
        response.raise_for_status()
        data = response.json()
        validate_response(data)
        layers[str(layer)] = data
    return {'service': SERVICE, 'crs': 'EPSG:27700', 'retrieved_date': datetime.now(timezone.utc).date().isoformat(), 'query_bounds': list(bounds), 'layers': layers}


def inventory(data, boundary=None):
    if boundary is not None and (boundary.is_empty or not boundary.is_valid or boundary.geom_type not in ('Polygon', 'MultiPolygon')):
        raise ValueError('Valid BNG park boundary required')
    layers = data['layers']
    if '0' not in layers or '3' not in layers:
        raise ValueError('Both NHLE location and polygon layers required')
    for layer in layers.values():
        validate_response(layer)
    polygons = {}
    for row in layers.get('3', {}).get('features', []):
        key = row['attributes']['ListEntry']
        polygons.setdefault(key, []).append(row.get('geometry', {}))
    candidates = []
    seen = set()
    for row in layers.get('0', {}).get('features', []):
        a = row['attributes']; key = a['ListEntry']
        if key in seen:
            raise ValueError('Duplicate NHLE list entry')
        seen.add(key)
        points = row.get('geometry', {}).get('points', [])
        if not points or any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in points):
            raise ValueError('Invalid NHLE location')
        location = MultiPoint(points)
        if boundary is not None:
            if not boundary.intersects(location):
                continue
        rings = [ring for g in polygons.get(key, []) for ring in g.get('rings', [])]
        # Detect observed three-vertex symbols, without treating other polygons as footprints.
        triangular = bool(rings) and all(len(r) == 4 and r[0] == r[-1] for r in rings)
        candidates.append({'id': f'nhle/{key}', 'name': a.get('Name'), 'grade': a.get('Grade'),
            'listing_url': a.get('hyperlink'), 'capture_scale': a.get('CaptureScale'),
            'location_bng': points, 'location_role': 'listing reference; not verified structure centre',
            'polygon_role': 'triangular_location_symbol' if triangular else ('unreviewed_listing_geometry' if rings else 'unavailable'),
            'family': 'heritage_asset', 'status': 'discovered; not reconstructed',
            'needed_evidence': ['physical footprint and components', 'independent plan registration',
                                'base elevation and vertical profile', 'materials and current condition']})
    return {'provider': 'Historic England NHLE', 'crs': 'EPSG:27700', 'attribution': ATTRIBUTION,
            'license': 'OGL-UK-3.0', 'candidates': sorted(candidates, key=lambda c: c['id']),
            'world_blocks_added': 0, 'limitations': ['Listed assets can include multiple structures.',
                'Listing location and listing polygons do not establish structural dimensions or heights.']}


def nhle_adapter(data, source):
    if CRS.from_user_input(source.crs) != CRS.from_epsg(27700):
        raise ValueError('NHLE source CRS must be EPSG:27700')
    return [], inventory(data)['candidates']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bounds', nargs=4, type=float, required=True, metavar=('E0','N0','E1','N1'))
    parser.add_argument('--retained-input', help='Replay retained API response without network access')
    parser.add_argument('--boundary'); parser.add_argument('--boundary-crs', default='EPSG:27700')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise ValueError('Use a new output directory')
    data = json.loads(Path(args.retained_input).read_text()) if args.retained_input else acquire(args.bounds)
    boundary = None
    if args.boundary:
        boundary = shape(json.loads(Path(args.boundary).read_text()))
        boundary = transform(Transformer.from_crs(args.boundary_crs, 27700, always_xy=True).transform, boundary)
    report = inventory(data, boundary)
    content = json.dumps(data, indent=2) + '\n'
    report.update(input_sha256=hashlib.sha256(content.encode()).hexdigest(),
                  boundary_filter='listing locations intersect boundary; discovery only' if boundary else None)
    output.mkdir(parents=True)
    (output/'nhle-source.json').write_text(content)
    (output/'heritage-inventory.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'candidates': len(report['candidates']), 'world_blocks_added': 0}))

if __name__ == '__main__':
    main()
