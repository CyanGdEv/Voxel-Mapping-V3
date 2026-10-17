"""Original numeric/level glyphs overlapping native cycles; context, not role acceptance."""
import re
import pymupdf
from shapely.geometry import Polygon, mapping, shape
from shapely.strtree import STRtree

from .drawing_geometry import native_inverse
from .ordinary_surfaces import label_runs
from .glyph_visibility import screen_architectural_span

VERSION = 'native-cycle-text-context-v1'


def printed_role(text):
    if re.fullmatch(r'\d{1,6}', text): return 'numeric_label'
    if re.fullmatch(r'[A-Za-z][A-Za-z -]{0,60}\s+Level(?:\s+(?:[+-]\s*)?\d{1,6}(?:\.\d{1,4})?)?', text, re.I):
        return 'level_caption'
    if re.fullmatch(r'[wd]\.\d{1,3}\.\d{1,3}', text, re.I): return 'opening_reference'
    return None


def review(page, scope, frames, *, max_checks=100000):
    if type(max_checks) is not int or not 1 <= max_checks <= 100000 or len(frames) > 512:
        raise ValueError('Bounded native text context required')
    traces = page.get_texttrace()
    if len(traces) > 10000 or sum(len(r['chars']) for r in traces) > 500000:
        return {'version': VERSION, 'status': 'annotation_context_budget_withheld', 'labels': [], 'cycles': []}
    inverse = native_inverse(page); regions = [shape(f['geometry_pdf_native']) for f in frames]
    index = STRtree(regions); labels = []; checks = 0; associations = {f['id']: [] for f in frames}
    for run in label_runs(traces):
        text = ''.join(chr(c[0]) for c in run['chars']).strip(); role = printed_role(text)
        if role is None: continue
        rect = pymupdf.Rect(run['bbox']); points = [p*inverse for p in [rect.tl, rect.tr, rect.br, rect.bl]]
        geometry = Polygon([(p.x, p.y) for p in points])
        if not scope.covers(geometry): continue
        matches = []
        for k in index.query(geometry, predicate='intersects'):
            checks += 1
            if checks > max_checks:
                return {'version': VERSION, 'status': 'annotation_context_budget_withheld', 'labels': [], 'cycles': []}
            k = int(k)
            if regions[k].intersection(geometry).area > 0: matches.append(frames[k]['id'])
        if not matches: continue
        if len(labels) >= 500:
            return {'version': VERSION, 'status': 'annotation_context_budget_withheld', 'labels': [], 'cycles': []}
        label = {'text': text, 'printed_role': role, 'geometry_pdf_native': mapping(geometry),
            'trace_indices': run['trace_indices'], 'character_indices': run['character_indices'],
            'glyph_screen': screen_architectural_span(page, run, zoom=24 if run['size'] < 4 else 6),
            'intersecting_cycle_ids': sorted(matches),
            'containing_cycle_ids': sorted(f['id'] for f, g in zip(frames, regions) if f['id'] in matches and g.covers(geometry)),
            'cycle_box_relations': [{'cycle_id': f['id'],
                'relationship': 'whole_label_box_contained' if g.covers(geometry) else 'label_box_crosses_cycle',
                'label_box_overlap_fraction': g.intersection(geometry).area/geometry.area,
                'cycle_area_overlap_fraction': g.intersection(geometry).area/g.area}
                for f, g in zip(frames, regions) if f['id'] in matches],
            'physical_identity_verified': False}
        labels.append(label)
        if label['glyph_screen']['status'] == 'raster_consistent_candidate':
            for identifier in matches: associations[identifier].append(len(labels)-1)
    cycles = []
    for frame in frames:
        indices = associations[frame['id']]; roles = {labels[i]['printed_role'] for i in indices}
        cycles.append({'cycle_id': frame['id'], 'visible_label_indices': indices,
            'status': 'visible_numeric_or_level_text_overlap' if roles & {'numeric_label', 'level_caption'} else
                'visible_opening_reference_context' if roles else 'no_supported_identifying_text',
            'physical_opening_verified': False, 'automatic_geometry_selection': False})
    return {'version': VERSION, 'status': 'original_glyph_cycle_context_only', 'labels': labels,
        'cycles': cycles, 'checks': checks, 'world_geometry_additions': 0,
        'limitations': ['Native label boxes can cross background cycles because font metrics extend beyond the actual ink.',
            'Visible text overlap is drafting context; a real opening can also contain a printed label.',
            'Every containing cycle remains an alternative. Context never deletes or selects source geometry.']}
