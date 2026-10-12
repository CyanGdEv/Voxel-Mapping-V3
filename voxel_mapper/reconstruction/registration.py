"""Independent-checkpoint review of a planar similarity registration."""
import math
import numpy as np


def review_registration(controls, checkpoints, *, tolerance_m=1., expected_scale=1., scale_tolerance=.02):
    """Local metric XY to target projected metre XY; no height/datum inference.

    A fit is a hypothesis until at least two independent checkpoints agree.
    Caller must establish landmark identity, target CRS and survey provenance.
    """
    if not all(math.isfinite(v) for v in (tolerance_m, expected_scale, scale_tolerance)) or tolerance_m<=0 or expected_scale<=0 or not 0<=scale_tolerance<1:
        raise ValueError('Invalid registration tolerances')
    def pairs(rows, minimum):
        if not isinstance(rows,list) or len(rows)<minimum or len(rows)>1000:
            raise ValueError('Insufficient or excessive registration points')
        ids=[];local=[];target=[]
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not row['id'] or row['id'] in ids:raise ValueError('Unique control identity required')
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
    return {'status':'accepted_horizontal_fit' if not reasons else 'withheld','reasons':reasons,
            'matrix':matrix.tolist(),'translation_m':[float(tx),float(ty)],'scale':scale,
            'rotation_degrees':math.degrees(math.atan2(c,s)),
            'control_pairs':controls,'checkpoint_pairs':checkpoints,'controls':ids,'checkpoints':independent,'control_error':result_error(fitting),
            'checkpoint_error':result_error(checked),'tolerance_m':tolerance_m,
            'limitations':['Horizontal fit only; no vertical datum or height acceptance',
                           'Landmark identity, source provenance and CRS must be reviewed separately']}


def require_accepted_review(report):
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


def registration_domain(report):
    require_accepted_review(report)
    from shapely.geometry import MultiPoint
    try:points=[p['target'] for p in report['control_pairs']+report['checkpoint_pairs']]
    except (KeyError,TypeError) as error:raise ValueError('Registration point evidence missing') from error
    coordinates=np.asarray(points,dtype=float)
    if coordinates.ndim!=2 or coordinates.shape[1]!=2 or not np.isfinite(coordinates).all():raise ValueError('Invalid registration domain')
    hull=MultiPoint(coordinates).convex_hull
    if hull.geom_type!='Polygon' or hull.area<=0:raise ValueError('Registration domain lacks area')
    return hull


def apply_registration(points, report):
    """Only apply a fit that passed independent horizontal review."""
    require_accepted_review(report)
    coordinates=np.asarray(points,dtype=float)
    if coordinates.ndim!=2 or coordinates.shape[1]!=2 or not np.isfinite(coordinates).all():raise ValueError('Finite XY coordinates required')
    transformed=coordinates@np.asarray(report['matrix']).T+report['translation_m']
    from shapely.geometry import MultiPoint
    if not registration_domain(report).buffer(1e-7).covers(MultiPoint(transformed)):
        raise ValueError('Registration extrapolation outside validated domain')
    return transformed.tolist()
