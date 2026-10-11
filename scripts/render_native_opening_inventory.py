"""Render exact source-label/frame audit overlays, never inferred 3D geometry."""
import argparse
import hashlib
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
import pymupdf


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['inventory','recipe','source','output']:p.add_argument('--'+name,required=True,type=Path)
    a=p.parse_args();r=json.loads(a.inventory.read_text());seed=json.loads(a.recipe.read_text())
    if hashlib.sha256(a.source.read_bytes()).hexdigest()!=r['document_sha256'] or hashlib.sha256(a.recipe.read_bytes()).hexdigest()!=r['recipe_sha256']:
        raise ValueError('Pinned audit inputs required')
    spec=seed['documents']['elevation']
    with pymupdf.open(a.source) as doc:
        page=doc[r['page']-1];pix=page.get_pixmap(matrix=pymupdf.Matrix(spec['render_width_pixels']/page.rect.width,spec['render_width_pixels']/page.rect.width))
        if hashlib.sha256(pix.samples).hexdigest()!=spec['render_samples_sha256']:raise ValueError('Pinned raster required')
        img=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,pix.n)
    fig=plt.figure(figsize=(16,9),facecolor='#f5f7fa');grid=fig.add_gridspec(2,2,height_ratios=[1.3,1],hspace=.28,wspace=.13)
    top=fig.add_subplot(grid[0,:]);left=fig.add_subplot(grid[1,0]);right=fig.add_subplot(grid[1,1])
    labels=r['opening_inventory']['labels'];frames={f['id']:f for f in r['frames']['frames']}
    palette={'one_source_frame_layout_candidate':'#1683c5','competing_source_frame_layout_candidates':'#dd9400','no_complete_source_rectangle':'#a03770'}
    def draw(ax,bounds,title):
        ax.imshow(img);ax.set_xlim(bounds[0],bounds[2]);ax.set_ylim(bounds[3],bounds[1]);ax.set_aspect('equal');ax.axis('off');ax.set_title(title,loc='left',fontsize=12,pad=12)
        seen=set()
        for label in labels:
            color=palette.get(label['status'],'#777777')
            for hit in label.get('frame_candidates',[]):
                key=hit['frame_id']
                if key in seen:continue
                seen.add(key);x,y,x1,y1=frames[key]['bounds_pixels']
                ax.add_patch(Rectangle((x,y),x1-x,y1-y,fill=False,color=color,lw=1.1,alpha=.75))
            x,y,x1,y1=label['bounds_pixels'];ax.add_patch(Rectangle((x-1,y-1),x1-x+2,y1-y+2,fill=False,color=color,lw=1.4))
    draw(top,[130,100,1520,432],'Native north-range elevation — 17 visible labels; nearby frame alternatives retained')
    draw(left,[895,312,1150,395],'Seed ID check: left opening is w.3.05; right is w.3.06')
    draw(right,[770,218,942,305],'Coverage gap: w.3.13 has no reviewed aperture trace')
    fig.suptitle('Mutiny Bay | Automatic opening inventory',x=.05,ha='left',fontsize=23,fontweight='bold',y=.97)
    fig.text(.05,.915,'4 labels with one frame candidate  •  7 with competing frames  •  6 without a supported rectangle',fontsize=12,color='#334155')
    fig.text(.05,.045,'Blue: one layout candidate    Amber: competing candidates    Magenta: no source rectangle\nSource cycles may be panes. Reviewed scope; no verified physical apertures or new world geometry.',fontsize=11,color='#334155')
    fig.subplots_adjust(top=.86,bottom=.13,left=.05,right=.96)
    a.output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(a.output,dpi=160,facecolor=fig.get_facecolor());plt.close(fig)


if __name__=='__main__':main()
