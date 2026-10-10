"""Bounded plan/elevation edge hypotheses, excluding all placement feeds."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re

import pymupdf
import shapely
from .boundary_registration import file_hash
from .drawing_views import text, SCALE
from .glyph_visibility import screen_span
from .plan_network import recover, containing_faces, VERSION as NETWORK_VERSION
from .clipped_plan_fills import recover as recover_fills, discontinuities, VERSION as FILL_VERSION

VERSION = 'plan-elevation-edge-hypotheses-v3'


def plan_scale(page):
    traces = page.get_texttrace()
    if len(traces) > 10000:
        raise ValueError('Plan text budget exceeded')
    claims = []
    for index, span in enumerate(traces):
        value = text(span)
        match = SCALE.fullmatch(value)
        title_match = re.fullmatch(r'1\s*:\s*(\d{1,5})\s*@A1', value)
        if not match and not title_match:
            continue
        denominator = int((match or title_match)[1])
        claims.append({'trace_index': index, 'text': value,
                       'denominator': denominator, 'bbox_page_points': list(span['bbox']),
                       'glyph_screen': screen_span(page, span)})
    values = {c['denominator'] for c in claims}
    supported = [c for c in claims if c['glyph_screen']['status'] == 'raster_consistent_candidate']
    # Conflicting claims cannot be discarded just because a font replay failed.
    unit = next(iter(values)) * .0254 / 72 if len(values) == 1 and supported and 0 not in values else None
    return {'claims': claims, 'nominal_metres_per_pdf_point_candidate': unit,
            'scale_verified': False, 'view_extent_verified': False}


def straight_edges(page, sha, number):
    paths = page.get_drawings()
    if len(paths) > 100000:
        raise ValueError('Plan path budget exceeded')
    edges = []
    for index, path in enumerate(paths):
        if path['type'] not in ('s', 'fs') or path.get('stroke_opacity') != 1 or path.get('layer'):
            continue
        if not re.fullmatch(r'\s*(?:\[\s*\]\s*0(?:\.0*)?)?\s*', str(path.get('dashes', 'unknown'))):
            continue
        for item_index, item in enumerate(path['items']):
            if item[0] == 'l':
                pairs = [(item[1], item[2])]
            elif item[0] == 're':
                r = item[1]
                pairs = [(r.tl, r.tr), (r.tr, r.br), (r.br, r.bl), (r.bl, r.tl)]
            else:
                continue
            for part, (a, b) in enumerate(pairs):
                if not all(math.isfinite(v) for p in (a, b) for v in p):
                    raise ValueError('Nonfinite plan edge')
                length = math.dist(a, b)
                if length == 0:
                    continue
                provenance = [sha, number, index, path['seqno'], item_index, part, list(a), list(b)]
                edges.append({'id': hashlib.sha256(json.dumps(provenance).encode()).hexdigest(),
                              'document_sha256': sha, 'page': number, 'path_index': index,
                              'paint_seqno': path['seqno'], 'item_index': item_index, 'item_part': part,
                              'points': [list(a), list(b)], 'length_pdf_points': length,
                              'coordinate_frame': 'unrotated_mupdf_points_y_down',
                              'stroke_color': path.get('color'), 'stroke_width': path.get('width'),
                              'clipping_and_visibility_verified': False,
                              'outer_component_edge_verified': False})
                if len(edges) > 20000:
                    raise ValueError('Plan edge budget exceeded')
    return edges


def match_edges(edges, nominal_unit, width, *, tolerance_m=.25):
    if not all(math.isfinite(v) and v > 0 for v in (nominal_unit, width, tolerance_m)) or tolerance_m > 1:
        raise ValueError('Finite positive nominal scale, width and bounded search tolerance required')
    if len(edges) > 20000:
        raise ValueError('Plan edge budget exceeded')
    result = []
    for edge in edges:
        if not math.isfinite(edge['length_pdf_points']) or edge['length_pdf_points'] <= 0:
            raise ValueError('Finite positive source edge length required')
        length = edge['length_pdf_points'] * nominal_unit
        residual = length - width
        if abs(residual) <= tolerance_m:
            result.append({**edge, 'nominal_length_m': length, 'plan_minus_elevation_width_m': residual})
            if len(result) > 500:
                raise ValueError('Edge hypothesis budget exceeded')
    # Never rank or select the nearest: equality of lengths does not identify a building.
    return sorted(result, key=lambda r: r['id'])


def run(documents_file, face_directory, *, component_label=None):
    if component_label is not None and (not isinstance(component_label, str) or not 1 <= len(component_label) <= 100):
        raise ValueError('Bounded literal component label required')
    catalogue = Path(documents_file)
    items = json.loads(catalogue.read_text())
    if not isinstance(items, list) or not 1 <= len(items) <= 1000:
        raise ValueError('Bounded pinned document catalogue required')
    by_sha = {}
    for item in items:
        path = catalogue.parent / item['file']
        if path.stat().st_size > 20000000 or file_hash(path) != item['sha256'] or item['sha256'] in by_sha:
            raise ValueError('Distinct bounded pinned PDFs required')
        by_sha[item['sha256']] = path
    root = Path(face_directory)
    report = json.loads((root / 'face-report.json').read_text())
    if report['contract']['documents_sha256'] != file_hash(catalogue):
        raise ValueError('Replay catalogue mismatch')
    for name, digest in report['output_sha256'].items():
        if file_hash(root / name) != digest:
            raise ValueError('Replay output checksum mismatch')
    def rows(name):
        with (root / name).open() as stream:
            for n, line in enumerate(stream, 1):
                if n > 2500000 or len(line) > 20000000:
                    raise ValueError('Replay record budget exceeded')
                yield json.loads(line)
    associations = {}; association_count = 0
    for record in rows('face-associations.jsonl'):
        view = record.get('drawing_view_candidate', {}).get('view_key_candidate')
        if view:
            association_count += 1
            if association_count > 10000:
                raise ValueError('View association budget exceeded')
            associations.setdefault((record['document_sha256'], record['page'], tuple(view)), []).append(record)
    pages = {}; results = []; network_pages = []
    for link in rows('view-links.jsonl'):
        if link['status'] != 'unique_unverified_plan_elevation_reference':
            continue
        sha, number = link['source_document_sha256'], link['source_page']
        key = (sha, number)
        if sha not in by_sha:
            raise ValueError('Missing pinned plan PDF')
        if key not in pages:
            with pymupdf.open(by_sha[sha]) as document:
                page = document[number - 1]
                scale = plan_scale(page); edges = straight_edges(page, sha, number)
                try:
                    fills = recover_fills(page, sha, number)
                except ValueError as error:
                    fills = {'version': FILL_VERSION, 'status': 'withheld_fill_recovery', 'reason': str(error),
                             'candidates': [], 'world_geometry_additions': 0}
                unit = scale['nominal_metres_per_pdf_point_candidate']
                if unit:
                    for fill in fills['candidates']:
                        fill['nominal_area_m2'] = fill['area_pdf_points_squared'] * unit * unit
                        fill['strip_discontinuity_candidates'] = discontinuities(fill, unit)
                try:
                    network = recover(edges)
                except ValueError as error:
                    network = {'version': NETWORK_VERSION, 'status': 'withheld_network_budget_or_geometry',
                               'reason': str(error), 'chains': [], 'straight_runs': [], 'faces': [], 'world_geometry_additions': 0}
                labels = []
                if component_label:
                    for index, span in enumerate(page.get_texttrace()):
                        if text(span) != component_label:
                            continue
                        bbox = pymupdf.Rect(span['bbox']); center = list((bbox.tl + bbox.br) * .5)
                        screen = screen_span(page, span)
                        labels.append({'text': text(span), 'trace_index': index, 'bbox_page_points': list(bbox),
                                       'center_page_point': center, 'glyph_screen': screen,
                                       'containing_unclassified_face_ids': containing_faces(network, center)
                                       if screen['status'] == 'raster_consistent_candidate' else [],
                                       'physical_component_identity_verified': False})
                network_pages.append({'document_sha256': sha, 'page': number, 'plan_scale': scale,
                                      'clipped_fill_recovery': fills,
                                      'network': network, 'component_label_candidates': labels,
                                      'world_geometry_additions': 0})
                chains = [{'id': c['id'], 'length_pdf_points': c['length_pdf_points'],
                           'geometry': c['geometry'], 'source_edge_ids': c['source_edge_ids'],
                           'junctions': c['junctions'],
                           'outer_component_edge_verified': False} for c in network['straight_runs']]
                pages[key] = (scale, edges, chains)
        scale, edges, chains = pages[key]
        target = link['target_candidates'][0]
        records = associations.get((target['document_sha256'], target['page'], tuple(target['view']['view_key_candidate'])), [])
        for record in records:
            region = record.get('raster_contrast_boundary_review', {})
            metric = region.get('nominal_measurements_candidate')
            if region.get('status') != 'unverified_contrast_boundary_candidate' or not metric:
                continue
            unit = scale['nominal_metres_per_pdf_point_candidate']
            candidates = match_edges(edges, unit, metric['width_m']) if unit else []
            chain_candidates = match_edges(chains, unit, metric['width_m']) if unit else []
            results.append({'plan_document_sha256': sha, 'plan_page': number,
                            'plan_reference': link['reference'], 'target_document_sha256': target['document_sha256'],
                            'target_page': target['page'], 'view_key_candidate': target['view']['view_key_candidate'],
                            'material_number': record['number'], 'component_class_candidate': record['component_class_candidate'],
                            'region_geometry_sha256': hashlib.sha256(json.dumps(region['geometry'], sort_keys=True).encode()).hexdigest(),
                            'nominal_elevation_measurements': metric, 'plan_scale': scale,
                            'search_tolerance_m': .25, 'edge_candidates': candidates,
                            'connected_straight_chain_candidates': chain_candidates,
                            'connected_run_status': 'withheld_plan_scale' if not unit else 'unverified_continuous_length_hypotheses' if chain_candidates else 'withheld_no_connected_length_match',
                            'status': 'withheld_plan_scale' if not unit else 'unverified_length_hypotheses' if candidates else 'withheld_no_full_segment_length_match',
                            'mesh_status': 'withheld_incomplete_component_correspondence',
                            'mesh': None, 'accepted_feature': False, 'world_geometry_additions': 0})
            if len(results) > 10000:
                raise ValueError('Correspondence budget exceeded')
    return {'version': VERSION, 'network_version': NETWORK_VERSION, 'fill_version': FILL_VERSION,
            'component_label_search': component_label, 'network_pages': network_pages,
            'input_catalogue_sha256': file_hash(catalogue),
            'face_replay_output_sha256': report['output_sha256'], 'pymupdf_version': pymupdf.VersionBind,
            'shapely_version': shapely.__version__,
            'results': results, 'plan_pages_examined': len(pages),
            'limitations': ['Length matches retain every eligible full segment, including unrelated drafting edges.',
                            'Search tolerance is a discovery window, not a physical accuracy bound.',
                            'Clipping, outer-edge identity, closed footprint, elevation baseline, roof topology, depth and registration remain unverified.',
                            'Degree-two chains stop at branches; straight coverage may continue through a unique opposite collinear junction, with junctions retained.',
                            'Exact connections only; gaps are not bridged and component boundary topology remains unverified.',
                            'Label containment identifies drafting faces, not exterior footprints; no manual traces or nearest-edge choices are used.'],
            'accepted_features': 0, 'world_geometry_additions': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--documents', required=True)
    parser.add_argument('--faces', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--component-label')
    args = parser.parse_args()
    result = run(args.documents, args.faces, component_label=args.component_label)
    output = Path(args.output)
    with output.open('x') as stream:
        stream.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'output': str(output), 'region_reference_pairs': len(result['results']), 'world_geometry_additions': 0}))


if __name__ == '__main__':
    main()
