"""Trace proposed shop walls/openings without forcing conflicting sheets to fit."""
import argparse,hashlib,json,math,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymupdf
from shapely.geometry import Polygon
from voxel_mapper.drawing_page_tools import pixel_to_native

SOURCE='08afa2513a3cb9ab35b515bcdbd5acb16b125ca5e5ffcedc4e2e14a7e10d9ad3'

def trace(pdf,annotations,roof_path):
    if hashlib.sha256(Path(pdf).read_bytes()).hexdigest()!=SOURCE:raise ValueError('Floor source checksum mismatch')
    a=json.loads(Path(annotations).read_text());roof=json.loads(Path(roof_path).read_text())
    if roof['source_sha256']!='d1a7251596b240489c145e76ac06f94448c76972b156f64b4a985753c532c0b6':raise ValueError('Shop elevation review required')
    if len(a['outer_corners_pixels'])!=4:raise ValueError('Four reviewed outer corners required')
    if a['source_sha256']!=SOURCE or a['scale_denominator']!=100:raise ValueError('Reviewed floor source/scale required')
    with pymupdf.open(pdf) as doc:
        page=doc[0];pix=page.get_pixmap(matrix=pymupdf.Matrix(1888/page.rect.width,1888/page.rect.width))
        if [pix.width,pix.height]!=a['render_size_pixels'] or hashlib.sha256(pix.samples).hexdigest()!=a['render_samples_sha256']:raise ValueError('Annotated render changed')
        matrix=pymupdf.Matrix(pixel_to_native(page,pix.width,pix.height))
    factor=100*.0254/72
    corners=[list(pymupdf.Point(*p)*matrix) for p in a['outer_corners_pixels']]
    # Local source frame is deliberately not centred/rescaled to the roof mesh.
    metric=[[p[0]*factor,p[1]*factor] for p in corners]
    polygon=Polygon(metric)
    if not polygon.is_valid or polygon.area<=0:raise ValueError('Invalid wall outline')
    lengths=[math.dist(metric[i],metric[(i+1)%4]) for i in range(4)]
    local_origin=metric[0]
    local=[[x-local_origin[0],y-local_origin[1]] for x,y in metric]
    samples=max(math.hypot(matrix.a,matrix.b),math.hypot(matrix.c,matrix.d))*factor
    endpoint_bound=a['manual_endpoint_bound_pixels']*math.sqrt(2)*samples
    openings=[];segments=[]
    for edge in range(4):
        start,end=local[edge],local[(edge+1)%4];dx,dy=end[0]-start[0],end[1]-start[1];norm=dx*dx+dy*dy
        gaps=[]
        for entry in a['openings']:
            if entry['edge']!=edge:continue
            native=[list(pymupdf.Point(*p)*matrix) for p in entry['endpoints_pixels']]
            pts=[[p[0]*factor-local_origin[0],p[1]*factor-local_origin[1]] for p in native]
            ts=[((p[0]-start[0])*dx+(p[1]-start[1])*dy)/norm for p in pts]
            lo,hi=sorted(ts)
            if not (0<lo<hi<1):raise ValueError('Opening outside wall')
            snapped=[[start[0]+t*dx,start[1]+t*dy] for t in [lo,hi]]
            residual=max(math.dist(p,[start[0]+t*dx,start[1]+t*dy]) for p,t in zip(pts,ts))
            if residual>endpoint_bound*2:raise ValueError('Opening does not lie on annotated wall')
            gaps.append((lo,hi));width=(hi-lo)*lengths[edge]
            openings.append({'id':entry['id'],'edge':edge,'drawing_role':entry['drawing_role'],
                             'raw_native_endpoints':native,'local_projected_endpoints':snapped,
                             'wall_projection_residual_metres':residual,'width_metres':width,
                             'sampling_interval_metres':[max(0,width-2*endpoint_bound),width+2*endpoint_bound],
                             'height_metres':None,'as_built_verified':False})
        cursor=0
        for lo,hi in sorted(gaps)+[(1,1)]:
            if lo<cursor:raise ValueError('Overlapping openings')
            if lo>cursor:segments.append({'edge':edge,'start':[start[0]+cursor*dx,start[1]+cursor*dy],'end':[start[0]+lo*dx,start[1]+lo*dy]})
            cursor=hi
    dims=sorted([sum(lengths[::2])/2,sum(lengths[1::2])/2],reverse=True)
    elevation=roof['profiles'][0]['measurements']['wall_span']['metres'],roof['profiles'][3]['measurements']['wall_span']['metres']
    differences=[dims[i]-elevation[i] for i in range(2)]
    area_upper=polygon.buffer(endpoint_bound).area
    mismatch=any(abs(d)>2*endpoint_bound+.18 for d in differences)
    gia_conflict=area_upper<170
    return {'source_sha256':SOURCE,'annotation_sha256':hashlib.sha256(Path(annotations).read_bytes()).hexdigest(),
            'roof_review_sha256':hashlib.sha256(Path(roof_path).read_bytes()).hexdigest(),
            'coordinate_frame':'local metres in native PDF axes, origin at first annotated corner; not a park frame',
            'native_outer_corners':corners,'local_outer_corners':local,'wall_edge_lengths_metres':lengths,
            'dimensions_metres':dims,'outer_area_metres_squared':polygon.area,
            'conservative_sampling_area_upper_metres_squared':area_upper,
            'per_endpoint_sampling_bound_metres':endpoint_bound,'openings':openings,'wall_segments':segments,
            'roof_fit_review':{'elevation_wall_dimensions_metres':list(elevation),'floor_minus_elevation_metres':differences,
                               'dimension_conflict':mismatch,'forced_scale_applied':False},
            'internal_area_review':{'native_label_metres_squared':170,'apparent_outer_area_below_label_even_with_sampling_bound':gia_conflict},
            'status':'proposed_source_trace_cross_sheet_conflict' if mismatch or gia_conflict else 'proposed_source_trace',
            'physical_accuracy_verified':False,'wall_height_metres':None,'world_placement_eligible':False,'world_geometry_additions':0}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('pdf','annotations','roof','output'):p.add_argument('--'+k,required=True)
    a=p.parse_args();result=trace(a.pdf,a.annotations,a.roof)
    Path(a.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'openings':len(result['openings']),'wall_segments':len(result['wall_segments']),'dimensions_metres':result['dimensions_metres']}))

if __name__=='__main__':main()
