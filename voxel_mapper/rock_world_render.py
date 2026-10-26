"""Schematic previews of the exact generated cells and block shapes."""
from PIL import Image,ImageDraw

COLOURS={'grass_block':'#78a052','stone':'#92968f','stone_bricks':'#888b85','cobblestone':'#70786f',
         'oak_fence':'#a18350','yellow_concrete':'#dfbd35','terracotta':'#a85a3e','mud_bricks':'#8d694c','oak_planks':'#a67c4c','granite':'#a17d6d'}


def colour(material):
    if material.startswith('stone_brick'):return COLOURS['stone_bricks']
    if material.startswith('stone_'):return COLOURS['stone']
    if material.startswith('cobblestone'):return COLOURS['cobblestone']
    return COLOURS.get(material,'#8c9188')


def _shade(value,factor):
    return tuple(int(int(value[i:i+2],16)*factor) for i in (1,3,5))


def _boxes(material,neighbors=()):
    if material=='oak_fence':
        boxes=[(.375,0,.375,.625,1.5,.625)]
        for dx,dz in neighbors:
            for low in (.4,1.):
                if dx:boxes.append((0 if dx<0 else .5,low,.43,.5 if dx<0 else 1,low+.2,.57))
                else:boxes.append((.43,low,0 if dz<0 else .5,.57,low+.2,.5 if dz<0 else 1))
        return boxes
    if material=='cobblestone_wall':return [(.25,0,.25,.75,1.5,.75)]
    if material.endswith('_slab'):return [(0,0,0,1,.5,1)]
    if '_stairs_' in material:
        suffix=material.split('_stairs_',1)[1];top=suffix.endswith('_top');direction=suffix.removesuffix('_top')
        # Plan Y is reflected into Minecraft Z, so north is positive plan depth.
        half={'north':(0,.5,1,1),'south':(0,0,1,.5),'east':(.5,0,1,1),'west':(0,0,.5,1)}[direction]
        x0,z0,x1,z1=half
        return [(0,.5 if top else 0,0,1,1 if top else .5,1),
                (x0,0 if top else .5,z0,x1,.5 if top else 1,z1)]
    return [(0,0,0,1,1,1)]


def render_previews(root,sampled):
    a,b,c,d=sampled['bounds'];scale=4
    image=Image.new('RGB',((c-a)*scale+48,(d-b)*scale+100),'#f6f5ef');draw=ImageDraw.Draw(image)
    draw.text((20,12),'Generated world: paving and reference-style rock edging',fill='#202620')
    for x in range(a,c):
        for z in range(b,d):
            material=sampled['ground'].get((x,z),'grass_block');px=24+(x-a)*scale;py=42+(d-z-1)*scale
            draw.rectangle((px,py,px+scale-1,py+scale-1),fill=colour(material))
            if (x,z) in sampled['rocks']:
                draw.rectangle((px,py,px+scale-1,py+scale-1),fill=colour(sampled['rocks'][(x,z)][0][1]),outline='#434b42')
    draw.text((20,image.height-38),'Grass interiors retained. Yellow: building footprint markers. Flat nominal ground.',fill='#303830')
    draw.text((20,image.height-20),'Rock shapes are a user-reference prototype; no building heights or surveyed terrain are claimed.',fill='#303830')
    image.save(root/'world-overview.png')
    rocks=sorted(sampled['rocks']);candidates=rocks[::max(1,len(rocks)//120)]
    if not candidates:centre=((a+c)//2,(b+d)//2)
    else:centre=max(candidates,key=lambda q:sum(abs(x-q[0])<=14 and abs(z-q[1])<=14 for x,z in rocks))
    ox,oz=centre;lowx=max(a,ox-16);highx=min(c,ox+17);lowz=max(b,oz-16);highz=min(d,oz+17)
    canvas=Image.new('RGB',(1280,900),'#dce7ee');painter=ImageDraw.Draw(canvas);unit=16
    def project(x,y,z):return (640+(x-ox-z+oz)*unit,120+(x-lowx+z-lowz)*unit/2-y*unit)
    objects=[]
    for x in range(lowx,highx):
        for z in range(lowz,highz):
            objects.append((x,z,0,(0,-.1,0,1,0,1),sampled['ground'].get((x,z),'grass_block')))
            for y,material in sampled['rocks'].get((x,z),[]):
                for bounds in _boxes(material,[(dx,dz) for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)) if sampled['rocks'].get((x+dx,z+dz))==[(1,'oak_fence')]]):objects.append((x,z,y-1,bounds,material))
    objects.sort(key=lambda row:(row[0]+row[1]+(row[3][0]+row[3][2]+row[3][3]+row[3][5])/4,row[2]+row[3][1]))
    for x,z,y,bounds,material in objects:
        x0,y0,z0,x1,y1,z1=bounds;x0+=x;x1+=x;z0+=z;z1+=z;y0+=y;y1+=y
        corners=[project(x0,y0,z0),project(x1,y0,z0),project(x1,y0,z1),project(x0,y0,z1),
                 project(x0,y1,z0),project(x1,y1,z0),project(x1,y1,z1),project(x0,y1,z1)]
        base=colour(material)
        for indices,factor in (((1,2,6,5),.68),((2,3,7,6),.83),((4,5,6,7),1.)):
            painter.polygon([corners[i] for i in indices],fill=_shade(base,factor),outline=_shade(base,.6))
    painter.rectangle((0,0,1280,48),fill='#f6f5ef');painter.text((20,14),'Exact generated cells and block shapes - schematic detail (Minecraft uses vanilla textures)',fill='#202620')
    painter.rectangle((0,855,1280,900),fill='#f6f5ef');painter.text((20,870),'Mixed stone/cobblestone stairs and slabs; oak fences where the adjacent path is under four blocks wide.',fill='#202620')
    canvas.save(root/'rock-style-detail.png')
