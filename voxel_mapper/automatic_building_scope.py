"""Visible named source enclosures and numbered facade rays; no physical selection."""
import math
import re

import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import LineString, Polygon, mapping, shape

from . import drawing_views, footprint_hypotheses, plan_elevation_edges
from . import plan_elevation_correspondence
from .automatic_opening_links import affine, bounded_work
from .drawing_page_tools import native_inverse
from .glyph_visibility import screen_architectural_span
from .ordinary_surfaces import label_runs
from .reconstruction_evidence_queue import digest

VERSION = 'automatic-named-building-scope-v1'
NAME = re.compile(r'(?:shop|(?:ride )?station|[A-Za-z][A-Za-z0-9 -]{0,63} building)', re.I)
MAX_LABELS = 16


def references(page, view):
    result = {'status': 'original_source_page_required', 'sheet_identity': None,
              'header_glyph_screen': None, 'plan_references': None, 'view_key_candidate': None,
              'whole_view_reference_sha256': [], 'crossing_view_reference_sha256': []}
    if page is None: return result
    traces = page.get_texttrace()
    if len(traces)>10000 or sum(len(t['chars']) for t in traces)>500000:
        return {**result, 'status': 'source_reference_budget_withheld'}
    identity = drawing_views.sheet_identity(traces)
    screen = screen_architectural_span(page, traces[identity['trace_index']]) if identity else None
    result.update(sheet_identity=identity, header_glyph_screen=screen, status='source_reference_candidates_only')
    if view['printed_claim']['view_kind']=='plan' and view['printed_claim'].get('plan_level_or_form')!='roof':
        try: result['plan_references'] = drawing_views.page_references(page)
        except ValueError as error:
            if 'budget exceeded' not in str(error): raise
            return {**result, 'status': 'source_reference_budget_withheld', 'reason': str(error), 'plan_references': None}
        matrix = native_inverse(page); zone = shape(view['geometry'])
        for reference in result['plan_references']['references']:
            boxes = [pymupdf.Rect(reference[k]) for k in ('circle_bbox_page_points','corner_fill_bbox_page_points')]
            polygons = [Polygon([tuple(p*matrix) for p in (b.tl,b.tr,b.br,b.bl)]) for b in boxes]
            key = 'whole_view_reference_sha256' if all(zone.covers(p) for p in polygons) else 'crossing_view_reference_sha256'
            result[key].append(digest(reference))
    number = view['printed_claim'].get('view_number')
    if (identity and screen['status']=='raster_consistent_candidate' and type(number) is int
            and view['printed_claim']['view_kind']=='elevation'):
        result['view_key_candidate'] = [identity['project'], identity['sheet'], number]
    return result


def review(page, view, gap_review, *, max_checks=100000):
    bounded_work(max_checks)
    result = {'version': VERSION, 'status': 'not_a_floor_plan', 'labels': [], 'gap_links': [],
              'association_checks': 0,
              'physical_building_identity_verified': False, 'selected_physical_footprint_id': None,
              'world_geometry_additions': 0}
    claim = view['printed_claim']
    if claim['view_kind']!='plan' or claim.get('plan_level_or_form')=='roof': return result
    if gap_review['status']!='whole_view_source_endcap_gaps_only':
        return {**result, 'status': 'source_plan_gaps_required'}
    if page is None: return {**result, 'status': 'original_source_page_required'}
    traces = page.get_texttrace()
    if len(traces)>10000 or sum(len(t['chars']) for t in traces)>500000:
        return {**result, 'status': 'building_scope_budget_withheld', 'reason': 'source_text_budget'}
    matrix = native_inverse(page); inverse = ~matrix; scope = shape(view['geometry'])
    zone = affine_transform(scope, affine(inverse)); labels = []
    for run in label_runs(traces):
        text = ''.join(chr(c[0]) for c in run['chars']).strip()
        if not NAME.fullmatch(text): continue
        rect = pymupdf.Rect(run['bbox']); polygon = Polygon([tuple(p*matrix) for p in (rect.tl,rect.tr,rect.br,rect.bl)])
        if not scope.covers(polygon): continue
        labels.append((run, text, polygon))
        if len(labels)>MAX_LABELS:
            return {**result, 'status': 'building_scope_budget_withheld', 'reason': 'named_label_budget'}
    if not labels: return {**result, 'status': 'no_supported_named_building_labels'}
    try: edges = plan_elevation_edges.straight_edges(page, view['document_sha256'], view['page'])
    except ValueError as error:
        if 'budget exceeded' not in str(error): raise
        return {**result, 'status': 'building_scope_budget_withheld', 'reason': str(error)}
    fills = gap_review['page_fill_recovery']['candidates']; factor = view['nominal_metres_per_pdf_point']
    for run, text, polygon in labels:
        row = {'id': digest([VERSION, view['id'], run['trace_indices'], run['character_indices']]),
            'text': text, 'trace_indices': run['trace_indices'], 'character_indices': run['character_indices'],
            'geometry_pdf_native': mapping(polygon),
            'glyph_screen': screen_architectural_span(page, run, zoom=24 if run['size']<4 else 6),
            'source_only_enclosure_review': None, 'candidates': [], 'whole_label_crossing_candidate_ids': [],
            'scope_crossing_candidate_ids': [],
            'status': 'label_glyph_screen_withheld'}
        if row['glyph_screen']['status']=='raster_consistent_candidate':
            rect = pymupdf.Rect(run['bbox']); seed = list((rect.tl+rect.br)*.5)
            source = footprint_hypotheses.propose(edges, fills, [], seed, list(zone.bounds),
                                                  options={'max_checks': max_checks})
            if source['status']=='hypothesis_budget_withheld':
                return {**result, 'status': 'building_scope_budget_withheld', 'reason': source['reason'],
                        'labels': [], 'gap_links': []}
            row['source_only_enclosure_review'] = source
            for candidate in source['candidates']:
                native = affine_transform(shape(candidate['geometry']), affine(matrix))
                if not scope.covers(native):
                    row['scope_crossing_candidate_ids'].append(candidate['id']); continue
                if not native.contains(polygon):
                    row['whole_label_crossing_candidate_ids'].append(candidate['id']); continue
                row['candidates'].append({'id': candidate['id'], 'source_candidate_sha256': digest(candidate),
                    'geometry_pdf_native': mapping(native), 'source_hole_count': len(native.interiors),
                    'physical_footprint_verified': False})
                for gap in gap_review['gaps']:
                    result['association_checks'] += 1
                    if result['association_checks']>max_checks:
                        return {**result, 'status': 'building_scope_budget_withheld',
                                'reason': 'gap_association_work_budget', 'labels': [], 'gap_links': []}
                    corridor = shape(gap['geometry_pdf_native']); fraction = native.intersection(corridor).area/corridor.area
                    if fraction <= 0: continue
                    result['gap_links'].append({'label_id': row['id'], 'enclosure_id': candidate['id'],
                        'source_gap_id': gap['id'], 'source_gap_sha256': gap['source_gap_sha256'],
                        'corridor_overlap_area_fraction': fraction,
                        'physical_building_assignment_verified': False})
            row['status'] = 'whole_label_source_enclosure_candidates' if row['candidates'] else 'no_whole_label_source_enclosure'
        result['labels'].append(row)
    result.update(status='named_source_enclosure_candidates_only', source_edges_sha256=digest(edges),
                  source_fills_sha256=digest(fills), nominal_metres_per_pdf_point=factor)
    return result


def link(inventories, width_links, *, max_checks=100000):
    bounded_work(max_checks)
    result = {'version': VERSION, 'status': 'numbered_source_facade_candidates_only',
        'frames': [], 'projected_gaps': [], 'width_links': [], 'checks': 0,
        'physical_building_identity_verified': False, 'position_alignment_verified': False,
        'elevation_facade_origin_status': 'independent_elevation_facade_origin_required',
        'world_geometry_additions': 0, 'training_labels_generated': 0,
        'source_width_links_sha256': digest(width_links),
        'source_inventory_sha256': {v['view_id']: digest(v) for v in inventories},
        'recipe': {'maximum_axis_difference_degrees': 5., 'maximum_gap_plane_offset_nominal_m': .25,
                   'gap_assignment_basis': 'positive_exact_corridor_overlap_with_whole_label_source_enclosure',
                   'position_basis': 'uncorrected_nominal_plan_projection', 'max_checks': max_checks}}
    if len(inventories)>32 or len(result['source_inventory_sha256'])!=len(inventories):
        raise ValueError('Bounded unique source views required')
    def charge(n=1):
        result['checks'] += n
        if result['checks']>max_checks: raise OverflowError('facade_link_work_budget')
    def hold(reason):
        return {**result, 'status': 'building_facade_budget_withheld', 'reason': reason,
                'frames': [], 'projected_gaps': [], 'width_links': []}
    if width_links['status']!='nominal_width_links_only':
        return {**result, 'status': 'source_width_links_required'}
    widths = {}
    for row in width_links['matches']:
        widths.setdefault((row['plan_view_id'],row['source_gap_id'],row['elevation_view_id']), []).append(row)
    targets = {}
    for view in inventories:
        key = view['drawing_reference_review']['view_key_candidate']
        if key is not None: targets.setdefault(tuple(key), []).append(view['view_id'])
    try:
        for plan in inventories:
            scope = plan['building_scope_review']; refs = plan['drawing_reference_review']['plan_references']
            if scope['status']!='named_source_enclosure_candidates_only' or refs is None: continue
            factor = plan['nominal_metres_per_pdf_point']
            matrix = pymupdf.Matrix(plan['plan_gap_review']['unrotated_mupdf_to_pdf_native_matrix'])
            gap_lookup = {g['id']: g for g in plan['plan_gap_review']['gaps']}
            for label in scope['labels']:
                for candidate in label['candidates']:
                    polygon = shape(candidate['geometry_pdf_native'])
                    for reference in refs['references']:
                        charge()
                        if reference['status']!='unverified_native_view_reference_candidate': continue
                        if digest(reference) not in plan['drawing_reference_review']['whole_view_reference_sha256']: continue
                        key = reference.get('target_view_key_candidate')
                        if key is None: continue
                        circle = pymupdf.Rect(reference['circle_bbox_page_points']); corner = pymupdf.Rect(reference['corner_fill_bbox_page_points'])
                        marker = {'center_pdf_native': list((circle.tl+circle.br)*.5*matrix),
                                  'corner_center_pdf_native': list((corner.tl+corner.br)*.5*matrix)}
                        charge(len(polygon.exterior.coords))
                        frame_review = plan_elevation_correspondence.marker_frames(polygon, marker, factor)
                        record = {'plan_view_id': plan['view_id'], 'label_id': label['id'], 'enclosure_id': candidate['id'],
                            'source_reference_sha256': digest(reference), 'marker': marker,
                            'target_view_key_candidate': key, 'target_elevation_view_ids': targets.get(tuple(key), []),
                            'frame_review': frame_review, 'physical_view_association_verified': False}
                        record['id'] = digest([VERSION, record]); result['frames'].append(record)
                        for frame in frame_review['frames']:
                            axis = frame['diagnostic_axis']; normal = (-axis[1], axis[0]); a = frame['source_native_endpoints'][0]
                            for assignment in scope['gap_links']:
                                charge()
                                if assignment['label_id']!=label['id'] or assignment['enclosure_id']!=candidate['id']: continue
                                gap = gap_lookup[assignment['source_gap_id']]; points = gap['gap_endpoints_pdf_native']
                                delta = [points[1][i]-points[0][i] for i in (0,1)]; length = math.hypot(*delta)
                                alignment = abs(sum(delta[i]/length*axis[i] for i in (0,1)))
                                offset = max(abs(sum((p[i]-a[i])*normal[i] for i in (0,1))) for p in points)*factor
                                if alignment<math.cos(math.radians(5)) or offset>.25: continue
                                projection = {'facade_record_id': record['id'], 'frame_id': frame['id'],
                                    'plan_view_id': plan['view_id'], 'label_id': label['id'], 'enclosure_id': candidate['id'],
                                    'source_gap_id': gap['id'], 'maximum_gap_plane_offset_nominal_m': offset,
                                    'axis_alignment_cosine': alignment,
                                    'nominal_plan_position_interval_m': sorted(sum(p[i]*axis[i] for i in (0,1))*factor-frame['projection_min_m'] for p in points),
                                    'physical_opening_verified': False, 'position_alignment_verified': False}
                                projection['id'] = digest([VERSION, projection]); result['projected_gaps'].append(projection)
                                for target in record['target_elevation_view_ids']:
                                    for width in widths.get((plan['view_id'],gap['id'],target), []):
                                        charge()
                                        result['width_links'].append({'projection_id': projection['id'],
                                            'source_width_link_id': width['id'], 'source_width_link_sha256': digest(width),
                                            'elevation_view_id': target, 'residual_family_id': width['residual_family_id'],
                                            'target_view_multiplicity': len(record['target_elevation_view_ids']),
                                            'physical_correspondence_verified': False, 'position_alignment_verified': False})
        result['counts'] = {'marker_enclosure_reviews': len(result['frames']),
            'source_facing_frames': sum(len(r['frame_review']['frames']) for r in result['frames']),
            'projected_gap_hypotheses': len(result['projected_gaps']), 'reference_scoped_width_links': len(result['width_links']),
            'linked_residual_families': len({r['residual_family_id'] for r in result['width_links']})}
        return result
    except OverflowError as error: return hold(str(error))
