"""Exact connected planning linework with bounded source provenance; no snapping."""
import hashlib
import json

from shapely.geometry import LineString, mapping, Point
from shapely.ops import unary_union, linemerge, polygonize_full
from shapely.strtree import STRtree

VERSION = 'exact-plan-network-v2'
PROVENANCE_EPSILON = 1e-7


def straight_runs(parts):
    """Continuous straight coverage through junctions, with all junctions retained.

    This does not choose a turn at a branch or infer a closed component outline.
    An exactly connected, unique opposite collinear continuation is required.
    """
    segments = []; adjacency = {}
    for part in parts:
        for a, b in zip(part.coords, list(part.coords)[1:]):
            if a == b:
                continue
            i = len(segments); segments.append((a, b))
            for point in (a, b):
                adjacency.setdefault(point, []).append(i)
    if len(segments) > 100000:
        raise ValueError('Straight-run segment budget exceeded')
    continuations = {}; comparisons = 0
    for point, indices in adjacency.items():
        if len(indices) > 256:
            raise ValueError('Straight-run junction degree budget exceeded')
        for i in indices:
            a, b = segments[i]; other = b if point == a else a
            dx, dy = other[0] - point[0], other[1] - point[1]; length = (dx * dx + dy * dy) ** .5
            matches = []
            for j in indices:
                if i == j:
                    continue
                comparisons += 1
                if comparisons > 500000:
                    raise ValueError('Straight-run comparison budget exceeded')
                c, d = segments[j]; end = d if point == c else c
                ex, ey = end[0] - point[0], end[1] - point[1]
                if dx * ex + dy * ey < 0 and abs(dx * ey - dy * ex) / length <= PROVENANCE_EPSILON:
                    matches.append(j)
            if len(matches) == 1:
                continuations[(point, i)] = matches[0]
    continuations = {key: value for key, value in continuations.items()
                     if continuations.get((key[0], value)) == key[1]}
    visited = set(); runs = []
    for i, (a, b) in enumerate(segments):
        if i in visited:
            continue
        # Find an end without selecting a turn or bridging a gap.
        start = a; current = i; backward = set()
        while (start, current) in continuations:
            if current in backward:
                raise ValueError('Unexpected closed straight-run cycle')
            backward.add(current); following = continuations[(start, current)]
            c, d = segments[following]; start = d if start == c else c; current = following
        points = [start]; junctions = []; used = set()
        while current not in used:
            used.add(current); visited.add(current)
            c, d = segments[current]; end = d if points[-1] == c else c
            points.append(end)
            if len(adjacency[end]) > 2:
                junctions.append({'point': list(end), 'network_degree': len(adjacency[end])})
            following = continuations.get((end, current))
            if following is None:
                break
            current = following
        run = LineString(points)
        chord = LineString([points[0], points[-1]])
        if not chord.buffer(PROVENANCE_EPSILON).covers(run):
            continue
        runs.append((run, junctions))
    return runs


def recover(edges):
    if len(edges) > 20000:
        raise ValueError('Network source edge budget exceeded')
    if not edges:
        return {'version': VERSION, 'chains': [], 'straight_runs': [], 'faces': [], 'counts': {}, 'world_geometry_additions': 0}
    lines = [LineString(e['points']) for e in edges]
    if any(not g.is_valid or g.length <= 0 for g in lines):
        raise ValueError('Finite nondegenerate source segments required')
    index = STRtree(lines); pairs = 0
    for i, line in enumerate(lines):
        pairs += sum(int(j) > i for j in index.query(line, predicate='intersects'))
        if pairs > 100000:
            raise ValueError('Network intersection budget exceeded')
    network = unary_union(lines)
    parts = list(network.geoms) if hasattr(network, 'geoms') else [network]
    if sum(len(g.coords) for g in parts) > 200000:
        raise ValueError('Noded network point budget exceeded')
    merged = linemerge(network) if network.geom_type == 'MultiLineString' else network
    chains = list(merged.geoms) if hasattr(merged, 'geoms') else [merged]
    polygons, cuts, dangles, invalid = polygonize_full(network)
    if len(chains) > 20000 or len(polygons.geoms) > 4000:
        raise ValueError('Network output budget exceeded')

    def provenance(geometry):
        refs = []; coverage = []
        for i in index.query(geometry.buffer(PROVENANCE_EPSILON)):
            source = lines[int(i)]
            if source.buffer(PROVENANCE_EPSILON, cap_style=2).intersection(geometry).length <= 1e-6:
                continue
            refs.append(edges[int(i)]['id']); coverage.append(source)
            if len(refs) > 256:
                return None
        if not coverage or not unary_union(coverage).buffer(PROVENANCE_EPSILON).covers(geometry):
            return None
        return sorted(refs)

    def record(geometry, boundary):
        vertices = sum(len(g.coords) for g in boundary.geoms) if hasattr(boundary, 'geoms') else len(boundary.coords)
        if vertices > 10000:
            return None
        refs = provenance(boundary)
        if refs is None:
            return None
        return {'id': hashlib.sha256((VERSION + json.dumps(refs) + geometry.normalize().wkb_hex).encode()).hexdigest(),
                'geometry': json.loads(json.dumps(mapping(geometry))), 'source_edge_ids': refs,
                'coordinate_frame': 'unrotated_mupdf_points_y_down',
                'physical_component_identity_verified': False, 'accepted_feature': False,
                'world_geometry_additions': 0}

    chain_records = []; face_records = []; run_records = []; withheld = 0
    for chain in chains:
        result = record(chain, chain)
        if result is None:
            withheld += 1; continue
        a, b = chain.coords[0], chain.coords[-1]
        chord = LineString([a, b])
        # Only exactly supported collinear chains are length-match hypotheses.
        straight = not chain.is_ring and chord.length > 0 and chord.buffer(PROVENANCE_EPSILON).covers(chain)
        result.update(length_pdf_points=chain.length, straight_chain_candidate=straight,
                      closed=chain.is_ring, joining_basis='exact intersections and degree-two nodes; branches stop chains')
        chain_records.append(result)
    for run, junctions in straight_runs(parts):
        result = record(run, run)
        if result is None:
            withheld += 1; continue
        result.update(length_pdf_points=run.length, straight_chain_candidate=True,
                      junctions=junctions, joining_basis='exact connected unique opposite collinear continuation',
                      component_boundary_topology_verified=False)
        run_records.append(result)
    for polygon in polygons.geoms:
        if polygon.area < 16:
            continue
        result = record(polygon, polygon.boundary)
        if result is None:
            withheld += 1; continue
        result.update(area_pdf_points_squared=polygon.area, opening_count_candidate=len(polygon.interiors),
                      semantic_status='unclassified_enclosed_network_face')
        face_records.append(result)
    return {'version': VERSION, 'source_edges': edges, 'chains': sorted(chain_records, key=lambda r: r['id']),
            'straight_runs': sorted(run_records, key=lambda r: r['id']),
            'faces': sorted(face_records, key=lambda r: r['id']),
            'counts': {'source_segments': len(lines), 'intersection_pairs': pairs, 'noded_segments': len(parts),
                       'chains': len(chain_records), 'straight_chains': sum(r['straight_chain_candidate'] for r in chain_records),
                       'enclosed_faces': len(face_records), 'cuts': len(cuts.geoms), 'dangles': len(dangles.geoms),
                       'straight_runs': len(run_records),
                       'invalid_rings': len(invalid.geoms), 'provenance_or_vertex_budget_holds': withheld},
            'provenance_epsilon_pdf_points': PROVENANCE_EPSILON, 'geometry_snapping_or_gap_bridging': False,
            'world_geometry_additions': 0}


def containing_faces(network, point):
    from shapely.geometry import shape
    anchor = Point(point)
    return [r['id'] for r in network['faces'] if shape(r['geometry']).contains(anchor)]
