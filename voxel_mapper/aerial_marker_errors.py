"""Source-bound normal-transect measurements for semantic surface markers."""
import numpy as np
from scipy import ndimage

VERSION='aerial-marker-normal-errors-v1'


def validate_reference(r,size):
    if r.get('class') not in (0,1,2,3) or not isinstance(r.get('id'),str) or not 1<=len(r['id'])<=80:raise ValueError('Named observed surface marker required')
    point=np.asarray(r.get('point_xy'),float);normal=np.asarray(r.get('normal_xy'),float)
    if point.shape!=(2,) or normal.shape!=(2,) or not np.isfinite(point).all() or not np.isfinite(normal).all() or not 0<=point[0]<size[0] or not 0<=point[1]<size[1] or np.linalg.norm(normal)<.1:raise ValueError('Bounded point and outward normal required')
    if r.get('outside_class') not in (None,0,1,2,3) or r.get('outside_class')==r['class']:raise ValueError('Distinct explicit outside class or unknown required')
    return point,normal/np.linalg.norm(normal)


def measure(prediction,reference,spacing_m=.08,radius_px=40):
    if prediction.ndim!=2 or prediction.size>1048576 or not set(np.unique(prediction))<={0,1,2,3} or not .05<=spacing_m<=1 or not 8<=radius_px<=80:raise ValueError('Bounded categorical marker grid required')
    point,normal=validate_reference(reference,(prediction.shape[1],prediction.shape[0]));offset=np.arange(-radius_px,radius_px+.125,.25);xy=point+offset[:,None]*normal
    if (xy[:,0]<0).any() or (xy[:,0]>=prediction.shape[1]).any() or (xy[:,1]<0).any() or (xy[:,1]>=prediction.shape[0]).any():raise ValueError('Complete source transect must lie inside the image')
    inside=ndimage.map_coordinates((prediction==reference['class']).astype(np.uint8),[xy[:,1],xy[:,0]],order=0,mode='nearest');inside=ndimage.median_filter(inside,size=5,mode='nearest');cross=np.flatnonzero((inside[:-1]==1)&(inside[1:]==0));candidates=(offset[cross]+offset[cross+1])/2;delta=float(candidates[np.argmin(np.abs(candidates))]) if len(candidates) else None
    probes=point+np.array([-8,8])[:,None]*normal;ends=ndimage.map_coordinates(prediction,[probes[:,1],probes[:,0]],order=0,mode='nearest');cap=radius_px*spacing_m
    opposite_correct=ends[1]==reference['outside_class'] if reference.get('outside_class') is not None else ends[1]!=reference['class']
    return {'id':reference['id'],'class':reference['class'],'outside_class':reference.get('outside_class'),'source_point_xy':point.tolist(),'normal_xy':normal.tolist(),'directed_crossings':len(cross),'missing_marker':delta is None,'signed_offset_pixels':delta,'signed_offset_m':delta*spacing_m if delta is not None else None,'absolute_error_m':abs(delta)*spacing_m if delta is not None else None,'capped_error_m':min(abs(delta)*spacing_m,cap) if delta is not None else cap,'marker_xy':(point+delta*normal).tolist() if delta is not None else None,'inside_outside_probes_correct':bool(ends[0]==reference['class'] and opposite_correct),'search_cap_m':cap,'reference_uncertainty_m':reference.get('uncertainty_px',3)*spacing_m}


def summarise(rows):
    if not rows:return {'samples':0,'capped_mean_error_m':None,'localized_markers':0}
    values=[r['absolute_error_m'] for r in rows if not r['missing_marker']];signed=[r['signed_offset_m'] for r in rows if not r['missing_marker']]
    return {'samples':len(rows),'localized_markers':len(values),'missing_markers':len(rows)-len(values),'coverage':len(values)/len(rows),'capped_mean_error_m':float(np.mean([r['capped_error_m'] for r in rows])),'detected_median_absolute_error_m':float(np.median(values)) if values else None,'detected_p90_absolute_error_m':float(np.percentile(values,90)) if values else None,'detected_mean_signed_offset_m':float(np.mean(signed)) if signed else None,'within_025m':sum(r['absolute_error_m'] is not None and r['absolute_error_m']<=.25 for r in rows),'within_05m':sum(r['absolute_error_m'] is not None and r['absolute_error_m']<=.5 for r in rows),'inside_outside_probes_correct':sum(r['inside_outside_probes_correct'] for r in rows),'scope':'Normal displacement relative to source-reviewed aerial pixels. Missing edges receive the search-cap penalty; not surveyed ground accuracy.'}


def snap_source_edge(rgb,cir,reference,radius_px=8):
    """A visible-gradient candidate for source review, independent of predictions."""
    if rgb.ndim!=3 or rgb.shape[2]!=3 or rgb.dtype!=np.uint8 or rgb.shape[0]*rgb.shape[1]>1048576 or not 1<=radius_px<=16 or (cir is not None and (cir.dtype!=np.uint8 or cir.shape!=rgb.shape)):raise ValueError('Matching bounded RGB/CIR source images required')
    point,normal=validate_reference(reference,(rgb.shape[1],rgb.shape[0]));tangent=np.array([-normal[1],normal[0]]);offset=np.arange(-radius_px,radius_px+.25,.5);channels=rgb.astype(np.float32)/255
    if cir is not None:channels=np.concatenate([channels,cir.astype(np.float32)/255*.6],2)
    means=[]
    for side in (-1.5,1.5):
        xy=point+offset[:,None,None]*normal+side*normal+np.arange(-3,4)[None,:,None]*tangent
        if (xy[:,:,0]<0).any() or (xy[:,:,1]<0).any() or (xy[:,:,0]>=rgb.shape[1]).any() or (xy[:,:,1]>=rgb.shape[0]).any():raise ValueError('Source guide too close to image margin')
        means.append(np.stack([ndimage.map_coordinates(channels[:,:,i],[xy[:,:,1],xy[:,:,0]],order=1,mode='nearest').mean(1) for i in range(channels.shape[2])],1))
    contrast=np.linalg.norm(means[1]-means[0],axis=1);score=contrast*np.exp(-offset**2/(2*6**2));index=int(score.argmax());delta=float(offset[index]);return {**reference,'guide_point_xy':point.tolist(),'point_xy':(point+delta*normal).tolist(),'normal_xy':normal.tolist(),'source_snap_offset_px':delta,'source_contrast':float(contrast[index]),'method':'RGB/CIR gradient candidate within a source-only guide; assistant visual review required','uncertainty_px':3,'independent_human_review':False}


def reference_band(reference,shape,half_normal=20,half_tangent=3,unknown_half=3):
    point,normal=validate_reference(reference,(shape[1],shape[0]));tangent=np.array([-normal[1],normal[0]]);radius=half_normal+half_tangent+2;x0=max(0,int(point[0]-radius));x1=min(shape[1],int(point[0]+radius+1));y0=max(0,int(point[1]-radius));y1=min(shape[0],int(point[1]+radius+1));yy,xx=np.mgrid[y0:y1,x0:x1];dx=xx-point[0];dy=yy-point[1];d=dx*normal[0]+dy*normal[1];s=dx*tangent[0]+dy*tangent[1];target=np.full(d.shape,255,np.uint8);scope=(np.abs(s)<=half_tangent)&(np.abs(d)<=half_normal);target[scope&(d<=-unknown_half)]=reference['class']
    if reference.get('outside_class') is not None:target[scope&(d>=unknown_half)]=reference['outside_class']
    return (slice(y0,y1),slice(x0,x1)),target


def split_references(references,spacing_m=.08):
    rows=[]
    for r in references:
        cell=np.floor(np.asarray(r['point_xy'])*spacing_m/24).astype(int);role='calibration_check' if (int(cell[0])+2*int(cell[1]))%3==0 else 'calibration_fit';rows.append({**r,'role':role,'spatial_cell':cell.tolist()})
    return rows


def fit_guard(shape,references,spacing_m=.08,guard_m=4.):
    allowed=np.ones(shape,bool);yy,xx=np.ogrid[:shape[0],:shape[1]]
    for r in references:
        if r.get('role')=='calibration_check':allowed&=(xx-r['point_xy'][0])**2+(yy-r['point_xy'][1])**2>(guard_m/spacing_m)**2
    return allowed
