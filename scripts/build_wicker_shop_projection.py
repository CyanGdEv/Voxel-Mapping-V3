"""Attach a proposed canopy hypothesis using roof-plan depth and explicit NE height choice."""
import argparse,hashlib,json,math,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pymupdf
from voxel_mapper.drawing_page_tools import pixel_to_native

ELEV='d1a7251596b240489c145e76ac06f94448c76972b156f64b4a985753c532c0b6'
ROOF='6ede3a782954b1ab9ae0442791169c25a44dcfa0a79d99fbfe8b4e4bda019047'

def build(directory,wall_path):
    frames={};traces={}
    picks={'NE':{'rear':[1140,818],'front-top':[1140,831],'front-bottom':[1140,837],'floor':[1374,893]},
           'SE':{'rear':[642,334],'front-top':[676,352],'front-bottom':[676,358],'floor':[119,407]}}
    for sha in [ELEV,ROOF]:
        path=Path(directory)/(sha+'.pdf')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('Source PDF checksum mismatch')
        with pymupdf.open(path) as doc:
            p=doc[0];pix=p.get_pixmap(matrix=pymupdf.Matrix(1888/p.rect.width,1888/p.rect.width));mat=pymupdf.Matrix(pixel_to_native(p,pix.width,pix.height))
        frames[sha]={'matrix':list(mat),'render_size_pixels':[pix.width,pix.height],'render_samples_sha256':hashlib.sha256(pix.samples).hexdigest()}
    matrix=pymupdf.Matrix(frames[ELEV]['matrix']);factor=100*.0254/72;step=math.hypot(matrix.c,matrix.d)*factor
    for view,points in picks.items():
        floor=points['floor'][1]
        traces[view]={'manual_points_pixels':points,'native_points':{k:list(pymupdf.Point(*v)*matrix) for k,v in points.items()},
                      'heights_above_drawn_floor_metres':{k:(floor-v[1])*step for k,v in points.items() if k!='floor'},
                      'endpoint_sampling_bound_pixels':2,'two_endpoint_height_sampling_bound_metres':4*step}
    ne=traces['NE']['heights_above_drawn_floor_metres'];se=traces['SE']['heights_above_drawn_floor_metres']
    fascia=ne['front-top']-ne['front-bottom']
    if not 0<fascia<.5 or not ne['rear']>ne['front-top']>ne['front-bottom']:raise ValueError('Invalid canopy height ordering')
    roof_matrix=pymupdf.Matrix(frames[ROOF]['matrix'])
    def metric(point):return np.array(list(pymupdf.Point(*point)*roof_matrix))*factor
    corners=np.array([metric(p) for p in [[460,594],[663,798],[396,1064],[193,861]]]);centre=corners.mean(axis=0)
    u=corners[2]-corners[1];u/=np.linalg.norm(u);v=np.array([-u[1],u[0]])
    if np.dot(v,corners[1]-corners[0])<0:v=-v
    projection_pixels=[[522,654],[615,749],[631,733],[538,638]]
    local=[[float(np.dot(metric(p)-centre,u)),float(np.dot(metric(p)-centre,v))] for p in projection_pixels]
    model=json.loads(Path(wall_path).read_text());outline=model['outer_wall_base_outline']
    back_x=(outline[0][0]+outline[1][0])/2
    front_x=sum(p[0] for p in local[2:])/2;y0,y1=sorted([p[1] for p in local[2:]])
    if front_x>=back_x:raise ValueError('Canopy must extend outward from NE end wall')
    roof_points=[[back_x,y0,ne['rear']],[back_x,y1,ne['rear']],[front_x,y1,ne['front-top']],[front_x,y0,ne['front-top']]]
    front_points=[[front_x,y0,ne['front-bottom']],[front_x,y1,ne['front-bottom']],[front_x,y1,ne['front-top']],[front_x,y0,ne['front-top']]]
    vertices=roof_points+front_points
    model['projection_surfaces']=[{'role':'canopy-roof','vertices':roof_points},{'role':'front-fascia','vertices':front_points}]
    model['projection_mesh']={'vertices':vertices,'triangles':[[0,1,2],[0,2,3],[4,5,6],[4,6,7]],'watertight':False}
    model['projection_review']={'source_frames':frames,'elevation_traces':traces,'roof_plan_points_pixels':projection_pixels,'roof_plan_local_points':local,
        'height_choice':'NE front and rear roof/fascia edges; preserves NE entrance-head relationship. SE differences retained, not averaged.',
        'front_height_NE_minus_SE_metres':ne['front-top']-se['front-top'],'combined_two_view_sampling_bound_metres':8*step,
        'fascia_height_metres':fascia,'wall_to_front_depth_metres':back_x-front_x,'width_metres':y1-y0,
        'slope_degrees':math.degrees(math.atan2(ne['rear']-ne['front-top'],back_x-front_x)),
        'attachment_hypothesis':'rear plane at NE wall, front plan edge retained; rear attachment hidden under main-roof overhang',
        'physical_identity_verified':False}
    model['projection_input_wall_sha256']=hashlib.sha256(Path(wall_path).read_bytes()).hexdigest()
    model['unresolved']=['cross-view canopy front-height discrepancy','roof/wall centring and 180-degree source correspondence','side fascia, wall thickness and construction details','cladding/bunding geometry','as-built identity and floor datum','independent geographic registration']
    return model

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['pdf-directory','walls','output']:p.add_argument('--'+k,required=True)
    a=p.parse_args();r=build(a.pdf_directory,a.walls);Path(a.output).write_text(json.dumps(r,indent=2)+'\n');print('Added two provisional projection surfaces; zero world geometry')

if __name__=='__main__':main()
