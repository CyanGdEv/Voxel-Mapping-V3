"""Recover exact straight native fill/clip intersections as unplaced candidates."""
from collections import Counter
import hashlib
import json
import math

import pymupdf
from shapely.geometry import box, mapping, Polygon, shape
from .drawing_footprints import rings_from_path, fill_geometry

VERSION = 'straight-clipped-plan-fills-v1'
GAP_VERSION = 'located-fill-discontinuities-v2'


def discontinuities(candidate, unit):
    """Nominal gaps between aligned filled strips; never classified as doors."""
    from shapely.geometry import shape
    if not math.isfinite(unit) or unit <= 0:
        raise ValueError('Finite positive nominal scale required')
    g = shape(candidate['geometry'])
    if g.geom_type != 'MultiPolygon' or candidate['fill_color'] == [1., 1., 1.] or candidate['fill_color'] == (1., 1., 1.):
        return []
    parts = list(g.geoms)
    if not 2 <= len(parts) <= 100:
        return []
    rectangles = []
    for part in parts:
        if part.interiors:
            return []
        rectangle = part.minimum_rotated_rectangle
        points = list(rectangle.exterior.coords)
        lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
        longest = max(range(4), key=lambda i: lengths[i]); width = min(lengths)
        if lengths[longest] < 3 * width or not .08 <= width * unit <= 1 or part.area < rectangle.area * .85:
            return []
        a, b = points[longest], points[longest + 1]
        rectangles.append((lengths[longest], ((b[0] - a[0]) / lengths[longest], (b[1] - a[1]) / lengths[longest])))
    _, axis = max(rectangles, key=lambda x: x[0]); normal = (-axis[1], axis[0])
    if axis[0] < 0 or (axis[0] == 0 and axis[1] < 0):
        axis = (-axis[0], -axis[1]); normal = (-axis[1], axis[0])
    if any(abs(axis[0] * direction[0] + axis[1] * direction[1]) < math.cos(math.radians(.5)) for _, direction in rectangles):
        return []
    intervals = []
    for index, part in enumerate(parts):
        ts = [p[0] * axis[0] + p[1] * axis[1] for p in part.exterior.coords]
        ss = [p[0] * normal[0] + p[1] * normal[1] for p in part.exterior.coords]
        intervals.append((min(ts), max(ts), min(ss), max(ss), index))
    if max(i[2] for i in intervals) - min(i[2] for i in intervals) > 1 or max(i[3] for i in intervals) - min(i[3] for i in intervals) > 1:
        return []
    result = []; intervals.sort()
    for left, right in zip(intervals, intervals[1:]):
        gap = right[0] - left[1]
        if gap <= 0:
            continue
        low, high = max(left[2], right[2]), min(left[3], right[3])
        if high <= low:
            continue
        def point(t, s):
            return [t * axis[0] + s * normal[0], t * axis[1] + s * normal[1]]
        corridor = Polygon([point(left[1], low), point(right[0], low),
                            point(right[0], high), point(left[1], high)])
        result.append({'fill_candidate_id': candidate['id'], 'left_polygon_part': left[4], 'right_polygon_part': right[4],
                       'recipe_version': GAP_VERSION,
                       'coordinate_frame': candidate.get('coordinate_frame', 'unrotated_mupdf_points_y_down'),
                       'gap_corridor_geometry': mapping(corridor),
                       'projected_gap_endpoints': [point(left[1], (low + high) / 2), point(right[0], (low + high) / 2)],
                       'physical_attachment_points_verified': False,
                       'nominal_gap_width_m': gap * unit, 'axis_candidate': list(axis),
                       'projection_interval_pdf_points': [left[1], right[0]],
                       'basis': 'disjoint aligned thin fill parts; width measured by projected source extents',
                       'candidate_recipe': {'maximum_axis_difference_degrees': .5, 'maximum_transverse_extent_difference_pdf_points': 1,
                                            'minimum_aspect_ratio': 3, 'nominal_thickness_range_m': [.08, 1],
                                            'minimum_rotated_rectangle_area_fraction': .85},
                       'status': 'unverified_fill_strip_discontinuity', 'opening_type': None,
                       'door_or_window_identity_verified': False, 'height_m': None,
                       'scale_verified': False, 'geometry_bridge_added': False, 'world_geometry_additions': 0})
    return result


def audit_discontinuities(candidates, unit):
    """Locate gaps and retain intersecting native fills, without certifying visibility."""
    if len(candidates) > 4000:
        raise ValueError('Gap audit candidate budget exceeded')
    geometries = [shape(c['geometry']) for c in candidates]
    from shapely.strtree import STRtree
    tree = STRtree(geometries)
    result = []; comparisons = 0
    for candidate in candidates:
        for gap in discontinuities(candidate, unit):
            corridor = shape(gap['gap_corridor_geometry']); overlaps = []
            for index in sorted(tree.query(corridor).tolist()):
                other = candidates[index]
                if other['id'] == candidate['id']:
                    continue
                comparisons += 1
                if comparisons > 100000:
                    raise ValueError('Gap overlap audit budget exceeded')
                intersection = corridor.intersection(geometries[index])
                if intersection.area <= 0:
                    continue
                overlaps.append({'fill_candidate_id': other['id'], 'paint_seqno': other.get('paint_seqno'),
                                 'fill_color': other['fill_color'],
                                 'gap_area_fraction': intersection.area / corridor.area,
                                 'intersection_geometry': mapping(intersection)})
            result.append({**gap, 'intersecting_fill_candidates': overlaps,
                           'visibility_review_status': 'intersecting_fills_require_review' if overlaps else 'no_retained_fill_overlap',
                           'complete_page_visibility_verified': False})
    return result


def recover(page, sha, number):
    paths = page.get_drawings(extended=True)
    if len(paths) > 100000:
        raise ValueError('Clipped-fill path budget exceeded')
    # All MuPDF paths and text traces share unrotated page coordinates.
    frame = box(0, 0, page.cropbox.width, page.cropbox.height)
    clips = []; groups = []; records = []; counts = Counter(); total_points = 0; overlay_count = 0
    def budget_error(error):
        return 'budget exceeded' in str(error)
    def bounded(g):
        polygons = list(g.geoms) if g.geom_type == 'MultiPolygon' else [g] if g.geom_type == 'Polygon' else []
        if sum(len(p.exterior.coords) + sum(len(r.coords) for r in p.interiors) for p in polygons) > 10000:
            raise ValueError('Clipped result vertex budget exceeded')
        return g
    def geometry(path):
        nonlocal total_points
        rings = rings_from_path({**path, 'type': 'f'}, pymupdf.Matrix(1, 1), 10000)
        total_points += sum(len(r) for r in rings)
        if total_points > 500000:
            raise ValueError('Page fill/clip point budget exceeded')
        if len(rings) > 100:
            raise ValueError('Fill/clip ring budget exceeded')
        g = fill_geometry(rings, path.get('even_odd', False), True)
        if g.is_empty or not g.is_valid or g.geom_type not in ('Polygon', 'MultiPolygon'):
            raise ValueError('Invalid fill/clip topology')
        return bounded(g), rings
    for ordinal, path in enumerate(paths):
        level = path.get('level', 0)
        clips = [c for c in clips if c['level'] < level]
        groups = [g for g in groups if g < level]
        if path['type'] == 'group':
            groups.append(level); continue
        if path['type'] == 'clip':
            if len(clips) >= 16:
                raise ValueError('Clip depth budget exceeded')
            candidate = {'level': level, 'path_ordinal': ordinal, 'geometry': None}
            try:
                if path.get('layer'):
                    raise ValueError('Optional clip layer state unknown')
                g, rings = geometry(path)
                candidate.update(geometry=g, source_rings=rings, even_odd=path.get('even_odd', False))
            except ValueError as error:
                if budget_error(error):
                    raise
                candidate['reason'] = str(error)
            clips.append(candidate); continue
        if 'f' not in path['type']:
            continue
        if groups or any(c['geometry'] is None for c in clips):
            counts['unsupported_clip_or_compositing_scope'] += 1; continue
        if path.get('layer') or path.get('fill_opacity') != 1:
            counts['optional_layer_or_nonopaque_fill'] += 1; continue
        try:
            fill, rings = geometry(path)
            result = fill.intersection(frame)
            for clip in clips:
                overlay_count += 1
                if overlay_count > 10000:
                    raise ValueError('Clip intersection budget exceeded')
                result = bounded(result.intersection(clip['geometry']))
            if result.is_empty:
                counts['empty_clipped_fill'] += 1; continue
            if result.geom_type not in ('Polygon', 'MultiPolygon') or not result.is_valid:
                raise ValueError('Unsupported clipped result topology')
            polygons = list(result.geoms) if result.geom_type == 'MultiPolygon' else [result]
            if sum(len(p.exterior.coords) + sum(len(r.coords) for r in p.interiors) for p in polygons) > 10000:
                raise ValueError('Clipped result vertex budget exceeded')
            if result.area < 16 or result.area > frame.area * .7:
                counts['small_symbol_or_sheet_fill'] += 1; continue
            clip_refs = [{'path_ordinal': c['path_ordinal'], 'level': c['level'],
                          'source_rings': c['source_rings'], 'even_odd': c['even_odd']} for c in clips]
            identity = [VERSION, sha, number, ordinal, path.get('seqno'), result.normalize().wkb_hex]
            records.append({'id': hashlib.sha256(json.dumps(identity).encode()).hexdigest(),
                            'document_sha256': sha, 'page': number, 'paint_ordinal': ordinal,
                            'paint_seqno': path.get('seqno'), 'fill_source_rings': rings,
                            'fill_even_odd': path.get('even_odd', False), 'fill_color': path.get('fill'),
                            'fill_opacity': path['fill_opacity'], 'clip_references': clip_refs,
                            'geometry': json.loads(json.dumps(mapping(result))),
                            'coordinate_frame': 'unrotated_mupdf_points_y_down',
                            'area_pdf_points_squared': result.area, 'polygon_parts': len(polygons),
                            'status': 'unverified_clipped_fill_geometry_candidate' if clips else 'unverified_native_fill_geometry_candidate',
                            'clipping_geometry_supported': True, 'later_overpaint_visibility_verified': False,
                            'physical_component_identity_verified': False, 'accepted_feature': False,
                            'world_geometry_additions': 0})
            if len(records) > 4000:
                raise ValueError('Clipped-fill candidate budget exceeded')
        except ValueError as error:
            # A geometry error is local; an output budget failure aborts this page.
            if budget_error(error):
                raise
            counts[str(error)] += 1
    counts.update(candidate_fills=len(records), clipped_fills=sum(bool(r['clip_references']) for r in records))
    return {'version': VERSION, 'candidates': records, 'counts': dict(counts),
            'geometry_snapping_or_gap_bridging': False, 'world_geometry_additions': 0}
