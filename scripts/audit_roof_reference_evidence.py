"""Fresh source replay and independent original-marker/caption/raster checks."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import tempfile

import numpy as np
import pymupdf

from voxel_mapper import drawing_view_candidates
from voxel_mapper.drawing_page_tools import native_inverse
from voxel_mapper.generation_cycles import atomic_json, file_hash
from voxel_mapper.reconstruction_evidence_queue import digest
from voxel_mapper.roof_reference_evidence import build


def clipped_length(points, polygon):
    """Independent convex half-plane clipping of a finite diagnostic segment."""
    start, end = np.array(points); delta = end - start; vertices = np.array(polygon)[:-1]
    def cross(a, b): return float(a[0] * b[1] - a[1] * b[0])
    orientation = 1 if sum(cross(a, b) for a, b in zip(vertices, np.roll(vertices, -1, axis=0))) > 0 else -1
    low, high = 0., 1.
    for a, b in zip(vertices, np.roll(vertices, -1, axis=0)):
        edge = b - a; constant = orientation * cross(edge, start - a); slope = orientation * cross(edge, delta)
        if abs(slope) < 1e-12:
            if constant < -1e-10: return 0.
        elif slope > 0: low = max(low, -constant / slope)
        else: high = min(high, -constant / slope)
    return max(0., high - low) * float(np.linalg.norm(delta))


def audit(evidence, topology, components, views, corpus, source_catalogue, additional_pdfs, output):
    evidence, topology, components, views, corpus, source_catalogue, additional_pdfs, output = map(Path,
        (evidence, topology, components, views, corpus, source_catalogue, additional_pdfs, output))
    path = evidence / 'roof-reference-evidence.json'; result = json.loads(path.read_text()); checked = Counter()
    with tempfile.TemporaryDirectory() as temp:
        replay = build(topology, components, views, corpus, source_catalogue, additional_pdfs, temp,
            max_checks=result['contract']['max_checks']); replay.pop('directory')
        assert digest(replay) == digest(result)
    assert result['status'] == 'roof_reference_evidence_only'
    refs = {}
    for page_record in result['roof_page_references']:
        original = corpus / 'files' / (page_record['document_sha256'] + '.pdf')
        assert file_hash(original) == page_record['document_sha256']
        with pymupdf.open(original) as doc:
            page = doc[page_record['page'] - 1]; paths = page.get_drawings(); matrix = native_inverse(page)
            for ref in page_record['side_reference_review']['references']:
                circle = paths[ref['circle_path_index']]
                assert list(circle['rect']) == ref['circle_bbox_page_points']
                assert [[list(p) for p in item[1:]] for item in circle['items']] == ref['circle_source_beziers']
                for head in ref['head_alternatives']:
                    a, tip, b = head['head_points_page_points']; arms = head['head_source_arms']
                    for arm in arms:
                        expected = arm['source_endpoints_page_points']
                        for index in arm['source_path_indices']:
                            assert paths[index]['type'] == 's' and len(paths[index]['items']) == 1
                            item = paths[index]['items'][0]; assert item[0] == 'l'
                            endpoints = [list(p) for p in item[1:]]
                            assert endpoints == expected or endpoints[::-1] == expected
                            checked['original_arm_paint_witnesses'] += 1
                    assert a in arms[0]['source_endpoints_page_points'] and b in arms[1]['source_endpoints_page_points']
                    gap = min(math.dist(tip, p) for p in arms[1]['source_endpoints_page_points'])
                    assert abs(gap - head['head_tip_junction_gap_pdf_points']) < 1e-10
                    rect = circle['rect']; center = list((rect.tl + rect.br) * .5)
                    vector = [tip[i] - center[i] for i in (0, 1)]; length = math.hypot(*vector)
                    assert np.allclose(np.array(vector) / length, head['source_aim_unit_vector_page'], atol=1e-12, rtol=0)
                    checked['independent_source_heads'] += 1
                if 'target_view_key_candidate' in ref:
                    assert ref['status'] == 'unverified_native_side_reference_candidate' and len(ref['head_alternatives']) == 1
                    review = page_record['side_reference_review']
                    assert all(review['glyph_screens'][str(i)]['status'] == 'raster_consistent_candidate' for i in ref['glyph_screen_trace_indices'])
                assert ref['pitch_degrees'] is None and not ref['marker_clipping_verified']
                refs[ref['id']] = (ref, list(matrix))
                checked['original_circle_markers'] += 1
    targets = []
    for page_record in result['additional_pages']:
        sha = page_record['document_sha256']; original = additional_pdfs / (sha + '.pdf')
        assert file_hash(original) == sha
        with pymupdf.open(original) as doc:
            page = doc[page_record['page'] - 1]; traces = page.get_texttrace()
            for label in page_record['page_labels']['views']:
                raw = ''.join(chr(c[0]) for c in traces[label['title_trace_index']]['chars']).strip()
                assert raw == label['title'] and 'Elevation ' in raw
                if 'view_key_candidate' in label:
                    assert label['view_key_candidate'][2] == label['view_index']
                    assert label['glyph_screen_status'] == 'raster_consistent_candidate'
                    assert len(label['scale_candidates']) == len(label['artwork_review_window_ids']) == 1
                checked['original_caption_traces'] += 1
            by_id = {c['id']: c for c in page_record['caption_layout']['view_captions']}
            for receipt in page_record['view_candidates']['caption_row_grouping_evidence']:
                caption = by_id[receipt['lower_caption_ids'][0]]; axis = tuple(round(v) for v in caption['reading_direction_pdf_native'])
                gray, _, proof = drawing_view_candidates._raster(page, axis)
                assert proof in page_record['view_candidates']['layout_raster_evidence']
                x0, y0, x1, y1 = receipt['source_raster_window_pixels']; white = np.all(gray[y0:y1, x0:x1] >= 250, axis=1)
                runs = []; begin = None
                for i, value in enumerate([*white.tolist(), False]):
                    if value and begin is None: begin = i
                    elif not value and begin is not None: runs.append([begin, i]); begin = None
                assert runs == receipt['white_row_runs_relative_pixels']
                separate = any((b - a) * receipt['pdf_points_per_source_row'] >= 8 for a, b in runs)
                assert separate == (receipt['status'] == 'separate_caption_rows_with_white_corridor')
                checked['independent_composited_row_windows'] += 1
        targets.extend(page_record['targets'])
    report = json.loads((components / 'component-report.json').read_text())
    for entry in report['results']:
        inv = json.loads((components / entry['file']).read_text()); key = inv.get('drawing_reference_review', {}).get('view_key_candidate')
        if key: targets.append({'view_key_candidate': key, 'view_id': inv['view_id']})
    for link in result['target_links']:
        ref = refs[link['source_reference_id']][0]; key = ref.get('target_view_key_candidate')
        expected = [t['view_id'] for t in targets if key and t['view_key_candidate'] == key]
        assert expected == [t['view_id'] for t in link['target_candidates']]
        assert not link['geometry_export_authorized'] and not link['physical_building_identity_verified']
        assert (link['status'] == 'unique_source_view_reference_candidate') == (len(expected) == 1)
        checked['exact_source_view_key_joins'] += 1
    for check in result['aim_checks']:
        ref, matrix = refs[check['source_reference_id']]; head = ref['head_alternatives'][check['head_alternative_index']]
        rect = pymupdf.Rect(ref['circle_bbox_page_points']); radius = (rect.width + rect.height) / 4
        tip = head['head_points_page_points'][1]; end = [tip[i] + 2 * radius * head['source_aim_unit_vector_page'][i] for i in (0, 1)]
        expected = [list(pymupdf.Point(p) * pymupdf.Matrix(matrix)) for p in (list((rect.tl + rect.br) * .5), end)]
        assert np.allclose(expected, check['diagnostic_aim_segment_pdf_native'], atol=1e-10, rtol=0)
        length = clipped_length(expected, check['assumed_whole_rail_envelope_pdf_native']['coordinates'][0])
        assert abs(length - check['positive_intersection_length_pdf_points']) < 1e-8
        assert not check['source_reference_visibility_hold_overridden'] and not check['source_stroke_extended']
        checked['independent_symbol_aim_diagnostics'] += 1
    for name, pin in result['output_artifact_sha256'].items():
        assert file_hash(evidence / name) == pin; checked['original_render_artifacts'] += 1
    assert result['new_roof_models'] == [] and not result['previous_source_holds_overridden']
    receipt = {'status': 'passed', 'fresh_replay_identical': True, 'review_sha256': file_hash(path),
        'source_topology_sha256': result['contract']['source_topology_sha256'], 'checked': dict(checked)}
    atomic_json(output, receipt); return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('evidence', 'topology', 'components', 'views', 'corpus', 'source-catalogue', 'additional-pdfs', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    print(json.dumps(audit(**vars(parser.parse_args()))))
