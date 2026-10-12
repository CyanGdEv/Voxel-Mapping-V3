"""Automatic map consistency checks; never independent survey registration."""
import math
import re
import numpy as np
from shapely.affinity import translate
from .boundary_registration import similarity

VERSION = 'held-out-map-alignment-v4'


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
                # Diagnostic centering isolates shape disagreement from the
                # held-out centre error. It never changes the evaluated fit.
                centroid_error=polygon.centroid.distance(reference.centroid)
                delta=np.asarray(reference.centroid.coords[0])-np.asarray(polygon.centroid.coords[0])
                centered=translate(polygon,*delta)
                centered_error=centered.boundary.hausdorff_distance(reference.boundary)
                centered_iou=centered.intersection(reference).area/centered.union(reference).area
                passed = (iou >= min_iou and error <= tolerance_m and scale_error <= scale_tolerance
                          and len(polygon.interiors) == len(reference.interiors))
                failed=[]
                if iou<min_iou:failed.append('intersection_over_union')
                if error>tolerance_m:failed.append('boundary_error_m')
                if scale_error>scale_tolerance:failed.append('relative_printed_scale_error')
                if len(polygon.interiors)!=len(reference.interiors):failed.append('hole_topology')
                checks.append({'candidate_id': candidate_id, 'reference_id': reference_id,
                    'fit_landmark_ids': [s['candidate_id'] for j, s in enumerate(supports) if j != i],
                    'intersection_over_union': iou, 'boundary_error_m': error,
                    'relative_printed_scale_error': scale_error, 'passed': passed,
                    'failed_thresholds':failed,
                    'boundary_discrepancy':{'centroid_error_m':centroid_error,
                        'centroid_aligned_boundary_error_m':centered_error,
                        'centroid_aligned_intersection_over_union':centered_iou,
                        'source_to_map_area_ratio':polygon.area/reference.area,
                        'diagnostic_only':True,'registration_verified':False}})
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


def fragmented_scale_runs(runs):
    """Join only adjacent singleton glyphs of one native font and baseline.

    CAD sometimes paints each glyph twice. Coincident duplicates retain all
    source references; conflicting characters cannot form a scale caption.
    """
    groups={}
    for run in runs:
        if len(run['chars'])!=1 or tuple(run['dir'])!=(1.,0.):continue
        char=run['chars'][0]
        key=(run['font'],round(run['size'],3),round(char[2][1],2),run.get('type'),run.get('opacity'),str(run.get('color')),run.get('layer'))
        groups.setdefault(key,[]).append(run)
    output=[]
    for group in groups.values():
        ordered=sorted(group,key=lambda r:r['chars'][0][2][0]);chains=[];chain=[]
        for run in ordered:
            char=run['chars'][0]
            if chain:
                previous=chain[-1]['chars'][0]
                if abs(char[2][0]-previous[2][0])<.02 and char[0]==previous[0]:
                    chain[-1]={**chain[-1],'trace_indices':chain[-1]['trace_indices']+run['trace_indices'],
                               'character_indices':chain[-1]['character_indices']+run['character_indices']}
                    continue
                gap=char[3][0]-previous[3][2]
                if gap<-.1 or gap>run['size']*.25:
                    chains.append(chain);chain=[]
            chain.append(run)
        if chain:chains.append(chain)
        for chain in chains:
            text=''.join(chr(r['chars'][0][0]) for r in chain)
            if '@' not in text or len(chain)>64:continue
            output.append({**chain[0],'chars':[r['chars'][0] for r in chain],
                'bbox':[min(r['bbox'][0] for r in chain),min(r['bbox'][1] for r in chain),
                        max(r['bbox'][2] for r in chain),max(r['bbox'][3] for r in chain)],
                'trace_indices':[i for r in chain for i in r['trace_indices']],
                'character_indices':[i for r in chain for i in r['character_indices']]})
    return output


def printed_scale_review(pdf, page):
    """Screen exact native scale labels, including split CAD text traces."""
    import pymupdf
    from .ordinary_surfaces import label_runs
    from .glyph_visibility import screen_span
    from .drawing_registration_bridge import SCALE
    from .boundary_registration import file_hash
    digest = file_hash(pdf)
    labels = []; denominators = set(); visible = set(); unresolved = False
    paper_pattern = re.compile(r'^(?:Scale\s+)?1\s*[:/]\s*(\d{1,5})\s*@\s*(A[0-5])$',re.I)
    papers={'A0':(841,1189),'A1':(594,841),'A2':(420,594),'A3':(297,420),'A4':(210,297),'A5':(148,210)}
    with pymupdf.open(pdf) as document:
        if not 1 <= page <= len(document) or len(document) > 1000:
            raise ValueError('Bounded map scale page required')
        native = document[page-1]; traces = native.get_texttrace()
        # Unrotated effective dimensions include PDF UserUnit; crop changes are
        # deliberately withheld because they may hide a resized sheet.
        angle=native.rotation
        try:
            native.set_rotation(0)
            dimensions=sorted([native.rect.width*25.4/72,native.rect.height*25.4/72])
        finally:native.set_rotation(angle)
        cropped=native.cropbox!=native.mediabox
        unit_kind,unit_text=document.xref_get_key(native.xref,'UserUnit')
        unit=1. if unit_kind=='null' else float(unit_text)
        paper_matches=[name for name,size in papers.items() if all(abs(a-b)<=1.5 for a,b in zip(dimensions,size)) and not cropped]
        if len(traces) > 10000 or sum(len(t['chars']) for t in traces) > 500000:
            raise ValueError('Map scale text budget exceeded')
        runs=label_runs(traces)
        for run in runs+fragmented_scale_runs(runs):
            text = ''.join(chr(c[0]) for c in run['chars']).strip()
            match = SCALE.fullmatch(text)
            paper_match=paper_pattern.fullmatch(text)
            match=match or paper_match
            if not match or not 1 <= int(match[1]) <= 10000: continue
            if len(labels) >= 16: raise ValueError('Map scale label budget exceeded')
            denominator = int(match[1])
            applicable=paper_match is None or (len(paper_matches)==1 and paper_match[2].upper()==paper_matches[0])
            if paper_match is not None and len(paper_matches)!=1:unresolved=True
            if applicable:denominators.add(denominator)
            screen = screen_span(native, run, zoom=24 if run['size'] < 4 else 6)
            if applicable and screen['status'] == 'raster_consistent_candidate': visible.add(denominator)
            labels.append({'text': text, 'denominator': denominator, 'bbox_page_points': list(run['bbox']),
                           'trace_indices': run['trace_indices'], 'character_indices': run['character_indices'],
                           'glyph_screen': screen,'paper_size':paper_match[2].upper() if paper_match else None,'applicable_to_page':applicable})
    usable = unit==1 and not unresolved and len(denominators) == 1 and denominators <= visible
    if file_hash(pdf) != digest: raise ValueError('Scale source PDF changed during review')
    return {'status': 'one_visible_printed_scale' if usable else 'withheld_missing_ambiguous_or_unverified_scale',
            'document_sha256':digest,'page':page,'effective_page_dimensions_mm':dimensions,'matching_paper_sizes':paper_matches,'unresolved_paper_scale':unresolved,'pdf_user_unit':unit,'native_unit_supported':unit==1,
            'denominators': sorted(denominators), 'labels': labels,
            'expected_metres_per_pdf_point': next(iter(denominators))*.0254/72 if usable else None}


def printed_scales(pdf, page):
    review = printed_scale_review(pdf, page)
    return review['denominators'] if review['status'] == 'one_visible_printed_scale' else []
