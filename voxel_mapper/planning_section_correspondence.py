"""Original sheet-reference markers and competing plan/section hypotheses.

Numeric view references do not identify lettered section cuts. Nominal size
agreement is retained as a diagnostic and never selects a physical component.
"""
from concurrent.futures import CancelledError
from html import escape
import json
import math
from pathlib import Path
import re

import pymupdf
from shapely.geometry import Polygon, mapping

from . import glyph_visibility, ordinary_surfaces, planning_component_footprints
from . import planning_component_measurements, planning_section_profiles
from .building_spec import digest
from .drawing_page_tools import native_inverse

VERSION = 'planning-section-correspondence-v1'
MARKER_LIMITS = {'max_markers': 128, 'max_checks': 500000, 'max_output_bytes': 2000000}


def source_page(evidence):
    """Bounded review projection; page discovery and preview payloads stay on disk."""
    return {k: evidence.get(k) for k in ('document_sha256', 'page', 'component_measurements',
        'component_footprints', 'section_profiles', 'drawing_references')}


def _check(cancelled):
    if cancelled():
        raise CancelledError('Section correspondence analysis cancelled')


def _limits(options):
    if options is None:
        options = {}
    if not isinstance(options, dict) or set(options)-set(MARKER_LIMITS):
        raise ValueError('Known reference marker limits required')
    result = {**MARKER_LIMITS, **options}
    if (any(type(v) is not int or not 1 <= v <= MARKER_LIMITS[k] for k, v in result.items())
            or result['max_output_bytes'] < 16384):
        raise ValueError('Lower-only reference marker limits required')
    return result


def _pinned(value, version):
    return (isinstance(value, dict) and value.get('version') == version
        and value.get('id') == digest({k: v for k, v in value.items() if k != 'id'}))


def _circle(path):
    if (path['type'] != 's' or len(path['items']) != 4
            or any(v[0] != 'c' for v in path['items']) or path.get('layer')
            or path.get('stroke_opacity') != 1):
        return False
    rect = path['rect']
    radius = (rect.width+rect.height)/4
    if not 3 <= radius <= 40 or abs(rect.width-rect.height) > .02*radius:
        return False
    center = (rect.tl+rect.br)*.5
    for i, item in enumerate(path['items']):
        points = item[1:]
        if math.dist(points[-1], path['items'][(i+1) % 4][1]) > .3:
            return False
        # Test the retained cubics, not just a square bounding box.
        for t in (0, .25, .5, .75, 1):
            p = [sum(w*q[axis] for w, q in zip(
                ((1-t)**3, 3*(1-t)**2*t, 3*(1-t)*t*t, t**3), points)) for axis in (0, 1)]
            if abs(math.dist(p, center)-radius) > .02*radius:
                return False
    return True


def page_references(page, sha, number, measurements, *, options=None, cancelled=lambda: False):
    """All eligible circular four-digit sheet claims, with every outside index.

    The radial search is a bounded layout hypothesis, not a bearing or cut line.
    No filled-corner assumption, nearest-number choice or clipping repair is made.
    """
    limits = _limits(options)
    if (not re.fullmatch('[0-9a-f]{64}', str(sha)) or type(number) is not int
            or page.number+1 != number
            or not _pinned(measurements, planning_component_measurements.VERSION)
            or measurements['document_sha256'] != sha or measurements['page'] != number):
        raise ValueError('Exact same-page measurement evidence required')
    result = {'version': VERSION, 'document_sha256': sha, 'page': number,
        'source_measurements_sha256': digest(measurements), 'limits': limits,
        'analysis_complete': True, 'status': 'unverified_sheet_reference_markers_only',
        'markers': [], 'checks': 0, 'coordinate_frame': 'pdf_native_points_y_up',
        'marker_semantics_verified': False, 'section_cut_identity_verified': False,
        'physical_component_correspondence_verified': False, 'world_geometry_additions': 0}

    def finish(reason=None):
        if reason:
            result.update(analysis_complete=False, status='reference_markers_withheld', reason=reason, markers=[])
        if len(json.dumps(result, allow_nan=False).encode())+80 > limits['max_output_bytes']:
            result.update(analysis_complete=False, status='reference_markers_withheld',
                reason='reference_marker_output_budget_exceeded', markers=[])
        _check(cancelled)
        result['id'] = digest(result)
        return result

    def charge(count=1):
        _check(cancelled)
        result['checks'] += count
        if result['checks'] > limits['max_checks']:
            raise OverflowError

    _check(cancelled)
    if not measurements['analysis_complete']:
        return finish('complete_measurement_context_required')
    if not measurements['sheet_references']:
        return finish()
    traces = page.get_texttrace()
    if len(traces) > 10000 or sum(len(s['chars']) for s in traces) > 500000:
        return finish('reference_text_budget_exceeded')
    runs = ordinary_surfaces.label_runs(traces)
    numbers = []
    inverse = native_inverse(page)
    for run in runs:
        _check(cancelled)
        text = ''.join(chr(c[0]) for c in run['chars']).strip()
        if re.fullmatch(r'\d{1,4}', text):
            numbers.append((run, text))
    if len(numbers) > 5000:
        return finish('reference_numeric_budget_exceeded')
    paths = page.get_drawings()
    if len(paths) > 100000:
        return finish('reference_path_budget_exceeded')
    screens = {}

    def evidence(run, text):
        key = digest([run['trace_indices'], run['character_indices']])
        if key not in screens:
            _check(cancelled)
            screens[key] = glyph_visibility.screen_architectural_span(
                page, run, zoom=24 if run['size'] < 4 else 6)
        rect = pymupdf.Rect(run['bbox'])
        return {'text': text, 'trace_indices': run['trace_indices'],
            'character_indices': run['character_indices'], 'glyph_screen': screens[key],
            'geometry_pdf_native': mapping(Polygon([tuple(p*inverse) for p in
                (rect.tl, rect.tr, rect.br, rect.bl)]))}

    try:
        for index, path in enumerate(paths):
            charge()
            if not _circle(path):
                continue
            rect = path['rect']; center = (rect.tl+rect.br)*.5
            radius = (rect.width+rect.height)/4
            inside = []
            for run, text in numbers:
                charge()
                if rect.contains(pymupdf.Rect(run['bbox'])):
                    inside.append((run, text))
            if len(inside) != 1 or len(inside[0][1]) != 4:
                continue
            run, text = inside[0]
            outside = []
            for other, value in numbers:
                charge()
                if not 1 <= int(value) <= 99 or other['dir'] != run['dir']:
                    continue
                box = pymupdf.Rect(other['bbox'])
                distance = math.dist((box.tl+box.br)*.5, center)
                if not rect.intersects(box) and radius < distance <= 3*radius:
                    outside.append(evidence(other, value))
            if len(result['markers']) >= limits['max_markers']:
                return finish('reference_marker_count_budget_exceeded')
            sheet = evidence(run, text)
            visible = sheet['glyph_screen']['status'] == 'raster_consistent_candidate'
            unique = len(outside) == 1 and outside[0]['glyph_screen']['status'] == 'raster_consistent_candidate'
            row = {'target_sheet_candidate': text, 'sheet_number_evidence': sheet,
                'outside_view_index_candidates': outside,
                'target_view_index_candidate': int(outside[0]['text']) if unique and visible else None,
                'status': 'unverified_sheet_reference_marker_candidate' if visible and unique
                    else 'withheld_reference_index_or_visibility',
                'circle_path_index': index, 'circle_paint_seqno': path['seqno'],
                'circle_source_beziers_pdf_native': [[list(p*inverse) for p in item[1:]] for item in path['items']],
                'center_pdf_native': list(center*inverse), 'radius_pdf_points': radius,
                'index_search_radius_pdf_points': 3*radius,
                'marker_semantics_verified': False, 'marker_paint_visibility_verified': False,
                'marker_clipping_verified': False, 'section_cut_identity_verified': False}
            row['id'] = digest([VERSION, sha, number, row])
            result['markers'].append(row)
    except OverflowError:
        return finish('reference_marker_work_budget_exceeded')
    return finish()


def review_pages(pages, *, tolerance_m=.25, max_checks=8192, max_output_bytes=8000000,
                 cancelled=lambda: False):
    """Retain rival same-family source components; never select by nominal size."""
    if (not isinstance(pages, list) or len(pages) > 512
            or type(tolerance_m) not in (int, float) or not math.isfinite(tolerance_m) or not 0 < tolerance_m <= .25
            or type(max_checks) is not int or not 1 <= max_checks <= 8192
            or type(max_output_bytes) is not int or not 16384 <= max_output_bytes <= 8000000):
        raise ValueError('Bounded lower-only correspondence review policy required')
    result = {'version': VERSION, 'status': 'section_plan_correspondence_diagnostics_only',
        'analysis_complete': True, 'tolerance_m': tolerance_m, 'checks': 0,
        'source_pages': {}, 'profiles': [], 'source_reference_markers': [],
        'physical_component_correspondences_verified': 0, 'physical_height_m': None,
        'physical_height_verified': False, 'ground_datum_verified': False,
        'local_3d_components': 0, 'world_geometry_additions': 0, 'world_placement_eligible': False,
        'training_labels_generated': 0, 'model_weights_updated': False,
        'limitations': ['Shared series and sheet references establish drawing context only.',
            'Numeric view indices are not mapped to lettered sections or caption order.',
            'Width checks compare both oriented plan spans; oblique section cuts are not modelled.',
            'All contextual rivals remain, including size mismatches; no nearest or best match is selected.',
            'Section cut topology, physical scale, exterior walls and local ground datum remain unresolved.']}

    def finish(reason=None):
        if reason:
            result.update(status='section_plan_correspondence_withheld', analysis_complete=False,
                reason=reason, profiles=[], source_reference_markers=[])
        result['summary'] = {
            'section_plan_context_pairs': sum(len(r['plan_candidates']) for r in result['profiles']),
            'profiles_with_multiple_plan_candidates': sum(len(r['plan_candidates']) > 1 for r in result['profiles']),
            'source_sheet_reference_markers': len(result['source_reference_markers']),
            'physical_component_correspondences_verified': 0}
        if len(json.dumps(result, indent=2, allow_nan=False).encode())+80 > max_output_bytes:
            result.update(status='section_plan_correspondence_withheld', analysis_complete=False,
                reason='correspondence_review_output_budget_exceeded', profiles=[],
                source_reference_markers=[], source_pages={})
            result['summary'] = dict.fromkeys(result['summary'], 0)
        _check(cancelled)
        result['id'] = digest(result)
        return result

    unique = {}
    for page in pages:
        _check(cancelled)
        sha, number = page['document_sha256'], page['page']
        if not re.fullmatch('[0-9a-f]{64}', str(sha)) or type(number) is not int or number < 1:
            raise ValueError('Pinned source page identity required')
        key = sha+':'+str(number)
        if key in unique and unique[key] != page:
            raise ValueError('Conflicting correspondence source page')
        measurements = page.get('component_measurements')
        profiles = page.get('section_profiles')
        markers = page.get('drawing_references')
        components = page.get('component_footprints')
        if measurements is None:
            if any(v is not None for v in (profiles, markers, components)):
                raise ValueError('Measurement context required')
        else:
            if (not _pinned(measurements, planning_component_measurements.VERSION)
                    or measurements['document_sha256'] != sha or measurements['page'] != number
                    or measurements['source_components_sha256'] != digest(components)):
                raise ValueError('Exact measurement and component source required')
            if components is not None and (components.get('version') != planning_component_footprints.VERSION
                    or components.get('document_sha256') != sha or components.get('page') != number):
                raise ValueError('Same-page current components required')
            for value, version in ((profiles, planning_section_profiles.VERSION), (markers, VERSION)):
                if value is not None and (not _pinned(value, version)
                        or value['document_sha256'] != sha or value['page'] != number
                        or value['source_measurements_sha256'] != digest(measurements)):
                    raise ValueError('Exact same-page profile and reference evidence required')
        unique[key] = page
        result['source_pages'][key] = {'sha256': digest(page),
            'measurements_complete': None if measurements is None else measurements['analysis_complete'],
            'components_complete': None if components is None else components['analysis_complete'],
            'profiles_complete': None if profiles is None else profiles['analysis_complete'],
            'reference_markers_complete': None if markers is None else markers['analysis_complete']}
    # Incremental accounting bounds retained evidence before the final JSON check.
    retained_bytes = 0

    def charge():
        _check(cancelled)
        result['checks'] += 1
        if result['checks'] > max_checks:
            raise OverflowError

    def retain(row):
        nonlocal retained_bytes
        retained_bytes += len(json.dumps(row, allow_nan=False).encode())
        if retained_bytes > max_output_bytes-2048:
            raise OverflowError('bytes')

    def visible(rows):
        return [r for r in rows if r['glyph_screen']['status'] == 'raster_consistent_candidate']

    try:
        for page in unique.values():
            markers = page.get('drawing_references')
            for marker in (markers or {}).get('markers', []):
                charge()
                row = {'document_sha256': page['document_sha256'], 'page': page['page'],
                    'source_reference_evidence_sha256': digest(markers), 'marker': marker}
                retain(row)
                result['source_reference_markers'].append(row)
        for page in unique.values():
            section_pack = page.get('section_profiles')
            if not section_pack or not section_pack['analysis_complete']:
                continue
            section_measurements = page['component_measurements']
            section_codes = visible(section_measurements['drawing_codes'])
            for profile in section_pack['profiles']:
                charge()
                if len(result['profiles']) >= 128:
                    return finish('correspondence_profile_count_budget_exceeded')
                row = {'profile_id': profile['id'], 'document_sha256': page['document_sha256'],
                    'page': page['page'], 'source_profile_sha256': digest(profile),
                    'section_caption': profile['caption_evidence']['text'],
                    'horizontal_span_nominal_m': profile['horizontal_span_nominal_m'],
                    'vertical_span_nominal_m': profile['vertical_span_nominal_m'],
                    'plan_candidates': [], 'selected_component_id': None,
                    'status': 'withheld_section_cut_component_identity_unresolved',
                    'section_cut_reference_status': 'withheld_no_source_cut_topology',
                    'physical_height_m': None, 'physical_height_verified': False,
                    'required_evidence': ['source_section_cut_to_plan_component_link',
                        'checked_scale_and_exterior_wall_interpretation', 'local_ground_datum_and_height_endpoints']}
                retain(row)
                result['profiles'].append(row)
                if len(section_codes) != 1:
                    row['context_hold'] = 'unique_visible_section_drawing_code_required'
                    continue
                section_code = section_codes[0]
                family = {r['claim']['noun'] for r in profile['labels']}
                for plan in unique.values():
                    charge()
                    measurements = plan.get('component_measurements')
                    components = plan.get('component_footprints')
                    if not measurements or not components:
                        continue
                    codes = visible(measurements['drawing_codes'])
                    refs = [r for r in visible(measurements['sheet_references']) if r['sheet'] == section_code['sheet']]
                    if (not measurements['analysis_complete'] or not components['analysis_complete']
                            or len(codes) != 1 or codes[0]['series'] != section_code['series']
                            or codes[0]['sheet'] == section_code['sheet'] or not refs
                            or measurements['printed_states'] != [profile['printed_state']]):
                        continue
                    source_markers = plan.get('drawing_references')
                    matching_markers = [m['id'] for m in (source_markers or {}).get('markers', [])
                        if m['status'] == 'unverified_sheet_reference_marker_candidate'
                        and m['target_sheet_candidate'] == section_code['sheet']]
                    for component in components['candidates']:
                        charge()
                        label = component['label']
                        if (label['claim']['noun'] not in family or label['claim']['printed_state'] not in
                                ('unspecified', profile['printed_state'], *(['new'] if profile['printed_state'] == 'proposed' else []))):
                            continue
                        trials = [t for t in measurements['trials'] if t['source_component_id'] == component['id']]
                        if not trials:
                            continue
                        comparisons = []
                        for trial in trials:
                            charge()
                            if trial['source_component_sha256'] != digest(component):
                                raise ValueError('Exact trial component required')
                            spans = trial['nominal_oriented_span_pair_m']
                            width = profile['horizontal_span_nominal_m']
                            if not all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in [width, *spans]):
                                raise ValueError('Finite positive nominal spans required')
                            comparisons.append({'trial_id': trial['id'], 'source_trial_sha256': digest(trial),
                                'plan_oriented_span_pair_nominal_m': spans,
                                'absolute_span_errors_m': [abs(width-v) for v in spans],
                                'span_within_tolerance': [abs(width-v) <= tolerance_m+1e-9 for v in spans],
                                'cut_axis_verified': False, 'correspondence_verified': False})
                        candidate = {'source_component_id': component['id'],
                            'source_component_sha256': digest(component), 'document_sha256': plan['document_sha256'],
                            'page': plan['page'], 'label': label['text'], 'nominal_width_comparisons': comparisons,
                            'drawing_code_evidence_id': codes[0]['id'], 'section_drawing_code_evidence_id': section_code['id'],
                            'literal_sheet_reference_ids': [r['id'] for r in refs],
                            'sheet_marker_candidate_ids': matching_markers,
                            'reference_view_to_section_status': 'withheld_numeric_view_index_is_not_a_section_cut_label',
                            'link_basis': 'shared_visible_series_sheet_reference_state_and_component_noun_only',
                            'section_cut_link_supported': False, 'physical_component_identity_verified': False}
                        retain(candidate)
                        row['plan_candidates'].append(candidate)
    except OverflowError as error:
        return finish('correspondence_review_output_budget_exceeded' if str(error) == 'bytes'
            else 'correspondence_work_budget_exceeded')
    return finish()


def write_review(root, review):
    if not _pinned(review, VERSION):
        raise ValueError('Exact current correspondence review required')
    root = Path(root)
    (root/'section-correspondence.json').write_text(json.dumps(review, indent=2, allow_nan=False), encoding='utf-8')
    body = ['<!doctype html><html lang="en"><meta charset="utf-8"><title>Section correspondence</title>',
        '<h1>Section to plan comparison</h1><p>Drawing context and nominal width diagnostics. '
        'Numeric reference indices do not identify lettered sections. Every competing plan component is retained. '
        'Physical identity, height and ground level remain unresolved; no 3D building is generated.</p>',
        '<p><a href="section-correspondence.json">Exact source pins, reference primitives and unresolved requirements</a></p>']
    if not review['analysis_complete']:
        body.append('<p>Comparison withheld: '+escape(review.get('reason', 'incomplete evidence'))+'</p>')
    for row in review['profiles']:
        body.append('<h2>'+escape(row['section_caption'])+'</h2><p>'+str(len(row['plan_candidates']))+
            ' contextual plan candidates; no component selected.</p><ul>')
        for candidate in row['plan_candidates']:
            body.append('<li>'+escape(candidate['label'])+' — '+escape(candidate['source_component_id'])+'</li>')
        body.append('</ul>')
    body.append('<h2>Original sheet reference markers</h2><ul>')
    for item in review['source_reference_markers']:
        marker = item['marker']
        body.append('<li>Sheet '+escape(marker['target_sheet_candidate'])+'; outside index '+
            escape(str(marker['target_view_index_candidate']))+'; '+escape(marker['status'])+'.</li>')
    body.append('</ul></html>')
    (root/'section-correspondence.html').write_text(''.join(body), encoding='utf-8')
