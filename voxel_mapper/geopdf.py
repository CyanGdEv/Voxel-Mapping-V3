"""Validate explicit WGS84 GeoPDF viewport registration, without extracting geometry."""
import math

import numpy as np
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError
from shapely.geometry import MultiPoint, Point, Polygon, box


def inspect_registration(page, bounds=None, tolerance_m=.5, max_viewports=16):
    if not math.isfinite(tolerance_m) or tolerance_m<=0:
        raise ValueError('Registration tolerance must be finite and positive')
    viewports = page.get('/VP') or []
    if hasattr(viewports, 'get_object'):
        viewports = viewports.get_object()
    report = {'status':'metadata_missing', 'viewports':[], 'independent_accuracy':'not_verified'}
    if not viewports:
        if page.get('/LGIDict'):
            report['status']='unsupported_lgi_encoding'
        return report
    if len(viewports)>max_viewports:
        return {**report, 'status':'rejected', 'reason':'Viewport budget exceeded'}
    for index, value in enumerate(viewports):
        entry = {'viewport':index, 'status':'rejected'}
        report['viewports'].append(entry)
        try:
            viewport = value.get_object() if hasattr(value,'get_object') else value
            measure = viewport.get('/Measure')
            if hasattr(measure,'get_object'):
                measure = measure.get_object()
            if not measure or measure.get('/Subtype') != '/GEO':
                raise ValueError('Unsupported or missing GEO measure')
            if int(page.get('/Rotate',0))%360 or float(page.get('/UserUnit',1)) != 1:
                raise ValueError('Rotated pages/non-default UserUnit are not supported')
            gcs = measure.get('/GCS')
            if hasattr(gcs,'get_object'):
                gcs = gcs.get_object()
            if not gcs:
                raise ValueError('Declared coordinate system required')
            epsg, source_wkt = gcs.get('/EPSG'), gcs.get('/WKT')
            if epsg is None and not source_wkt:
                raise ValueError('Declared EPSG or WKT required')
            source_crs = CRS.from_epsg(int(epsg)) if epsg is not None else CRS.from_wkt(str(source_wkt))
            if source_wkt and epsg is not None and not CRS.from_wkt(str(source_wkt)).equals(source_crs,ignore_axis_order=True):
                raise ValueError('Conflicting EPSG/WKT declarations')
            if source_crs.to_epsg() != 4326 or not source_crs.is_geographic:
                raise ValueError('Only explicit WGS84 EPSG:4326 registration is supported')
            rect = np.array(viewport['/BBox'],dtype=float)
            local = np.array(measure['/LPTS'],dtype=float)
            geographic = np.array(measure['/GPTS'],dtype=float)
            if rect.shape != (4,) or not np.all(np.isfinite(rect)) or rect[2]<=rect[0] or rect[3]<=rect[1]:
                raise ValueError('Invalid viewport rectangle')
            if not box(*map(float,page.mediabox)).covers(box(*rect)):
                raise ValueError('Viewport lies outside page')
            if local.ndim!=1 or geographic.ndim!=1 or len(local)!=len(geographic) or len(local)%2 or not 8<=len(local)<=128:
                raise ValueError('Four to 64 paired control points required')
            local, geographic = local.reshape(-1,2), geographic.reshape(-1,2)
            if not np.all(np.isfinite(local)) or not np.all(np.isfinite(geographic)) or np.any(local<0) or np.any(local>1):
                raise ValueError('Invalid/nonfinite normalised control coordinates')
            if len(np.unique(local,axis=0)) != len(local):
                raise ValueError('Duplicate control points')
            # ISO GEO GPTS pairs are latitude,longitude, unlike GeoJSON.
            latitudes, longitudes = geographic[:,0], geographic[:,1]
            if np.any(np.abs(latitudes)>=90) or np.any(np.abs(longitudes)>180) or np.ptp(longitudes)>180:
                raise ValueError('Invalid geographic controls or antimeridian registration')
            hull = MultiPoint(local).convex_hull
            if hull.geom_type != 'Polygon' or hull.area<.01:
                raise ValueError('Degenerate control geometry')
            if measure.get('/Bounds') is not None:
                neat = np.array(measure['/Bounds'],dtype=float)
                if neat.ndim!=1 or len(neat)%2 or not 6<=len(neat)<=128 or not np.all(np.isfinite(neat)) or np.any(neat<0) or np.any(neat>1):
                    raise ValueError('Invalid normalised registration boundary')
                polygon = Polygon(neat.reshape(-1,2))
                if not polygon.is_valid or polygon.is_empty:
                    raise ValueError('Invalid registration boundary polygon')
                hull = hull.intersection(polygon)
                if hull.geom_type!='Polygon' or hull.is_empty:
                    raise ValueError('Boundary does not overlap control hull')
            if bounds is not None:
                west,south,east,north = bounds
                if not box(west,south,east,north).intersects(MultiPoint(np.column_stack([longitudes,latitudes])).convex_hull):
                    raise ValueError('Registration does not intersect requested area')
                lon0,lat0=(west+east)/2,(south+north)/2
            else:
                lon0,lat0=float(longitudes.mean()),float(latitudes.mean())
            target = CRS.from_proj4(f'+proj=aeqd +lat_0={lat0} +lon_0={lon0} +datum=WGS84 +units=m')
            projector = Transformer.from_crs(4326,target,always_xy=True)
            eastings,northings = projector.transform(longitudes,latitudes)
            metric = np.column_stack([eastings,northings])
            if not np.all(np.isfinite(metric)) or np.any(np.ptp(metric,axis=0)>20_000):
                raise ValueError('Registration exceeds supported 20 km local extent')
            design = np.column_stack([local,np.ones(len(local))])
            if np.linalg.matrix_rank(design)!=3 or np.linalg.cond(design)>10_000:
                raise ValueError('Unstable registration control geometry')
            coefficients = np.linalg.lstsq(design,metric,rcond=None)[0]
            residuals = np.linalg.norm(design@coefficients-metric,axis=1)
            withheld = []
            for i in range(len(local)):
                training = np.delete(design,i,axis=0)
                if np.linalg.matrix_rank(training)!=3 or np.linalg.cond(training)>10_000:
                    raise ValueError('Controls cannot support withheld-point validation')
                fit = np.linalg.lstsq(training,np.delete(metric,i,axis=0),rcond=None)[0]
                withheld.append(float(np.linalg.norm(design[i]@fit-metric[i])))
            if not np.all(np.isfinite(coefficients)) or abs(np.linalg.det(coefficients[:2]))<1e-6:
                raise ValueError('Degenerate metric transformation')
            entry.update(control_count=len(local), max_fit_error_m=float(residuals.max()),
                         rms_fit_error_m=float(np.sqrt(np.mean(residuals**2))),
                         max_withheld_error_m=max(withheld), tolerance_m=tolerance_m)
            if max(float(residuals.max()),max(withheld))>tolerance_m:
                raise ValueError('Registration exceeds metre-scale residual tolerance')
            entry.update(status='internally_consistent_unverified', source_crs='EPSG:4326',
                         metric_crs=target.to_wkt(), viewport_bbox=rect.tolist(),
                         normalised_to_metric=coefficients.tolist(), control_hull=list(hull.exterior.coords),
                         area_check='intersects_requested_area' if bounds is not None else 'not_checked',
                         coordinate_convention='Unrotated PDF page coordinates; normalised viewport LPTS; GPTS latitude,longitude')
        except (ValueError,TypeError,KeyError,AttributeError,OverflowError,CRSError,np.linalg.LinAlgError) as error:
            entry['reason']=str(error)
    accepted = sum(v['status']=='internally_consistent_unverified' for v in report['viewports'])
    report['status']='candidate_alignment' if accepted else 'rejected'
    report['candidate_viewports']=accepted
    report['limitations']=['Residuals test embedded controls, not independent surveyed accuracy',
                           'Multiple viewport candidates remain separate; no automatic inset selection',
                           'No geometry extraction, reuse clearance or construction verification']
    return report


def page_point_to_metric(registration, x, y):
    """Map only inside a selected validated control hull; forbid extrapolation."""
    if registration.get('status')!='internally_consistent_unverified' or not math.isfinite(x) or not math.isfinite(y):
        raise ValueError('Validated registration and finite coordinates required')
    left,bottom,right,top=registration['viewport_bbox']
    u,v=(x-left)/(right-left),(y-bottom)/(top-bottom)
    if not Polygon(registration['control_hull']).covers(Point(u,v)):
        raise ValueError('Point lies outside registration control hull')
    point=np.array([u,v,1.])@np.array(registration['normalised_to_metric'])
    return float(point[0]),float(point[1])
