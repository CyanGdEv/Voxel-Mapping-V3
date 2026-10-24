"""Source-pinned prose dimensions; spacing endpoints and physical identity stay unresolved."""
from concurrent.futures import CancelledError
import copy
import json
import math
import re

import pymupdf
from shapely.geometry import Polygon, mapping

from . import glyph_visibility, ordinary_surfaces
from .building_spec import digest
from .drawing_page_tools import native_inverse

VERSION = 'planning-design-dimensions-v1'
LIMITS = {'max_claims': 16, 'max_height_claims': 32, 'max_lines': 2048,
          'max_checks': 200000, 'max_output_bytes': 2000000}
NUMBER = r'(?:\d{1,3}(?:\.\d{1,3})?)'
METRES = r'\s*m(?:etres|eters)?\b'
PAIRED = re.compile(
    r'(?:The\s+)?(?P<state>proposed\s+)?(?:two|2)\s+(?:lines|rows)\s+of\s+'
    r'(?P<family>portacabins?|(?:shipping\s+)?containers?)\s+(?:are\s+)?'
    r'(?:located|positioned|set)\s+(?P<spacing>'+NUMBER+r')'+METRES+r'\s+apart\s*,\s*'
    r'(?P<length>'+NUMBER+r')'+METRES+r'\s+long\s+and\s+(?P<width>'+NUMBER+r')'+METRES+
    r'\s+wide\s+with\s+an?\s+eaves\s+height\s+of\s+(?P<eaves>'+NUMBER+r')'+METRES+
    r'(?:\s+and\s+linked\s+by\s+a\s+domed\s+ridge\s+(?P<approx>approximately\s+)?'
    r'(?P<ridge>'+NUMBER+r')'+METRES+r'\s+above\s+ground\s+level)?\s*\.?', re.I)
START = re.compile(r'^(?:The\s+)?(?:proposed\s+)?(?:two|2)\s+(?:lines|rows)\s+of\b', re.I)
STATE = re.compile(r'^(?:The\s+)?(?P<state>proposed|existing)\s+layout\b', re.I)
HEIGHT = re.compile(
    r'(?:(?P<role>eaves|ridge|maximum|overall)\s+)?height\s+(?:of\s+)?'
    r'(?P<approx>approximately\s+|about\s+|circa\s+)?(?P<a>'+NUMBER+r')'+METRES+
    r'|(?P<approx2>approximately\s+|about\s+|circa\s+)?(?P<b>'+NUMBER+r')'+METRES+
    r'\s+(?P<suffix>above\s+ground\s+level|high)\b', re.I)


def page_evidence(page, sha, number, *, options=None, cancelled=lambda: False):
    options = {} if options is None else options
    if not isinstance(options, dict) or set(options)-set(LIMITS):
        raise ValueError('Known narrative dimension limits required')
    limits = {**LIMITS, **options}
    if (any(type(v) is not int or not 1 <= v <= LIMITS[k] for k, v in limits.items())
            or limits['max_output_bytes'] < 16384):
        raise ValueError('Lower-only narrative dimension limits required')
    if (not re.fullmatch('[0-9a-f]{64}', str(sha)) or type(number) is not int
            or page.number+1 != number):
        raise ValueError('Pinned original source page required')
    result = {'version': VERSION, 'document_sha256': sha, 'page': number,
        'coordinate_frame': 'pdf_native_points_y_up', 'limits': limits,
        'analysis_complete': True, 'status': 'source_narrative_dimensions_only',
        'claims': [], 'height_claims': [], 'withheld': [], 'checks': 0,
        'physical_identity_verified': False, 'physical_scale_verified': False,
        'ground_datum_verified': False, 'world_placement_eligible': False,
        'world_geometry_additions': 0, 'training_labels_generated': 0,
        'limitations': ['Text dimensions are source design claims, not surveyed or current as-built measurements.',
            'Apart does not specify clear-gap or centre-line endpoints.',
            'Printed state context is retained separately; its physical scope remains unverified.',
            'Height statements retain their source role; statements from different documents need not describe one component.']}

    def check(count=1):
        if cancelled():
            raise CancelledError('Narrative dimension extraction cancelled')
        result['checks'] += count
        if result['checks'] > limits['max_checks']:
            raise OverflowError('narrative_dimension_work_budget_exceeded')

    def finish(reason=None):
        if reason:
            result.update(analysis_complete=False, status='narrative_dimensions_withheld',
                          reason=reason, claims=[], height_claims=[], withheld=[])
        if len(json.dumps(result, indent=2, allow_nan=False).encode())+80 > limits['max_output_bytes']:
            result.update(analysis_complete=False, status='narrative_dimensions_withheld',
                reason='narrative_dimension_output_budget_exceeded', claims=[], height_claims=[], withheld=[])
        if cancelled():
            raise CancelledError('Narrative dimension extraction cancelled')
        result['id'] = digest(result)
        return result

    try:
        check()
        traces = page.get_texttrace()
        if len(traces) > 10000 or sum(len(s['chars']) for s in traces) > 500000:
            return finish('narrative_dimension_text_budget_exceeded')
        runs = ordinary_surfaces.label_runs(traces)
        layout = page.get_text('dict', flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)
        lines = []
        for block_index, block in enumerate(layout['blocks']):
            if block['type'] != 0:
                continue
            for line_index, line in enumerate(block['lines']):
                check()
                if len(lines) >= limits['max_lines']:
                    return finish('narrative_dimension_line_budget_exceeded')
                spans = line['spans']
                lines.append({'block_index': block_index, 'line_index': line_index,
                    'bbox': list(line['bbox']), 'dir': list(line['dir']),
                    'size': max((s['size'] for s in spans), default=0),
                    'layout_text': ''.join(s['text'] for s in spans), 'runs': []})
        result['source_layout_sha256'] = digest([{k: v for k, v in line.items() if k != 'runs'} for line in lines])
        # Dictionary blocks/line order supply layout only. Every claimed letter
        # must come from uniquely contained original text-trace characters.
        for run in runs:
            matches = []
            for i, line in enumerate(lines):
                check()
                if tuple(run['dir']) != (1., 0.) or tuple(line['dir']) != (1., 0.):
                    continue
                a, b, c, d = line['bbox']
                if pymupdf.Rect(a-1, b-1, c+1, d+1).contains(pymupdf.Rect(run['bbox'])):
                    matches.append(i)
            if len(matches) == 1:
                lines[matches[0]]['runs'].append(run)
        for line in lines:
            # Preserve source trace order, including spaces and split decimals.
            line['runs'].sort(key=lambda r: (r['trace_indices'][0], r['character_indices'][0]))
            line['text'] = ''.join(''.join(chr(c[0]) for c in r['chars']) for r in line['runs'])
            line['complete'] = (' '.join(line['text'].split()) == ' '.join(line['layout_text'].split()))
        inverse = native_inverse(page)
        screens = {}

        def run_record(run):
            check()
            key = digest([run['trace_indices'], run['character_indices'], run['chars']])
            text = ''.join(chr(c[0]) for c in run['chars'])
            if key not in screens:
                screens[key] = ({'status': 'whitespace_only_source_characters'} if not text.strip()
                    else glyph_visibility.screen_architectural_span(page, run, zoom=24 if run['size'] < 4 else 6))
            box = pymupdf.Rect(run['bbox'])
            return {'text': text, 'trace_indices': run['trace_indices'],
                'character_indices': run['character_indices'], 'source_characters': run['chars'],
                'source_run_sha256': key, 'glyph_screen': screens[key],
                'geometry_pdf_native': mapping(Polygon([tuple(p*inverse) for p in (box.tl, box.tr, box.br, box.bl)]))}

        def source_evidence(window):
            rows = []
            visible = True
            for line in window:
                records = [run_record(r) for r in line['runs']]
                ok = line['complete'] and all(r['glyph_screen']['status'] in
                    ('raster_consistent_candidate', 'whitespace_only_source_characters') for r in records)
                visible &= ok
                box = pymupdf.Rect(line['bbox'])
                rows.append({'block_index': line['block_index'], 'line_index': line['line_index'],
                    'text': line['text'], 'layout_text': line['layout_text'], 'text_trace_inventory_complete': line['complete'],
                    'geometry_pdf_native': mapping(Polygon([tuple(p*inverse) for p in (box.tl, box.tr, box.br, box.bl)])),
                    'runs': records, 'glyph_status': 'raster_consistent_candidate' if ok else 'withheld'})
            joins = [{'from_line_index': a['line_index'], 'to_line_index': b['line_index'],
                'block_index': a['block_index'], 'baseline_step_pdf_points': b['bbox'][1]-a['bbox'][1],
                'left_edge_offset_pdf_points': b['bbox'][0]-a['bbox'][0],
                'source_line_order_preserved': True} for a, b in zip(window, window[1:])]
            return {'source_text': '\n'.join(line['text'].rstrip() for line in window),
                'source_lines': rows, 'line_join_evidence': joins,
                'glyph_status': 'raster_consistent_candidate' if visible else 'withheld'}

        def contiguous(a, b):
            return (a['block_index'] == b['block_index'] and b['line_index'] == a['line_index']+1
                and a['layout_text'].strip() and b['layout_text'].strip()
                and tuple(a['dir']) == tuple(b['dir']) == (1., 0.)
                and 0 < b['bbox'][1]-a['bbox'][1] <= 1.8*max(a['size'], b['size'])
                and abs(b['bbox'][0]-a['bbox'][0]) <= 2*max(a['size'], b['size']))

        def state_context(start):
            own = lines[start]
            if re.match(r'^(?:The\s+)?proposed\s+(?:two|2)\b', own['text'].strip(), re.I):
                return 'proposed', {'basis': 'literal_proposed_in_dimension_sentence', 'scope_verified': False}
            # Only the immediately preceding nonempty line of the same original
            # block/column can supply the literal proposed-layout context.
            j = start-1
            while j >= 0 and not lines[j]['layout_text'].strip() and lines[j]['block_index'] == own['block_index']:
                j -= 1
            if j < 0:
                return 'unknown', None
            previous = lines[j]
            match = STATE.match(previous['text'].strip())
            if (not match or previous['block_index'] != own['block_index']
                    or own['bbox'][1]-previous['bbox'][1] > 3*max(own['size'], previous['size'])
                    or abs(own['bbox'][0]-previous['bbox'][0]) > max(own['size'], previous['size'])
                    or not previous['complete']):
                return 'unknown', None
            # Screen original characters of the explicit state prefix. Preserve
            # the full surrounding sentence separately, including punctuation
            # that the ASCII glyph screen may not support.
            raw = previous['text']; prefix = STATE.match(raw.lstrip())
            lo = len(raw)-len(raw.lstrip()); hi = lo+prefix.end()
            selected = []
            offset = 0
            for run in previous['runs']:
                length = len(run['chars']); a = max(0, lo-offset); b = min(length, hi-offset)
                if a < b:
                    part = copy.deepcopy(run)
                    part['chars'] = run['chars'][a:b]
                    part['character_indices'] = run['character_indices'][a:b]
                    boxes = [c[3] for c in part['chars']]
                    part['bbox'] = [min(r[0] for r in boxes), min(r[1] for r in boxes),
                                    max(r[2] for r in boxes), max(r[3] for r in boxes)]
                    selected.append(run_record(part))
                offset += length
            visible = selected and all(r['glyph_screen']['status'] in
                ('raster_consistent_candidate', 'whitespace_only_source_characters') for r in selected)
            context = {'text': previous['text'], 'block_index': previous['block_index'],
                'line_index': previous['line_index'], 'state_phrase': raw[lo:hi], 'state_phrase_evidence': selected,
                'state_phrase_glyph_status': 'raster_consistent_candidate' if visible else 'withheld',
                'basis': 'preceding_same_block_layout_statement_with_bounded_line_and_column_gap',
                'gap_pdf_points': own['bbox'][1]-previous['bbox'][1], 'scope_verified': False}
            # Existing is retained as context, but never relabelled proposed.
            return (match['state'].lower() if visible else 'unknown'), context

        heights = {}
        for start, first in enumerate(lines):
            check()
            window = []
            for end in range(start, min(start+8, len(lines))):
                line = lines[end]
                if end > start and not contiguous(lines[end-1], line):
                    break
                window.append(line)
                text = '\n'.join(v['text'].strip() for v in window).strip()
                if START.match(first['layout_text'].strip()):
                    match = PAIRED.fullmatch(text)
                    if match:
                        values = {k: float(match[k]) for k in ('spacing', 'length', 'width', 'eaves')}
                        ridge = None if match['ridge'] is None else float(match['ridge'])
                        if (any(not math.isfinite(v) or not 0 < v <= 999 for v in values.values())
                                or values['eaves'] > 100 or ridge is not None and not 0 < ridge <= 100):
                            result['withheld'].append({'reason': 'positive_bounded_narrative_dimensions_required', 'source_text': text})
                            break
                        evidence = source_evidence(window)
                        state, context = state_context(start)
                        claim = {'kind': 'paired_row_design_dimensions', 'row_count': 2,
                            'family': 'portacabin' if match['family'].lower().startswith('portacabin') else 'container',
                            'spacing_m': values['spacing'], 'spacing_semantics': 'unspecified_apart',
                            'length_m': values['length'], 'width_m': values['width'],
                            'eaves_height_m': values['eaves'], 'ridge_height_m': ridge,
                            'ridge_approximate': bool(match['approx']),
                            'printed_state': state, 'state_context': context,
                            'status': 'visible_narrative_design_dimension_claim',
                            'source_evidence': evidence, 'physical_identity_verified': False,
                            'ground_datum_verified': False, 'world_placement_eligible': False}
                        claim['id'] = digest([VERSION, sha, number, claim])
                        if evidence['glyph_status'] != 'raster_consistent_candidate':
                            result['withheld'].append({'reason': 'source_narrative_visibility_or_inventory_unresolved', 'candidate': claim})
                        else:
                            if len(result['claims']) >= limits['max_claims']:
                                return finish('narrative_dimension_claim_budget_exceeded')
                            result['claims'].append(claim)
                        break
                if len(window) > 3:
                    continue
                for match in HEIGHT.finditer(text):
                    value = float(match['a'] or match['b'])
                    if not 0 < value <= 100:
                        continue
                    line_offset = text[:match.start()].count('\n')
                    column = len(text[:match.start()].rsplit('\n', 1)[-1])
                    key = (first['block_index'], first['line_index']+line_offset, column, match.group())
                    if key in heights:
                        continue
                    evidence = source_evidence(window)
                    if evidence['glyph_status'] != 'raster_consistent_candidate':
                        continue
                    role = match['role'] or ('ridge' if re.search(r'\bridge\s+(?:approximately\s+)?$', text[:match.start()], re.I) else 'unspecified')
                    height = {'kind': 'height_statement', 'height_m': value,
                        'dimension_role': role.lower(), 'approximate': bool(match['approx'] or match['approx2']),
                        'printed_state': 'unknown', 'physical_component_correspondence_verified': False,
                        'source_evidence': evidence, 'matched_text': match.group(),
                        'ground_datum_verified': False}
                    height['id'] = digest([VERSION, sha, number, height])
                    if len(heights) >= limits['max_height_claims']:
                        return finish('narrative_height_claim_budget_exceeded')
                    heights[key] = height
        result['height_claims'] = list(heights.values())
        signatures = {tuple(c[k] for k in ('row_count', 'spacing_m', 'length_m', 'width_m', 'eaves_height_m', 'ridge_height_m')) for c in result['claims']}
        if len(signatures) > 1:
            result['withheld'].extend({'reason': 'conflicting_paired_row_dimension_paragraphs', 'candidate': c} for c in result['claims'])
            result['claims'] = []
            result['status'] = 'conflicting_narrative_dimensions_withheld'
        return finish()
    except OverflowError as error:
        return finish(str(error))
