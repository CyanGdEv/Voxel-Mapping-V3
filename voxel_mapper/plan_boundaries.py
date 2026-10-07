"""Renderer-resolved straight plan boundary candidates, never world features."""
from collections import defaultdict
import re

from shapely.geometry import LineString, Polygon, Point, mapping
from shapely.ops import polygonize


def recover_boundaries(drawings, labels=(), min_area=25, max_area=500000, max_paths=100000):
    if len(drawings) > max_paths:
        raise ValueError('Rendered drawing path budget exceeded')
    groups = defaultdict(list)
    segment_count = 0
    clipped = curves = 0
    scopes = []
    for path in drawings:
        level = path.get('level', 0)
        scopes = [s for s in scopes if s['level'] < level]
        if path['type'] in ('clip', 'group'):
            scopes.append(path)
            continue
        # A scissor rectangle alone cannot reconstruct arbitrary clip geometry.
        if scopes or path.get('layer') or (path.get('stroke_opacity') or 0) < 1:
            clipped += 1
            continue
        if path['type'] != 's' or path.get('dashes', '[] 0') != '[] 0':
            continue
        if any(item[0] not in ('l', 're', 'qu') for item in path['items']):
            curves += 1
            continue
        key = (tuple(path.get('color') or ()), round(path.get('width', 0), 4))
        for item in path['items']:
            if item[0] == 'l':
                points = [tuple(item[1]), tuple(item[2])]
            elif item[0] == 're':
                x0, y0, x1, y1 = item[1]
                points = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
            else:
                quad = item[1]
                points = [tuple(quad.ul), tuple(quad.ur), tuple(quad.lr), tuple(quad.ll), tuple(quad.ul)]
            line = LineString(points)
            if line.is_valid and line.length:
                groups[key].append(line)
                segment_count += 1
                if segment_count > 250000:
                    raise ValueError('Plan segment budget exceeded')
    polygons = []
    seen = set()
    for key, lines in groups.items():
        for polygon in polygonize(lines):
            if not polygon.is_valid or not min_area <= polygon.area <= max_area:
                continue
            identity = polygon.normalize().wkb
            if identity in seen:
                continue
            seen.add(identity)
            evidence = []
            for label in labels:
                text = re.sub(r'\s+', ' ', label['text'].strip().lower())
                semantic = {'tarmac': 'asphalt', 'asphalt': 'asphalt', 'concrete': 'concrete',
                            'brick paved': 'paving_stones', 'block paving': 'paving_stones',
                            'building': 'building', 'brick building': 'building'}.get(text)
                if semantic and polygon.contains(Point(label['origin'])):
                    evidence.append({'text': label['text'], 'candidate_semantic': semantic})
            polygons.append({'geometry': mapping(polygon), 'area_pdf_points2': polygon.area,
                             'stroke_rgb': list(key[0]), 'stroke_width_points': key[1],
                             'contained_label_evidence': evidence,
                             'semantic_status': 'unverified', 'registration_verified': False})
            if len(polygons) > 2000:
                raise ValueError('Plan polygon candidate budget exceeded')
    return {'status': 'unregistered_plan_boundary_candidates', 'polygons': polygons,
            'world_geometry_additions': 0, 'coordinate_space': 'MuPDF unrotated page points, y downward',
            'skipped_scoped_or_hidden_paths': clipped, 'skipped_curve_paths': curves,
            'limitations': ['Exact straight-stroke closure only; no snapping or bridging gaps',
                           'Clipped/grouped/optional-layer and curved paths withheld',
                           'Closed boundaries and contained labels do not establish physical semantics']}


def inspect_plan_boundaries(payload, page_number=0):
    import fitz
    with fitz.open(stream=payload, filetype='pdf') as document:
        page = document[page_number]
        drawings = page.get_drawings(extended=True)
        labels = []
        for block in page.get_text('dict')['blocks']:
            for line in block.get('lines', []):
                for span in line['spans']:
                    labels.append({'text': span['text'], 'origin': span['origin']})
                    if len(labels) > 20000:
                        raise ValueError('Plan label budget exceeded')
        return recover_boundaries(drawings, labels)
