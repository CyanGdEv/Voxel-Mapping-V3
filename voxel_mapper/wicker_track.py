"""Route topology, ambiguous height bindings and real tunnel-outline candidates."""
import gzip
import json
import math
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Polygon, Point, mapping

from .wicker_registration import apply_candidate


# Reviewed against drawing 373/95/7 B: crossing marks need branch selection.
# These windows are drawing-specific hypotheses, never surveyed controls.
REVIEW_DOCUMENT = '1c5dc5b43ddf14de2d0b96d7970cee8197d115c46d6919ad74aa484c77a61a1d'
REVIEW_BRANCHES = {'LP5': (190, 215), 'HP5': (250, 270),
                   'HP2': (0, 20), 'HP7': (430, 450)}


def height_marker(vectors, bbox):
    """Find the drawing's circle with orthogonal crosshairs beside a label."""
    x0, y0, x1, y1 = bbox
    matches = []
    for index, drawing in enumerate(vectors):
        rect = drawing.get('rect')
        items = drawing.get('items', [])
        if not rect or len(items) != 4 or any(item[0] != 'c' for item in items):
            continue
        width, height = rect[2]-rect[0], rect[3]-rect[1]
        if not 5 <= width <= 16 or abs(width-height) > .1:
            continue
        cx, cy = (rect[0]+rect[2])/2, (rect[1]+rect[3])/2
        if not 0 <= x0-cx <= 20 or not y1-2 <= cy <= y1+10:
            continue
        crosses = []
        for nearby in vectors[max(0,index-2):index+3]:
            ni = nearby.get('items', [])
            if len(ni) != 1 or ni[0][0] != 'l':
                continue
            a,b = ni[0][1:]
            if (abs(a[1]-b[1]) < .1 and abs(a[1]-cy) < .3
                    and min(a[0],b[0]) < rect[0] and max(a[0],b[0]) > rect[2]):
                crosses.append('horizontal')
            if (abs(a[0]-b[0]) < .1 and abs(a[0]-cx) < .3
                    and min(a[1],b[1]) < rect[1] and max(a[1],b[1]) > rect[3]):
                crosses.append('vertical')
        if set(crosses) == {'horizontal','vertical'}:
            matches.append({'point_pdf': [cx,cy], 'pdf_vector_sequence':drawing['seqno']})
    return matches[0] if len(matches) == 1 else None


def reviewed_binding(binding, label, document_id):
    if document_id != REVIEW_DOCUMENT or label not in REVIEW_BRANCHES:
        return binding
    start,end = REVIEW_BRANCHES[label]
    choices = [c for c in binding.get('candidates', []) if start <= c['station_m'] <= end]
    if not choices:
        return binding
    return {**binding, 'status':'reviewed_plan_marker_binding',
            'nearest_candidate':min(choices,key=lambda c:c['distance_m']),
            'review_note':'Drawing crosshair reviewed at a track crossing; branch remains provisional',
            'review_station_window_m':[start,end], 'as_built_verified':False}


def ordered_route(ways, project):
    if not ways or len(ways) > 100:
        raise ValueError('Expected a bounded set of mapped track ways')
    endpoints, coordinates, identifiers = {}, {}, set()
    for way in ways:
        nodes, geometry = way.get('nodes', []), way.get('geometry', [])
        if way['id'] in identifiers or len(nodes) != len(geometry) or len(nodes) < 2 or len(nodes) > 20_000:
            raise ValueError('Duplicate or malformed track way')
        identifiers.add(way['id'])
        for node, point in zip(nodes, geometry):
            xy = (point['lon'], point['lat'])
            if node in coordinates and math.dist(coordinates[node], xy) > 1e-8:
                raise ValueError('Shared track node has conflicting coordinates')
            coordinates[node] = xy
        for node in (nodes[0], nodes[-1]):
            endpoints.setdefault(node, []).append(way['id'])
    if any(len(edges) != 2 for edges in endpoints.values()):
        raise ValueError('Track endpoints do not form an unbranched closed route')
    remaining = {way['id']: way for way in ways}
    first = remaining.pop(min(remaining))
    node_ids = first['nodes'][:]
    way_segments = [(first['id'], first.get('tags', {}).get('covered') == 'yes')]*(len(node_ids)-1)
    ordered_ids = [first['id']]
    while remaining:
        matches = [identifier for identifier in endpoints[node_ids[-1]] if identifier in remaining]
        if len(matches) != 1:
            raise ValueError('Disconnected or ambiguous track route')
        way = remaining.pop(matches[0])
        nodes = way['nodes'] if way['nodes'][0] == node_ids[-1] else way['nodes'][::-1]
        node_ids.extend(nodes[1:])
        way_segments.extend([(way['id'], way.get('tags', {}).get('covered') == 'yes')]*(len(nodes)-1))
        ordered_ids.append(way['id'])
    if node_ids[0] != node_ids[-1]:
        raise ValueError('Mapped track route is not closed')
    wgs84 = [coordinates[node] for node in node_ids]
    xy = [project(*point) for point in wgs84]
    stations, segments = [0.], []
    for i, (start, end) in enumerate(zip(xy, xy[1:])):
        length = math.dist(start, end)
        if not math.isfinite(length) or length <= 0:
            raise ValueError('Zero-length or nonfinite track segment')
        stations.append(stations[-1]+length)
        segments.append({'start': start, 'end': end, 'station_start_m': stations[-2],
                         'station_end_m': stations[-1], 'way_id': way_segments[i][0],
                         'mapped_covered': way_segments[i][1]})
    return {'ordered_way_ids': ordered_ids, 'route_length_m': stations[-1],
            'coordinates_wgs84': wgs84, 'segments': segments}


def bind_annotation(point, route, radius_m=5, ambiguity_margin_m=1, separate_station_m=10):
    matches = []
    for index, segment in enumerate(route['segments']):
        start, end = segment['start'], segment['end']
        dx, dy = end[0]-start[0], end[1]-start[1]
        fraction = max(0., min(1., ((point[0]-start[0])*dx+(point[1]-start[1])*dy)/(dx*dx+dy*dy)))
        nearest = [start[0]+fraction*dx, start[1]+fraction*dy]
        distance = math.dist(point, nearest)
        if distance <= radius_m:
            matches.append({'segment_index': index, 'distance_m': distance,
                            'segment_fraction': fraction,
                            'station_m': segment['station_start_m']+fraction*(segment['station_end_m']-segment['station_start_m']),
                            'nearest_xy': nearest, 'way_id': segment['way_id']})
    matches.sort(key=lambda match: match['distance_m'])
    if not matches:
        return {'status': 'outside_track_matching_radius', 'candidates': []}
    best = matches[0]
    alternatives = []
    for match in matches[1:]:
        difference = abs(match['station_m']-best['station_m'])
        separation = min(difference, route['route_length_m']-difference)
        if separation > separate_station_m and match['distance_m'] <= best['distance_m']+ambiguity_margin_m:
            alternatives.append(match)
    return {'status': 'ambiguous_route_section' if alternatives else 'provisional_annotation_binding',
            'nearest_candidate': best, 'alternate_route_sections': alternatives, 'candidates': matches}


def filled_ring_candidate(drawing, label_bbox):
    """PDF fills close implicitly; open strokes alone are never bridged."""
    if drawing.get('type') not in ('f', 'fs') or drawing.get('fill') is None:
        return None
    items = drawing.get('items', [])
    if len(items) < 3 or any(item[0] != 'l' for item in items):
        return None
    if any(items[i][2] != items[i+1][1] for i in range(len(items)-1)):
        return None
    points = [item[1] for item in items]+[items[-1][2]]
    polygon = Polygon(points)  # Closing a painted fill follows PDF semantics.
    x0, y0, x1, y1 = label_bbox
    if not polygon.is_valid or not polygon.contains(Point((x0+x1)/2, (y0+y1)/2)):
        return None
    # Text knockout masks lie almost exactly around the annotation box.
    b = polygon.bounds
    if max(abs(a-c) for a, c in zip(b, label_bbox)) <= 2:
        return None
    if not drawing.get('color') or drawing.get('stroke_opacity', 0) <= 0:
        return None
    return polygon


def inspect_track(evidence, raw_osm, alignment, output):
    output = Path(output)
    report = {'status': 'unavailable', 'world_geometry_additions': 0,
              'height_profile_verified': False, 'registration_verified': False,
              'limitations': ['Drawing crosshairs and reviewed crossing branches remain unverified geographic height controls',
                             'OSM covered segments do not establish sound tunnel bounds or height',
                             'Ambiguous route matches cannot be assigned by nearest distance alone']}
    features = []
    try:
        if alignment['status'] != 'shop_track_alignment_hypothesis':
            raise ValueError('SW8 alignment hypothesis unavailable')
        page = next(d for d in evidence['documents'] if d.get('sha256') == alignment['document_id'])['pages'][0]
        project = Transformer.from_crs(4326, 27700, always_xy=True)
        inverse = Transformer.from_crs(27700, 4326, always_xy=True)
        ways = [way for way in raw_osm['elements'] if way.get('tags', {}).get('name') == 'Wicker Man'
                and way['tags'].get('roller_coaster') == 'track']
        route = ordered_route(ways, project.transform)
        with gzip.open(output/page['vector_file'], 'rt') as stream:
            vectors = json.load(stream)
        bindings = []
        for index in alignment['candidate']['matched_annotation_indices']:
            annotation = page['ride_level_candidates'][index]
            x0, y0, x1, y1 = annotation['bbox']
            marker = height_marker(vectors, annotation['bbox'])
            anchor = marker['point_pdf'] if marker else [(x0+x1)/2, (y0+y1)/2]
            point = apply_candidate([anchor], alignment['candidate'])[0]
            binding = bind_annotation(point, route)
            if marker:
                binding = reviewed_binding(binding, annotation['point_label'], alignment['document_id'])
            bindings.append({**binding, 'point_label': annotation['point_label'],
                             'printed_level_m': annotation['printed_level'], 'datum_label': 'not_established_by_site_plan',
                             'document_id': alignment['document_id'], 'source_bbox': annotation['bbox'],
                             'anchor_kind':'drawing_crosshair' if marker else 'annotation_centre',
                             'source_anchor_pdf':anchor,
                             'marker_vector_sequence':marker['pdf_vector_sequence'] if marker else None})
        ambiguous = sum(binding['status'] == 'ambiguous_route_section' for binding in bindings)
        report.update(status='route_association_candidates', ordered_way_ids=route['ordered_way_ids'],
                      route_length_m=route['route_length_m'], bindings=bindings,
                      provisional_bindings=sum(b['status'] == 'provisional_annotation_binding' for b in bindings),
                      reviewed_bindings=sum(b['status'] == 'reviewed_plan_marker_binding' for b in bindings),
                      drawing_marker_bindings=sum(b['anchor_kind'] == 'drawing_crosshair' for b in bindings),
                      ambiguous_bindings=ambiguous, profile_status='withheld_ambiguous_controls' if ambiguous else 'withheld_unverified_controls_and_datum')
        features.append({'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': route['coordinates_wgs84']},
                         'properties': {'kind': 'mapped_ordered_track_route', 'planning_geometry_verified': False}})
        labels = [a for a in page['annotations'] if a['text'] == 'Sound Tunnel']
        tunnels = {}
        for label in labels:
            for drawing in vectors:
                polygon = filled_ring_candidate(drawing, label['bbox'])
                if polygon is None:
                    continue
                dimensions = polygon.minimum_rotated_rectangle
                vertices = list(dimensions.exterior.coords)
                lengths = [math.dist(a, b)*alignment['printed_scale_m_per_pdf_point'] for a, b in zip(vertices, vertices[1:])]
                if not 1 <= min(lengths) <= 8 or not 5 <= max(lengths) <= 100:
                    continue
                tunnels[polygon.normalize().wkb] = (polygon, drawing, min(lengths), max(lengths))
        report['sound_tunnel_outline_candidates'] = len(tunnels)
        if len(tunnels) == 1:
            polygon, drawing, width, length = next(iter(tunnels.values()))
            xy = apply_candidate(list(polygon.exterior.coords), alignment['candidate'])
            properties = {'kind': 'sound_tunnel_footprint_candidate', 'document_id': alignment['document_id'],
                          'pdf_vector_sequence': drawing['seqno'], 'width_m_from_printed_scale': width,
                          'length_m_from_printed_scale': length, 'height_m': None,
                          'fill_closure': 'PDF implicit closure; not an inferred stroke',
                          'registration_verified': False, 'as_built_verified': False,
                          'world_geometry_additions': 0}
            features.append({'type': 'Feature', 'geometry': mapping(Polygon([inverse.transform(*point) for point in xy])), 'properties': properties})
            report['sound_tunnel'] = properties
    except (KeyError, OSError, ValueError, TypeError, IndexError, StopIteration) as error:
        report.update(status='unavailable', reason=str(error))
    (output/'wicker-man-track-association.json').write_text(json.dumps(report, indent=2))
    (output/'wicker-man-component-candidates.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': features}, indent=2))
    return report
