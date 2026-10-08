"""Deterministic vanilla-block surface palettes at one block per metre.

Brick blocks already carry a fine running-bond texture. Larger tile choices
provide gentle colour variation, not a claim to reproduce individual bricks.
"""
import math
import re

PALETTES = {
 'brick': {'blocks':['bricks','red_terracotta'],'pattern':'running_bond','colours':['#995740','#8f4635']},
 'asphalt': {'blocks':['black_concrete','gray_concrete'],'pattern':'fine_grain','colours':['#303035','#45464a']},
 'concrete': {'blocks':['light_gray_concrete','stone'],'pattern':'slab','colours':['#aaa9a4','#90918a']},
 'paving_stones': {'blocks':['stone_bricks','stone'],'pattern':'staggered_pavers','colours':['#92938d','#7b7c77']},
 'stone': {'blocks':['stone','stone_bricks'],'pattern':'irregular_stone','colours':['#93938c','#777971']},
 'sett': {'blocks':['cobblestone','stone'],'pattern':'setts','colours':['#73766f','#93938c']},
 'gravel': {'blocks':['gravel','coarse_dirt'],'pattern':'fine_grain','colours':['#99948c','#78664a']},
 'compacted': {'blocks':['coarse_dirt','gravel'],'pattern':'fine_grain','colours':['#867252','#9e9581']},
 'wood': {'blocks':['oak_planks','dark_oak_planks'],'pattern':'boards','colours':['#b7985a','#69502e']},
 'sand': {'blocks':['sand'],'pattern':'fine_grain','colours':['#d9c891']},
}
ALIASES={'tarmac':'asphalt','tarmacadam':'asphalt','block paving':'paving_stones',
         'stone paving':'stone','brick paving':'brick','brick paved':'brick',
         'concrete:plates':'concrete','concrete:lanes':'concrete','cobblestone':'sett',
         'fine_gravel':'gravel','ground':'compacted','unpaved':'compacted',
         'paved':'stone','earth':'compacted','dirt':'compacted','pebblestone':'sett',
         'concrete paving':'concrete','paving slabs':'concrete','stone slabs':'stone',
         'gravel path':'gravel','brick pavers':'brick','timber decking':'wood',
         'wooden decking':'wood','granite setts':'sett','stone setts':'sett'}


def material_label(text):
    text=re.sub(r'\s+',' ',text.strip().lower())
    # Full labels only: brick walls, concrete roofs and report prose are not floors.
    return ALIASES.get(text,text if text in PALETTES else None)


def palette_block(surface,x,z):
    key=material_label(surface) if isinstance(surface,str) else None
    if key is None:raise ValueError('Unsupported paving palette')
    if not all(isinstance(v,int) for v in (x,z)):raise ValueError('Integer voxel coordinates required')
    p=PALETTES[key];blocks=p['blocks']
    if len(blocks)==1:return blocks[0]
    # Coordinate hash has no runtime/random seed and stays stable across chunks.
    grain=((x*73856093)^(z*19349663))&0xffffffff
    if p['pattern']=='running_bond':alternate=((x+(z%2)*2)//4+z*3)%17==0
    elif p['pattern']=='slab':alternate=grain%29==0
    elif p['pattern']=='staggered_pavers':alternate=((x+z%2)//2+z*7)%13==0
    elif p['pattern']=='boards':alternate=x%11==0
    else:alternate=grain%19==0
    return blocks[int(alternate)]


def palette_preview(path):
    from PIL import Image,ImageDraw,ImageFont
    image=Image.new('RGB',(920,680),'#f7f7f4');draw=ImageDraw.Draw(image)
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',17)
    title=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',24)
    draw.text((24,18),'Path and plaza block palettes',fill='#20252a',font=title)
    draw.text((24,54),'Vanilla blocks · deterministic variation · 1 block/metre',fill='#52575b',font=font)
    for i,(key,p) in enumerate(PALETTES.items()):
        ox=24+(i%2)*450;oy=96+(i//2)*110
        draw.text((ox,oy),key.replace('_',' ').title(),fill='#20252a',font=font)
        for z in range(6):
            for x in range(24):
                b=palette_block(key,x,z);colour=p['colours'][p['blocks'].index(b)]
                draw.rectangle((ox+x*16,oy+29+z*10,ox+x*16+15,oy+38+z*10),fill=colour)
        draw.text((ox,oy+91),p['pattern'].replace('_',' '),fill='#52575b',font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',12))
    draw.text((24,656),'Colour swatches show block choices; built-in Minecraft textures supply the fine detail.',fill='#52575b',font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',12))
    image.save(path)
