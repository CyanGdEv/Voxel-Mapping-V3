"""Reproducible plan-marker/track-branch links with explicitly separate LiDAR context."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re
import shutil
import tempfile

import laspy
import numpy as np
from shapely.geometry import LineString, Point, shape
from shapely.affinity import affine_transform

from .building_spec import digest
from .generation_cycles import atomic_json
from .point_cloud import is_bng
from .study_dataset import file_hash
from .study_intake import input_path
from . import study_component_learning as reader
from .wicker_track import height_marker

VERSION = 'ride-geometry-evidence-request-v1'


def branches(route, xy, *, radius=4., visit_separation=8., margin=.75):
    """Keep distant visits separate even when they occupy the same XY."""
    if (route.geom_type != 'LineString' or not route.is_valid or route.is_empty
            or not 0 < radius <= 10 or not 0 < visit_separation <= 20 or not 0 < margin <= radius):
        raise ValueError('Bounded original route and branch settings required')
    query = Point(xy)
    choices = []
    station = 0.
    for index, (a, b) in enumerate(zip(route.coords, list(route.coords)[1:])):
        line = LineString([a, b])
        if not line.length:
            continue
        distance = query.distance(line)
        if distance <= radius:
            along = line.project(query)
            choices.append({'segment': index, 'station_m': station+along,
                'distance_m': distance, 'xy': list(line.interpolate(along).coords[0])})
        station += line.length
    choices.sort(key=lambda c: (c['distance_m'], c['station_m'], c['segment']))
    visits = []
    for choice in choices:
        if all(abs(choice['station_m']-v['station_m']) > visit_separation for v in visits):
            visits.append(choice)
    delta = visits[1]['distance_m']-visits[0]['distance_m'] if len(visits) > 1 else None
    selected = bool(visits and visits[0]['distance_m'] <= .15 and (delta is None or delta >= margin))
    return {'candidates': visits, 'status': 'source_branch_candidate' if selected else 'held_ambiguous_or_distant',
        'selected': visits[0] if selected else None, 'alternative_distance_margin_m': delta,
        'physical_branch_verified': False}


def printed_markers(pdf, profile, route, cancelled=lambda: False):
    import pymupdf
    rows = []
    unit = profile['metres_per_pdf_point']
    with pymupdf.open(pdf) as document:
        if len(document) != 1:
            raise ValueError('Single-page original ride plan required')
        page = document[0]
        if page.rotation != 0 or page.rect.height != profile['source_native_height_points']:
            raise ValueError('Original unrotated source page frame required')
        vectors = page.get_drawings()
        blocks = page.get_text('blocks')
        for control in profile['controls']:
            reader._check(cancelled)
            label = control['label']
            pattern = re.compile(re.escape(label)+r'\s*-\s*(\d+\.?\d*)')
            matches = [(b, pattern.fullmatch(' '.join(b[4].split()))) for b in blocks]
            matches = [(b, m) for b, m in matches if m]
            if len(matches) != 1 or float(matches[0][1][1]) != control['height_m']:
                raise ValueError('Unique unchanged printed height label required')
            block, match = matches[0]
            marker = height_marker(vectors, list(block[:4]))
            if (not marker or marker['pdf_vector_sequence'] != control['marker_vector_sequence']
                    or math.dist(marker['point_pdf'], control['raw_marker_pdf_xy']) > .02):
                raise ValueError('Original source crosshair witness changed')
            x, y = marker['point_pdf']
            xy = [x*unit, (page.rect.height-y)*unit]
            rows.append({'label': label, 'printed_text': ' '.join(block[4].split()),
                'printed_level_m': float(match[1]), 'printed_level_datum': 'not_established',
                'label_bbox_page_points': list(block[:4]), 'crosshair_page_points': [x, y],
                'crosshair_vector_sequence': marker['pdf_vector_sequence'], 'nominal_plan_xy_m': xy,
                'binding': branches(route, xy), 'source_text_and_crosshair_replayed': True,
                'surveyed_xyz_training_eligible': False, 'model_weights_updated': False})
    return rows


def cloud_context(path, receipt, alignment, rows):
    if file_hash(path) != receipt.get('sha256') or receipt.get('crs') != 'EPSG:27700' or receipt.get('vertical_datum') != 'ODN':
        raise ValueError('Pinned BNG/ODN cloud context required')
    cloud = laspy.read(path)
    if not is_bng(cloud.header.parse_crs()) or len(cloud) != receipt['retained_points'] or len(cloud) > 1_000_000:
        raise ValueError('Bounded original BNG cloud count required')
    affine = alignment['nominal_local_xy_to_bng_en_affine']
    if len(affine) != 6 or not all(type(v) in (int, float) and math.isfinite(v) for v in affine):
        raise ValueError('Finite nominal-to-BNG context transform required')
    a, b, c, d, e, n = affine
    if abs(a*d-b*c) < 1e-8:
        raise ValueError('Invertible map transform required')
    xy = np.column_stack([cloud.x, cloud.y])
    z = np.asarray(cloud.z)
    classes = np.asarray(cloud.classification)
    eligible = ~np.asarray(cloud.withheld, dtype=bool) & ~np.asarray(cloud.synthetic, dtype=bool) & (classes != 7)
    for row in rows:
        x, y = row['nominal_plan_xy_m']
        bng = np.array([a*x+b*y+e, c*x+d*y+n])
        mask = eligible & (np.sum((xy-bng)**2, axis=1) <= 2.**2)
        heights = z[mask]
        row['lidar_context'] = {'nominal_bng_xy': bng.tolist(), 'query_radius_m': 2.,
            'eligible_returns': len(heights), 'classes': dict(Counter(map(str, classes[mask].tolist()))),
            'height_quantiles_odn_m': np.quantile(heights, [0,.25,.5,.75,1]).tolist() if len(heights) else None,
            'training_eligible': False, 'semantic_track_identity_verified': False,
            'registration_independently_surveyed': False,
            'printed_level_minus_lidar_error_m': None,
            'reason_no_accuracy_error': 'Plan datum, branch semantics and plan-to-cloud registration are not independently verified.'}


def build(request_path, output, *, cancelled=lambda: False):
    request_path, output = Path(request_path).resolve(), Path(output)
    request, raw = reader._json(request_path, 1_000_000)
    if (request.get('version') != VERSION or output.exists()
            or request.get('source_state') not in ('proposed', 'existing', 'unknown')):
        raise ValueError('Current request and fresh geometry evidence output required')
    required = {'pdf', 'markings', 'profile', 'cloud', 'cloud_receipt', 'alignment'}
    if set(request.get('assets', {})) != required:
        raise ValueError('Complete pinned geometry evidence asset set required')
    assets = {}
    for name, spec in request['assets'].items():
        reader._check(cancelled)
        path = input_path(request_path.parent, spec['path'])
        if not path.is_file() or path.stat().st_size > 32_000_000 or file_hash(path) != spec.get('sha256'):
            raise ValueError('Pinned bounded evidence asset changed: '+name)
        assets[name] = path
    profile, _ = reader._json(assets['profile'], 2_000_000)
    markings, _ = reader._json(assets['markings'], 32_000_000)
    if (profile['source_pdf_sha256'] != request['assets']['pdf']['sha256']
            or profile['markings_sha256'] != request['assets']['markings']['sha256']
            or markings['document_sha256'] != profile['source_pdf_sha256']
            or markings.get('coordinate_frame') != 'pdf_native_points_y_up'):
        raise ValueError('Source plan/profile coordinate and byte pins disagree')
    unit = profile.get('metres_per_pdf_point')
    controls = profile.get('controls')
    if type(unit) not in (int, float) or not 0 < unit < 1 or not isinstance(controls, list) or not 1 <= len(controls) <= 128:
        raise ValueError('Bounded plan scale and explicit printed controls required')
    if len({r['label'] for r in controls}) != len(controls) or any(r.get('estimated') for r in controls):
        raise ValueError('Unique source controls, without display estimates, required')
    routes = [r['geometry_pdf_native'] for r in markings['records'] if r['role'] == 'track_centre']
    if len(routes) != 1:
        raise ValueError('One original track source trace required')
    route = affine_transform(shape(routes[0]), [unit,0,0,unit,0,0])
    if route.geom_type != 'LineString' or not 2 <= len(route.coords) <= 2000:
        raise ValueError('Bounded original ordered track required')
    rows = printed_markers(assets['pdf'], profile, route, cancelled)
    receipt, _ = reader._json(assets['cloud_receipt'], 1_000_000)
    alignment, _ = reader._json(assets['alignment'], 1_000_000)
    cloud_context(assets['cloud'], receipt, alignment, rows)
    result = {'version': 'ride-geometry-evidence-v1', 'request_sha256': reader._sha(raw),
        'source_assets_sha256': {k:v['sha256'] for k,v in request['assets'].items()},
        'ride_id': request['ride_id'], 'source_state': request['source_state'], 'source_route_xy_m': list(route.coords),
        'original_track_vertices': len(route.coords), 'original_route_length_nominal_m': route.length,
        'estimated_closure_added': False, 'markers': rows,
        'summary': {'printed_levels_replayed': len(rows),
            'single_branch_candidates': sum(r['binding']['selected'] is not None for r in rows),
            'held_branch_bindings': sum(r['binding']['selected'] is None for r in rows),
            'surveyed_xyz_training_targets': 0, 'verified_3d_support_targets': 0,
            'cloud_returns_context_only': receipt['retained_points']},
        'settings': {'branch_radius_m':4., 'visit_separation_m':8., 'branch_margin_m':.75,
            'maximum_marker_to_selected_branch_m':.15, 'lidar_radius_m':2.},
        'model_weights_updated': False, 'production_eligible': False, 'world_blocks_generated': 0,
        'limitations': ['Printed plan level datum is unestablished; no ODN conversion or terrain offset is inferred.',
            'Branch candidates are deterministic source geometry links, not physical or as-built acceptance.',
            'Historical planning geometry and later LiDAR can disagree; missing returns do not exclude hidden track.',
            'Map fit uses related OSM references, not independently surveyed control points.',
            'No interpolation, display corrections or generated world variants become targets.']}
    result['id'] = digest(result)
    reader._check(cancelled)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ride-geometry-', dir=output.parent) as tmp:
        stage = Path(tmp)/'result'
        (stage/'sources').mkdir(parents=True)
        replay = json.loads(raw)
        for name, path in assets.items():
            target = stage/'sources'/(name+path.suffix)
            shutil.copy2(path, target)
            if file_hash(target) != request['assets'][name]['sha256'] or file_hash(path) != request['assets'][name]['sha256']:
                raise ValueError('Evidence changed during copying')
            replay['assets'][name]['path'] = target.relative_to(stage).as_posix()
        atomic_json(stage/'replay-request.json', replay)
        atomic_json(stage/'evidence.json', result)
        atomic_json(stage/'review-queue.json', [{'label':r['label'],
            'tasks': ['Verify the source vertical datum against independent survey.',
                'Verify printed level refers to running surface rather than another ride component.']+
                (['Resolve alternative source track visits before assigning height.'] if r['binding']['selected'] is None else []),
            'training_eligible': False} for r in rows])
        reader._check(cancelled)
        shutil.move(stage, output)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    result = build(args.request, args.output)
    print(json.dumps(result['summary']))


if __name__ == '__main__':
    main()
