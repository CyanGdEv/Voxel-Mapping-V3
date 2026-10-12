"""Draw a block-geometry preview; this is not an in-game screenshot."""
import argparse,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

COLORS={'sandstone':'#ead8a9','sandstone_wall':'#ead8a9','sandstone_slab_top':'#ead8a9','red_terracotta':'#944941','green_stained_glass_pane':'#507450','stone':'#929395','stone_slab':'#a3a4a6','iron_bars':'#7f5250'}

def faces(row):
    x,y,z=row['x'],row['y'],row['z'];m=row['material'];dx=dz=1;dy=1
    if m.endswith('_wall'):dx=dz=.25
    if m=='iron_bars':dx=dz=.16
    if m=='green_stained_glass_pane':dz=.12
    if 'slab' in m:
        dy=.5
        if m.endswith('_top'):y+=.5
    x+=(1-dx)/2;z+=(1-dz)/2
    p=[(x,z,y),(x+dx,z,y),(x+dx,z+dz,y),(x,z+dz,y),(x,z,y+dy),(x+dx,z,y+dy),(x+dx,z+dz,y+dy),(x,z+dz,y+dy)]
    return [[p[i] for i in ids] for ids in ((0,1,2,3),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7))]

def render(inputs,output):
    fig=plt.figure(figsize=(12,8),facecolor='#faf8f3')
    for index,path in enumerate(inputs):
        rows=[json.loads(line) for line in Path(path).read_text().splitlines()];rows=[r for r in rows if r['kind']=='structure']
        ax=fig.add_subplot(1,len(inputs),index+1,projection='3d');ax.set_facecolor('#faf8f3')
        polygons=[];colors=[]
        for r in rows:
            f=faces(r);polygons.extend(f);colors.extend([COLORS.get(r['material'],'#999999')]*len(f))
        ax.add_collection3d(Poly3DCollection(polygons,facecolors=colors,edgecolors='#55483d',linewidths=.10,alpha=.95))
        bound=max(max(abs(r['x']),abs(r['z'])) for r in rows)+2;height=max(r['y'] for r in rows)+2
        ax.set_xlim(-bound,bound);ax.set_ylim(-bound,bound);ax.set_zlim(-1,height);ax.set_box_aspect((bound*2,bound*2,height))
        ax.view_init(elev=17,azim=-58);ax.set_axis_off();ax.set_title('1:1 block study' if index==0 else '4:1 enlarged study',fontsize=15,pad=12)
    fig.suptitle('Prospect Tower — relative reconstruction study',fontsize=21,y=.95)
    fig.text(.5,.045,'Geometry preview, not an in-game screenshot.\nLocation is withheld; roof, railings, stairs and block colours include approximations.',ha='center',fontsize=11,color='#4a4a4a')
    fig.savefig(output,dpi=150,bbox_inches='tight');plt.close(fig)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--voxels',nargs='+',required=True);p.add_argument('--output',required=True);a=p.parse_args();render(a.voxels,a.output)
