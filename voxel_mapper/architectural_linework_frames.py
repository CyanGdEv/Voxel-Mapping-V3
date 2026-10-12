"""Exact closed source rectangles around captions; drawing-frame hypotheses only."""
from collections import Counter
import hashlib
import json
from shapely.geometry import Polygon, shape, mapping
from shapely.strtree import STRtree
from .architectural_graph import VERSION as GRAPH_VERSION
from .architectural_view_layout import VERSION as LAYOUT_VERSION

VERSION = 'architectural-linework-frames-v1'


def review(graph, layout, *, max_checks=100000):
    if type(max_checks) is not int or not 1 <= max_checks <= 100000:
        raise ValueError('Bounded linework checks required')
    graph_hash = hashlib.sha256(json.dumps(graph, sort_keys=True).encode()).hexdigest()
    if (graph['version'] != GRAPH_VERSION or graph['status'] != 'source_drawing_topology_only'
            or layout['version'] != LAYOUT_VERSION or layout['source_graph_sha256'] != graph_hash
            or graph['document_sha256'] != layout['document_sha256'] or graph['page'] != layout['page']
            or graph['coordinate_frame'] != 'pdf_native_points_y_up'
            or layout['coordinate_frame'] != 'pdf_native_points_y_up'):
        raise ValueError('Matching complete native graph and layout required')
    components = graph['source_components']
    geometries = [shape(r['geometry']) for r in components]
    index = STRtree(geometries)
    captions = layout['view_captions']
    labels = [shape(r['label_geometry']) for r in captions]
    label_index = STRtree(labels)
    records = []; checks = 0
    for source, geom in zip(components, geometries):
        checks += 1
        if checks > max_checks: break
        # Only original closed straight rings qualify. Never close gaps or combine paths.
        if source.get('curve_approximation', {}).get('cubic_segments', 0): continue
        if geom.geom_type == 'Polygon':
            if geom.interiors: continue
            coords = list(geom.exterior.coords)
        elif geom.geom_type == 'LineString' and geom.is_ring:
            coords = list(geom.coords)
        else: continue
        if len(coords) != 5 or len(set(coords[:-1])) != 4: continue
        if any(a[0] != b[0] and a[1] != b[1] for a, b in zip(coords, coords[1:])): continue
        region = Polygon(coords)
        if not region.is_valid or region.area <= 0: continue
        hits = []; contained = []
        for k in label_index.query(region, predicate='intersects'):
            checks += 1
            if checks > max_checks: break
            k = int(k); hits.append(captions[k]['id'])
            if region.contains(labels[k]): contained.append(captions[k]['id'])
        if checks > max_checks: break
        if not hits: continue
        row = {'source_component_id': source['id'], 'geometry': mapping(region),
               'intersecting_caption_ids': sorted(hits), 'containing_caption_ids': sorted(contained),
               'status': 'competing_or_crossing_captions', 'component_membership': [],
               'view_scope_verified': False, 'scale_application_verified': False}
        if len(hits) == 1 and hits == contained:
            caption = next(r for r in captions if r['id'] == hits[0])
            row['status'] = ('closed_source_frame_caption_candidate' if
                caption['glyph_screen']['status'] == 'raster_consistent_candidate' else 'caption_visibility_withheld')
        for k in index.query(region, predicate='intersects'):
            checks += 1
            if checks > max_checks: break
            k = int(k)
            row['component_membership'].append({'component_id': components[k]['id'],
                'status': 'whole_component_inside_frame' if region.covers(geometries[k]) else 'frame_boundary_crossing'})
        row['component_membership'].sort(key=lambda r: r['component_id'])
        records.append(row)
        if checks > max_checks: break
    exhausted = checks > max_checks
    if exhausted: records = []
    multiplicity = Counter(c for r in records for c in r['intersecting_caption_ids'])
    for row in records:
        if row['status'] == 'closed_source_frame_caption_candidate' and multiplicity[row['containing_caption_ids'][0]] != 1:
            row['status'] = 'competing_source_frames'
    return {'version': VERSION, 'document_sha256': graph['document_sha256'], 'page': graph['page'],
        'coordinate_frame': graph['coordinate_frame'], 'source_graph_sha256': graph_hash,
        'source_layout_sha256': hashlib.sha256(json.dumps(layout, sort_keys=True).encode()).hexdigest(),
        'status': 'linework_frame_budget_withheld' if exhausted else 'source_linework_frame_hypotheses_only',
        'frames': records, 'checks': checks, 'max_checks': max_checks,
        'counts': dict(Counter(r['status'] for r in records)),
        'view_scope_verified': False, 'scale_application_verified': False, 'world_geometry_additions': 0,
        'limitations': ['Exact axis-aligned source rectangles only; no snapping, gap joining or inferred hulls.',
            'A rectangle containing a caption may be a table or title block, not a drawing-view boundary.',
            'Source paint is not proof of visible frame semantics. No dimensions or physical geometry are promoted.']}
