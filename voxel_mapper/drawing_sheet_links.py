"""Printed-scale-normalised cross-sheet landmark proposals; review only."""
import hashlib
import json
import math
from shapely.affinity import scale
from shapely.geometry import shape
from .mapped_sheet_placement import propose
from .mapped_alignment_checks import check

VERSION = 'drawing-sheet-links-v1'


def link(source_records, target_records, source_scale_review, target_scale_review, *, max_seed_fits=512):
    """Find common outlines without claiming walls, roofs or geographic pose."""
    def collect(records, review):
        if (review.get('status') != 'one_visible_printed_scale'
                or type(review.get('expected_metres_per_pdf_point')) not in (int,float)
                or not math.isfinite(review['expected_metres_per_pdf_point'])
                or not 0 < review['expected_metres_per_pdf_point'] <= 10000*.0254/72):
            raise ValueError('Verified visible sheet scale required')
        if not records or len(records) > 20000: raise ValueError('Bounded nonempty sheet records required')
        identities = {(r['document_sha256'],r['page'],r['coordinate_frame']) for r in records}
        if len(identities) != 1 or next(iter(identities))[2] != 'pdf_native_points_y_up':
            raise ValueError('One native source page required')
        source_identity = next(iter(identities))
        if review.get('document_sha256') != source_identity[0] or review.get('page') != source_identity[1]:
            raise ValueError('Printed scale must bind the exact source page')
        output = {}; factor = review['expected_metres_per_pdf_point']
        for record in records:
            if record['geometry']['type'] != 'Polygon': continue
            if (record.get('rendering_status') != 'supported_straight_unclipped_polygon'
                    and record.get('extraction_kind') not in ('linework_boundaries','linework_envelopes')): continue
            if record.get('curve_approximation',{}).get('cubic_segments',0) or record.get('paint_reference_truncated'): continue
            if record['id'] in output: raise ValueError('Unique sheet geometry identities required')
            output[record['id']] = {'candidate_id':record['id'],'geometry':scale(shape(record['geometry']),factor,factor,origin=(0,0))}
        return list(output.values()), next(iter(identities)), factor
    objects, source_identity, source_factor = collect(source_records, source_scale_review)
    targets, target_identity, target_factor = collect(target_records, target_scale_review)
    if source_identity[:2] == target_identity[:2]: raise ValueError('Cross-sheet links require different source pages')
    refs = [{'id':o['candidate_id'],'geometry':o['geometry']} for o in targets]
    result = propose(objects,refs,max_seed_fits=max_seed_fits,min_iou=.85,tolerance_m=1.)
    review = check(objects,refs,result['hypotheses'],expected_scale=1.,search_flags=result['review_flags'])
    native_fits = [{'hypothesis_index':i,'matched_outlines':len(h['supports']),
                   'consistency_status':review['hypotheses'][i]['status'],
                   'matrix':[[v*source_factor/target_factor for v in row] for row in h['matrix']],
                   'translation_pdf_points':[v/target_factor for v in h['translation_m']],
                   'source_coordinate_frame':'pdf_native_points_y_up','target_coordinate_frame':'pdf_native_points_y_up'}
                  for i,h in enumerate(result['hypotheses'])]
    return {'version':VERSION,'status':'cross_sheet_consistent_candidate' if review['status']=='map_consistent_candidate' else 'withheld',
            'source_document_sha256':source_identity[0],'source_page':source_identity[1],
            'target_document_sha256':target_identity[0],'target_page':target_identity[1],
            'source_records_sha256':hashlib.sha256(json.dumps(source_records,sort_keys=True).encode()).hexdigest(),
            'target_records_sha256':hashlib.sha256(json.dumps(target_records,sort_keys=True).encode()).hexdigest(),
            'source_metres_per_pdf_point':source_factor,'target_metres_per_pdf_point':target_factor,
            'proposal':result,'alignment_checks':review,'native_sheet_transforms':native_fits,
            'registration_verified':False,'physical_identity_verified':False,'world_geometry_additions':0,
            'limitations':['Common outline geometry does not establish wall/roof/annotation identity.',
                           'Cross-sheet matches are not independent survey checkpoints.',
                           'No geographic alignment is propagated or accepted.']}
