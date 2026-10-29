"""CPU perspective inspection of block geometry with local vanilla textures.

This is a diagnostic renderer, not a Minecraft client capture. It deliberately
uses fixed cameras and material textures so plain-colour isometric previews do
not conceal cladding, proportion or viewpoint mistakes. Texture files are
external inspection inputs and are not added to the native world.
"""
from functools import lru_cache
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .structure_block_preview import boxes, COLOURS


def full_cube(material):
    return not any(word in material for word in ('stairs','slab','trapdoor','fence','bars','campfire','leaves','grass','fern'))


class Textures:
    def __init__(self, root):self.root=Path(root)

    @lru_cache(maxsize=None)
    def get(self, material, face):
        wood=material.split('_stairs_')[0].split('_trapdoor_')[0]
        for suffix in ('_slab_top','_slab','_fence','_planks'):
            wood=wood.removesuffix(suffix)
        tint=None
        if material=='grass_block':name='grass_top' if face=='up' else 'dirt';tint=(.45,.72,.28) if face=='up' else None
        elif 'leaves' in material:name='leaves_oak';tint=(.4,.68,.27)
        elif '_log' in material:name='log_oak_top' if face in ('up','down') else 'log_oak'
        elif 'trapdoor' in material:name='dark_oak_trapdoor' if material.startswith('dark_oak') else 'trapdoor'
        elif wood in ('oak','spruce','dark_oak'):name='planks_'+('big_oak' if wood=='dark_oak' else wood)
        elif material=='terracotta':name='hardened_clay'
        elif material=='stone_bricks':name='stonebrick'
        elif material.startswith('smooth_stone'):name='stone'
        elif material in ('stone','cobblestone','dirt'):name=material
        elif material=='campfire':name='campfire_log_lit'
        else:name=''
        texture=None
        for extension in ('.png','.tga'):
            path=self.root/(name+extension)
            if name and path.exists():
                im=Image.open(path).convert('RGBA');texture=np.asarray(im,dtype=np.float32)[:16,:16].copy();break
        if texture is None:
            rgb=COLOURS.get(material,(125,125,116))
            texture=np.full((16,16,4),255.,np.float32);texture[:,:,:3]=rgb
            if 'leaves' in material:texture[:,:,:3]=(90,155,62);tint=None
        if tint:texture[:,:,:3]*=np.asarray(tint)
        return texture


def block_boxes(x,y,z,material,voxels):
    if '_trapdoor_' in material:
        direction=material.rsplit('_trapdoor_',1)[1]
        if direction=='top':return [(x,x+1,y+.8125,y+1,z,z+1)]
        if direction in ('east','west'):
            xx=x+.8125 if direction=='east' else x
            return [(xx,xx+.1875,y,y+1,z,z+1)]
        zz=z+.8125 if direction=='south' else z
        return [(x,x+1,y,y+1,zz,zz+.1875)]
    return boxes(x,y,z,material,voxels)


def render(voxels,camera,target,textures,size=(960,540),horizontal_fov=70,label=''):
    """Render actual XYZ/material records; camera and target are native XYZ."""
    width,height=size;eye=np.asarray(camera,float);forward=np.asarray(target,float)-eye
    forward/=np.linalg.norm(forward);right=np.cross(forward,[0,1,0]);right/=np.linalg.norm(right)
    up=np.cross(right,forward);basis=np.asarray([right,up,forward]).T
    focal=width/(2*math.tan(math.radians(horizontal_fov)/2))
    sky=np.linspace([139,179,225],[202,220,237],height).astype(np.uint8)
    canvas=np.broadcast_to(sky[:,None,:],(height,width,3)).copy()
    depth=np.full((height,width),np.inf,np.float32)
    texture_cache=Textures(textures)

    def triangle(projected,uv,tex,shade):
        x0=max(0,math.floor(projected[:,0].min()));x1=min(width,math.ceil(projected[:,0].max()))
        y0=max(0,math.floor(projected[:,1].min()));y1=min(height,math.ceil(projected[:,1].max()))
        if x0>=x1 or y0>=y1:return
        a,b,c=projected
        denominator=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(denominator)<1e-9:return
        yy,xx=np.mgrid[y0:y1,x0:x1];xx=xx+.5;yy=yy+.5
        w0=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/denominator
        w1=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/denominator
        w2=1-w0-w1
        inv=w0/a[2]+w1/b[2]+w2/c[2]
        z=1/np.maximum(inv,1e-9)
        mask=(w0>=-1e-7)&(w1>=-1e-7)&(w2>=-1e-7)&(z<depth[y0:y1,x0:x1])
        if not mask.any():return
        u=(w0*uv[0,0]/a[2]+w1*uv[1,0]/b[2]+w2*uv[2,0]/c[2])*z
        v=(w0*uv[0,1]/a[2]+w1*uv[1,1]/b[2]+w2*uv[2,1]/c[2])*z
        tx=np.minimum(15,np.maximum(0,(u*16).astype(int)))
        ty=np.minimum(15,np.maximum(0,(v*16).astype(int)))
        rgba=tex[ty,tx];mask&=rgba[:,:,3]>128
        if not mask.any():return
        canvas[y0:y1,x0:x1][mask]=np.clip(rgba[:,:,:3][mask]*shade,0,255).astype(np.uint8)
        depth[y0:y1,x0:x1][mask]=z[mask]

    for (x,y,z),material in voxels.items():
        centre=np.array([x+.5,y+.5,z+.5]);view=(centre-eye)@basis
        if view[2]<-.9:continue
        partial=not full_cube(material)
        for x0,x1,y0,y1,z0,z1 in block_boxes(x,y,z,material,voxels):
            faces=[('up',(0,1,0),[(x0,y1,z0),(x1,y1,z0),(x1,y1,z1),(x0,y1,z1)],1.),
                   ('down',(0,-1,0),[(x0,y0,z0),(x1,y0,z0),(x1,y0,z1),(x0,y0,z1)],.55),
                   ('east',(1,0,0),[(x1,y0,z0),(x1,y1,z0),(x1,y1,z1),(x1,y0,z1)],.82),
                   ('west',(-1,0,0),[(x0,y0,z0),(x0,y1,z0),(x0,y1,z1),(x0,y0,z1)],.74),
                   ('south',(0,0,1),[(x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)],.9),
                   ('north',(0,0,-1),[(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0)],.68)]
            for face,normal,vertices,shade in faces:
                points=np.asarray(vertices,float)
                if np.dot(eye-points.mean(0),normal)<=0:continue
                neighbour=voxels.get((x+normal[0],y+normal[1],z+normal[2]),'air')
                if not partial and neighbour!='air' and full_cube(neighbour):continue
                q=(points-eye)@basis
                if q[:,2].min()<.15:continue
                projected=np.column_stack([width/2+focal*q[:,0]/q[:,2],height/2-focal*q[:,1]/q[:,2],q[:,2]])
                if (projected[:,0].max()<0 or projected[:,0].min()>width or
                    projected[:,1].max()<0 or projected[:,1].min()>height):continue
                if face in ('up','down'):uv=np.column_stack([points[:,0]-x,points[:,2]-z])
                elif face in ('east','west'):uv=np.column_stack([points[:,2]-z,1-(points[:,1]-y)])
                else:uv=np.column_stack([points[:,0]-x,1-(points[:,1]-y)])
                texture=texture_cache.get(material,face)
                for indices in ([0,1,2],[0,2,3]):triangle(projected[indices],uv[indices],texture,shade)
    image=Image.fromarray(canvas)
    if label:
        draw=ImageDraw.Draw(image);draw.rectangle((0,0,width,25),fill='#20252a')
        draw.text((8,7),label,fill='white')
    return image
