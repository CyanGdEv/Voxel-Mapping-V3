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


def audit_full_route(line,profile,block_at):
    """Audit intended route samples, never just successfully emitted records."""
    from .bedrock import material_block
    gaps=[];cells=set();missing=0;buried=0
    for sample in profile:
        point=line.interpolate(sample['station_m']);x,z=math.floor(point.x),math.floor(point.y);deck=math.floor(sample['corrected_rail_m'])-1
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
        if key in rows and rows[key]['material']!='air' and material=='air':return
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
        deck_cells={};buried=0;angle_records=[]
        for sample_index,s in enumerate(stations):
            p=line.interpolate(float(s));a=line.interpolate(max(0,s-.3));b=line.interpolate(min(line.length,s+.3));dx,dz=b.x-a.x,b.y-a.y;length=math.hypot(dx,dz)
            if not length:continue
            nx,nz=-dz/length,dx/length;h=math.floor(heights[sample_index]);g=terrain.sample(p.x,p.y)
            if g is None:continue
            buried+=h<g
            for side in np.arange(-1.5,1.51,.5):
                x,z=math.floor(p.x+side*nx),math.floor(p.y+side*nz);ground=terrain.sample(x+.5,z+.5)
                if ground is None:continue
                # Retain profile: expose the deck through DTM conflicts, rather
                # than lifting surveyed controls. No unrelated solid shell cut.
                for y in range(h, max(h+4,math.ceil(ground)+1)):
                    add(x,y,z,'air','wicker/graded-clearance',replace=(x,y,z) in owned or (x,y,z) in wicker_architecture,carve=True)
                add(x,h-1,z,'oak_planks' if abs(side)<.75 else 'spruce_planks','wicker/timber-track',replace=(x,h-1,z) in owned,carve=True)
                if abs(side)<.75:deck_cells[(x,h-1,z)]='oak_planks'
                if abs(side)>1:add(x,h,z,'spruce_slab','wicker/track-edge',replace=(x,h,z) in owned,carve=True)
            if context['lift_start_m']<=s<=context['lift_crest_station_m']:
                wx,wz=math.floor(p.x+2*nx),math.floor(p.y+2*nz)
                add(wx,h-1,wz,'spruce_slab','wicker/lift-walkway',replace=(wx,h-1,wz) in owned)
            if abs(s/4-round(s/4))<.05:
                for side in (-1.5,1.5):
                    x,z=p.x+side*nx,p.y+side*nz;base=terrain.sample(x,z)
                    if base is None:continue
                    for y in range(math.floor(base)+1,h-1):add(x,y,z,'oak_fence','wicker/posts',replace=(math.floor(x),y,math.floor(z)) in owned)
                    if h-base>3:
                        rise=min(6,h-base-2);run=min(3,rise);angle_records.append(math.degrees(math.atan2(rise,run)))
                        for t in np.arange(0,1,.12):add(x+dx/length*run*t,h-2-rise*t,z+dz/length*run*t,'oak_fence','wicker/estimated-braces',replace=(math.floor(x+dx/length*run*t),math.floor(h-2-rise*t),math.floor(z+dz/length*run*t)) in owned)
                    add(x,h-3,z,'spruce_trapdoor','wicker/bent-detail',replace=(math.floor(x),h-3,math.floor(z)) in owned)
                for side in np.arange(-1.5,1.51,.5):add(p.x+side*nx,h-2,p.y+side*nz,'oak_fence','wicker/crossbeam',replace=(math.floor(p.x+side*nx),h-2,math.floor(p.y+side*nz)) in owned)
        # Move the retained tunnel shell to the corrected local rail level.
        for key,a in owned.items():
            point=Point(key[0]+.5,key[2]+.5);station=line.project(point);shift=math.floor(float(np.interp(station,stations,heights)))-math.floor(height(station));target=(key[0],key[1]+shift,key[2])
            if a['feature'].endswith('/sound_tunnel_walls'):
                add(*target,'dark_oak_trapdoor' if key[1]%3==0 else 'dark_oak_fence' if (key[0]+key[2])%5==0 else 'dark_oak_planks','wicker/sound-tunnel-frame',replace=target in owned)
            elif a['feature'].endswith('/sound_tunnel_roof'):add(*target,'dark_oak_slab','wicker/sound-tunnel-roof',replace=target in owned)
        # Enforce deck priority after all supports, walkways and tunnel framing.
        for key,material in deck_cells.items():add(*key,material,'wicker/timber-track',replace=key in owned or key in wicker_architecture,carve=True)
        profile=[{'station_m':float(s),'original_rail_m':float(h),'corrected_rail_m':float(v),'terrain_envelope_m':float(g),'uplift_m':float(u)} for s,h,v,g,u in zip(stations,original_heights,heights,ground_envelope,uplift)]
        items.append({'component':'wicker','route_samples':len(stations),'profile':profile,'maximum_uplift_m':float(max(uplift)),'raised_samples':int(np.count_nonzero(uplift)),'remedy':'smooth uplift above original uncut terrain; no trench used to satisfy clearance','height_status':'terrain-constrained preview; changed planning height controls are not asserted as surveyed','brace_angles_status':'estimated; retained application text has no bound support section','estimated_brace_angle_range_degrees':[min(angle_records),max(angle_records)] if angle_records else []})
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
    report={'stations':[],'world_name':'Alton Towers — Wicker track clearance V8','items':items,'records_by_component':dict(collections.Counter(a['feature'].split('/')[0] for a in rows.values())),'rejections':dict(stats),'height_sources':elevation,'raw_osm_sha256':hashlib.sha256(Path(raw_path).read_bytes()).hexdigest(),'limitations':['Transport heights/pier positions are estimates, not planning sections','Wicker brace angles remain estimated; no exact angle annotation found in retained sheets','Landmark shells use mapped outlines and raster heights; detailed facade and inner wall geometry remains unresolved','Pagoda open octagonal three-stage form follows Historic England listing 1192054; dimensions are estimated','Mapped fences/walls use one-block preview heights; materials unspecified'],'references':['https://historicengland.org.uk/listing/the-list/list-entry/1192054','https://historicengland.org.uk/listing/the-list/list-entry/1374685']}
    apply_overlay(source,output,list(rows.values()),report,report_key='park_completion',report_filename='park-completion-report.json')
    reopened=amulet.load_level(str(output/'bedrock-world'));verified_chunks={}
    def exported_block(x,y,z):
        key=(x//16,(-z)//16)
        if key not in verified_chunks:verified_chunks[key]=reopened.get_chunk(*key,'minecraft:overworld')
        ch=verified_chunks[key];return ch.block_palette[int(ch.blocks[x%16,y+offset,(-z)%16])]
    try:checks=audit_full_route(line,profile,exported_block)
    finally:reopened.close()
    (output/'route-clearance-checks.json').write_text(json.dumps(checks,indent=2))
    (output/'completion-overlay.jsonl').write_text(''.join(json.dumps(a)+'\n' for a in rows.values()));print(json.dumps({k:report[k] for k in ('records_by_component','world_verification')},indent=2));return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('source','park','raw-osm','output','datum-grid'):p.add_argument('--'+n,required=True)
    a=p.parse_args();generate(a.source,a.park,a.raw_osm,a.output,a.datum_grid)
if __name__=='__main__':main()
