"""Whole original contrast-column runs; flat ink regions are not fascia edges."""
import hashlib
import numpy as np
from shapely.geometry import Point,Polygon
from .reconstruction_evidence_queue import digest

VERSION='original-neighbour-contrast-fascia-v1'


def columns(gray,excluded,threshold,contrast,charge):
    if (gray.dtype!=np.uint8 or gray.ndim!=2 or gray.size>6000000 or min(gray.shape)<3 or max(gray.shape)>3000
            or excluded.shape!=gray.shape or excluded.dtype!=bool or threshold not in (220,235) or contrast not in (32,64)):
        raise ValueError('Bounded original raster/mask, ink threshold and contrast required')
    signed=gray.astype(np.int16)
    left=np.pad(signed[:,:-1],((0,0),(1,0)),mode='edge');right=np.pad(signed[:,1:],((0,0),(0,1)),mode='edge')
    differences=np.maximum(left,right)-signed
    neighbours_clear=~excluded & ~np.pad(excluded[:,:-1],((0,0),(1,0)),constant_values=True) & ~np.pad(excluded[:,1:],((0,0),(0,1)),constant_values=True)
    eligible=(gray<threshold)&neighbours_clear&(differences>=contrast)
    # The raster boundary lacks two original neighbours and is never padded into evidence.
    eligible[:,[0,-1]]=False
    source_sha=hashlib.sha256(gray.tobytes()).hexdigest();mask_sha=hashlib.sha256(excluded.astype('uint8').tobytes()).hexdigest();rows=[]
    for x in range(1,gray.shape[1]-1):
        charge();yy=np.flatnonzero(eligible[:,x]);groups=np.split(yy,np.flatnonzero(np.diff(yy)>2)+1)
        for group in groups:
            charge()
            if len(group)<16 or not 16<=group[-1]-group[0]<64 or group[0]==0 or group[-1]==gray.shape[0]-1:continue
            row={'x':x,'source_y_interval_pixels':[int(group[0]),int(group[-1])],
                'source_pixels':[{'x':x,'y':int(y),'gray':int(gray[y,x]),
                    'left_original_gray':int(gray[y,x-1]),'right_original_gray':int(gray[y,x+1]),
                    'maximum_original_neighbour_difference':int(differences[y,x])} for y in group],
                'unsupported_row_intervals':[[int(a+1),int(b)] for a,b in zip(group[:-1],group[1:]) if b>a+1],
                'source_gaps_filled':False,'source_pixels_clipped_to_prediction':False,'physical_fascia_role_verified':False}
            row['id']=digest([VERSION,source_sha,mask_sha,threshold,contrast,row]);rows.append(row)
            if len(rows)>2048:raise OverflowError('contrast_fascia_column_budget')
    return {'threshold':threshold,'source_gradient_contrast':contrast,'source_gray_sha256':source_sha,
        'source_mask_sha256':mask_sha,'eligible_source_pixels':int(eligible.sum()),'source_fascia_columns':rows,
        'recipe':'original ink AND maximum left/right original neighbour minus centre >= contrast; no smoothing or Sobel-centre requirement'}


def observed_edges(candidate,context,lines,charge):
    """Which original perimeter edge does the unchanged finite aim enter first?"""
    start,end=map(np.array,context['diagnostic_aim_segment_pdf_native']);direction=end-start;rows=[]
    corners=candidate['source_corners_pdf_native']
    def cross(a,b):return float(a[0]*b[1]-a[1]*b[0])
    for index in range(4):
        charge();a,b=map(np.array,(corners[index],corners[(index+1)%4]));delta=b-a;den=cross(direction,delta)
        if abs(den)<1e-12:continue
        t=cross(a-start,delta)/den;u=cross(a-start,direction)/den
        if not 0<=t<=1 or not 0<=u<=1:continue
        row={'source_edge_index':index,'source_perimeter_ids':candidate['source_perimeter_ids_per_edge'][index],
            'original_edge_endpoints_pdf_native':[a.tolist(),b.tolist()],
            'diagnostic_segment_fraction':t,'original_edge_station_fraction':u,
            'diagnostic_entry_point_pdf_native':(start+t*direction).tolist(),
            'entry_is_interior_of_original_edge':1e-6<u<1-1e-6}
        row['id']=digest([VERSION,row]);rows.append(row)
    rows.sort(key=lambda r:(r['diagnostic_segment_fraction'],r['source_edge_index']))
    first=[r for r in rows if abs(r['diagnostic_segment_fraction']-rows[0]['diagnostic_segment_fraction'])<=1e-9] if rows else []
    return {'intersections':rows,'status':'conditional_original_observed_edge' if not Polygon(corners).covers(Point(start)) and len(first)==1 and first[0]['entry_is_interior_of_original_edge'] else 'observed_edge_ambiguous_or_missing',
        'first_edge_candidates':first,'physical_view_face_correspondence_verified':False,
        'diagnostic_reach_changed':False}


def fascia_mesh(candidate,model,silhouette,endcheck,columns,edge_index,unit):
    """One observed edge only; no transfer of fascia depth to other faces."""
    cap_by_id={c['id']:c for c in columns};level=silhouette['source_level_pixel'];mpp=silhouette['nominal_metres_per_pixel']
    image_bottom=[(level-cap_by_id[key]['source_y_interval_pixels'][1])*mpp for key in endcheck['source_fascia_column_ids']]
    bottoms=image_bottom[::silhouette['image_left_to_native_orientation']]
    projection=silhouette['projection'];left,right=projection['native_runs_m'];stations=projection['corner_horizontal_stations_nominal_m']
    all_bottoms=[bottoms[0]+(s+left)/(left+right)*(bottoms[1]-bottoms[0]) for s in stations]
    a,b=edge_index,(edge_index+1)%4;vertices=model['mesh']['vertices'];points=[vertices[a],[*vertices[a][:2],all_bottoms[a]],[*vertices[b][:2],all_bottoms[b]],vertices[b]]
    if min(vertices[i][2]-all_bottoms[i] for i in (a,b))<=0:raise ValueError('Positive observed fascia depth required')
    return {'vertices':points,'triangles':[[0,1,2],[0,2,3]],'original_plan_edge_index':edge_index,
        'source_perimeter_ids':candidate['source_perimeter_ids_per_edge'][edge_index],
        'observed_corner_depths_nominal_m':[vertices[i][2]-all_bottoms[i] for i in (a,b)],
        'source_bottom_y_pixels':[cap_by_id[key]['source_y_interval_pixels'][1] for key in endcheck['source_fascia_column_ids']],
        'linear_top_and_bottom_edge_planes_assumed':True,'physical_fascia_role_verified':False,
        'depth_transferred_to_other_edges':False,'wall_mesh':None,'world_placement_eligible':False}
