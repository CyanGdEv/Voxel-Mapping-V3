"""Unseeded source regions, wall bands and opening evidence per candidate view.

These inventories never select a physical outline or carve an aperture.
"""
from collections import Counter
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, __version__ as PIL_VERSION
import pymupdf
import shapely
from shapely.affinity import affine_transform
from shapely.geometry import Polygon, box, mapping, shape

from . import architectural_interpretation, drawing_components, native_opening_inventory, raster_opening_scan
from . import raster_stroke_context, drawing_annotation_context, glyph_visibility, ordinary_surfaces
from . import jamb_group_partitions
from .drawing_view_candidates import VERSION as VIEW_VERSION
from .generation_cycles import atomic_json, file_hash
from .reconstruction_evidence_queue import digest

VERSION = 'automatic-view-component-inventory-v3'
DEFAULTS = {'max_views': 32, 'max_checks': 100000, 'max_frames': 512}
MAX_OUTPUT_BYTES = 64000000


def options(settings=None):
    if settings is None: settings = {}
    if not isinstance(settings, dict) or set(settings) - set(DEFAULTS):
        raise ValueError('Known view-component options required')
    result = {**DEFAULTS, **settings}
    if any(type(v) is not int or not 1 <= v <= DEFAULTS[k] for k, v in result.items()):
        raise ValueError('Bounded view-component options required')
    return result


def affine(matrix):
    return [matrix.a, matrix.c, matrix.b, matrix.d, matrix.e, matrix.f]


def orient(gray, pixel_native, direction):
    """Rotate pixel edges by exact quarter turns, with no resampling."""
    matrix = pymupdf.Matrix(pixel_native); inverse = ~matrix
    if (not all(math.isfinite(v) for v in matrix) or abs(matrix.a*matrix.d-matrix.b*matrix.c) < 1e-15):
        raise ValueError('Invertible finite source pixel transform required')
    x, y = direction
    vector = (inverse.a*x + inverse.c*y, inverse.b*x + inverse.d*y)
    length = math.hypot(*vector)
    if not length: raise ValueError('Nonzero caption reading direction required')
    unit = tuple(round(v/length) for v in vector)
    turns = {(1, 0): 0, (0, 1): 1, (-1, 0): 2, (0, -1): 3}
    if unit not in turns or any(abs(vector[i]/length-unit[i]) > 1e-6 for i in (0, 1)):
        raise ValueError('Orthogonal caption pixel direction required')
    k = turns[unit]; height, width = gray.shape
    old = [pymupdf.Matrix(1, 0, 0, 1, 0, 0), pymupdf.Matrix(0, 1, -1, 0, width, 0),
           pymupdf.Matrix(-1, 0, 0, -1, width, height), pymupdf.Matrix(0, -1, 1, 0, 0, height)][k]
    return np.ascontiguousarray(np.rot90(gray, k)), old*matrix, k


def inspect_view(view, parents, gray, pixel_native, *, settings=None, source_page=None):
    """The caller binds original parents and source crop bytes before this pass."""
    config = options(settings); scope = shape(view['geometry'])
    if len(parents) > 10000 or len({p['id'] for p in parents}) != len(parents):
        raise ValueError('Bounded unique original view parents required')
    if any(p['document_sha256'] != view['document_sha256'] or p['page'] != view['page']
           or not scope.covers(shape(p['geometry'])) for p in parents):
        raise ValueError('Whole parents from the same source view required')
    records = sorted(drawing_components.split_page(parents), key=lambda r: r['id'])
    factor = view['nominal_metres_per_pdf_point']; local = view['native_to_nominal_local_affine']
    if factor is not None and (type(factor) not in (int, float) or not math.isfinite(factor) or factor <= 0 or local is None):
        raise ValueError('Finite nominal view scale required')
    def geometry_record(g):
        return {'geometry_pdf_native': mapping(g),
                'geometry_nominal_local': mapping(affine_transform(g, local)) if local is not None else None}
    regions = []
    for record in records:
        g = shape(record['geometry'])
        if g.geom_type == 'LineString' and g.is_ring: g = Polygon(g.coords)
        if g.geom_type != 'Polygon' or not g.is_valid or g.area <= 0: continue
        regions.append({'id': digest([VERSION, view['id'], record['id'], 'region']),
                        'source_component_id': record['id'], 'source_component_sha256': digest(record),
                        **geometry_record(g), 'source_hole_count': len(g.interiors),
                        'curve_approximation_present': bool(record['curve_approximation']['cubic_segments']),
                        'status': 'closed_source_region_role_unresolved', 'physical_boundary_verified': False})
    kind = view['printed_claim']['view_kind']; bands = []; band_review = {'status': 'not_a_floor_plan'}
    if kind == 'plan' and view['printed_claim'].get('plan_level_or_form') != 'roof':
        if factor is None: band_review = {'status': 'nominal_view_scale_required'}
        else:
            bands, band_review = architectural_interpretation.wall_bands_from_components(
                records, factor, interpretation_options={'max_pair_comparisons': config['max_checks']})
    frames = {'status': 'not_an_elevation', 'frames': []}
    scan = {'status': 'not_an_elevation', 'candidates': [], 'index': None}
    hypotheses = []; residual_hypotheses = []; raster = None
    legacy_attempts = {}
    stroke_context = {'status': 'not_an_elevation', 'variants': []}
    residual_scan = {'status': 'not_an_elevation', 'index': None}
    text_context = {'status': 'not_an_elevation', 'labels': [], 'cycles': []}
    if kind == 'elevation':
        if gray is None:
            frames = {'status': 'source_raster_budget_withheld', 'frames': []}
            scan = {'status': 'source_raster_budget_withheld', 'candidates': [], 'index': None}
            stroke_context = {'status': 'source_raster_budget_withheld', 'variants': []}
            residual_scan = {'status': 'source_raster_budget_withheld', 'index': None}
            text_context = {'status': 'source_raster_budget_withheld', 'labels': [], 'cycles': []}
        else:
            gray = np.asarray(gray)
            if gray.dtype != np.uint8 or gray.ndim != 2 or gray.size > 6000000 or max(gray.shape) > 3000:
                raise ValueError('Bounded uint8 source raster required')
            gray, matrix, k = orient(gray, pixel_native, view['caption_evidence']['reading_direction_pdf_native'])
            height, width = gray.shape; inverse = ~matrix
            raster = {'quarter_turns_counterclockwise': k, 'size_pixels': [width, height],
                      'pixel_edge_to_pdf_native_matrix': list(matrix), 'resampling_applied': False}
            if factor is None: frames = {'status': 'nominal_view_scale_required', 'frames': []}
            else:
                step = math.hypot(matrix.a, matrix.b)
                if abs(step-math.hypot(matrix.c, matrix.d)) > 1e-6 or abs(matrix.a*matrix.c+matrix.b*matrix.d) > 1e-6:
                    raise ValueError('Uniform orthogonal source raster required')
                frames = native_opening_inventory.frame_candidates(
                    records, [0, 0, width, height], list(inverse), factor*step,
                    max_checks=config['max_checks'], max_frames=config['max_frames'])
                for frame in frames['frames']:
                    frame.update(geometry_record(affine_transform(shape(frame['geometry_pixels']), affine(matrix))))
            scan = raster_opening_scan.scan(gray, representation='indexed', pair_scope='all', max_checks=config['max_checks'])
            if scan.get('reason') == 'vertical_run_group_budget':
                legacy_attempts['raster'] = scan
                scan = raster_opening_scan.scan(gray, representation='indexed', pair_scope='all',
                    max_checks=config['max_checks'], partition_groups=True)
            if scan['index'] is not None:
                for i, family in enumerate(scan['index']['consensus_families']):
                    g = affine_transform(box(*family['bounds_pixels']), affine(matrix))
                    hypotheses.append({'id': digest([VERSION, view['id'], 'raster', i, family]),
                        'consensus_family_index': i, **geometry_record(g),
                        'status': 'unverified_jamb_head_correspondence' if scope.covers(g) else 'candidate_scope_crossing_withheld',
                        'physical_opening_verified': False, 'opening_type': None, 'floor_datum_verified': False})
            stroke_context = raster_stroke_context.review(gray, max_checks=config['max_checks'])
            if stroke_context['status'] == 'repeated_stroke_layout_context_only':
                residual_scan = raster_opening_scan.scan(gray, representation='indexed', pair_scope='all',
                    max_checks=config['max_checks'], excluded_groups=stroke_context['excluded_groups'])
                if residual_scan.get('reason') == 'vertical_run_group_budget':
                    legacy_attempts['residual'] = residual_scan
                    residual_scan = raster_opening_scan.scan(gray, representation='indexed', pair_scope='all',
                        max_checks=config['max_checks'], excluded_groups=stroke_context['excluded_groups'], partition_groups=True)
                if residual_scan['index'] is not None:
                    for i, family in enumerate(residual_scan['index']['consensus_families']):
                        g = affine_transform(box(*family['bounds_pixels']), affine(matrix))
                        residual_hypotheses.append({'id': digest([VERSION, view['id'], 'residual', i, family]),
                            'consensus_family_index': i, **geometry_record(g),
                            'status': 'residual_jamb_head_context_candidate' if scope.covers(g) else 'candidate_scope_crossing_withheld',
                            'search_scope': 'residual_jamb_groups_only', 'physical_opening_verified': False,
                            'opening_type': None, 'floor_datum_verified': False})
            else: residual_scan = {'status': 'stroke_context_budget_withheld', 'index': None}
            text_context = drawing_annotation_context.review(source_page, scope, frames['frames'], max_checks=config['max_checks']) if source_page is not None else {'status': 'original_text_page_required', 'labels': [], 'cycles': []}
    return {'version': VERSION, 'view_id': view['id'], 'document_sha256': view['document_sha256'], 'page': view['page'],
            'caption': view['caption_text'], 'printed_claim': view['printed_claim'],
            'source_view_sha256': digest(view), 'source_parent_records_sha256': digest(sorted(parents, key=lambda p: p['id'])),
            'source_components': records, 'closed_source_regions': regions, 'wall_band_candidates': bands,
            'wall_band_review': band_review, 'native_rectangle_review': frames, 'raster_opening_scan': scan,
            'raster_coordinate_receipt': raster, 'raster_opening_hypotheses': hypotheses,
            'repeated_stroke_context': stroke_context, 'residual_raster_scan': residual_scan,
            'residual_raster_hypotheses': residual_hypotheses, 'native_cycle_text_context': text_context,
            'legacy_group_limit_attempts': legacy_attempts,
            'counts': {'source_components': len(records), 'closed_source_regions': len(regions), 'wall_bands': len(bands),
                       'native_rectangle_cycles': len(frames['frames']), 'raster_opening_families': len(hypotheses),
                       'raster_scope_crossings': sum(h['status']=='candidate_scope_crossing_withheld' for h in hypotheses),
                       'residual_raster_families': len(residual_hypotheses),
                       'partitioned_scan_passes': int('group_partition_proofs' in scan)+int('group_partition_proofs' in residual_scan),
                       'repeated_stroke_groups': sum(len(v['residual_excluded_group_indices']) for v in stroke_context['variants']),
                       'numeric_or_level_cycle_contexts': sum(c['status']=='visible_numeric_or_level_text_overlap' for c in text_context['cycles'])},
            'view_scope_verified': False, 'physical_boundary_verified': False, 'world_placement_eligible': False,
            'accepted_physical_components': 0, 'world_geometry_additions': 0, 'training_labels_generated': 0,
            'remaining_requirements': ['Identify actual exterior, roof and aperture boundaries among the retained alternatives.',
                'Resolve view construction state and reconcile plan/elevation dimensions and levels.',
                'Establish independent geographic registration and vertical datum before park placement.']}


def run(corpus, drawing_directory, view_directory, output, *, settings=None):
    config = options(settings); drawing_directory = Path(drawing_directory); view_directory = Path(view_directory)
    source_report = view_directory/'view-report.json'; source_data = view_directory/'view-candidates.json'
    if source_data.stat().st_size > 128000000: raise ValueError('Bounded source view pack required')
    report = json.loads(source_report.read_text()); data = json.loads(source_data.read_text())
    feed = drawing_directory/'geometry-candidates.jsonl'
    if (report['contract'] != data['contract'] or report['contract']['version'] != VIEW_VERSION
            or file_hash(feed) != report['contract']['drawing_feed_sha256']):
        raise ValueError('Current matching source view pack and drawing feed required')
    source_pins = {name: file_hash(view_directory/name) for name in report['output_sha256']}
    if source_pins != report['output_sha256']: raise ValueError('Source view artifact changed')
    for sha in report['contract']['source_sha256']:
        if file_hash(corpus.root/'files'/(sha+'.pdf')) != sha: raise ValueError('Original component source changed')
    contract = {'version': VERSION, 'options': config, 'view_report_sha256': file_hash(source_report),
                'view_candidates_sha256': file_hash(source_data), 'drawing_feed_sha256': file_hash(feed),
                'implementation_sha256': file_hash(Path(__file__)),
                'kernel_sha256': {module.__name__: file_hash(Path(module.__file__)) for module in
                    [architectural_interpretation, drawing_components, native_opening_inventory, raster_opening_scan,
                     raster_stroke_context, drawing_annotation_context, glyph_visibility, ordinary_surfaces, jamb_group_partitions]},
                'pillow_version': PIL_VERSION, 'numpy_version': np.__version__, 'pymupdf_version': pymupdf.VersionBind,
                'shapely_version': shapely.__version__, 'geos_version': shapely.geos_version_string}
    root = Path(output)/digest(contract)
    if root.exists():
        result = json.loads((root/'component-report.json').read_text())
        if result['contract'] != contract: raise ValueError('Component contract changed')
        for name, pin in result['output_sha256'].items():
            if file_hash(root/name) != pin: raise ValueError('Component output changed')
        return {**result, 'directory': str(root), 'run_views': 0, 'reused_views': result['views']}
    views = [(p, v) for p in data['pages'] for v in p['views']]
    selected = views[:config['max_views']]; keys = {(p['document_sha256'], p['page']) for p, _ in selected}
    parents = {key: {} for key in keys}
    with feed.open() as stream:
        for line in stream:
            parent = json.loads(line); key = (parent['document_sha256'], parent['page'])
            if key not in parents: continue
            if parent['id'] in parents[key] or len(parents[key]) >= 10000: raise ValueError('Unique bounded page parents required')
            parents[key][parent['id']] = parent
    results = []; counts = Counter(); withheld = []; root.mkdir(parents=True); names = []; output_bytes = 0
    for page, view in selected:
        key = (page['document_sha256'], page['page']); raw = parents[key]; retained = []
        membership = {m['source_id']: m for m in page['source_membership']}
        for source in view['whole_sources']:
            if source['kind'] != 'native_vector': continue
            parent = raw.get(source['id'])
            if parent is None: raise ValueError('Original view parent missing')
            reference = {'id': parent['id'], 'document_sha256': key[0], 'page': key[1], 'kind': 'native_vector',
                         'geometry': parent['geometry'], 'parent_record_sha256': digest(parent)}
            m = membership[source['id']]
            if (digest(reference) != source['record_sha256'] or digest(parent['geometry']) != digest(source['geometry_pdf_native'])
                    or m['source_record_sha256'] != source['record_sha256'] or m['status'] != 'one_whole_source_candidate'
                    or m['contained_candidate_ids'] != [view['id']] or m['crossing_candidate_ids']):
                raise ValueError('Whole original source membership required')
            retained.append(parent)
        receipt_path = view_directory/view['render']['receipt']; receipt = json.loads(receipt_path.read_text())
        image_path = view_directory/view['render']['png']
        if (receipt['document_sha256'] != key[0] or receipt['page'] != key[1]
                or receipt['bounds_pdf_native'] != list(shape(view['geometry']).bounds)
                or file_hash(image_path) != receipt['png_sha256'] or receipt['png_sha256'] != view['render']['png_sha256']):
            raise ValueError('Matching original view render required')
        gray = None
        if view['printed_claim']['view_kind'] == 'elevation':
            with Image.open(image_path) as image:
                if list(image.size) != receipt['size_pixels']: raise ValueError('Source raster dimensions changed')
                if image.width*image.height <= 6000000 and max(image.size) <= 3000:
                    gray = np.asarray(image.convert('L')).copy()
        with pymupdf.open(corpus.root/'files'/(key[0]+'.pdf')) as document:
            result = inspect_view({**view, 'document_sha256': key[0], 'page': key[1]}, retained, gray,
                                  receipt['pixel_edge_to_pdf_native_matrix'], settings=config, source_page=document[key[1]-1])
        result['source_view_sha256'] = digest(view)
        result['source_render_receipt_sha256'] = file_hash(receipt_path)
        result['source_png_sha256'] = receipt['png_sha256']
        for kernel, review in [('wall_bands', result['wall_band_review']),
                               ('native_rectangles', result['native_rectangle_review']),
                               ('raster_openings', result['raster_opening_scan']),
                               ('stroke_context', result['repeated_stroke_context']),
                               ('residual_raster', result['residual_raster_scan']),
                               ('cycle_text', result['native_cycle_text_context'])]:
            if review['status'].endswith(('_withheld', '_required')):
                withheld.append({'view_id': view['id'], 'kernel': kernel, 'status': review['status'],
                                 'reason': review.get('reason')})
        name = 'views/'+view['id']+'.json'; atomic_json(root/name, result)
        output_bytes += (root/name).stat().st_size
        if output_bytes > MAX_OUTPUT_BYTES: raise ValueError('Component output budget exceeded')
        names.append(name); counts.update(result['counts']); results.append({'view_id': view['id'], 'file': name,
            'caption': result['caption'], 'counts': result['counts'],
            'native_status': result['native_rectangle_review']['status'], 'raster_status': result['raster_opening_scan']['status'],
            'residual_raster_status': result['residual_raster_scan']['status'],
            'text_context_status': result['native_cycle_text_context']['status']})
    if (file_hash(feed) != contract['drawing_feed_sha256'] or file_hash(source_data) != contract['view_candidates_sha256']
            or file_hash(source_report) != contract['view_report_sha256']): raise ValueError('Source inputs changed during component inventory')
    for name, pin in source_pins.items():
        if file_hash(view_directory/name) != pin: raise ValueError('Source view changed during component inventory')
    for sha in report['contract']['source_sha256']:
        if file_hash(corpus.root/'files'/(sha+'.pdf')) != sha: raise ValueError('Original source changed during component inventory')
    result = {'contract': contract, 'status': 'partial_component_inventory' if len(views) > len(selected) else
              'component_candidates_with_withheld_passes' if withheld else 'component_candidates_only',
              'views': len(results), 'deferred_views': len(views)-len(results), 'counts': dict(counts), 'results': results,
              'withheld_passes': withheld, 'all_requested_passes_completed': not withheld and len(views)==len(selected),
              'output_sha256': {name: file_hash(root/name) for name in names}, 'world_geometry_additions': 0,
              'accepted_physical_components': 0, 'training_labels_generated': 0, 'world_placement_eligible': False}
    atomic_json(root/'component-report.json', result)
    return {**result, 'directory': str(root), 'run_views': len(results), 'reused_views': 0}
