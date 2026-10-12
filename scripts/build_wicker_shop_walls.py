"""Add source-traced proposed wall surfaces to the local shop hypothesis."""
import argparse,hashlib,json,math,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymupdf
from voxel_mapper.drawing_page_tools import pixel_to_native

SOURCE='d1a7251596b240489c145e76ac06f94448c76972b156f64b4a985753c532c0b6'

def build(pdf,annotation_path,preview_path):
    if hashlib.sha256(Path(pdf).read_bytes()).hexdigest()!=SOURCE:raise ValueError('Elevation PDF checksum mismatch')
    a=json.loads(Path(annotation_path).read_text());model=json.loads(Path(preview_path).read_text())
    if a['source_sha256']!=SOURCE:raise ValueError('Annotation source mismatch')
    with pymupdf.open(pdf) as doc:
        page=doc[0];pix=page.get_pixmap(matrix=pymupdf.Matrix(1888/page.rect.width,1888/page.rect.width))
        if [pix.width,pix.height]!=a['render_size_pixels'] or hashlib.sha256(pix.samples).hexdigest()!=a['render_samples_sha256']:raise ValueError('Annotated render changed')
        matrix=pymupdf.Matrix(pixel_to_native(page,pix.width,pix.height))
    metre_per_pixel=math.hypot(matrix.c,matrix.d)*100*.0254/72
    measurements={}
    for key,row in a['vertical_traces'].items():
        top,bottom=row['top_pixel'],row['bottom_pixel']
        if not (0<=top[1]<bottom[1]<pix.height):raise ValueError('Invalid vertical trace')
        value=(bottom[1]-top[1])*metre_per_pixel;bound=4*metre_per_pixel
        measurements[key]={**row,'native_points':[list(pymupdf.Point(*p)*matrix) for p in [top,bottom]],'height_metres':value,'manual_sampling_interval_metres':[value-bound,value+bound]}
    # One shoulder/apex representative keeps the preview connected. Every traced
    # shoulder and apex must agree with it within that trace's sampling interval.
    shoulder=measurements['SW-shoulder']['height_metres'];apex=measurements['SW-apex']['height_metres']
    for key in ['SE-shoulder','NW-shoulder','NE-shoulder']:
        lo,hi=measurements[key]['manual_sampling_interval_metres']
        if not lo<=shoulder<=hi:raise ValueError('Wall shoulder views conflict')
    lo,hi=measurements['NE-apex']['manual_sampling_interval_metres']
    if not lo<=apex<=hi:raise ValueError('Gable apex views conflict')
    mappings={'opening-SW':'SW-opening','opening-NE':'NE-opening','door-NW':'NW-door'}
    for opening in model['opening_base_segments']:
        h=measurements[mappings[opening['id']]]['height_metres']
        if not 0<h<shoulder:raise ValueError('Opening height exceeds wall shoulder')
        opening['height_metres']=h;opening['height_trace']=mappings[opening['id']]
    vertices=[];triangles=[];panels=[]
    def panel(points,role,edge):
        offset=len(vertices);vertices.extend(points)
        faces=[[offset,offset+1,offset+2]]
        if len(points)==4:faces.append([offset,offset+2,offset+3])
        triangles.extend(faces);panels.append({'role':role,'edge':edge,'vertices':points,'triangle_indices':faces})
    for segment in model['wall_base_segments']:
        start,end=segment['start'],segment['end'];segment['height_metres']=shoulder
        panel([start,end,[end[0],end[1],shoulder],[start[0],start[1],shoulder]],'solid-wall',segment['edge'])
    for opening in model['opening_base_segments']:
        start,end=opening['endpoints'];h=opening['height_metres'];edge={'opening-NE':0,'opening-SW':2,'door-NW':3}[opening['id']]
        panel([[start[0],start[1],h],[end[0],end[1],h],[end[0],end[1],shoulder],[start[0],start[1],shoulder]],'lintel-wall',edge)
    outline=model['outer_wall_base_outline']
    for edge in [0,2]:
        start,end=outline[edge],outline[(edge+1)%4]
        panel([[start[0],start[1],shoulder],[end[0],end[1],shoulder],[(start[0]+end[0])/2,(start[1]+end[1])/2,apex]],'gable-wall',edge)
    model['wall_surfaces']=panels
    model['wall_mesh']={'vertices':vertices,'triangles':triangles,'watertight':False,'wall_thickness_metres':None}
    model['vertical_measurements']=measurements
    model['representative_wall_heights_metres']={'shoulder':shoulder,'gable_apex':apex}
    model['vertical_input_sha256']={str(p):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in [annotation_path,preview_path]}
    model['unresolved']=['roof/wall centring and 180-degree source correspondence','fascia, wall thickness and roof projection depth','cladding/bunding geometry','as-built identity and floor datum','independent geographic registration']
    model['surface_status']='proposed_local_hypothesis; source-traced heights, no world placement'
    return model

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('pdf','annotations','preview','output'):p.add_argument('--'+k,required=True)
    a=p.parse_args();r=build(a.pdf,a.annotations,a.preview);Path(a.output).write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({'wall_panels':len(r['wall_surfaces']),'wall_triangles':len(r['wall_mesh']['triangles']),'world_geometry_additions':0}))

if __name__=='__main__':main()
