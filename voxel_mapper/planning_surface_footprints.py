"""Fine native boundaries around visible path, plaza and material labels.

The search rectangle selects whole paint primitives. It cannot close a path,
remove a known competing enclosure, establish scale or accept physical geometry.
"""
from concurrent.futures import CancelledError
import json
import math
import re

import pymupdf
from shapely.geometry import Polygon, shape
from shapely.strtree import STRtree

from . import glyph_visibility, ordinary_surfaces, planning_outline_semantics, planning_view_geometry
from .building_spec import digest
from .drawing_page_tools import native_inverse
from .paving_palette import material_label, polygon_surface

VERSION = 'planning-surface-boundaries-v1'
FRAME = 'pdf_native_points_y_up'
SEARCH_MARGIN_POINTS = 144
LIMITS = {'max_surface_labels': 256, 'max_native_candidates': 10000,
          'max_native_points': 200000, 'max_outlines': 500,
          'max_association_checks': 64000, 'max_output_bytes': 8000000}
ROLES = {'path', 'plaza', 'surface'}


def page_candidates(page, sha, number, inventory, associations, *, options=None,
                    cancelled=lambda: False):
    """Return source-bound surface hypotheses; no physical identity is accepted."""
    options = {} if options is None else options
    if not isinstance(options, dict) or set(options)-set(LIMITS):
        raise ValueError('Known surface boundary limits required')
    limits = {**LIMITS, **options}
    if any(type(v) is not int or not 1 <= v <= LIMITS[k] for k, v in limits.items()):
        raise ValueError('Lower-only surface boundary limits required')
    if limits['max_output_bytes'] < 16384:
        raise ValueError('Surface boundary metadata needs 16384 bytes')
    if (not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
            or type(number) is not int or number < 1 or page.number+1 != number
            or not isinstance(inventory, dict)
            or inventory.get('version') != ordinary_surfaces.OUTLINE_VERSION
            or inventory.get('status') != 'complete_source_outline_inventory'
            or inventory.get('inventory_complete') is not True
            or not isinstance(associations, dict)
            or associations.get('version') != planning_outline_semantics.VERSION
            or associations.get('document_sha256') != sha or associations.get('page') != number
            or associations.get('source_inventory_sha256') != digest(inventory)
            or associations.get('inventory_complete') is not True):
        raise ValueError('Complete same-source surface outline associations required')
    records = inventory.get('records')
    if not isinstance(records, list) or len(records) > 500:
        raise ValueError('Bounded source outline records required')
    coarse_geometries = []
    identifiers = set()
    coarse_points = 0
    for record in records:
        candidate = record.get('candidate', {})
        identifier = record.get('candidate_id')
        if (not isinstance(identifier, str) or not re.fullmatch('[0-9a-f]{64}', identifier)
                or identifier in identifiers or candidate.get('id') != identifier
                or record.get('source_record_sha256') != digest(candidate)
                or any(r.get('document_sha256') != sha or r.get('page') != number
                       or r.get('coordinate_frame') != FRAME for r in (record, candidate))):
            raise ValueError('Unchanged same-source unique outline records required')
        geometry = shape(candidate.get('geometry'))
        if (geometry.geom_type != 'Polygon' or geometry.is_empty or not geometry.is_valid
                or not all(math.isfinite(v) for v in geometry.bounds)):
            raise ValueError('Finite complete source polygons required')
        coarse_points += len(geometry.exterior.coords)+sum(len(r.coords) for r in geometry.interiors)
        if coarse_points > 200000:
            raise ValueError('Bounded complete source outline point inventory required')
        identifiers.add(identifier); coarse_geometries.append(geometry)
    def check():
        if cancelled():
            raise CancelledError('Surface boundary recovery cancelled')
    checks = 0
    def charge():
        nonlocal checks
        check(); checks += 1
        if checks > limits['max_association_checks']:
            raise OverflowError('surface_association_work_budget_exceeded')
    check()
    source_labels = associations.get('labels')
    if not isinstance(source_labels, list) or len(source_labels) > 128:
        raise ValueError('Bounded source role labels required')
    labels = []
    result = {'version': VERSION, 'document_sha256': sha, 'page': number,
        'coordinate_frame': FRAME, 'limits': limits,
        'source_inventory_sha256': digest(inventory),
        'source_associations_sha256': digest(associations),
        'status': 'no_visible_surface_labels', 'analysis_complete': True,
        'candidates': [], 'boundary_decisions': [], 'labels': labels,
        'physical_identity_verified': False, 'view_scope_verified': False,
        'registration_verified': False, 'scale_verified': False,
        'world_placement_eligible': False, 'world_geometry_additions': 0,
        'training_labels_generated': 0, 'model_weights_updated': False,
        'geometric_accuracy': None,
        'limitations': ['A visible contained label supports a source boundary hypothesis only.',
            'Material labels do not establish physical horizontal surface identity or drawing scope.',
            'Original holes are preserved; labels inside a hole do not bind to its surrounding face.',
            'No endpoint snapping, gap repair, nearest/smallest selection, clipping or guessed width.',
            'Scale, physical boundary role, finished levels, current state and park alignment remain unresolved.']}
    def finish(reason=None):
        if reason:
            result.update(status='surface_boundaries_withheld', analysis_complete=False,
                          reason=reason, candidates=[])
        visible = [r for r in labels if r['glyph_screen']['status'] == 'raster_consistent_candidate']
        resolved = {r['id'] for c in result['candidates'] for r in c['labels']}
        result.update(surface_labels=len(labels), visible_surface_labels=len(visible),
                      association_checks=checks)
        result['summary'] = {'surface_boundary_candidates': len(result['candidates']),
            'surface_labels': len(labels), 'visible_surface_labels': len(visible),
            'unresolved_surface_labels': len(labels)-len(resolved)}
        if len(json.dumps(result, allow_nan=False).encode()) > limits['max_output_bytes']:
            for key in ('fine_associations', 'fine_inventory_records', 'extraction', 'recovery'):
                result.pop(key, None)
            result.update(status='surface_boundaries_withheld', analysis_complete=False,
                reason='surface_output_budget_exceeded', candidates=[], boundary_decisions=[], labels=[])
            result['summary'].update(surface_boundary_candidates=0,
                                     unresolved_surface_labels=len(labels))
        check(); return result
    # Reuse the already screened literal role evidence; material labels retain
    # separate native trace/character identities and their original glyph proof.
    seen = set()
    for row in source_labels:
        if row.get('claim', {}).get('role') in ROLES:
            label = {**row, 'material': None, 'label_source': 'literal_surface_role'}
            labels.append(label)
            seen.add((tuple(row['trace_indices']), tuple(row['character_indices'])))
    if len(labels) > limits['max_surface_labels']:
        return finish('surface_label_budget_exceeded')
    raw = page.get_texttrace()
    if len(raw) > 10000 or sum(len(r['chars']) for r in raw) > 500000:
        return finish('surface_text_budget_exceeded')
    inverse = native_inverse(page)
    for run in ordinary_surfaces.label_runs(raw):
        check()
        text = ''.join(chr(c[0]) for c in run['chars']).strip()
        material = material_label(text)
        key = (tuple(run['trace_indices']), tuple(run['character_indices']))
        if material is None or key in seen:
            continue
        if len(labels) >= limits['max_surface_labels']:
            return finish('surface_label_budget_exceeded')
        rect = pymupdf.Rect(run['bbox'])
        geometry = Polygon([tuple(p*inverse) for p in (rect.tl, rect.tr, rect.br, rect.bl)])
        screen = glyph_visibility.screen_architectural_span(page, run, zoom=24 if run['size'] < 4 else 6)
        labels.append({'id': digest([VERSION, sha, number, run['trace_indices'], run['character_indices']]),
            'text': text, 'claim': {'role': 'surface', 'scope': 'enclosure', 'printed_state': 'unspecified'},
            'material': material, 'label_source': 'literal_surface_material',
            'trace_indices': run['trace_indices'], 'character_indices': run['character_indices'],
            'geometry_pdf_native': {'type': 'Polygon', 'coordinates': [list(geometry.exterior.coords)]},
            'glyph_screen': screen})
        seen.add(key)
    visible = [r for r in labels if r['glyph_screen']['status'] == 'raster_consistent_candidate']
    if not visible:
        return finish()
    coarse_index = STRtree(coarse_geometries)
    try:
        for label in visible:
            polygon = shape(label['geometry_pdf_native'])
            if (polygon.geom_type != 'Polygon' or not polygon.is_valid or polygon.is_empty
                    or not all(math.isfinite(v) for v in polygon.bounds)):
                raise ValueError('Finite native surface label geometry required')
            matches = []
            for position in coarse_index.query(polygon, predicate='intersects'):
                charge()
                if coarse_geometries[int(position)].contains(polygon):
                    matches.append(records[int(position)]['candidate_id'])
            label['coarse_candidate_ids'] = sorted(matches)
    except OverflowError as error:
        return finish(str(error))
    bounds = [shape(r['geometry_pdf_native']).bounds for r in visible]
    frame = planning_view_geometry._native_frame(page).bounds
    region = [max(frame[0], min(b[0] for b in bounds)-SEARCH_MARGIN_POINTS),
              max(frame[1], min(b[1] for b in bounds)-SEARCH_MARGIN_POINTS),
              min(frame[2], max(b[2] for b in bounds)+SEARCH_MARGIN_POINTS),
              min(frame[3], max(b[3] for b in bounds)+SEARCH_MARGIN_POINTS)]
    extraction_options = {'region_native_points': region, 'min_line_length_points': .25,
        'max_candidates': limits['max_native_candidates'], 'max_total_points': limits['max_native_points'],
        'max_paths': 100000, 'max_scan_paths': 100000, 'regional_fallback': False}
    result.update(search_region_pdf_native=region, search_margin_pdf_points=SEARCH_MARGIN_POINTS,
                  extraction_options=extraction_options)
    check()
    try:
        faces, extraction, recovery, covered = ordinary_surfaces.closed_source_faces(page, sha, number,
            extraction_options=extraction_options, recovery_options={'max_face_provenance': 2048})
    except (ValueError, RuntimeError, OverflowError) as error:
        result['error'] = str(error)[:512]
        return finish('fine_source_geometry_failed')
    check()
    fine_inventory = ordinary_surfaces._outline_inventory(faces, extraction, recovery, limits['max_outlines'])
    result.update(extraction=extraction, recovery=recovery, covered_boundaries_withheld=covered,
        fine_inventory_sha256=digest(fine_inventory),
        fine_inventory_records=[{'candidate_id': r['candidate_id'], 'source_record_sha256': r['source_record_sha256']}
                                for r in fine_inventory['records']])
    if not fine_inventory['inventory_complete']:
        return finish(fine_inventory['reason'])
    fine = planning_outline_semantics.page_candidates(page, sha, number, fine_inventory, cancelled=cancelled)
    result['fine_associations'] = fine
    if not fine['inventory_complete']:
        return finish('fine_label_associations_incomplete')
    fine_records = fine_inventory['records']; geometries = [shape(r['candidate']['geometry']) for r in fine_records]
    index = STRtree(geometries); bound = {}; competing = set()
    try:
        for label in visible:
            polygon = shape(label['geometry_pdf_native']); matches = []
            for position in index.query(polygon, predicate='intersects'):
                charge()
                if geometries[int(position)].contains(polygon):
                    matches.append(fine_records[int(position)]['candidate_id'])
            label['candidate_ids'] = sorted(matches)
            label['status'] = ('ambiguous_source_enclosures_withheld' if len(matches) > 1 else
                              'unique_visible_source_enclosure' if len(matches) == 1 else 'no_supported_source_enclosure')
            if len(matches) == 1:
                bound.setdefault(matches[0], []).append(label)
            elif len(matches) > 1:
                competing.update(matches)
    except OverflowError as error:
        return finish(str(error))
    semantic_outlines = {r['candidate_id']: r for r in fine['outlines']}
    for record in fine_records:
        check(); identifier = record['candidate_id']; support = bound.get(identifier, [])
        if not support:
            continue
        semantic = semantic_outlines.get(identifier)
        role = semantic.get('source_role_hint') if semantic else 'surface'
        reason = ('competing_label_context_withheld' if identifier in competing else
                  'coarse_competing_enclosures_require_interpretation' if any(len(r['coarse_candidate_ids']) > 1 for r in support) else
                  semantic['status'] if semantic and semantic['status'] != 'visible_label_enclosure_hint' else
                  'conflicting_source_roles_withheld' if role not in ROLES else None)
        materials = [r['text'] for r in support if r['material'] is not None]
        surface = polygon_surface(materials)
        if reason is None and surface is None:
            reason = 'conflicting_surface_materials_withheld'
        decision = {'candidate_id': identifier, 'label_ids': [r['id'] for r in support],
                    'status': 'withheld', 'reason': reason}
        result['boundary_decisions'].append(decision)
        if reason:
            continue
        candidate = {'id': digest([VERSION, sha, number, identifier, sorted(r['id'] for r in support)]),
            'status': 'source_surface_boundary_hypothesis', 'document_sha256': sha, 'page': number,
            'coordinate_frame': FRAME, 'geometry_pdf_native': record['candidate']['geometry'],
            'source_outline': record, 'labels': support, 'source_role_hint': role,
            'surface': surface, 'material_basis': 'bound source labels' if materials else 'user stone default on labelled surface',
            'physical_identity_verified': False, 'world_placement_eligible': False, 'geometric_accuracy': None}
        result['candidates'].append(candidate)
        decision.update(status='source_surface_boundary_hypothesis', reason=None)
    result['status'] = 'source_surface_boundary_candidates'
    return finish()
