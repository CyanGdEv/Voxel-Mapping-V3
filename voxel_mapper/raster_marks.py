"""Local raster crosshair hypotheses; never certify survey accuracy."""
import math

import numpy as np
from PIL import Image
from shapely.geometry import MultiPoint


def crosshair_at(dark, expected, radius=12):
    """Require both centred continuous strokes, not a nearest dark pixel."""
    if dark.ndim!=2 or not 1<=radius<=12 or not all(math.isfinite(v) for v in expected):
        raise ValueError('Finite point, two-dimensional raster and bounded radius required')
    height,width=dark.shape
    ex,ey=expected
    centres=[]
    for y in range(max(24,round(ey)-radius),min(height-24,round(ey)+radius+1)):
        for x in range(max(24,round(ex)-radius),min(width-24,round(ex)+radius+1)):
            if not dark[y,x]:continue
            left=right=x;top=bottom=y
            while left>x-24 and dark[y,left-1]:left-=1
            while right<x+24 and dark[y,right+1]:right+=1
            while top>y-24 and dark[top-1,x]:top-=1
            while bottom<y+24 and dark[bottom+1,x]:bottom+=1
            h,v=right-left+1,bottom-top+1
            if not 20<=h<=44 or not 20<=v<=44 or abs(h-v)>6:
                continue
            cx,cy=(left+right)/2,(top+bottom)/2
            if abs(cx-x)>2 or abs(cy-y)>2 or max(abs(cx-ex),abs(cy-ey))>radius:
                continue
            # A thick filled plus/rectangle is not the thin survey symbol.
            if np.count_nonzero(dark[y-3:y+4,x-3:x+4])>33:
                continue
            centres.append((cx,cy))
    if not centres:return None,'missing_complete_crosshair'
    centre=np.median(np.array(centres),axis=0)
    if any(math.dist(point,centre)>2 for point in centres):
        return None,'ambiguous_crosshairs'
    return tuple(map(float,centre)),'crosshair_hypothesis'


def inspect_grid_marks(image, labels, *, reuse_allowed=False, max_error=0.5):
    report={'status':'insufficient_grid_marks','world_geometry_additions':0,
            'geographic_registration':'not_established','independent_accuracy':'not_verified',
            'controls_exported':False,'attempts':[]}
    if len(labels)>64 or not math.isfinite(max_error) or max_error<=0:
        raise ValueError('Invalid raster mark budget/tolerance')
    axes={}
    for axis in ('E','N'):
        group=[label for label in labels if label['axis']==axis]
        values={label['value'] for label in group}
        axes[axis]=[(value,float(np.mean([label['pixel_position'] for label in group if label['value']==value])))
                    for value in sorted(values)]
    if min(map(len,axes.values()))<2 or len(axes['E'])*len(axes['N'])>64:
        return report
    with Image.open(image) as raster:
        if max(raster.size)>4096 or raster.width*raster.height>4096**2:
            raise ValueError('Raster mark pixel budget exceeded')
        dark=np.array(raster.convert('L'))<140
    controls=[]
    for east,x in axes['E']:
        for north,y in axes['N']:
            if not all(math.isfinite(v) for v in (east,north,x,y)):
                raise ValueError('Finite coordinate labels required')
            point,status=crosshair_at(dark,(x,y))
            report['attempts'].append({'status':status})
            if point is not None:controls.append((point,(east,north)))
    report['complete_mark_count']=len(controls)
    if len(controls)<4:return report
    pixels=np.array([p for p,_ in controls]);coordinates=np.array([c for _,c in controls],dtype=float)
    if np.any(np.ptp(coordinates,axis=0)>20_000):
        return {**report,'status':'rejected_control_extent'}
    hull=MultiPoint(pixels).convex_hull
    if hull.geom_type!='Polygon' or hull.area<1000:
        return {**report,'status':'rejected_control_geometry'}
    centre=pixels.mean(axis=0)
    design=np.column_stack([pixels-centre,np.ones(len(pixels))])
    if np.linalg.matrix_rank(design)!=3 or np.linalg.cond(design)>10_000:
        return {**report,'status':'rejected_control_geometry'}
    fit=np.linalg.lstsq(design,coordinates,rcond=None)[0]
    errors=np.linalg.norm(design@fit-coordinates,axis=1)
    withheld=[]
    for i in range(len(controls)):
        training=np.delete(design,i,axis=0)
        if np.linalg.matrix_rank(training)!=3:
            return {**report,'status':'insufficient_withheld_control_geometry'}
        prediction=design[i]@np.linalg.lstsq(training,np.delete(coordinates,i,axis=0),rcond=None)[0]
        withheld.append(float(np.linalg.norm(prediction-coordinates[i])))
    report.update(max_fit_error_coordinate_units=float(errors.max()),
                  max_withheld_error_coordinate_units=max(withheld))
    if fit[0,0]<=0 or fit[1,1]>=0 or abs(np.linalg.det(fit[:2]))<1e-9 or max(float(errors.max()),max(withheld))>max_error:
        return {**report,'status':'rejected_grid_mark_fit'}
    report['status']='internally_consistent_grid_marks_unverified'
    report['limitations']=['Raster symbol/label correspondence uses a twelve-pixel window and remains a hypothesis',
                           'Only thin, continuous, nearly symmetric twenty-to-forty-four-pixel crosses are supported',
                           'Internal fit does not verify CRS, coordinate units, survey accuracy or constant offsets',
                           'Partial strokes are omitted; no missing mark or polygon is interpolated',
                           'No geographic registration or world insertion is established']
    if reuse_allowed is True:
        report.update(controls_exported=True,controls=[{'page_pixel':list(p),'drawing_coordinate':list(c)} for p,c in controls],
                      pixel_centre=centre.tolist(),centred_pixel_to_drawing=fit.tolist(),
                      pixel_control_hull=list(hull.exterior.coords))
    return report
