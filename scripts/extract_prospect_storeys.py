"""Hash-pinned extraction of reviewed upper Prospect floor members; local metres."""
import argparse,hashlib,json
from pathlib import Path
import pymupdf as fitz
import numpy as np
from affine import Affine
from rasterio.features import shapes
from shapely.geometry import shape,mapping
from shapely.ops import unary_union

RECIPES={
 '89794':{'sha256':'8b07a06706e5dc3c436889c2d285f7c5d47855d7a80c08ede5237983b508c7fe','sheet':'AL3.03 Rev B','center':[552.72,523.0792236328125],'indices':list(range(24))},
 '89795':{'sha256':'122058b4a585b267cf6a5a29ad8bd1b33c6165f0bc1ede9a173f45d6c1bfd26d','sheet':'AL3.04 Rev B','center':[559.7999877929688,560.1592407226562],'indices':list(range(9))+[153,168,183,198,213,228,243]},
}
SCALE=20*.0254/72


def extract(pdf_directory):
    storeys=[]
    for identifier,recipe in RECIPES.items():
        content=(Path(pdf_directory)/(identifier+'.pdf')).read_bytes()
        if hashlib.sha256(content).hexdigest()!=recipe['sha256']:raise ValueError('Reviewed floor drawing hash changed')
        with fitz.open(stream=content,filetype='pdf') as doc:
            page=doc[0];drawings=page.get_drawings();parts=[]
            for index in recipe['indices']:
                d=drawings[index];fill=d.get('fill');r=d['rect']
                if not fill or any(abs(v-.5898439884185791)>1e-5 for v in fill) or r.y1>800:
                    raise ValueError('Reviewed member fill or viewport changed')
                with fitz.open() as canvas:
                    target=canvas.new_page(width=page.rect.width,height=page.rect.height);pen=target.new_shape()
                    for it in d['items']:
                        if it[0]=='l':pen.draw_line(it[1],it[2])
                        elif it[0]=='c':pen.draw_bezier(*it[1:])
                        elif it[0]=='re':pen.draw_rect(it[1])
                        elif it[0]=='qu':pen.draw_quad(it[1])
                        else:raise ValueError('Unsupported drawing operation')
                    pen.finish(fill=(0,0,0),color=None,even_odd=d.get('even_odd',False),closePath=d.get('closePath',False));pen.commit()
                    pix=target.get_pixmap(matrix=fitz.Matrix(2,2),clip=fitz.Rect(r.x0-1,r.y0-1,r.x1+1,r.y1+1),colorspace=fitz.csGRAY)
                    mask=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width)<128
                    cx,cy=recipe['center'];tr=Affine(SCALE/2,0,(pix.x/2-cx)*SCALE,0,-SCALE/2,(cy-pix.y/2)*SCALE)
                    geom=unary_union([shape(g) for g,v in shapes(mask.astype('uint8'),mask=mask,transform=tr) if v==1]).simplify(.005,preserve_topology=True)
                    if geom.is_empty or not geom.is_valid:raise ValueError('Invalid member footprint')
                    parts.append({'id':f"{recipe['sheet']}/path-{index}",'path_index':index,'paper_bbox':list(r),'geometry':mapping(geom),'area_m2':geom.area})
            storeys.append({'sheet':recipe['sheet'],'source_sha256':recipe['sha256'],'source_url':f'https://publicaccess.staffsmoorlands.gov.uk/portal/servlets/AttachmentShowServlet?ImageName={identifier}', 'paper_center':recipe['center'],'components':parts})
    return {'frame':'local metres; paper north up; stair centre origin','scale_denominator':20,'registration':'relative profiles only; geographic placement withheld','storeys':storeys}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pdf-directory',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    out=Path(a.output)
    if out.exists():raise ValueError('Use new output file')
    out.write_text(json.dumps(extract(a.pdf_directory),indent=2)+'\n')
