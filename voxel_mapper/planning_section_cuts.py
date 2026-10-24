"""Exact source connectors between repeated enclosed section-label candidates.

Restricted source topology only: no nearest text, endpoint snapping, gap repair,
physical section certification, height assignment or world placement.
"""
from concurrent.futures import CancelledError
from collections import Counter
import json
import math
import re

import pymupdf
from shapely.geometry import LineString, Polygon, box, mapping

from . import glyph_visibility, ordinary_surfaces
from .building_spec import digest
from .drawing_page_tools import native_inverse

VERSION = 'planning-section-cuts-v1'
LIMITS = {'max_labels': 128, 'max_markers': 128, 'max_cuts': 128,
    'max_paths': 100000, 'max_checks': 500000, 'max_output_bytes': 2000000}
LABEL = re.compile(r'([A-Z])(?:\s*[-–]\s*\1)?')


def _circle(path):
    if len(path['items']) != 4 or any(item[0] != 'c' for item in path['items']):
        return False
    rect = path['rect']; radius = (rect.width+rect.height)/4
    if not 3 <= radius <= 40 or abs(rect.width-rect.height) > .02*radius:
        return False
    center = (rect.tl+rect.br)*.5
    for index, item in enumerate(path['items']):
        if item[-1] != path['items'][(index+1) % 4][1]:
            return False
        for t in (0, .25, .5, .75, 1):
            weights = ((1-t)**3, 3*(1-t)**2*t, 3*(1-t)*t*t, t**3)
            point = [sum(w*p[k] for w, p in zip(weights, item[1:])) for k in (0, 1)]
            if abs(math.dist(point, center)-radius) > .02*radius:
                return False
    return True


def _on_boundary(point, marker):
    nodes = marker['boundary_nodes_pdf_native']
    if marker['kind'] == 'circle':
        return point in nodes  # Exact original cubic nodes, not radial projection.
    for a, b in zip(nodes, nodes[1:]+nodes[:1]):
        if ((point[0]-a[0])*(b[1]-a[1]) == (point[1]-a[1])*(b[0]-a[0])
                and min(a[0], b[0]) <= point[0] <= max(a[0], b[0])
                and min(a[1], b[1]) <= point[1] <= max(a[1], b[1])):
            return True
    return False


def page_evidence(page, sha, number, *, options=None, cancelled=lambda: False):
    options = {} if options is None else options
    if not isinstance(options, dict) or set(options)-set(LIMITS):
        raise ValueError('Known section cut limits required')
    limits = {**LIMITS, **options}
    if (any(type(v) is not int or not 1 <= v <= LIMITS[k] for k, v in limits.items())
            or limits['max_output_bytes'] < 16384):
        raise ValueError('Lower-only section cut limits required')
    if (not re.fullmatch('[0-9a-f]{64}', str(sha)) or type(number) is not int
            or number < 1 or page.number+1 != number):
        raise ValueError('Pinned original page identity required')
    result = {'version': VERSION, 'document_sha256': sha, 'page': number,
        'coordinate_frame': 'pdf_native_points_y_up', 'limits': limits,
        'status': 'source_section_cut_topology_candidates_only', 'analysis_complete': True,
        'labels': [], 'markers': [], 'cuts': [], 'checks': 0, 'source_path_count': 0,
        'source_scope_holds': {}, 'marker_semantics_verified': False,
        'cut_direction_verified': False, 'physical_component_correspondence_verified': False,
        'source_paint_visibility_verified': False,
        'physical_height_verified': False, 'world_placement_eligible': False,
        'local_3d_components': 0, 'world_geometry_additions': 0, 'training_labels_generated': 0,
        'limitations': ['Repeated visible letter labels require explicit source marker enclosures.',
            'The connector is one unchanged original straight stroke ending exactly on both marker boundaries.',
            'Circle contacts must coincide with original cubic nodes; no snapping or gap repair.',
            'Later filled paint intersecting the connector conservatively withholds it.',
            'Marker semantics, direction, physical view identity, scale and ground datum remain unresolved.']}

    def check():
        if cancelled():
            raise CancelledError('Section cut recovery cancelled')

    def finish(reason=None):
        if reason:
            result.update(status='section_cuts_withheld', analysis_complete=False, reason=reason, cuts=[], markers=[])
        result['summary'] = {'section_cut_topology_candidates': len(result['cuts']),
            'source_letter_labels': len(result['labels']), 'source_marker_enclosures': len(result['markers']),
            'physical_section_cut_correspondences_verified': 0}
        if len(json.dumps(result, allow_nan=False).encode())+80 > limits['max_output_bytes']:
            result.update(status='section_cuts_withheld', analysis_complete=False,
                reason='section_cut_output_budget_exceeded', cuts=[], markers=[], labels=[])
            result['summary'] = dict.fromkeys(result['summary'], 0)
        check(); result['id'] = digest(result)
        return result

    def charge():
        check(); result['checks'] += 1
        if result['checks'] > limits['max_checks']:
            raise OverflowError

    check()
    kind, value = page.parent.xref_get_key(page.xref, 'UserUnit')
    try:
        unit = 1. if kind == 'null' else float(value)
    except (ValueError, TypeError):
        unit = None
    if unit != 1 or page.cropbox != page.mediabox:
        return finish('original_uncropped_standard_point_page_required')
    traces = page.get_texttrace()
    if len(traces) > 10000 or sum(len(s['chars']) for s in traces) > 500000:
        return finish('section_cut_text_budget_exceeded')
    inverse = native_inverse(page)
    try:
        for run in ordinary_surfaces.label_runs(traces):
            charge()
            text = ''.join(chr(c[0]) for c in run['chars']).strip()
            match = LABEL.fullmatch(text)
            if not match:
                continue
            if len(result['labels']) >= limits['max_labels']:
                return finish('section_cut_label_budget_exceeded')
            rect = pymupdf.Rect(run['bbox'])
            label = {'text': text, 'section_key_candidate': match[1]+'-'+match[1],
                'trace_indices': run['trace_indices'], 'character_indices': run['character_indices'],
                'bbox_pymupdf_unrotated': list(rect),
                'geometry_pdf_native': mapping(Polygon([list(p*inverse) for p in
                    (rect.tl, rect.tr, rect.br, rect.bl)])),
                'glyph_screen': glyph_visibility.screen_architectural_span(
                    page, run, zoom=24 if run['size'] < 4 else 6)}
            label['id'] = digest([VERSION, sha, number, label]); result['labels'].append(label)
        if not result['labels']:
            return finish()
        paths = page.get_drawings(extended=True)
        result['source_path_count'] = len(paths)
        if len(paths) > limits['max_paths']:
            return finish('section_cut_path_budget_exceeded')
        markers = []; lines = []; fills = []; clips = []; groups = []; holds = Counter()
        for index, path in enumerate(paths):
            charge()
            level = path.get('level', 0)
            clips = [v for v in clips if v < level]; groups = [v for v in groups if v < level]
            if path['type'] == 'clip':
                clips.append(level); continue
            if path['type'] == 'group':
                groups.append(level); continue
            if 'f' in path['type']:
                fills.append((index, box(*path['rect'])))
            if clips or groups:
                holds['clipping_or_group_scope_unsupported'] += 1; continue
            if path['type'] != 's' or path.get('layer') or path.get('stroke_opacity') != 1:
                continue
            if len(path['items']) == 1 and path['items'][0][0] == 'l':
                raw = [list(p) for p in path['items'][0][1:]]
                points = [list(p*inverse) for p in path['items'][0][1:]]
                if points[0] != points[1] and all(math.isfinite(v) for p in points for v in p):
                    lines.append({'source_path_index': index, 'paint_seqno': path['seqno'],
                        'endpoints_pdf_native': points, 'endpoints_pymupdf_unrotated': raw})
                continue
            rect = path['rect']; marker = None
            if (len(path['items']) == 1 and path['items'][0][0] == 're'
                    and 6 <= min(rect.width, rect.height) <= max(rect.width, rect.height) <= 80
                    and max(rect.width, rect.height) <= 2*min(rect.width, rect.height)):
                marker = {'kind': 'rectangle', 'boundary_nodes_pdf_native':
                    [list(p*inverse) for p in (rect.tl, rect.tr, rect.br, rect.bl)]}
            elif _circle(path):
                marker = {'kind': 'circle', 'boundary_nodes_pdf_native':
                    [list(item[1]*inverse) for item in path['items']],
                    'source_beziers_pdf_native': [[list(p*inverse) for p in item[1:]] for item in path['items']]}
            if marker is None:
                continue
            label_ids = []
            for label in result['labels']:
                charge()
                label_rect = pymupdf.Rect(label['bbox_pymupdf_unrotated'])
                enclosed = rect.contains(label_rect)
                if marker['kind'] == 'circle':
                    center = (rect.tl+rect.br)*.5; radius = (rect.width+rect.height)/4
                    enclosed = enclosed and all(math.dist(p, center) < .98*radius for p in
                        (label_rect.tl, label_rect.tr, label_rect.br, label_rect.bl))
                if enclosed:
                    label_ids.append(label['id'])
            if not label_ids:
                continue
            if len(markers) >= limits['max_markers']:
                return finish('section_cut_marker_budget_exceeded')
            marker.update(source_path_index=index, paint_seqno=path['seqno'], label_ids=label_ids,
                marker_semantics_verified=False, source_geometry_changed=False)
            marker['id'] = digest([VERSION, sha, number, marker]); markers.append(marker)
        result['source_scope_holds'] = dict(holds)
        labels = {r['id']: r for r in result['labels']}
        uses = Counter(identifier for marker in markers for identifier in marker['label_ids'])
        for marker in markers:
            ids = marker['label_ids']
            marker['status'] = ('unique_visible_source_marker_enclosure' if len(ids) == 1 and uses[ids[0]] == 1
                and labels[ids[0]]['glyph_screen']['status'] == 'raster_consistent_candidate'
                else 'withheld_ambiguous_or_hidden_marker_label')
            marker['section_key_candidate'] = labels[ids[0]]['section_key_candidate'] if marker['status'].startswith('unique') else None
        result['markers'] = markers
        for line in lines:
            contacts = []
            for endpoint in line['endpoints_pdf_native']:
                hits = []
                for marker in markers:
                    charge()
                    if _on_boundary(endpoint, marker):
                        hits.append(marker)
                contacts.append(hits)
            if any(len(hits) != 1 for hits in contacts):
                continue
            a, b = contacts[0][0], contacts[1][0]
            if (a['id'] == b['id'] or not a['section_key_candidate']
                    or a['section_key_candidate'] != b['section_key_candidate']):
                continue
            native_line = LineString(line['endpoints_pdf_native'])
            outward_contacts = True
            for endpoint, marker in zip(line['endpoints_pdf_native'], (a, b)):
                charge()
                nodes = marker['boundary_nodes_pdf_native']
                bounds = box(min(p[0] for p in nodes), min(p[1] for p in nodes),
                    max(p[0] for p in nodes), max(p[1] for p in nodes))
                contact = native_line.intersection(bounds)
                if contact.geom_type != 'Point' or list(contact.coords)[0] != tuple(endpoint):
                    outward_contacts = False; break
            if not outward_contacts:
                holds['connector_crosses_own_marker_enclosure'] += 1; continue
            interrupted = False
            for marker in markers:
                charge()
                if marker['id'] in (a['id'], b['id']):
                    continue
                nodes = marker['boundary_nodes_pdf_native']
                bounds = box(min(p[0] for p in nodes), min(p[1] for p in nodes),
                    max(p[0] for p in nodes), max(p[1] for p in nodes))
                if native_line.intersects(bounds):
                    interrupted = True; break
            if interrupted:
                holds['intermediate_labelled_source_marker'] += 1; continue
            obscured = False
            source_line = LineString(line['endpoints_pymupdf_unrotated'])
            for index, fill in fills:
                charge()
                if index > line['source_path_index'] and fill.intersects(source_line):
                    obscured = True; break
            if obscured:
                holds['later_filled_paint_over_connector'] += 1; continue
            if len(result['cuts']) >= limits['max_cuts']:
                return finish('section_cut_count_budget_exceeded')
            cut = {'section_key_candidate': a['section_key_candidate'],
                'status': 'unverified_exact_source_section_cut_topology',
                'source_line': line, 'marker_ids': [a['id'], b['id']],
                'label_ids': [a['label_ids'][0], b['label_ids'][0]],
                'endpoints_pdf_native': line['endpoints_pdf_native'],
                'source_geometry_changed': False, 'endpoints_snapped': False,
                'marker_semantics_verified': False, 'cut_direction_verified': False,
                'source_paint_visibility_verified': False,
                'physical_component_correspondence_verified': False, 'world_placement_eligible': False}
            cut['id'] = digest([VERSION, sha, number, cut]); result['cuts'].append(cut)
        result['source_scope_holds'] = dict(holds)
    except OverflowError:
        return finish('section_cut_work_budget_exceeded')
    return finish()
