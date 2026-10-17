"""Verify unseeded view inventories against original parents and a fresh replay."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np
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
    checked = Counter(); rows = []; baseline_comparison = None; old_views = {}
    if baseline is not None:
        baseline = Path(baseline); baseline_report = json.loads((baseline/'component-report.json').read_text())
        for name, pin in baseline_report['output_sha256'].items(): assert file_hash(baseline/name) == pin
        old_views = {r['view_id']: json.loads((baseline/r['file']).read_text()) for r in baseline_report['results']}
        baseline_comparison = {'report_sha256': file_hash(baseline/'component-report.json'), 'views_checked': 0,
            'native_geometry_and_raw_scan_preserved': True,
            'comparison_scope': 'Original default attempts; selected partitioned fallbacks are additional evidence.'}
    for row in report['results']:
        result = json.loads((root/row['file']).read_text()); view = views[result['view_id']]
        if baseline is not None:
            old = old_views[result['view_id']]
            assert digest(old['source_components']) == digest(result['source_components'])
            assert digest(old['wall_band_candidates']) == digest(result['wall_band_candidates'])
            assert digest(old['native_rectangle_review']) == digest(result['native_rectangle_review'])
            assert [digest(r['geometry_pdf_native']) for r in old['closed_source_regions']] == [digest(r['geometry_pdf_native']) for r in result['closed_source_regions']]
            before = {k: v for k, v in old['raster_opening_scan'].items() if k != 'version'}
            legacy = result['legacy_group_limit_attempts'].get('raster', result['raster_opening_scan'])
            after = {k: v for k, v in legacy.items() if k != 'version'}
            assert before == after
            if 'residual_raster_scan' in old:
                legacy_residual = result['legacy_group_limit_attempts'].get('residual', result['residual_raster_scan'])
                assert {k: v for k, v in old['residual_raster_scan'].items() if k!='version'} == {k: v for k, v in legacy_residual.items() if k!='version'}
            baseline_comparison['views_checked'] += 1
        originals = [parents[s['id']] for s in view['whole_sources'] if s['kind'] == 'native_vector']
        components = sorted(split_page(originals), key=lambda r: r['id']); by_id = {r['id']: r for r in components}
        assert result['source_view_sha256'] == digest(view)
        assert digest(components) == digest(result['source_components'])
        assert result['source_parent_records_sha256'] == digest(sorted(originals, key=lambda r: r['id']))
        assert not result['world_placement_eligible'] and not result['physical_boundary_verified']
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
    result = {'version': 'automatic-view-component-audit-v1', 'status': 'passed',
        'job_sha256': file_hash(job), 'source_contract': report['contract'], 'views': rows, 'counts': report['counts'],
        'checked': dict(checked), 'fresh_replay_artifact_hashes_identical': len(report['output_sha256']),
        'inventory_status': report['status'], 'withheld_passes': report['withheld_passes'],
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
