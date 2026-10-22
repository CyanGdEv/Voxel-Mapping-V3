"""Fresh replay plus independent original-PDF junction/position arithmetic."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import tempfile

import numpy as np
import pymupdf

from voxel_mapper.drawing_page_tools import native_inverse
from voxel_mapper.generation_cycles import atomic_json, file_hash
from voxel_mapper.reconstruction_evidence_queue import digest
from voxel_mapper.roof_source_topology import build


def distance(point, endpoints):
    a, b = np.asarray(endpoints); delta = b - a
    t = float(np.dot(np.asarray(point) - a, delta) / np.dot(delta, delta))
    return float(np.linalg.norm(np.asarray(point) - a - min(1., max(0., t)) * delta)), t


def audit(topology, source_gradient, source_partial, gable, profile, preview, components, views, corpus, output):
    topology, source_gradient, source_partial, gable, profile, preview, components, views, corpus, output = map(Path,
        (topology, source_gradient, source_partial, gable, profile, preview, components, views, corpus, output))
    path = topology / 'roof-source-topology.json'; evidence = json.loads(path.read_text()); checked = Counter()
    with tempfile.TemporaryDirectory() as temp:
        fresh = build(source_gradient, source_partial, gable, profile, preview, components, views, corpus, temp,
            max_checks=evidence['contract']['max_checks']); fresh.pop('directory')
        assert digest(fresh) == digest(evidence)
    assert evidence['status'] == 'roof_source_topology_review_only'
    candidates = {}; lines_by_view = {}
    for top in evidence['topologies']:
        original = corpus / 'files' / (top['document_sha256'] + '.pdf')
        assert file_hash(original) == top['document_sha256']; index = defaultdict(list)
        with pymupdf.open(original) as doc:
            page = doc[top['page'] - 1]; matrix = native_inverse(page)
            for drawing in page.get_drawings():
                for item in drawing['items']:
                    if item[0] == 'l': edges = [item[1:]]
                    elif item[0] == 're':
                        box = item[1]; p = [box.tl, box.tr, box.br, box.bl, box.tl]; edges = list(zip(p[:-1], p[1:]))
                    elif item[0] == 'qu':
                        q = item[1]; p = [q.ul, q.ur, q.lr, q.ll, q.ul]; edges = list(zip(p[:-1], p[1:]))
                    else: continue
                    for a, b in edges:
                        points = np.array([list(a * matrix), list(b * matrix)])
                        for p in (points, points[::-1]): index[tuple(np.round(p.ravel(), 4))].append(p)
        lines = {l['source_component_id']: l for l in top['lines']}; lines_by_view[top['view_id']] = lines
        unit = top['nominal_metres_per_pdf_point']
        for line in lines.values():
            p = np.array(line['source_endpoints_pdf_native'])
            assert any(np.allclose(p, q, rtol=0, atol=1e-6) for q in index[tuple(np.round(p.ravel(), 4))])
            assert abs(np.linalg.norm(p[1] - p[0]) * unit - line['nominal_length_m']) < 1e-10
            checked['original_pdf_strokes'] += 1
        for candidate in top['candidates']:
            ridge = np.array(lines[candidate['ridge_source_id']]['source_endpoints_pdf_native'])
            axis = (ridge[1] - ridge[0]) / np.linalg.norm(ridge[1] - ridge[0]); normal = [-axis[1], axis[0]]
            offsets = [float((np.array(lines[i]['source_endpoints_pdf_native'])[0] - ridge[0]) @ normal) * unit for i in candidate['rail_source_ids']]
            assert offsets[0] < 0 < offsets[1] and abs(abs(offsets[0]) - abs(offsets[1])) <= .25
            assert np.allclose(sorted(abs(x) for x in offsets), candidate['nominal_runs_m'], atol=1e-10, rtol=0)
            for junction in candidate['source_junctions']:
                endpoint = ridge[junction['ridge_endpoint_index']]
                for contact in junction['rail_contacts']:
                    rail = lines[contact['rail_source_id']]['source_endpoints_pdf_native']
                    for alternative in contact['alternatives']:
                        cap = lines[alternative['cap_source_id']]['source_endpoints_pdf_native']
                        corner = cap[alternative['cap_endpoint_index']]
                        assert corner == alternative['cap_endpoint_pdf_native']
                        a, _ = distance(endpoint, cap); b, t = distance(corner, rail)
                        assert max(a, b) <= .25 + 1e-10
                        assert abs(a - alternative['ridge_to_cap_gap_pdf_points']) < 1e-10
                        assert abs(b - alternative['cap_to_rail_gap_pdf_points']) < 1e-10
                        assert abs(min(1., max(0., t)) - alternative['rail_station_fraction']) < 1e-10
                        checked['independent_junction_contacts'] += 1
            stations = sorted((ridge @ axis).tolist())
            for tail in candidate['source_rail_tails']:
                interval = sorted((np.array(lines[tail['rail_source_id']]['source_endpoints_pdf_native']) @ axis).tolist())
                expected = [max(0., stations[0] - interval[0]) * unit, max(0., interval[1] - stations[1]) * unit]
                assert np.allclose(expected, tail['nominal_source_tails_m'], atol=1e-10, rtol=0)
                assert not tail['source_trimmed']; checked['untrimmed_source_rails'] += 1
            assert not candidate['source_points_moved'] and not candidate['physical_roof_roles_verified']
            candidates[candidate['id']] = (candidate, top)
    source = json.loads((source_gradient / 'source-gradient-gables.json').read_text())
    pairs = {p['id']: p for r in source['views'] for s in r['variants'] for a in s['anchor_reviews'] for p in a['pairs']}
    parent = json.loads((gable / 'gable-roof-review.json').read_text())
    plans = {p['source_view_id']: p for p in parent['plan_reviews']}
    contexts = {c['id']: c for c in source['projection_contexts']}
    profiles = {p['view_id']: p for p in json.loads((profile / 'facade-profile.json').read_text())['profiles']}
    for check in evidence['position_checks']:
        candidate, top = candidates[check['candidate_id']]; context = contexts[check['context_id']]
        plan = plans[top['view_id']]; group = profiles[context['elevation_view_id']]
        pair = pairs[check['source_pair_id']]; assert pair['status'] == check['source_pair_status'] == 'conditional_partial_gable_source_support'
        point = lines_by_view[top['view_id']][candidate['ridge_source_id']]['source_endpoints_pdf_native'][check['ridge_endpoint_index']]
        station = float(np.dot(point, plan['source_axis_pdf_native'])) * top['nominal_metres_per_pdf_point']
        anchor = next(l for l in plan['lines'] if l['source_component_id'] == check['anchor_source_component_id'])
        matching = [v for v in group['variants'] if v['threshold'] in check['profile_thresholds_with_identical_original_span']]
        assert matching and len({tuple(v['source_upper_span_pixels']) for v in matching}) == 1
        span = matching[0]['source_upper_span_pixels']; end = span.index(check['anchor_source_pixel'])
        origin = anchor['along_interval_nominal_m'][end if check['source_axis_sign_hypothesis'] == 1 else 1 - end]
        offset = (pair['inferred_ridge_pixel'][0] - check['anchor_source_pixel']) * group['nominal_metres_per_source_pixel']
        predicted = origin + check['source_axis_sign_hypothesis'] * offset; error = station - predicted
        for a, b in [(origin, check['anchor_plan_station_nominal_m']), (station, check['ridge_endpoint_plan_station_nominal_m']),
                (predicted, check['predicted_plan_station_nominal_m']), (error, check['signed_position_error_nominal_m'])]:
            assert abs(a - b) < 1e-9
        assert (check['status'] == 'relative_source_position_agrees') == (abs(error) <= .25)
        assert not check['physical_correspondence_verified'] and not check['source_translation_refitted']
        checked['independent_relative_position_checks'] += 1
    assert evidence['new_roof_models'] == [] and not evidence['prior_source_holds_overridden']
    result = {'status': 'passed', 'fresh_replay_identical': True, 'source_review_sha256': file_hash(path),
        'source_gradient_sha256': file_hash(source_gradient / 'source-gradient-gables.json'), 'checked': dict(checked)}
    atomic_json(output, result); return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('topology', 'source-gradient', 'source-partial', 'gable', 'profile', 'preview', 'components', 'views', 'corpus', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    print(json.dumps(audit(**vars(parser.parse_args()))))
