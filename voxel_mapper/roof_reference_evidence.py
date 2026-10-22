"""Source-linked additional elevations; no physical identity or mesh promotion."""
import json
import math
from pathlib import Path
import re
import shutil
import tempfile

import numpy as np
import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import LineString, Polygon, mapping, shape
from shapely.ops import unary_union

from . import architectural_graph, architectural_view_layout, building_raster_views
from . import drawing_annotations, drawing_geometry, drawing_side_references, drawing_view_candidates, drawing_views
from . import numbered_elevation_captions, roof_source_topology, glyph_visibility
from .automatic_facade_preview import _verified_inputs
from .automatic_opening_links import bounded_work
from .drawing_page_tools import native_inverse
from .generation_cycles import atomic_json, file_hash
from .reconstruction_evidence_queue import digest

VERSION = 'roof-reference-evidence-v1'


def target_links(references, targets, charge):
    """Join exact project/sheet/view keys; missing and competing targets stay held."""
    result = []
    for reference in references:
        charge(); key = reference.get('target_view_key_candidate')
        matches = []
        if key:
            for target in targets:
                charge()
                if target['view_key_candidate'] == key: matches.append(target)
        row = {'source_reference_id': reference['id'], 'source_reference_sha256': digest(reference),
            'target_view_key_candidate': key, 'target_candidates': matches,
            'status': 'unique_source_view_reference_candidate' if len(matches) == 1 else
                'source_reference_visibility_or_identity_held' if not key else
                'missing_source_view_target' if not matches else 'competing_source_view_targets',
            'physical_building_identity_verified': False, 'geometry_export_authorized': False}
        row['id'] = digest([VERSION, row]); result.append(row)
    return result


def aim_checks(topology, references, page, charge):
    """Bounded symbol-direction diagnostics against whole-rail envelopes.

The line is an explicit diagnostic projection beyond the original V tip, never
an invented drawing stroke, footprint edge or physical building assignment.
"""
    matrix = native_inverse(page); lines = {l['source_component_id']: l for l in topology['lines']}; result = []
    for candidate in topology['candidates']:
        ridge = np.array(lines[candidate['ridge_source_id']]['source_endpoints_pdf_native'])
        axis = (ridge[1] - ridge[0]) / np.linalg.norm(ridge[1] - ridge[0])
        rails = [np.array(lines[i]['source_endpoints_pdf_native']) for i in candidate['rail_source_ids']]
        a, b = [p[np.argsort(p @ axis)] for p in rails]
        polygon = Polygon([a[0], a[1], b[1], b[0]])
        if not polygon.is_valid or polygon.area <= 0: raise ValueError('Valid original rail envelope required')
        for reference in references:
            for head_index, head in enumerate(reference['head_alternatives']):
                charge(); rect = pymupdf.Rect(reference['circle_bbox_page_points']); center = (rect.tl + rect.br) * .5
                radius = (rect.width + rect.height) / 4; tip = head['head_points_page_points'][1]
                end = np.array(tip) + 2 * radius * np.array(head['source_aim_unit_vector_page'])
                points = [list(pymupdf.Point(p) * matrix) for p in (list(center), end.tolist())]
                ray = LineString(points); intersection = ray.intersection(polygon)
                row = {'candidate_id': candidate['id'], 'source_reference_id': reference['id'],
                    'head_alternative_index': head_index, 'source_reference_status': reference['status'],
                    'assumed_whole_rail_envelope_pdf_native': mapping(polygon),
                    'diagnostic_aim_segment_pdf_native': points, 'source_head_extension_radii': 2,
                    'positive_intersection_length_pdf_points': intersection.length,
                    'status': 'source_symbol_aim_overlaps_assumed_envelope' if intersection.length > 0 else 'source_symbol_aim_misses_assumed_envelope',
                    'source_reference_visibility_hold_overridden': False,
                    'source_stroke_extended': False, 'physical_building_identity_verified': False}
                row['id'] = digest([VERSION, row]); result.append(row)
    return result


def discover(page, sha, charge):
    parents, extraction = drawing_geometry.extract_page(page, sha, page.number + 1,
        min_line_length_points=.25, max_candidates=10000)
    if extraction['status'] != 'unplaced_geometry_candidates':
        raise OverflowError('complete_additional_source_geometry_required')
    graph = architectural_graph.build([]); graph.update(document_sha256=sha, page=page.number + 1)
    layout = architectural_view_layout.review(page, sha, page.number + 1, graph)
    images = building_raster_views.placements(page, sha, page.number + 1)
    if images['status'] != 'source_image_placements_only':
        raise OverflowError('complete_additional_source_images_required')
    sources = [{'id': s['id'], 'document_sha256': sha, 'page': page.number + 1,
        'kind': 'native_vector', 'geometry': s['geometry'], 'parent_record_sha256': digest(s)} for s in parents]
    sources += [{**s, 'kind': 'raster_placement'} for s in images['placements']]
    views = drawing_view_candidates.candidates(page, sha, page.number + 1, layout, sources)
    if views['status'] != 'automatic_view_candidates_only':
        raise OverflowError('complete_additional_source_views_required')
    for _ in range(views['checks']): charge()
    matrix = ~native_inverse(page); groups = []
    for view in views['views']:
        charge()
        if not view['whole_sources']: continue
        union = unary_union([shape(s['geometry_pdf_native']) for s in view['whole_sources']])
        bounds = affine_transform(union, [matrix.a, matrix.c, matrix.b, matrix.d, matrix.e, matrix.f]).bounds
        groups.append({'id': view['id'], 'bbox_page_points': list(bounds)})
    labels = drawing_views.page_labels(page, groups)
    annotations, annotation_page = drawing_annotations.page_annotations(page, sha, page.number + 1)
    targets = []
    for label in labels['views']:
        charge()
        if not label.get('view_key_candidate'): continue
        ids = label['artwork_review_window_ids']
        if len(ids) != 1: continue
        targets.append({'view_key_candidate': label['view_key_candidate'], 'view_id': ids[0],
            'document_sha256': sha, 'page': page.number + 1, 'label_sha256': digest(label),
            'physical_building_identity_verified': False})
    return {'document_sha256': sha, 'page': page.number + 1, 'source_geometry': parents,
        'source_geometry_extraction': extraction, 'source_image_placements': images,
        'caption_layout': layout, 'view_candidates': views, 'page_labels': labels,
        'source_annotations': annotations, 'source_annotation_page': annotation_page, 'targets': targets}


def build(topology, components, views, corpus, source_catalogue, additional_pdfs, output, *, max_checks=100000):
    bounded_work(max_checks)
    topology, components, views, corpus, source_catalogue, additional_pdfs, output = map(Path,
        (topology, components, views, corpus, source_catalogue, additional_pdfs, output))
    topology_path = topology / 'roof-source-topology.json'; parent = json.loads(topology_path.read_text())
    if parent['status'] != 'roof_source_topology_review_only': raise ValueError('Complete source topology required')
    report, _, inventories, source_views, _ = _verified_inputs(components, views, corpus)
    pins = {topology_path: file_hash(topology_path), source_catalogue: file_hash(source_catalogue),
        components / 'component-report.json': file_hash(components / 'component-report.json'),
        views / 'view-report.json': file_hash(views / 'view-report.json')}
    if any(parent['contract']['source_input_sha256'][p.name] != pin for p, pin in pins.items()
            if p.name in ('component-report.json', 'view-report.json')):
        raise ValueError('Original topology source pack changed')
    entries = json.loads(source_catalogue.read_text())['entries']
    if not 1 <= len(entries) <= 4 or len({r['sha256'] for r in entries}) != len(entries):
        raise ValueError('One to four distinct additional source documents required')
    for entry in entries:
        sha = entry['sha256']
        if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha): raise ValueError('Original source digest required')
        path = additional_pdfs / (sha + '.pdf')
        if path.stat().st_size > 20000000 or file_hash(path) != sha: raise ValueError('Original additional PDF changed')
        pins[path] = sha
    modules = [architectural_view_layout, building_raster_views, drawing_annotations, drawing_geometry,
        drawing_side_references, drawing_view_candidates, drawing_views, numbered_elevation_captions,
        roof_source_topology, glyph_visibility]
    contract = {'version': VERSION, 'implementation_sha256': file_hash(Path(__file__)),
        'kernel_sha256': {m.__name__: file_hash(Path(m.__file__)) for m in modules},
        'source_topology_sha256': pins[topology_path], 'catalogue_sha256': pins[source_catalogue],
        'component_report_sha256': pins[components / 'component-report.json'],
        'view_report_sha256': pins[views / 'view-report.json'], 'additional_pdf_sha256': sorted(r['sha256'] for r in entries),
        'max_checks': max_checks, 'pymupdf_version': pymupdf.VersionBind}
    root = output / digest(contract)
    result = {'contract': contract, 'status': 'roof_reference_evidence_only', 'checks': 0,
        'source_topologies': [], 'roof_page_references': [], 'additional_pages': [],
        'target_links': [], 'aim_checks': [], 'rendered_views': [], 'output_artifact_sha256': {},
        'new_roof_models': [], 'accepted_physical_components': 0, 'world_geometry_additions': 0,
        'training_labels_generated': 0, 'previous_source_holds_overridden': False,
        'unresolved': ['Physical building/roof identity and complete geometry',
            'Independent eave/ridge heights, source tail depth and source state', 'Geographic/vertical registration']}
    def charge():
        result['checks'] += 1
        if result['checks'] > max_checks: raise OverflowError('roof_reference_work_budget')
    with tempfile.TemporaryDirectory() as temp:
        temporary = Path(temp)
        try:
            for top in parent['topologies']:
                inv = inventories[top['view_id']]; fresh = roof_source_topology.connected_candidates(inv, charge)
                if digest(fresh) != digest(top): raise ValueError('Original source topology replay changed')
                result['source_topologies'].append(fresh)
                with pymupdf.open(corpus / 'files' / (top['document_sha256'] + '.pdf')) as doc:
                    page = doc[top['page'] - 1]; references = drawing_side_references.page_references(page)
                    if references['status'] != 'side_reference_candidates_only': raise OverflowError('complete_side_references_required')
                    for _ in range(references['checks']): charge()
                    result['roof_page_references'].append({'view_id': top['view_id'], 'document_sha256': top['document_sha256'],
                        'page': top['page'], 'side_reference_review': references})
                    result['aim_checks'].extend(aim_checks(fresh, references['references'], page, charge))
            for entry in entries:
                sha = entry['sha256']; path = additional_pdfs / (sha + '.pdf')
                with pymupdf.open(path) as doc:
                    if len(doc) > 4: raise OverflowError('additional_source_page_budget')
                    for page in doc:
                        charge()
                        if len(result['additional_pages']) >= 4: raise OverflowError('additional_source_total_page_budget')
                        record = discover(page, sha, charge); result['additional_pages'].append(record)
                        for view in record['view_candidates']['views']:
                            charge(); name = 'views/' + view['id']
                            receipt = building_raster_views.render({'version': building_raster_views.VERSION,
                                'path': str(path.resolve()), 'sha256': sha, 'page': page.number + 1,
                                'bounds_pdf_native': list(shape(view['geometry']).bounds), 'width_pixels': 1200},
                                lambda p: p, temporary / name)
                            for suffix in ('view.png', 'receipt.json'):
                                result['output_artifact_sha256'][name + '/' + suffix] = file_hash(temporary / name / suffix)
                            result['rendered_views'].append({'view_id': view['id'], 'document_sha256': sha,
                                'page': page.number + 1, 'caption': view['caption_text'], 'png': name + '/view.png',
                                'receipt': name + '/receipt.json', 'png_sha256': receipt['png_sha256']})
            targets = [t for p in result['additional_pages'] for t in p['targets']]
            for inv in inventories.values():
                key = inv.get('drawing_reference_review', {}).get('view_key_candidate')
                if key: targets.append({'view_key_candidate': key, 'view_id': inv['view_id'],
                    'document_sha256': inv['document_sha256'], 'page': inv['page'], 'physical_building_identity_verified': False})
            references = [r for p in result['roof_page_references'] for r in p['side_reference_review']['references']]
            result['target_links'] = target_links(references, targets, charge)
        except OverflowError as error:
            result.update(status='roof_reference_evidence_budget_withheld', reason=str(error),
                source_topologies=[], roof_page_references=[], additional_pages=[], target_links=[],
                aim_checks=[], rendered_views=[], output_artifact_sha256={})
        for path, pin in pins.items():
            if file_hash(path) != pin: raise ValueError('Original roof-reference input changed during build')
        _verified_inputs(components, views, corpus)
        result['counts'] = {'additional_source_documents': len(entries), 'additional_source_pages': len(result['additional_pages']),
            'additional_view_candidates': len(result['rendered_views']),
            'side_reference_candidates': sum(len(p['side_reference_review']['references']) for p in result['roof_page_references']),
            'unique_source_target_links': sum(t['status'] == 'unique_source_view_reference_candidate' for t in result['target_links']),
            'missing_source_targets': sum(t['status'] == 'missing_source_view_target' for t in result['target_links']),
            'source_visibility_holds': sum(t['status'] == 'source_reference_visibility_or_identity_held' for t in result['target_links']),
            'source_aim_diagnostics': len(result['aim_checks']), 'new_roof_models': 0}
        if len(json.dumps(result).encode()) > 32000000: raise ValueError('Roof-reference evidence output budget exceeded')
        # Native glyph helpers use integer trace-map keys. Normalize the public
        # JSON model before hashing/caching so loaded string keys replay equally.
        result = json.loads(json.dumps(result))
        if (root / 'roof-reference-evidence.json').exists():
            if digest(json.loads((root / 'roof-reference-evidence.json').read_text())) != digest(result):
                raise ValueError('Saved roof-reference evidence changed')
            for name, pin in result['output_artifact_sha256'].items():
                if file_hash(root / name) != pin: raise ValueError('Saved roof-reference crop changed')
        else:
            for name in result['output_artifact_sha256']:
                target = root / name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(temporary / name, target)
            atomic_json(root / 'roof-reference-evidence.json', result)
    return {**result, 'directory': str(root)}
