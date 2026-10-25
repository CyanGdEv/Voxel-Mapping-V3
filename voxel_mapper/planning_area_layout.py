"""Source-local shared-frame area proposals, without physical or world acceptance."""
from concurrent.futures import CancelledError
from html import escape
import hashlib
import json
import math
from pathlib import Path
import re

from shapely.affinity import affine_transform
from shapely.geometry import box, mapping, shape

from . import architectural_view_layout, ordinary_surfaces, planning_component_measurements
from . import planning_component_footprints, planning_outline_semantics, planning_view_geometry
from . import planning_surface_footprints
from . import planning_area_scale
from .building_spec import digest
from .paving_palette import material_label, polygon_surface

VERSION = 'planning-area-layout-v1'
FRAME = 'pdf_native_points_y_up'
LIMITS = {'max_candidates': 128, 'max_points': 100000,
          'max_pair_checks': 8192, 'max_output_bytes': 8000000}
SUMMARY_KEYS = ('nominal_area_layout_candidates', 'nominal_area_building_candidates',
    'nominal_area_path_plaza_candidates', 'nominal_area_boundary_contacts',
    'nominal_area_overlap_pairs', 'nominal_area_gap_pairs', 'registered_area_layouts')


def _limits(options):
    options = {} if options is None else options
    if not isinstance(options, dict) or set(options)-set(LIMITS):
        raise ValueError('Known area layout limits required')
    result = {**LIMITS, **options}
    if (any(type(v) is not int or not 1 <= v <= LIMITS[k] for k, v in result.items())
            or result['max_output_bytes'] < 16384):
        raise ValueError('Lower-only bounded area layout limits required')
    return result


def _polygon(value):
    geometry = shape(value)
    if (geometry.geom_type != 'Polygon' or geometry.is_empty or not geometry.is_valid
            or geometry.has_z or not all(math.isfinite(v) for v in geometry.bounds)):
        raise ValueError('Complete finite two-dimensional source polygon required')
    return geometry


def _record(record, sha, number):
    if not isinstance(record, dict) or not isinstance(record.get('candidate'), dict):
        raise ValueError('Complete source outline record required')
    candidate = record['candidate']
    if (not re.fullmatch('[0-9a-f]{64}', str(record.get('candidate_id')))
            or candidate.get('id') != record['candidate_id']
            or record.get('source_record_sha256') != digest(candidate)
            or any(r.get('document_sha256') != sha or r.get('page') != number
                or r.get('coordinate_frame') != FRAME for r in (record, candidate))):
        raise ValueError('Exact same-page source outline record required')
    return _polygon(candidate['geometry'])


def _affine(context):
    caption = context['caption']; claim = caption['printed_claim']
    source_layout = context['caption_layout']
    visible = [r for r in source_layout['view_captions']+source_layout['sheet_titles']
               if r.get('glyph_screen', {}).get('status') == 'raster_consistent_candidate']
    if (source_layout.get('version') not in ('architectural-caption-layout-v4',architectural_view_layout.VERSION)
            or visible != [caption]
            or (claim.get('view_kind') != 'plan' and not
                (claim.get('view_kind') == 'sheet_title' and claim.get('plan_level_or_form') in ('site', 'block')))
            or claim.get('plan_level_or_form') in ('roof', 'firstfloor', 'secondfloor', 'first', 'second')):
        raise ValueError('One exact horizontal ground or site plan context required')
    if (caption.get('glyph_screen', {}).get('status') != 'raster_consistent_candidate'
            or context['measurements'].get('analysis_complete') is not True
            or context['measurements'].get('pdf_user_unit') != 1):
        raise ValueError('Visible nominal plan and supported native paper required')
    denominator = context['printed_scale_denominator']
    resolution=planning_area_scale.resolve(caption,source_layout,context['measurements'])
    if (type(denominator) is not int or resolution['printed_scale_denominator']!=denominator
            or ('scale_resolution' in context and context['scale_resolution']!=resolution)
            or (resolution['basis']=='original_page_iso_paper_match' and 'scale_resolution' not in context)):
        raise ValueError('One visible unambiguous per-plan scale required')
    axis = caption.get('reading_direction_pdf_native')
    if axis not in ([1., 0.], [0., 1.], [-1., 0.], [0., -1.]):
        raise ValueError('Orthogonal source caption reading direction required')
    bounds = context['native_page_bounds']
    if (not isinstance(bounds, list) or len(bounds) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds)
            or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]):
        raise ValueError('Bounded native original page required')
    measured_mm = context['measurements'].get('effective_page_dimensions_mm', [])
    actual_mm = sorted([(bounds[2]-bounds[0])*25.4/72, (bounds[3]-bounds[1])*25.4/72])
    if len(measured_mm) != 2 or any(abs(a-b)>1e-6 for a,b in zip(actual_mm, measured_mm)):
        raise ValueError('Original page dimensions differ from nominal paper receipt')
    frame = box(*bounds)
    if not frame.covers(_polygon(caption['label_geometry'])):
        raise ValueError('Caption must remain inside its original page')
    normal = [-axis[1], axis[0]]
    points = list(frame.exterior.coords)
    a = min(sum(p[k]*axis[k] for k in (0, 1)) for p in points)
    b = min(sum(p[k]*normal[k] for k in (0, 1)) for p in points)
    factor = denominator*.0254/72
    matrix = [axis[0]*factor, axis[1]*factor, normal[0]*factor,
              normal[1]*factor, -a*factor, -b*factor]
    return {'coordinate_frame': 'nominal_area_xy_metres',
        'native_coordinate_frame': FRAME, 'native_to_nominal_local_affine': matrix,
        'origin_pdf_native': [axis[k]*a+normal[k]*b for k in (0, 1)],
        'metres_per_pdf_point': factor, 'printed_scale_denominator': denominator,
        'caption_id': caption['id'], 'source_context_sha256': digest(context),
        'local_origin_is_physical_datum': False, 'physical_scale_verified': False}


def _relations(candidates, maximum, check):
    relations = []; count = 0
    for i, left in enumerate(candidates):
        a = _polygon(left['geometry_nominal_local'])
        for right in candidates[i+1:]:
            check(); count += 1
            if count > maximum:
                raise ValueError('Area layout pair work budget exceeded')
            b = _polygon(right['geometry_nominal_local'])
            overlap = a.intersection(b).area
            contact = a.boundary.intersection(b.boundary).length
            gap = a.distance(b)
            kind = ('overlap' if overlap > 0 else 'boundary_contact' if contact > 0
                    else 'point_contact' if a.intersects(b) else 'disjoint_gap')
            relations.append({'a': left['id'], 'b': right['id'], 'kind': kind,
                'boundary_contact_length_m': contact, 'overlap_area_m2': overlap,
                'gap_m': gap, 'traversable': None,
                'entrance_correspondence_verified': False, 'finished_levels_verified': False})
    return relations


def _summary(result):
    rows = result['candidates']; edges = result['relations']
    return {'nominal_area_layout_candidates': len(rows),
        'nominal_area_building_candidates': sum(r['role'] == 'building' for r in rows),
        'nominal_area_path_plaza_candidates': sum(r['role'] in ('path', 'plaza') for r in rows),
        'nominal_area_boundary_contacts': sum(r['kind'] == 'boundary_contact' for r in edges),
        'nominal_area_overlap_pairs': sum(r['kind'] == 'overlap' for r in edges),
        'nominal_area_gap_pairs': sum(r['kind'] == 'disjoint_gap' for r in edges),
        'registered_area_layouts': 0}


def _row_id(sha, number, row):
    return digest([VERSION, sha, number, row['role'], row['geometry_pdf_native'],
                   row['source_evidence_sha256']])



def _semantics(evidence, sha, number):
    """Derive role/material/state from the retained visible literal labels."""
    record = evidence['source_outline']; native = _record(record, sha, number)
    semantic = evidence['semantic_evidence']; kind = evidence.get('kind')
    surface_version=semantic.get('surface_version','planning-surface-boundaries-v1')
    if surface_version not in ('planning-surface-boundaries-v1','planning-surface-boundaries-v2',planning_surface_footprints.VERSION):
        raise ValueError('Known source surface boundary version required')
    labels = semantic.get('labels', []) + ([semantic['label']] if 'label' in semantic else [])
    if not labels or len(labels) > 256:
        raise ValueError('Bounded visible source labels required')
    roles = set(); states = set(); materials = []
    for label in labels:
        if (label.get('glyph_screen', {}).get('status') != 'raster_consistent_candidate'
                or not native.contains(_polygon(label['geometry_pdf_native']))):
            raise ValueError('Visible whole source label inside original boundary required')
        printed = planning_outline_semantics.claim(label.get('text'))
        finish = material_label(label.get('text'))
        if printed is not None:
            if label.get('claim') != printed:
                raise ValueError('Literal source role differs from retained label text')
            expected_label_id = digest([planning_outline_semantics.VERSION, sha, number,
                label['trace_indices'], label['character_indices']])
        elif kind == 'fine_surface' and finish is not None:
            if label.get('claim') != {'role': 'surface', 'scope': 'enclosure', 'printed_state': 'unspecified'}:
                raise ValueError('Literal material label cannot supply another role')
            expected_label_id = digest([surface_version, sha, number,
                label['trace_indices'], label['character_indices']])
        else:
            raise ValueError('Supported literal role or material label required')
        if label.get('id') != expected_label_id:
            raise ValueError('Exact source trace and character label identity required')
        if label.get('material') not in (None, finish):
            raise ValueError('Surface finish differs from visible source text')
        if finish is not None: materials.append(label['text'])
        roles.add(label['claim']['role'])
        state = label['claim'].get('printed_state', 'unspecified')
        if state != 'unspecified': states.add('proposed' if state == 'new' else state)
    primary = roles-{'surface'}
    if len(primary) > 1 or 'annotation' in roles or len(states) > 1:
        raise ValueError('Conflicting source roles or drawing states')
    role = next(iter(primary)) if primary else 'surface'
    if kind in ('coarse_building', 'fine_building'):
        association = semantic['association']
        if (role != 'building' or association.get('status') != 'visible_label_enclosure_hint'
                or association.get('source_role_hint') != 'building'
                or association.get('candidate_id') != record['candidate_id']
                or association.get('source_record_sha256') != record['source_record_sha256']
                or set(association.get('label_ids', [])) != {r['id'] for r in labels}):
            raise ValueError('Exact visible building association required')
        if kind == 'fine_building' and semantic.get('component') != digest([
                planning_component_footprints.VERSION, sha, number, record['candidate_id'], labels[0]['id']]):
            raise ValueError('Exact fine component identity required')
        surface = None
    elif kind == 'fine_surface':
        if role not in ('path', 'plaza', 'surface'):
            raise ValueError('Exact visible surface role required')
        if semantic.get('surface_candidate') != digest([surface_version, sha,
                number, record['candidate_id'], sorted(r['id'] for r in labels)]):
            raise ValueError('Exact fine surface identity required')
        surface = polygon_surface(materials)
        if surface is None: raise ValueError('Conflicting visible surface finishes')
        if semantic.get('material_basis') != ('bound source labels' if materials else 'user stone default on labelled surface'):
            raise ValueError('Exact visible material or explicit user default basis required')
    else:
        raise ValueError('Known source boundary evidence kind required')
    return role, surface, states

def page_layout(page, sha, number, layout, inventory, associations, components, surfaces,
                *, options=None, cancelled=lambda: False):
    limits = _limits(options)
    if (not re.fullmatch('[0-9a-f]{64}', str(sha)) or type(number) is not int
            or page.number+1 != number):
        raise ValueError('Same pinned original area page required')
    def check():
        if cancelled(): raise CancelledError('Area layout cancelled')
    check()
    result = {'version': VERSION, 'document_sha256': sha, 'page': number,
        'status': 'nominal_source_local_area_layout', 'analysis_complete': True,
        'limits': limits, 'source_pins': {k: digest(v) for k, v in
            [('layout', layout), ('inventory', inventory), ('associations', associations),
             ('components', components), ('surfaces', surfaces)]},
        'source_context': None, 'shared_frame': None, 'candidates': [], 'relations': [],
        'withheld': [], 'physical_identity_verified': False,
        'physical_scale_verified': False, 'registration_verified': False,
        'ground_datum_verified': False, 'world_placement_eligible': False,
        'physical_traversability': None, 'geometric_accuracy': None,
        'training_labels_generated': 0, 'model_weights_updated': False,
        'world_geometry_additions': 0,
        'limitations': ['Shapes are literal source-label boundary proposals, not accepted physical buildings or paths.',
            'One common nominal printed-scale frame preserves relative positions only on this source page.',
            'The original page corner is a display origin, not surveyed park coordinates or a ground datum.',
            'Boundary contact and overlap are two-dimensional diagnostics, not entrances or walkable routes.',
            'No height, roof, doorway, path width, snapping, gap fill, training label or park block is invented.']}
    def finish(reason=None):
        if reason:
            result.update(status='area_layout_withheld', analysis_complete=False, reason=reason,
                candidates=[], relations=[], shared_frame=None)
        result['summary'] = _summary(result)
        if len(json.dumps(result, allow_nan=False).encode())+80 > limits['max_output_bytes']:
            result.update(status='area_layout_withheld', analysis_complete=False,
                reason='area_layout_output_budget_exceeded', candidates=[], relations=[],
                shared_frame=None, source_context=None, withheld=[])
            result['summary'] = _summary(result)
        check(); result['id'] = digest(result)
        return json.loads(json.dumps(result, allow_nan=False))
    if layout is None or inventory is None or associations is None:
        return finish('complete_original_layout_and_source_inventory_required')
    if (layout.get('version') != architectural_view_layout.VERSION
            or layout.get('document_sha256') != sha or layout.get('page') != number
            or inventory.get('version') != ordinary_surfaces.OUTLINE_VERSION
            or associations.get('version') != planning_outline_semantics.VERSION
            or associations.get('document_sha256') != sha or associations.get('page') != number
            or associations.get('source_inventory_sha256') != digest(inventory)):
        raise ValueError('Exact current same-page layout and source associations required')
    if inventory.get('inventory_complete') is not True or associations.get('inventory_complete') is not True:
        return finish('complete_source_boundary_associations_required')
    for pack, version in ((components, planning_component_footprints.VERSION),
                          (surfaces, planning_surface_footprints.VERSION)):
        if pack is not None:
            if (pack.get('version') != version or pack.get('document_sha256') != sha or pack.get('page') != number
                    or pack.get('source_inventory_sha256') != digest(inventory)
                    or pack.get('source_associations_sha256') != digest(associations)):
                raise ValueError('Exact same-page boundary discovery pack required')
            if pack.get('analysis_complete') is not True:
                return finish('complete_fine_boundary_discovery_required')
    visible = [r for r in layout['view_captions']+layout['sheet_titles']
               if r.get('glyph_screen', {}).get('status') == 'raster_consistent_candidate']
    if len(visible) != 1:
        if not visible and layout['view_captions']+layout['sheet_titles']:
            return finish('complete_plan_caption_glyph_evidence_required')
        return finish('one_unambiguous_horizontal_plan_context_required')
    caption = visible[0]; claim = caption['printed_claim']
    if (claim.get('view_kind') != 'plan' and not
            (claim.get('view_kind') == 'sheet_title' and claim.get('plan_level_or_form') in ('site', 'block'))):
        return finish('horizontal_ground_or_site_plan_required')
    if claim.get('plan_level_or_form') in ('roof', 'firstfloor', 'secondfloor', 'first', 'second'):
        return finish('horizontal_ground_or_site_plan_required')
    measurements = planning_component_measurements.page_evidence(page, sha, number, layout, None,
        cancelled=cancelled)
    if measurements['analysis_complete'] is not True:
        return finish(measurements.get('reason', 'supported_native_paper_required'))
    try:resolution=planning_area_scale.resolve(caption,layout,measurements)
    except ValueError as error:return finish(str(error))
    result['source_context'] = {'caption': caption, 'caption_layout': layout, 'measurements': measurements,
        'native_page_bounds': list(planning_view_geometry._native_frame(page).bounds),
        'printed_scale_denominator': resolution['printed_scale_denominator'],
        'scale_resolution':resolution,
        'context_scope': 'single visible horizontal plan context; physical view extent unverified'}
    try: result['shared_frame'] = _affine(result['source_context'])
    except ValueError as error: return finish(str(error))
    records = {r['candidate_id']: r for r in inventory['records']}
    labels = {r['id']: r for r in associations['labels']}
    raw = []
    def add(role, geometry, record, semantic, kind, surface=None):
        check(); source = _record(record, sha, number)
        native = _polygon(geometry)
        if not source.equals_exact(native, 0): raise ValueError('Boundary differs from retained source polygon')
        if not box(*result['source_context']['native_page_bounds']).covers(native):
            raise ValueError('Source boundary escapes original page')
        evidence = {'kind': kind, 'source_outline': record, 'semantic_evidence': semantic}
        derived_role, derived_surface, _ = _semantics(evidence, sha, number)
        if role != derived_role or surface != derived_surface:
            raise ValueError('Candidate role or finish differs from retained source labels')
        raw.append({'role': role, 'geometry_pdf_native': geometry, 'source_evidence': [evidence],
                    'surface': surface})
    for association in associations['outlines']:
        check()
        if association['status'] != 'visible_label_enclosure_hint' or association['source_role_hint'] != 'building': continue
        record = records.get(association['candidate_id'])
        if record is None or association['source_record_sha256'] != record['source_record_sha256']:
            raise ValueError('Area association must bind retained source outline')
        add('building', record['candidate']['geometry'], record,
            {'association': association, 'labels': [labels[k] for k in association['label_ids']]}, 'coarse_building')
    for row in (components or {}).get('candidates', []):
        add('building', row['geometry_pdf_native'], row['source_outline'],
            {'component': row['id'], 'label': row['label'], 'association': row['association']}, 'fine_building')
    for row in (surfaces or {}).get('candidates', []):
        if row.get('coordinate_frame') != FRAME or row.get('document_sha256') != sha or row.get('page') != number:
            raise ValueError('Same native page surface boundary required')
        role = row.get('source_role_hint')
        if role not in ('path', 'plaza', 'surface'): raise ValueError('Supported literal surface role required')
        add(role, row['geometry_pdf_native'], row['source_outline'],
            {'surface_candidate': row['id'], 'surface_version':surfaces['version'], 'labels': row['labels'],
             'material_basis': row.get('material_basis')}, 'fine_surface', row.get('surface'))
    if len(raw) > limits['max_candidates']: return finish('area_layout_candidate_budget_exceeded')
    merged = []
    for row in raw:
        geometry = _polygon(row['geometry_pdf_native'])
        matches = [r for r in merged if r['role'] == row['role']
                   and _polygon(r['geometry_pdf_native']).equals(geometry)]
        if matches:
            matches[0]['source_evidence'] += row['source_evidence']
        else: merged.append(row)
    ambiguous = set(); checks = 0
    for i, a in enumerate(merged):
        for j in range(i+1, len(merged)):
            check(); checks += 1
            if checks > limits['max_pair_checks']: return finish('area_layout_pair_work_budget_exceeded')
            left, right = map(_polygon, (a['geometry_pdf_native'], merged[j]['geometry_pdf_native']))
            if left.covers(right) or right.covers(left):
                ambiguous.update((i, j))
                result['withheld'].append({'reason': 'nested_or_conflicting_role_boundaries',
                    'source_candidate_ids': sorted({e['source_outline']['candidate_id']
                        for r in (a, merged[j]) for e in r['source_evidence']})})
    points = 0
    for index, row in enumerate(merged):
        if index in ambiguous: continue
        native = _polygon(row['geometry_pdf_native']); points += len(native.exterior.coords)+sum(len(r.coords) for r in native.interiors)
        if points > limits['max_points']: return finish('area_layout_point_budget_exceeded')
        nominal = affine_transform(native, result['shared_frame']['native_to_nominal_local_affine'])
        states = set()
        for evidence in row['source_evidence']:
            _, _, source_states = _semantics(evidence, sha, number)
            states.update(source_states)
        caption_state = claim.get('printed_state', 'unspecified')
        if caption_state != 'unspecified': states.add(caption_state)
        if len(states) > 1:
            result['withheld'].append({'reason': 'conflicting_caption_and_component_states',
                'source_candidate_ids': [e['source_outline']['candidate_id'] for e in row['source_evidence']]}); continue
        row.update(source_evidence_sha256=digest(row['source_evidence']),
            geometry_nominal_local=mapping(nominal), nominal_area_m2=nominal.area,
            nominal_perimeter_m=nominal.length, nominal_bounds_m=list(nominal.bounds),
            printed_state=next(iter(states)) if states else 'unknown', height_m=None,
            physical_identity_verified=False, physical_scale_verified=False,
            world_placement_eligible=False)
        row['id'] = _row_id(sha, number, row)
        result['candidates'].append(row)
    try: result['relations'] = _relations(result['candidates'], limits['max_pair_checks'], check)
    except ValueError: return finish('area_layout_pair_work_budget_exceeded')
    return finish()


def validate_layout(result):
    """Recompute shared-frame polygons and graph before reload or draft export.

    This proves source-record consistency, never original-PDF authenticity or
    physical identity; the producer/caller retains and checks original PDF pins.
    """
    if (not isinstance(result, dict) or result.get('version') != VERSION
            or set(result)-{'version','document_sha256','page','status','analysis_complete',
                'limits','source_pins','source_context','shared_frame','candidates','relations',
                'withheld','physical_identity_verified','physical_scale_verified','registration_verified',
                'ground_datum_verified','world_placement_eligible','physical_traversability',
                'geometric_accuracy','training_labels_generated','model_weights_updated',
                'world_geometry_additions','limitations','summary','id','reason'}
            or result.get('id') != digest({k: v for k, v in result.items() if k != 'id'})
            or not re.fullmatch('[0-9a-f]{64}', str(result.get('document_sha256')))
            or type(result.get('page')) is not int or result['page'] < 1):
        raise ValueError('Exact current source-local area layout required')
    if (type(result.get('analysis_complete')) is not bool
            or result.get('status') != ('nominal_source_local_area_layout'
                if result['analysis_complete'] else 'area_layout_withheld')
            or result.get('geometric_accuracy') is not None):
        raise ValueError('Source-local layout cannot claim completed physical reconstruction or accuracy')
    limits = _limits(result.get('limits'))
    if len(json.dumps(result, allow_nan=False).encode()) > limits['max_output_bytes']:
        raise ValueError('Area layout output budget exceeded')
    for key in ('physical_identity_verified', 'physical_scale_verified', 'registration_verified',
                'ground_datum_verified', 'world_placement_eligible', 'model_weights_updated'):
        if result.get(key) is not False: raise ValueError('Unverified source-local layout required')
    if (result.get('physical_traversability') is not None or result.get('training_labels_generated') != 0
            or result.get('world_geometry_additions') != 0):
        raise ValueError('Area layout cannot claim traversal, labels or park geometry')
    rows = result.get('candidates'); edges = result.get('relations')
    if not isinstance(rows, list) or len(rows) > limits['max_candidates'] or not isinstance(edges, list):
        raise ValueError('Bounded area candidate and graph inventory required')
    if result['analysis_complete'] is not True:
        if rows or edges or result.get('shared_frame') is not None:
            raise ValueError('Withheld layout cannot contain usable geometry')
    else:
        context = result.get('source_context')
        if not isinstance(context, dict) or result.get('shared_frame') != _affine(context):
            raise ValueError('Exact common source-derived nominal frame required')
        measurements = context['measurements']
        if (measurements.get('version') != planning_component_measurements.VERSION
                or measurements.get('id') != digest({k: v for k, v in measurements.items() if k != 'id'})
                or measurements.get('document_sha256') != result['document_sha256']
                or measurements.get('page') != result['page']
                or measurements.get('source_layout_sha256') != result['source_pins']['layout']
                or digest(context['caption_layout']) != result['source_pins']['layout']
                or context['caption_layout'].get('document_sha256') != result['document_sha256']
                or context['caption_layout'].get('page') != result['page']):
            raise ValueError('Exact source-bound paper and scale measurement receipt required')
        ids = set(); points = 0
        for row in rows:
            if (row.get('role') not in ('building', 'path', 'plaza', 'surface')
                    or row.get('source_evidence_sha256') != digest(row.get('source_evidence'))
                    or row.get('id') != _row_id(result['document_sha256'], result['page'], row)
                    or row['id'] in ids or row.get('height_m') is not None
                    or row.get('physical_identity_verified') is not False
                    or row.get('physical_scale_verified') is not False
                    or row.get('world_placement_eligible') is not False):
                raise ValueError('Exact unique source geometry candidate required')
            ids.add(row['id']); native = _polygon(row['geometry_pdf_native'])
            if not box(*context['native_page_bounds']).covers(native):
                raise ValueError('Original source page must contain complete boundary')
            if not isinstance(row['source_evidence'], list) or not row['source_evidence']:
                raise ValueError('Original boundary evidence required')
            states = set()
            for evidence in row['source_evidence']:
                if not _record(evidence['source_outline'], result['document_sha256'], result['page']).equals(native):
                    raise ValueError('Candidate polygon differs from original source record')
                role, surface, source_states = _semantics(evidence, result['document_sha256'], result['page'])
                if row['role'] != role or row.get('surface') != surface:
                    raise ValueError('Candidate role or material differs from original source labels')
                states.update(source_states)
            state = context['caption']['printed_claim'].get('printed_state', 'unspecified')
            if state != 'unspecified': states.add(state)
            if len(states) > 1 or row.get('printed_state') != (next(iter(states)) if states else 'unknown'):
                raise ValueError('Candidate drawing state differs from original source context')
            points += len(native.exterior.coords)+sum(len(r.coords) for r in native.interiors)
            nominal = affine_transform(native, result['shared_frame']['native_to_nominal_local_affine'])
            if (mapping(nominal) != mapping(_polygon(row['geometry_nominal_local']))
                    or row.get('nominal_area_m2') != nominal.area
                    or row.get('nominal_perimeter_m') != nominal.length
                    or row.get('nominal_bounds_m') != list(nominal.bounds)):
                raise ValueError('Nominal candidate must preserve the one common source affine')
        if points > limits['max_points']: raise ValueError('Area layout point budget exceeded')
        if edges != _relations(rows, limits['max_pair_checks'], lambda: None):
            raise ValueError('Exact source-local planar relation graph required')
    if result.get('summary') != _summary(result): raise ValueError('Exact area layout counters required')
    return result


def write_review(root, pages, *, cancelled=lambda: False):
    """Write source-local overlays and portable GeoJSON; no world is generated."""
    if not isinstance(pages, list) or len(pages) > 512:
        raise ValueError('Bounded area layout page inventory required')
    if cancelled(): raise CancelledError('Area layout review cancelled')
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    total_bytes = 0; pins = {}; files = []; seen = set()
    summary = dict.fromkeys(SUMMARY_KEYS, 0)
    body = ['<!doctype html><html lang="en"><meta charset="utf-8"><title>Source-local area layouts</title>',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<style>body{font:16px system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem;line-height:1.5}svg{width:100%;max-height:560px;background:#f1f4f5}li{margin:.5rem 0}</style>',
        '<h1>Source-local building and path layouts</h1><p>Original polygon proposals share one nominal printed-scale frame per page. '
        'Purple: buildings; blue: paths; green: plazas; grey: other labelled surfaces. '
        'These are unverified source outlines. Heights, roofs, entrances, finished levels, surveyed park placement and walkable connectivity remain unresolved.</p>']
    def write(name, value):
        nonlocal total_bytes
        data = value.encode('utf-8') if isinstance(value, str) else value
        total_bytes += len(data)
        if total_bytes > 64000000: raise ValueError('Area layout review output budget exceeded')
        (root/name).write_bytes(data); pins[name] = hashlib.sha256(data).hexdigest()
    for result in pages:
        if cancelled(): raise CancelledError('Area layout review cancelled')
        validate_layout(result)
        key = (result['document_sha256'], result['page'])
        if key in seen: raise ValueError('Unique area layout source pages required')
        seen.add(key)
        for k in summary: summary[k] += result['summary'][k]
        stem = 'area-layout-'+result['document_sha256']+'-'+str(result['page'])
        name = stem+'.json'; write(name, json.dumps(result, indent=2, allow_nan=False)+'\n')
        entry = {'id': result['id'], 'file': name, 'sha256': pins[name],
            'document_sha256': key[0], 'page': key[1], 'candidate_count': len(result['candidates']),
            'building_candidates': result['summary']['nominal_area_building_candidates'],
            'path_plaza_candidates': result['summary']['nominal_area_path_plaza_candidates'],
            'status': result['status']}
        files.append(entry)
        body.append('<h2>Source '+escape(key[0][:12])+' · page '+str(key[1])+'</h2>')
        body.append('<p><a href="'+name+'">Exact layout and evidence</a></p>')
        if not result['analysis_complete'] or not result['candidates']:
            body.append('<p>No usable area layout: '+escape(result.get('reason', 'no supported building or path boundaries'))+'.</p>'); continue
        collection = {'type': 'FeatureCollection', 'coordinate_frame': 'nominal_area_xy_metres',
            'geographic_registration': None, 'world_placement_eligible': False,
            'source_layout_id': result['id'], 'shared_frame': result['shared_frame'],
            'features': [{'type': 'Feature', 'id': r['id'], 'geometry': r['geometry_nominal_local'],
                'properties': {'role': r['role'], 'printed_state': r['printed_state'],
                    'height_m': None, 'physical_identity_verified': False,
                    'source_evidence_sha256': r['source_evidence_sha256']}} for r in result['candidates']]}
        geo = stem+'.geojson'; write(geo, json.dumps(collection, indent=2, allow_nan=False)+'\n')
        entry.update(geojson_file=geo, geojson_sha256=pins[geo])
        polygons = [_polygon(r['geometry_nominal_local']) for r in result['candidates']]
        xmin = min(g.bounds[0] for g in polygons); ymin = min(g.bounds[1] for g in polygons)
        xmax = max(g.bounds[2] for g in polygons); ymax = max(g.bounds[3] for g in polygons)
        scale = min(1000/max(xmax-xmin, 1e-9), 480/max(ymax-ymin, 1e-9))
        body.append('<p><a download href="'+geo+'">Download nominal local GeoJSON</a> — '+
            str(len(polygons))+' boundary proposals, '+str(result['summary']['nominal_area_boundary_contacts'])+
            ' boundary contacts, '+str(result['summary']['nominal_area_gap_pairs'])+' disjoint pairs. '
            'Contacts do not establish traversable entrances; gaps are preserved.</p>')
        body.append('<svg viewBox="0 0 1040 530" role="img" aria-label="Source-local shared-frame building and path boundary proposals">')
        for row, polygon in zip(result['candidates'], polygons):
            commands = []
            for ring in [polygon.exterior, *polygon.interiors]:
                commands.append('M'+' L'.join(f'{20+(x-xmin)*scale:.3f},{500-(y-ymin)*scale:.3f}' for x, y in ring.coords)+' Z')
            colour = {'building': '#a15cb7', 'path': '#368cb5', 'plaza': '#5a9b76', 'surface': '#939ca5'}[row['role']]
            body.append('<path fill="'+colour+'" fill-opacity=".35" fill-rule="evenodd" stroke="'+colour+'" stroke-width="1.5" d="'+''.join(commands)+'"><title>'+escape(row['role']+' '+row['id'][:12])+'</title></path>')
        body.append('</svg>')
    body.append('<p>No model weights, training labels or accepted park blocks are produced. '
                '<a href="area-layouts.json">Complete source-local layout inventory</a></p></html>')
    write('area-layouts.html', ''.join(body))
    review = {'version': VERSION, 'status': 'source_local_area_layout_review',
        'pages': pages, 'page_layout_files': files, 'summary': summary,
        'world_placement_eligible': False, 'physical_traversability': None,
        'training_labels_generated': 0, 'model_weights_updated': False,
        'world_geometry_additions': 0, 'output_sha256': pins}
    write('area-layouts.json', json.dumps(review, indent=2, allow_nan=False)+'\n')
    # Exclude the report's own hash; its serialized manifest cannot contain itself.
    pins.pop('area-layouts.json', None)
    if cancelled(): raise CancelledError('Area layout review cancelled')
    return review


validate_result = validate_layout
