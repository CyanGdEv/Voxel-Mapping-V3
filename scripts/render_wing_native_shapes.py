#!/usr/bin/env python3
"""Render exact exposed half-cell faces of exported native stair/slab shapes."""
import argparse
import io
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from PIL import Image,ImageChops,ImageDraw,ImageFont
from voxel_mapper.wing_block_shapes import occupied_halves


def render(path):
    rows=[json.loads(line) for line in Path(path).read_text().splitlines()]
    cells={(r['x'],r['y'],r['z']):r['material'] for r in rows if r['kind']=='review_surface'}
    half=occupied_halves(cells);faces=[];colors=[]
    for (x,y,z),material in half.items():
        # Render coordinates are frontage, depth, height.
        origin=[x/2,z/2,y/2]
        for axis in range(3):
            for side in (0,1):
                neighbor=[x,y,z];neighbor[[0,2,1][axis]]+=1 if side else -1
                adjacent=half.get(tuple(neighbor))
                if adjacent is not None and (adjacent=='glass')==(material=='glass'):continue
                others=[i for i in range(3) if i!=axis];face=[]
                for a,b in [(0,0),(1,0),(1,1),(0,1)]:
                    point=origin.copy();point[axis]+=.5*side
                    point[others[0]]+=.5*a;point[others[1]]+=.5*b;face.append(point)
                color=(.43,.49,.56,1) if material.startswith('stone') else (.34,.22,.13,1)
                if material=='glass':color=(.27,.70,.82,.30)
                shade=[.85,.72,1][axis]
                faces.append(face);colors.append(tuple(v*shade for v in color[:3])+(color[3],))
    fig=plt.figure(figsize=(16,6),dpi=180,facecolor='white');ax=fig.add_subplot(111,projection='3d')
    ax.add_collection3d(Poly3DCollection(faces,facecolors=colors,edgecolors=(.13,.16,.19,.18),linewidths=.18))
    ax.set(xlim=(0,33),ylim=(0,7),zlim=(0,8));ax.set_box_aspect((33,7,8))
    ax.view_init(elev=13,azim=-72);ax.set_proj_type('ortho');ax.set_axis_off()
    buffer=io.BytesIO();fig.savefig(buffer,facecolor='white',bbox_inches='tight',pad_inches=0);plt.close(fig)
    image=Image.open(buffer).convert('RGB')
    bounds=ImageChops.difference(image,Image.new('RGB',image.size,'white')).getbbox()
    return image.crop(bounds)


def main():
    p=argparse.ArgumentParser();p.add_argument('--before',required=True);p.add_argument('--after',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    panels=[render(a.before),render(a.after)];width=1800
    panels=[im.resize((width,round(im.height*width/im.width)),Image.Resampling.LANCZOS) for im in panels]
    font_path='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    title=ImageFont.truetype(font_path,36);small=ImageFont.truetype(font_path,23)
    image=Image.new('RGB',(width+100,sum(im.height for im in panels)+290),'white');d=ImageDraw.Draw(image);y=32
    for im,label in zip(panels,['Previous export | full blocks','Native shapes V2 | slabs, stairs and illustrative glazing']):
        d.text((50,y),label,font=title,fill='#172534');y+=65;image.paste(im,(50,y));y+=im.height+35
    d.text((50,y),'Exact exported block shapes at 1 block per metre. Partial facade and roof; end/rear walls unresolved.',font=small,fill='#485565')
    d.text((50,y+35),'Glass setback is illustrative. The source mesh is unchanged; this export still needs an in-game check.',font=small,fill='#485565')
    Path(a.output).parent.mkdir(parents=True,exist_ok=True);image.save(a.output)

if __name__=='__main__':main()
