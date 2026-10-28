"""Source-defined local path connections and grass-separator bridge checks."""
import numpy as np
from scipy import ndimage
from PIL import Image,ImageDraw


def evaluate(target,prediction,registration,probes):
    if target.shape!=prediction.shape or target.size>1048576:raise ValueError('Bounded matching path review grids required')
    M=np.asarray(registration['reference_to_clean'],float)
    if M.shape!=(2,3) or not np.isfinite(M).all() or len(probes)>32:raise ValueError('Bounded source probe registration required')
    rows=[]
    for p in probes:
        x0,y0,x1,y1=p['reference_box_xyxy'];corners=np.array([[x0,y0],[x1,y0],[x1,y1],[x0,y1]])@M[:,:2].T+M[:,2]
        im=Image.new('L',(target.shape[1],target.shape[0]));ImageDraw.Draw(im).polygon([tuple(x) for x in corners],fill=1);scope=np.array(im,dtype=bool)
        coords=[];adjustments=[]
        for point in (p['a_reference_xy'],p['b_reference_xy']):
            xy=M[:,:2]@point+M[:,2];x,y=np.rint(xy).astype(int);candidates=[]
            for dy in range(-2,3):
                for dx in range(-2,3):
                    xx,yy=x+dx,y+dy
                    if 0<=yy<target.shape[0] and 0<=xx<target.shape[1] and target[yy,xx]==0 and scope[yy,xx]:candidates.append(((xx-xy[0])**2+(yy-xy[1])**2,xx,yy))
            if not candidates:raise ValueError('Probe endpoint is not supported by known paving: '+p['id'])
            distance,x,y=min(candidates);coords.append((y,x));adjustments.append(float(distance**.5))
        def connected(mask):
            labels,n=ndimage.label(mask&scope);a,b=[int(labels[y,x]) for y,x in coords];return bool(a and a==b)
        truth=connected(target==0);expected=p['expected_local_connection']
        if truth!=expected:raise ValueError('Probe topology differs from explicit targets: '+p['id'])
        grass=scope&(target==2)
        if not expected and grass.sum()<20:raise ValueError('Explicit grass separator support required')
        found=connected(prediction==0)
        rows.append({'id':p['id'],'expected_local_connection':expected,'predicted_local_connection':found,'passed':found==expected,
          'endpoint_adjustment_clean_pixels':adjustments,'known_grass_pixels':int(grass.sum()),
          'grass_predicted_as_paving_fraction':float((prediction[grass]==0).mean()) if grass.any() else None})
    positives=[r for r in rows if r['expected_local_connection']];negatives=[r for r in rows if not r['expected_local_connection']]
    return {'probes':rows,'connected_visible_paths':sum(r['passed'] for r in positives),'visible_path_probes':len(positives),
      'false_local_grass_bridges':sum(not r['passed'] for r in negatives),'grass_separator_probes':len(negatives),
      'scope':'Local source-defined corridors only; separate paths can connect elsewhere in the garden. Draft labels, not surveyed geometry.'}
