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


def audit(job, output):
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
    checked = Counter(); rows = []
    for row in report['results']:
        result = json.loads((root/row['file']).read_text()); view = views[result['view_id']]
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
        rows.append({'caption': result['caption'], 'view_id': result['view_id'], 'printed_claim': result['printed_claim'],
            'counts': result['counts'], 'native_status': result['native_rectangle_review']['status'],
            'raster_status': scan['status'], 'scan_checks': scan.get('checks', 0),
            'source_png_sha256': result['source_png_sha256'], 'source_components_sha256': digest(components)})
    result = {'version': 'automatic-view-component-audit-v1', 'status': 'passed',
        'job_sha256': file_hash(job), 'source_contract': report['contract'], 'views': rows, 'counts': report['counts'],
        'checked': dict(checked), 'fresh_replay_artifact_hashes_identical': len(report['output_sha256']),
        'inventory_status': report['status'], 'withheld_passes': report['withheld_passes'],
        'all_requested_passes_completed': report['all_requested_passes_completed'],
        'output_sha256': report['output_sha256'], 'world_geometry_additions': 0, 'accepted_physical_components': 0,
        'training_labels_generated': 0, 'scope': 'Unseeded source evidence; no selected physical boundary, aperture or park placement.'}
    atomic_json(output, result)
    print(json.dumps({'status': result['status'], 'views': len(rows), 'counts': result['counts'], 'checked': result['checked']}))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); audit(args.job, args.output)
