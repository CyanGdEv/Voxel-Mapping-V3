"""Render local surveyed surfaces, with no geographic pose or invented hidden walls."""
import argparse,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection


def render(model_path,output):
    model=json.loads(Path(model_path).read_text());m=model['measurements'];length=model['width_check']['elevation_length_m']
    fig=plt.figure(figsize=(15,8),facecolor='#0b1420');ax=fig.add_axes([.025,.10,.95,.76],projection='3d',computed_zorder=False)
    ax.set_facecolor('#0b1420');ax.set_proj_type('ortho');ax.view_init(elev=23,azim=-66)
    for key,color in [('wall_mesh','#c4b99b'),('roof_mesh','#67798b')]:
        mesh=model[key];tris=[[mesh['vertices'][i] for i in f] for f in mesh['triangles']]
        ax.add_collection3d(Poly3DCollection(tris,facecolors=color,linewidths=0,shade=True,zorder=3 if key=='roof_mesh' else 2),autolim=False)
    # Only the measured courtyard wall is present; aperture edges remain visible.
    for opening in model['openings']:
        pts=opening['local_polygon_xz'];ax.plot([p[0] for p in pts],[0]*len(pts),[p[1] for p in pts],color='#f0d89a',lw=.5,zorder=4)
    ax.set_xlim(-1,length+1);ax.set_ylim(-1,m['depth_m']+1);ax.set_zlim(-.5,m['ridge_m']+1)
    ax.set_box_aspect((length,m['depth_m']+2,m['ridge_m']+1),zoom=1.05);ax.set_axis_off()
    fig.text(.05,.93,'MUTINY BAY · NORTH COURTYARD RANGE',color='#a6b9cf',fontsize=12,weight='bold')
    fig.text(.05,.87,'First vertical reconstruction study',color='#eef5fc',fontsize=25,weight='bold')
    fig.text(.05,.82,f"Frontage {length:.2f} m · eaves {m['eaves_m']:.2f} m · ridge {m['ridge_m']:.2f} m above drawn floor",color='#a6b9cf',fontsize=12)
    fig.text(.05,.095,'16 traced openings retained, including archway 3. Courtyard wall + main roof candidate; other faces omitted.',color='#d2dfed',fontsize=11)
    fig.text(.05,.052,'Reviewed drawing traces · cross-date roof assembly hypothesis · no geographic placement · display colours',color='#94a9c2',fontsize=10)
    fig.savefig(output,dpi=180,facecolor=fig.get_facecolor());plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();render(a.model,a.output)
