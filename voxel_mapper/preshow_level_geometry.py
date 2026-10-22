"""Own-source level/ridge/fascia evidence and bounded conditional roof patches."""
import json
import math
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image
import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import shape

from . import automatic_gable_roof as roof
from . import drawing_components, elevation_levels, split_level_labels, preshow_roof_patches as patches
from . import roof_reference_evidence as reference
from .automatic_facade_preview import _verified_inputs
from .automatic_opening_links import bounded_work
from .drawing_page_tools import native_inverse
from .generation_cycles import atomic_json, file_hash
from .reconstruction_evidence_queue import digest

VERSION = 'preshow-source-level-geometry-v1'


def contexts(parent, additional_pdfs, corpus):
    views = {v['id']: v for p in parent['additional_pages'] for v in p['view_candidates']['views']}
    refs = {r['id']: (p, r) for p in parent['roof_page_references'] for r in p['side_reference_review']['references']}
    candidates = {c['id']: (t, c) for t in parent['source_topologies'] for c in t['candidates']}
    result = []
    for link in parent['target_links']:
        if link['status'] != 'unique_source_view_reference_candidate': continue
        target = link['target_candidates'][0]
        if target['view_id'] not in views: continue
        page_record, ref = refs[link['source_reference_id']]
        with pymupdf.open(corpus / 'files' / (page_record['document_sha256'] + '.pdf')) as doc:
            matrix = native_inverse(doc[page_record['page'] - 1])
        for aim in parent['aim_checks']:
            if aim['source_reference_id'] != ref['id'] or aim['positive_intersection_length_pdf_points'] <= 0: continue
            top, candidate = candidates[aim['candidate_id']]
            line = next(l for l in top['lines'] if l['source_component_id'] == candidate['ridge_source_id'])
            head = ref['head_alternatives'][aim['head_alternative_index']]
            center = (pymupdf.Rect(ref['circle_bbox_page_points']).tl + pymupdf.Rect(ref['circle_bbox_page_points']).br) * .5
            tip = pymupdf.Point(head['head_points_page_points'][1]); vector = np.array(list(tip*matrix-center*matrix))
            vector /= np.linalg.norm(vector); alignment = abs(float(vector @ line['unit_vector']))
            row = {'candidate_id': candidate['id'], 'roof_view_id': top['view_id'],
                'source_aim_check_id': aim['id'], 'source_target_link_id': link['id'],
                'additional_view_id': target['view_id'], 'target_view_key_candidate': target['view_key_candidate'],
                'source_aim_to_ridge_alignment': alignment,
                'status': 'conditional_face_on_gable_source_context' if alignment >= math.cos(math.radians(5))
                    else 'side_or_oblique_gable_source_context_held',
                'orthographic_gable_projection_assumed': True, 'physical_correspondence_verified': False}
            row['id'] = digest([VERSION, row]); result.append(row)
    return result


def old_witnesses(topology, gradient, level_context):
    level_records = {r['id']: r for p in level_context.get('pages', []) for r in p['level_review']['records']}
    references = {v['view_id']: v['relative_reference'] for v in level_context.get('views', [])}
    pairs = {p['id']: (r, p) for r in gradient['views'] for s in r['variants'] for a in s['anchor_reviews'] for p in a['pairs']}
    grouped = {}
    for check in topology['position_checks']:
        if check['status'] == 'relative_source_position_agrees':
            grouped.setdefault((check['candidate_id'], check['source_pair_id']), []).append(check['id'])
    result = []
    for (candidate, pair_id), positions in sorted(grouped.items()):
        view, pair = pairs[pair_id]; relative = references.get(view['view_id'], {})
        if pair['status'] != 'conditional_partial_gable_source_support' or relative.get('status') != 'unverified_source_relative_shop_level': continue
        marker = level_records[relative['reference_id']]
        result.append({'candidate_id': candidate, 'source_pair_id': pair_id, 'source_view_id': view['view_id'],
            'source_pair_sha256': digest(pair), 'source_marker_id': marker['id'], 'source_marker_sha256': digest(marker),
            'source_label': marker['label']['level_label_candidate'], 'printed_level_value_m_candidate': marker['label']['value_m_candidate'],
            'nominal_ridge_height_above_source_level_m': pair['nominal_ridge_height_m'],
            'source_position_agreement_ids': positions})
    return result


def height_checks(context, pair, binding, level_pixel, mpp, witnesses, charge):
    rows = []; height = (level_pixel-pair['inferred_ridge_pixel'][1])*mpp
    for witness in witnesses:
        if witness['candidate_id'] != context['candidate_id']: continue
        charge(); error = (height+binding['label']['value_m_candidate']
            - witness['nominal_ridge_height_above_source_level_m']-witness['printed_level_value_m_candidate'])
        row = {'context_id': context['id'], 'source_pair_id': pair['id'], 'source_level_binding_id': binding['id'],
            'old_source_pair_id': witness['source_pair_id'], 'old_source_witness_sha256': digest(witness),
            'nominal_ridge_height_above_selected_level_m': height,
            'signed_source_ridge_height_difference_nominal_m': error,
            'status': 'conditional_inter_sheet_ridge_height_agrees' if abs(error) <= .25 else 'inter_sheet_ridge_height_held',
            'shared_printed_level_datum_assumed': True, 'physical_vertical_datum_verified': False,
            'independent_survey_check': False, 'old_source_hold_overridden': False}
        row['id'] = digest([VERSION, row]); rows.append(row)
    return rows


def threshold_checks(models, charge):
    result = []
    for a in models:
        if a['source_ink_threshold'] != 220: continue
        for b in models:
            if b['source_ink_threshold'] != 235 or any(a[k] != b[k] for k in
                    ('context_id', 'source_level_binding_id', 'source_cap_variant_id', 'image_left_to_native_rail_orientation')): continue
            charge(); ridge = float(np.linalg.norm(np.array(a['source_ridge_pixel'])-b['source_ridge_pixel']))
            ends = [float(np.linalg.norm(np.array(x)-y)) for x, y in zip(a['source_eave_top_pixels'], b['source_eave_top_pixels'])]
            row = {'source_model_ids': [a['id'], b['id']], 'ridge_difference_pixels': ridge,
                'source_endcap_differences_pixels': ends,
                'status': 'source_threshold_patch_measurements_agree' if max(ridge, *ends) <= 4 else 'source_threshold_patch_measurements_disagree',
                'shared_source_pixels_are_not_independent_controls': True}
            row['id'] = digest([VERSION, row]); result.append(row)
    return result


def build(references, topology, gradient, components, views, corpus, source_catalogue, additional_pdfs, output, *, max_checks=100000):
    bounded_work(max_checks)
    references, topology, gradient, components, views, corpus, source_catalogue, additional_pdfs, output = map(Path,
        (references, topology, gradient, components, views, corpus, source_catalogue, additional_pdfs, output))
    source_path = references/'roof-reference-evidence.json'; parent = json.loads(source_path.read_text())
    top_path = topology/'roof-source-topology.json'; old_top = json.loads(top_path.read_text())
    grad_path = gradient/'source-gradient-gables.json'; old_grad = json.loads(grad_path.read_text())
    pins = {source_path: file_hash(source_path), top_path: file_hash(top_path), grad_path: file_hash(grad_path)}
    pins.update({references/name: pin for name, pin in parent['output_artifact_sha256'].items()})
    pins[source_catalogue] = parent['contract']['catalogue_sha256']
    for path, pin in pins.items():
        if file_hash(path) != pin: raise ValueError('Original preshow geometry input changed')
    if pins[top_path] != parent['contract']['source_topology_sha256'] or pins[grad_path] != old_top['contract']['source_gradient_sha256']:
        raise ValueError('Matching original source chains required')
    with tempfile.TemporaryDirectory() as temp:
        fresh = reference.build(topology, components, views, corpus, source_catalogue, additional_pdfs, temp,
            max_checks=parent['contract']['max_checks']); fresh.pop('directory')
        if digest(fresh) != digest(parent): raise ValueError('Original preshow source replay changed')
    if parent['status'] != 'roof_reference_evidence_only': raise ValueError('Complete preceding reference evidence required')
    _, _, _, _, reviews = _verified_inputs(components, views, corpus)
    modules = [reference, split_level_labels, patches, roof, drawing_components, elevation_levels]
    contract = {'version': VERSION, 'implementation_sha256': file_hash(Path(__file__)),
        'source_reference_sha256': pins[source_path], 'source_topology_sha256': pins[top_path],
        'source_gradient_sha256': pins[grad_path], 'source_level_context_sha256': digest(reviews['elevation_level_context']),
        'kernel_sha256': {m.__name__: file_hash(Path(m.__file__)) for m in modules}, 'max_checks': max_checks}
    result = {'contract': contract, 'status': 'conditional_preshow_level_geometry_only', 'checks': 0,
        'level_pages': [], 'gable_views': [], 'contexts': [], 'old_source_witnesses': [], 'source_cap_variants': [],
        'inter_sheet_height_checks': [], 'endcap_checks': [], 'conditional_roof_patches': [], 'threshold_checks': [],
        'accepted_physical_components': 0, 'world_geometry_additions': 0, 'training_labels_generated': 0,
        'previous_source_holds_overridden': False, 'complete_building_generated': False}
    def charge():
        result['checks'] += 1
        if result['checks'] > max_checks: raise OverflowError('preshow_level_geometry_work_budget')
    try:
        result['contexts'] = contexts(parent, additional_pdfs, corpus)
        result['old_source_witnesses'] = old_witnesses(old_top, old_grad, reviews['elevation_level_context'])
        caps_by_context = {}
        for context in result['contexts']:
            if context['status'] != 'conditional_face_on_gable_source_context': continue
            top = next(t for t in parent['source_topologies'] if t['view_id'] == context['roof_view_id'])
            candidate = next(c for c in top['candidates'] if c['id'] == context['candidate_id'])
            variants = patches.source_cap_variants(top, candidate)
            caps_by_context[context['id']] = variants
            for variant in variants:
                result['source_cap_variants'].append({'context_id': context['id'], **variant})
        for original in parent['additional_pages']:
            sha = original['document_sha256']; path = additional_pdfs/(sha+'.pdf'); pins[path] = sha
            with pymupdf.open(path) as doc:
                page = doc[original['page']-1]; matrix = ~native_inverse(page)*page.rotation_matrix
                keys = {t['view_id']: t['view_key_candidate'] for t in original['targets']}; scopes = []
                for view in original['view_candidates']['views']:
                    if view['id'] not in keys: continue
                    polygon = affine_transform(shape(view['geometry']), [matrix.a,matrix.c,matrix.b,matrix.d,matrix.e,matrix.f])
                    scopes.append({'view_key_candidate': keys[view['id']], 'display_bounds': list(polygon.bounds),
                        'nominal_metres_per_pdf_point_candidate': view['nominal_metres_per_pdf_point']})
                levels = split_level_labels.review(page, sha, original['page'], scopes, max_checks=max_checks)
                if levels['status'] != 'split_source_level_review_only': raise OverflowError('complete_split_level_review_required')
                for _ in range(levels['checks']): charge()
                result['level_pages'].append(levels); components_for_mask = drawing_components.split_page(original['source_geometry'])
                for source in parent['rendered_views']:
                    if source['document_sha256'] != sha or source['page'] != original['page']: continue
                    key = keys.get(source['view_id']); relevant = [c for c in result['contexts'] if c['additional_view_id'] == source['view_id']
                        and c['status'] == 'conditional_face_on_gable_source_context']
                    # Retain all level reviews. Roof proposals require a supported face-on source context.
                    if not relevant: continue
                    receipt = json.loads((references/source['receipt']).read_text()); pixel_native = pymupdf.Matrix(receipt['pixel_edge_to_pdf_native_matrix'])
                    pixel_display = pixel_native*matrix
                    if min(pixel_display.a, pixel_display.d) <= 0 or max(abs(pixel_display.b), abs(pixel_display.c), abs(pixel_display.a-pixel_display.d)) > 1e-6:
                        raise ValueError('Aligned square source pixels required')
                    view = next(v for v in original['view_candidates']['views'] if v['id'] == source['view_id'])
                    mpp = pixel_display.a*view['nominal_metres_per_pdf_point']
                    with Image.open(references/source['png']) as im: gray = np.asarray(im.convert('L')).copy(); size = im.size
                    mask, exclusion = roof.exclusion_mask({'source_components': components_for_mask}, page, pixel_native, size, charge)
                    bindings = [b for b in levels['marker_bindings'] if b.get('view_key_candidate') == key and b['status'] == 'unverified_source_level_marker_binding']
                    relative = [c for c in levels['relative_checks'] if c['view_key_candidate'] == key]
                    level_scale_supported = bool(relative) and all(c['status'] == 'source_relative_level_scale_agrees' for c in relative)
                    row = {**source, 'nominal_metres_per_pixel': mpp, 'pixel_to_display_matrix': list(pixel_display),
                        'source_exclusions': exclusion, 'variants': [], 'level_scale_supported': level_scale_supported}
                    for threshold in (220,235):
                        scan = roof.slope_lines(gray, mask, threshold, charge)
                        pairs = roof.gable_pairs(scan['lines'], mpp, 0., charge)
                        for pair in pairs:
                            pair.pop('nominal_ridge_height_m'); pair.pop('id')
                            pair['id'] = digest([VERSION, source['view_id'], threshold, pair])
                        scan['gable_intersections'] = pairs; scan['source_fascia_columns'] = patches.vertical_caps(gray, mask, threshold, charge)
                        for context in relevant:
                            for variant in caps_by_context[context['id']]:
                                for pair in pairs:
                                    endchecks = patches.endcap_checks(pair, scan['source_fascia_columns'], variant, mpp, charge)
                                    result['endcap_checks'].extend({'context_id': context['id'], **c} for c in endchecks)
                                    for binding in bindings:
                                        level_pixel = (binding['datum_y_display_points']-pixel_display.f)/pixel_display.d
                                        heights = height_checks(context, pair, binding, level_pixel, mpp, result['old_source_witnesses'], charge)
                                        result['inter_sheet_height_checks'].extend(heights)
                                        if not level_scale_supported or not any(c['status'] == 'conditional_inter_sheet_ridge_height_agrees' for c in heights): continue
                                        for check in endchecks:
                                            if check['status'] != 'conditional_source_endcaps_agree': continue
                                            model = {'context_id': context['id'], 'view_id': source['view_id'], 'source_pair_id': pair['id'],
                                                'source_ink_threshold': threshold, 'source_level_binding_id': binding['id'],
                                                'source_level_label': binding['label']['level_label_candidate'],
                                                'source_level_value_m_candidate': binding['label']['value_m_candidate'],
                                                'source_cap_variant_id': variant['id'], 'source_endcap_check_id': check['id'],
                                                'image_left_to_native_rail_orientation': check['image_left_to_native_rail_orientation'],
                                                'source_ridge_pixel': pair['inferred_ridge_pixel'], 'source_eave_top_pixels': check['source_eave_top_pixels'],
                                                'source_agreeing_height_check_ids': [c['id'] for c in heights if c['status'] == 'conditional_inter_sheet_ridge_height_agrees'],
                                                'mesh': patches.patch_mesh(variant, pair, check, level_pixel, mpp), 'status': 'conditional_source_cap_patch_only'}
                                            model['id'] = digest([VERSION, model]); result['conditional_roof_patches'].append(model)
                                            if len(result['conditional_roof_patches']) > 256: raise OverflowError('preshow_roof_patch_budget')
                        row['variants'].append(scan)
                    result['gable_views'].append(row)
        result['threshold_checks'] = threshold_checks(result['conditional_roof_patches'], charge)
    except OverflowError as error:
        result.update(status='preshow_level_geometry_budget_withheld', reason=str(error), level_pages=[], gable_views=[], contexts=[],
            old_source_witnesses=[], source_cap_variants=[], inter_sheet_height_checks=[], endcap_checks=[], conditional_roof_patches=[], threshold_checks=[])
    for path, pin in pins.items():
        if file_hash(path) != pin: raise ValueError('Original preshow geometry source changed during build')
    final_reviews = _verified_inputs(components, views, corpus)[4]
    if digest(final_reviews['elevation_level_context']) != contract['source_level_context_sha256']:
        raise ValueError('Original level context changed during geometry build')
    result['counts'] = {'split_label_pairs': sum(len(p['split_pairs']) for p in result['level_pages']),
        'source_marker_bindings': sum(b['status'] == 'unverified_source_level_marker_binding' for p in result['level_pages'] for b in p['marker_bindings']),
        'relative_level_checks': sum(len(p['relative_checks']) for p in result['level_pages']),
        'source_gable_intersections': sum(len(s['gable_intersections']) for v in result['gable_views'] for s in v['variants']),
        'inter_sheet_height_checks': len(result['inter_sheet_height_checks']), 'source_endcap_checks': len(result['endcap_checks']),
        'conditional_roof_patches': len(result['conditional_roof_patches']), 'threshold_checks': len(result['threshold_checks'])}
    result = json.loads(json.dumps(result))
    if len(json.dumps(result).encode()) > 64000000: raise ValueError('Preshow level geometry output budget exceeded')
    root = output/digest(contract); path = root/'preshow-level-geometry.json'
    if path.exists():
        if digest(json.loads(path.read_text())) != digest(result): raise ValueError('Saved preshow level geometry changed')
    else: atomic_json(path, result)
    return {**result, 'directory': str(root)}
