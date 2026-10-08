"""Reviewed planning footprints for park-side details; no ride reconstruction."""
import argparse
import collections
import copy
import hashlib
import json
import math
import re
from pathlib import Path

from pyproj import CRS,Transformer
from shapely.geometry import Point,box,mapping,shape
from shapely.ops import transform,unary_union
from shapely.strtree import STRtree

from .buildings import reconstruct_building
from .park_paving import protected_record
from .park_paving_plans import scale_bar_regions
from .survey import activate_retained_grid
from .terrain import Terrain
from .wicker_registration import apply_candidate
from .xsector import apply_overlay


def detail_semantics(text):
    text=re.sub(r'\s+',' ',text.strip().lower())
    if re.fullmatch(r'rock(?:s|ery)?',text):return {'kind':'rockery' if text=='rockery' else 'rock','material':'stone','material_status':'printed_rock_label'}
    if text=='planter':return {'kind':'planter','material':'stone_bricks','material_status':'unspecified_planter_material_preview'}
    if re.fullmatch(r'(?:(?:stone|brick|concrete|conc|timber) )?(?:(?:retaining|ret) )?wall(?:\s+\d+(?:\.\d+)?\s*(?:m\s*)?(?:ht|high)|\s+ht\s*\d+(?:\.\d+)?)?',text):
        material='bricks' if text.startswith('brick ') else 'light_gray_concrete' if text.startswith(('concrete ','conc ')) else 'oak_planks' if text.startswith('timber ') else 'stone_bricks'
        result={'kind':'retaining_wall' if re.search(r'\bret(?:aining)?\b',text) else 'wall','material':material,'material_status':'printed_wall_material' if text.split()[0] in ('stone','brick','concrete','conc','timber') else 'unspecified_wall_material_preview'}
        height=re.search(r'(\d+(?:\.\d+)?)\s*(?:m\s*)?(?:ht|high)\b|\bht\s*(\d+(?:\.\d+)?)',text)
        if height:
            value=float(height.group(1) or height.group(2))
            if 0<value<=10:result['height_m']=value;result['height_status']='printed_annotation'
        return result
    if re.fullmatch(r'(?:(?:brick|stone|timber|steel clad|steel framed canvas) )?building',text):
        material='bricks' if text.startswith('brick ') else 'oak_planks' if text.startswith('timber ') else 'gray_concrete' if text.startswith('steel ') else 'stone_bricks'
        return {'kind':'building','material':material,'material_status':'printed_building_material' if text!='building' else 'unspecified_building_material_preview'}
    return None


def labelled_faces(polygons,labels,scale):
    """Bind bounded closed faces to exact labels; all output still needs review."""
    geometries=[shape(p['geometry']) for p in polygons];index=STRtree(geometries)
    masks=scale_bar_regions(labels);found=[];withheld=[]
    for label in labels:
        semantic=detail_semantics(label['text'])
        if semantic is None:continue
        b=label['bbox'];point=Point((b[0]+b[2])/2,(b[1]+b[3])/2);kind=semantic['kind'];choices=[]
        for i in index.query(point,predicate='within'):
            i=int(i);g=geometries[i];area=g.area*scale**2
            if any(g.boundary.intersects(mask) for mask in masks):continue
            if kind=='rock' and not .15<=area<=(25 if label['text'].strip().lower()=='rock' else 100):continue
            if kind=='rockery' and not .5<=area<=500:continue
            if kind=='planter' and not .25<=area<=100:continue
            if kind=='building' and not 6<=area<=1500:continue
            if kind in ('wall','retaining_wall') and (area>150 or 2*g.area/g.length*scale>2.5):continue
            choices.append((area,i,g))
        association='contained_native_label'
        if not choices and kind=='planter':
            # Small planter labels sit immediately beside the box. Require a
            # unique nearby face; no geometry is invented around a text point.
            near=sorted((g.distance(point)*scale,i,g) for i,g in enumerate(geometries)
                        if .25<=g.area*scale**2<=30 and not any(g.boundary.intersects(m) for m in masks))
            if near and near[0][0]<=1.5 and (len(near)==1 or near[1][0]-near[0][0]>=.5):
                _,i,g=near[0];choices=[(g.area*scale**2,i,g)];association='unique_adjacent_native_label'
        if not choices:withheld.append({'label':label['text'],'reason':'No bounded unambiguous closed footprint'});continue
        _,i,g=min(choices,key=lambda row:row[0])
        found.append({'face_index':i,'native_geometry':mapping(g),'label':label,'association':association,**semantic})
    return found,withheld


def building_material(labels,geometry):
    inside=[a for a in labels if geometry.covers(Point((a['bbox'][0]+a['bbox'][2])/2,(a['bbox'][1]+a['bbox'][3])/2))]
    words={a['text'].strip().lower() for a in inside}
    materials={'brick':'bricks','stone':'stone_bricks','timber':'oak_planks','steel clad':'gray_concrete','concrete':'light_gray_concrete'}
    bound={materials[word] for word in words if word in materials}
    # CAD text often splits a single material phrase across adjacent spans.
    steel=[a for a in inside if a['text'].strip().lower()=='steel']
    clad=[a for a in inside if a['text'].strip().lower()=='clad']
    if any(abs(a['origin'][1]-b['origin'][1])<.5 and abs(a['bbox'][2]-b['bbox'][0])<1 for a in steel for b in clad):bound.add('gray_concrete')
    return next(iter(bound)) if len(bound)==1 else None


def raster_cells(polygon):
    """One-metre raster with a bounded fallback for genuine sub-block objects."""
    x0,z0,x1,z1=polygon.bounds
    if (math.ceil(x1)-math.floor(x0))*(math.ceil(z1)-math.floor(z0))>20000:raise ValueError('Detail column budget exceeded')
    cells=[(x,z) for x in range(math.floor(x0),math.ceil(x1)) for z in range(math.floor(z0),math.ceil(z1)) if polygon.covers(Point(x+.5,z+.5))]
    if not cells and polygon.area>=.15:
        areas=[(polygon.intersection(box(x,z,x+1,z+1)).area,x,z) for x in range(math.floor(x0),math.ceil(x1)) for z in range(math.floor(z0),math.ceil(z1))]
        area,x,z=max(areas)
        if area>=min(.25,polygon.area*.5):cells=[(x,z)]
    return cells


def load_reviewed_details(cache,crs):
    payload=json.loads((Path(__file__).parent/'data/alton-path-details.json').read_text());project=Transformer.from_crs(27700,crs,always_xy=True);features=[]
    for entry in payload['features']:
        digest=entry['document_id'];path=Path(cache)/'files'/(digest+'.pdf')
        if not re.fullmatch(r'[0-9a-f]{64}',digest) or not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Reviewed detail PDF hash mismatch')
        semantic=detail_semantics(entry['label']['text'])
        if not semantic or semantic['kind']!=entry['kind']:raise ValueError('Reviewed detail semantics mismatch')
        geometry=shape(entry['native_geometry']);scale=entry['alignment']['candidate']['scale_m_per_pdf_point']
        if not geometry.is_valid or not .15<=geometry.area*scale**2<=1500:raise ValueError('Invalid reviewed detail footprint')
        if entry.get('registration_verified') or not entry.get('review_method'):raise ValueError('Details require provisional registration and explicit review')
        def convert(x,y,z=None):
            coordinates=apply_candidate(list(zip(x,y)),entry['alignment']['candidate']);return project.transform(coordinates[:,0],coordinates[:,1])
        local=transform(convert,geometry)
        if semantic['kind']=='building':
            refined=building_material(entry.get('material_labels',[]),geometry)
            if refined:semantic.update(material=refined,material_status='contained_native_building_material_label')
        features.append({'type':'Feature','id':entry['id'],'geometry':mapping(local),'properties':{**entry,**semantic,'as_built_verified':False}})
    return features,payload


def emit_detail(feature,terrain,surface=None):
    properties=feature['properties'];geometry=shape(feature['geometry']);kind=properties['kind'];cells=raster_cells(geometry);rows=[]
    report={'feature':feature['id'],'kind':kind,'document_id':properties['document_id'],'page':properties['page'],'source_url':properties['source_url'],'material_status':properties['material_status'],'registration_verified':False}
    if kind=='building':
        if surface is None:return [],{**report,'status':'withheld','reason':'No roof surface available'}
        profile,quality=reconstruct_building(geometry,1,terrain,surface,max_checks=10000)
        report['building_profile']=quality
        if profile is None:return [],{**report,'status':'withheld','reason':quality['reason']}
        for (x,z),(base,top) in profile.items():
            roof=math.floor(top)
            for y in range(math.floor(base)+1,roof+1):rows.append({'x':x,'y':y,'z':z,'material':'stone' if y==roof else properties['material']})
        report['height_status']='independently_sampled_surface_profile_unverified';report['roof_status']='2.5D_surface_profile_not_exact_architectural_roof'
    else:
        report['height_status']=properties.get('height_status','low_relief_preview_not_printed_height')
        for x,z in cells:
            value=terrain.sample(x+.5,z+.5)
            if value is None:continue
            ground=math.floor(value);height=max(1,math.ceil(properties.get('height_m',1)))
            if kind=='retaining_wall' and 'height_m' not in properties:
                adjacent=[terrain.sample(x+.5+dx,z+.5+dz) for dx,dz in ((2,0),(-2,0),(0,2),(0,-2))];valid=[a for a in adjacent if a is not None]
                height=max(1,min(6,math.ceil(max(valid+[value])-value)))
                report['height_status']='terrain_relief_estimate_not_printed_height'
            if kind=='rock':
                centre=Point(x+.5,z+.5);height=2 if geometry.boundary.distance(centre)>=.8 else 1
                material='cobblestone' if (x*17+z*31)%5==0 else 'granite' if (x*17+z*31)%7==0 else 'stone'
                for dy in range(1,height+1):rows.append({'x':x,'y':ground+dy,'z':z,'material':material})
            elif kind=='planter':
                edge=geometry.boundary.distance(Point(x+.5,z+.5))<1
                rows.append({'x':x,'y':ground+1,'z':z,'material':properties['material'] if edge else 'dirt'})
                if not edge or len(cells)==1:rows.append({'x':x,'y':ground+2,'z':z,'material':'oak_leaves'})
            else:
                for dy in range(1,height+1):rows.append({'x':x,'y':ground+dy,'z':z,'material':properties['material']})
    for row in rows:row.update(kind='structure',feature=feature['id'],source='planning-path-details',document_id=properties['document_id'],page=properties['page'],material_origin=properties['material_status'])
    return rows,{**report,'status':'candidate','candidate_blocks':len(rows)}


def generate(source,park,cache,output,grid):
    import amulet
    source,park,output=map(Path,(source,park,output));quality=json.loads((source/'quality-report.json').read_text());config=json.loads((source/'resolved-config.json').read_text());crs=CRS.from_wkt(quality['crs']);datum=copy.deepcopy(next(s for s in config['sources'] if s['id']=='ea-dtm'));datum['coordinate_transform']['grid']['file']=grid;activate_retained_grid(datum)
    project=Transformer.from_crs(4326,crs,always_xy=True);boundary=transform(project.transform,shape(config['boundary_geojson']));mapped=json.loads((park/'features-local.geojson').read_text())['features'];water=unary_union([shape(f['geometry']) for f in mapped if f['properties']['kind']=='water']);corridors=unary_union([shape(f['geometry']) for f in mapped if f['properties']['kind'] in ('road','path','steps')]);existing=unary_union([shape(f['geometry']) for f in mapped if f['properties']['kind']=='building'])
    features,review=load_reviewed_details(cache,crs);sources={s['id']:s for s in config['sources']};terrain=Terrain(config['terrain'],crs,sources);surface=Terrain(config['surface'],crs,sources);protected=set()
    with (park/'voxels.jsonl').open() as stream:
        for line in stream:
            r=json.loads(line)
            if protected_record(r):protected.add((r['x'],r['y'],r['z']))
    # Protect the retained Oblivion physical/clearance cells without replacing its layout.
    retained=quality.get('xsector_reconstruction',{})
    if retained.get('oblivion_reconstruction'):
        from .oblivion_reconstruction import emit_track
        station=next(s for s in retained['stations'] if s['name']=='Oblivion Station');ride,mask=emit_track(retained['rides']['Oblivion'],station,terrain.sample)
        if mask['phase_model']!=retained['oblivion_reconstruction']['phase_model']:raise ValueError('Retained ride protection mask mismatch')
        protected.update((r['x'],r['y'],r['z']) for r in ride)
    offset=quality['world']['vertical_offset_blocks'];level=amulet.load_level(str(source/'bedrock-world'));chunks={};rows=[];decisions=[];occupied=set()
    try:
        world_chunks=set(level.all_chunk_coords('minecraft:overworld'))
        for feature in features:
            geometry=shape(feature['geometry']);kind=feature['properties']['kind'];decision={'feature':feature['id'],'kind':kind,'status':'withheld'}
            if not boundary.covers(geometry) or geometry.intersection(water).area/geometry.area>.15:decisions.append({**decision,'reason':'Outside park or excessive water overlap'});continue
            if geometry.intersection(corridors).area/geometry.area>.2:decisions.append({**decision,'reason':'Mapped through-path or road overlap exceeds 20%'});continue
            if geometry.intersection(existing.buffer(.5)).area/geometry.area>.2:decisions.append({**decision,'reason':'Existing mapped building overlap'});continue
            candidates,detail=emit_detail(feature,terrain,surface);safe=[];blocked=collections.Counter()
            for row in candidates:
                key=(row['x'],row['y'],row['z']);x,y,z=row['x'],row['y']+offset,-row['z'];coords=(x//16,z//16)
                if key in protected or key in occupied:blocked['protected_or_duplicate_cell']+=1;continue
                if coords not in world_chunks or not -64<=y<=319:blocked['outside_existing_world']+=1;continue
                if coords not in chunks:chunks[coords]=level.get_chunk(*coords,'minecraft:overworld')
                chunk=chunks[coords];block=chunk.block_palette[int(chunk.blocks[x%16,y,z%16])]
                if block.base_name!='air':blocked['existing_solid_cell']+=1;continue
                safe.append(row)
            # Buildings and planters are atomic; do not deliver chopped shells.
            if kind in ('building','planter') and blocked:decisions.append({**detail,'status':'withheld','reason':'Footprint overlaps protected/existing world cells','blocked_cells':dict(blocked)});continue
            if not safe:decisions.append({**detail,'status':'withheld','reason':detail.get('reason','No safe unoccupied cells'),'blocked_cells':dict(blocked)});continue
            rows.extend(safe);occupied.update((r['x'],r['y'],r['z']) for r in safe);decisions.append({**detail,'status':'emitted','emitted_blocks':len(safe),'blocked_cells':dict(blocked)})
    finally:
        level.close();height_sources={'terrain':terrain.report(),'surface':surface.report()};terrain.close();surface.close()
    if not rows:raise ValueError('No reviewed path details survived world validation')
    report={'status':'provisional_reviewed_path_details','stations':[],'world_name':'Alton Towers — Paths and Planning Details','features':decisions,'emitted_features_by_kind':dict(collections.Counter(d['kind'] for d in decisions if d['status']=='emitted')),'overlay_blocks':len(rows),'protected_mask_cells':len(protected),'ride_layouts_changed':False,'review_source':review['review_scope'],'height_sources':height_sources,'limitations':['Absolute registration is provisional and inherited from the Wicker Man alignment','Historical drawings and mixed-date height rasters do not establish present-day construction','Rocks use estimated one/two-block relief; planter height and unspecified materials are visual estimates','Retaining wall relief without a printed height uses bounded terrain estimates','Building roof surfaces are 2.5D height profiles, not architectural roof geometry','No existing solid cells or paving ground cells are replaced']}
    apply_overlay(source,output,rows,report,report_key='park_details',report_filename='park-details-report.json');(output/'details-overlay.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows));(output/'park-details.geojson').write_text(json.dumps({'type':'FeatureCollection','coordinate_frame':'local x east/z north, metres','features':features}));print(json.dumps({k:report[k] for k in ('emitted_features_by_kind','overlay_blocks','world_verification')},indent=2));return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source-output','park-output','planning-cache','output','datum-grid'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args();generate(args.source_output,args.park_output,args.planning_cache,args.output,args.datum_grid)

if __name__=='__main__':main()
