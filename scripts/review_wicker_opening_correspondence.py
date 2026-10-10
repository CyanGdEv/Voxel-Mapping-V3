"""Recompute pinned layout/trace evidence and compare exact recovered plan gaps."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pymupdf
from audit_wicker_fill_gaps import run as gap_audit
from normalize_wicker_floor_scale import review as layout_review, FLOOR, ROOF
from trace_wicker_shop_floor import trace
from build_wicker_shop_walls import build, SOURCE as ELEVATION
from voxel_mapper.drawing_page_tools import native_inverse
from voxel_mapper.opening_correspondence import compare, VERSION


def numerically_equal(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(numerically_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(numerically_equal(x, y) for x, y in zip(a, b))
    if type(a) is float and type(b) is float:
        return math.isclose(a, b, rel_tol=0, abs_tol=1e-9)
    return a == b


def run(pdf_directory):
    root = Path(pdf_directory)
    pdf = lambda sha: root / (sha + '.pdf')
    floor = trace(pdf(FLOOR), 'evidence/wicker-shop-floor-annotations.json', 'evidence/wicker-shop-local-roof.json')
    saved_floor = json.loads(Path('evidence/wicker-shop-local-floor.json').read_text())
    if floor != saved_floor:
        raise ValueError('Pinned floor trace failed reproduction')
    layout = layout_review(pdf(FLOOR), pdf(ROOF), 'evidence/wicker-shop-local-floor.json', 'evidence/wicker-shop-local-roof.json')
    saved_layout = json.loads(Path('evidence/wicker-shop-floor-scale-review.json').read_text())
    if not numerically_equal(layout, saved_layout):
        raise ValueError('Pinned layout review failed reproduction')
    walls = build(pdf(ELEVATION), 'evidence/wicker-shop-vertical-annotations.json', 'evidence/wicker-shop-local-preview.json')
    pages = gap_audit(root, 'evidence/wicker-shop-clipped-fill-replay.json')['pages']
    floor_pages = [p for p in pages if p['document_sha256'] == FLOOR and p['page'] == 1]
    if len(floor_pages) != 1:
        raise ValueError('Unique pinned floor gap page required')
    gaps = floor_pages[0]['gaps']
    with pymupdf.open(pdf(FLOOR)) as doc:
        matrix = list(native_inverse(doc[0]))
    records = compare(gaps, floor['openings'], matrix, layout['floor_to_roof_linear_matrix'],
                      100 * .0254 / 72, floor['per_endpoint_sampling_bound_metres'])
    associations = {'opening-SW': 'SW-opening', 'opening-NE': 'NE-opening', 'door-NW': 'NW-door'}
    for record in records:
        for match in record['reviewed_trace_candidates']:
            key = associations[match['reviewed_opening_id']]
            match['reviewed_elevation_height_trace'] = walls['vertical_measurements'][key]
            match['height_assignment_status'] = 'conditional_on_unverified_plan_to_elevation_association'
    inputs = ['evidence/wicker-shop-floor-annotations.json', 'evidence/wicker-shop-local-floor.json',
              'evidence/wicker-shop-local-roof.json', 'evidence/wicker-shop-floor-scale-review.json',
              'evidence/wicker-shop-vertical-annotations.json', 'evidence/wicker-shop-local-preview.json',
              'evidence/wicker-shop-clipped-fill-replay.json']
    return {'version': VERSION, 'input_sha256': {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in inputs},
            'source_pdf_sha256': [FLOOR, ROOF, ELEVATION], 'discovery_tolerance_nominal_m': .25,
            'manual_endpoint_sampling_bound_nominal_m': floor['per_endpoint_sampling_bound_metres'],
            'layout_heldout_max_residual_pdf_points': layout['heldout_max_residual_pdf_points'],
            'normalized_floor_minus_elevation_dimensions_m': layout['normalized_minus_elevation_metres'],
            'unmatched_reviewed_opening_ids': sorted({o['id'] for o in floor['openings']} -
                {m['reviewed_opening_id'] for r in records for m in r['reviewed_trace_candidates']}),
            'layout_reproduction_numerical_tolerance': 1e-9,
            'records': records, 'accepted_openings': 0, 'accepted_registration_points': 0, 'world_geometry_additions': 0}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pdf-directory', required=True); p.add_argument('--output', required=True)
    a = p.parse_args(); Path(a.output).write_text(json.dumps(run(a.pdf_directory), sort_keys=True, indent=2) + '\n')
