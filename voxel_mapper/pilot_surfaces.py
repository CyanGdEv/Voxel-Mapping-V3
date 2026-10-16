"""Source-linked, explicitly provisional paving from the retained Wicker site plan."""
from collections import Counter
import hashlib
import json
import math

import numpy as np
from pyproj import CRS
from shapely.geometry import Point, Polygon, LineString, box, mapping, shape
from shapely.ops import transform, unary_union, polygonize
from shapely.strtree import STRtree

from .bedrock import material_block
from .horizontal_grid import OSTN15Transform
from .paving_palette import palette_block
from .pilot_access import (SURFACE_POLICY, WALKING_KINDS, _read_inputs, _scene, _mapped_nodes,
                           _mapped_node, _review_surface_nodes, _shortest_path, collision)
from .pilot_navigation import _tree, _walking_nodes
from .wicker_registration import printed_scale, straight_ring, similarity_candidates, apply_candidate
from .wicker_surfaces import extract_surfaces, painted_polygon
from .wicker_patterns import extract_pattern_surfaces
from .wickerman import annotation_evidence, _json_geometry

ARTIFACTS = ['planning-surfaces-review.json', 'planning-surfaces-source.geojson', 'planning-surfaces-local.geojson']
SOURCE_ID = 'provisional-plan-paving'


def _even_odd_fill(path):
    """Resolve crossing native even-odd edges by their PDF fill parity."""
    simple = painted_polygon(path)
    if simple is not None or not path.get('even_odd'):
        return simple
    rings, current = [], []
    for item in path.get('items', []):
        if item[0] == 're':
            if current:
                rings.append(current); current = []
            x0, y0, x1, y1 = item[1]
            rings.append([(x0,y0),(x1,y0),(x1,y1),(x0,y1)])
        elif item[0] == 'l':
            a, b = tuple(item[1]), tuple(item[2])
            if current and current[-1] != a:
                rings.append(current); current = []
            if not current:
                current.append(a)
            current.append(b)
        else:
            return None
    if current:
        rings.append(current)
    if not rings or any(len(ring) < 3 for ring in rings) or sum(map(len, rings)) > 2048:
        return None
    segments = [(a,b) for ring in rings for a,b in zip(ring, ring[1:] + ring[:1]) if a != b]
    lines = [LineString(edge) for edge in segments]
    if len(STRtree(lines).query(lines, predicate='intersects')[0]) > 40_000:
        raise ValueError('Planning paving crossing-edge budget exceeded')
    faces = list(polygonize(unary_union(lines)))
    if len(faces) > 4096:
        raise ValueError('Planning paving filled-face budget exceeded')
    def filled(point):
        x, y = point.x, point.y
        return sum((a[1] > y) != (b[1] > y) and
                   x < a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) for a,b in segments) % 2 == 1
    result = unary_union([face for face in faces if filled(face.representative_point())])
    return result if result.geom_type in ('Polygon','MultiPolygon') and result.is_valid and not result.is_empty else None


def _curved_fills(vectors, tolerance_pdf_points):
    """Flatten native cubic fill/clip edges; never repair gaps or invalid rings."""
    if not math.isfinite(tolerance_pdf_points) or tolerance_pdf_points <= 0:
        raise ValueError('Finite positive curve tolerance required')
    def endpoints(a, b, c, d, depth=0):
        delta = d - a
        length2 = float(delta @ delta)
        def distance(p):
            nearest = a + np.clip(float((p - a) @ delta) / length2, 0, 1) * delta if length2 else a
            return float(np.linalg.norm(p - nearest))
        if max(distance(b), distance(c)) <= tolerance_pdf_points:
            return [d.tolist()]
        if depth >= 16:
            raise ValueError('Planning paving curve subdivision budget exceeded')
        ab, bc, cd = (a + b) / 2, (b + c) / 2, (c + d) / 2
        abc, bcd = (ab + bc) / 2, (bc + cd) / 2
        mid = (abc + bcd) / 2
        return endpoints(a, ab, abc, mid, depth + 1) + endpoints(mid, bcd, cd, d, depth + 1)
    result, segments, curves = [], 0, 0
    for path in vectors:
        if path.get('type') not in ('f', 'fs', 'clip'):
            result.append(path); continue
        items = []
        for item in path.get('items', []):
            previous_count = len(items)
            if item[0] == 'c':
                a, b, c, d = (np.array(p, dtype=float) for p in item[1:])
                if not all(p.shape == (2,) and np.isfinite(p).all() for p in (a, b, c, d)):
                    raise ValueError('Invalid planning paving curve')
                previous = a.tolist()
                for end in endpoints(a, b, c, d):
                    items.append(['l', previous, end]); previous = end
                curves += 1
            else:
                items.append(item)
            segments += len(items) - previous_count
            if segments > 2_000_000:
                raise ValueError('Planning paving flattened edge budget exceeded')
        result.append({**path, 'items': items})
    return result, curves


def prepare(settings, asset, load_json, directory, config):
    if (not isinstance(settings, dict) or set(settings) != {'policy', 'source_pdf', 'source_record', 'raw_osm', 'max_cells'}
            or settings.get('policy') != SURFACE_POLICY
            or type(settings.get('max_cells')) is not int or not 1 <= settings['max_cells'] <= 10_000):
        raise ValueError('Explicit bounded provisional planning paving policy required')
    pdf = asset(settings['source_pdf'], directory, 'review_paving_pdf')
    metadata = load_json(asset(settings['source_record'], directory, 'review_paving_source_record'))
    if (metadata.get('document_sha256') != settings['source_pdf']['sha256'] or metadata.get('page') != 1
            or metadata.get('drawing_state') != 'proposed'
            or metadata.get('registration_verified') is not False or metadata.get('as_built_verified') is not False
            or any(not isinstance(metadata.get(k), str) or not metadata[k].strip()
                   for k in ('title', 'application_reference', 'source_url'))):
        raise ValueError('Pinned proposed drawing identity with explicitly unverified placement/state required')
    if pdf.stat().st_size > 10_000_000 or pdf.read_bytes()[:5] != b'%PDF-':
        raise ValueError('Bounded original planning PDF required')
    raw_path = asset(settings['raw_osm'], directory, 'review_paving_osm')
    raw = load_json(raw_path)
    if not isinstance(raw.get('elements'), list) or len(raw['elements']) > 100_000 or raw.get('remark'):
        raise ValueError('Complete bounded map reference required for provisional paving')
    operation = config['terrain'].get('horizontal_operation')
    if not operation:
        raise ValueError('Planning paving requires the pinned OSTN15 operation')
    if any(s['id'] == SOURCE_ID for s in config['sources']):
        raise ValueError('Reserved provisional paving source identity')
    config['sources'].append({'id': SOURCE_ID, 'kind': 'planning_study', 'url': metadata['source_url'],
        'sha256': metadata['document_sha256'], 'license': 'unconfirmed-drawing-reuse',
        'attribution': metadata['title'] + '; Nichols Brown Webber LLP. Proposed plan; placement and materials remain review estimates.'})
    return {'pdf': pdf, 'raw': raw, 'source': metadata, 'operation': operation,
            'max_cells': settings['max_cells'], 'bounds_wgs84': config['bbox']}


def recover(pdf, raw, operation, bounds):
    """Reuse native fill/pattern recovery; keep the scale bar fixed during the map fit."""
    import pymupdf
    with pymupdf.open(pdf) as document:
        if len(document) != 1 or document[0].rotation != 0:
            raise ValueError('One complete unrotated site-plan page required')
        page = document[0]
        lines = [{'text': ''.join(s['text'] for s in line['spans']), 'bbox': list(line['bbox'])}
                 for block in page.get_text('dict')['blocks'] for line in block.get('lines', [])]
        if len(lines) > 10_000:
            raise ValueError('Planning paving annotation budget exceeded')
        scale = printed_scale(lines)
        vectors = _json_geometry(page.get_drawings(extended=True))
    if len(vectors) > 150_000:
        raise ValueError('Planning paving vector budget exceeded')
    shops = [e for e in raw['elements'] if e.get('tags', {}).get('name') == 'Wicker Man Shop']
    labels = [line for line in lines if line['text'] == 'Shop']
    if len(shops) != 1 or len(labels) != 1:
        raise ValueError('One named mapped shop and one native Shop label required')
    x0, y0, x1, y1 = labels[0]['bbox']
    centre = Point((x0 + x1) / 2, (y0 + y1) / 2)
    rings = {p.normalize().wkb: p for vector in vectors
             if vector.get('fill') == [1., 1., 1.] and len(vector.get('items', [])) == 4
             and (p := straight_ring(vector)) is not None and 25 <= p.area * scale ** 2 <= 2500
             and p.contains(centre)}
    if len(rings) != 1:
        raise ValueError('Unique closed source shop footprint required; label boxes are excluded')
    ring = next(iter(rings.values()))
    geographic = [(p['lon'], p['lat']) for p in shops[0].get('geometry', [])]
    if (len(geographic) != 5 or geographic[0] != geographic[-1]
            or not box(*bounds).covers(Polygon(geographic))):
        raise ValueError('Closed four-corner mapped shop must be inside the pilot')
    coordinate = OSTN15Transform(4326, 27700, operation)
    target = np.array([coordinate.transform(*p) for p in geographic[:-1]])
    tracks = [e for e in raw['elements'] if e.get('tags', {}).get('name') == 'Wicker Man'
              and e['tags'].get('roller_coaster') == 'track']
    if not tracks or len(tracks) > 100 or sum(len(e.get('geometry', [])) for e in tracks) > 20_000:
        raise ValueError('Bounded mapped track reference required for orientation checks')
    track = unary_union([LineString([coordinate.transform(p['lon'], p['lat']) for p in e['geometry']])
                         for e in tracks if len(e.get('geometry', [])) >= 2])
    _, levels = annotation_evidence(lines)
    points = [[(p['bbox'][0] + p['bbox'][2]) / 2, (p['bbox'][1] + p['bbox'][3]) / 2] for p in levels]
    if not points:
        raise ValueError('Track annotation orientation checks unavailable')
    source = np.array(ring.exterior.coords[:-1]); source[:, 1] *= -1
    hypotheses, passing = [], []
    for candidate in similarity_candidates(list(ring.exterior.coords)[:-1], target):
        free_scale = candidate['scale_m_per_pdf_point']
        rotation = np.array(candidate['rotation'])
        candidate['scale_m_per_pdf_point'] = scale
        candidate['translation_epsg27700_m'] = (target.mean(0) - scale * source.mean(0) @ rotation).tolist()
        corners = apply_candidate(list(ring.exterior.coords)[:-1], candidate)
        corner_rms = float(np.sqrt(np.mean([min(np.linalg.norm(p - q) ** 2 for q in target) for p in corners])))
        distances = [float(track.distance(Point(p))) for p in apply_candidate(points, candidate)]
        groups = {}
        for i, level in enumerate(levels):
            groups.setdefault(level['point_label'], []).append(i)
        selected = [i for group in groups.values() for i in group
                    if distances[i] <= 5 and all(distances[j] >= 10 for j in group if j != i)]
        median = float(np.median([distances[i] for i in selected])) if selected else None
        item = {'candidate': candidate, 'free_scale_diagnostic_m_per_point': free_scale,
                'scale_difference_fraction': abs(free_scale / scale - 1), 'shop_corner_rms_at_printed_scale_m': corner_rms,
                'unique_near_track_labels': len(selected), 'median_annotation_track_distance_m': median}
        hypotheses.append(item)
        if item['scale_difference_fraction'] <= .02 and corner_rms <= 1 and len(selected) >= 12 and median <= 3:
            passing.append(item)
    if len(passing) != 1:
        raise ValueError('Shop/scale/track checks do not select one provisional orientation')
    filled_vectors, curve_count = _curved_fills(vectors, .05 / scale)
    candidates, fills = extract_surfaces(filled_vectors, lines, scale, polygon_resolver=_even_odd_fill)
    fills.update(flattened_cubic_edges=curve_count, curve_tolerance_m_at_printed_scale=.05,
                 crossing_fill_policy='Native even-odd edge parity; no snapping, hulls or inferred closing gaps.')
    try:
        patterned, patterns = extract_pattern_surfaces(pdf, lines, scale, hashlib.sha256(pdf.read_bytes()).hexdigest())
        candidates += patterned
    except (ValueError, KeyError, StopIteration) as error:
        patterns = {'status': 'withheld', 'reason': str(error) or 'New-paving pattern legend unavailable'}
    if len(candidates) > 100:
        raise ValueError('Planning paving feature budget exceeded')
    if not candidates:
        raise ValueError('No source-supported paving footprints recovered')
    plaza_labels = [line for line in lines if line['text'].lower() == 'plaza']
    unmatched = [line for line in plaza_labels if not any(c['polygon'].covers(Point(
        (line['bbox'][0] + line['bbox'][2]) / 2, (line['bbox'][1] + line['bbox'][3]) / 2)) for c in candidates)]
    placement = {'status': 'provisional_shop_track_hypothesis', 'candidate': passing[0]['candidate'],
                 'printed_scale_m_per_pdf_point': scale, 'scale_adjusted_to_fit_map': False,
                 'hypotheses': hypotheses, 'shop_osm_id': shops[0]['id'], 'horizontal_operation': coordinate.report(),
                 'registration_verified': False, 'as_built_verified': False, 'vertical_datum_verified': False,
                 'independent_control_objects': 0,
                 'limitations': ['Named shop corners and track annotation centres are map agreement, not independent survey controls.',
                                 'The proposed site plan does not establish present-day as-built state or finished paving levels.']}
    return candidates, placement, {'fills': fills, 'patterns': patterns, 'source_plaza_labels': len(plaza_labels),
                                   'unmatched_plaza_labels': unmatched}


def append(output, quality, config, access, prepared):
    candidates, placement, extraction = recover(prepared['pdf'], prepared['raw'], prepared['operation'], prepared['bounds_wgs84'])
    records, terrain, paths, bounds = _read_inputs(output, access['component'], whole_area=True)
    scene = _scene(records, bounds)
    coordinate = OSTN15Transform(CRS.from_wkt(quality['crs']), 27700, prepared['operation'])
    def project(x, y, z=None):
        xy = apply_candidate(list(zip(x, y)), placement['candidate'])
        return coordinate.inverse(xy[:, 0], xy[:, 1])
    domain = box(bounds[0], bounds[1], bounds[2] + 1, bounds[3] + 1)
    proposed, source_features, local_features, cells = {}, [], [], {}
    decisions, checks = [], 0
    for index, candidate in enumerate(candidates):
        polygon = candidate['polygon']
        identifier = f'review/planning-paving/{index:03d}'
        labels = candidate.get('contained_labels', [])
        plaza = any(label.lower() == 'plaza' for label in labels)
        printed_brick = any(label.lower() == 'brick paving' for label in labels)
        brick = printed_brick or plaza or candidate['state'] == 'new'
        surface = 'brick' if brick else 'stone'
        properties = {k: v for k, v in candidate.items() if k != 'polygon'}
        properties.update(source_document_sha256=prepared['source']['document_sha256'], source_page=1,
            surface=surface, surface_role='labelled_plaza' if plaza else 'paving_footprint',
            material_basis='native brick paving label' if printed_brick else
                'Retained Wicker brick display rule from park_paving.wicker_paving; not printed constituent evidence' if brick else
                'Unspecified existing paving; retained stone display palette',
            registration_verified=False, as_built_verified=False, accepted_physical_geometry=False,
            finished_level_method='retained terrain surface; drawing spot levels not bound to these polygons')
        source_features.append({'type': 'Feature', 'id': identifier, 'geometry': mapping(polygon), 'properties': properties})
        local = transform(project, polygon)
        clipped = local.intersection(domain)
        local_features.append({'type': 'Feature', 'id': identifier, 'geometry': mapping(local), 'properties': properties})
        decision = {'feature_id': identifier, 'surface_role': properties['surface_role'], 'legend_state': candidate['state'],
                    'surface': surface, 'source_area_m2_at_printed_scale': polygon.area * placement['printed_scale_m_per_pdf_point'] ** 2,
                    'projected_area_m2': local.area, 'area_inside_pilot_m2': clipped.area,
                    'source_polygon_holes': sum(len(p.interiors) for p in (list(polygon.geoms) if polygon.geom_type == 'MultiPolygon' else [polygon])),
                    'excluded_cells': {}, 'source_grid_cells_in_pilot': 0, 'owned_cells': 0}
        decisions.append(decision)
        covered = set(); cells[identifier] = covered
        if clipped.is_empty:
            continue
        x0, z0, x1, z1 = clipped.bounds
        counts = Counter()
        for x in range(math.floor(x0), math.ceil(x1)):
            for z in range(math.floor(z0), math.ceil(z1)):
                checks += 1
                if checks > config['max_column_checks']:
                    raise ValueError('Planning paving column budget exceeded')
                if not clipped.covers(Point(x + .5, z + .5)):
                    continue
                decision['source_grid_cells_in_pilot'] += 1
                if access['footprint'].intersects(box(x, z, x + 1, z + 1)):
                    counts['review_building_footprint'] += 1; continue
                y = terrain.get((x, z)); key = x, y, z
                base = records.get(key)
                if y is None or base is None:
                    counts['missing_terrain'] += 1; continue
                if base['kind'] not in WALKING_KINDS | {'terrain'}:
                    counts['protected_road_parking_or_structure'] += 1; continue
                if (not scene.standing((x, z, 2 * y + 2))
                        and (key not in paths or _mapped_node(scene, key, paths[key], records) is None)):
                    counts['blocked_or_buried_surface'] += 1; continue
                covered.add(key)
                rank = (candidate['state'] == 'new', plaza, printed_brick)
                if key in proposed and proposed[key][0] >= rank:
                    continue
                row = {'x': x, 'y': y, 'z': z, 'kind': 'plaza' if plaza else 'path',
                       'feature': identifier, 'source': SOURCE_ID, 'material': palette_block(surface, x, z),
                       'material_origin': 'estimated_reconstruction_shell', 'review_surface_policy': SURFACE_POLICY,
                       'source_document_sha256': prepared['source']['document_sha256'], 'source_page': 1,
                       'accepted_physical_geometry': False, 'finished_level_verified': False}
                if key in paths and records.get(key) == paths[key]:
                    row['overlays_mapped_source_cell'] = {k: paths[key][k] for k in ('feature', 'x', 'y', 'z')}
                proposed[key] = rank, row
        decision['excluded_cells'] = dict(counts)
    rows = {key: value[1] for key, value in sorted(proposed.items())}
    if len(rows) > prepared['max_cells'] or quality['voxel_records'] + len(rows) > config['max_voxels']:
        raise ValueError('Planning paving voxel budget exceeded')
    for row in rows.values():
        decisions[int(row['feature'].rsplit('/', 1)[1])]['owned_cells'] += 1
    updated = {**records, **rows}
    after_scene = _scene(updated, bounds)
    if _mapped_nodes(scene, paths, records) != _mapped_nodes(after_scene, paths, updated):
        raise ValueError('Planning paving would lose an existing mapped walking surface')
    if any(_mapped_node(after_scene, key, row, updated) is None for key, row in rows.items()):
        raise ValueError('Planning paving would lose support or headroom')
    with (output / 'voxels.jsonl').open('a', encoding='utf-8') as stream:
        for row in rows.values():
            stream.write(json.dumps(row) + '\n')
    collection = json.loads((output / 'features-local.geojson').read_text())
    collection['features'] += local_features
    (output / 'features-local.geojson').write_text(json.dumps(collection, indent=2) + '\n', encoding='utf-8')
    _write(output / 'planning-surfaces-source.geojson', {'type': 'FeatureCollection', 'coordinate_frame': 'unrotated PDF points, x right/y down', 'features': source_features})
    _write(output / 'planning-surfaces-local.geojson', {'type': 'FeatureCollection', 'coordinate_frame': 'local x east/z north, metres', 'features': local_features})
    report = {'version': SURFACE_POLICY, 'status': 'awaiting_native_readback', 'source': prepared['source'],
              'placement': placement, 'extraction': extraction, 'features': decisions,
              'recovered_features': len(candidates), 'labelled_plaza_features': sum(d['surface_role'] == 'labelled_plaza' for d in decisions),
              'added_paving_records': len(rows), 'terrain_repaint_cells': sum(records[k]['kind'] == 'terrain' for k in rows),
              'scanned_candidate_columns': checks, 'source_coverage': 'supported paving subset; not a complete physical area inventory',
              'mapped_paving_finish_cells': sum('overlays_mapped_source_cell' in row for row in rows.values()),
              'overlap_rule': 'Proposed footprints, then labelled plazas, then printed brick; stable source order breaks ties.',
              'source_building_records_modified': 0, 'terrain_heights_modified': 0, 'source_geometry_stretched': False,
              'finished_paving_levels_verified': False, 'accepted_physical_geometry': False,
              'training_labels_generated': 0, 'minecraft_playtest': 'not_performed'}
    quality['voxel_records'] += len(rows)
    from .cli import file_sha256
    quality['sha256'] = file_sha256(output / 'voxels.jsonl')
    quality['planning_surfaces_review'] = report
    _write(output / 'planning-surfaces-review.json', report)
    mask = unary_union([box(x, z, x + 1, z + 1) for x, _, z in rows])
    return {'report': report, 'rows': rows, 'feature_cells': cells, 'walking_mask': mask}


def verify(output, scene, records, paths, spawn, offset, navigation, prepared):
    for key, row in prepared['rows'].items():
        if records.get(key) != row or _mapped_node(scene, key, row, records) is None:
            raise ValueError('Saved planning paving lost its source row, bearing support or headroom')
    mapped = _mapped_nodes(scene, paths, records)
    review = _review_surface_nodes(scene, records)
    walking = _walking_nodes(scene, mapped, records)
    any_reached, _ = _tree(scene, spawn)
    paving_reached, _ = _tree(scene, spawn, walking)
    report = prepared['report']
    for feature in report['features']:
        nodes = {_mapped_node(scene, key, records[key], records) for key in prepared['feature_cells'][feature['feature_id']]}
        nodes.discard(None)
        feature.update(native_supported_footprint_cells=len(nodes),
                       reachable_cells_any_walking=len(nodes & any_reached.keys()),
                       reachable_cells_on_walking_surfaces=len(nodes & paving_reached.keys()))
        feature['status'] = ('outside_or_no_emitted_cells' if not nodes else 'reachable_on_walking_surfaces'
            if nodes <= paving_reached.keys() else 'reachable_using_other_surfaces' if nodes <= any_reached.keys() else 'partial_or_unresolved')
        if feature['surface_role'] == 'labelled_plaza':
            allowed = (lambda p: p in walking) if nodes & paving_reached.keys() else None
            route = _shortest_path(scene, [spawn], lambda p: p in nodes, allowed)
            feature['walkthrough'] = {'status': 'native_route_ready' if route else 'unresolved',
                'surface_scope': 'walking_surfaces_only' if allowed else 'includes_other_surfaces',
                'horizontal_length_m': len(route) - 1 if route else None,
                'route_local_x_z_half_y': [list(p) for p in route],
                'route_native_xyz': [[x + .5, h / 2 + offset, -z + .5] for x, z, h in route],
                'minecraft_playtest': 'not_performed'}
    report.update(status='native_paving_verified', native_readback={'status': 'completed',
        'verified_paving_cells': len(review), 'reachable_cells_any_walking': len(set(review) & any_reached.keys()),
        'reachable_cells_on_walking_surfaces': len(set(review) & paving_reached.keys()),
        'mapped_cells_supported': len(mapped), 'all_planned_materials_verified': True,
        'minecraft_playtest': 'not_performed'})
    _write(output / 'planning-surfaces-review.json', report)


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
