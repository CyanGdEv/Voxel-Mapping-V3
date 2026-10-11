"""Render source PDF and explicit gap proposal together, without AI imagery."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
import pymupdf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def render(source,report_path,recipe_path,output):
    report=json.loads(Path(report_path).read_text());recipe=json.loads(Path(recipe_path).read_text())
    if (hashlib.sha256(Path(source).read_bytes()).hexdigest()!=report['document_sha256'] or
        hashlib.sha256(Path(recipe_path).read_bytes()).hexdigest()!=report['recipe_sha256']):
        raise ValueError('Matching checksum-pinned source and proposal recipe required')
    row=next(r for r in report['rows'] if r['seed_id']=='archway-3')
    proposals=row['review']['proposals']
    if len({p['geometry_identity'] for p in proposals})!=1:raise ValueError('Arch review requires one geometry with all provenance variants retained')
    proposal=proposals[0];gap_ids={p['gap_id'] for p in proposal['hypothesis_interval_proofs']}
    gaps=[g for g in row['review']['gaps'] if g['id'] in gap_ids]
    with pymupdf.open(source) as doc:
        page=doc[report['page']-1] if 'page' in report else doc[recipe['documents']['elevation']['page']-1]
        s=recipe['documents']['elevation']['render_width_pixels']/page.rect.width
        pix=page.get_pixmap(matrix=pymupdf.Matrix(s,s),alpha=False)
        image=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,pix.n)
    fig,axes=plt.subplots(1,2,figsize=(15,8),gridspec_kw={'width_ratios':[2.2,1]},facecolor='#101927')
    for ax in axes:
        ax.imshow(image);ax.set_facecolor('white');ax.set_axis_off()
    axes[0].set_xlim(730,925);axes[0].set_ylim(420,270)
    pts=np.array(proposal['geometry_pixels']['coordinates'][0]);axes[0].plot(pts[:,0],pts[:,1],c='#00a9bc',lw=1.4)
    previous=np.array(next(o for o in recipe['openings'] if o['id']=='archway-3')['points_pixels'])
    previous=np.vstack([previous,previous[0]]);axes[0].plot(previous[:,0],previous[:,1],c='#d78515',lw=1,ls='--')
    for gap in gaps:
        points=np.array([e['pixel_point'] for e in gap['endpoints']])
        for ax in axes:ax.plot(points[:,0],points[:,1],c='#e32843',lw=3,marker='o',markersize=3)
    center=np.mean(points,axis=0);axes[1].set_xlim(center[0]-1.5,center[0]+1.5);axes[1].set_ylim(center[1]+1.5,center[1]-1.5)
    fig.suptitle('MUTINY BAY · SOURCE ARCH OUTLINE REVIEW',color='white',fontsize=20,y=.97)
    axes[0].set_title('Cyan: source-network proposal · amber: previous trace',color='white',fontsize=11,pad=12)
    axes[1].set_title('Right spring · connector magnified',color='white',fontsize=11,pad=12)
    fig.text(.06,.05,f"One {gaps[0]['distance_pixels']:.3f} px hypothesis connector · two provenance variants, one shape · no original endpoint moved",color='white',fontsize=11)
    fig.text(.06,.018,'Partial drawing reconstruction review. Connector and physical opening identity remain provisional.',color='#b5c5d8',fontsize=10)
    fig.subplots_adjust(top=.88,bottom=.11,wspace=.08);fig.savefig(output,dpi=160,facecolor=fig.get_facecolor());plt.close(fig)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','report','recipe','output'):parser.add_argument('--'+name,required=True)
    a=parser.parse_args();render(a.source,a.report,a.recipe,a.output)
