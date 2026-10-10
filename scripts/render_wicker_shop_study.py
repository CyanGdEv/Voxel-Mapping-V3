"""Render exposed native-study voxel faces; this is not an in-game screenshot."""
import argparse,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection


def render(directory,output):
    fig=plt.figure(figsize=(14,7),facecolor='#f5f7fa')
    colors={'spruce_planks':'#bd946a','dark_oak_planks':'#574336'}
    directions=[(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]
    faces=[[(1,0,0),(1,1,0),(1,1,1),(1,0,1)],[(0,0,0),(0,0,1),(0,1,1),(0,1,0)],
           [(0,1,0),(0,1,1),(1,1,1),(1,1,0)],[(0,0,0),(1,0,0),(1,0,1),(0,0,1)],
           [(0,0,1),(1,0,1),(1,1,1),(0,1,1)],[(0,0,0),(0,1,0),(1,1,0),(1,0,0)]]
    for panel,scale in enumerate((1,4),1):
        ax=fig.add_subplot(1,2,panel,projection='3d');cells={}
        for line in (Path(directory)/f'study-{scale}'/'voxels.jsonl').read_text().splitlines():
            r=json.loads(line)
            if r['kind']=='study_surface':cells[(r['x'],r['y'],r['z'])]=r['material']
        polygons=[];palette=[]
        for (x,y,z),material in sorted(cells.items()):
            for direction,face in zip(directions,faces):
                if tuple(a+b for a,b in zip((x,y,z),direction)) in cells:continue
                polygons.append([((x+dx)/scale,(z+dz)/scale,(y+dy)/scale) for dx,dy,dz in face]);palette.append(colors[material])
        ax.add_collection3d(Poly3DCollection(polygons,facecolors=palette,edgecolors='#342b23',linewidths=.12))
        ax.set_xlim(-10,10);ax.set_ylim(-8,8);ax.set_zlim(0,9);ax.set_box_aspect((20,16,9));ax.view_init(elev=20,azim=-50)
        ax.set_xlabel('Local long axis (m)');ax.set_ylabel('Local short axis (m)');ax.set_zlabel('Above study zero (m)')
        ax.set_title(f'{scale}:1 study · {len(cells):,} surface cells',pad=16)
    fig.suptitle('Wicker shop · isolated proposed-drawing surface study',fontsize=18,y=.96)
    fig.text(.5,.03,'Voxel preview, not an in-game screenshot · illustrative palette · centring/orientation and NW door remain unresolved',ha='center',fontsize=10)
    fig.subplots_adjust(left=.03,right=.97,top=.85,bottom=.12,wspace=.06);fig.savefig(output,dpi=150);plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();render(a.directory,a.output)
