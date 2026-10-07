"""Legend-associated filled paving polygons; provisional geometry only."""
import gzip
import json
import math
import re
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Polygon, Point, box, mapping
from shapely.ops import transform

from .wicker_registration import apply_candidate


def painted_polygon(path):
    """Resolve straight PDF fill/clip subpaths, including even-odd holes."""
    rings, current = [], []
    for item in path.get('items', []):
        if item[0] == 're':
            if current:
                if len(current) < 3: return None
                rings.append(Polygon(current)); current = []
            rings.append(box(*item[1]))
        elif item[0] == 'l':
            start, end = tuple(item[1]), tuple(item[2])
            if current and current[-1] != start:
                if len(current) < 3: return None
                rings.append(Polygon(current)); current = []
            if not current:
                current.append(start)
            current.append(end)
        else:
            return None  # Curves and unknown subpath operations are withheld.
    if current:
        if len(current) < 3:
            return None
        rings.append(Polygon(current))
    if not rings or any(not r.is_valid or r.is_empty or r.area == 0 for r in rings):
        return None
    if len(rings) > 1 and not path.get('even_odd'):
        return None  # Do not guess winding-rule holes.
    result = rings[0]
    for ring in rings[1:]:
        # Crossing rings require a richer path interpreter, not repairs.
        if result.boundary.crosses(ring.boundary):
            return None
        result = result.symmetric_difference(ring)
    return result if not result.is_empty and result.is_valid and result.geom_type in ('Polygon', 'MultiPolygon') else None


def visible_fills(vectors, max_paths=150_000):
    if len(vectors) > max_paths:
        raise ValueError('Surface vector budget exceeded')
    scopes, fills = [], []
    withheld = 0
    for index, path in enumerate(vectors):
        level = path.get('level', 0)
        scopes = [scope for scope in scopes if scope[0] < level]
        if path['type'] in ('clip', 'group'):
            polygon = painted_polygon(path) if path['type'] == 'clip' and not path.get('layer') else None
            scopes.append((level, polygon))
            continue
        if path['type'] not in ('f', 'fs') or path.get('fill') is None:
            continue
        if path.get('layer') or path.get('fill_opacity') != 1 or any(p is None for _, p in scopes):
            withheld += 1; continue
        polygon = painted_polygon(path)
        if polygon is None:
            withheld += 1; continue
        for _, clip in scopes:
            polygon = polygon.intersection(clip)
        if polygon.is_empty or polygon.geom_type not in ('Polygon', 'MultiPolygon'):
            continue
        fills.append({'polygon': polygon, 'fill': path['fill'],
                      'vector_index': index, 'sequence': path.get('seqno')})
    return fills, withheld


def extract_surfaces(vectors, annotations, scale):
    if not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0:
        raise ValueError('A finite positive printed drawing scale is required')
    fills, withheld = visible_fills(vectors)
    legends, candidates = [], []
    excluded_text_masks, identities = set(), set()
    for label in annotations:
        match = re.fullmatch(r'(Existing|New) Paving with levels', label['text'], re.I)
        if not match:
            continue
        x0, y0, x1, y1 = label['bbox']
        swatches = []
        for fill in fills:
            a, b, c, d = fill['polygon'].bounds
            if (0 <= x0-c <= 100 and max(b, y0) < min(d, y1)
                    and 20 <= c-a <= 120 and 10 <= d-b <= 60):
                swatches.append(fill)
        legend = {'text': label['text'], 'bbox': label['bbox'], 'state': match[1].lower(),
                  'status': 'unique_filled_swatch' if len(swatches) == 1 else 'withheld_no_unique_filled_swatch'}
        if len(swatches) == 1:
            swatch = swatches[0]
            legend.update(fill_rgb=swatch['fill'], swatch_sequence=swatch['sequence'])
            for fill in fills:
                polygon = fill['polygon']
                if fill['fill'] != swatch['fill'] or fill['vector_index'] == swatch['vector_index']:
                    continue
                if any(max(abs(a-b) for a, b in zip(polygon.bounds, annotation['bbox'])) <= 2
                       for annotation in annotations):
                    excluded_text_masks.add(fill['vector_index'])
                    continue
                identity = (legend['state'], polygon.normalize().wkb)
                if identity in identities:
                    continue
                if not 2 <= polygon.area*scale**2 <= 10000:
                    continue
                # Only the plan side of this legend column, never title/legend artwork.
                if polygon.bounds[2] >= swatch['polygon'].bounds[0]:
                    continue
                labels = [a['text'] for a in annotations if a['text'].lower() in ('plaza', 'brick paving')
                          and polygon.contains(Point((a['bbox'][0]+a['bbox'][2])/2, (a['bbox'][1]+a['bbox'][3])/2))]
                identities.add(identity)
                candidates.append({'polygon': polygon, 'area_m2_printed_scale': polygon.area*scale**2,
                                   'state': legend['state'], 'legend_text': label['text'],
                                   'legend_sequence': swatch['sequence'], 'vector_sequence': fill['sequence'],
                                   'contained_labels': labels, 'material': None,
                                   'material_status': 'paving_legend_does_not_specify_material'})
        legends.append(legend)
    # A shared colour cannot distinguish existing work from a new proposal.
    states_by_colour = {}
    for legend in legends:
        if legend['status'] == 'unique_filled_swatch':
            states_by_colour.setdefault(tuple(legend['fill_rgb']), set()).add(legend['state'])
    conflicts = {colour for colour, states in states_by_colour.items() if len(states) > 1}
    conflicting_sequences = set()
    for legend in legends:
        if tuple(legend.get('fill_rgb', [])) in conflicts:
            legend['status'] = 'withheld_colour_shared_by_existing_and_new_legends'
            conflicting_sequences.add(legend['swatch_sequence'])
    candidates = [c for c in candidates if c['legend_sequence'] not in conflicting_sequences]
    return candidates, {'legends': legends, 'withheld_fill_paths': withheld,
                        'excluded_text_masks': len(excluded_text_masks)}


def inspect_surfaces(evidence, alignment, output):
    output = Path(output)
    report = {'status': 'unavailable', 'world_geometry_additions': 0,
              'registration_verified': False, 'as_built_verified': False}
    features = []
    try:
        if alignment['status'] != 'shop_track_alignment_hypothesis':
            raise ValueError('Drawing alignment hypothesis unavailable')
        document = next(d for d in evidence['documents'] if d.get('sha256') == alignment['document_id'])
        page = document['pages'][0]
        if document.get('status') != 'inspected' or page.get('rotation') != 0 or page.get('vector_status') != 'drawing_space_only':
            raise ValueError('Complete unrotated inspected drawing vectors required')
        with gzip.open(output/page['vector_file'], 'rt') as stream:
            candidates, detail = extract_surfaces(json.load(stream), page['annotations'],
                                                  alignment['printed_scale_m_per_pdf_point'])
        # PyMuPDF's drawing list exposes pattern clipping but omits the tile
        # paint itself. Read the original PDF paint/resource identity instead.
        try:
            from .wicker_patterns import extract_pattern_surfaces
            pattern_candidates,pattern_detail = extract_pattern_surfaces(
                Path(document['local_pdf']),page['annotations'],
                alignment['printed_scale_m_per_pdf_point'],document['sha256'])
            candidates += pattern_candidates
            detail['new_paving_pattern'] = pattern_detail
        except (KeyError,ValueError,OSError,StopIteration) as error:
            detail['new_paving_pattern'] = {'status':'withheld','reason':str(error)}
        inverse = Transformer.from_crs(27700, 4326, always_xy=True)
        def project(x, y, z=None):
            xy = apply_candidate(list(zip(x, y)), alignment['candidate'])
            return inverse.transform(xy[:, 0], xy[:, 1])
        for candidate in candidates:
            polygon = candidate.pop('polygon')
            properties = {**candidate, 'document_id': document['sha256'], 'page': page['page'],
                          'application_reference': document['applicationReference'],
                          'source_url': document['url'],
                          'kind': 'paving_polygon_candidate', 'registration_verified': False,
                          'as_built_verified': False, 'world_geometry_additions': 0}
            features.append({'type': 'Feature', 'geometry': mapping(transform(project, polygon)),
                             'properties': properties})
        report.update(status='legend_associated_surface_candidates', polygon_candidates=len(features),
                      labelled_plaza_candidates=sum(any(label.lower() == 'plaza' for label in f['properties']['contained_labels']) for f in features),
                      **detail)
    except (KeyError, ValueError, TypeError, OSError, StopIteration) as error:
        report['reason'] = str(error)
    (output/'wicker-man-surfaces.json').write_text(json.dumps(report, indent=2))
    (output/'wicker-man-surface-candidates.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': features}, indent=2))
    return report
