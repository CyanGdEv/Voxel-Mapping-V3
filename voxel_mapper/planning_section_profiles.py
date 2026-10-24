"""Labelled native section spans; no physical height or plan correspondence."""
from concurrent.futures import CancelledError
from html import escape
import json
import math
from pathlib import Path
import re

from shapely.affinity import affine_transform
from shapely.geometry import mapping, shape

from . import drawing_view_candidates, ordinary_surfaces, planning_outline_semantics
from . import planning_component_measurements, planning_view_geometry
from .building_spec import digest

VERSION = 'planning-section-profiles-v1'
LIMITS = {'max_profiles': 32, 'max_checks': 8192, 'max_output_bytes': 8000000}


def page_evidence(page, sha, number, views, measurements, *, options=None, cancelled=lambda: False):
    options = {} if options is None else options
    if not isinstance(options, dict) or set(options)-set(LIMITS):
        raise ValueError('Known section profile limits required')
    limits = {**LIMITS, **options}
    if (any(type(v) is not int or not 1 <= v <= LIMITS[k] for k, v in limits.items())
            or limits['max_output_bytes'] < 16384):
        raise ValueError('Lower-only section profile limits required')
    if (not re.fullmatch('[0-9a-f]{64}', str(sha)) or type(number) is not int or page.number+1 != number
            or views.get('version') != drawing_view_candidates.VERSION
            or views.get('document_sha256') != sha or views.get('page') != number
            or measurements.get('version') != planning_component_measurements.VERSION
            or measurements.get('document_sha256') != sha or measurements.get('page') != number
            or measurements.get('id') != digest({k: v for k, v in measurements.items() if k != 'id'})
            or views.get('source_layout_sha256') != measurements.get('source_layout_sha256')):
        raise ValueError('Same current pinned original view and measurement evidence required')
    def check():
        if cancelled():
            raise CancelledError('Section profile analysis cancelled')
    check()
    result = {'version': VERSION, 'document_sha256': sha, 'page': number, 'limits': limits,
        'source_view_pack_sha256': digest(views), 'source_measurements_sha256': digest(measurements),
        'status': 'nominal_section_profile_evidence_only', 'analysis_complete': True,
        'source_inventory': None, 'label_associations': None, 'profiles': [], 'withheld': [], 'checks': 0,
        'physical_height_m': None, 'physical_height_verified': False,
        'plan_component_correspondence_verified': False, 'local_3d_components': 0,
        'world_geometry_additions': 0, 'world_placement_eligible': False,
        'training_labels_generated': 0, 'model_weights_updated': False,
        'limitations': ['Spans describe retained source polygons along the printed section axes.',
            'Coarse linework enclosures are diagnostic hypotheses; exterior-wall and paint visibility are unverified.',
            'View scope and paper scale are drawing hypotheses, not checked physical dimensions.',
            'No plan component, ground datum or physical building height is assigned; no 3D shell is generated.']}
    def finish(reason=None):
        if reason:
            result.update(status='section_profiles_withheld', analysis_complete=False, reason=reason, profiles=[])
        result['summary'] = {'nominal_section_profile_hypotheses': len(result['profiles']),
            'physical_section_heights_verified': 0}
        if len(json.dumps(result, allow_nan=False).encode())+80 > limits['max_output_bytes']:
            result.update(status='section_profiles_withheld', analysis_complete=False,
                reason='section_profile_output_budget_exceeded', profiles=[], source_inventory=None,
                label_associations=None, withheld=[])
            result['summary']['nominal_section_profile_hypotheses'] = 0
        check()
        result['id'] = digest(result)
        return result
    if views.get('status') != 'automatic_view_candidates_only':
        return finish('complete_view_candidate_inventory_required')
    candidates = views.get('views')
    if (not isinstance(candidates, list) or len(candidates) > 128
            or len({v['id'] for v in candidates}) != len(candidates)):
        raise ValueError('Distinct bounded source views required')
    sections = [v for v in candidates if v.get('printed_claim', {}).get('view_kind') == 'section']
    if not sections:
        return finish()
    if not measurements['analysis_complete']:
        return finish('complete_original_page_measurement_context_required')
    if measurements.get('pdf_user_unit') != 1 or page.cropbox != page.mediabox:
        return finish('original_uncropped_standard_point_page_required')
    frame = planning_view_geometry._native_frame(page)
    scopes = []
    for view in sections:
        check()
        if view['id'] != digest([drawing_view_candidates.VERSION, sha, number, view['caption_id'], view['geometry']]):
            raise ValueError('Exact source view identity required')
        region, caption, affine = planning_view_geometry._scope(view, frame)
        if affine is None:
            result['withheld'].append({'view_id': view['id'], 'reason': 'unique_visible_section_scale_required'})
        scopes.append((view, region, caption, affine))
    check()
    _, _, report = ordinary_surfaces.page_candidates(page, sha, number)
    inventory = report.get('source_outline_inventory')
    result['source_inventory'] = inventory
    if not inventory or not inventory.get('inventory_complete'):
        return finish('complete_coarse_source_outline_inventory_required')
    check()
    semantics = planning_outline_semantics.page_candidates(page, sha, number, inventory, cancelled=cancelled)
    result['label_associations'] = semantics
    if not semantics['inventory_complete']:
        return finish('complete_source_label_inventory_required')
    by_id = {r['candidate_id']: r for r in inventory['records']}
    labels = {r['id']: r for r in semantics['labels']}
    for association in semantics['outlines']:
        check()
        if (association['status'] != 'visible_label_enclosure_hint'
                or association['component_label_count'] != 1 or association['source_role_hint'] != 'building'):
            continue
        source = by_id[association['candidate_id']]
        geometry = shape(source['candidate']['geometry'])
        if geometry.interiors:
            result['withheld'].append({'candidate_id': source['candidate_id'], 'reason': 'section_enclosure_has_holes'})
            continue
        matches = []
        for view in candidates:
            check()
            result['checks'] += 1
            if result['checks'] > limits['max_checks']:
                return finish('section_profile_work_budget_exceeded')
            if shape(view['geometry']).intersects(geometry):
                matches.append(view['id'])
        scoped = [(v, p, c, a) for v, p, c, a in scopes if matches == [v['id']] and p.covers(geometry)]
        if len(scoped) != 1 or scoped[0][3] is None:
            result['withheld'].append({'candidate_id': source['candidate_id'],
                'intersecting_view_ids': sorted(matches), 'reason': 'unique_whole_scaled_section_scope_required'})
            continue
        view, _, caption, affine = scoped[0]
        bound = [labels[i] for i in association['label_ids']]
        label_states = {r['claim']['printed_state'] for r in bound}-{'unspecified'}
        state = caption['printed_claim']['printed_state']
        if state not in ('existing', 'proposed') or label_states-set((state, 'new') if state == 'proposed' else (state,)):
            result['withheld'].append({'candidate_id': source['candidate_id'], 'reason': 'section_label_state_unresolved_or_conflicting'})
            continue
        nominal = affine_transform(geometry, affine)
        x0, y0, x1, y1 = nominal.bounds
        if not all(math.isfinite(v) for v in (x0, y0, x1, y1)) or min(x1-x0, y1-y0) <= 0:
            raise ValueError('Finite nondegenerate section profile required')
        if len(result['profiles']) >= limits['max_profiles']:
            return finish('section_profile_count_budget_exceeded')
        result['profiles'].append({'id': digest([VERSION, sha, number, source['candidate_id'], view['id']]),
            'document_sha256': sha, 'page': number, 'status': 'unassigned_nominal_section_profile_hypothesis',
            'source_outline': source, 'source_association': association, 'labels': bound,
            'source_view_sha256': digest(view), 'view_id': view['id'], 'caption_evidence': caption,
            'printed_state': state, 'geometry_pdf_native': mapping(geometry),
            'geometry_nominal_local': mapping(nominal), 'native_to_nominal_local_affine': affine,
            'horizontal_span_nominal_m': x1-x0, 'vertical_span_nominal_m': y1-y0,
            'measurement_basis': 'coarse_source_enclosure_and_unverified_section_paper_scale',
            'physical_height_m': None, 'physical_height_verified': False,
            'plan_component_correspondence_status': 'withheld_no_supported_plan_component_link',
            'view_scope_verified': False, 'scale_application_verified': False,
            'paint_visibility_verified': False, 'world_placement_eligible': False})
    return finish()


def write_review(root, pages, *, cancelled=lambda: False):
    """Bounded source-pinned index; complete page evidence remains beside previews."""
    if not isinstance(pages, list) or len(pages) > 512:
        raise ValueError('Bounded section profile page list required')
    unique = {}
    for page in pages:
        if cancelled():
            raise CancelledError('Section profile review cancelled')
        if page.get('version') != VERSION or page.get('id') != digest({k: v for k, v in page.items() if k != 'id'}):
            raise ValueError('Exact current section profile page required')
        key = page['document_sha256']+':'+str(page['page'])
        if key in unique and unique[key] != page:
            raise ValueError('Conflicting section profile page')
        unique[key] = page
    retained = []
    profile_bytes = 0
    budget_exceeded = False
    for page in unique.values():
        for row in page['profiles']:
            if cancelled():
                raise CancelledError('Section profile review cancelled')
            profile_bytes += len(json.dumps(row, allow_nan=False).encode())
            if len(retained) >= 128 or profile_bytes > 7800000:
                budget_exceeded = True
                break
            retained.append(row)
        if budget_exceeded:
            break
    result = {'version': VERSION, 'status': 'unassigned_nominal_section_profiles_only',
        'source_pages': {key: {'sha256': digest(p), 'analysis_complete': p['analysis_complete'],
            'reason': p.get('reason')} for key, p in unique.items()}, 'profiles': retained,
        'physical_height_m': None, 'physical_height_verified': False, 'local_3d_components': 0,
        'world_geometry_additions': 0, 'world_placement_eligible': False}
    if budget_exceeded or len(json.dumps(result, indent=2, allow_nan=False).encode()) > 8000000:
        result.update(status='section_profile_review_budget_withheld', profiles=[])
    result['summary'] = {'nominal_section_profile_hypotheses': len(result['profiles']),
        'physical_section_heights_verified': 0}
    root = Path(root)
    if cancelled():
        raise CancelledError('Section profile review cancelled')
    (root/'section-profiles.json').write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
    body = ['<!doctype html><html><meta charset="utf-8"><title>Section profile evidence</title>',
        '<h1>Unassigned section profile measurements</h1><p>These are nominal source-polygon spans. '
        'View scope, paper scale, wall role and paint visibility remain unverified. No physical height, '
        'floor-plan component or ground datum is assigned. No 3D building is generated.</p>',
        '<p><a href="section-profiles.json">Exact source evidence and holds</a></p>']
    for row in result['profiles']:
        if cancelled():
            raise CancelledError('Section profile review cancelled')
        body.append('<p>'+escape(row['caption_evidence']['text'])+': '+
            f"{row['horizontal_span_nominal_m']:.4f} m horizontal × {row['vertical_span_nominal_m']:.4f} m vertical. "+
            'Unassigned profile '+escape(row['id'])+'.</p>')
    body.append('</html>')
    (root/'section-profiles.html').write_text(''.join(body), encoding='utf-8')
    return result
