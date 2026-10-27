"""Plan-positioned coaster support bents and stepped fence X-bracing."""
import argparse
from collections import defaultdict
from concurrent.futures import CancelledError
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile

import numpy as np
from shapely.geometry import shape
from shapely.affinity import affine_transform
from shapely.ops import polygonize
from .generation_cycles import atomic_json,file_hash
from .timber_track_world import frame

PROFILE=Path(__file__).with_name('data')/'wicker-fence-supports.json'
FENCES={'oak_fence','spruce_fence','dark_oak_fence','nether_brick_fence'}


def staircase_line(a,b):
    """A cardinally connected voxel line, including diagonal stair connectors."""
    a=np.asarray(a,dtype=int);b=np.asarray(b,dtype=int);current=a.copy();result=[tuple(map(int,current))]
    for frac in np.linspace(0,1,int(max(abs(b-a)))*4+1):
        target=np.floor(a+frac*(b-a)+.5).astype(int)
        for axis in np.argsort(-abs(target-current)):
            while current[axis]!=target[axis]:
                current[axis]+=1 if target[axis]>current[axis] else -1;result.append(tuple(map(int,current)))
    return list(dict.fromkeys(result))


def source_frames(markings,pdf,profile,cancelled):
    if file_hash(markings)!=profile['markings_sha256'] or file_hash(pdf)!=profile['source_pdf_sha256']:raise ValueError('Pinned original planning inputs required')
    data=json.loads(Path(markings).read_text());u=profile['metres_per_pdf_point'];affine=[u,0,0,u,0,0]
    route=affine_transform(shape(next(r['geometry_pdf_native'] for r in data['records'] if r['role']=='track_centre')),affine)
    boundaries=affine_transform(shape(next(r['geometry_pdf_native'] for r in data['records'] if r['role']=='support_boundaries')),affine)
    if route.geom_type!='LineString' or len(route.coords)>2000 or len(boundaries.geoms)>80000:raise ValueError('Bounded source route/support linework required')
    points=np.asarray(route.coords);a=points[:-1];v=points[1:]-a;length=np.linalg.norm(v,axis=1);stations=np.r_[0,np.cumsum(length)]
    posts=[];ambiguous=[]
    for index,poly in enumerate(polygonize(boundaries)):
        if cancelled():raise CancelledError('Support extraction cancelled')
        if not profile['symbol_area_m2'][0]<=poly.area<=profile['symbol_area_m2'][1]:continue
        p=np.asarray(poly.centroid.coords[0]);t=np.clip(np.sum((p-a)*v,axis=1)/(length*length),0,1)
        distances=np.linalg.norm(p-(a+t[:,None]*v),axis=1);order=np.argsort(distances);best=int(order[0]);s=float(stations[best]+t[best]*length[best])
        alt=[int(j) for j in order if abs(stations[j]+t[j]*length[j]-s)>8]
        if alt and distances[alt[0]]-distances[best]<profile['ambiguity_margin_m']:
            ambiguous.append({'source_polygon_index':index,'nearest_station_m':s,'branch_margin_m':float(distances[alt[0]]-distances[best])});continue
        mid,tangent,normal=frame(route,s);offset=float(np.dot(p-mid,normal))
        if .65<=abs(offset)<=6:
            posts.append({'source_polygon_index':index,'xy':p.tolist(),'station_m':s,'offset_m':offset,'symbol_area_m2':poly.area,'geometry_sha256':hashlib.sha256(poly.normalize().wkb).hexdigest()})
    pairs=[];used=set();cells=set()
    for left in sorted((p for p in posts if p['offset_m']<0),key=lambda p:p['station_m']):
        choices=[p for p in posts if p['offset_m']>0 and p['source_polygon_index'] not in used and abs(p['station_m']-left['station_m'])<=.8]
        if not choices:continue
        right=min(choices,key=lambda p:abs(p['station_m']-left['station_m']));key=tuple(sorted(tuple(map(math.floor,p['xy'])) for p in [left,right]))
        if key[0]==key[1] or key in cells:continue
        used.add(right['source_polygon_index']);cells.add(key)
        pairs.append({'posts':[left,right],'station_m':(left['station_m']+right['station_m'])/2})
    return route,pairs,{'source_centre_length_m':route.length,'source_line_segments':len(boundaries.geoms),'eligible_post_symbols':len(posts),'paired_bents':len(pairs),'ambiguous_symbols_withheld':ambiguous,'symbol_size_is_physical_footing_size':False}


def deck_intervals(track):
    result=defaultdict(list)
    for (x,h,y),m in track.items():
        if m in ['oak_planks','spruce_planks']:result[x,y].append((h,h+1))
        elif m in ['oak_slab_top','spruce_slab_top']:result[x,y].append((h+.5,h+1))
        elif m in ['oak_slab','spruce_slab']:result[x,y].append((h,h+.5))
    merged={}
    for xy,parts in result.items():
        intervals=[]
        for lo,hi in sorted(parts):
            if intervals and lo<=intervals[-1][1]+1e-6:intervals[-1][1]=max(hi,intervals[-1][1])
            else:intervals.append([lo,hi])
        merged[xy]=intervals
    return merged


def conflict(proposal,terrain,old,head,walk):
    for (x,h,y),m in proposal.items():
        if (x,y) not in terrain:return 'outside_terrain'
        if h<=terrain[x,y]['y']:return 'terrain_intersection'
        if (x,h,y) in old:return 'retained_geometry'
        occupied=[(x,h,y)]+([(x,h+1,y)] if m in FENCES or '_fence_gate' in m else [])
        if any(k in head for k in occupied):return 'track_headroom'
        if any(k in walk for k in occupied):return 'pedestrian_clearance'
    return None


def make_bent(pair,track_intervals,terrain,samples,centre_keys,track,profile):
    posts=[tuple(map(math.floor,p['xy'])) for p in pair['posts']]
    for xy in posts:
        if xy not in terrain:return {},{},'outside_terrain'
        if terrain[xy]['material'] not in ['grass_block','brown_wool','blue_wool','orange_wool']:return {},{},'post_on_paving_or_other_land_use'
    nearest=min(range(len(samples)),key=lambda i:abs(samples[i]['station_m']-pair['station_m']))
    key=tuple(centre_keys[nearest]);m=track[key];top=key[1]+(.5 if m.endswith('_slab') else 1)
    span=staircase_line((posts[0][0],0,posts[0][1]),(posts[1][0],0,posts[1][1]));joins=[]
    for x,_,y in span:
        for lo,hi in track_intervals.get((x,y),[]):
            if abs(hi-top)<=1.5:joins.append((lo,(x,y),hi))
    if not joins:return {},{},'source_span_misses_deck'
    underside,join_xy,join_top=min(joins);beam=math.floor(underside)-1
    bases=[terrain[xy]['y']+1 for xy in posts]
    if beam<max(bases):return {},{},'ground_borne_or_insufficient_fence_clearance'
    if beam-min(bases)>32:return {},{},'height_budget'
    proposal={};level0=max(bases);levels=list(range(level0,beam,3))+[beam]
    if levels[0]!=level0:levels.insert(0,level0)
    levels=sorted(set(levels))
    # Horizontal crossmembers and transverse X-braces span measured plan posts.
    for h in levels:
        for x,_,y in span:proposal[x,h,y]='oak_fence'
    for low,high in zip(levels,levels[1:]):
        if high-low<2:continue
        for forward,material in [(True,'spruce_fence'),(False,'nether_brick_fence')]:
            a=(posts[0][0],low if forward else high,posts[0][1]);b=(posts[1][0],high if forward else low,posts[1][1])
            for k in staircase_line(a,b):proposal[k]=material
    # Uprights take precedence at brace junctions, keeping each post continuous.
    for xy,base in zip(posts,bases):
        for h in range(base,beam+1):proposal[xy[0],h,xy[1]]='spruce_fence'
    receipt={'source_pair':pair,'post_cells_xy':[list(p) for p in posts],'base_heights':bases,'beam_height':beam,'crossmember_levels':levels,
             'join_cell_xy':list(join_xy),'deck_underside_m':underside,'deck_top_m':join_top,'structural_cells':len(proposal)}
    return proposal,receipt,None


def add_caps(proposal,receipt,terrain,old,head,walk):
    added=0
    for x,y in receipt['post_cells_xy']:
        h=receipt['beam_height'];options={(x,h+1,y):'oak_trapdoor'}
        dx,dy=(1 if x>=receipt['join_cell_xy'][0] else -1,0) if abs(x-receipt['join_cell_xy'][0])>=abs(y-receipt['join_cell_xy'][1]) else (0,1 if y>=receipt['join_cell_xy'][1] else -1)
        facing='east' if dx>0 else 'west' if dx<0 else 'north' if dy>0 else 'south'
        for level in receipt['crossmember_levels']:options[x+dx,level,y+dy]='oak_trapdoor_'+facing
        for k,m in options.items():
            if k not in proposal and not conflict({k:m},terrain,old,head,walk):proposal[k]=m;added+=1
    receipt['trapdoor_caps']=added


def validate_connected(proposal,feet,join):
    pending=[next(iter(proposal))];seen=set(pending)
    while pending:
        x,h,y=pending.pop()
        for k in [(x-1,h,y),(x+1,h,y),(x,h-1,y),(x,h+1,y),(x,h,y-1),(x,h,y+1)]:
            if k in proposal and k not in seen:seen.add(k);pending.append(k)
    if len(seen)!=len(proposal) or not set(feet)<=seen or join not in seen:raise ValueError('Unsupported or disconnected frame cells')


def build(pairs,terrain,old,head,samples,keys,track,profile):
    intervals=deck_intervals(track);support={};accepted=[];held=[];walk=set()
    for (x,y),r in terrain.items():
        if r['material'] not in ['grass_block','brown_wool','blue_wool','orange_wool','purple_wool','yellow_wool']:
            walk.update((x,h,y) for h in range(r['y']+1,r['y']+4))
    for pair in pairs:
        proposal,receipt,reason=make_bent(pair,intervals,terrain,samples,keys,track,profile)
        reason=reason or conflict(proposal,terrain,old,head,walk)
        if reason:held.append({'source_pair':pair,'reason':reason});continue
        add_caps(proposal,receipt,terrain,old,head,walk)
        feet=[(x,h,y) for (x,y),h in zip(receipt['post_cells_xy'],receipt['base_heights'])]
        join=(receipt['join_cell_xy'][0],receipt['beam_height'],receipt['join_cell_xy'][1])
        validate_connected(proposal,feet,join)
        for k,m in proposal.items():
            if k not in support or ('trapdoor' in support[k] and m in FENCES):support[k]=m
        accepted.append(receipt)
    links=[];held_links=[]
    for a,b in zip(accepted,accepted[1:]):
        if b['source_pair']['station_m']-a['source_pair']['station_m']>profile['max_link_station_gap_m']:continue
        proposal={}
        for side in [0,1]:
            p=a['post_cells_xy'][side];q=b['post_cells_xy'][side]
            if math.dist(p,q)>8:continue
            ha,hb=a['beam_height'],b['beam_height']
            if abs(ha-hb)>4:continue
            # Side stringers and crossed longitudinal braces tie neighbouring bents.
            for k in staircase_line((p[0],ha,p[1]),(q[0],hb,q[1])):proposal[k]='oak_fence'
            lowa=max(a['base_heights'][side],ha-3);lowb=max(b['base_heights'][side],hb-3)
            if ha-lowa>=2 and hb-lowb>=2:
                for start,end in [((p[0],lowa,p[1]),(q[0],hb,q[1])),((p[0],ha,p[1]),(q[0],lowb,q[1]))]:
                    for k in staircase_line(start,end):proposal.setdefault(k,'nether_brick_fence')
        reason=conflict(proposal,terrain,old,head,walk)
        if reason:held_links.append({'from_station_m':a['source_pair']['station_m'],'to_station_m':b['source_pair']['station_m'],'reason':reason});continue
        if proposal:
            for k,m in proposal.items():
                if k not in support or ('trapdoor' in support[k] and m in FENCES):support[k]=m
            links.append({'from_station_m':a['source_pair']['station_m'],'to_station_m':b['source_pair']['station_m'],'cells':len(proposal)})
    if len(accepted)<8:raise ValueError('Too few source frames fit without altering the park')
    if len(support)>profile['max_added_blocks']:raise ValueError('Support build budget exceeded')
    return support,{'constructed_bents':accepted,'withheld_bents':held,'longitudinal_links':links,'withheld_links':held_links,'added_support_cells':len(support),
                    'style':'spruce fence uprights; oak fence crossmembers; stepped spruce/nether-brick fence X-braces; oak trapdoor plates',
                    'engineering_dimensions_verified':False,'diagonals_are_voxel_stair_steps':True}


def run(base_directory,markings_path,pdf_path,output,*,cancelled=lambda:False,style='reference',cloud_path=None,cloud_receipt=None):
    if style not in ['reference','dense','footprint']:raise ValueError('Unknown support style')
    if cancelled():raise CancelledError('Supports cancelled')
    base_directory=Path(base_directory);output=Path(output);profile=json.loads(PROFILE.read_text())
    if output.exists():raise ValueError('Fresh support output required')
    for name,sha in profile['base_pins'].items():
        if file_hash(base_directory/name)!=sha:raise ValueError('Exact solid-step track world required')
    profile={**profile,'support_style':style}
    from . import dense_trestle
    route,pairs,source=dense_trestle.source_frames(markings_path,pdf_path,profile,cancelled)
    base=json.loads((base_directory/'quality-report.json').read_text());rows=[json.loads(l) for l in (base_directory/'voxels.jsonl').read_text().splitlines()]
    terrain={(r['x'],r['z']-1):r for r in rows if r['kind']=='terrain'};old={(r['x'],r['y'],r['z']-1):r['material'] for r in rows if r['kind']=='structure'}
    track={tuple(r['source_xyz']):r['material'] for r in json.loads((base_directory/'track-blocks.json').read_text())};head={tuple(k) for k in json.loads((base_directory/'running-clearance-air.json').read_text())}
    samples=json.loads((base_directory/'track-samples.json').read_text());keys=base['full_track']['topology']['centre_sample_keys']
    if style=='footprint':
        from . import footprint_supports
        if not cloud_path or not cloud_receipt:raise ValueError('Dated native point cloud and crop receipt required')
        profile.update(markings_path=str(markings_path),isolated_symbols=source['unresolved_isolated_symbols'],cloud_path=str(cloud_path),cloud_receipt=str(cloud_receipt),nominal_to_bng=base['alignment']['nominal_local_xy_to_bng_en_affine'])
        support,review=footprint_supports.build(route,pairs,terrain,old,head,samples,keys,track,profile)
    else:
        support,review=dense_trestle.build(route,pairs,terrain,old,head,samples,keys,track,profile)
    report=dict(base);report.update(version='reference-support-frames-v3' if style=='reference' else 'dense-fence-support-world-v2',support_style=style,implementation_sha256=file_hash(__file__),profile_sha256=file_hash(PROFILE),dense_implementation_sha256=file_hash(dense_trestle.__file__),bedrock_implementation_sha256=file_hash(Path(__file__).with_name('bedrock.py')),source_parent_world_sha256=base['world']['sha256'])
    if style=='footprint':
        report.update(version='footprint-centre-supports-v1',footprint_implementation_sha256=file_hash(footprint_supports.__file__))
    report['full_track']=dict(base['full_track']);report['full_track']['supports_constructed']=len(review.get('constructed_supports',review.get('constructed_bents',[])))
    report['fence_supports']={**review,'source_review':source,'source_pdf_sha256':profile['source_pdf_sha256'],'markings_sha256':profile['markings_sha256'],
        'limitations':['Plan post-symbol centroids guide XY; symbol dimensions are not verified footing sizes.','Both main-row and smaller outer-footing symbols are recovered. Native cross-lines group measured footings; isolated symbols and infeasible legs are reported without shifting their XY.','Beam levels and member sizes are reconstruction estimates. Reference style replaces the diagonal lattice with segmented fence uprights, gates and flat trapdoor tiers.' if style=='reference' else 'Beam levels, member sizes and X-brace shape are reconstruction estimates. Vanilla fences approximate diagonals with connected voxel steps.','Track heights, terrain, roofs, existing blocks and centre clearance remain unchanged.']}
    if style=='footprint':
        report['fence_supports']['limitations']=['Footprints and native brown cross-lines determine starts and branch assignments; metre-grid fence members approximate continuous geometry.','LiDAR is a dated aerial survey: canopy, sparse returns and occluded lower track prevent exact timber identification.','Ambiguous or obstructed connections are withheld whole; no routing through a lower deck or arbitrary new footings.','Track heights, terrain, buildings and walking clearances remain unchanged.']
    output.parent.mkdir(parents=True,exist_ok=True)
    from . import bedrock,planning_station_preshow_world as checker,timber_track_world as renderer
    from .planning_world_preview import _verify_archive,_spawn_check
    with tempfile.TemporaryDirectory(prefix='fence-support-',dir=output.parent) as temp:
        root=Path(temp)/'result';root.mkdir();voxels=root/'voxels.jsonl'
        with voxels.open('w') as stream:
            for r in terrain.values():stream.write(json.dumps(r)+'\n')
            for (x,h,y),m in sorted({**old,**support}.items()):stream.write(json.dumps({'x':x,'y':h,'z':y+1,'kind':'structure','material':m})+'\n')
        def check(path,offset,spawn):
            if offset!=base['world']['vertical_offset_blocks']:raise ValueError('World offset changed')
            report['spawn_validation']=_spawn_check(path,spawn);report['support_track_air_native']=checker._native_air(path,offset,head)
            surfaces={tuple(k) for k in keys}
            report['support_track_surfaces_native']=checker._native_surfaces(path,offset,[{'source_cell_xy':[x,y],'walking_top_m':h+(.5 if track[x,h,y].endswith('_slab') else 1)} for x,h,y in surfaces])
            atomic_json(path/'FENCE-SUPPORT-ASSUMPTIONS.json',report['fence_supports'])
        title='Wicker FOOTPRINT TO CENTRE - dark oak supports' if style=='footprint' else 'Wicker REFERENCE FRAMES - mixed posts gates trapdoors' if style=='reference' else 'Wicker DENSE TRESTLE - separate diagonal braces'
        world=bedrock.export_world(voxels,root,report,name=title,max_blocks=1_000_000,ground_depth=3,foundation_mode='chunk',post_export_check=check)
        report['world']=world;report['archive_validation']=_verify_archive(root/world['file'],root/'bedrock-world',world,cancelled)
        shutil.move(root/world['file'],root/'wicker-fence-supports.mcworld');report['world']['file']='wicker-fence-supports.mcworld';shutil.rmtree(root/'bedrock-world')
        atomic_json(root/'quality-report.json',report);atomic_json(root/'support-blocks.json',[{'source_xyz':list(k),'material':m} for k,m in sorted(support.items())])
        for name in ['track-blocks.json','track-samples.json','running-clearance-air.json']:shutil.copy2(base_directory/name,root/name)
        support_preview(root/'support-preview.png',terrain,{**old,**support},base['full_track']['controls'],track_only=True,caption='Original brown footprints to assigned centreline: dark oak fences only; blocked connections omitted.' if style=='footprint' else None)
        (root/'index.html').write_text('<!doctype html><meta charset="utf-8"><h1>Plan-positioned timber support reconstruction</h1><a href="wicker-fence-supports.mcworld">Download world</a><p>'+review['style']+'. Member sizes are inferred; blocked or ambiguous source positions are reported.</p><img style="max-width:100%" src="support-preview.png">')
        shutil.move(root,output)
    return report


def support_preview(path,terrain,blocks,controls,*,track_only=False,caption=None):
    from PIL import Image,ImageDraw,ImageColor
    from .rock_world_render import _boxes,colour
    xs=[k[0] for k in blocks];ys=[k[2] for k in blocks];lowx=min(xs)-2;highx=max(xs)+3;lowy=min(ys)-2;highy=max(ys)+3
    occupied={(x,h,y):r['material'] for (x,y),r in terrain.items() if lowx<=x<=highx and lowy<=y<=highy for h in [r['y']]};occupied.update(blocks)
    palette={'oak_log':'#9a7945','oak_log_x':'#ac8a54','oak_log_z':'#ac8a54','oak_planks':'#b99758','spruce_planks':'#775637','oak_slab':'#b99758','oak_slab_top':'#b99758','dark_oak_planks':'#4e3522','dark_oak_slab':'#4e3522','oak_fence':'#bba36a','spruce_fence':'#83633f','nether_brick_fence':'#49323f','oak_trapdoor':'#9e7c45','grass_block':'#86a963'}
    datum=min(r['y'] for k,r in terrain.items() if lowx<=k[0]<=highx and lowy<=k[1]<=highy)
    def project(x,h,y):return ((x-y)*9,(x+y)*4.5-(h-datum)*10)
    points=[project(x+dx,h+dh,y+dy) for x,h,y in occupied for dx,dh,dy in [(0,0,0),(1,1.5,1)]];xmin=min(p[0] for p in points);ymin=min(p[1] for p in points)
    image=Image.new('RGB',(math.ceil(max(p[0] for p in points)-xmin)+100,math.ceil(max(p[1] for p in points)-ymin)+150),'#f7f5ed');draw=ImageDraw.Draw(image);faces=[]
    for (x,h,y),m in occupied.items():
        paint='#4e3522' if m.startswith('dark_oak_') else '#775637' if m.startswith('spruce_') else '#9e7c45' if 'trapdoor' in m else palette.get(m.removesuffix('_top'),colour(m));rgb=ImageColor.getrgb(paint)
        neighbors=[(dx,dy) for dx,dy in [(1,0),(-1,0),(0,1),(0,-1)] if (occupied.get((x+dx,h,y+dy)) in ['oak_fence','spruce_fence','dark_oak_fence'] if m in ['oak_fence','spruce_fence','dark_oak_fence'] else occupied.get((x+dx,h,y+dy))==m)]
        if m.endswith('_trapdoor_top'):
            bounds=[(0,.8125,0,1,1,1)]
        elif '_trapdoor_' in m:
            direction=m.rsplit('_',1)[1];bounds=[{'north':(0,0,0,1,1,.1875),'south':(0,0,.8125,1,1,1),'east':(0,0,0,.1875,1,1),'west':(.8125,0,0,1,1,1)}[direction]]
        elif '_fence_gate_' in m:
            d=m.rsplit('_',1)[1];bounds=[(0,.3,.375,1,.85,.625)] if d in ['north','south'] else [(.375,.3,0,.625,.85,1)]
        else:bounds=[(0,.5,0,1,1,1)] if m.endswith('_slab_top') else [(0,0,0,1,.1875,1)] if m=='oak_trapdoor' else _boxes('oak_fence' if m.endswith('_fence') else m,neighbors)
        for x0,h0,y0,x1,h1,y1 in bounds:
            v=[(x+x0,h+h0,y+y0),(x+x1,h+h0,y+y0),(x+x1,h+h0,y+y1),(x+x0,h+h0,y+y1),(x+x0,h+h1,y+y0),(x+x1,h+h1,y+y0),(x+x1,h+h1,y+y1),(x+x0,h+h1,y+y1)]
            for ids,shade in [([1,2,6,5],.78),([2,3,7,6],.59),([4,5,6,7],1)]:
                vertices=[v[i] for i in ids];depth=sum(a+c+.7*b for a,b,c in vertices)/4;polygon=[(project(*p)[0]-xmin+40,project(*p)[1]-ymin+85) for p in vertices]
                faces.append((depth,polygon,tuple(round(c*shade) for c in rgb)))
    for _,polygon,rgb in sorted(faces,key=lambda f:f[0]):draw.polygon(polygon,fill=rgb,outline=tuple(max(0,c-12) for c in rgb))
    draw.rectangle((0,0,image.width,62),fill='#f7f5ed');draw.text((18,14),('WICKER MAN: fence support reconstruction' if track_only else 'WICKER MAN: first source-bound timber track and support section'),fill='black');draw.text((18,35),caption or 'Source-positioned mixed fence frames, gate crosspieces and flat trapdoors; structural details remain provisional.',fill='black')
    image.save(path)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['base-directory','markings-path','pdf-path','output']:p.add_argument('--'+name,required=True)
    p.add_argument('--style',choices=['reference','dense','footprint'],default='reference')
    p.add_argument('--cloud-path');p.add_argument('--cloud-receipt')
    a=p.parse_args(argv);r=run(a.base_directory,a.markings_path,a.pdf_path,a.output,style=a.style,cloud_path=a.cloud_path,cloud_receipt=a.cloud_receipt)
    print(json.dumps({'world_sha256':r['world']['sha256'],'supports':r['full_track']['supports_constructed'],'support_cells':r['fence_supports']['added_support_cells']}))


if __name__=='__main__':main()
