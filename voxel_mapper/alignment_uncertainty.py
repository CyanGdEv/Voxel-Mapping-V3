"""Conditional horizontal error budgets for contextual similarity proposals.

This is a deterministic sensitivity calculation, not a confidence interval or
independent registration. Source centroids and the proposed model are fixed.
"""
import math
from numbers import Real
import numpy as np
from shapely.affinity import affine_transform
from shapely.geometry import MultiPoint, mapping, shape
from .reconstruction.registration import registration_domain

VERSION = 'contextual-horizontal-scope-v1'


def horizontal_scope(hypothesis, candidates, landmarks, *, tolerance_m=1.):
    """Assess complete candidate polygons inside a shared checked domain.

    Errors are summed, never averaged down for landmarks sharing a survey.
    A one-PDF-point attachment allowance is charged to each fit observation
    and each evaluated output point. Unknown parent budgets remain unknown.
    """
    if type(tolerance_m) not in (int, float) or not math.isfinite(tolerance_m) or not 0 < tolerance_m <= 1:
        raise ValueError('Horizontal tolerance must be finite and at most one metre')
    if len(candidates) > 64 or len(landmarks) > 1000:
        raise ValueError('Bounded contextual scope inventory required')
    result = {'version': VERSION, 'status': 'awaiting_parent_error_budgets',
              'registration_verified': False, 'world_geometry_additions': 0,
              'tolerance_m': tolerance_m, 'candidate_reviews': [],
              'limitations': ['Conditional on fixed source centroids, correct correspondence and similarity model',
                             'Not a statistical confidence interval or independent checkpoint validation',
                             'No source view, construction state, vertical datum or semantic acceptance']}
    objects = {c['id']: shape(c['geometry']) for c in candidates}
    refs = {r['id']: r for r in landmarks}
    supports = hypothesis['supports']
    if len(objects) != len(candidates) or len(refs) != len(landmarks) or not 3 <= len(supports) <= 64:
        raise ValueError('Distinct bounded scope identities required')
    if len({s['candidate_id'] for s in supports}) != len(supports) or len({s['reference_id'] for s in supports}) != len(supports):
        raise ValueError('Distinct scope correspondences required')
    scale = hypothesis['scale_metres_per_pdf_point']
    if isinstance(scale, bool) or not isinstance(scale, Real) or not math.isfinite(scale) or scale <= 0:
        raise ValueError('Finite positive contextual scale required')
    domains = []; budgets = []
    for support in supports:
        ref = refs[support['reference_id']]
        review = ref.get('registration')
        if not review or 'reference_and_attachment_error_budget_m' not in review:
            return result
        domain = registration_domain(review)
        budget = review['reference_and_attachment_error_budget_m']
        residual = support['centroid_error_m']
        if any(isinstance(v, bool) or not isinstance(v, Real) or not math.isfinite(v) or v < 0 for v in (budget, residual)):
            raise ValueError('Finite nonnegative parent budget and contextual residual required')
        if budget > review['tolerance_m']:
            raise ValueError('Parent error budget exceeds accepted registration tolerance')
        if not domain.buffer(1e-7).covers(shape(ref['feature']['geometry'])):
            raise ValueError('Parent landmark outside checked registration domain')
        domains.append(domain)
        budgets.append(budget + residual + scale)
    points = np.asarray([objects[s['candidate_id']].centroid.coords[0] for s in supports])
    origin = points.mean(axis=0); local = points - origin
    if np.linalg.matrix_rank(local, tol=1e-8) < 2:
        raise ValueError('Contextual supports must span an area')
    design = np.zeros((2 * len(local), 4))
    design[::2, 0] = local[:, 0]; design[::2, 1] = -local[:, 1]; design[::2, 2] = 1
    design[1::2, 0] = local[:, 1]; design[1::2, 1] = local[:, 0]; design[1::2, 3] = 1
    inverse = np.linalg.pinv(design)
    matrix = np.asarray(hypothesis['matrix'], dtype=float)
    translation = np.asarray(hypothesis['translation_m'], dtype=float)
    if matrix.shape != (2, 2) or translation.shape != (2,) or not np.isfinite(matrix).all() or not np.isfinite(translation).all():
        raise ValueError('Finite contextual transform required')
    contextual_domain = MultiPoint(points @ matrix.T + translation).convex_hull
    domain = contextual_domain
    for parent_domain in domains:
        domain = domain.intersection(parent_domain)
    reviews = []; vertex_count = 0
    for candidate in candidates:
        geometry = objects[candidate['id']]
        # The sensitivity norm is convex: its maximum is on the source hull.
        hull = geometry.convex_hull
        if hull.geom_type != 'Polygon' or not geometry.is_valid or geometry.is_empty:
            raise ValueError('Valid polygon scope candidate required')
        vertices = list(hull.exterior.coords)[:-1]; vertex_count += len(vertices)
        if vertex_count > 16384:
            return {**result, 'status': 'scope_budget_withheld', 'candidate_reviews': []}
        maximum = 0.
        for x, y in vertices:
            x -= origin[0]; y -= origin[1]
            evaluation = np.asarray([[x, -y, 1., 0.], [y, x, 0., 1.]]) @ inverse
            bound = scale + sum(float(np.linalg.norm(evaluation[:, 2*i:2*i+2], ord=2)) * b
                                for i, b in enumerate(budgets))
            maximum = max(maximum, bound)
        placed = affine_transform(geometry, [*matrix[0], *matrix[1], *translation])
        within = domain.buffer(1e-7).covers(placed)
        flags = []
        if not within: flags.append('outside_shared_checked_domain')
        if maximum > tolerance_m: flags.append('horizontal_error_budget_exceeded')
        reviews.append({'candidate_id': candidate['id'], 'within_checked_domain': within,
                        'conditional_horizontal_error_budget_m': maximum,
                        'review_flags': flags, 'registration_verified': False})
    return {**result, 'status': 'conditional_scope_assessed',
            'checked_domain': mapping(domain), 'candidate_reviews': reviews,
            'parent_landmark_ids': [s['reference_id'] for s in supports],
            'parent_observation_error_budgets_m': budgets}
