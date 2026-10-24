"""Bounded native outlines within inferred drawing views, without physical acceptance.

Regional extraction keeps complete paint primitives. It never clips artwork to a
caption box, snaps endpoints, or classifies a closed face as a building or path.
"""
from collections import Counter
from concurrent.futures import CancelledError
import json
import math
import re

import pymupdf
from shapely.affinity import affine_transform
from shapely.errors import ShapelyError
from shapely.geometry import box, mapping, shape

from . import building_raster_views, drawing_geometry, drawing_view_candidates, linework_boundaries
from .building_spec import digest

VERSION = 'planning-view-geometry-v1'
LIMITS = {'max_views': 16, 'max_candidates_per_view': 2000,
          'max_points_per_view': 100000, 'max_total_parents': 12000,
          'max_total_points': 200000, 'max_paths': 100000,
          'max_scan_paths': 100000, 'max_outlines': 500,
          'max_face_provenance': 2048,
          'max_output_bytes': 16000000}
FRAME = 'pdf_native_points_y_up'


def _options(options):
    options = {} if options is None else options
    if not isinstance(options, dict) or set(options)-set(LIMITS):
        raise ValueError('Known view geometry limits required')
    result = {**LIMITS, **options}
    if any(type(v) is not int or not 1 <= v <= LIMITS[k] for k, v in result.items()):
        raise ValueError('Lower-only bounded view geometry limits required')
    if result['max_output_bytes'] < 16384:
        raise ValueError('View geometry output needs at least 16384 metadata bytes')
    return result


def _measure(geometry):
    return {'bounds': list(geometry.bounds), 'area': geometry.area,
            'perimeter': geometry.length,
            'hole_count': sum(len(p.interiors) for p in
                ([geometry] if geometry.geom_type == 'Polygon' else geometry.geoms))}


def _point_count(geometry):
    if geometry.geom_type == 'LineString':
        return len(geometry.coords)
    return sum(len(p.exterior.coords)+sum(len(r.coords) for r in p.interiors)
               for p in ([geometry] if geometry.geom_type == 'Polygon' else geometry.geoms))


def _native_frame(page):
    rotation = page.rotation
    inverse = drawing_geometry.native_inverse(page)
    try:
        page.set_rotation(0)
        return box(*(page.rect*inverse))
    finally:
        page.set_rotation(rotation)


def _scope(view, frame):
    """Reject unsupported scopes; recompute rather than trust a supplied affine."""
    if view.get('coordinate_frame') != FRAME:
        raise ValueError('Native drawing view frame required')
    geometry = view.get('geometry')
    polygon = shape(geometry)
    if (polygon.geom_type != 'Polygon' or polygon.is_empty or not polygon.is_valid
            or polygon.interiors or not polygon.equals(box(*polygon.bounds))
            or not frame.covers(polygon)
            or any(not math.isfinite(v) for v in polygon.bounds)):
        raise ValueError('Complete axis-aligned rectangular view inside original page required')
    caption = view.get('caption_evidence', {})
    if (not isinstance(caption, dict) or caption.get('id') != view.get('caption_id')
            or caption.get('printed_claim') != view.get('printed_claim')
            or caption.get('glyph_screen', {}).get('status') != 'raster_consistent_candidate'
            or not polygon.covers(shape(caption.get('label_geometry')))):
        raise ValueError('Same visible source caption inside view required')
    axis = caption.get('reading_direction_pdf_native')
    if (not isinstance(axis, (list, tuple)) or len(axis) != 2
            or tuple(axis) not in ((1, 0), (0, 1), (-1, 0), (0, -1))):
        raise ValueError('Orthogonal native caption reading direction required')
    claim = caption['printed_claim']
    inline = claim.get('printed_scale_denominator')
    adjacent = caption.get('adjacent_scale_candidates', [])
    factor = None
    if view.get('nominal_scale_status') == 'unique_view_scale_claim':
        denominators = [inline] if inline is not None else [s.get('printed_denominator') for s in adjacent]
        conflict = inline is not None and any(s.get('printed_denominator') != inline for s in adjacent)
        visible = all(s.get('glyph_screen', {}).get('status') == 'raster_consistent_candidate' for s in adjacent)
        if (len(denominators) != 1 or conflict or not visible
                or type(denominators[0]) is not int or not 1 <= denominators[0] <= 10000):
            raise ValueError('Unique visible bounded per-view scale claim required')
        factor = denominators[0]*.0254/72
        if view.get('nominal_metres_per_pdf_point') != factor:
            raise ValueError('Per-view nominal factor differs from printed claim')
    normal = (-axis[1], axis[0])
    points = list(polygon.exterior.coords)
    lower_a = min(x*axis[0]+y*axis[1] for x, y in points)
    lower_b = min(x*normal[0]+y*normal[1] for x, y in points)
    affine = ([axis[0]*factor, axis[1]*factor, normal[0]*factor, normal[1]*factor,
               -lower_a*factor, -lower_b*factor] if factor is not None else None)
    if affine is not None and view.get('native_to_nominal_local_affine') != affine:
        raise ValueError('Per-view nominal affine differs from source scope and scale')
    return polygon, caption, affine


def page_candidates(page, sha, number, view_pack, *, options=None, cancelled=lambda: False):
    """Inspect inferred scopes independently of a whole-sheet topology graph.

    Inputs bind to an upstream checksum-verified original page. All returned
    areas/dimensions in metres are nominal paper-scale claims, not measurements
    of independently identified physical park features.
    """
    limits = _options(options)
    if (not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
            or type(number) is not int or number < 1 or page.number+1 != number):
        raise ValueError('Pinned original PDF page identity required')
    if (not isinstance(view_pack, dict) or view_pack.get('version') != drawing_view_candidates.VERSION
            or view_pack.get('document_sha256') != sha or view_pack.get('page') != number
            or view_pack.get('status') != 'automatic_view_candidates_only'):
        raise ValueError('Same complete current source-bound view pack required')
    views = view_pack.get('views')
    if (not isinstance(views, list) or len(views) > 128
            or any(not isinstance(v, dict) or not isinstance(v.get('id'), str) for v in views)
            or len({v['id'] for v in views}) != len(views)):
        raise ValueError('Distinct bounded drawing view candidates required')
    frame = _native_frame(page)
    scope_rows = []
    outlines = []
    counters = Counter()
    parents_used = points_used = record_bytes = 0
    stop_reason = None
    paths = None
    def check():
        if cancelled():
            raise CancelledError('Regional planning geometry cancelled')
    check()
    unit_kind, unit_value = page.parent.xref_get_key(page.xref, 'UserUnit')
    try:
        user_unit = 1. if unit_kind == 'null' else float(unit_value)
        standard_units = math.isfinite(user_unit) and user_unit == 1.
        if not math.isfinite(user_unit):
            user_unit = None
    except (ValueError, TypeError):
        user_unit = None
        standard_units = False
    try:
        raster_inventory = building_raster_views.placements(page, sha, number)
    except (ValueError, RuntimeError, TypeError, OverflowError) as error:
        raster_inventory = {'status': 'image_placement_inventory_failed', 'placements': [],
                            'reason': str(error)[:512]}
    raster_complete = raster_inventory['status'] == 'source_image_placements_only'
    raster_sources = [(r['id'], shape(r['geometry'])) for r in raster_inventory['placements']]
    # Metadata reserve leaves room for all bounded per-view diagnostics.
    available_bytes = max(0, limits['max_output_bytes']-65536)
    for index, view in enumerate(views):
        check()
        receipt = {'view_id': view['id'], 'source_view_sha256': digest(view),
                   'caption_id': view.get('caption_id'), 'status': 'view_scope_withheld',
                   'outlines': 0, 'native_parents': 0, 'native_points': 0}
        scope_rows.append(receipt)
        if index >= limits['max_views']:
            receipt.update(status='view_limit_deferred', reason='Maximum inspected view count reached')
            continue
        if stop_reason:
            receipt.update(status='collection_budget_deferred', reason=stop_reason)
            continue
        try:
            polygon, caption, affine = _scope(view, frame)
        except (ValueError, TypeError, KeyError, AttributeError, ShapelyError) as error:
            receipt['reason'] = str(error)[:512]
            continue
        nominal_scale_withheld = affine is not None and not standard_units
        if nominal_scale_withheld:
            affine = None
        raster_ids = [identifier for identifier, geometry in raster_sources
                      if polygon.intersection(geometry).area > 0]
        receipt.update(bounds_pdf_native=list(polygon.bounds),
            caption_text=str(caption.get('text', ''))[:512],
            printed_claim=caption['printed_claim'],
            nominal_scale_status=view.get('nominal_scale_status'),
            nominal_metres_per_pdf_point=view.get('nominal_metres_per_pdf_point') if affine is not None else None,
            native_to_nominal_local_affine=affine,
            nominal_scale_withheld=nominal_scale_withheld,
            nominal_scale_withheld_reason='Nondefault or invalid PDF UserUnit requires physical paper-unit interpretation' if nominal_scale_withheld else None,
            raster_source_placement_count=len(raster_ids),
            raster_source_placement_ids=raster_ids[:16],
            raster_placement_references_truncated=len(raster_ids)>16,
            raster_geometry_unresolved=bool(raster_ids),
            raster_placement_inventory_complete=raster_complete)
        if paths is None:
            check()
            paths = page.get_cdrawings(extended=True)
        if len(paths) > limits['max_scan_paths']:
            stop_reason = 'Original page raw paint scan budget exceeded'
            receipt.update(status='source_scan_budget_withheld', raw_paths=len(paths), reason=stop_reason)
            continue
        remaining_parents = limits['max_total_parents']-parents_used
        remaining_points = limits['max_total_points']-points_used
        if not remaining_parents or not remaining_points:
            stop_reason = 'Cumulative native candidate or point budget exhausted'
            receipt.update(status='collection_budget_deferred', reason=stop_reason)
            continue
        extraction_options = {'region_native_points': list(polygon.bounds),
            'min_line_length_points': .25, 'max_candidates': min(limits['max_candidates_per_view'], remaining_parents),
            'max_total_points': min(limits['max_points_per_view'], remaining_points),
            'max_paths': limits['max_paths'], 'max_scan_paths': limits['max_scan_paths'],
            'regional_fallback': False}
        check()
        try:
            parents, extraction = drawing_geometry.extract_page(page, sha, number, _paths=paths, **extraction_options)
        except (ValueError, RuntimeError, TypeError, OverflowError) as error:
            receipt.update(status='regional_extraction_failed', reason=str(error)[:512])
            continue
        points = sum(_point_count(shape(p['geometry'])) for p in parents)
        parents_used += len(parents)
        points_used += points
        receipt.update(extraction=extraction, extraction_options=extraction_options,
            source_parents_sha256=digest(parents), native_parents=len(parents), native_points=points)
        if extraction['status'] != 'unplaced_geometry_candidates':
            receipt.update(status='incomplete_regional_extraction', reason=extraction['status'])
            continue
        receipt['status'] = 'complete_regional_outline_candidates'
        crossings = extraction.get('rejections', {}).get('complete_primitive_crosses_region_boundary', 0)
        if crossings:
            receipt.update(status='regional_outlines_with_deferred_crossing_primitives',
                reason='Whole source primitives cross inferred scope edges and remain withheld',
                crossing_primitives_withheld=crossings)
        check()
        try:
            recovered, recovery = linework_boundaries.recover_page(parents,
                recovery_options={'max_face_provenance': limits['max_face_provenance']})
        except (ValueError, RuntimeError, TypeError, OverflowError) as error:
            recovered = []
            recovery = {'status': 'regional_boundary_recovery_failed', 'reason': str(error)[:512]}
        receipt['recovery'] = recovery
        deferred = recovery.get('counts', {})
        recovery_complete = (recovery['status'] in ('enclosed_faces_only', 'no_eligible_linework')
            and not any(deferred.get(key, 0) for key in (
                'face_vertex_budget', 'provenance_budget_deferred', 'combined_page_budget_deferred')))
        if not recovery_complete:
            receipt.update(status='incomplete_regional_boundary_recovery',
                reason='recovery_face_or_provenance_budget_deferred' if recovery['status'] == 'enclosed_faces_only' else recovery['status'])
        complete_faces = [p for p in recovered if p.get('extraction_kind') == 'linework_boundaries'] if recovery_complete and recovery['status'] == 'enclosed_faces_only' else []
        seen = set()
        for source in parents+complete_faces:
            check()
            geometry = shape(source['geometry'])
            if geometry.geom_type not in ('Polygon', 'MultiPolygon'):
                continue
            if source.get('paint_reference_truncated'):
                counters['truncated_provenance_withheld'] += 1
                continue
            if not polygon.covers(geometry):
                raise ValueError('Regional extractor returned geometry outside its source view')
            identity = geometry.normalize().wkb_hex
            if identity in seen:
                counters['duplicate_outline_withheld'] += 1
                continue
            seen.add(identity)
            nominal = affine_transform(geometry, affine) if affine is not None else None
            source_sha = digest(source)
            record = {'id': digest([VERSION, sha, number, view['id'], source_sha]),
                'document_sha256': sha, 'page': number, 'coordinate_frame': FRAME,
                'view_id': view['id'], 'caption_id': view['caption_id'],
                'source_view_sha256': receipt['source_view_sha256'], 'source_record_sha256': source_sha,
                'source_candidate': source, 'geometry_pdf_native': mapping(geometry),
                'measurements_pdf_points': _measure(geometry),
                'geometry_nominal_local': mapping(nominal) if nominal is not None else None,
                'measurements_nominal_metres': _measure(nominal) if nominal is not None else None,
                'measurement_basis': 'unverified_view_paper_scale_claim' if nominal is not None else 'native_pdf_points_only',
                'semantic_role': 'unclassified_closed_outline', 'physical_identity_verified': False,
                'paint_visibility_verified': False,
                'view_scope_verified': False, 'scale_application_verified': False,
                'registration_verified': False, 'world_placement_eligible': False,
                'geometric_accuracy': None}
            size = len(json.dumps(record, sort_keys=True, allow_nan=False).encode())
            if len(outlines) >= limits['max_outlines'] or record_bytes+size > available_bytes:
                stop_reason = 'Closed-outline count or output byte budget exhausted'
                receipt.update(status='outline_output_budget_deferred', reason=stop_reason)
                counters['outline_output_budget_deferred'] += 1
                break
            record_bytes += size
            outlines.append(record)
            receipt['outlines'] += 1
        if receipt['status'] == 'complete_regional_outline_candidates':
            if nominal_scale_withheld:
                receipt.update(status='regional_native_geometry_with_scale_gap',
                    reason=receipt['nominal_scale_withheld_reason'])
            elif not raster_complete:
                receipt.update(status='regional_native_geometry_with_raster_inventory_gap',
                    reason=raster_inventory['status'])
            elif raster_ids and not receipt['outlines']:
                receipt.update(status='raster_geometry_unresolved',
                    reason='Image placements overlap inferred view but no native closed outline was retained; raster content interpretation remains unresolved')
    statuses = Counter(v['status'] for v in scope_rows)
    summary = {'detected_views': len(views), 'inspected_views': sum('extraction' in v for v in scope_rows),
        'complete_views': statuses['complete_regional_outline_candidates'],
        'deferred_or_incomplete_views': sum(v['status'] != 'complete_regional_outline_candidates' for v in scope_rows),
        'native_parents': parents_used, 'native_points': points_used, 'closed_outlines': len(outlines),
        'nominally_scaled_outlines': sum(o['geometry_nominal_local'] is not None for o in outlines),
        'view_statuses': dict(statuses), **dict(counters)}
    result = {'version': VERSION, 'document_sha256': sha, 'page': number,
        'source_view_pack_sha256': digest(view_pack), 'coordinate_frame': FRAME, 'limits': limits,
        'pdf_user_unit': user_unit,
        'source_image_inventory_sha256': digest(raster_inventory),
        'source_image_inventory_status': raster_inventory['status'],
        'status': 'scoped_source_geometry_candidates' if not summary['deferred_or_incomplete_views'] else 'scoped_source_geometry_candidates_with_gaps',
        'views': scope_rows, 'outlines': outlines, 'summary': summary,
        'view_scope_verified': False, 'scale_application_verified': False,
        'physical_identity_verified': False, 'registration_verified': False,
        'world_placement_eligible': False, 'world_geometry_additions': 0,
        'training_labels_generated': 0, 'geometric_accuracy': None,
        'limitations': ['Caption regions are unverified layout hypotheses; enclosed faces can be symbols, rooms, context or annotations.',
            'Whole paint primitives crossing region edges are withheld; no source clipping, endpoint snapping or gap repair.',
            'Nominal local paper-scale measurements do not establish physical dimensions, source state, materials or geographic registration.',
            'Image placements are source occurrences, never object footprints; overlapping raster content remains uninterpreted.',
            'Paint visibility and enclosed-face physical meaning remain unverified; native parser allocation precedes the raw-path count gate.']}
    if len(json.dumps(result, sort_keys=True, allow_nan=False).encode()) > limits['max_output_bytes']:
        raise ValueError('Regional view report metadata exceeded output byte budget')
    check()
    return result
