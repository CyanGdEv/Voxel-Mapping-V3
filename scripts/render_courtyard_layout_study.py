"""Render the full geometry plus roof-hidden room inspection view."""
import argparse,json
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from render_wing_shell_study import panel


def main():
    p=argparse.ArgumentParser();p.add_argument('--model',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    model=json.loads(Path(a.model).read_text())
    panels=[panel(model,-60),panel(model,120,True)]
    width=1800
    panels=[im.resize((width,round(im.height*width/im.width)),Image.Resampling.LANCZOS) for im in panels]
    image=Image.new('RGB',(1900,sum(p.height for p in panels)+420),'white');d=ImageDraw.Draw(image)
    font='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf';title=ImageFont.truetype(font,34);small=ImageFont.truetype(font,24);y=30
    for p,label in zip(panels,['Mutiny Bay | full courtyard layout V8','Roof hidden | rooms, service spaces and courtyard passages']):
        d.text((50,y),label,font=title,fill='#172534');y+=70;image.paste(p,(50,y));y+=p.height+35
    for line in ['Four ranges, two rear annexes and 28 room areas. Previous north-wing geometry retained.',
                 'Green: room partitions. Amber: sampled plan walls. Blue: reviewed north courtyard wall.',
                 'Ground-floor layout study: new heights, roofs and joins are provisional. No glass.',
                 'Upper floors, stairs, tower details and complete elevation openings remain to be reconstructed.']:
        d.text((50,y),line,font=small,fill='#485565');y+=38
    image.save(a.output)


if __name__=='__main__':main()
