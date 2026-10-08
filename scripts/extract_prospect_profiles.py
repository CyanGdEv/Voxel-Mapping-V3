"""Extract reviewed Prospect Tower GF grey member footprints in a local frame.

Run with the retained AL3.02 PDF and a new JSON output path. Not geographic data.
"""
import argparse,hashlib,json
from pathlib import Path
import pymupdf as fitz
import numpy as np
from affine import Affine
from rasterio.features import shapes
from shapely.geometry import shape,mapping

EXPECTED='51b4bff0df222ab5b6050b3e0b608534b900bf59bd93e4ab17d51c2812731383'
SCALE=20*0.0254/72  # Printed 1:20: paper points -> metres.
CENTER=(1011.12,696.0)  # Reviewed centre of upper ground-floor view, PDF points.


def extract(path):
    content=Path(path).read_bytes()
    if hashlib.sha256(content).hexdigest()!=EXPECTED:raise ValueError('Reviewed AL3.02 source hash differs')
    doc=fitz.open(stream=content,filetype='pdf');page=doc[0]
    parts=[]
    for index,d in enumerate(page.get_drawings()):
        fill=d.get('fill');rect=d['rect']
        if not fill or any(abs(v-.5898439884185791)>1e-5 for v in fill) or rect.y1>=1100:continue
        # Grey members in the upper GF view only. Exclude lower soffit view,
        # report key, title, paving repair overlays and all stroked paths.
        canvas=fitz.open();target=canvas.new_page(width=page.rect.width,height=page.rect.height)
        pen=target.new_shape()
        for item in d['items']:
            if item[0]=='l':pen.draw_line(item[1],item[2])
            elif item[0]=='c':pen.draw_bezier(*item[1:])
            elif item[0]=='re':pen.draw_rect(item[1])
            elif item[0]=='qu':pen.draw_quad(item[1])
            else:raise ValueError('Unsupported reviewed path operation')
        pen.finish(fill=(0,0,0),color=None,even_odd=d.get('even_odd',False),closePath=d.get('closePath',False));pen.commit()
        clip=fitz.Rect(rect.x0-1,rect.y0-1,rect.x1+1,rect.y1+1)
        pix=target.get_pixmap(matrix=fitz.Matrix(2,2),clip=clip,colorspace=fitz.csGRAY,alpha=False)
        mask=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width)<128
        transform=Affine(SCALE/2,0,(pix.x/2-CENTER[0])*SCALE,0,-SCALE/2,(CENTER[1]-pix.y/2)*SCALE)
        from shapely.ops import unary_union
        polygons=[shape(g) for g,value in shapes(mask.astype('uint8'),mask=mask,transform=transform) if value==1]
        geom=unary_union(polygons).simplify(.005,preserve_topology=True)
        if geom.is_empty or not geom.is_valid:raise ValueError('Invalid extracted profile')
        parts.append({'id':f'AL3.02/path-{index}','path_index':index,'paper_bbox':list(rect),
                      'geometry':mapping(geom),'area_m2':geom.area,'semantics':'reviewed GF structural member footprint',
                      'vertical_extent':'not_assigned'})
        canvas.close()
    doc.close()
    if len(parts)!=23:raise ValueError('Reviewed GF member count changed')
    return {'source_sha256':EXPECTED,'application':'SMD/2014/0841','sheet':'AL3.02 Rev B',
            'source_url':'https://publicaccess.staffsmoorlands.gov.uk/portal/servlets/AttachmentShowServlet?ImageName=89793',
            'frame':'local metres; x right/east, z up/north as drawn; origin reviewed stair centre',
            'scale_denominator':20,'scale_status':'measured_from_printed_scale; not independent dimensional survey',
            'absolute_registration':'unregistered','world_geometry_additions':0,'components':parts,
            'limitations':['Existing condition December 2014; current condition unverified',
                           'Sub-block details alias when voxelized','No vertical extents inferred from floor-plan fills',
                           'Not accepted as EPSG:27700 geometry; needs geographic anchor/rotation and measured levels']}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pdf',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    out=Path(a.output)
    if out.exists():raise ValueError('Use a new output file')
    result=extract(a.pdf);out.write_text(json.dumps(result,indent=2));print(json.dumps({'components':len(result['components']),'absolute_registration':result['absolute_registration']}))
