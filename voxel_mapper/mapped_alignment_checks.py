"""Automatic map consistency checks; never independent survey registration."""
import math
import numpy as np
from .boundary_registration import similarity

VERSION = 'held-out-map-alignment-v1'


def check(objects, references, hypotheses, *, expected_scale=None,
          tolerance_m=1., min_iou=.85, scale_tolerance=.01, search_flags=()):
    from .mapped_sheet_placement import placed
    for value, lower, upper in ((tolerance_m, 0, 1), (min_iou, .5, 1), (scale_tolerance, 0, .02)):
        if type(value) not in (int, float) or not math.isfinite(value) or not lower < value <= upper:
            raise ValueError('Invalid held-out map thresholds')
    if expected_scale is not None and (type(expected_scale) not in (int, float)
            or not math.isfinite(expected_scale) or not 0 < expected_scale <= 10000*.0254/72):
        raise ValueError('Bounded printed map scale required')
    if len(hypotheses) > 12 or len(objects) > 20000 or len(references) > 5000:
        raise ValueError('Held-out map input budget exceeded')
    by_id = {o['candidate_id']: o['geometry'] for o in objects}
    refs = {r['id']: r['geometry'] for r in references}
    if len(by_id) != len(objects) or len(refs) != len(references):
        raise ValueError('Unique held-out map identities required')
    from .footprint_matching import descriptor
    for geometry in list(by_id.values())+list(refs.values()):
        descriptor(geometry)
    reviews = []
    for hypothesis in hypotheses:
        supports = hypothesis['supports']; reasons = []; checks = []
        if expected_scale is None: reasons.append('printed_scale_missing_or_ambiguous')
        if not 5 <= len(supports) <= 256: reasons.append('requires_five_to_256_distinct_map_landmarks')
        pairs = [(s['candidate_id'], s['reference_id']) for s in supports]
        if (len({a for a, _ in pairs}) != len(pairs) or len({b for _, b in pairs}) != len(pairs)
                or any(a not in by_id or b not in refs for a, b in pairs)):
            reasons.append('invalid_or_reused_map_landmarks')
        if not reasons:
            if any(by_id[a].geom_type != 'Polygon' or refs[b].geom_type != 'Polygon' for a,b in pairs):
                reasons.append('polygon_map_landmarks_required')
            for i,(a,b) in enumerate(pairs):
                for c,d in pairs[:i]:
                    if any(left.intersection(right).area/min(left.area,right.area) > .1
                           for left,right in ((by_id[a],by_id[c]),(refs[b],refs[d]))):
                        reasons.append('overlapping_map_landmarks'); break
                if reasons: break
        if not reasons:
            local = np.array([by_id[a].centroid.coords[0] for a, _ in pairs])
            target = np.array([refs[b].centroid.coords[0] for _, b in pairs])
            for i, (candidate_id, reference_id) in enumerate(pairs):
                # The held-out object's geometry and centre never enter this fit.
                a, b = np.delete(local, i, axis=0), np.delete(target, i, axis=0)
                if np.linalg.matrix_rank(a-a.mean(axis=0)) < 2 or np.linalg.matrix_rank(b-b.mean(axis=0)) < 2:
                    reasons.append('degenerate_held_out_fit'); break
                matrix, translation, scale, _ = similarity(a, b)
                fit = {'matrix': matrix, 'translation_m': translation}
                polygon = placed(by_id[candidate_id], fit); reference = refs[reference_id]
                iou = polygon.intersection(reference).area/polygon.union(reference).area
                error = polygon.boundary.hausdorff_distance(reference.boundary)
                scale_error = abs(scale/expected_scale-1)
                passed = (iou >= min_iou and error <= tolerance_m and scale_error <= scale_tolerance
                          and len(polygon.interiors) == len(reference.interiors))
                checks.append({'candidate_id': candidate_id, 'reference_id': reference_id,
                    'fit_landmark_ids': [s['candidate_id'] for j, s in enumerate(supports) if j != i],
                    'intersection_over_union': iou, 'boundary_error_m': error,
                    'relative_printed_scale_error': scale_error, 'passed': passed})
            if any(not row['passed'] for row in checks): reasons.append('held_out_boundary_or_scale_disagreement')
        reviews.append({'status': 'map_consistent_candidate' if not reasons else 'withheld',
                        'reasons': reasons, 'held_out_checks': checks})
    blockers = []
    if len(hypotheses) != 1: blockers.append('requires_one_unambiguous_map_hypothesis')
    if 'seed_fit_budget_exhausted' in search_flags: blockers.append('map_search_budget_exhausted')
    qualified = len(reviews) == 1 and reviews[0]['status'] == 'map_consistent_candidate' and not blockers
    return {'version': VERSION, 'status': 'map_consistent_candidate' if qualified else 'withheld',
            'expected_metres_per_pdf_point': expected_scale, 'tolerance_m': tolerance_m,
            'min_iou': min_iou, 'scale_tolerance': scale_tolerance,
            'blockers': blockers, 'hypotheses': reviews, 'registration_verified': False,
            'physical_identity_verified': False, 'independent_survey_checkpoints': 0,
            'world_geometry_additions': 0,
            'limitations': ['Held-out correspondences were discovered from the same map and drawing.',
                           'Passing checks is map consistency evidence, not independently surveyed registration.']}


def printed_scale_review(pdf, page):
    """Screen exact native scale labels, including split CAD text traces."""
    import pymupdf
    from .ordinary_surfaces import label_runs
    from .glyph_visibility import screen_span
    from .drawing_registration_bridge import SCALE
    labels = []; denominators = set(); visible = set()
    with pymupdf.open(pdf) as document:
        if not 1 <= page <= len(document) or len(document) > 1000:
            raise ValueError('Bounded map scale page required')
        native = document[page-1]; traces = native.get_texttrace()
        if len(traces) > 10000 or sum(len(t['chars']) for t in traces) > 500000:
            raise ValueError('Map scale text budget exceeded')
        for run in label_runs(traces):
            text = ''.join(chr(c[0]) for c in run['chars']).strip()
            match = SCALE.fullmatch(text)
            if not match or not 1 <= int(match[1]) <= 10000: continue
            if len(labels) >= 16: raise ValueError('Map scale label budget exceeded')
            denominator = int(match[1]); denominators.add(denominator)
            screen = screen_span(native, run, zoom=24 if run['size'] < 4 else 6)
            if screen['status'] == 'raster_consistent_candidate': visible.add(denominator)
            labels.append({'text': text, 'denominator': denominator, 'bbox_page_points': list(run['bbox']),
                           'trace_indices': run['trace_indices'], 'character_indices': run['character_indices'],
                           'glyph_screen': screen})
    usable = len(denominators) == 1 and denominators <= visible
    return {'status': 'one_visible_printed_scale' if usable else 'withheld_missing_ambiguous_or_unverified_scale',
            'denominators': sorted(denominators), 'labels': labels,
            'expected_metres_per_pdf_point': next(iter(denominators))*.0254/72 if usable else None}


def printed_scales(pdf, page):
    review = printed_scale_review(pdf, page)
    return review['denominators'] if review['status'] == 'one_visible_printed_scale' else []
