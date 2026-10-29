"""Simplified isometric previews of saved block crops; not client screenshots."""
from PIL import Image,ImageDraw
import numpy as np

COLOURS={'oak_planks':(177,139,83),'spruce_planks':(125,87,48),'oak_log':(145,104,54),
    'dark_oak_planks':(57,39,26),'oak_slab':(177,139,83),'oak_slab_top':(177,139,83),
    'dark_oak_fence':(70,45,28),'oak_fence':(170,132,75),'spruce_fence':(110,74,41),
    'oak_leaves':(48,94,43),'spruce_leaves':(34,73,39),'birch_leaves':(68,109,46),
    'grass_block':(93,127,63),'stone':(134,136,130),'dirt':(113,78,51),'black_concrete':(33,34,32),
    'stone_bricks':(139,141,134),'gray_concrete':(89,92,91),'gray_wool':(85,87,84),
    'cobblestone':(121,123,117),'terracotta':(155,91,65),'mud_bricks':(137,104,77),
    'smooth_stone':(187,185,169),'campfire':(201,114,39)}

def boxes(x,y,z,m,voxels):
    """Small block-shape proxy, including steps, upright panels and fence rails."""
    if '_stairs_' in m:
        direction=m.split('_stairs_',1)[1].removesuffix('_top')
        top=m.endswith('_top');base=(y+.5,y+1) if top else (y,y+.5)
        step=(y,y+.5) if top else (y+.5,y+1)
        x0,x1,z0,z1=x,x+1,z,z+1
        if direction=='east':x0+=.5
        elif direction=='west':x1-=.5
        elif direction=='south':z0+=.5
        else:z1-=.5
        return [(x,x+1,*base,z,z+1),(x0,x1,*step,z0,z1)]
    if '_trapdoor_' in m:
        direction=m.rsplit('_trapdoor_',1)[1]
        if direction=='top':return [(x,x+1,y+.8125,y+1,z,z+1)]
        # Separate slats suggest the holes in an upright wooden trapdoor.
        panels=[]
        for a,b in ((0,.2),(.43,.57),(.8,1)):
            if direction in ('east','west'):
                xx=x+.8125 if direction=='east' else x
                panels.append((xx,xx+.1875,y,y+1,z+a,z+b))
            else:
                zz=z+.8125 if direction=='south' else z
                panels.append((x+a,x+b,y,y+1,zz,zz+.1875))
        return panels
    if 'fence' in m and 'gate' not in m:
        parts=[(x+.375,x+.625,y,y+1,z+.375,z+.625)]
        for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)):
            neighbour=voxels.get((x+dx,y,z+dz),'air')
            if neighbour!=m:continue
            for h in (.375,.75):
                if dx:parts.append((x+(.5 if dx>0 else 0),x+(1 if dx>0 else .5),y+h,y+h+.125,z+.4375,z+.5625))
                else:parts.append((x+.4375,x+.5625,y+h,y+h+.125,z+(.5 if dz>0 else 0),z+(1 if dz>0 else .5)))
        return parts
    if m=='campfire':return [(x+.1,x+.9,y,y+.35,z+.1,z+.9)]
    y0=y+.5 if m.endswith('_slab_top') else y
    y1=y+.5 if m.endswith('_slab') else y+1
    return [(x,x+1,y0,y1,z,z+1)]

def render(voxels,sign=1,size=(800,650),scale=22,centre=None):
    if not voxels:return Image.new('RGB',size,'#e7e6df')
    if centre is None:
        a=np.array(list(voxels));centre=(a[:,:3].min(axis=0)+a[:,:3].max(axis=0))/2
    def project(x,y,z):
        x-=centre[0];z-=centre[2];y-=centre[1]
        return (size[0]/2+sign*(x-z)*scale, size[1]/2+(sign*(x+z)*.43-y)*scale)
    im=Image.new('RGB',size,'#e7e6df');d=ImageDraw.Draw(im)
    shapes=[]
    for (x,y,z),m in voxels.items():
        wood=m.split('_stairs_',1)[0].split('_trapdoor_',1)[0].removesuffix('_slab_top').removesuffix('_slab')
        base=COLOURS.get(m,COLOURS.get(wood+'_planks',COLOURS.get(m.removesuffix('_slab_top').removesuffix('_slab'),(139,112,76))))
        partial=any(s in m for s in ('fence','stairs','slab','trapdoor','campfire'))
        faces=[]
        for x0,x1,y0,y1,z0,z1 in boxes(x,y,z,m,voxels):
            if partial or (x,y+1,z) not in voxels:
                faces.append(([(x0,y1,z0),(x1,y1,z0),(x1,y1,z1),(x0,y1,z1)],1.08))
            xx=x1 if sign>0 else x0
            if partial or (x+sign,y,z) not in voxels:
                faces.append(([(xx,y0,z0),(xx,y1,z0),(xx,y1,z1),(xx,y0,z1)],.78))
            zz=z1 if sign>0 else z0
            if partial or (x,y,z+sign) not in voxels:
                faces.append(([(x0,y0,zz),(x1,y0,zz),(x1,y1,zz),(x0,y1,zz)],.94))
        for points,shade in faces:
            depth=sum(sign*p[0]+p[1]+sign*p[2] for p in points)/4
            colour=tuple(min(255,int(c*shade)) for c in base)
            shapes.append((depth,points,colour))
    for depth,points,colour in sorted(shapes,key=lambda a:a[0]):
        polygon=[project(*p) for p in points]
        d.polygon(polygon,fill=colour,outline=tuple(int(c*.77) for c in colour))
    return im
