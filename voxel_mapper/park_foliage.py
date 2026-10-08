"""Mapped vegetation plus terrain/DSM-supported canopy reconstruction on a retained world.

Tree centres inferred inside woodland, crown widths, branching and unspecified
species remain estimates. DSM is a surface model, not a vegetation classifier.
"""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import amulet
import numpy as np
import shapely
from pyproj import CRS,Transformer
from shapely.geometry import Point,Polygon,LineString,shape,mapping
from shapely.ops import transform,unary_union
from .foliage import tree_cells,shrub_cells,stable_seed
from .terrain import Terrain
from .survey import activate_retained_grid
from .xsector import apply_overlay


def canopy_height(ground,surface,x,z,radius=2):
    values=[]
    for dx,dz in ((0,0),(-radius,0),(radius,0),(0,-radius),(0,radius),(-radius,-radius),(-radius,radius),(radius,-radius),(radius,radius)):
        a,b=ground.sample(x+dx,z+dz),surface.sample(x+dx,z+dz)
        if a is not None and b is not None and 0<=b-a<=45:values.append(b-a)
    return float(np.percentile(values,80)) if len(values)>=5 else None


def mapped_geometry(element,project):
    coords=element.get('geometry',[])
    if len(coords)<2:return None
    points=[project(p['lon'],p['lat']) for p in coords]
    if points[0]==points[-1] and len(points)>=4:
        polygon=Polygon(points)
        return polygon if polygon.is_valid else None
    return LineString(points)


def reconstruct(source,raw_path,nodes_path,surface_path,boundary_path,output,grid=None,
                clearance_path=None,hints_path=None,max_trees=2600,max_cells=3_000_000,cloud_path=None,cloud_metadata_path=None):
    source,output=Path(source),Path(output)
    q=json.loads((source/'quality-report.json').read_text());config=json.loads((source/'resolved-config.json').read_text());sources={s['id']:s for s in config['sources']}
    if grid:
        for s in sources.values():
            if s.get('coordinate_transform',{}).get('grid'):
                s['coordinate_transform']['grid']['file']=str(Path(grid).resolve());activate_retained_grid(s)
    crs=CRS.from_wkt(q['crs']);project=Transformer.from_crs(4326,crs,always_xy=True).transform
    ground=Terrain(config['terrain'],crs,sources)
    surface=Terrain({'path':str(surface_path),'source_id':config['terrain']['source_id'],'vertical_datum':config['terrain']['vertical_datum'],'units':'m'},crs,sources)
    boundary=shape(json.loads(Path(boundary_path).read_text()));shapely.prepare(boundary)
    raw=json.loads(Path(raw_path).read_text());nodes=json.loads(Path(nodes_path).read_text())
    woods=[];scrubs=[];hedges=[];hard=[];rides=[];paths=[];transport=[]
    for e in raw['elements']:
        t=e.get('tags',{});geom=mapped_geometry(e,project)
        if geom is None:continue
        geom=geom.intersection(boundary)
        if geom.is_empty:continue
        item={'id':f"osm/{e['type']}/{e['id']}",'tags':t,'geometry':geom}
        if (t.get('natural')=='wood' or t.get('landuse')=='forest') and geom.geom_type in ('Polygon','MultiPolygon'):woods.append(item)
        if (t.get('natural')=='scrub' or t.get('landuse')=='flowerbed') and geom.geom_type in ('Polygon','MultiPolygon'):scrubs.append(item)
        if t.get('barrier')=='hedge':hedges.append(item)
        if t.get('building') not in (None,'no') and geom.geom_type in ('Polygon','MultiPolygon'):hard.append(geom.buffer(1.5))
        if t.get('attraction') and geom.geom_type in ('Polygon','MultiPolygon'):rides.append(geom)
        if t.get('highway'):
            try:width=float(t.get('width',2))
            except ValueError:width=2
            paths.append(geom.buffer(width/2+1) if geom.geom_type in ('LineString','MultiLineString') else geom.buffer(1))
        if t.get('aerialway') or t.get('railway')=='monorail' or t.get('roller_coaster')=='track':transport.append(geom.buffer(3))
    woodland=unary_union([w['geometry'] for w in woods]);hard=unary_union(hard+transport);ride_areas=unary_union(rides);path_areas=unary_union(paths)
    for geom in (woodland,hard,ride_areas,path_areas):shapely.prepare(geom)
    hints=json.loads(Path(hints_path).read_text()) if hints_path else []
    cloud_candidates=[];cloud_report=None;vegetation_xy=set();cloud_bounds=None
    if cloud_path:
        import laspy
        from .point_cloud import is_bng
        if not cloud_metadata_path:raise ValueError('Vegetation cloud requires source/datum metadata')
        meta=json.loads(Path(cloud_metadata_path).read_text())
        checksum=hashlib.sha256(Path(cloud_path).read_bytes()).hexdigest()
        if meta.get('vertical_datum')!=config['terrain']['vertical_datum'] or meta.get('sha256')!=checksum:
            raise ValueError('Vegetation cloud datum or checksum mismatch')
        with laspy.open(cloud_path) as reader:
            if reader.header.point_count>15_000_000:raise ValueError('Vegetation cloud point budget exceeded')
        cloud=laspy.read(cloud_path)
        if not is_bng(cloud.header.parse_crs()):raise ValueError('Vegetation cloud requires explicit EPSG:27700')
        if len(cloud.points)>15_000_000:raise ValueError('Vegetation cloud point budget exceeded')
        cp=Transformer.from_crs(27700,crs,always_xy=True)
        px,pz=cp.transform(np.asarray(cloud.x),np.asarray(cloud.y));py=np.asarray(cloud.z);classification=np.asarray(cloud.classification)
        cloud_bounds=(float(px.min()),float(pz.min()),float(px.max()),float(pz.max()))
        usable=(~np.asarray(cloud.withheld,dtype=bool))&(~np.asarray(cloud.synthetic,dtype=bool))
        mask=np.isin(classification,[3,4,5])&usable;vegetation_xy={(math.floor(x),math.floor(z)) for x,z in zip(px[mask],pz[mask])}
        clusters=collections.defaultdict(list)
        high=(classification==5)&usable
        for x,y,z in zip(px[high],py[high],pz[high]):clusters[math.floor(x/8),math.floor(z/8)].append((x,y,z))
        for (gx,gz),points in sorted(clusters.items()):
            if len(points)<15:continue
            x,z=float(np.median([p[0] for p in points])),float(np.median([p[2] for p in points]));base=ground.sample(x,z)
            if base is None or not boundary.covers(Point(x,z)):continue
            h=float(np.percentile([p[1] for p in points],90))-base
            if not 5<=h<=40:continue
            cloud_candidates.append({'id':f'classified-vegetation/{gx}/{gz}','x':math.floor(x),'z':math.floor(z),'height':h,'position_method':'estimated_centre_of_classified_high_vegetation_cluster','height_method':'classified_vegetation_90th_percentile_minus_DTM','tags':{},'classified':True})
        cloud_report={'sha256':checksum,'source_url':meta.get('source_url'),'survey':meta.get('survey'),'vertical_datum':meta['vertical_datum'],'classified_vegetation_points':int(mask.sum()),'high_vegetation_clusters':len(cloud_candidates),'local_bounds':cloud_bounds,'classes_used':[3,4,5],'limitation':'Classifications can contain errors; clustered canopy centres are not surveyed stem locations.'}
        cloud_candidates.sort(key=lambda c:stable_seed(c['id']))
    clearance={tuple(c) for c in json.loads(Path(clearance_path).read_text())} if clearance_path else set()
    world=amulet.load_level(str(source/'bedrock-world'));chunks=set(world.all_chunk_coords('minecraft:overworld'));cache={};offset=q['world']['vertical_offset_blocks']
    rows={};decisions=[];accepted=[];centres=collections.defaultdict(list);skip=collections.Counter();horizontal={};vegetation={'leaves','plant','azalea','flowering_azalea'}
    def old(x,y,z):
        key=x//16,(-z)//16
        if key not in chunks or not -64<=y+offset<320:return None
        if key not in cache:cache[key]=world.get_chunk(*key,'minecraft:overworld')
        c=cache[key];return c.block_palette[int(c.blocks[x%16,y+offset,(-z)%16])]
    def masks(x,z):
        key=x,z
        if key not in horizontal:
            p=Point(x+.5,z+.5);horizontal[key]=(boundary.covers(p),hard.covers(p),path_areas.covers(p),ground.sample(p.x,p.y))
        return horizontal[key]
    def real_ground(x,z):
        value=ground.sample(x+.5,z+.5)
        if value is None:return None
        for y in range(math.floor(value)+2,math.floor(value)-3,-1):
            b=old(x,y,z);above=old(x,y+1,z)
            if b and above and b.base_name in ('grass_block','dirt') and above.base_name in ('air',*vegetation,'log'):return y
        return None
    def crowded(x,z,radius):
        bucket=x//12,z//12
        for dx in range(-2,3):
            for dz in range(-2,3):
                if any(math.hypot(x-a,z-b)<max(4,(radius+r)*.8) for a,b,r in centres[bucket[0]+dx,bucket[1]+dz]):return True
        return False
    def permitted(k,material,owned=()):
        x,y,z=k;inside,blocked,onpath,g=masks(x,z)
        if not inside or blocked or k in clearance or (onpath and g is not None and y<=math.floor(g)+4):return False
        block=old(x,y,z)
        return block is not None and (block.base_name in ('air',*vegetation) or k in owned)
    def write(k,material,id,method):
        rows[k]={'x':k[0],'y':k[1],'z':k[2],'kind':'structure','material':material,'feature':id,'source':'osm+ea-dtm-dsm','geometry_method':method,'shape_status':'estimated_fence_and_noise_foliage'}
        if len(rows)>max_cells:raise ValueError('Foliage voxel budget exceeded')
    def profile(tags,x,z,seed):
        species=(tags.get('species','')+' '+tags.get('genus','')).lower()
        hint=min(hints,key=lambda h:(h['x']-x)**2+(h['z']-z)**2) if hints else None
        hint=hint if hint and math.hypot(hint['x']-x,hint['z']-z)<=7 else None
        hint_species=hint['species'] if hint else ''
        if 'araucaria' in species:return 'monkey_puzzle','spruce','spruce','mapped_araucaria; voxel silhouette proxy'
        if 'pinus' in species:return 'pine','oak','spruce','mapped_pinus; voxel silhouette proxy'
        if tags.get('leaf_type')=='needleleaved':return 'conifer','spruce','spruce','mapped_needleleaved; species unspecified'
        if hint_species in ('yew','cypress','fir','larch'):
            return ('columnar' if hint_species in ('yew','cypress') else 'conifer'),'spruce','spruce','nearby_provisional_planning_annotation; individual identity unverified'
        if hint_species=='willow':return 'weeping','oak','oak','nearby_provisional_planning_annotation; individual identity unverified'
        if 'quercus' in species:return 'broadleaf','oak','oak','mapped_quercus; voxel silhouette proxy'
        # Leaf-block colours approximate foliage; these variants do not assert species.
        leaf=('oak','oak','dark_oak','birch')[seed%4]
        return ('airy' if seed%5==0 else 'broadleaf'),'oak',leaf,'unspecified_broadleaf_visual_proxy'
    candidates=[]
    try:
        # Retain the centres of earlier planning-symbol previews when rebuilding
        # their small, uniform silhouettes. Never classify arbitrary architecture
        # as a tree: roots, vertical wood and neighbouring leaf blocks are needed.
        existing=[]
        for cx,cz in sorted(chunks):
            ch=world.get_chunk(cx,cz,'minecraft:overworld');logs=np.array([b.base_name=='log' and str(b.properties.get('material','')).strip('"') in ('oak','spruce','birch','dark_oak') for b in ch.block_palette])
            if not logs.any():continue
            for sy in ch.blocks.sub_chunks:
                coords=np.argwhere(logs[ch.blocks.get_sub_chunk(sy)])
                for xx,yy,zz in coords:
                    x,y,z=cx*16+int(xx),sy*16+int(yy)-offset,-(cz*16+int(zz))
                    below=old(x,y-1,z)
                    if not below or below.base_name not in ('grass_block','dirt') or not boundary.covers(Point(x+.5,z+.5)):continue
                    above=old(x,y+1,z)
                    if not above or above.base_name!='log':continue
                    leaf=any((b:=old(x+dx,y+dy,z+dz)) and b.base_name=='leaves' for dx,dz in ((-2,0),(2,0),(0,-2),(0,2)) for dy in (2,3,4))
                    if leaf:existing.append((x,y-1,z))
        for x,base,z in existing:
            h=canopy_height(ground,surface,x+.5,z+.5)
            candidates.append({'id':f'retained-planning-tree/{x}/{z}','x':x,'z':z,'height':max(6,min(28,h)) if h and h>=3 else 7,'position_method':'retained_existing_tree_preview_centre','tags':{},'existing':True,'height_method':'DSM_minus_DTM_envelope' if h and h>=3 else 'estimated_young_tree'})
        for n in nodes:
            x,z=project(float(n['lon']),float(n['lat']))
            if not boundary.covers(Point(x,z)):continue
            h=canopy_height(ground,surface,x,z)
            declared=n.get('tags',{}).get('height')
            try:declared=float(str(declared).removesuffix(' m')) if declared else None
            except ValueError:declared=None
            height=declared if declared and 3<=declared<=40 else max(6,min(35,h)) if h and h>=3 else 8
            candidates.append({'id':'osm/node/'+n['id'],'x':math.floor(x),'z':math.floor(z),'height':height,'position_method':'mapped_tree_node','tags':n.get('tags',{}),'height_method':'declared_OSM_height' if declared else 'DSM_minus_DTM_envelope' if h and h>=3 else 'estimated_mapped_tree_height'})
        candidates.extend(cloud_candidates)
        forest=[]
        for item in woods:
            geom=item['geometry'];a,b,c,d=geom.bounds
            for gx in range(math.floor(a/8)*8,math.ceil(c),8):
                for gz in range(math.floor(b/8)*8,math.ceil(d),8):
                    seed=stable_seed(f"{item['id']}/{gx}/{gz}");x,z=gx+1+seed%6,gz+1+(seed//7)%6
                    if not geom.covers(Point(x+.5,z+.5)):continue
                    h=canopy_height(ground,surface,x+.5,z+.5)
                    if h is None or h<5:continue
                    forest.append({'id':f"{item['id']}/canopy/{gx}/{gz}",'x':x,'z':z,'height':min(35,h),'position_method':'estimated_centre_in_mapped_woodland_with_DSM_canopy','tags':item['tags'],'height_method':'DSM_minus_DTM_envelope','woodland':geom})
        forest.sort(key=lambda c:(-c['height'],c['id']));candidates.extend(forest)
        print(json.dumps({'phase':'vegetation_candidates','retained_tree_centres':len(existing),'candidates':len(candidates),'classified_vegetation':cloud_report}),flush=True)
        for c in candidates:
            x,z=c['x'],c['z'];seed=stable_seed(c['id']);base=real_ground(x,z);h=max(3,round(c['height']));r=max(2,min(6.5,h*.25))
            if base is None:skip['no_unpaved_root_ground']+=1;continue
            inside,blocked,onpath,g=masks(x,z)
            if blocked or onpath or (not c.get('existing') and not c.get('classified') and ride_areas.covers(Point(x+.5,z+.5))):skip['root_in_path_structure_or_ride_extent']+=1;continue
            if crowded(x,z,r):skip['canopy_spacing']+=1;continue
            if len(accepted)>=max_trees:skip['tree_budget']+=1;continue
            prof,wood,leaf,species_status=profile(c['tags'],x,z,seed)
            if prof=='columnar':r=max(2,r*.65)
            cells=tree_cells(x,base,z,h,r,prof,seed,wood,leaf);owned=set()
            if c.get('existing'):
                for xx in range(x-4,x+5):
                    for zz in range(z-4,z+5):
                        for yy in range(base+1,base+11):
                            ob=old(xx,yy,zz)
                            if ob and ob.base_name in ('leaves','log') and (ob.base_name=='leaves' or (xx,zz)==(x,z)):owned.add((xx,yy,zz))
            woody={k for k,m in cells.items() if m.endswith('_fence')}
            if any(not permitted(k,cells[k],owned) for k in woody):skip['branch_collision_or_clearance']+=1;continue
            leaves={k:m for k,m in cells.items() if '_leaves' in m and permitted(k,m,owned)}
            if len(leaves)<(12 if h<=10 else 30) or len(leaves)<sum('_leaves' in m for m in cells.values())*.65:skip['canopy_clipped_by_structure_or_boundary']+=1;continue
            # Forest crowns follow observed canopy support, rather than filling
            # every mapped woodland clearing with an invented full canopy.
            if c.get('woodland') is not None:
                supported={k:m for k,m in leaves.items() if c['woodland'].covers(Point(k[0]+.5,k[2]+.5)) and ((v:=surface.sample(k[0]+.5,k[2]+.5)) is not None and k[1]<=math.ceil(v)+2)}
                if len(supported)<len(leaves)*.6:skip['insufficient_canopy_envelope']+=1;continue
                leaves=supported
            if cloud_bounds and cloud_bounds[0]<=x<=cloud_bounds[2] and cloud_bounds[1]<=z<=cloud_bounds[3]:
                supported={k:m for k,m in leaves.items() if any((k[0]+dx,k[2]+dz) in vegetation_xy for dx,dz in ((0,0),(-1,0),(1,0),(0,-1),(0,1),(-2,0),(2,0),(0,-2),(0,2)))}
                if len(supported)<len(leaves)*.6:skip['insufficient_classified_vegetation_support']+=1;continue
                leaves=supported
            for k in owned:
                # Old preview leaves may overlap an already composed neighbour.
                # Cleanup must never erase that neighbour's new branches/crown.
                if k not in rows and permitted(k,'air',owned):write(k,'air',c['id'],'replace_retained_tree_preview')
            for k in woody:write(k,cells[k],c['id'],'connected_estimated_fence_tree_skeleton')
            for k,m in leaves.items():
                if k not in rows or not rows[k]['material'].endswith('_fence'):write(k,m,c['id'],'random_mixed_leaves_on_four_sides_of_branches')
            centres[x//12,z//12].append((x,z,r));entry={k:v for k,v in c.items() if k not in ('woodland','tags')};entry.update(base_odn_m=base,height_m=h,crown_radius_m=r,profile=prof,wood_palette=wood,leaves_palette=leaf,species_status=species_status,voxel_cells=len(woody)+len(leaves));accepted.append(entry)
        # Low shrubs belong to mapped scrub/flowerbeds or planning-supported,
        # low-canopy woodland patches. Planting density remains a visual estimate.
        shrubs=0;plants=0
        for item in [*scrubs,*woods]:
            geom=item['geometry'];a,b,c,d=geom.bounds
            for gx in range(math.floor(a/6)*6,math.ceil(c),6):
                for gz in range(math.floor(b/6)*6,math.ceil(d),6):
                    seed=stable_seed(f"shrub/{item['id']}/{gx}/{gz}");x,z=gx+seed%5,gz+(seed//11)%5
                    if not geom.covers(Point(x+.5,z+.5)):continue
                    base=real_ground(x,z)
                    if base is None:continue
                    inside,blocked,onpath,g=masks(x,z)
                    if blocked or onpath or ride_areas.covers(Point(x+.5,z+.5)):continue
                    h=canopy_height(ground,surface,x+.5,z+.5,1)
                    low=h is not None and .7<=h<=4.5
                    scrub=item in scrubs
                    if low or (scrub and seed%3==0):
                        radius=1.5+seed%3*.5;height=max(1,min(4,round(h or 2)));id=f"{item['id']}/shrub/{gx}/{gz}";flowering=any(a['species']=='rhododendrons' and math.hypot(a['x']-x,a['z']-z)<15 for a in hints)
                        cells=shrub_cells(x,base,z,radius,height,seed,flowering);valid={k:m for k,m in cells.items() if permitted(k,m) and k not in rows}
                        if len(valid)>=len(cells)*.7:
                            for k,m in valid.items():write(k,m,id,'mapped_low_vegetation_organic_shrub_proxy')
                            shrubs+=1
                    elif woodland.covers(Point(x,z)) and seed%4==0:
                        k=x,base+1,z
                        if permitted(k,'fern') and k not in rows:write(k,'fern' if seed%3 else 'short_grass',item['id']+'/groundcover','sparse_estimated_woodland_groundcover');plants+=1
        hedge_cells=0
        for item in hedges:
            geom=item['geometry'].buffer(.65);a,b,c,d=geom.bounds
            for x in range(math.floor(a),math.ceil(c)):
                for z in range(math.floor(b),math.ceil(d)):
                    if not geom.covers(Point(x+.5,z+.5)):continue
                    base=real_ground(x,z)
                    if base is None:continue
                    for dy in (1,2):
                        k=x,base+dy,z
                        if permitted(k,'dark_oak_leaves') and k not in rows:write(k,'dark_oak_leaves',item['id'],'mapped_hedge_estimated_two_metre_height');hedge_cells+=1
    finally:world.close();ground.close();surface.close()
    report={'stations':[],'world_name':'Alton Towers — Procedural branch foliage V13','trees':accepted,'tree_count':len(accepted),'mapped_tree_nodes_in_boundary':sum(c['position_method']=='mapped_tree_node' for c in candidates),'woodland_polygons':len(woods),'woodland_area_m2':woodland.area,'shrub_clusters':shrubs,'groundcover_plants':plants,'hedge_cells':hedge_cells,'withheld_candidates':dict(skip),'overlay_records':len(rows),'sources':{'raw_osm_sha256':hashlib.sha256(Path(raw_path).read_bytes()).hexdigest(),'terrain_sha256':ground.checksum,'surface_sha256':surface.checksum,'planning_hints':len(hints),'classified_vegetation':cloud_report},'limitations':['DSM-minus-DTM is a canopy envelope proxy; DSM may include other objects. Mapped vegetation masks and structure exclusions reduce this ambiguity.','Canopy centres inferred within woodland, widths, branches, understorey density and unspecified species are visual estimates.','Mapped named species use Minecraft block/shape proxies; nearby planning species labels do not establish individual tree identity.','Composite survey dates vary; foliage is a summer visual reconstruction, not a complete current arboricultural survey.']}
    apply_overlay(source,output,list(rows.values()),report,report_key='park_foliage',report_filename='park-foliage-report.json')
    (output/'foliage-overlay.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows.values()))
    print(json.dumps({k:v for k,v in report.items() if k not in ('trees','stations')}));return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','osm','tree_nodes','surface','boundary','output'):p.add_argument('--'+name.replace('_','-'),required=True)
    for name in ('datum_grid','clearance','planning_hints','vegetation_cloud','vegetation_cloud_report'):p.add_argument('--'+name.replace('_','-'))
    p.add_argument('--max-trees',type=int,default=2600);a=p.parse_args()
    reconstruct(a.source,a.osm,a.tree_nodes,a.surface,a.boundary,a.output,a.datum_grid,a.clearance,a.planning_hints,a.max_trees,cloud_path=a.vegetation_cloud,cloud_metadata_path=a.vegetation_cloud_report)
if __name__=='__main__':main()
