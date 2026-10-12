"""Plot retained footprint hypotheses, not accepted geographic geometry."""
import argparse,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams['svg.hashsalt']='wicker-shop-model-lidar'
matplotlib.rcParams['svg.fonttype']='none'
import matplotlib.pyplot as plt
import numpy as np

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--review',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    report=json.loads(Path(a.review).read_text());fig,axes=plt.subplots(1,2,figsize=(11,5))
    for ax,row in zip(axes,report['envelopes']):
        coords=np.array(row['observed_envelope_geometry']['coordinates'][0]);origin=coords.mean(axis=0)
        q=coords-origin;ax.fill(q[:,0],q[:,1],facecolor='#dde6ee',edgecolor='#273c50',label='LiDAR convex envelope')
        for i,h in enumerate(row['hypotheses'][:2]):
            color=['#087bb5','#bf5c26'][i]
            for key,label in [('placed_main_roof_geometry','Main roof'),('placed_canopy_geometry','Canopy')]:
                q=np.array(h[key]['coordinates'][0])-origin
                ax.plot(q[:,0],q[:,1],color=color,linestyle='-' if key.startswith('placed_main') else '--',label=f'{label}, hypothesis {i+1}')
        ax.set_title(f"{row['point_count']} returns · best main-roof IoU {row['hypotheses'][0]['main_roof_iou']:.1%}")
        ax.set_aspect('equal');ax.set_xlabel('Easting from local plot origin (m)');ax.set_ylabel('Northing from local plot origin (m)');ax.legend(fontsize=8);ax.grid(alpha=.2)
    fig.suptitle('Proposed roof vs dated LiDAR · boundary self-fit hypotheses, not verified registration')
    fig.tight_layout();fig.savefig(a.output,metadata={'Date':None});plt.close(fig)
    if Path(a.output).suffix=='.svg':
        output=Path(a.output);output.write_text('\n'.join(line.rstrip() for line in output.read_text().splitlines())+'\n')

if __name__=='__main__':main()
