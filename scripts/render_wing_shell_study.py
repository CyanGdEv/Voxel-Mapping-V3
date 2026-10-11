"""Render the exact core-shell solids with explicit hypothesis colours."""
import argparse,json
from pathlib import Path
from PIL import Image,ImageChops,ImageDraw,ImageFont


def panel(model,azimuth,cutaway=False):
    # Orthographic depth-buffer rasterization avoids painter-order artifacts in
    # long perforated walls, overlapping caps and the thin roof solid.
    import math
    import numpy as np
    az=math.radians(azimuth);el=math.radians(50 if cutaway else 16)
    view=np.array([math.cos(az)*math.cos(el),math.sin(az)*math.cos(el),math.sin(el)])
    right=np.array([-math.sin(az),math.cos(az),0]);up=np.cross(view,right)
    all_vertices=np.array([v for c in model['components'] for v in c['mesh']['vertices']])
    centre=(all_vertices.min(axis=0)+all_vertices.max(axis=0))/2
    xy=np.column_stack(((all_vertices-centre)@right,(all_vertices-centre)@up))
    low=xy.min(axis=0);high=xy.max(axis=0);width=2400;scale=(width-20)/(high[0]-low[0]);height=int((high[1]-low[1])*scale)+20
    pixels=np.full((height,width,3),255,dtype=np.uint8);depth=np.full((height,width),-np.inf)
    light=np.array([.25,-.5,1.]);light/=np.linalg.norm(light)
    palette={'courtyard_wall':'859caf','roof_shell':'775338','floor':'b5b8ba'}
    for c in model['components']:
        if cutaway and c['id']=='roof_shell':continue
        vertices=np.array(c['mesh']['vertices']);rel=vertices-centre
        screen=np.column_stack(((rel@right-low[0])*scale+10,(high[1]-rel@up)*scale+10,rel@view))
        hex_colour='67947b' if c['id'].startswith('interior_partition_') else palette.get(c['id'],'c99a5c')
        colour=np.array([int(hex_colour[i:i+2],16) for i in (0,2,4)])
        for f in c['mesh']['triangles']:
            tri=screen[f];x0=max(0,int(np.floor(tri[:,0].min())));x1=min(width-1,int(np.ceil(tri[:,0].max())))
            y0=max(0,int(np.floor(tri[:,1].min())));y1=min(height-1,int(np.ceil(tri[:,1].max())))
            if x1<x0 or y1<y0:continue
            a,b,d=tri;den=(b[1]-d[1])*(a[0]-d[0])+(d[0]-b[0])*(a[1]-d[1])
            if abs(den)<1e-9:continue
            yy,xx=np.mgrid[y0:y1+1,x0:x1+1];xx=xx+.5;yy=yy+.5
            u=((b[1]-d[1])*(xx-d[0])+(d[0]-b[0])*(yy-d[1]))/den
            v=((d[1]-a[1])*(xx-d[0])+(a[0]-d[0])*(yy-d[1]))/den;w=1-u-v
            z=u*a[2]+v*b[2]+w*d[2];section=depth[y0:y1+1,x0:x1+1]
            mask=(u>=-1e-7)&(v>=-1e-7)&(w>=-1e-7)&(z>section+1e-7)
            normal=np.cross(vertices[f[1]]-vertices[f[0]],vertices[f[2]]-vertices[f[0]]);norm=np.linalg.norm(normal)
            if norm==0:continue
            shade=.62+.38*max(0,float(normal@light/norm))
            pixels[y0:y1+1,x0:x1+1][mask]=(colour*shade).astype(np.uint8);section[mask]=z[mask]
    im=Image.fromarray(pixels);bounds=ImageChops.difference(im,Image.new('RGB',im.size,'white')).getbbox();return im.crop(bounds)


def main():
    p=argparse.ArgumentParser();p.add_argument('--model',required=True);p.add_argument('--output',required=True);p.add_argument('--cutaway',action='store_true');a=p.parse_args()
    model=json.loads(Path(a.model).read_text());panels=[panel(model,-65,a.cutaway),panel(model,115,a.cutaway)];width=1800
    panels=[im.resize((width,round(im.height*width/im.width)),Image.Resampling.LANCZOS) for im in panels]
    im=Image.new('RGB',(1900,sum(p.height for p in panels)+330),'white');draw=ImageDraw.Draw(im)
    font='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf';title=ImageFont.truetype(font,36);small=ImageFont.truetype(font,24);y=30
    labels=['Source partition cutaway | courtyard side','Source partition cutaway | rear side'] if a.cutaway else ['North range core shell | courtyard side','North range core shell | rear side']
    for p,label in zip(panels,labels):
        draw.text((50,y),label,font=title,fill='#172534');y+=70;im.paste(p,(50,y));y+=p.height+30
    for line in ['Green: reviewed plan wall strip; height assumed. Roof hidden for inspection.' if a.cutaway else 'Blue: reviewed courtyard silhouette. Amber: provisional rear wall and joining-plane closures.',
                 'Rear arch projection, construction thickness and floor slab are assumptions. No glass is generated.',
                 'This closes the selected range for review; neighbouring wings, annexes and room interiors remain unresolved.']:
        draw.text((50,y),line,font=small,fill='#485565');y+=38
    im.save(a.output)

if __name__=='__main__':main()
