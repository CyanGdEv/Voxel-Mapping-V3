"""Original circle/V-head side references; complementary to corner markers.

Clipped fill rectangles are never reinterpreted as arrow shapes. Whole source
circle curves and both straight outline arms supply the candidate direction.
"""
import math

import numpy as np
import pymupdf
from scipy.spatial import cKDTree

from .drawing_views import resolve_identity, sheet_identity, text
from .glyph_visibility import screen_span
from .reconstruction_evidence_queue import digest

VERSION = 'native-side-view-reference-v1'


def page_references(page, *, sheet_metadata=None, max_checks=100000):
    if type(max_checks) is not int or not 1 <= max_checks <= 100000:
        raise ValueError('Bounded side-reference work required')
    result = {'version': VERSION, 'status': 'side_reference_candidates_only',
        'references': [], 'glyph_screens': {}, 'checks': 0, 'world_geometry_additions': 0}
    def charge():
        result['checks'] += 1
        if result['checks'] > max_checks:
            raise OverflowError('side_reference_work_budget')
    try:
        traces = page.get_texttrace(); paths = page.get_drawings()
        if len(traces) > 10000 or len(paths) > 100000 or sum(len(t['chars']) for t in traces) > 500000:
            raise OverflowError('side_reference_source_budget')
        identity = resolve_identity(traces, sheet_metadata); numbers = []
        for i, span in enumerate(traces):
            charge(); value = text(span)
            if value.isascii() and value.isdecimal() and 1 <= len(value) <= 3:
                numbers.append((i, span, int(value)))
        if len(numbers) > 5000:
            raise OverflowError('side_reference_numeric_budget')
        arms = {}; circles = []
        for i, path in enumerate(paths):
            charge()
            if path['type'] != 's' or path.get('layer') or path.get('stroke_opacity') != 1:
                continue
            items = path['items']
            if len(items) == 1 and items[0][0] == 'l':
                points = [list(p) for p in items[0][1:]]
                if not np.isfinite(points).all(): raise ValueError('Finite source arm endpoints required')
                key = tuple(sorted(tuple(p) for p in points))
                if key[0] != key[1]:
                    row = arms.setdefault(key, {'source_endpoints_page_points': points, 'source_path_indices': []})
                    row['source_path_indices'].append(i)
            elif len(items) == 4 and all(item[0] == 'c' for item in items):
                rect = path['rect']; radius = (rect.width + rect.height) / 4
                if (3 <= radius <= 40 and abs(rect.width - rect.height) <= .02 * radius
                        and math.dist(items[0][1], items[-1][-1]) <= .3):
                    circles.append((i, path, radius))
        arms = list(arms.values())
        if len(arms) > 20000 or len(circles) > 512:
            raise OverflowError('side_reference_primitive_budget')
        if not arms: return result
        tree = cKDTree([p for arm in arms for p in arm['source_endpoints_page_points']])
        for circle_index, circle, radius in circles:
            charge(); rect = circle['rect']; center = np.array(list((rect.tl + rect.br) * .5))
            inside = []
            for i, span, number in numbers:
                charge()
                if rect.contains(pymupdf.Rect(span['bbox'])): inside.append((i, span, number))
            if len(inside) != 1: continue
            sheet_index, sheet_span, sheet = inside[0]; possible = []
            near = sorted(set(j // 2 for j in tree.query_ball_point(center, 2 * radius)))
            for ai in near:
                charge(); points = np.array(arms[ai]['source_endpoints_page_points'])
                for base_index in (0, 1):
                    base, tip = points[base_index], points[1 - base_index]
                    if abs(np.linalg.norm(base - center) - radius) > .3:
                        continue
                    reach = float(np.linalg.norm(tip - center))
                    if not 1.1 * radius <= reach <= 2 * radius: continue
                    axis = (tip - center) / reach; normal = np.array([-axis[1], axis[0]])
                    for bj in sorted(set(j // 2 for j in tree.query_ball_point(tip, .25))):
                        charge()
                        if bj <= ai: continue
                        other = np.array(arms[bj]['source_endpoints_page_points'])
                        distances = np.linalg.norm(other - tip, axis=1); ti = int(np.argmin(distances))
                        other_base = other[1 - ti]; relative = np.array([base - center, other_base - center])
                        if (distances[ti] > .25 or abs(np.linalg.norm(other_base - center) - radius) > .3
                                or np.prod(relative @ normal) >= 0
                                or max(abs(relative @ normal)) < .25 * radius
                                or min(relative @ axis) < .2 * radius):
                            continue
                        for vi, span, view in numbers:
                            charge()
                            if vi == sheet_index or not 1 <= view <= 99 or span['dir'] != sheet_span['dir']:
                                continue
                            label_center = np.array(list((pymupdf.Rect(span['bbox']).tl + pymupdf.Rect(span['bbox']).br) * .5))
                            delta = label_center - tip
                            if not 0 < delta @ axis <= 2 * span['size'] or abs(delta @ normal) > .5 * span['size']:
                                continue
                            possible.append({'target_view_candidate': view, 'view_number_trace_index': vi,
                                'head_arm_indices': [ai, bj], 'head_source_arms': [arms[ai], arms[bj]],
                                'head_points_page_points': [base.tolist(), tip.tolist(), other_base.tolist()],
                                'head_tip_junction_gap_pdf_points': float(distances[ti]),
                                'source_aim_unit_vector_page': axis.tolist()})
            # Duplicate original arm paints were coalesced only by exact endpoints,
            # retaining every source path witness. Competing heads/indexes stay held.
            if not possible: continue
            indices = [sheet_index] + sorted({p['view_number_trace_index'] for p in possible})
            if identity and 'trace_index' in identity and not identity.get('identity_basis'):
                indices.append(identity['trace_index'])
            for index in indices:
                if index not in result['glyph_screens']:
                    result['glyph_screens'][index] = screen_span(page, traces[index])
            visible = all(result['glyph_screens'][i]['status'] == 'raster_consistent_candidate' for i in indices)
            row = {'source_sheet_identity_candidate': identity, 'target_sheet_candidate': sheet,
                'sheet_number_trace_index': sheet_index, 'circle_path_index': circle_index,
                'circle_paint_seqno': circle['seqno'], 'circle_bbox_page_points': list(rect),
                'circle_source_beziers': [[list(p) for p in item[1:]] for item in circle['items']],
                'head_alternatives': possible, 'glyph_screen_trace_indices': indices,
                'status': 'unverified_native_side_reference_candidate' if visible and identity and len(possible) == 1
                    else 'withheld_competing_head_or_visibility_or_identity',
                'marker_semantics_verified': False, 'marker_clipping_verified': False,
                'physical_building_identity_verified': False, 'pitch_degrees': None,
                'source_points_moved': False, 'world_geometry_additions': 0}
            if row['status'] == 'unverified_native_side_reference_candidate':
                row['target_view_key_candidate'] = [identity['project'], sheet, possible[0]['target_view_candidate']]
            row['id'] = digest([VERSION, row]); result['references'].append(row)
            if len(result['references']) > 128:
                raise OverflowError('side_reference_candidate_budget')
    except OverflowError as error:
        result.update(status='side_reference_budget_withheld', reason=str(error), references=[], glyph_screens={})
    return result
