"""Source-plan timber track section, styled from the user's Minecraft references."""
import argparse
from collections import deque
from concurrent.futures import CancelledError
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile

import numpy as np
from shapely.geometry import Point,Polygon,shape,LineString,mapping
from shapely.affinity import affine_transform
from shapely.ops import polygonize

from .generation_cycles import atomic_json,file_hash
from .wicker_track import height_marker

PROFILE=Path(__file__).with_name('data')/'wicker-track-timber-style.json'


def height_at(station,controls):
    if not controls[0]['station_m']<=station<=controls[-1]['station_m']:raise ValueError('Track height extrapolation forbidden')
    for a,b in zip(controls,controls[1:]):
        if station<=b['station_m']:
            t=(station-a['station_m'])/(b['station_m']-a['station_m']);t=t*t*(3-2*t)
            return a['height_m']+(b['height_m']-a['height_m'])*t
    return controls[-1]['height_m']


def frame(line,station):
    a=np.asarray(line.interpolate(max(0,station-.25)).coords[0]);b=np.asarray(line.interpolate(min(line.length,station+.25)).coords[0]);v=b-a
    if np.linalg.norm(v)<1e-8:raise ValueError('Track tangent is degenerate')
    tangent=v/np.linalg.norm(v);return np.asarray(line.interpolate(station).coords[0]),tangent,np.array([-tangent[1],tangent[0]])


def source_geometry(markings_path,pdf_path,profile,cancelled):
    if file_hash(markings_path)!=profile['markings_sha256'] or file_hash(pdf_path)!=profile['source_pdf_sha256']:raise ValueError('Pinned original track geometry required')
    data=json.loads(Path(markings_path).read_text());unit=profile['metres_per_pdf_point'];transform=[unit,0,0,unit,0,0]
    centre=affine_transform(shape(next(r['geometry_pdf_native'] for r in data['records'] if r['role']=='track_centre')),transform)
    supports=affine_transform(shape(next(r['geometry_pdf_native'] for r in data['records'] if r['role']=='support_boundaries')),transform)
    if centre.geom_type!='LineString' or len(centre.coords)>2000 or not 700<centre.length<850 or len(supports.geoms)>80000:raise ValueError('Bounded reviewed Wicker source geometry required')
    import pymupdf
    with pymupdf.open(pdf_path) as doc:
        page=doc[0]
        if len(doc)!=1 or page.rotation!=0 or page.rect.height!=profile['source_native_height_points']:raise ValueError('Original landscape drawing frame required')
        vectors=page.get_drawings();text=page.get_text();controls=[]
        for expected in profile['controls']:
            if cancelled():raise CancelledError('Track control replay cancelled')
            import re
            label=expected['label'];blocks=[b for b in page.get_text('blocks') if re.fullmatch(label+r'\s*-\s*(\d+\.?\d*)',' '.join(b[4].split()))]
            if len(blocks)!=1:raise ValueError('Unique printed track level required')
            import re
            match=re.fullmatch(label+r'\s*-\s*(\d+\.?\d*)',' '.join(blocks[0][4].split()))
            if not match or float(match[1])!=expected['height_m']:raise ValueError('Printed track level changed')
            marker=height_marker(vectors,list(blocks[0][:4]))
            if not marker or marker['pdf_vector_sequence']!=expected['marker_vector_sequence'] or math.dist(marker['point_pdf'],expected['raw_marker_pdf_xy'])>.02:raise ValueError('Track height crosshair source changed')
            q=Point(marker['point_pdf'][0]*unit,(page.rect.height-marker['point_pdf'][1])*unit);station=centre.project(q)
            if q.distance(centre)>.05:raise ValueError('Crosshair is not on the selected plan centreline')
            controls.append({'label':label,'height_m':expected['height_m'],'station_m':station,'nominal_xy':list(q.coords[0]),'crosshair_to_source_line_m':q.distance(centre),'source_marker_sequence':marker['pdf_vector_sequence']})
    controls.sort(key=lambda c:c['station_m'])
    if [c['label'] for c in controls]!=profile['section_controls']:raise ValueError('Unexpected track section order')
    lo,hi=profile['post_symbol_area_range_m2'];posts=[]
    for index,polygon in enumerate(polygonize(supports)):
        if cancelled():raise CancelledError('Support symbol extraction cancelled')
        if not lo<=polygon.area<=hi:continue
        p=polygon.centroid;s=centre.project(p)
        if not controls[0]['station_m']<=s<=controls[-1]['station_m']:continue
        mid,t,n=frame(centre,s);off=float(np.dot(np.asarray(p.coords[0])-mid,n))
        if .65<=abs(off)<=6:posts.append({'source_polygon_index':index,'geometry_sha256':hashlib.sha256(polygon.normalize().wkb).hexdigest(),'xy':list(p.coords[0]),'station_m':s,'offset_m':off,'symbol_area_m2':polygon.area})
    pairs=[];used=set();voxel_pairs=set()
    for a in sorted((p for p in posts if p['offset_m']<0),key=lambda p:p['station_m']):
        other=[p for p in posts if p['offset_m']>0 and p['source_polygon_index'] not in used and abs(p['station_m']-a['station_m'])<=profile['max_post_station_difference_m']]
        if not other:continue
        b=min(other,key=lambda p:abs(p['station_m']-a['station_m']));key=tuple(sorted(tuple(map(math.floor,p['xy'])) for p in [a,b]))
        if key[0]==key[1] or key in voxel_pairs:continue
        used.add(b['source_polygon_index']);voxel_pairs.add(key);pairs.append({'posts':[a,b],'station_m':(a['station_m']+b['station_m'])/2})
    if len(pairs)<8:raise ValueError('Insufficient paired source support symbols')
    return centre,controls,pairs,{'source_centre_length_m':centre.length,'source_support_line_segments':len(supports.geoms),'selected_post_symbols':len(posts),'paired_source_bents':len(pairs),'symbol_dimensions_are_physical_sizes':False}


def sample_deck(line,controls):
    start,end=controls[0]['station_m'],controls[-1]['station_m'];core={};catwalk={};rails={};ties={};samples=[]
    for s in np.linspace(start,end,math.ceil((end-start)/.25)+1):
        p,t,n=frame(line,float(s));top=round(2*height_at(float(s),controls))/2;base=math.ceil(top)-1
        for off in [-.8,0,.8]:
            x,y=map(math.floor,p+off*n);core[x,base,y]='dark_oak_slab' if top%1 else 'dark_oak_planks'
        x,y=map(math.floor,p+1.7*n);catwalk[x,base,y]='oak_slab' if top%1 else 'oak_slab_top'
        x,y=map(math.floor,p+2.35*n);rails[x,math.floor(top),y]='oak_fence';ties[x,math.floor(top)-1,y]='oak_planks'
        x,y=map(math.floor,p);ties[x,base-1,y]='spruce_planks'
        samples.append({'station_m':float(s),'source_cell_xy':list(map(math.floor,p)),'running_top_m':top})
    # Several sub-metre samples can quantize to one Minecraft column. Keep
    # its highest actual surface rather than leaving a lower sample's air
    # requirement inside the upper stair/slab in the same column.
    def topmost(cells):
        chosen={}
        for (x,h,y),m in cells.items():
            top=h+(.5 if m.endswith('_slab') else 1)
            if (x,y) not in chosen or chosen[x,y][0]<top:chosen[x,y]=(top,(x,h,y),m)
        return {k:m for _,k,m in chosen.values()}
    core=topmost(core);catwalk=topmost(catwalk);core_xy={(x,y) for x,h,y in core}
    catwalk={k:m for k,m in catwalk.items() if (k[0],k[2]) not in core_xy}
    result=dict(ties);result.update(catwalk);result.update(core)
    head={(x,h,y) for x,b,y in core for h in [b+1,b+2,b+3]}
    # Guard rails never occupy the running strip's headroom.
    for k,m in rails.items():
        if k not in result and k not in head:result[k]=m
    if set(result)&head:raise ValueError('Track crosses its own three-block running clearance')
    return result,core,head,samples


def running_connectivity(core):
    tops={(x,y):h+(.5 if m.endswith('_slab') else 1) for (x,h,y),m in core.items()}
    seen={min(tops)};pending=list(seen)
    while pending:
        x,y=pending.pop()
        for q in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)]:
            if q in tops and q not in seen:seen.add(q);pending.append(q)
    if len(seen)!=len(tops):raise ValueError('Running strip has disconnected metre cells')
    return {'all_running_columns_cardinally_connected':True,'running_columns':len(tops),
        'maximum_cardinal_grid_height_change_m':max((abs(h-tops[q]) for (x,y),h in tops.items() for q in [(x+1,y),(x,y+1)] if q in tops),default=0),
        'operable_minecraft_railway':False}


def support_bent(pair,line,controls,terrain):
    h=round(2*height_at(pair['station_m'],controls))/2;beam=math.ceil(h)-2;p,t,n=frame(line,pair['station_m']);posts=[tuple(map(math.floor,r['xy'])) for r in pair['posts']];result={}
    for x,y in posts:
        if (x,y) not in terrain:return {},'outside_terrain'
        ground=terrain[x,y]['y']
        if ground>=beam or beam-ground>32:return {},'terrain_height_conflict'
        if terrain[x,y]['material'] not in ['grass_block','brown_wool','blue_wool','orange_wool']:return {},'source_post_over_retained_paving_or_other_land_use'
        result[x,ground+1,y]='stone_bricks'
        for z in range(ground+2,beam+1):result[x,z,y]='oak_log' if z in [ground+2,beam] or (beam-z)%3==0 else 'oak_fence'
    a,b=map(np.asarray,posts);length=np.linalg.norm(b-a)
    if not 1<=length<=12:return {},'source_bent_span_outside_budget'
    axis='x' if abs(b[0]-a[0])>=abs(b[1]-a[1]) else 'z'
    bottom=max(terrain[k]['y']+2 for k in posts)
    levels=list(range(bottom,beam,3))+[beam]
    for z in levels:
        for frac in np.linspace(0,1,math.ceil(length/.25)+1):
            x,y=map(lambda v:math.floor(v+.5),a+frac*(b-a))
            if (x,y) in terrain and z>terrain[x,y]['y']:
                if result.get((x,z,y))!='oak_log':result[x,z,y]='oak_log_'+axis
        if z+3<=beam:
            for frac in np.linspace(0,1,math.ceil(length/.25)+1):
                x,y=map(lambda v:math.floor(v+.5),a+frac*(b-a));zz=z+round(frac*3)
                if (x,y) in terrain and zz>terrain[x,y]['y']:result.setdefault((x,zz,y),'oak_fence')
                zz=z+round((1-frac)*3)
                if (x,y) in terrain and zz>terrain[x,y]['y']:result.setdefault((x,zz,y),'oak_fence')
    for x,y in posts:
        direction=np.asarray([x+.5,y+.5])-p;offset=np.array([1 if direction[0]>0 else -1,0]) if abs(direction[0])>abs(direction[1]) else np.array([0,1 if direction[1]>0 else -1])
        xx,yy=np.asarray([x,y])+offset
        facing='east' if offset[0]>0 else 'west' if offset[0]<0 else 'north' if offset[1]>0 else 'south'
        if (int(xx),int(yy)) in terrain and beam>terrain[int(xx),int(yy)]['y']:result.setdefault((int(xx),beam,int(yy)),'oak_trapdoor_'+facing)
    return result,None


def run(base_directory,markings_path,pdf_path,output,*,allow_provisional=False,cancelled=lambda:False):
    if allow_provisional is not True:raise ValueError('Explicit conditional track construction opt-in required')
    if cancelled():raise CancelledError('Track construction cancelled')
    output=Path(output);base_directory=Path(base_directory)
    if output.exists():raise ValueError('Fresh track world output required')
    profile=json.loads(PROFILE.read_text())
    def pins():
        for name,sha in profile['base_pins'].items():
            if file_hash(base_directory/name)!=sha:raise ValueError('Exact maintenance-built base required')
        if file_hash(markings_path)!=profile['markings_sha256'] or file_hash(pdf_path)!=profile['source_pdf_sha256']:raise ValueError('Source track inputs changed')
    pins();line,controls,pairs,source_review=source_geometry(markings_path,pdf_path,profile,cancelled)
    base=json.loads((base_directory/'quality-report.json').read_text());rows=[json.loads(l) for l in (base_directory/'voxels.jsonl').read_text().splitlines()]
    terrain={(r['x'],r['z']-1):r for r in rows if r['kind']=='terrain'};old={(r['x'],r['y'],r['z']-1):r['material'] for r in rows if r['kind']=='structure'}
    blocks,core,head,samples=sample_deck(line,controls);connectivity=running_connectivity(core)
    if any((x,y) not in terrain or h<=terrain[x,y]['y'] for x,h,y in blocks):raise ValueError('Track intersects terrain; no automatic cuts allowed')
    if any(k in old for k in blocks) or head&old.keys():raise ValueError('Track collides with retained park')
    accepted=[];held=[]
    for pair in pairs:
        if cancelled():raise CancelledError('Timber supports cancelled')
        proposal,reason=support_bent(pair,line,controls,terrain)
        if reason or any(k in old for k in proposal) or set(proposal)&head:
            held.append({'pair':pair,'reason':reason or 'retained park / running clearance collision'});continue
        for k,m in proposal.items():
            if k not in blocks or (m in ['oak_log','oak_log_x','oak_log_z','stone_bricks'] and (blocks[k]=='oak_fence' or 'trapdoor' in blocks[k])) or (m=='oak_fence' and 'trapdoor' in blocks[k]):blocks[k]=m
        accepted.append({'source_pair':pair,'blocks_proposed':len(proposal)})
    if len(accepted)<8:raise ValueError('Too few source support bents can be constructed without altering the park')
    if len(blocks)>profile['max_added_blocks']:raise ValueError('Track build budget exceeded')
    solid_posts=0
    for bent in accepted:
        pair=bent['source_pair'];beam=math.ceil(round(2*height_at(pair['station_m'],controls))/2)-2
        for post in pair['posts']:
            x,y=map(math.floor,post['xy'])
            for h in range(terrain[x,y]['y']+1,beam+1):
                if blocks.get((x,h,y)) not in ['oak_log','oak_log_x','oak_log_z','stone_bricks','spruce_planks','dark_oak_planks','oak_planks','oak_fence']:raise ValueError('Timber post has a missing support cell: '+str((x,h,y,blocks.get((x,h,y)))))
                solid_posts+=1
    all_blocks={**old,**blocks};report=dict(base)
    report.update(version='timber-track-section-world-v1',status='source_bound_first_track_section_constructed',implementation_sha256=file_hash(__file__),profile_sha256=file_hash(PROFILE),source_parent_world_sha256=base['world']['sha256'])
    report['timber_track']={'controls':controls,'source_review':source_review,'section_length_m':controls[-1]['station_m']-controls[0]['station_m'],'full_source_route_length_m':line.length,'added_structure_records':len(blocks),'constructed_source_bents':accepted,'withheld_source_bents':held,'samples':samples,'continuous_post_cells_checked':solid_posts,'running_connectivity':connectivity,
        'reference_style':profile['reference_origin'],'palette':profile['palette'],'exact_reference_block_identity_verified':False,'banking_verified':False,'operable_ride':False,
        'limitations':['Screenshots guide palette and lattice rhythm, not surveyed geometry; pictured running rails may use custom ride/resource-pack assets.',
            'Plan centreline and paired closed support symbols guide XY. Symbol areas are not verified footing sizes or structural timber dimensions.',
            'Printed HP/LP levels are conditionally treated as running-surface ODN heights. Smoothstep interpolation and half-block quantization between anchors are display hypotheses.',
            'Bank angle is held at zero because it is not recovered. Exact cross-sections, structural design, train mechanism and the remaining route are not reconstructed.',
            'Retained park, terrain and coloured plan guides remain unchanged. Source bents conflicting with paving, markers or existing geometry are withheld with receipts.']}
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='timber-track-',dir=output.parent) as temp:
        root=Path(temp)/'result';root.mkdir();voxel=root/'voxels.jsonl'
        with voxel.open('w') as stream:
            for row in terrain.values():stream.write(json.dumps(row)+'\n')
            for (x,h,y),m in sorted(all_blocks.items()):stream.write(json.dumps({'x':x,'y':h,'z':y+1,'kind':'structure','material':m})+'\n')
        from . import bedrock
        from . import planning_station_preshow_world as checkers
        from .planning_world_preview import _verify_archive,_spawn_check
        def check(path,offset,spawn):
            if offset!=base['world']['vertical_offset_blocks']:raise ValueError('Retained world offset changed')
            report['spawn_validation']=_spawn_check(path,spawn)
            report['track_running_clearance_native']=checkers._native_air(path,offset,head)
            report['track_running_surfaces_native']=checkers._native_surfaces(path,offset,[{'source_cell_xy':[x,y],'walking_top_m':h+(.5 if m.endswith('_slab') else 1)} for (x,h,y),m in sorted(core.items())])
            atomic_json(path/'TRACK-SECTION-ASSUMPTIONS.json',report['timber_track'])
        world=bedrock.export_world(voxel,root,report,name='Wicker TIMBER TRACK - HP1 LP1 HP2 first section',max_blocks=1_000_000,ground_depth=3,foundation_mode='chunk',post_export_check=check)
        report['world']=world;report['archive_validation']=_verify_archive(root/world['file'],root/'bedrock-world',world,cancelled)
        shutil.move(root/world['file'],root/'wicker-timber-track.mcworld');report['world']['file']='wicker-timber-track.mcworld';shutil.rmtree(root/'bedrock-world')
        atomic_json(root/'quality-report.json',report);atomic_json(root/'track-blocks.json',[{'source_xyz':list(k),'material':m} for k,m in sorted(blocks.items())]);atomic_json(root/'running-clearance-air.json',[list(k) for k in sorted(head)])
        preview(root/'track-section-preview.png',terrain,blocks,controls)
        (root/'index.html').write_text('<!doctype html><meta charset="utf-8"><h1>First source-bound timber track section</h1><a href="wicker-timber-track.mcworld">Download world</a><p>HP1–LP1–HP2 centreline and source support symbols, styled using user reference screenshots. Smooth vertical interpolation, palette and unbanked shape are prototype choices. No functional ride mechanism.</p><img style="max-width:100%" src="track-section-preview.png">')
        pins();shutil.move(root,output)
    return report


def preview(path,terrain,blocks,controls):
    from PIL import Image,ImageDraw,ImageColor
    from .rock_world_render import _boxes,colour
    xs=[k[0] for k in blocks];ys=[k[2] for k in blocks];lowx=min(xs)-2;highx=max(xs)+3;lowy=min(ys)-2;highy=max(ys)+3
    occupied={(x,h,y):r['material'] for (x,y),r in terrain.items() if lowx<=x<=highx and lowy<=y<=highy for h in [r['y']]};occupied.update(blocks)
    palette={'oak_log':'#9a7945','oak_log_x':'#ac8a54','oak_log_z':'#ac8a54','oak_planks':'#b99758','spruce_planks':'#775637','oak_slab':'#b99758','oak_slab_top':'#b99758','dark_oak_planks':'#4e3522','dark_oak_slab':'#4e3522','oak_fence':'#a8874d','oak_trapdoor':'#9e7c45','grass_block':'#86a963'}
    datum=min(r['y'] for k,r in terrain.items() if lowx<=k[0]<=highx and lowy<=k[1]<=highy)
    def project(x,h,y):return ((x-y)*9,(x+y)*4.5-(h-datum)*10)
    points=[project(x+dx,h+dh,y+dy) for x,h,y in occupied for dx,dh,dy in [(0,0,0),(1,1.5,1)]];xmin=min(p[0] for p in points);ymin=min(p[1] for p in points)
    image=Image.new('RGB',(math.ceil(max(p[0] for p in points)-xmin)+100,math.ceil(max(p[1] for p in points)-ymin)+150),'#f7f5ed');draw=ImageDraw.Draw(image);faces=[]
    for (x,h,y),m in occupied.items():
        paint='#9e7c45' if 'trapdoor' in m else palette.get(m,colour(m));rgb=ImageColor.getrgb(paint)
        neighbors=[(dx,dy) for dx,dy in [(1,0),(-1,0),(0,1),(0,-1)] if occupied.get((x+dx,h,y+dy))=='oak_fence']
        if '_trapdoor_' in m:
            direction=m.rsplit('_',1)[1];bounds=[{'north':(0,0,0,1,1,.1875),'south':(0,0,.8125,1,1,1),'east':(0,0,0,.1875,1,1),'west':(.8125,0,0,1,1,1)}[direction]]
        else:bounds=[(0,.5,0,1,1,1)] if m.endswith('_slab_top') else [(0,0,0,1,.1875,1)] if m=='oak_trapdoor' else _boxes(m,neighbors)
        for x0,h0,y0,x1,h1,y1 in bounds:
            v=[(x+x0,h+h0,y+y0),(x+x1,h+h0,y+y0),(x+x1,h+h0,y+y1),(x+x0,h+h0,y+y1),(x+x0,h+h1,y+y0),(x+x1,h+h1,y+y0),(x+x1,h+h1,y+y1),(x+x0,h+h1,y+y1)]
            for ids,shade in [([1,2,6,5],.78),([2,3,7,6],.59),([4,5,6,7],1)]:
                vertices=[v[i] for i in ids];depth=sum(a+c+.7*b for a,b,c in vertices)/4;polygon=[(project(*p)[0]-xmin+40,project(*p)[1]-ymin+85) for p in vertices]
                faces.append((depth,polygon,tuple(round(c*shade) for c in rgb)))
    for _,polygon,rgb in sorted(faces,key=lambda f:f[0]):draw.polygon(polygon,fill=rgb,outline=tuple(max(0,c-12) for c in rgb))
    draw.rectangle((0,0,image.width,62),fill='#f7f5ed');draw.text((18,14),'WICKER MAN: first source-bound timber track and support section',fill='black');draw.text((18,35),'HP1 / LP1 / HP2. Screenshot-style palette; interpolated heights and unmeasured banking remain provisional.',fill='black')
    image.save(path)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['base-directory','markings-path','pdf-path','output']:p.add_argument('--'+name,required=True)
    p.add_argument('--allow-provisional',action='store_true');a=p.parse_args(argv)
    r=run(a.base_directory,a.markings_path,a.pdf_path,a.output,allow_provisional=a.allow_provisional)
    print(json.dumps({'world_sha256':r['world']['sha256'],'section_length_m':r['timber_track']['section_length_m'],'bents':len(r['timber_track']['constructed_source_bents'])}))


if __name__=='__main__':main()
