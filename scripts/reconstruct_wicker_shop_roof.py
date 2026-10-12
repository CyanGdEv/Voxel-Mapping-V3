"""Reproduce manually reviewed elevation profiles and a provisional local roof mesh."""
import argparse, hashlib, json, math, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymupdf
from voxel_mapper.drawing_page_tools import pixel_to_native
from voxel_mapper.drawing_geometry import extract_page

SOURCE='d1a7251596b240489c145e76ac06f94448c76972b156f64b4a985753c532c0b6'

def reconstruct(pdf, annotations, roof_pdf):
    if hashlib.sha256(Path(pdf).read_bytes()).hexdigest()!=SOURCE:
        raise ValueError('Elevation source checksum mismatch')
    roof_sha='6ede3a782954b1ab9ae0442791169c25a44dcfa0a79d99fbfe8b4e4bda019047'
    if hashlib.sha256(Path(roof_pdf).read_bytes()).hexdigest()!=roof_sha:raise ValueError('Roof plan checksum mismatch')
    with pymupdf.open(roof_pdf) as roof_doc:
        records,_=extract_page(roof_doc[0],roof_sha,1)
    line_id='96cae9d1a97616dc2b5bf863665ea4e4efc0994a981fec1529c20709994fede2'
    line=next(r for r in records if r['id']==line_id)
    endpoints=line['geometry']['coordinates']
    plan_points=math.dist(endpoints[0],endpoints[-1])
    a=json.loads(Path(annotations).read_text())
    if a['scale_denominator']!=100:raise ValueError('Expected reviewed 1:100 view scale')
    if a['source_sha256']!=SOURCE:raise ValueError('Annotation source mismatch')
    with pymupdf.open(pdf) as doc:
        page=doc[0]
        pix=page.get_pixmap(matrix=pymupdf.Matrix(a['render_width_pixels']/page.rect.width,a['render_width_pixels']/page.rect.width))
        if [pix.width,pix.height]!=a['render_size_pixels']:raise ValueError('Render dimensions changed')
        if hashlib.sha256(pix.samples).hexdigest()!=a['render_samples_sha256']:raise ValueError('Annotated raster changed')
        matrix=pymupdf.Matrix(pixel_to_native(page,pix.width,pix.height))
    # Each view labels 1:100. Graphic scale is an additional same-sheet check,
    # not an independent geographic checkpoint.
    factor=100*.0254/72
    mx=math.hypot(matrix.a,matrix.b)*factor
    my=math.hypot(matrix.c,matrix.d)*factor
    err=a['manual_endpoint_bound_pixels']
    profiles=[]
    for view in a['views']:
        points=view['points_pixels']
        for point in points.values():
            if not (0<=point[0]<pix.width and 0<=point[1]<pix.height):raise ValueError('Point outside raster')
        metrics={}
        for name,left,right,axis in [('roof_span','roof_left','roof_right',0),('wall_span','wall_left','wall_right',0),('ridge_above_floor','ridge','floor',1),('eave_above_floor','eave','floor',1),('left_overhang','roof_left','wall_left',0),('right_overhang','wall_right','roof_right',0)]:
            value=abs(points[right][axis]-points[left][axis])*(mx if axis==0 else my)
            bound=2*err*(mx if axis==0 else my)
            metrics[name]={'metres':value,'manual_sampling_interval_metres':[max(0,value-bound),value+bound]}
        profiles.append({'view':view['view'],'points_pixels':points,
                         'points_native_pdf':{k:list(pymupdf.Point(*v)*matrix) for k,v in points.items()},'measurements':metrics})
    length=profiles[0]['measurements']['roof_span']['metres']
    width=profiles[3]['measurements']['roof_span']['metres']
    eave=profiles[0]['measurements']['eave_above_floor']['metres']
    ridge=profiles[0]['measurements']['ridge_above_floor']['metres']
    vertices=[[-length/2,-width/2,eave],[length/2,-width/2,eave],[-length/2,0,ridge],[length/2,0,ridge],[-length/2,width/2,eave],[length/2,width/2,eave]]
    mesh={'coordinate_frame':'local metres: x long axis, y transverse, z above drawn shop floor',
          'vertices':vertices,'triangles':[[0,1,3],[0,3,2],[2,3,5],[2,5,4]],
          'scope':'main roof surface only; excludes fascia, projections, neighbouring roofs, walls and entrances',
          'registration':None,'source_state':'proposed','world_placement_eligible':False}
    plan_span=plan_points*factor
    return {'source_sha256':SOURCE,'annotation_sha256':hashlib.sha256(Path(annotations).read_bytes()).hexdigest(),
            'pixel_to_native_matrix':list(matrix),'profiles':profiles,'local_roof_mesh':mesh,
            'scale_check':{'graphic_bar_pixels':a['graphic_scale_bar_pixels'],'graphic_bar_drawn_metres':10,
                           'graphic_bar_scaled_metres':abs(a['graphic_scale_bar_pixels'][1]-a['graphic_scale_bar_pixels'][0])*mx},
            'roof_plan_comparison':{'source_sha256':'6ede3a782954b1ab9ae0442791169c25a44dcfa0a79d99fbfe8b4e4bda019047',
                                    'line_record_id':'96cae9d1a97616dc2b5bf863665ea4e4efc0994a981fec1529c20709994fede2',
                                    'line_length_metres':plan_span,'elevation_minus_plan_metres':length-plan_span,
                                    'physical_edge_correspondence_verified':False},
            'limitations':['Manual endpoint bounds describe sampling only, not total physical accuracy.',
                           'Scale checked within proposed drawing; no as-built dimensions or ODN datum acceptance.',
                           'Mesh is a local provisional main roof, not an accepted wall footprint or park registration.'],
            'world_geometry_additions':0}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('pdf','annotations','roof-pdf','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();result=reconstruct(a.pdf,a.annotations,a.roof_pdf)
    Path(a.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'output':a.output,'local_roof_vertices':6,'local_roof_triangles':4,'world_geometry_additions':0}))

if __name__=='__main__':main()
