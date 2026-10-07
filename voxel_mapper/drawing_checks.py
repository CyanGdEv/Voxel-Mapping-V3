"""Audit externally supplied check points without claiming surveyed accuracy."""
import math

from shapely.geometry import MultiPoint, Polygon

from .geopdf import page_point_to_metric


def check_external_controls(registration, checks, *, drawing_source_id, tolerance_m=1):
    report={'status':'rejected','independent_accuracy':'not_verified',
            'world_geometry_additions':0,'checks':[]}
    try:
        if not drawing_source_id or not math.isfinite(tolerance_m) or not 0<tolerance_m<=1:
            raise ValueError('Drawing provenance and tolerance of at most one metre required')
        if not 3<=len(checks)<=64:
            raise ValueError('Three to 64 external check points required')
        page_points=[]
        for check in checks:
            if (not check.get('source_id') or check['source_id']==drawing_source_id or
                    not check.get('evidence_reference') or check.get('used_in_fit') is not False):
                raise ValueError('External evidence provenance and withheld-from-fit declaration required')
            if check.get('metric_crs')!=registration.get('metric_crs'):
                raise ValueError('Check CRS must exactly match registration metric CRS')
            uncertainty=check.get('horizontal_uncertainty_m')
            if not isinstance(uncertainty,(float,int)) or isinstance(uncertainty,bool) or not math.isfinite(uncertainty) or uncertainty<0:
                raise ValueError('Finite measured reference uncertainty required')
            point=check['page_point']
            expected=check['metric_point']
            if len(point)!=2 or len(expected)!=2 or not all(math.isfinite(v) for v in expected):
                raise ValueError('Finite two-dimensional check coordinates required')
            actual=page_point_to_metric(registration,*point)
            error=math.dist(actual,expected)
            page_points.append(point)
            report['checks'].append({'source_id':check['source_id'],'evidence_reference':check['evidence_reference'],
                                    'error_m':error,'horizontal_uncertainty_m':uncertainty,
                                    'within_tolerance':error+uncertainty<=tolerance_m})
        left,bottom,right,top=registration['viewport_bbox']
        normalised=[((x-left)/(right-left),(y-bottom)/(top-bottom)) for x,y in page_points]
        hull=MultiPoint(normalised).convex_hull
        domain=Polygon(registration['control_hull'])
        if hull.geom_type!='Polygon' or hull.area<.25*domain.area:
            raise ValueError('External checks must span at least one quarter of control hull area')
        report['status']='external_control_agreement' if all(c['within_tolerance'] for c in report['checks']) else 'external_control_disagreement'
        report['tolerance_m']=tolerance_m
        report['limitations']=['Reference identity, source independence and uncertainty are adapter declarations, not independently verified here',
                              'Control agreement does not establish drawing reuse, revision, construction status or absolute surveyed accuracy',
                              'No automatic external landmark provider or world insertion']
        return report
    except (ValueError,TypeError,KeyError,IndexError) as error:
        return {**report,'status':'rejected','reason':str(error)}
