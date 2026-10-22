"""Complementary native two-line level bindings; no physical datum promotion."""
from itertools import combinations
import json
import math
import re

import numpy as np
import pymupdf

from . import elevation_levels
from .glyph_visibility import screen_architectural_span
from .ordinary_surfaces import label_runs
from .reconstruction_evidence_queue import digest

VERSION = 'split-native-level-labels-v1'
LABEL = re.compile(r'(?:[A-Za-z][A-Za-z0-9 -]{0,63} )?Level', re.I)
VALUE = re.compile(r'[+-]\s*\d{2,3}\.\d{1,3}')


def fragments(page, charge):
    traces = page.get_texttrace()
    if len(traces) > 10000 or sum(len(t['chars']) for t in traces) > 500000:
        raise OverflowError('split_level_source_text_budget')
    labels, values, duplicates = [], [], []
    for run in label_runs(traces):
        charge(); text = ''.join(chr(c[0]) for c in run['chars']).strip()
        kind = 'label' if LABEL.fullmatch(text) else 'value' if VALUE.fullmatch(text) else 'numeric_duplicate' if re.fullmatch(r'\d{3,6}', text) else None
        if kind is None: continue
        if not all(math.isfinite(v) for v in [*run['bbox'], *run['dir'], run['size']]):
            raise ValueError('Finite original level text required')
        row = {'text': text, 'trace_indices': run['trace_indices'], 'character_indices': run['character_indices'],
            'bbox_page_points': list(run['bbox']), 'direction': list(run['dir']), 'font': run['font'],
            'font_size_points': run['size'], 'rendering_type': run['type'], 'opacity': run['opacity'],
            'color': list(run['color']), 'layer': run.get('layer'),
            'glyph_origins_page_points': [list(c[2]) for c in run['chars']],
            'glyph_screen': screen_architectural_span(page, run, zoom=24 if run['size'] < 4 else 6)}
        row['id'] = digest([VERSION, row]); {'label': labels, 'value': values, 'numeric_duplicate': duplicates}[kind].append(row)
        if max(len(labels), len(values), len(duplicates)) > 128:
            raise OverflowError('split_level_fragment_budget')
    return {'labels': labels, 'values': values, 'numeric_duplicates': duplicates}


def ranges(row, axis):
    rect = pymupdf.Rect(row['bbox_page_points']); normal = [-axis[1], axis[0]]
    points = np.array([list(p) for p in (rect.tl, rect.tr, rect.br, rect.bl)])
    along, across = points @ axis, points @ normal
    return [float(min(along)), float(max(along)), float(min(across)), float(max(across))]


def pair_fragments(source, charge):
    """Every style-compatible, edge-aligned following line; never nearest text."""
    pairs = []
    for label in source['labels']:
        axis = np.array(label['direction']); size = label['font_size_points']
        if abs(np.linalg.norm(axis) - 1) > 1e-6 or size <= 0:
            raise ValueError('Unit reading direction and positive original font size required')
        a = ranges(label, axis)
        for value in source['values']:
            charge()
            style = ('font', 'font_size_points', 'direction', 'rendering_type', 'opacity', 'color', 'layer')
            if any(label[k] != value[k] for k in style): continue
            b = ranges(value, axis); gap = b[2] - a[3]
            edge_errors = [abs(a[i] - b[i]) for i in (0, 1)]
            if not 0 <= gap <= 2 * size or min(edge_errors) > .25 * size: continue
            numeric = []
            for duplicate in source['numeric_duplicates']:
                charge()
                if duplicate['direction'] != label['direction']: continue
                d = ranges(duplicate, axis); numeric_gap = d[2] - b[3]
                if 0 <= numeric_gap <= 2 * size and min(abs(b[i] - d[i]) for i in (0, 1)) <= .25 * size:
                    numeric.append({'fragment_id': duplicate['id'],
                        'printed_integer': int(duplicate['text']), 'assumed_mm_value_m': int(duplicate['text']) / 1000,
                        'difference_from_decimal_m': int(duplicate['text']) / 1000 - float(value['text'].replace(' ', '')),
                        'assumed_numeric_units_verified': False,
                        'glyph_screen_status': duplicate['glyph_screen']['status']})
            duplicate_status = ('no_numeric_duplicate' if not numeric else 'competing_numeric_duplicates' if len(numeric) != 1
                else 'numeric_duplicate_visibility_held' if numeric[0]['glyph_screen_status'] != 'raster_consistent_candidate'
                else 'consistent_assumed_mm_duplicate' if abs(numeric[0]['difference_from_decimal_m']) <= .005
                else 'conflicting_assumed_mm_duplicate')
            visible = all(r['glyph_screen']['status'] == 'raster_consistent_candidate' for r in (label, value))
            row = {'label_fragment_id': label['id'], 'value_fragment_id': value['id'],
                'level_label_candidate': label['text'], 'value_m_candidate': float(value['text'].replace(' ', '')),
                'fragment_gap_pdf_points': gap, 'edge_alignment_errors_pdf_points': edge_errors,
                'numeric_duplicate_candidates': numeric, 'numeric_duplicate_status': duplicate_status,
                'status': 'unverified_native_split_level_label' if visible and duplicate_status in
                    ('no_numeric_duplicate', 'consistent_assumed_mm_duplicate') else 'split_level_label_source_check_held',
                'text_fragments_joined_or_moved': False, 'physical_level_identity_verified': False}
            row['id'] = digest([VERSION, row]); pairs.append(row)
            if len(pairs) > 256: raise OverflowError('split_level_pair_budget')
    return pairs


def bind(markers, source, pairs, views, rotation, charge):
    lookup = {r['id']: r for group in source.values() for r in group}; records = []
    for original in markers['records']:
        charge(); bounds = pymupdf.Rect(original['circle_bbox_display_points']); center = (bounds.tl + bounds.br) * .5
        radius = (bounds.width + bounds.height) / 4; labels = []
        for label in original['label_candidates']:
            labels.append({'recipe': 'preceding_single_trace_label', 'source_label': label,
                'level_label_candidate': label['level_label_candidate'], 'value_m_candidate': label['value_m_candidate'],
                'bbox_display_points': label['bbox_display_points'],
                'glyph_screen_status': label['glyph_screen_status'], 'split_pair_id': None})
        for pair in pairs:
            charge(); label = lookup[pair['label_fragment_id']]; value = lookup[pair['value_fragment_id']]
            value_box = pymupdf.Rect(value['bbox_page_points']) * rotation
            label_box = pymupdf.Rect(label['bbox_page_points']) * rotation; whole = label_box | value_box
            left = 0 <= bounds.x0 - whole.x1 <= 2 * radius
            right = 0 <= whole.x0 - bounds.x1 <= 2 * radius
            if not (left or right) or not 0 <= center.y - value_box.y1 <= radius: continue
            labels.append({'recipe': 'two_separate_original_level_fragments', 'split_pair_id': pair['id'],
                'source_fragment_ids': [label['id'], value['id']], 'level_label_candidate': pair['level_label_candidate'],
                'value_m_candidate': pair['value_m_candidate'], 'bbox_display_points': list(whole),
                'glyph_screen_status': 'raster_consistent_candidate' if pair['status'] == 'unverified_native_split_level_label' else 'withheld'})
        scopes = []
        for view in views:
            charge(); box = pymupdf.Rect(view['display_bounds'])
            if (box.contains(bounds) and all(box.contains(pymupdf.Rect(l['bbox_display_points'])) for l in labels)
                    and all(box.contains(pymupdf.Point(p)) for line in original['datum_line_candidates'] for p in line['display_endpoints'])):
                scopes.append(view)
        row = {'legacy_marker_id': original['id'], 'legacy_marker_sha256': digest(original),
            'legacy_marker_status': original['status'], 'circle_bbox_display_points': list(bounds),
            'label_candidates': labels, 'source_datum_line_candidates': original['datum_line_candidates'],
            'view_candidates': scopes, 'status': 'split_level_marker_source_check_held',
            'physical_floor_role_verified': False, 'vertical_datum_verified': False,
            'source_reference_line_extended': False, 'legacy_marker_record_changed': False}
        if (len(labels) == len(original['datum_line_candidates']) == len(scopes) == 1
                and labels[0]['glyph_screen_status'] == 'raster_consistent_candidate'
                and scopes[0]['nominal_metres_per_pdf_point_candidate'] is not None):
            row.update(status='unverified_source_level_marker_binding', label=labels[0],
                view_key_candidate=scopes[0]['view_key_candidate'],
                nominal_metres_per_pdf_point=scopes[0]['nominal_metres_per_pdf_point_candidate'],
                datum_y_display_points=original['datum_line_candidates'][0]['display_endpoints'][0][1])
        row['id'] = digest([VERSION, row]); records.append(row)
    return records


def relative_checks(records, charge):
    result = []
    for a, b in combinations(records, 2):
        charge()
        if (a['status'] != 'unverified_source_level_marker_binding' or b['status'] != a['status']
                or a['view_key_candidate'] != b['view_key_candidate']): continue
        if a['nominal_metres_per_pdf_point'] != b['nominal_metres_per_pdf_point']:
            raise ValueError('Same source view level scale required')
        nominal = (b['datum_y_display_points'] - a['datum_y_display_points']) * a['nominal_metres_per_pdf_point']
        printed = a['label']['value_m_candidate'] - b['label']['value_m_candidate']; error = nominal - printed
        row = {'source_binding_ids': [a['id'], b['id']], 'view_key_candidate': a['view_key_candidate'],
            'printed_difference_m_candidate': printed, 'nominal_source_difference_m': nominal,
            'difference_residual_nominal_m': error,
            'status': 'source_relative_level_scale_agrees' if abs(error) <= .01 else 'source_relative_level_scale_disagrees',
            'independent_survey_controls': False, 'physical_units_verified': False, 'vertical_datum_verified': False}
        row['id'] = digest([VERSION, row]); result.append(row)
    return result


def review(page, sha, number, views, *, max_checks=100000):
    if type(max_checks) is not int or not 1 <= max_checks <= 100000:
        raise ValueError('Bounded split level work required')
    result = {'version': VERSION, 'document_sha256': sha, 'page': number,
        'status': 'split_source_level_review_only', 'checks': 0, 'legacy_marker_review': None,
        'fragments': {}, 'split_pairs': [], 'marker_bindings': [], 'relative_checks': [],
        'physical_floor_role_verified': False, 'vertical_datum_verified': False, 'world_geometry_additions': 0}
    def charge():
        result['checks'] += 1
        if result['checks'] > max_checks: raise OverflowError('split_level_work_budget')
    try:
        try: legacy = elevation_levels.extract(page, sha, number, views, max_checks=max_checks, scope_mode='whole_view_containment')
        except ValueError as error:
            if 'budget' not in str(error): raise
            raise OverflowError(str(error)) from error
        for _ in range(legacy['checks']): charge()
        source = fragments(page, charge); pairs = pair_fragments(source, charge)
        records = bind(legacy, source, pairs, views, page.rotation_matrix, charge)
        result.update(legacy_marker_review=legacy, fragments=source, split_pairs=pairs, marker_bindings=records,
            relative_checks=relative_checks(records, charge))
    except OverflowError as error:
        result.update(status='split_source_level_budget_withheld', reason=str(error), legacy_marker_review=None,
            fragments={}, split_pairs=[], marker_bindings=[], relative_checks=[])
    return json.loads(json.dumps(result))
