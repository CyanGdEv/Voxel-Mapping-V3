"""Independent-checkpoint review of a planar similarity registration."""
import math
from copy import deepcopy
import numpy as np

VERSION = 'independent-registration-v2'
REPLAY_EPSILON_M = 1e-7


def review_registration(controls, checkpoints, *, tolerance_m=1., expected_scale=1., scale_tolerance=.02):
    """Local metric XY to target projected metre XY; no height/datum inference.

    A fit is a hypothesis until at least two independent checkpoints agree.
    Caller must establish landmark identity, target CRS and survey provenance.
    """
    if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (tolerance_m, expected_scale, scale_tolerance))
            or tolerance_m<=0 or expected_scale<=0 or not 0<=scale_tolerance<1):
        raise ValueError('Invalid registration tolerances')
    controls, checkpoints = deepcopy(controls), deepcopy(checkpoints)
    def pairs(rows, minimum):
        if not isinstance(rows,list) or len(rows)<minimum or len(rows)>1000:
            raise ValueError('Insufficient or excessive registration points')
        ids=[];local=[];target=[]
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not row['id'] or row['id'] in ids:raise ValueError('Unique control identity required')
            for key in ('local', 'target'):
                point = row.get(key)
                if (not isinstance(point, (list, tuple)) or len(point) != 2
                        or any(type(v) not in (int, float) or not math.isfinite(v) for v in point)):
                    raise ValueError('Finite numeric 2D registration pairs required')
            ids.append(row['id']);local.append(row['local']);target.append(row['target'])
        a,b=np.asarray(local,dtype=float),np.asarray(target,dtype=float)
        if a.shape!=(len(rows),2) or b.shape!=a.shape or not np.isfinite(a).all() or not np.isfinite(b).all():
            raise ValueError('Finite 2D registration pairs required')
        if len(set(map(tuple,a)))!=len(a) or len(set(map(tuple,b)))!=len(b):
            raise ValueError('Repeated registration point coordinates')
        return ids,a,b
    ids,a,b=pairs(controls,3)
    centered=a-a.mean(axis=0)
    if np.linalg.matrix_rank(centered)<2:raise ValueError('Controls must span an area')
    # Orientation-preserving similarity: X=ax-by+tx, Y=bx+ay+ty.
    design=np.zeros((2*len(a),4));design[::2,0]=a[:,0];design[::2,1]=-a[:,1];design[::2,2]=1
    design[1::2,0]=a[:,1];design[1::2,1]=a[:,0];design[1::2,3]=1
    coefficient=np.linalg.lstsq(design,b.reshape(-1),rcond=None)[0]
    s,c,tx,ty=coefficient;scale=math.hypot(s,c)
    matrix=np.array([[s,-c],[c,s]])
    def errors(local,target):return np.linalg.norm(local@matrix.T+[tx,ty]-target,axis=1)
    fitting=errors(a,b);reasons=[];independent=[];checked=np.array([])
    if checkpoints:
        independent,q,r=pairs(checkpoints,2)
        if set(ids)&set(independent) or set(map(tuple,a))&set(map(tuple,q)) or set(map(tuple,b))&set(map(tuple,r)):
            raise ValueError('Checkpoints must be independent of controls')
        checked=errors(q,r)
        if np.linalg.matrix_rank(np.vstack((a,q))-np.vstack((a,q)).mean(axis=0))<2:raise ValueError('Registration has no spatial extent')
        if float(checked.max())>tolerance_m:reasons.append('independent_checkpoint_error')
    else:reasons.append('independent_checkpoints_missing')
    if fitting.max()>tolerance_m:reasons.append('control_fit_error')
    if abs(scale/expected_scale-1)>scale_tolerance:reasons.append('unexpected_scale')
    def result_error(values):
        return {'rms_m':float(np.sqrt(np.mean(values**2))),'max_m':float(values.max())} if len(values) else None
    return {'version': VERSION, 'status':'accepted_horizontal_fit' if not reasons else 'withheld','reasons':reasons,
            'fit_parameters': {'expected_scale': expected_scale, 'scale_tolerance': scale_tolerance},
            'matrix':matrix.tolist(),'translation_m':[float(tx),float(ty)],'scale':scale,
            'rotation_degrees':math.degrees(math.atan2(c,s)),
            'control_pairs':controls,'checkpoint_pairs':checkpoints,'controls':ids,'checkpoints':independent,'control_error':result_error(fitting),
            'checkpoint_error':result_error(checked),'tolerance_m':tolerance_m,
            'limitations':['Horizontal fit only; no vertical datum or height acceptance',
                           'Landmark identity, source provenance and CRS must be reviewed separately']}


def require_accepted_review(report):
    """Replay saved point evidence and require this exact pose; never repair it."""
    if not isinstance(report,dict) or report.get('status')!='accepted_horizontal_fit':
        raise ValueError('Registration not independently accepted')
    controls=report.get('controls',[]);checks=report.get('checkpoints',[])
    error=report.get('checkpoint_error')
    if not isinstance(controls,list) or not isinstance(checks,list) or not all(isinstance(v,str) for v in controls+checks):
        raise ValueError('Registration point identities malformed')
    if len(controls)<3 or len(checks)<2 or len(set(controls))!=len(controls) or len(set(checks))!=len(checks) or set(controls)&set(checks) or not isinstance(error,dict):
        raise ValueError('Independent registration checks missing')
    tolerance=report.get('tolerance_m',0);maximum=error.get('max_m',math.inf)
    if not isinstance(tolerance,(int,float)) or not isinstance(maximum,(int,float)) or not math.isfinite(tolerance) or tolerance<=0 or not math.isfinite(maximum) or maximum>tolerance:
        raise ValueError('Registration checkpoint tolerance exceeded')
    if report.get('version') != VERSION or not isinstance(report.get('fit_parameters'), dict):
        raise ValueError('Registration evidence requires replay from original control/checkpoint pairs')
    settings = report['fit_parameters']
    if set(settings) != {'expected_scale', 'scale_tolerance'}:
        raise ValueError('Registration fit parameters are missing or changed')
    try:
        replay = review_registration(report['control_pairs'], report['checkpoint_pairs'],
            tolerance_m=tolerance, expected_scale=settings['expected_scale'], scale_tolerance=settings['scale_tolerance'])
    except (KeyError, TypeError, ValueError, np.linalg.LinAlgError) as error:
        raise ValueError('Registration point evidence cannot be replayed: ' + str(error)) from error
    if (replay['status'] != 'accepted_horizontal_fit' or report.get('reasons') != []
            or controls != replay['controls'] or checks != replay['checkpoints']):
        raise ValueError('Registration point evidence no longer passes independent review')
    def numeric(value, field):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('Invalid registration ' + field)
        return value
    try:
        if (not isinstance(report['matrix'], list) or len(report['matrix']) != 2
                or any(not isinstance(row, list) or len(row) != 2 for row in report['matrix'])
                or not isinstance(report['translation_m'], list) or len(report['translation_m']) != 2):
            raise ValueError('Finite 2D registration transform required')
        for value in [v for row in report['matrix'] for v in row] + report['translation_m']:
            numeric(value, 'transform')
        matrix = np.asarray(report['matrix'], dtype=float)
        translation = np.asarray(report['translation_m'], dtype=float)
    except (KeyError, ValueError, TypeError) as error:
        raise ValueError('Invalid registration transform') from error
    if (matrix.shape != (2, 2) or translation.shape != (2,) or
            not np.isfinite(matrix).all() or not np.isfinite(translation).all()):
        raise ValueError('Invalid registration transform')
    # Compare the serialized pose at every evidence point, with an absolute metre
    # bound. Relative tolerances at large eastings would permit metre-scale drift.
    pairs = report['control_pairs'] + report['checkpoint_pairs']
    local = np.asarray([p['local'] for p in pairs], dtype=float)
    stored = local @ matrix.T + translation
    refitted = local @ np.asarray(replay['matrix']).T + replay['translation_m']
    residuals = np.linalg.norm(stored - np.asarray([p['target'] for p in pairs]), axis=1)
    if not np.isfinite(residuals).all() or float(residuals.max()) > tolerance:
        raise ValueError('Serialized registration transform exceeds control/checkpoint tolerance')
    if not np.allclose(stored, refitted, rtol=0, atol=REPLAY_EPSILON_M):
        raise ValueError('Registration transform differs from replayed control/checkpoint evidence')
    # An evidence-point comparison alone must not accept a sheared/reflected
    # matrix, or a changed pose hidden by cancellation at a large local origin.
    if not np.allclose(matrix, replay['matrix'], rtol=0, atol=1e-10):
        raise ValueError('Registration matrix differs from replayed similarity fit')
    for key in ('scale', 'rotation_degrees'):
        actual = numeric(report.get(key), key)
        delta = abs((actual - replay[key] + 180) % 360 - 180) if key == 'rotation_degrees' else abs(actual - replay[key])
        if delta > 1e-9:
            raise ValueError('Registration ' + key + ' differs from replayed fit')
    for key in ('control_error', 'checkpoint_error'):
        summary = report.get(key)
        if not isinstance(summary, dict):
            raise ValueError('Registration residual evidence missing')
        for metric in ('rms_m', 'max_m'):
            actual = numeric(summary.get(metric), key + '/' + metric)
            if actual < 0 or not math.isclose(actual, replay[key][metric], rel_tol=0, abs_tol=REPLAY_EPSILON_M):
                raise ValueError('Registration residual summary differs from replayed point evidence')


def _domain(report):
    """Build the domain only after the caller has validated the complete review."""
    from shapely.geometry import MultiPoint
    points = [p['target'] for p in report['control_pairs'] + report['checkpoint_pairs']]
    hull = MultiPoint(points).convex_hull
    if hull.geom_type != 'Polygon' or hull.area <= 0:
        raise ValueError('Registration domain lacks area')
    return hull


def registration_domain(report):
    require_accepted_review(report)
    return _domain(report)


def apply_registration(points, report):
    """Only apply a fit that passed independent horizontal review."""
    require_accepted_review(report)
    coordinates=np.asarray(points,dtype=float)
    if coordinates.ndim!=2 or coordinates.shape[1]!=2 or not np.isfinite(coordinates).all():raise ValueError('Finite XY coordinates required')
    transformed=coordinates@np.asarray(report['matrix']).T+report['translation_m']
    from shapely.geometry import MultiPoint
    if not _domain(report).buffer(1e-7).covers(MultiPoint(transformed)):
        raise ValueError('Registration extrapolation outside validated domain')
    return transformed.tolist()
