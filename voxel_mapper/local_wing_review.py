"""Replay reviewed survey traces into an isolated, explicitly provisional 3D study."""
import hashlib
import json
import math
from pathlib import Path
import re

import pymupdf
from shapely.geometry import Polygon, box
from shapely.ops import unary_union
from shapely import constrained_delaunay_triangles

VERSION = 'local-wing-surface-review-v1'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def build(recipe, source_paths):
    """No inference of trace points, scheme identity, hidden walls or world pose."""
    if recipe.get('version') != VERSION or recipe.get('reviewed_trace_seed') is not True:
        raise ValueError('Explicit reviewed trace seed required')
    specs = recipe['documents']
    if set(specs) != {'plan', 'elevation', 'roof'} or set(source_paths) != set(specs):
        raise ValueError('Pinned plan, elevation and roof sources required')
    frames = {}; pins = {}
    for key, spec in specs.items():
        path = Path(source_paths[key])
        if path.stat().st_size > 32 * 1024 * 1024: raise ValueError('Source PDF byte budget exceeded')
        raw = path.read_bytes()
        if len(raw) > 32 * 1024 * 1024 or digest(raw) != spec['sha256']:
            raise ValueError('Source PDF checksum mismatch')
        if spec.get('state') != 'existing':
            raise ValueError('Existing survey review cannot mix source states')
        width = spec['render_width_pixels']; number = spec['page']; denominator = spec['scale_denominator']
        if (type(width) is not int or not 200 <= width <= 4000 or type(number) is not int
                or not 1 <= number <= 10000 or type(denominator) is not int or not 1 <= denominator <= 1000):
            raise ValueError('Bounded source frame required')
        with pymupdf.open(stream=raw, filetype='pdf') as doc:
            if number > len(doc): raise ValueError('Source page missing')
            page = doc[number - 1]
            if not 0 < page.rect.width or not 0 < page.rect.height or page.rect.height / page.rect.width * width > 4000:
                raise ValueError('Source raster dimension budget exceeded')
            pix = page.get_pixmap(matrix=pymupdf.Matrix(width / page.rect.width, width / page.rect.width))
            if digest(pix.samples) != spec['render_samples_sha256'] or [pix.width, pix.height] != spec['render_size_pixels']:
                raise ValueError('Reviewed source raster changed')
            normal = lambda text: re.sub(r'\s+', '', text).lower()
            if normal(spec['caption']) not in normal(page.get_text()):
                raise ValueError('Reviewed view caption absent')
            unit = page.rect.width / width * denominator * .0254 / 72
            from .drawing_page_tools import pixel_to_native
            frames[key] = {'metres_per_pixel': unit, 'matrix': list(pixel_to_native(page, pix.width, pix.height)),
                           'render_size_pixels': [pix.width, pix.height], 'specification': spec}
        pins[key] = digest(raw)
    points_checked = 0

    def point(key, value):
        nonlocal points_checked
        points_checked += 1
        w, h = frames[key]['render_size_pixels']
        if (points_checked > 2048 or len(value) != 2 or any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in value)
                or not 0 <= value[0] < w or not 0 <= value[1] < h):
            raise ValueError('Bounded finite trace point required')
        return tuple(value)

    plan = recipe['plan_trace']; elev = recipe['elevation_trace']; roof = recipe['roof_trace']
    a, b = [point('plan', v) for v in plan['facade_endpoints']]
    rear = point('plan', plan['rear_point'])
    pu = frames['plan']['metres_per_pixel']; eu = frames['elevation']['metres_per_pixel']
    length = math.dist(a, b) * pu
    vector = ((b[0] - a[0]) / (length / pu), (b[1] - a[1]) / (length / pu)) if length else (0, 0)
    depth = abs((rear[0] - a[0]) * vector[1] - (rear[1] - a[1]) * vector[0]) * pu
    left, right = [point('elevation', v) for v in elev['baseline_endpoints']]
    eave = point('elevation', elev['eave_point']); ridge = point('elevation', elev['ridge_point'])
    if abs(left[1] - right[1]) > 2 or right[0] <= left[0]:
        raise ValueError('Horizontal reviewed facade baseline required')
    elevation_length = (right[0] - left[0]) * eu
    eaves = (left[1] - eave[1]) * eu; ridge_height = (left[1] - ridge[1]) * eu
    if not 1 <= depth <= 20 or not 2 <= length <= 100 or not 0 < eaves < ridge_height <= 30:
        raise ValueError('Invalid wing dimensions')
    sampling = recipe['endpoint_sampling_bound_pixels']
    if isinstance(sampling, bool) or not isinstance(sampling, (int, float)) or not 0 < sampling <= 4:
        raise ValueError('Explicit bounded endpoint sampling required')
    # Bounds concern trace sampling only; they are not as-built accuracy.
    width_bound = 2 * sampling * (pu + eu)
    width_check = {'plan_length_m': length, 'elevation_length_m': elevation_length,
                   'difference_m': length - elevation_length, 'combined_sampling_bound_m': width_bound}
    result = {'version': VERSION, 'component_id': recipe['component_id'], 'recipe_sha256': digest(json.dumps(recipe, sort_keys=True).encode()),
              'source_frames': frames, 'source_pdf_sha256': pins, 'reviewed_trace_seed': True,
              'automatic_trace_extraction': False, 'coordinate_frame': 'local_metres_z_up', 'floor_datum': 'DRAWN_FLOOR_ZERO',
              'geographic_registration': None, 'world_placement_eligible': False, 'world_geometry_additions': 0,
              'physical_identity_verified': False, 'measurements': {'length_m': length, 'depth_m': depth, 'eaves_m': eaves,
              'ridge_m': ridge_height, 'height_sampling_bound_m': 2 * sampling * eu}, 'width_check': width_check,
              'unresolved': ['Independent physical identity and park placement', 'Roof/floor cross-date correspondence',
              'Roof attachment to adjacent ranges, overhangs and construction thickness', 'Outer facade, end walls and interiors',
              'Material assignments and details not measured by these traces', 'Automatic discovery of reviewed trace points']}
    result['reviewed_traces']={'plan':plan,'elevation':elev,'roof':roof,'endpoint_sampling_bound_pixels':sampling}
    for key, path in source_paths.items():
        if digest(Path(path).read_bytes()) != pins[key]: raise ValueError('Source changed during review')
    if abs(length - elevation_length) > width_bound:
        return {**result, 'status': 'withheld_cross_sheet_width_conflict', 'wall_mesh': None, 'roof_mesh': None}
    # Use elevation width as measured. Never stretch a sheet to fit another.
    wall = box(0, 0, elevation_length, eaves); openings = []
    records = recipe['openings']
    if not 1 <= len(records) <= 128 or len({r['id'] for r in records}) != len(records):
        raise ValueError('Unique bounded opening traces required')
    for row in records:
        coords = [point('elevation', v) for v in row['points_pixels']]
        poly = Polygon([((x - left[0]) * eu, (left[1] - y) * eu) for x, y in coords])
        if not poly.is_valid or poly.area <= 0 or not wall.covers(poly) or row['kind'] not in {'window', 'door', 'archway'}:
            raise ValueError('Valid contained opening trace required')
        if any(poly.intersection(other['polygon']).area > 1e-8 for other in openings):
            raise ValueError('Opening traces overlap')
        openings.append({**row, 'polygon': poly})
    cut = wall.difference(unary_union([r['polygon'] for r in openings]))
    triangles = []
    for poly in [cut] if cut.geom_type == 'Polygon' else cut.geoms:
        triangles.extend(constrained_delaunay_triangles(poly).geoms)
    assert abs(sum(t.area for t in triangles) - cut.area) < 1e-7
    vertices = []; indices = []
    for tri in triangles:
        offset = len(vertices); vertices.extend([[x, 0, z] for x, z in list(tri.exterior.coords)[:3]])
        indices.append([offset, offset + 1, offset + 2])
    # Existing roof plan supplies only a relative ridge position hypothesis.
    inner, centre, outer = [point('roof', v) for v in roof['cross_section_points']]
    axis = (outer[0] - inner[0], outer[1] - inner[1]); squared = sum(v * v for v in axis)
    if squared <= 0: raise ValueError('Distinct roof eave traces required')
    fraction = sum((centre[i] - inner[i]) * axis[i] for i in (0, 1)) / squared
    off_axis = abs((centre[0] - inner[0]) * axis[1] - (centre[1] - inner[1]) * axis[0]) / math.sqrt(squared)
    if not .1 <= fraction <= .9 or off_axis > sampling: raise ValueError('Ridge cross-section trace invalid')
    ridge_depth = depth * fraction
    roof_vertices = [[0, 0, eaves], [elevation_length, 0, eaves], [0, ridge_depth, ridge_height],
                     [elevation_length, ridge_depth, ridge_height], [0, depth, eaves], [elevation_length, depth, eaves]]
    # Opposite eave equality is explicitly a display hypothesis, not a measurement.
    result.update(status='provisional_local_surface_review', wall_mesh={'vertices': vertices, 'triangles': indices, 'watertight': False},
                  roof_mesh={'vertices': roof_vertices, 'triangles': [[0, 1, 3], [0, 3, 2], [2, 3, 5], [2, 5, 4]], 'watertight': False},
                  openings=[{k: v for k, v in r.items() if k != 'polygon'} | {'local_polygon_xz': list(r['polygon'].exterior.coords)} for r in openings],
                  wall_area_m2=cut.area, opening_area_m2=sum(r['polygon'].area for r in openings),
                  roof_assembly={'ridge_fraction_across_depth': fraction, 'ridge_depth_m': ridge_depth,
                  'opposite_eaves_equal_height_hypothesis': True, 'cross_date_roof_alignment_verified': False,
                  'end_junctions_omitted': True, 'status': 'explicit_review_hypothesis'},
                  points_checked=points_checked)
    for key, path in source_paths.items():
        if digest(Path(path).read_bytes()) != pins[key]: raise ValueError('Source changed during review')
    return result


def run(recipe_path, source_paths, output):
    recipe_path = Path(recipe_path); raw = recipe_path.read_bytes()
    if len(raw) > 2 * 1024 * 1024: raise ValueError('Recipe byte budget exceeded')
    model = build(json.loads(raw), source_paths)
    if recipe_path.read_bytes() != raw: raise ValueError('Recipe changed during review')
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    target = output / 'local-wing-model.json'; encoded = (json.dumps(model, sort_keys=True, indent=2) + '\n').encode()
    reused = target.exists()
    if reused and target.read_bytes() != encoded: raise ValueError('Local review inputs or output changed; use a fresh output')
    if not reused: target.write_bytes(encoded)
    return {'version': VERSION, 'status': model['status'], 'model_path': str(target), 'model_sha256': digest(encoded),
            'reused': reused, 'world_geometry_additions': 0, 'world_placement_eligible': False,
            'wall_triangles': len(model['wall_mesh']['triangles']) if model['wall_mesh'] else 0,
            'roof_triangles': len(model['roof_mesh']['triangles']) if model['roof_mesh'] else 0}
