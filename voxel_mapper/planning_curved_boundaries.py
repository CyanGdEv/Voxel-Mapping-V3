"""Original closed curved paint boundaries for review, never physical surfaces.

Flattening supplies an explicitly bounded display approximation. Original
operators, fill rules and closure remain evidence; no endpoint is snapped and
no open curve is repaired. Symbols, trees and annotations remain unclassified.
"""
from concurrent.futures import CancelledError
import base64
import hashlib
from html import escape
import json
import math
import re

import pymupdf
from shapely.geometry import shape

from . import drawing_geometry, ordinary_surfaces
from .building_spec import digest
from .drawing_page_tools import native_inverse

VERSION = 'planning-closed-curved-boundaries-v1'
TOLERANCE_POINTS = .05
LIMITS = {'max_candidates': 500, 'max_points': 200000,
          'max_source_operators': 20000, 'max_source_control_points': 100000,
          'max_output_bytes': 8000000}


def _operators(path, inverse):
    """Lossless operator identities with coordinates in the native page frame."""
    def point(value):
        p = pymupdf.Point(value)*inverse
        if not all(math.isfinite(v) for v in p):
            raise ValueError('Finite original curve controls required')
        return list(p)
    result = []
    for item in path['items']:
        kind = item[0]
        if kind in ('l', 'c'):
            result.append({'operator': kind, 'points': [point(p) for p in item[1:]]})
        elif kind == 're':
            r = pymupdf.Rect(item[1])
            result.append({'operator': kind, 'points': [point(p) for p in (r.tl,r.tr,r.br,r.bl)],
                           'orientation': item[2]})
        elif kind == 'qu':
            q = pymupdf.Quad(item[1])
            result.append({'operator': kind, 'points': [point(p) for p in (q.ul,q.ur,q.lr,q.ll)]})
        else:
            raise ValueError('Supported original curve operators required')
    return result


def page_inventory(page, sha, number, *, options=None, cancelled=lambda: False):
    """Whole-page inventory independent of labels and unchanged surface recovery.

    All records are withheld on extraction/output/work quota failure. This
    inventory is deliberately not an ordinary source-outline inventory, and
    cannot authorize a building, surface, nominal layout or world placement.
    """
    options = {} if options is None else options
    if not isinstance(options,dict) or set(options)-set(LIMITS):
        raise ValueError('Known closed-curve review limits required')
    limits = {**LIMITS, **options}
    if (any(type(v) is not int or not 1 <= v <= LIMITS[k] for k,v in limits.items())
            or limits['max_output_bytes'] < 16384):
        raise ValueError('Lower-only closed-curve review limits required')
    if (not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha)
            or type(number) is not int or number < 1 or page.number+1 != number):
        raise ValueError('Original document hash and matching page required')
    def check():
        if cancelled():
            raise CancelledError('Closed curved boundary review cancelled')
    result = {'version': VERSION, 'document_sha256': sha, 'page': number,
        'coordinate_frame': 'pdf_native_points_y_up', 'limits': limits,
        'scope': 'whole_original_page_closed_curved_paint; not physical paths or plazas',
        'status': 'closed_curved_boundary_review', 'analysis_complete': True,
        'curve_tolerance_pdf_points': TOLERANCE_POINTS, 'records': [],
        'physical_identity_verified': False, 'topology_against_exact_curves_verified': False,
        'scale_verified': False, 'registration_verified': False,
        'world_placement_eligible': False, 'world_geometry_additions': 0,
        'training_labels_generated': 0}
    def fail(reason):
        result.update(status='closed_curved_boundary_review_withheld', analysis_complete=False,
                      reason=reason, records=[])
        # Oversized diagnostics must not defeat the output quota.
        if len(json.dumps(result,allow_nan=False).encode()) > limits['max_output_bytes']:
            result.pop('extraction',None)
        return result
    check()
    try:
        cache = ordinary_surfaces._source_page_cache(page)
        check()
        rows, extraction = drawing_geometry.extract_page(page,sha,number,
            _paths=cache['compact'], closed_curved_primitives_only=True,
            curve_tolerance_points=TOLERANCE_POINTS, max_paths=100000,
            max_candidates=limits['max_candidates'], max_total_points=limits['max_points'],
            regional_fallback=False)
        result['extraction'] = extraction
        result['source_content_sha256'] = cache['source_content_sha256']
        if extraction['status'] != 'unplaced_geometry_candidates':
            return fail('complete_closed_curve_extraction_required')
        if any(count and 'budget' in reason.lower()
               for reason,count in extraction.get('rejections',{}).items()):
            return fail('complete_closed_curve_primitive_budgets_required')
        inverse = native_inverse(page); operators = controls = 0; covered = white = 0
        for row in sorted(rows,key=lambda r:r['id']):
            check()
            if row.get('paint_reference_truncated'):
                return fail('complete_closed_curve_paint_references_required')
            geometry = shape(row['geometry'])
            error = row['curve_approximation']['chord_error_bound_pdf_points']
            boundary_envelope = geometry.boundary.buffer(error) if error else geometry.boundary
            references = row['paint_references']
            originals = [cache['paths'][r['ordinal']] for r in references]
            seqs = [p.get('seqno',-1) for p in originals]
            if any(s < 0 for s in seqs):
                return fail('original_curve_paint_sequence_required')
            overlaps = ([] if cache['fill_index'] is None else
                        cache['fill_index'].query(boundary_envelope,predicate='intersects'))
            if any(cache['later_fills'][int(i)][0] > max(seqs) for i in overlaps):
                covered += 1; continue
            if all(p['type']=='f' and p.get('fill') and min(p['fill'])>.98 for p in originals):
                white += 1; continue
            witnesses = []
            for reference, original in zip(references,originals):
                check()
                count = len(original['items'])
                operators += count
                if operators > limits['max_source_operators']:
                    return fail('closed_curve_source_operator_budget_exceeded')
                source_ops = _operators(original,inverse)
                controls += sum(len(op['points']) for op in source_ops)
                if controls > limits['max_source_control_points']:
                    return fail('closed_curve_control_point_budget_exceeded')
                witness = {'ordinal':reference['ordinal'], 'subpath':reference['subpath'],
                    'paint_sequence':original['seqno'], 'paint_type':original['type'],
                    'explicit_close_path':bool(original.get('closePath')),
                    'fill_rule':'even_odd' if original.get('even_odd') else 'nonzero',
                    'fill':original.get('fill'), 'stroke':original.get('color'),
                    'fill_opacity':original.get('fill_opacity',1),
                    'stroke_opacity':original.get('stroke_opacity',1),
                    'stroke_style':reference['stroke_style'],
                    'operators_pdf_native':source_ops,
                    'curve_approximation':reference['curve_approximation']}
                witnesses.append(witness)
            record = {'candidate_id':row['id'], 'candidate':row,
                'source_record_sha256':digest(row), 'source_paint_witnesses':witnesses,
                'source_paint_witnesses_sha256':digest(witnesses),
                'status':'unclassified_closed_curve_review_only',
                'native_metrics':{'area_square_pdf_points':geometry.area,
                    'perimeter_pdf_points':geometry.length,'hole_count':len(geometry.interiors),
                    'bounds_pdf_points':list(geometry.bounds)},
                'curve_approximation':row['curve_approximation'],
                'physical_identity_verified':False, 'world_placement_eligible':False,
                'world_geometry_additions':0}
            result['records'].append(record)
            if len(json.dumps(result,allow_nan=False).encode()) > limits['max_output_bytes']:
                return fail('closed_curve_output_budget_exceeded')
        check()
        if hashlib.sha256(page.read_contents()).hexdigest() != cache['source_content_sha256']:
            return fail('original_curve_page_changed')
        result.update(covered_boundaries_withheld=covered, white_fills_withheld=white,
                      source_operator_count=operators,source_control_point_count=controls)
        if len(json.dumps(result,allow_nan=False).encode()) > limits['max_output_bytes']:
            return fail('closed_curve_output_budget_exceeded')
        return result
    except (ValueError,RuntimeError,OverflowError) as error:
        return fail(str(error)[:512])


def write_overlay(inventory, preview, path):
    """Keep curve review separate from accepted-feature and straight overlays."""
    if not inventory or not inventory['analysis_complete'] or not inventory['records']:
        return None
    background=base64.b64encode((path.parent/preview['file']).read_bytes()).decode('ascii')
    width,height=preview['size_pixels'];matrix=pymupdf.Matrix(preview['pdf_native_to_pixels'])
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
           'role="img" aria-label="Unclassified curved source boundaries; review only">',
           f'<image href="data:image/png;base64,{background}" width="{width}" height="{height}"/>']
    for record in inventory['records']:
        commands=[]
        for ring in record['candidate']['geometry']['coordinates']:
            projected=[pymupdf.Point(*p)*matrix for p in ring]
            commands.append('M'+' L'.join(f'{p.x:.4f},{p.y:.4f}' for p in projected)+' Z')
        title=escape('Unclassified closed curve '+record['candidate_id']+'; holes '+
            str(record['native_metrics']['hole_count'])+'; PDF-point chord error '+
            str(record['curve_approximation']['chord_error_bound_pdf_points']))
        parts.append('<path fill="none" stroke="#c00090" stroke-width="1.5" '
            'vector-effect="non-scaling-stroke" data-source-candidate-id="'+record['candidate_id']+
            '" d="'+' '.join(commands)+'"><title>'+title+'</title></path>')
    parts.append('</svg>');data=''.join(parts).encode()
    if len(data)>16000000:
        raise ValueError('Closed curve overlay byte budget exceeded')
    path.write_bytes(data)
    return {'file':path.name,'sha256':hashlib.sha256(data).hexdigest(),
            'records':len(inventory['records']),'physical_geometry_verified':False,
            'pdf_native_to_pixels':preview['pdf_native_to_pixels']}
