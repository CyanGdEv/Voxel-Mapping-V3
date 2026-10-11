"""Render seven explicitly reviewed window cycles and their parent traces."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
import pymupdf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def render(source,report_path,seed_path,output):
    report=json.loads(Path(report_path).read_text());seed=json.loads(Path(seed_path).read_text())
    review=seed['opening_cycle_review']
    if (hashlib.sha256(Path(report_path).read_bytes()).hexdigest()!=review['outline_report_sha256'] or
        hashlib.sha256(Path(source).read_bytes()).hexdigest()!=report['source_pdf_sha256']['elevation']):
        raise ValueError('Matching source and outline review required')
    with pymupdf.open(source) as doc:
        page=doc[seed['documents']['elevation']['page']-1];s=seed['documents']['elevation']['render_width_pixels']/page.rect.width
        pix=page.get_pixmap(matrix=pymupdf.Matrix(s,s),alpha=False)
        image=np.frombuffer(pix.samples,np.uint8).reshape(pix.height,pix.width,pix.n)
    fig,axes=plt.subplots(2,4,figsize=(16,9),facecolor='#101927')
    for ax,change in zip(axes.flat,review['window_revisions']):
        before=np.array(change['parent_points_pixels']);after=np.array(change['reviewed_points_pixels'])
        allpoints=np.vstack([before,after]);lo=allpoints.min(axis=0);hi=allpoints.max(axis=0)
        ax.imshow(image);ax.set_xlim(lo[0]-10,hi[0]+10);ax.set_ylim(hi[1]+10,lo[1]-10);ax.set_axis_off()
        for pts,color,style in [(before,'#de981f','--'),(after,'#00a7b9','-')]:
            pts=np.vstack([pts,pts[0]]);ax.plot(pts[:,0],pts[:,1],c=color,ls=style,lw=1.3)
        ax.set_title(change['id'],color='white',fontsize=13)
    axes.flat[-1].set_axis_off();axes.flat[-1].text(.05,.65,'Cyan: reviewed source cycle\nAmber: previous trace\n\nOriginal source edges retained.\nNo synthetic window connector.\n\nDrawing silhouette review;\nphysical aperture extents\nremain unverified.',color='white',fontsize=13,linespacing=1.5)
    fig.suptitle('MUTINY BAY · SEVEN WINDOW OUTLINE REVISIONS',color='white',fontsize=20)
    fig.subplots_adjust(top=.9,bottom=.06,wspace=.15,hspace=.25)
    fig.savefig(output,dpi=160,facecolor=fig.get_facecolor());plt.close(fig)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','report','seed','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();render(a.source,a.report,a.seed,a.output)
