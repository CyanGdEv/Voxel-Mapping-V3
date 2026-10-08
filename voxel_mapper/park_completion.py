"""Mapped transport, landmark shells and Wicker timber refinement previews."""
import argparse,collections,copy,hashlib,json,math
from pathlib import Path
import numpy as np
import amulet
from pyproj import CRS,Transformer
from shapely.geometry import LineString,Point,Polygon,shape
from shapely.ops import transform
from .terrain import Terrain
from .survey import activate_retained_grid
from .xsector import apply_overlay
from .wicker_reconstruction import local_height_bindings,preview_profile
from .wicker_station import station_context,phase_controls,lift_profile
from .wicker_track import ordered_route


def line_cells(line,spacing=.4):
    """Metre cells sampled along a bounded mapped line, including its endpoint."""
    if line.is_empty or not math.isfinite(line.length) or line.length>10000:raise ValueError('Invalid mapped line')
    cells={};previous=None
    for s in np.r_[np.arange(0,line.length,spacing),line.length]:
        p=line.interpolate(float(s));cell=(math.floor(p.x),math.floor(p.y))
        if previous and cell[0]!=previous[0] and cell[1]!=previous[1]:
            cells[(previous[0],cell[1])]=float(s)
        cells[cell]=float(s);previous=cell
    return cells


def roof_cells(polygon):
    a,b,c,d=polygon.bounds
    if (c-a)*(d-b)>30000:raise ValueError('Landmark footprint budget exceeded')
    return [(x,z) for x in range(math.floor(a),math.ceil(c)) for z in range(math.floor(b),math.ceil(d)) if polygon.covers(Point(x+.5,z+.5))]


def above_terrain_profile(original, ground, spacing=.4, ramp=.12):
    """Smooth periodic uplift above the uncut terrain, with a two-block gap.

    This corrects a provisional preview; it is not a surveyed ride profile.
    A slope-limited upper envelope spreads correction into adjacent spans.
    """
    original=np.asarray(original,dtype=float);ground=np.asarray(ground,dtype=float)
    if original.shape!=ground.shape or original.ndim!=1 or not len(original) or not np.all(np.isfinite(original+ground)) or spacing<=0 or ramp<=0:
        raise ValueError('Finite paired profile and terrain samples required')
    uplift=np.maximum(0,np.floor(ground)+3-np.floor(original))
    n=len(uplift)
    for k in range(2*n):
        i=k%n;uplift[i]=max(uplift[i],uplift[(i-1)%n]-spacing*ramp)
    for k in range(2*n-1,-1,-1):
        i=k%n;uplift[i]=max(uplift[i],uplift[(i+1)%n]-spacing*ramp)
    return original+uplift,uplift


def connected_segment(start,end):
    """Six-connected voxel member, including both joints."""
    current=tuple(map(math.floor,start));target=tuple(map(math.floor,end));cells=[current]
    while current!=target:
        delta=[target[i]-current[i] for i in range(3)]
        axis=max(range(3),key=lambda i:abs(delta[i]))
        nxt=list(current);nxt[axis]+=1 if delta[axis]>0 else -1
        current=tuple(nxt);cells.append(current)
    return cells


def track_masks(line,stations,heights):
    """Raster deck and three-block rider envelope with ramp alias consolidation."""
    columns=collections.defaultdict(list);centres=set()
    for index,(s,h) in enumerate(zip(stations,heights)):
        p=line.interpolate(float(s));a=line.interpolate(max(0,s-.3));b=line.interpolate(min(line.length,s+.3))
        dx,dz=b.x-a.x,b.y-a.y;length=math.hypot(dx,dz);nx,nz=-dz/length,dx/length
        for side in np.arange(-1.5,1.51,.5):
            x,z=math.floor(p.x+side*nx),math.floor(p.y+side*nz)
            columns[x,z].append((math.floor(h)-1,index,abs(side)<.75))
    deck={};envelope=set();sample_decks={}
    for (x,z),entries in columns.items():
        # Consecutive metre cells can contain both sides of a stepped ramp.
        groups=[]
        for entry in sorted(entries,key=lambda v:v[1]):
            if not groups or entry[1]-groups[-1][-1][1]>25:groups.append([])
            groups[-1].append(entry)
        # Join the closed route seam.
        if len(groups)>1 and groups[0][0][1]+len(stations)-groups[-1][-1][1]<=25:
            groups[0]=groups[-1]+groups[0];groups.pop()
        for group in groups:
            y=max(v[0] for v in group);central=any(v[2] for v in group)
            deck[x,y,z]='oak_planks' if central else 'spruce_planks'
            if central:
                centres.add((x,y,z))
                for v in group:
                    if v[2]:sample_decks[v[1],x,z]=y
                envelope.update((x,y+dy,z) for dy in (1,2,3))
    conflicts=envelope.intersection(deck)
    if conflicts:raise ValueError(f'Overlapping rider envelopes and crossing decks: {len(conflicts)} cells')
    return deck,envelope,centres,sample_decks


def separate_crossings(line,stations,original,heights):
    """Use one consistent over/under order per spatial crossing region."""
    heights=np.array(heights,copy=True);columns=collections.defaultdict(set)
    for i,s in enumerate(stations):
        p=line.interpolate(float(s));a=line.interpolate(max(0,s-.3));b=line.interpolate(min(line.length,s+.3))
        dx,dz=b.x-a.x,b.y-a.y;length=math.hypot(dx,dz)
        for side in np.arange(-1.5,1.51,.5):columns[math.floor(p.x-side*dz/length),math.floor(p.y+side*dx/length)].add(i)
    bins=collections.defaultdict(set)
    for indices in columns.values():
        for i in indices:
            for j in indices:
                if i>=j or min(abs(stations[i]-stations[j]),line.length-abs(stations[i]-stations[j]))<15:continue
                bins[i//25,j//25].add((i,j))
    pending=set(bins);constraints=[]
    while pending:
        seed=pending.pop();group={seed};queue=[seed]
        while queue:
            i,j=queue.pop()
            neighbours={(i+di,j+dj) for di in (-1,0,1) for dj in (-1,0,1)} & pending
            pending-=neighbours;group|=neighbours;queue.extend(neighbours)
        pairs=set().union(*(bins[k] for k in group))
        # Do not reverse order independently at each voxel of the same crossing.
        difference=np.median([original[i]-original[j] for i,j in pairs])
        constraints.extend((i,j) if difference<=0 else (j,i) for i,j in pairs)
    initial=heights.copy()
    for iteration in range(40):
        required=heights.copy();count=0
        for lower,upper in constraints:
            if math.floor(heights[upper])-math.floor(heights[lower])<5:
                required[upper]=max(required[upper],math.floor(heights[lower])+5);count+=1
        if not count:
            if max(heights-initial)>20:raise ValueError('Crossing correction exceeds bounded preview budget')
            return heights,iteration
        heights,_=above_terrain_profile(heights,required-3,ramp=.6)
    raise ValueError('Crossing clearance constraints failed to converge')


def audit_bents(bents,block_at):
    """Every structural cell must join a grounded leg and a deck bearing."""
    for bent in bents:
        cells={tuple(k) for k in bent['cells']}
        seeds={(leg[0],leg[1],leg[2]) for leg in bent['legs']}
        reached={next(iter(seeds))};pending=list(reached)
        while pending:
            x,y,z=pending.pop()
            for dx,dy,dz in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)):
                k=x+dx,y+dy,z+dz
                if k in cells and k not in reached:reached.add(k);pending.append(k)
        if reached!=cells or not seeds<=reached:raise ValueError('Disconnected structural bent')
        if any(block_at(x,y-1,z).base_name=='air' for x,y,z in seeds):raise ValueError('Ungrounded bent foundation')
        for x,y,z in bent['deck_contacts']:
            if (x,y-1,z) not in reached or block_at(x,y,z).base_name!='planks':raise ValueError('Bent bearing does not touch track deck')
        if any(block_at(*k).base_name=='air' for k in cells):raise ValueError('Missing bent member')
    return {'grounded_connected_bents':len(bents)}


def audit_envelope(envelope,block_at):
    blocked=[cell for cell in envelope if block_at(*cell).base_name!='air']
    if blocked:raise ValueError(f'Rider envelope obstructed at {len(blocked)} cells; first: {blocked[:5]}')
    return {'rider_envelope_cells_checked':len(envelope),'obstructed_rider_envelope_cells':len(blocked),'headroom_blocks':3}


def audit_full_route(line,profile,block_at):
    """Audit intended route samples, never just successfully emitted records."""
    from .bedrock import material_block
    gaps=[];cells=set();missing=0;buried=0
    for sample in profile:
        point=line.interpolate(sample['station_m']);x,z=math.floor(point.x),math.floor(point.y);deck=sample.get('raster_deck_m',math.floor(sample['corrected_rail_m'])-1)
        cells.add((x,deck,z));gaps.append(deck-math.floor(sample['terrain_envelope_m']))
        missing+=block_at(x,deck,z)!=material_block('oak_planks')
        buried+=block_at(x,deck+1,z).base_name in ('grass_block','dirt','stone','granite','sand')
    if not gaps or missing or buried or min(gaps)<2:raise ValueError(f'Full route clearance failed: missing deck={missing}, buried={buried}')
    return {'route_samples_checked':len(profile),'unique_centre_deck_cells':len(cells),'minimum_deck_above_original_terrain_blocks':min(gaps),'missing_deck_samples':int(missing),'terrain_above_deck_samples':int(buried)}


def generate(source,park,raw_path,output,grid):
    source,park,output=map(Path,(source,park,output));raw=json.loads(Path(raw_path).read_text());q=json.loads((source/'quality-report.json').read_text());c=json.loads((source/'resolved-config.json').read_text());crs=CRS.from_wkt(q['crs']);project=Transformer.from_crs(4326,crs,always_xy=True)
    datum=copy.deepcopy(next(s for s in c['sources'] if s['id']=='ea-dtm'));datum['coordinate_transform']['grid']['file']=str(Path(grid).resolve());activate_retained_grid(datum)
    sources={s['id']:s for s in c['sources']};terrain=Terrain(c['terrain'],crs,sources);surface=Terrain(c['surface'],crs,sources);boundary=transform(project.transform,shape(c['boundary_geojson']));offset=q['world']['vertical_offset_blocks'];level=amulet.load_level(str(source/'bedrock-world'));chunks={};coords=set(level.all_chunk_coords('minecraft:overworld'));rows={};stats=collections.Counter();items=[];owned={}
    # Only the exact retained reconstruction mask permits replacement of ride
    # structure. Paving/landscape/detail masks are never blanket-cleared.
    components=('track_rails','track_ties','timber_bents','lift_chain','lift_walkway','sound_tunnel_walls','sound_tunnel_roof');wicker_architecture=set()
    for text in (park/'voxels.jsonl').open():
        a=json.loads(text)
        if a.get('source')=='wicker-estimated-reconstruction' and any(a.get('feature','').endswith('/'+part) for part in components):owned[(a['x'],a['y'],a['z'])]=a
        if a.get('source')=='wicker-estimated-reconstruction' and a.get('feature','').endswith(('_walls','_roof','_platform','/sound_screens','/sound_screen_posts')):wicker_architecture.add((a['x'],a['y'],a['z']))
    def old(x,y,z):
        mc=(x//16,(-z)//16)
        if mc not in coords or not -64<=y+offset<=319:return None
        if mc not in chunks:chunks[mc]=level.get_chunk(*mc,'minecraft:overworld')
        ch=chunks[mc];return ch.block_palette[int(ch.blocks[x%16,y+offset,(-z)%16])]
    def add(x,y,z,material,feature,replace=False,carve=False):
        key=(math.floor(x),math.floor(y),math.floor(z));x,y,z=key
        if not boundary.covers(Point(x+.5,z+.5)):stats['outside_boundary']+=1;return
        b=old(x,y,z)
        if b is None:stats['outside_world']+=1;return
        if key in rows and rows[key]['material']!='air' and material=='air' and not replace:return
        if not replace and b.base_name!='air' and not (carve and b.base_name in ('grass_block','dirt','stone','granite','gravel','sand')):stats['occupied_withheld']+=1;return
        rows[key]={'x':x,'y':y,'z':z,'kind':'structure','material':material,'feature':feature,'source':'park-completion-preview','material_origin':'estimated_reconstruction_void' if material=='air' else 'estimated_reconstruction_shell'}
        if len(rows)>150000:raise ValueError('Completion overlay budget exceeded')
    try:
        # Remove the prior timber/rail shell only where it still matches its
        # expected block. Ground excavation happens separately, with a small mask.
        from .bedrock import material_block
        for key,a in owned.items():
            b=old(*key)
            if b is not None and b==material_block(a['material']):add(*key,'air','wicker/old-shell-removal',replace=True)
        ways=[e for e in raw['elements'] if e.get('tags',{}).get('name')=='Wicker Man' and e['tags'].get('roller_coaster')=='track'];route=ordered_route(ways,project.transform);line=LineString([route['segments'][0]['start']]+[s['end'] for s in route['segments']]);bindings=local_height_bindings(json.loads((park/'wicker-man-track-association.json').read_text()),route);context=station_context(raw,route,project.transform,json.loads((park/'wicker-man-planning-evidence.json').read_text()),bindings);bindings+=phase_controls(context)
        def height(s):
            if context['lift_start_m']<=s<=context['lift_crest_station_m']:return float(lift_profile([s],context['lift_start_m'],context['lift_crest_station_m'],context['lift_foot_level_m'],context['lift_crest_level_m'])[0])
            return float(preview_profile(route,bindings,[s])[0])
        stations=np.arange(0,line.length,.4);original_heights=np.array([height(s) for s in stations]);ground_envelope=[]
        for s in stations:
            p=line.interpolate(float(s));a=line.interpolate(max(0,s-.3));b=line.interpolate(min(line.length,s+.3));dx,dz=b.x-a.x,b.y-a.y;length=math.hypot(dx,dz)
            if not length:raise ValueError('Undefined route tangent')
            values=[terrain.sample(math.floor(p.x-side*dz/length)+.5,math.floor(p.y+side*dx/length)+.5) for side in np.arange(-2.5,2.51,.5)]
            if any(v is None for v in values):raise ValueError('Full track terrain envelope unavailable')
            ground_envelope.append(max(values))
        heights,uplift=above_terrain_profile(original_heights,ground_envelope)
        heights,crossing_iterations=separate_crossings(line,stations,original_heights,heights)
        uplift=heights-original_heights
        all_decks,rider_envelope,centre_decks,sample_decks=track_masks(line,stations,heights)
        angle_records=[];support_members={};support_bents=[]
        def structural_cell(key):
            if key in rider_envelope or key in all_decks:return False
            b=old(*key)
            return b is not None and (b.base_name in ('air','grass_block','dirt','stone','granite','gravel','sand','leaves','oak_leaves','spruce_leaves','vine') or key in owned or key in wicker_architecture)

        for sample_index,s in enumerate(stations):
            p=line.interpolate(float(s));a=line.interpolate(max(0,s-.3));b=line.interpolate(min(line.length,s+.3));dx,dz=b.x-a.x,b.y-a.y;length=math.hypot(dx,dz)
            if not length:continue
            nx,nz=-dz/length,dx/length;h=math.floor(heights[sample_index]);g=terrain.sample(p.x,p.y)
            if g is None:continue
            for side in np.arange(-1.5,1.51,.5):
                x,z=math.floor(p.x+side*nx),math.floor(p.y+side*nz);ground=terrain.sample(x+.5,z+.5)
                if ground is None:continue
                # Local provisional shell removal; final rider mask is applied
                # after deck, trestles and tunnel framing.
                for y in range(h, max(h+4,math.ceil(ground)+1)):
                    add(x,y,z,'air','wicker/graded-clearance',replace=(x,y,z) in owned or (x,y,z) in wicker_architecture,carve=True)
                add(x,h-1,z,'oak_planks' if abs(side)<.75 else 'spruce_planks','wicker/timber-track',replace=(x,h-1,z) in owned,carve=True)
                if abs(side)>1:add(x,h,z,'spruce_slab','wicker/track-edge',replace=(x,h,z) in owned,carve=True)
            if context['lift_start_m']<=s<=context['lift_crest_station_m']:
                wx,wz=math.floor(p.x+2*nx),math.floor(p.y+2*nz)
                add(wx,h-1,wz,'spruce_slab','wicker/lift-walkway',replace=(wx,h-1,wz) in owned)
            if abs(s/4-round(s/4))<.05:
                # Atomic bents: no skipped post blocks, no ornaments in the legs.
                for width in (1.5,2.,2.5,3.):
                    legs=[];members={};contacts=[]
                    for side in (-width,width):
                        x,z=math.floor(p.x+side*nx),math.floor(p.y+side*nz);base=terrain.sample(x+.5,z+.5)
                        # Outriggers connect to the nearest actual deck underside.
                        choices=[k for k in all_decks if abs(k[0]-x)<=2 and abs(k[2]-z)<=2 and abs(k[1]-(h-1))<=1]
                        if base is None or not choices:break
                        contact=min(choices,key=lambda k:(k[0]-x)**2+(k[2]-z)**2)
                        cap=contact[1]-1;bottom=math.floor(base)+1
                        # The sampled DTM may bridge an existing raster cut.
                        # Extend the complete leg down to actual retained ground.
                        minimum=bottom-16
                        while bottom>minimum:
                            footing=(x,bottom-1,z);foundation=old(*footing)
                            if foundation is not None and foundation.base_name not in ('air','leaves','vine') and footing not in owned:break
                            bottom-=1
                        if bottom==minimum or cap<bottom:break
                        legs.append((x,bottom,z,cap));contacts.append(contact)
                        for y in range(bottom,cap):members[x,y,z]='oak_fence'
                        for cell in connected_segment((x,cap,z),(contact[0],cap,contact[2])):members[cell]='spruce_planks'
                    if len(legs)!=2:continue
                    l,r=legs;beam=min(l[3],r[3])
                    for cell in connected_segment((l[0],beam,l[2]),(r[0],beam,r[2])):members[cell]='spruce_planks'
                    bottom=max(l[1],r[1]);rise=beam-bottom
                    if rise>=3:
                        # Repeated braced panels avoid a single steep full-height X.
                        for lo in range(bottom,beam-1,3):
                            hi=min(lo+3,beam-1)
                            for start,end in [((l[0],lo,l[2]),(r[0],hi,r[2])),((r[0],lo,r[2]),(l[0],hi,l[2]))]:
                                for cell in connected_segment(start,end):members.setdefault(cell,'oak_fence')
                            for cell in connected_segment((l[0],hi,l[2]),(r[0],hi,r[2])):members.setdefault(cell,'oak_fence')
                            angle_records.append(math.degrees(math.atan2(hi-lo,math.hypot(l[0]-r[0],l[2]-r[2]))))
                    if not all(structural_cell(k) for k in members):continue
                    support_members.update(members)
                    support_bents.append({'station_m':float(s),'legs':legs,'deck_contacts':contacts,'cells':[list(k) for k in members]})
                    break
        # Join successive bents with longitudinal braces on both trestle faces.
        longitudinal_members=0
        for first,second in zip(support_bents,support_bents[1:]):
            if second['station_m']-first['station_m']>8.1:continue
            for leg_a,leg_b in zip(first['legs'],second['legs']):
                xa,ba,za,ta=leg_a;xb,bb,zb,tb=leg_b
                lo=max(ba,bb);hi=min(ta,tb)-1
                if hi-lo<2:continue
                extra=set()
                for start,end in [((xa,hi,za),(xb,hi,zb)),((xa,max(lo,hi-3),za),(xb,hi,zb)),((xa,hi,za),(xb,max(lo,hi-3),zb))]:
                    extra.update(connected_segment(start,end))
                if not all(structural_cell(k) for k in extra):continue
                for k in extra:support_members.setdefault(k,'oak_fence')
                first['cells'].extend(list(k) for k in extra if list(k) not in first['cells'])
                longitudinal_members+=1
        # Move the retained tunnel shell to the corrected local rail level.
        for key,a in owned.items():
            point=Point(key[0]+.5,key[2]+.5);station=line.project(point);shift=math.floor(float(np.interp(station,stations,heights)))-math.floor(height(station));target=(key[0],key[1]+shift,key[2])
            if a['feature'].endswith('/sound_tunnel_walls'):
                add(*target,'dark_oak_trapdoor' if key[1]%3==0 else 'dark_oak_fence' if (key[0]+key[2])%5==0 else 'dark_oak_planks','wicker/sound-tunnel-frame',replace=target in owned)
            elif a['feature'].endswith('/sound_tunnel_roof'):add(*target,'dark_oak_slab','wicker/sound-tunnel-roof',replace=target in owned)
        for key,material in support_members.items():add(*key,material,'wicker/connected-trestles',replace=True)
        # Final deck and clearance masks outrank provisional tunnel timber.
        for key,material in all_decks.items():add(*key,material,'wicker/timber-track',replace=True)
        for key in rider_envelope:add(*key,'air','wicker/rider-clearance',replace=True)
        profile=[{'station_m':float(s),'original_rail_m':float(h),'corrected_rail_m':float(v),'terrain_envelope_m':float(g),'uplift_m':float(u)} for s,h,v,g,u in zip(stations,original_heights,heights,ground_envelope,uplift)]
        for i,sample in enumerate(profile):
            pt=line.interpolate(sample['station_m']);sample['raster_deck_m']=sample_decks[i,math.floor(pt.x),math.floor(pt.y)]
        items.append({'component':'wicker','route_samples':len(stations),'profile':profile,'maximum_uplift_m':float(max(uplift)),'raised_samples':int(np.count_nonzero(uplift)),'remedy':'terrain and crossing constrained profile; final three-block rider envelope', 'crossing_constraint_iterations':crossing_iterations,'connected_bents':len(support_bents),'longitudinal_braced_spans':longitudinal_members,'height_status':'terrain-constrained preview; changed planning height controls are not asserted as surveyed','brace_angles_status':'estimated; retained application text has no bound support section','estimated_brace_angle_range_degrees':[min(angle_records),max(angle_records)] if angle_records else []})
        for e in raw['elements']:
            tags=e.get('tags',{});geom=e.get('geometry',[])
            if len(geom)<2:continue
            pts=[project.transform(a['lon'],a['lat']) for a in geom];l=LineString(pts);fid=str(e['id'])
            if tags.get('railway')=='monorail' or tags.get('aerialway')=='gondola':
                sky=tags.get('aerialway')=='gondola';name='skyride' if sky else 'monorail';material='iron_bars' if sky else 'cobblestone_wall';vertices=[terrain.sample(x,z) for x,z in pts]
                if any(a is None for a in vertices):items.append({'component':name,'osm_id':e['id'],'status':'withheld_missing_endpoint_terrain'});continue
                # Cable spans interpolate between mapped vertices; these are not
                # surveyed pylon positions. Beam elevations are a preview only.
                distances=[l.project(Point(*p)) for p in pts];levels=np.array(vertices)+(12 if sky else 7)
                for (x,z),s in line_cells(l).items():
                    g=terrain.sample(x+.5,z+.5)
                    if g is None:continue
                    h=max(g+6,float(np.interp(s,distances,levels)));add(x,h,z,material,name+'/'+fid)
                    if not sky and int(s)%20==0:
                        for y in range(math.floor(g)+1,math.floor(h)):add(x,y,z,'cobblestone_wall',name+'/estimated-piers/'+fid)
                if sky:
                    for (x,z),h,g in zip(pts,levels,vertices):
                        for y in range(math.floor(g)+1,math.floor(h)):add(x,y,z,'cobblestone_wall',name+'/mapped-vertex-support/'+fid)
                items.append({'component':name,'osm_id':e['id'],'horizontal_geometry':'retained OSM','height_status':'estimated ground clearance; no surveyed transport levels','supports_status':'estimated at mapped vertices or regular spacing'})
            elif tags.get('barrier') in ('fence','wall','retaining_wall','gate','turnstile'):
                name=tags['barrier'];mat='oak_fence_gate' if name in ('gate','turnstile') else 'oak_fence' if name=='fence' else 'cobblestone_wall'
                for x,z in line_cells(l):
                    g=terrain.sample(x+.5,z+.5)
                    if g is not None:add(x,math.floor(g)+1,z,mat,'barrier/'+name+'/'+fid)
                items.append({'component':'barrier','osm_id':e['id'],'kind':name,'height_material_status':'one-block preview; unspecified material'})
            elif tags.get('name') in ('Chinese Pagoda','Main Entrance') or tags.get('historic')=='ruins':
                if pts[0]!=pts[-1]:continue
                polygon=Polygon(pts);cells=roof_cells(polygon)
                if not cells:continue
                samples=[(x,z,terrain.sample(x+.5,z+.5),surface.sample(x+.5,z+.5)) for x,z in cells];valid=[a for a in samples if a[2] is not None and a[3] is not None]
                if len(valid)<len(cells)*.9:items.append({'component':'landmark','osm_id':e['id'],'status':'withheld_height_coverage'});continue
                base=math.floor(float(np.median([a[2] for a in valid])));top=math.ceil(float(np.percentile([a[3] for a in valid],95)));top=min(base+30,top)
                if top<base+3:items.append({'component':'landmark','osm_id':e['id'],'status':'withheld_low_surface_profile'});continue
                name='pagoda' if tags.get('name')=='Chinese Pagoda' else 'entrance' if tags.get('name')=='Main Entrance' else 'ruins';f='landmark/'+name+'/'+fid
                if name=='entrance':top=min(top,base+6)
                # Explicit target footprints permit hollowing the previous solid
                # extrusions. Other buildings and landscaping remain untouched.
                for x,z,g,s in valid:
                    for y in range(math.floor(g)+1,max(top,math.ceil(s))+1):add(x,y,z,'air',f+'/old-box-removal',replace=True)
                if name=='pagoda':
                    centre=polygon.centroid;radius=math.sqrt(polygon.area/math.pi);stage=max(3,(top-base)//3)
                    # Five half-block rises approximate the listed five steps.
                    # At one metre raster size some narrow rings share cells.
                    for step in range(5):
                        step_ring=polygon.buffer(-step*.3)
                        for x,z in roof_cells(step_ring):
                            if step_ring.boundary.distance(Point(x+.5,z+.5))<.7:
                                add(x,base+1+step//2,z,'stone_slab' if step%2==0 else 'stone',f+'/five-step-base',replace=True)
                    for tier in range(3):
                        ring=polygon.buffer(-tier*.6);roof=base+(tier+1)*stage
                        for x,z in roof_cells(ring):
                            p=Point(x+.5,z+.5);edge=ring.boundary.distance(p)<.7
                            if edge:
                                for y in range(base+tier*stage+1,roof):add(x,y,z,'iron_bars',f+'/open-frame',replace=True)
                            rise=math.ceil(max(0,radius*.6-p.distance(centre))) if tier==2 else 0
                            add(x,roof+rise,z,'dark_oak_slab',f+'/tier-canopy',replace=True)
                            if edge:
                                dx,dz=x+.5-centre.x,z+.5-centre.y
                                facing=('east' if dx>0 else 'west') if abs(dx)>abs(dz) else ('north' if dz>0 else 'south')
                                add(x,roof-1,z,'dark_oak_stairs_'+facing,f+'/canopy-edge',replace=True)
                    add(centre.x,base+3*stage+math.ceil(radius*.6)+1,centre.y,'iron_bars',f+'/finial',replace=True)
                elif name=='entrance':
                    for x,z,g,s in valid:
                        add(x,top,z,'spruce_slab',f+'/canopy',replace=True)
                        if polygon.boundary.distance(Point(x+.5,z+.5))<.6 and (x+z)%5==0:
                            for y in range(math.floor(g)+1,top):add(x,y,z,'cobblestone_wall',f+'/posts',replace=True)
                else:
                    for x,z,g,s in valid:
                        if polygon.boundary.distance(Point(x+.5,z+.5))>1.1:continue
                        localtop=min(top,math.floor(s));
                        for y in range(math.floor(g)+1,localtop+1):add(x,y,z,'stone_bricks' if y<localtop else 'cobblestone_wall',f+'/surface-wall-profile',replace=True)
                items.append({'component':name,'osm_id':e['id'],'height_range_odn_m':[base,top],'geometry_status':'mapped outline and raster-guided architectural preview','limitations':'exact internal rooms, openings, roof pitches and facade details unresolved'})
    finally:
        level.close();elevation={'terrain':terrain.report(),'surface':surface.report()};terrain.close();surface.close()
    # Connect wall beams in Minecraft coordinates (local north is negative Z).
    for key,row in rows.items():
        if row['material']!='cobblestone_wall' or not row['feature'].startswith(('monorail/','barrier/')):continue
        x,y,z=key;directions=''
        for label,dx,dz in [('n',0,1),('e',1,0),('s',0,-1),('w',-1,0)]:
            if any(rows.get((x+dx,y+dy,z+dz),{}).get('material','').startswith('cobblestone_wall') for dy in (-1,0,1)):directions+=label
        if directions:row['material']='cobblestone_wall_'+directions
    report={'stations':[],'world_name':'Alton Towers — Wicker connected trestles V9','items':items,'records_by_component':dict(collections.Counter(a['feature'].split('/')[0] for a in rows.values())),'rejections':dict(stats),'height_sources':elevation,'raw_osm_sha256':hashlib.sha256(Path(raw_path).read_bytes()).hexdigest(),'limitations':['Transport heights/pier positions are estimates, not planning sections','Wicker brace angles remain estimated; no exact angle annotation found in retained sheets','Landmark shells use mapped outlines and raster heights; detailed facade and inner wall geometry remains unresolved','Pagoda open octagonal three-stage form follows Historic England listing 1192054; dimensions are estimated','Mapped fences/walls use one-block preview heights; materials unspecified'],'references':['https://historicengland.org.uk/listing/the-list/list-entry/1192054','https://historicengland.org.uk/listing/the-list/list-entry/1374685']}
    apply_overlay(source,output,list(rows.values()),report,report_key='park_completion',report_filename='park-completion-report.json')
    reopened=amulet.load_level(str(output/'bedrock-world'));verified_chunks={}
    def exported_block(x,y,z):
        key=(x//16,(-z)//16)
        if key not in verified_chunks:verified_chunks[key]=reopened.get_chunk(*key,'minecraft:overworld')
        ch=verified_chunks[key];return ch.block_palette[int(ch.blocks[x%16,y+offset,(-z)%16])]
    try:
        checks=audit_full_route(line,profile,exported_block)
        checks.update(audit_envelope(rider_envelope,exported_block))
        checks.update(audit_bents(support_bents,exported_block))
        failures=[key for key,mat in support_members.items() if exported_block(*key)!=material_block(mat)]
        if failures:raise ValueError(f'Support readback failed: {failures[:5]}')
        checks.update({'complete_bents_checked':len(support_bents),'structural_cells_checked':len(support_members),'missing_structural_cells':len(failures)})
    finally:reopened.close()
    (output/'rider-envelope.json').write_text(json.dumps(sorted(rider_envelope)))
    (output/'support-bents.json').write_text(json.dumps(support_bents))
    (output/'route-clearance-checks.json').write_text(json.dumps(checks,indent=2))
    (output/'completion-overlay.jsonl').write_text(''.join(json.dumps(a)+'\n' for a in rows.values()));print(json.dumps({k:report[k] for k in ('records_by_component','world_verification')},indent=2));return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('source','park','raw-osm','output','datum-grid'):p.add_argument('--'+n,required=True)
    a=p.parse_args();generate(a.source,a.park,a.raw_osm,a.output,a.datum_grid)
if __name__=='__main__':main()
