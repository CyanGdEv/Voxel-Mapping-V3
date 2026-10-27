"""User-authorized appearance-based material assignments, separate from RGB evidence."""
import csv
from html import escape
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .aerial_material_research import _lab
from .generation_cycles import atomic_json, file_hash
from .paving_palette import PALETTES

VERSION='colour-appearance-materials-v1'
SPECIAL={
    'vegetation':{'blocks':['grass_block','moss_block'],'weights':[80,20],'colours':['#6b8e42','#607c32']},
    'water':{'blocks':['water'],'weights':[1],'colours':['#3f76a1']}}


def _colours(palette):
    return np.array([[int(c[i:i+2],16) for i in (1,3,5)] for c in palette['colours']],dtype=float)


def assign(row):
    result={'cell_id':row['id'],'image_sha256':row['image_sha256'],'pixel_box':row['pixel_box'],
        'assignment_policy':VERSION,'assignment_basis':'user_authorized_rgb_colour_appearance',
        'material_verified':False,'training_eligible':False,'physical_registration_verified':False,
        'geometry_role':'imagery_sample_cell_not_object_boundary','geometry':row.get('geometry')}
    if row.get('status')!='rgb_observation_only' or 'median_rgb' not in row:
        return {**result,'status':'unassigned','reason':'insufficient_opaque_pixels','material':None,'blocks':[]}
    rgb=np.asarray(row['median_rgb'],dtype=float)
    if rgb.shape!=(3,) or not np.isfinite(rgb).all() or np.any(rgb<0) or np.any(rgb>255):
        raise ValueError('Finite sampled RGB triplet required for material assignment')
    cue=row.get('colour_cue');shadow=row.get('shadow_fraction',0)
    if cue=='shadow_or_dark_surface' or shadow>.35:
        return {**result,'status':'unassigned','reason':'shadow_or_dark_surface','material':None,'blocks':[],
            'observed_rgb':rgb.tolist()}
    if cue=='vegetation_colour':material='vegetation';palette=SPECIAL[material];method='green_colour_grass_moss_proxy'
    elif cue=='blue_surface_or_water':material='water';palette=SPECIAL[material];method='blue_colour_water_proxy'
    else:
        candidates=row.get('block_palette_candidates',[])
        if not candidates or candidates[0].get('palette') not in PALETTES:raise ValueError('Known source colour palette required')
        material=candidates[0]['palette'];palette=PALETTES[material];method='nearest_existing_palette_cielab'
    colours=_colours(palette);weights=palette.get('weights',[1]*len(colours))
    display=np.average(colours,axis=0,weights=weights).round().astype(int).tolist()
    primary=int(np.argmin(np.linalg.norm(_lab(colours)-_lab(rgb),axis=1)))
    return {**result,'status':'provisional_colour_assignment','material':material,
        'blocks':['minecraft:'+b for b in palette['blocks']],'weights':weights,
        'primary_block':'minecraft:'+palette['blocks'][primary],'display_rgb':display,'observed_rgb':rgb.tolist(),
        'colour_rule':method,'colour_distance_delta_e76':round(float(np.linalg.norm(_lab(rgb)-_lab(display))),3),
        'assumptions':(['Green vegetation is represented by grass/moss; canopy and ground are not distinguished.'] if material=='vegetation' else
            ['Blue appearance is represented as water; a blue roof/surface may look similar.'] if material=='water' else
            ['The chosen palette is a visual approximation; paving, roofs and bare ground may share colours.'])}


def write(rows,output,site,attribution=""):
    output=Path(output);assignments=[assign(row) for row in rows]
    jsonl=output/'material-assignments.jsonl'
    jsonl.write_text(''.join(json.dumps(row,sort_keys=True)+'\n' for row in assignments))
    atomic_json(output/'material-assignments.geojson',{'type':'FeatureCollection','features':[
        {'type':'Feature','id':row['cell_id'],'geometry':row['geometry'],
            'properties':{k:v for k,v in row.items() if k!='geometry'}} for row in assignments if row.get('geometry')]})
    with (output/'material-assignments.csv').open('w',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['cell','status','material','primary_block','observed_rgb','colour_rule','material_verified'])
        for row in assignments:writer.writerow([row['cell_id'],row['status'],row['material'],row.get('primary_block',''),
            row.get('observed_rgb',''),row.get('colour_rule',row.get('reason')),False])
    counts={name:sum(r.get('material')==name for r in assignments) for name in sorted({r['material'] for r in assignments if r['material']})}
    # A scientific classification-layer preview; the original aerial pixels stay untouched.
    width=max((r['pixel_box'][2] for r in rows),default=512);height=max((r['pixel_box'][3] for r in rows),default=512)
    legend=[(name,next(r['display_rgb'] for r in assignments if r.get('material')==name),count) for name,count in counts.items()]
    image=Image.new('RGB',(width,height+max(80,36+len(legend)*20)),(248,249,250));draw=ImageDraw.Draw(image)
    draw.rectangle((0,0,width-1,height-1),fill=(38,42,48))
    for row in assignments:
        left,top,right,bottom=row['pixel_box']
        if row['material'] is not None:draw.rectangle((left,top,right-1,bottom-1),fill=tuple(row['display_rgb']))
        else:
            for y in range(top,bottom,8):draw.line((left,y,min(right-1,left+bottom-y),bottom-1),fill=(90,94,100))
    draw.text((8,height+8),'Draft material assignments by colour | dark hatching: unassigned shadow/no data',fill=(30,40,50))
    for i,(name,colour,count) in enumerate(legend):
        y=height+30+i*20;draw.rectangle((8,y,22,y+12),fill=tuple(colour));draw.text((30,y),name.replace('_',' ')+': '+str(count)+' cells',fill=(30,40,50))
    image.save(output/'material-map.png')
    html='<!doctype html><meta charset="utf-8"><title>Draft material assignments</title><style>body{font:16px system-ui;max-width:1200px;margin:30px auto;padding:0 16px;color:#253341}.views{display:flex;flex-wrap:wrap}figure{width:46%;margin:12px}img{width:100%}</style><h1>'+escape(site)+'</h1><p>Materials assigned from colour appearance. Dark/shadow areas remain unassigned. This draft uses sampling cells, so it does not define building or path edges.</p><div class="views"><figure><img src="rgb-preview.png"><figcaption>Source aerial RGB</figcaption></figure><figure><img src="material-map.png"><figcaption>Assigned material palettes</figcaption></figure></div><p>'+escape(attribution)+'</p><p><a href="material-assignments.csv">Assignments table</a> · <a href="material-assignments.geojson">Georeferenced material layer</a></p>'
    (output/'materials.html').write_text(html,encoding='utf-8')
    return {'policy':VERSION,'assigned_cells':sum(r['material'] is not None for r in assignments),
        'unassigned_cells':sum(r['material'] is None for r in assignments),'material_counts':counts,
        'file':'material-assignments.jsonl','sha256':file_hash(jsonl),'map':'material-map.png','review':'materials.html',
        'material_verified':False,'training_labels_generated':0,'world_blocks_generated':0}
