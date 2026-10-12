"""Render exposed native-study voxel faces; this is not an in-game screenshot."""
import argparse,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection


def render(directory,output,boundary=False):
    fig=plt.figure(figsize=(14,12) if boundary else (14,7),facecolor='#f5f7fa')
    colors={'spruce_planks':'#bd946a','dark_oak_planks':'#574336'}
    colors.update(dark_oak_slab='#574336',dark_oak_slab_top='#574336')
    colors['dark_oak_fence']='#574336'
    colors.update({f'spruce_trapdoor_{d}':'#ad8054' for d in ('north','east','south','west')})
    directions=[(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]
    faces=[[(1,0,0),(1,1,0),(1,1,1),(1,0,1)],[(0,0,0),(0,0,1),(0,1,1),(0,1,0)],
           [(0,1,0),(0,1,1),(1,1,1),(1,1,0)],[(0,0,0),(1,0,0),(1,0,1),(0,0,1)],
           [(0,0,1),(1,0,1),(1,1,1),(0,1,1)],[(0,0,0),(0,1,0),(1,1,0),(1,0,0)]]
    scales=[s for s in (1,4) if (Path(directory)/f'study-{s}'/'voxels.jsonl').exists()]
    views=[(s,a) for a in ((-50,130) if boundary else (-50,)) for s in scales]
    for panel,(scale,angle) in enumerate(views,1):
        ax=fig.add_subplot(2 if boundary else 1,len(scales),panel,projection='3d');cells={}
        for line in (Path(directory)/f'study-{scale}'/'voxels.jsonl').read_text().splitlines():
            r=json.loads(line)
            if r['kind']=='study_surface':cells[(r['x'],r['y'],r['z'])]=r['material']
        polygons=[];palette=[]
        for (x,y,z),material in sorted(cells.items()):
            xlo,zlo=0,0;xhi,zhi=1,1
            if material.endswith('_fence'):xlo=zlo=.375;xhi=zhi=.625
            if '_trapdoor_' in material:
                direction=material.rsplit('_',1)[1]
                if direction=='north':zlo=.8125
                elif direction=='south':zhi=.1875
                elif direction=='west':xlo=.8125
                else:xhi=.1875
            for direction,face in zip(directions,faces):
                neighbour=cells.get(tuple(a+b for a,b in zip((x,y,z),direction)))
                partial=any(t in material for t in ('slab','fence','trapdoor'))
                if neighbour and not partial and not any(t in neighbour for t in ('slab','fence','trapdoor')):continue
                lo=.5 if material.endswith('_slab_top') else 0
                height=.5 if 'slab' in material else 1
                polygons.append([((x+xlo+dx*(xhi-xlo))/scale,(z+zlo+dz*(zhi-zlo))/scale,(y+lo+dy*height)/scale) for dx,dy,dz in face]);palette.append(colors[material])
        ax.add_collection3d(Poly3DCollection(polygons,facecolors=palette,edgecolors='#342b23',linewidths=.12))
        ax.set_xlim(-10,10);ax.set_ylim(-8,8);ax.set_zlim(0,9);ax.set_box_aspect((20,16,9));ax.view_init(elev=20,azim=angle)
        ax.set_xlabel('Local long axis (m)');ax.set_ylabel('Local short axis (m)');ax.set_zlabel('Above study zero (m)')
        ax.set_title(f'{scale}:1 study · {len(cells):,} surface cells',pad=16)
    title='Wicker shop · 1:1 shape review · both sides' if boundary else 'Wicker shop · isolated proposed-drawing surface study'
    fig.suptitle(title,fontsize=18,y=.96)
    fig.text(.5,.03,'Voxel preview, not an in-game screenshot · illustrative palette · centring/orientation and NW door remain unresolved',ha='center',fontsize=10)
    fig.subplots_adjust(left=.03,right=.97,top=.85,bottom=.12,wspace=.06);fig.savefig(output,dpi=150);plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();render(a.directory,a.output)
