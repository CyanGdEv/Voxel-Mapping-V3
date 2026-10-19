"""Verify unseeded view inventories against original parents and a fresh replay."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np
import pymupdf
from PIL import Image

from shapely.affinity import affine_transform
from shapely.geometry import Polygon, box, shape

from voxel_mapper.area_reconstruction import run as area_run
from voxel_mapper.drawing_components import split_page
from voxel_mapper.drawing_view_components import run as inventory, orient, affine
from voxel_mapper.generation_cycles import atomic_json, file_hash
from voxel_mapper.planning_bulk import Corpus
from voxel_mapper.reconstruction_evidence_queue import digest
from voxel_mapper.raster_opening_scan import scan as opening_scan
from voxel_mapper import automatic_opening_links, clipped_plan_fills, fill_endcaps
from voxel_mapper import automatic_building_scope, plan_elevation_edges
from voxel_mapper.ordinary_surfaces import label_runs


def verify_building_scope(page, view, result, checked):
    review = result['building_scope_review']
    if review['status']!='named_source_enclosure_candidates_only': return
    edges = plan_elevation_edges.straight_edges(page, result['document_sha256'], result['page'])
    assert digest(edges)==review['source_edges_sha256']
    fills = result['plan_gap_review']['page_fill_recovery']['candidates']
    assert digest(fills)==review['source_fills_sha256']
    edge_lookup = {e['id']: e for e in edges}; fill_lookup = {f['id']: f for f in fills}
    runs = {(tuple(r['trace_indices']),tuple(r['character_indices'])): r for r in label_runs(page.get_texttrace())}
    matrix = pymupdf.Matrix(result['plan_gap_review']['unrotated_mupdf_to_pdf_native_matrix'])
    expected = set(); gap_lookup = {g['id']: g for g in result['plan_gap_review']['gaps']}
    for label in review['labels']:
        run = runs[(tuple(label['trace_indices']),tuple(label['character_indices']))]
        assert ''.join(chr(c[0]) for c in run['chars']).strip()==label['text']
        rect = pymupdf.Rect(run['bbox'])
        native_label = Polygon([tuple(p*matrix) for p in (rect.tl,rect.tr,rect.br,rect.bl)])
        assert native_label.equals_exact(shape(label['geometry_pdf_native']),0)
        source = label['source_only_enclosure_review']
        if source is None:
            assert not label['candidates']; continue
        assert not source['gap_effects'] and all(not t['active_gap_ids'] for t in source['trials'])
        candidate_lookup = {c['id']: c for c in source['candidates']}
        for candidate in label['candidates']:
            original = candidate_lookup[candidate['id']]
            assert digest(original)==candidate['source_candidate_sha256']
            polygon = affine_transform(shape(original['geometry']),affine(matrix))
            assert polygon.equals_exact(shape(candidate['geometry_pdf_native']),0)
            assert polygon.contains(native_label) and shape(view['geometry']).covers(polygon)
            assert len(polygon.interiors)==candidate['source_hole_count']
            for proof in original['boundary_provenance']:
                if proof['kind']=='original_stroke':
                    assert digest(proof['source_endpoints'])==digest(edge_lookup[proof['source_edge_id']]['points'])
                else:
                    assert proof['kind']=='original_fill_boundary'
                    fill = fill_lookup[proof['source_fill_id']]; geometry = shape(fill['geometry'])
                    part = list(geometry.geoms)[proof['part_index']] if geometry.geom_type=='MultiPolygon' else geometry
                    ring = part.exterior if proof['ring_index']==0 else part.interiors[proof['ring_index']-1]
                    coords = list(ring.coords); i = proof['segment_index']
                    assert digest(proof['source_endpoints'])==digest([list(coords[i]),list(coords[i+1])])
                    assert proof['paint_seqno']==fill['paint_seqno']
                    assert proof['clip_source_path_ordinals']==[c['path_ordinal'] for c in fill['clip_references']]
                checked['named_enclosure_boundary_proofs'] += 1
            for gap in gap_lookup.values():
                corridor = shape(gap['geometry_pdf_native']); fraction = polygon.intersection(corridor).area/corridor.area
                if fraction>0: expected.add((label['id'],candidate['id'],gap['id']))
            checked['whole_label_named_enclosures'] += 1
            checked['named_enclosure_protected_holes'] += len(polygon.interiors)
        for identifier in label['whole_label_crossing_candidate_ids']:
            polygon = affine_transform(shape(candidate_lookup[identifier]['geometry']),affine(matrix))
            assert not polygon.contains(native_label)
            checked['whole_label_crossing_enclosures_withheld'] += 1
        checked['original_named_labels'] += 1
    observed = {(r['label_id'],r['enclosure_id'],r['source_gap_id']) for r in review['gap_links']}
    assert observed==expected and len(observed)==len(review['gap_links'])
    for link in review['gap_links']:
        label = next(r for r in review['labels'] if r['id']==link['label_id'])
        candidate = next(c for c in label['candidates'] if c['id']==link['enclosure_id'])
        corridor = shape(gap_lookup[link['source_gap_id']]['geometry_pdf_native'])
        assert link['corridor_overlap_area_fraction']==shape(candidate['geometry_pdf_native']).intersection(corridor).area/corridor.area
        assert not link['physical_building_assignment_verified']
    checked['independent_named_gap_links'] += len(observed)


def audit(job, output, baseline=None):
    job = Path(job).resolve(); configuration = json.loads(job.read_text())
    if len(configuration['areas']) != 1: raise ValueError('One bounded area required')
    area = configuration['areas'][0]['id']; work = (job.parent/configuration['work_directory']).resolve()/area
    entry = area_run(job, stage='extract')['areas'][area]
    report = entry['drawing_view_components']; root = Path(report['directory']); pack = Path(entry['drawing_views']['directory'])
    source = json.loads((pack/'view-candidates.json').read_text())
    views = {v['id']: v for p in source['pages'] for v in p['views']}
    parents = {}
    with (work/'drawing-geometry/geometry-candidates.jsonl').open() as stream:
        for line in stream:
            record = json.loads(line); parents[record['id']] = record
    corpus = Corpus(work/'corpus')
    try:
        with tempfile.TemporaryDirectory(prefix='view-component-fresh-replay-') as temporary:
            fresh = inventory(corpus, work/'drawing-geometry', pack, Path(temporary)/'components', settings=report['contract']['options'])
            assert fresh['output_sha256'] == report['output_sha256']
    finally: corpus.close()
    checked = Counter(); rows = []; baseline_comparison = None; old_views = {}; inspected_views = []
    if baseline is not None:
        baseline = Path(baseline); baseline_report = json.loads((baseline/'component-report.json').read_text())
        for name, pin in baseline_report['output_sha256'].items(): assert file_hash(baseline/name) == pin
        old_views = {r['view_id']: json.loads((baseline/r['file']).read_text()) for r in baseline_report['results']}
        baseline_comparison = {'report_sha256': file_hash(baseline/'component-report.json'), 'views_checked': 0,
            'native_geometry_and_raw_scan_preserved': True,
            'comparison_scope': 'Original default attempts; selected partitioned fallbacks are additional evidence.'}
    for row in report['results']:
        result = json.loads((root/row['file']).read_text()); view = views[result['view_id']]
        inspected_views.append(result)
        if baseline is not None:
            old = old_views[result['view_id']]
            assert digest(old['source_components']) == digest(result['source_components'])
            assert digest(old['wall_band_candidates']) == digest(result['wall_band_candidates'])
            assert digest(old['native_rectangle_review']) == digest(result['native_rectangle_review'])
            assert [digest(r['geometry_pdf_native']) for r in old['closed_source_regions']] == [digest(r['geometry_pdf_native']) for r in result['closed_source_regions']]
            old_raw = old.get('legacy_group_limit_attempts', {}).get('raster', old['raster_opening_scan'])
            before = {k: v for k, v in old_raw.items() if k != 'version'}
            legacy = result['legacy_group_limit_attempts'].get('raster', result['raster_opening_scan'])
            after = {k: v for k, v in legacy.items() if k != 'version'}
            assert before == after
            if 'residual_raster_scan' in old:
                legacy_residual = result['legacy_group_limit_attempts'].get('residual', result['residual_raster_scan'])
                old_residual = old.get('legacy_group_limit_attempts', {}).get('residual', old['residual_raster_scan'])
                assert {k: v for k, v in old_residual.items() if k!='version'} == {k: v for k, v in legacy_residual.items() if k!='version'}
            baseline_comparison['views_checked'] += 1
        originals = [parents[s['id']] for s in view['whole_sources'] if s['kind'] == 'native_vector']
        components = sorted(split_page(originals), key=lambda r: r['id']); by_id = {r['id']: r for r in components}
        assert result['source_view_sha256'] == digest(view)
        assert digest(components) == digest(result['source_components'])
        assert result['source_parent_records_sha256'] == digest(sorted(originals, key=lambda r: r['id']))
        assert not result['world_placement_eligible'] and not result['physical_boundary_verified']
        if result['building_scope_review']['status']=='named_source_enclosure_candidates_only':
            with pymupdf.open(work/'corpus/files'/(result['document_sha256']+'.pdf')) as document:
                verify_building_scope(document[result['page']-1],view,result,checked)
        gaps = result['plan_gap_review']
        if gaps['status'] == 'whole_view_source_endcap_gaps_only':
            with pymupdf.open(work/'corpus/files'/(result['document_sha256']+'.pdf')) as document:
                fills = clipped_plan_fills.recover(document[result['page']-1], result['document_sha256'], result['page'])
            assert digest(fills) == digest(gaps['page_fill_recovery'])
            originals = fill_endcaps.recover(fills['candidates'], view['nominal_metres_per_pdf_point'],
                                            max_checks=report['contract']['options']['max_checks'])
            assert digest(originals) == digest(gaps['page_endcap_recovery'])
            lookup = {g['id']: g for g in originals['gaps']}
            matrix = pymupdf.Matrix(gaps['unrotated_mupdf_to_pdf_native_matrix'])
            fill_lookup = {c['id']: c for c in fills['candidates']}
            retained_ids = {g['id'] for g in gaps['gaps']}
            assert retained_ids | set(gaps['withheld_scope_gap_ids']) == set(lookup)
            assert not retained_ids & set(gaps['withheld_scope_gap_ids'])
            scope = shape(view['geometry'])
            for gap in gaps['gaps']:
                source_gap = lookup[gap['id']]
                assert gap['source_gap_sha256'] == digest(source_gap)
                native = affine_transform(shape(source_gap['gap_corridor_geometry']), affine(matrix))
                assert native.equals_exact(shape(gap['geometry_pdf_native']), 0) and scope.covers(native)
                assert gap['nominal_gap_width_m'] == source_gap['nominal_gap_width_m']
                assert gap['source_fill_overlap_present'] == bool(source_gap['intersecting_fill_candidates'])
                for cap in source_gap['source_endcaps']:
                    fill = fill_lookup[cap['fill_candidate_id']]; geometry = shape(fill['geometry'])
                    part = list(geometry.geoms)[cap['polygon_part']] if geometry.geom_type=='MultiPolygon' else geometry
                    coords = list(part.exterior.coords); i = cap['boundary_edge_index']
                    assert digest([list(coords[i]), list(coords[i+1])]) == digest(cap['source_endpoints'])
                    assert scope.covers(affine_transform(geometry, affine(matrix)))
                    checked['original_plan_endcap_edges'] += 1
                checked['whole_view_plan_gaps'] += 1
            checked['original_page_fill_records'] += len(fills['candidates'])
        for region in result['closed_source_regions']:
            record = by_id[region['source_component_id']]; g = shape(record['geometry'])
            if g.geom_type == 'LineString': g = Polygon(g.coords)
            assert digest(record) == region['source_component_sha256']
            assert g.equals_exact(shape(region['geometry_pdf_native']), 0)
            assert len(g.interiors) == region['source_hole_count']
            if region['geometry_nominal_local'] is not None:
                assert affine_transform(g, view['native_to_nominal_local_affine']).equals_exact(shape(region['geometry_nominal_local']), 0)
            checked['closed_regions'] += 1; checked['protected_holes'] += len(g.interiors)
        for frame in result['native_rectangle_review']['frames']:
            for side in frame['source_side_support']:
                assert side['source_intervals']
                for proof in side['source_intervals']:
                    record = by_id[proof['component_id']]; g = shape(record['geometry'])
                    chain = list(g.coords) if g.geom_type == 'LineString' else list(g.exterior.coords) if proof['ring_index'] == 0 else list(g.interiors[proof['ring_index']-1].coords)
                    i = proof['segment_index']
                    assert digest([list(chain[i]), list(chain[i+1])]) == digest(proof['native_endpoints'])
                    assert 0 <= proof['interval_fractions'][0] < proof['interval_fractions'][1] <= 1
                    checked['native_cycle_side_intervals'] += 1
        scan = result['raster_opening_scan']; families = scan['index']['consensus_families'] if scan['index'] else []
        matrix = None
        if result['raster_coordinate_receipt'] is not None:
            receipt = json.loads((pack/view['render']['receipt']).read_text())
            with Image.open(pack/view['render']['png']) as image: gray = np.asarray(image.convert('L')).copy()
            gray, matrix, k = orient(gray, receipt['pixel_edge_to_pdf_native_matrix'], view['caption_evidence']['reading_direction_pdf_native'])
            assert hashlib.sha256(gray.tobytes()).hexdigest() == scan['source_gray_sha256']
            assert list(matrix) == result['raster_coordinate_receipt']['pixel_edge_to_pdf_native_matrix']
            checked['original_crop_gray_hashes'] += 1
        assert len(result['raster_opening_hypotheses']) == len(families)
        for h in result['raster_opening_hypotheses']:
            assert not h['physical_opening_verified'] and h['opening_type'] is None
            family = families[h['consensus_family_index']]
            g = affine_transform(box(*family['bounds_pixels']), affine(matrix))
            assert g.equals_exact(shape(h['geometry_pdf_native']), 0)
            if h['geometry_nominal_local'] is not None:
                assert affine_transform(g, view['native_to_nominal_local_affine']).equals_exact(shape(h['geometry_nominal_local']), 0)
            assert (h['status']=='candidate_scope_crossing_withheld') == (not shape(view['geometry']).covers(g))
            checked['raster_families'] += 1
        context = result['repeated_stroke_context']; residual = result['residual_raster_scan']
        for inspected in [scan, residual]:
            for proof in inspected.get('group_partition_proofs', []):
                variant = next(v for v in inspected['index']['variants'] if v['threshold']==proof['threshold'])
                groups = variant['jamb_groups']; owners = {}; per_component = [0]*len(proof['components'])
                source_variant = next(v for v in context['variants'] if v['threshold']==proof['threshold'])
                excluded = {tuple(g) for g in inspected.get('excluded_group_bounds', {}).get(str(proof['threshold']), [])}
                expected = [g for g in source_variant['original_vertical_groups'] if tuple(g) not in excluded]
                assert [[g[k] for k in ['left', 'top', 'right', 'bottom']] for g in groups] == expected
                checked['partition_source_tables_verified'] += 1
                for k, component in enumerate(proof['components']):
                    assert len(component['group_indices']) <= inspected['recipe']['max_groups_per_component']
                    for i in component['group_indices']:
                        assert i not in owners; owners[i] = k
                assert set(owners) == set(range(len(groups)))
                for i, left in enumerate(groups):
                    for j, right in enumerate(groups):
                        if (inspected['recipe']['min_width_pixels'] <= right['left']-left['right'] <= inspected['recipe']['maximum_width_pixels']
                                and max(abs(left[k]-right[k]) for k in ['top', 'bottom']) <= 2):
                            assert owners[i] == owners[j]
                            per_component[owners[i]] += 1; checked['partition_eligible_pairs'] += 1
                assert per_component == [c['eligible_directed_pairs'] for c in proof['components']]
                assert sum(per_component) == proof['eligible_directed_pairs']
                assert proof['total_original_groups'] == len(groups)
                assert proof['max_component_groups'] == max((len(c['group_indices']) for c in proof['components']), default=0)
                for pair in variant['pairs']:
                    a, b = pair['jamb_group_indices']; assert owners[a] == owners[b]
                checked['partition_original_groups'] += len(groups)
        if context['status'] == 'repeated_stroke_layout_context_only':
            assert context['source_gray_sha256'] == scan['source_gray_sha256']
            for variant in context['variants']:
                groups = variant['original_vertical_groups']; union = set()
                for lattice in variant['lattices']:
                    ids = lattice['group_indices']; rows_for_lattice = [groups[i] for i in ids]
                    assert len(ids) >= 6 and len(set(ids)) == len(ids)
                    assert max(g[1] for g in rows_for_lattice)-min(g[1] for g in rows_for_lattice) <= 2
                    assert max(g[3] for g in rows_for_lattice)-min(g[3] for g in rows_for_lattice) <= 2
                    for a, b in zip(rows_for_lattice, rows_for_lattice[1:]):
                        pitch = b[0]-a[0]
                        assert 2 <= pitch <= 16 and abs(pitch-lattice['first_pitch_pixels']) <= 1 and b[0] > a[2]
                    assert all(1 <= g[2]-g[0] <= 3 for g in rows_for_lattice)
                    union.update(ids)
                assert sorted(union) == variant['residual_excluded_group_indices']
                assert context['excluded_groups'][str(variant['threshold'])] == [groups[i] for i in sorted(union)]
                dark = gray < variant['threshold']
                for left, top, right, bottom in groups:
                    assert dark[top:bottom, left:right].all() and not dark[top-1, left:right].any() and not dark[bottom, left:right].any()
                    checked['original_stroke_groups'] += 1
            recomputed = opening_scan(gray, representation='indexed', pair_scope='all',
                max_checks=report['contract']['options']['max_checks'], excluded_groups=context['excluded_groups'],
                partition_groups='group_partition_proofs' in residual)
            assert recomputed == residual
            if residual['index'] is not None:
                families = residual['index']['consensus_families']
                assert len(families) == len(result['residual_raster_hypotheses'])
                for h in result['residual_raster_hypotheses']:
                    family = families[h['consensus_family_index']]
                    g = affine_transform(box(*family['bounds_pixels']), affine(matrix))
                    assert g.equals_exact(shape(h['geometry_pdf_native']), 0)
                    assert not h['physical_opening_verified'] and h['opening_type'] is None
                    if h['geometry_nominal_local'] is not None:
                        assert affine_transform(g, view['native_to_nominal_local_affine']).equals_exact(shape(h['geometry_nominal_local']), 0)
                    checked['residual_family_transforms'] += 1
        text = result['native_cycle_text_context']
        frame_lookup = {f['id']: f for f in result['native_rectangle_review']['frames']}
        for cycle in text['cycles']:
            assert not cycle['physical_opening_verified'] and not cycle['automatic_geometry_selection']
            for i in cycle['visible_label_indices']:
                label = text['labels'][i]
                assert label['glyph_screen']['status'] == 'raster_consistent_candidate'
                g = shape(frame_lookup[cycle['cycle_id']]['geometry_pdf_native']); label_geometry = shape(label['geometry_pdf_native'])
                assert g.intersection(label_geometry).area > 0
                assert cycle['cycle_id'] in label['intersecting_cycle_ids']
                relation = next(r for r in label['cycle_box_relations'] if r['cycle_id']==cycle['cycle_id'])
                assert relation['label_box_overlap_fraction'] == g.intersection(label_geometry).area/label_geometry.area
                assert (relation['relationship']=='whole_label_box_contained') == g.covers(label_geometry)
                checked['original_glyph_cycle_links'] += 1
        rows.append({'caption': result['caption'], 'view_id': result['view_id'], 'printed_claim': result['printed_claim'],
            'counts': result['counts'], 'native_status': result['native_rectangle_review']['status'],
            'raster_status': scan['status'], 'scan_checks': scan.get('checks', 0),
            'residual_raster_status': residual['status'], 'residual_scan_checks': residual.get('checks', 0),
            'text_context_status': text['status'],
            'source_png_sha256': result['source_png_sha256'], 'source_components_sha256': digest(components)})
    opening_links = json.loads((root/report['opening_links']['file']).read_text())
    assert automatic_opening_links.compare(inspected_views, max_checks=report['contract']['options']['max_checks']) == opening_links
    if baseline is not None and 'opening_links' in baseline_report:
        before = json.loads((baseline/baseline_report['opening_links']['file']).read_text())
        keys = ['plan_view_id','source_gap_id','elevation_view_id','consensus_family_index',
                'plan_nominal_width_m','elevation_nominal_width_m','elevation_minus_plan_width_m',
                'source_fill_overlap_present','construction_state_unresolved']
        assert sorted(tuple(m[k] for k in keys) for m in before['matches'])==sorted(tuple(m[k] for k in keys) for m in opening_links['matches'])
        baseline_comparison['nominal_width_pairs_preserved'] = len(opening_links['matches'])
    by_view = {v['view_id']: v for v in inspected_views}; expected = set()
    for plan in inspected_views:
        for gap in plan['plan_gap_review']['gaps']:
            for elevation in inspected_views:
                scale = elevation['nominal_metres_per_pdf_point']
                scan = elevation['residual_raster_scan']
                if scan.get('index') is None or scale is None: continue
                states = [v['printed_claim'].get('printed_state', 'unspecified') for v in (plan, elevation)]
                if 'unspecified' not in states and states[0] != states[1]: continue
                matrix = elevation['raster_coordinate_receipt']['pixel_edge_to_pdf_native_matrix']
                for h in elevation['residual_raster_hypotheses']:
                    if h['status']=='candidate_scope_crossing_withheld': continue
                    family = scan['index']['consensus_families'][h['consensus_family_index']]
                    width = (family['bounds_pixels'][2]-family['bounds_pixels'][0])*(matrix[0]**2+matrix[1]**2)**.5*scale
                    if abs(width-gap['nominal_gap_width_m']) <= .25:
                        expected.add((plan['view_id'], gap['id'], elevation['view_id'], h['id']))
                    checked['independent_width_pair_comparisons'] += 1
    if opening_links['status']=='nominal_width_links_only':
        observed = {(m['plan_view_id'], m['source_gap_id'], m['elevation_view_id'], m['residual_family_id']) for m in opening_links['matches']}
        assert observed == expected and len(observed)==len(opening_links['matches'])
        for match in opening_links['matches']:
            assert match['plan_inventory_sha256']==digest(by_view[match['plan_view_id']])
            assert match['elevation_inventory_sha256']==digest(by_view[match['elevation_view_id']])
            assert not match['physical_correspondence_verified'] and not match['position_alignment_verified']
        checked['independent_nominal_width_links'] += len(observed)
    building_links = json.loads((root/report['building_facade_links']['file']).read_text())
    assert automatic_building_scope.link(inspected_views,opening_links,max_checks=report['contract']['options']['max_checks'])==building_links
    width_lookup = {w['id']: w for w in opening_links['matches']}
    records = {r['id']: r for r in building_links['frames']}
    projection_lookup = {p['id']: p for p in building_links['projected_gaps']}
    for record in records.values():
        plan = by_view[record['plan_view_id']]
        reference = next(r for r in plan['drawing_reference_review']['plan_references']['references'] if digest(r)==record['source_reference_sha256'])
        assert digest(reference) in plan['drawing_reference_review']['whole_view_reference_sha256']
        assert reference['target_view_key_candidate']==record['target_view_key_candidate']
        label = next(l for l in plan['building_scope_review']['labels'] if l['id']==record['label_id'])
        candidate = next(c for c in label['candidates'] if c['id']==record['enclosure_id'])
        polygon = shape(candidate['geometry_pdf_native'])
        for frame in record['frame_review']['frames']:
            coords = list(polygon.exterior.coords); i = frame['boundary_segment_index']
            assert digest(frame['source_native_endpoints'])==digest([list(coords[i]),list(coords[i+1])])
            checked['original_named_facade_segments'] += 1
        checked['numbered_marker_enclosure_reviews'] += 1
    expected = set()
    for projection in projection_lookup.values():
        record = records[projection['facade_record_id']]
        frame = next(f for f in record['frame_review']['frames'] if f['id']==projection['frame_id'])
        plan = by_view[projection['plan_view_id']]
        gap = next(g for g in plan['plan_gap_review']['gaps'] if g['id']==projection['source_gap_id'])
        axis = frame['diagnostic_axis']; factor = plan['nominal_metres_per_pdf_point']
        expected_interval = sorted(sum(p[i]*axis[i] for i in (0,1))*factor-frame['projection_min_m'] for p in gap['gap_endpoints_pdf_native'])
        assert expected_interval==projection['nominal_plan_position_interval_m']
        assert projection['maximum_gap_plane_offset_nominal_m']<=.25 and not projection['position_alignment_verified']
        for width in width_lookup.values():
            if (width['plan_view_id']==projection['plan_view_id'] and width['source_gap_id']==projection['source_gap_id']
                    and width['elevation_view_id'] in record['target_elevation_view_ids']):
                expected.add((projection['id'],width['id']))
        checked['nominal_plan_gap_projections'] += 1
    observed = {(r['projection_id'],r['source_width_link_id']) for r in building_links['width_links']}
    assert observed==expected and len(observed)==len(building_links['width_links'])
    for link in building_links['width_links']:
        assert digest(width_lookup[link['source_width_link_id']])==link['source_width_link_sha256']
        assert not link['physical_correspondence_verified'] and not link['position_alignment_verified']
    checked['independent_reference_scoped_width_links'] += len(observed)
    result = {'version': 'automatic-view-component-audit-v3', 'status': 'passed',
        'job_sha256': file_hash(job), 'source_contract': report['contract'], 'views': rows, 'counts': report['counts'],
        'checked': dict(checked), 'fresh_replay_artifact_hashes_identical': len(report['output_sha256']),
        'inventory_status': report['status'], 'withheld_passes': report['withheld_passes'],
        'opening_links': report['opening_links'],
        'building_facade_links': report['building_facade_links'],
        'baseline_comparison': baseline_comparison,
        'all_requested_passes_completed': report['all_requested_passes_completed'],
        'output_sha256': report['output_sha256'], 'world_geometry_additions': 0, 'accepted_physical_components': 0,
        'training_labels_generated': 0, 'scope': 'Unseeded source evidence; no selected physical boundary, aperture or park placement.'}
    atomic_json(output, result)
    print(json.dumps({'status': result['status'], 'views': len(rows), 'counts': result['counts'], 'checked': result['checked']}))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, help='Optional prior component pack for native/raw preservation checks')
    args = parser.parse_args(); audit(args.job, args.output, args.baseline)
