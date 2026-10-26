"""Map-relative registration and LiDAR draping of the retained planning preview.

This is a separate geographic study export, never a production geometry review.
"""
from concurrent.futures import CancelledError
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile

import numpy as np
from shapely.geometry import Polygon,LineString,Point,shape,mapping
from shapely.affinity import affine_transform,scale
from shapely.ops import unary_union

from . import planning_geometry_world as geometry_world
from .generation_cycles import atomic_json,file_hash
from .horizontal_grid import OSTN15Transform

PROFILE_PATH=Path(__file__).with_name('data')/'wicker-map-alignment.json'
MAX_WORLD_WRITES=1_000_000


def profile():
    p=json.loads(PROFILE_PATH.read_text())
    if (p.get('version')!='wicker-map-alignment-profile-v1' or p.get('transform_model')!='rigid_unit_scale_no_reflection'
            or p.get('independent_registration_verified') is not False or len(p.get('controls',[]))!=3):
        raise ValueError('Reviewed map-relative rigid alignment profile required')
    return p


def rigid_fit(local,target):
    a=np.asarray(local,dtype=float);b=np.asarray(target,dtype=float)
    if a.shape!=b.shape or a.ndim!=2 or a.shape[1]!=2 or len(a)<3 or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError('Finite corresponding metric control points required')
    if len(np.unique(a,axis=0))!=len(a) or len(np.unique(b,axis=0))!=len(b):raise ValueError('Distinct control coordinates required')
    ac=a-a.mean(0);bc=b-b.mean(0)
    if np.linalg.matrix_rank(ac)<2 or np.linalg.matrix_rank(bc)<2:raise ValueError('Noncollinear controls required')
    u,_,vt=np.linalg.svd(ac.T@bc);rotation=(u@vt).T
    if np.linalg.det(rotation)<0:raise ValueError('Reflected correspondence rejected')
    translation=b.mean(0)-rotation@a.mean(0)
    return [float(rotation[0,0]),float(rotation[0,1]),float(rotation[1,0]),float(rotation[1,1]),*translation.tolist()]


def references(osm,project):
    rows={}
    def add(identifier,points,tags):
        if len(points)<2:return
        xy=[project.transform(p['lon'],p['lat']) for p in points]
        g=Polygon(xy) if len(xy)>=4 and xy[0]==xy[-1] else LineString(xy)
        if g.is_empty or not g.is_valid:raise ValueError('Valid mapped reference geometry required')
        if identifier in rows and rows[identifier]['geometry'].wkb!=g.wkb:raise ValueError('Conflicting map way geometry')
        rows[identifier]={'geometry':g,'tags':tags}
    if len(osm.get('elements',[]))>10000:raise ValueError('Map reference work budget exceeded')
    for row in osm['elements']:
        if row['type']=='way':add(row['id'],row.get('geometry',[]),row.get('tags',{}))
        elif row['type']=='relation':
            for member in row.get('members',[]):
                if member.get('type')=='way':add(member['ref'],member.get('geometry',[]),{'relation':row['id']})
    return rows


def alignment(data,osm,project):
    p=profile()
    if data['layout']['document_sha256']!=p['document_sha256']:raise ValueError('Reviewed Wicker source required')
    refs=references(osm,project);controls=[];source={}
    for c in p['controls']:
        matches=[r for r in data['buildings']['records'] if c['label'] in [x['text'] for x in r['labels']]]
        if len(matches)!=1:raise ValueError('Unique original labelled building control required')
        g=scale(shape(matches[0]['geometry_pdf_native']),xfact=p['source_metres_per_native_point'],yfact=p['source_metres_per_native_point'],origin=(0,0))
        target=refs[c['osm_way_id']]['geometry']
        if g.geom_type!='Polygon' or target.geom_type!='Polygon':raise ValueError('Polygon correspondence required')
        source[c['label']]=g
        controls.append({'label':c['label'],'source_building_id':matches[0]['id'],'osm_way_id':c['osm_way_id'],
            'local_xy':list(g.centroid.coords[0]),'target_bng_en':list(target.centroid.coords[0])})
    affine=rigid_fit([r['local_xy'] for r in controls],[r['target_bng_en'] for r in controls])
    for c in controls:
        g=affine_transform(source[c['label']],affine);h=refs[c['osm_way_id']]['geometry']
        c.update(centroid_residual_m=g.centroid.distance(h.centroid),footprint_iou=g.intersection(h).area/g.union(h).area)
        if c['centroid_residual_m']>p['max_control_residual_m'] or c['footprint_iou']<p['minimum_control_iou']:
            raise ValueError('Map-relative building correspondence disagrees with retained geometry')
    centre=next(r for r in data['markings']['records'] if r['role']=='track_centre')
    line=affine_transform(scale(shape(centre['geometry_pdf_native']),xfact=p['source_metres_per_native_point'],yfact=p['source_metres_per_native_point'],origin=(0,0)),affine)
    tracks=unary_union([r['geometry'] for r in refs.values() if r['tags'].get('roller_coaster')=='track' and r['tags'].get('name')=='Wicker Man'])
    if tracks.is_empty:raise ValueError('Held-out mapped ride geometry missing')
    distances=[tracks.distance(line.interpolate(i/200,normalized=True)) for i in range(201)]
    checks={'track':{'samples':201,'median_distance_m':float(np.median(distances)),'p95_distance_m':float(np.percentile(distances,95)),
        'maximum_sample_distance_m':max(distances),'symmetric_hausdorff_m':line.hausdorff_distance(tracks),'used_to_fit':False}}
    held=p['held_out_references']
    from .courtyard_plan_expansion import geometry
    court=shape(next(r for r in geometry()[0] if r['key']=='courtyard-floor')['geometry_nominal_local'])
    candidates=[r for r in data['layout']['candidates'] if r['id'].startswith(held['nearby_building_candidate_prefix'])]
    if len(candidates)!=1:raise ValueError('Held-out source building changed')
    for key,g,identifier in [('courtyard',court,held['courtyard_inner_way_id']),('nearby_building',shape(candidates[0]['geometry_nominal_local']),held['nearby_building_way_id'])]:
        g=affine_transform(g,affine);h=refs[identifier]['geometry'];checks[key]={'osm_way_id':identifier,'centroid_residual_m':g.centroid.distance(h.centroid),
            'footprint_iou':g.intersection(h).area/g.union(h).area,'used_to_fit':False,'identity_independently_verified':False}
    return {'version':'wicker-map-relative-alignment-v1','nominal_local_xy_to_bng_en_affine':affine,'scale':1.,'rotation_degrees':math.degrees(math.atan2(affine[2],affine[0])),
        'target_crs':'EPSG:27700','controls':controls,'held_out_map_checks':checks,'independent_registration_verified':False,
        'production_placement_eligible':False,
        'map_check_review_flags':['nearby_building_outline_disagrees_with_osm'] if checks['nearby_building']['footprint_iou']<.8 else [],
        'limitations':p['limitations'],'horizontal_operation':project.report()},refs


def terrain_heights(sampled,affine,path,*,cancelled=lambda:False):
    import rasterio
    a,b,c,d=sampled['bounds'];keys=[(x,y) for x in range(a,c) for y in range(b,d)]
    xy=np.array([(x+.5,y+.5) for x,y in keys]);A,B,C,D,E,N=affine
    points=np.column_stack((A*xy[:,0]+B*xy[:,1]+E,C*xy[:,0]+D*xy[:,1]+N))
    with rasterio.open(path) as ds:
        if ds.crs!=rasterio.crs.CRS.from_epsg(27700) or ds.count!=1 or ds.res!=(1.,1.):raise ValueError('One-metre BNG terrain required')
        heights=[]
        # Batch cancellation and full coverage are checked before native world writing.
        for i in range(0,len(keys),1024):
            if cancelled():raise CancelledError('Terrain sampling cancelled')
            for q in points[i:i+1024]:
                if not ds.bounds.left<=q[0]<ds.bounds.right or not ds.bounds.bottom<q[1]<=ds.bounds.top:raise ValueError('Terrain does not cover complete geometry')
            for value in ds.sample(points[i:i+1024],masked=True):
                if np.ma.is_masked(value[0]) or not np.isfinite(value[0]):raise ValueError('Terrain nodata in requested platform; no interpolation allowed')
                heights.append(float(value[0]))
    raw=dict(zip(keys,heights));rounded={k:math.floor(v) for k,v in raw.items()}
    return rounded,{'sampled_cells':len(keys),'complete_coverage':True,'source_minimum_odn_m':min(heights),'source_maximum_odn_m':max(heights),
        'sampling':'nearest original one-metre pixel at transformed source-cell centre','quantization':'floor to one-metre block; error below one metre',
        'vertical_datum':'ODN','finished_floor_levels_verified':False,'path_design_levels_verified':False,'terrain_is_ground_not_ride_height':True}


def saved_check(path,offset,sampled,heights,cancelled):
    from amulet.level.formats.leveldb_world import LevelDBFormat
    from .bedrock import material_block
    wrapper=LevelDBFormat(str(path));wrapper.open();a,b,c,d=sampled['bounds'];checked=0;edging=0;cache={}
    try:
        for cx in range(a//16,(c-1)//16+1):
            for cy in range(b//16,(d-1)//16+1):
                if cancelled():raise CancelledError('Terrain world verification cancelled')
                chunk=wrapper.load_chunk(cx,-cy-1,'minecraft:overworld')
                for x in range(max(a,cx*16),min(c,(cx+1)*16)):
                    for y in range(max(b,cy*16),min(d,(cy+1)*16)):
                        key=x,y;z=-y-1;column=dict(sampled['rocks'].get(key,[]));ground=heights[key]+offset
                        for level in range(4):
                            name=sampled['ground'].get(key,'grass_block') if level==0 else column.get(level,'air')
                            if name not in cache:cache[name]=material_block(name)
                            actual=chunk.block_palette[int(chunk.blocks[x%16,ground+level,z%16])];wanted=cache[name]
                            if actual.namespaced_name!=wanted.namespaced_name or any(actual.properties.get(k)!=v for k,v in wanted.properties.items()):
                                raise ValueError('Saved terrain/material/edging mismatch')
                            if level in column:edging+=1
                        checked+=1
                del chunk
    finally:wrapper.close()
    if checked!=sampled['platform_cells'] or edging!=sampled['boundary_blocks']:raise ValueError('Incomplete terrain-world readback')
    return {'all_terrain_heights_and_materials_verified':True,'platform_cells_verified':checked,'saved_boundary_blocks_verified':edging,
        'native_block_states_verified':True,'headroom_verified':True,'decoded_chunk_cache_limit':1}


def run(config,output,*,cancelled=lambda:False):
    if (not isinstance(config,dict) or set(config)!={'version','terrain_vertical_datum','geometry_request','osm_path','osm_sha256','dtm_path','dtm_sha256','grid_path','grid_sha256'} or config.get('version')!='planning-geographic-preview-v1' or config.get('terrain_vertical_datum')!='ODN'):raise ValueError('Explicit ODN geographic preview required')
    p=profile();pins={};output=Path(output)
    if output.exists():raise ValueError('Fresh geographic preview output required')
    for name in ('osm','dtm','grid'):
        path=Path(config[name+'_path'])
        if not path.is_file() or path.stat().st_size>16_000_000 or file_hash(path)!=config[name+'_sha256']:raise ValueError('Pinned bounded '+name+' input required')
        pins[name]=file_hash(path)
    if pins['osm']!=p['osm_sha256']:raise ValueError('Reviewed OSM snapshot required')
    data=geometry_world.read_inputs(config['geometry_request']);sampled=geometry_world.rasterize(data,cancelled=cancelled)
    project=OSTN15Transform('EPSG:4326','EPSG:27700',{'method':'ostn15-bng-v1','path':config['grid_path'],'sha256':pins['grid']})
    placement,refs=alignment(data,json.loads(Path(config['osm_path']).read_text()),project)
    heights,terrain=terrain_heights(sampled,placement['nominal_local_xy_to_bng_en_affine'],config['dtm_path'],cancelled=cancelled)
    a,b,c,d=sampled['bounds'];spawn=sampled['retained_spawn_local_xyz_m'];spawn_key=math.floor(spawn[0]),math.floor(spawn[2])-1
    report={'version':'planning-geographic-preview-v1','status':'map_relative_terrain_preview','crs':'EPSG:27700','vertical_datum':'ODN',
        'voxel_size_m':1,'model_blocks_per_source_metre':1,'spawn_local_xyz_m':[spawn[0],heights[spawn_key]+1,spawn[2]],
        'horizontal_transform':{'minecraft_x':'retained plan X; BNG transform in planning-geographic-alignment.json','minecraft_z':'negative retained plan Y; BNG transform in planning-geographic-alignment.json'},
        'alignment':placement,'terrain':terrain,'platform_cells':sampled['platform_cells'],'baseline_ground_feature_cells_preserved':len(sampled['ground']),
        'baseline_plan_marking_cells_preserved':len(sampled['plan_markers']),'baseline_edging_columns_preserved':len(sampled['rocks']),
        'planning_source_pins':{n:config['geometry_request'][n+'_sha256'] for n in data},
        'profile_sha256':file_hash(PROFILE_PATH),'implementation_sha256':file_hash(__file__),
        'plan_markings':sampled['plan_marking_report'],'physical_registration_verified':False,'production_placement_eligible':False,
        'minecraft_import_tested':False,'reconstructed_buildings':0,'training_labels_generated':0,'source_pins':pins,
        'sources':[{'id':'osm','url':'https://www.openstreetmap.org/copyright','attribution':'OpenStreetMap contributors, ODbL-1.0'},
                   {'id':'ea-dtm','url':'https://environment.data.gov.uk/','attribution':'Contains Environment Agency information, OGL-UK-3.0'}]}
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='geo-preview-',dir=output.parent) as temporary:
        root=Path(temporary)/'result';root.mkdir();voxel=root/'voxels.jsonl'
        with voxel.open('w') as stream:
            for x in range(a,c):
                if cancelled():raise CancelledError('Terrain preview writing cancelled')
                for y in range(b,d):
                    h=heights[x,y];rows=[{'x':x,'y':h,'z':y+1,'kind':'terrain','material':sampled['ground'].get((x,y),'grass_block')}]
                    rows.extend({'x':x,'y':h+n,'z':y+1,'kind':'structure','material':m} for n,m in sampled['rocks'].get((x,y),[]))
                    for row in rows:stream.write(json.dumps(row)+'\n')
        from . import bedrock
        from .planning_world_preview import _spawn_check,_verify_archive
        def check(path,offset,native_spawn):
            report['spawn_validation']=_spawn_check(path,native_spawn)
            report['saved_geometry_validation']=saved_check(path,offset,sampled,heights,cancelled)
            transform={**placement,'minecraft_cell_centre_to_source_xy':'[Minecraft X + 0.5, -(Minecraft Z + 0.5)]',
                       'odn_elevation_from_minecraft_y':'Minecraft Y - vertical_offset_blocks','vertical_offset_blocks':offset}
            atomic_json(path/'planning-geographic-alignment.json',transform)
        world=bedrock.export_world(voxel,root,report,name='Wicker and courtyard - OSM and LiDAR alignment study',max_blocks=MAX_WORLD_WRITES,ground_depth=3,foundation_mode='chunk',post_export_check=check)
        report['world']=world;report['archive_validation']=_verify_archive(root/world['file'],root/'bedrock-world',world,cancelled)
        shutil.move(root/world['file'],root/'wicker-geographic-preview.mcworld');report['world']['file']='wicker-geographic-preview.mcworld'
        shutil.rmtree(root/'bedrock-world');atomic_json(root/'alignment.json',placement)
        atomic_json(root/'terrain-samples.json',[{'source_cell_xy':list(k),'surface_odn_block_m':v} for k,v in heights.items()])
        features=[]
        for row in data['buildings']['records']:
            g=scale(shape(row['geometry_pdf_native']),xfact=p['source_metres_per_native_point'],yfact=p['source_metres_per_native_point'],origin=(0,0))
            features.append({'type':'Feature','geometry':mapping(affine_transform(g,placement['nominal_local_xy_to_bng_en_affine'])),'properties':{'role':'planning_building','labels':[r['text'] for r in row['labels']]}})
        for row in data['markings']['records']:
            g=scale(shape(row['geometry_pdf_native']),xfact=p['source_metres_per_native_point'],yfact=p['source_metres_per_native_point'],origin=(0,0))
            features.append({'type':'Feature','geometry':mapping(affine_transform(g,placement['nominal_local_xy_to_bng_en_affine'])),'properties':{'role':row['role'],'key':row['key']}})
        for row in data['paving']['records']:
            if not row.get('legend_claim'):continue
            g=scale(shape(row['geometry']),xfact=p['source_metres_per_native_point'],yfact=p['source_metres_per_native_point'],origin=(0,0))
            features.append({'type':'Feature','geometry':mapping(affine_transform(g,placement['nominal_local_xy_to_bng_en_affine'])),
                'properties':{'role':'planning_paving','id':row['id'],'printed_state':row['legend_claim']['printed_state']}})
        for row in data['expansion']['features']:
            features.append({'type':'Feature','geometry':mapping(affine_transform(shape(row['geometry_nominal_local']),placement['nominal_local_xy_to_bng_en_affine'])),'properties':{'role':row['role'],'key':row['key']}})
        atomic_json(root/'planning-bng.geojson',{'type':'FeatureCollection','crs':{'type':'name','properties':{'name':'EPSG:27700'}},'features':features})
        _overview(root,features,refs,config['dtm_path'],placement,sampled)
        for name in pins:
            if file_hash(config[name+'_path'])!=pins[name]:raise ValueError('Geographic input changed during export')
        geometry_world.read_inputs(config['geometry_request'])
        atomic_json(root/'quality-report.json',report);shutil.move(str(root),output)
    return report


def _overview(root,features,refs,dtm_path,placement,sampled):
    from PIL import Image,ImageDraw
    import rasterio
    from shapely.geometry import box
    with rasterio.open(dtm_path) as ds:
        values=ds.read(1,masked=True);bounds=ds.bounds
    unit=4;width=values.shape[1]*unit;height=values.shape[0]*unit
    t=np.clip((values.filled(180)-175)/22,0,1)
    rgb=np.stack((174+48*t,199-32*t,140-38*t),axis=-1).astype('uint8')
    canvas=Image.new('RGB',(width+100,height+130),'#faf9f3');canvas.paste(Image.fromarray(rgb).resize((width,height)),(75,60));draw=ImageDraw.Draw(canvas)
    def point(q):return (75+(q[0]-bounds.left)*unit,60+(bounds.top-q[1])*unit)
    extent=box(bounds.left,bounds.bottom,bounds.right,bounds.top)
    def lines(g,colour,thickness):
        g=g.intersection(extent)
        for part in (g.geoms if hasattr(g,'geoms') else [g]):
            if part.geom_type=='Polygon':coords=part.exterior.coords
            elif part.geom_type in ('LineString','LinearRing'):coords=part.coords
            else:continue
            coords=[point(q) for q in coords]
            if len(coords)>1:draw.line(coords,fill=colour,width=thickness)
    for r in refs.values():
        if r['geometry'].geom_type=='Polygon' or r['tags'].get('roller_coaster')=='track':lines(r['geometry'],'#40443c',1)
    colours={'track_centre':'#e87910','track_sides':'#2854c9','support_boundaries':'#80532d','queue_area':'#747470','theming_envelope':'#a035bb','building_boundary':'#159ddd','planning_building':'#159ddd','paving':'#787872','planning_paving':'#777a72','passage':'#e5a34b'}
    for row in features:lines(shape(row['geometry']),colours.get(row['properties']['role'],'#159ddd'),2)
    for c in placement['controls']:
        x,y=point(c['target_bng_en']);draw.ellipse((x-4,y-4,x+4,y+4),fill='#d71e5a');draw.text((x+7,y+2),c['label'],fill='#202020')
    for east in range(math.ceil(bounds.left/50)*50,math.floor(bounds.right/50)*50+1,50):
        x,y=point((east,bounds.bottom));draw.text((x-20,y+8),str(east),fill='#303030')
    for north in range(math.ceil(bounds.bottom/50)*50,math.floor(bounds.top/50)*50+1,50):
        x,y=point((bounds.left,north));draw.text((8,y),str(north),fill='#303030')
    draw.text((20,12),'Wicker Man + courtyard: current plan aligned over OSM and EA ground terrain',fill='#202020')
    draw.text((20,31),'BNG metres. Map-relative study, fixed scale 1; OSM black, planning colours. Accuracy is not surveyed.',fill='#303030')
    draw.text((75,height+95),'EA ODN terrain backdrop; blue building outlines, orange ride centre, purple theming envelopes.',fill='#303030')
    draw.line((width-170,height+105,width-170+50*unit,height+105),fill='black',width=3)
    draw.text((width-170,height+113),'50 metres',fill='black');canvas.save(root/'alignment-overview.png')


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args(argv);path=Path(args.config).resolve()
    if path.stat().st_size>32768:raise ValueError('Geographic preview request byte budget exceeded')
    config=json.loads(path.read_text())
    for name in ('osm','dtm','grid'):config[name+'_path']=str((path.parent/config[name+'_path']).resolve())
    for name in ('layout','paving','gaps','buildings','markings','expansion'):
        if name+'_path' in config['geometry_request']:
            config['geometry_request'][name+'_path']=str((path.parent/config['geometry_request'][name+'_path']).resolve())
    r=run(config,args.output);print(json.dumps({'status':r['status'],'world_sha256':r['world']['sha256']}))


if __name__=='__main__':main()
