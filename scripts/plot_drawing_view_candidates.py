"""Plot candidate layout rectangles, without reproducing original plan artwork."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import shape

from voxel_mapper.drawing_geometry import native_inverse
from voxel_mapper.generation_cycles import file_hash


def plot(pack,pdfs,output):
    pack=Path(pack);pdfs=Path(pdfs);data=json.loads((pack/'view-candidates.json').read_text())
    pages=[p for p in data['pages'] if p['views']]
    if not pages:raise ValueError('View candidates required')
    figure,axes=plt.subplots(1,len(pages),figsize=(5*len(pages),5.3),squeeze=False)
    for axis,record in zip(axes[0],pages):
        sha=record['document_sha256'];path=pdfs/(sha+'.pdf')
        if file_hash(path)!=sha:raise ValueError('Original source changed')
        with pymupdf.open(path) as document:
            page=document[record['page']-1];m=(~native_inverse(page))*page.rotation_matrix
            affine=[m.a,m.c,m.b,m.d,m.e,m.f];width,height=page.rect.width,page.rect.height
        axis.add_patch(plt.Rectangle((0,0),width,height,facecolor='#f7f7f3',edgecolor='#87908b'))
        for i,view in enumerate(record['views']):
            g=affine_transform(shape(view['geometry']),affine);x,y=g.exterior.xy
            color='#3b899c' if view['printed_claim']['view_kind']=='elevation' else '#72976d'
            axis.fill(x,y,facecolor=color,alpha=.28,edgecolor=color,linewidth=1.5)
            point=g.representative_point();label=view['caption_text'].replace(' to the ','\nto the ')
            axis.text(point.x,point.y,label,ha='center',va='center',fontsize=8,color='#263a38')
        axis.set_xlim(-30,width+30);axis.set_ylim(height+30,-30);axis.set_aspect('equal');axis.axis('off')
        axis.set_title(sha[:10]+'… • page '+str(record['page']),fontsize=10)
    figure.suptitle('Automatic source-view candidates • Wicker shop',fontsize=16,y=.96)
    figure.text(.5,.08,'Visible-caption and white-corridor layout hints; these rectangles are not verified physical view boundaries.',ha='center',fontsize=9)
    figure.text(.5,.035,'Original source artwork omitted. Nominal drawing coordinates do not establish surveyed placement, building dimensions or construction state.',ha='center',fontsize=8,color='#59645d')
    figure.subplots_adjust(left=.02,right=.98,bottom=.17,top=.85,wspace=.12)
    Path(output).parent.mkdir(parents=True,exist_ok=True);figure.savefig(output,dpi=160);plt.close(figure)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack',type=Path,required=True);parser.add_argument('--pdf-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();plot(args.pack,args.pdf_root,args.output)
