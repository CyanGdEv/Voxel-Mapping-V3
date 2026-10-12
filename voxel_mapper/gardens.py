"""Reviewed garden planning geometry applied to an existing native park world.

No ride reconstruction or guessed landmark elevations. Survey registrations
remain provisional; collision withholding takes precedence over completeness.
"""
import argparse,collections,copy,hashlib,json,math
from pathlib import Path
import numpy as np
from pyproj import CRS,Transformer
from shapely.geometry import Point,LineString,shape,mapping
from shapely.ops import transform
from .reconstruction.geometry import line_cells,roof_cells
from .reconstruction.garden_surfaces import walking_block,barrier_column
from .wicker_registration import apply_candidate
from .terrain import Terrain
from .survey import activate_retained_grid
from .xsector import apply_overlay


def reconstruct(source,output,planning_cache,grid,protection_files=(),reviewed_features_path=None):
    import amulet
    source,output,planning_cache=map(Path,(source,output,planning_cache))
    if output.exists():raise ValueError('Refusing to overwrite garden output')
    feature_path=Path(reviewed_features_path) if reviewed_features_path else Path(__file__).parent/'data/alton-gardens-v16.json'
    payload=json.loads(feature_path.read_text())
    if not payload.get('features') or len(payload['features'])>10000:raise ValueError('Reviewed feature budget exceeded')
    if any(f.get('kind') not in ('path','wall','barrier') for f in payload['features']):raise ValueError('Unsupported reviewed feature family')
    config=json.loads((source/'resolved-config.json').read_text());quality=json.loads((source/'quality-report.json').read_text())
    sources={s['id']:copy.deepcopy(s) for s in config['sources']}
    datum=sources['ea-dtm'];datum['coordinate_transform']['grid']['file']=str(Path(grid).resolve());activate_retained_grid(datum)
    crs=CRS.from_wkt(quality['crs']);project=Transformer.from_crs(27700,crs,always_xy=True);ground=Terrain(config['terrain'],crs,sources)
    registrations={s['document_id']:s['alignment']['candidate'] for s in payload['sources']}
    for digest in [*registrations,*(s['document_id'] for s in payload.get('specification_sources',[]))]:
        pdf=planning_cache/(digest+'.pdf')
        if hashlib.sha256(pdf.read_bytes()).hexdigest()!=digest:raise ValueError('Source PDF checksum mismatch')
    protected=set();water_columns=set();protections=[]
    for file in protection_files:
        file=Path(file);protections.append({'path':str(file),'sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
        if file.suffix=='.jsonl':
            for line in file.open():
                r=json.loads(line);protected.add((r['x'],r['y'],r['z']))
        else:
            obj=json.loads(file.read_text())
            if isinstance(obj,list) and obj and isinstance(obj[0],dict) and 'floor' in obj[0]:water_columns.update((c['x'],c['z']) for c in obj)
            elif isinstance(obj,list):protected.update(tuple(k) for k in obj)
    tree_report=source/'park-foliage-report.json'
    if tree_report.exists():
        for t in json.loads(tree_report.read_text())['trees']:protected.add((t['x'],t['base_odn_m'],t['z']))
    level=amulet.load_level(str(source/'bedrock-world'));chunks={};offset=quality['world']['vertical_offset_blocks'];cells={};floors={};withheld=collections.Counter();stats=[]
    def native(k):
        x,y,z=k;key=(x//16,(-z)//16)
        if key not in chunks:chunks[key]=level.get_chunk(*key,'minecraft:overworld')
        ch=chunks[key];return ch.block_palette[int(ch.blocks[x%16,y+offset,(-z)%16])]
    def safe(k):
        if k in protected or (k[0],k[2]) in water_columns:return False
        b=native(k)
        return b.base_name in ('air','grass_block','dirt','stone','cobblestone','stone_bricks','slab','stairs','concrete')
    def put(k,material,feature):cells[k]={'x':k[0],'y':k[1],'z':k[2],'material':material,'feature':feature}
    def projected(feature):
        candidate=registrations[feature['document_id']]
        def convert(x,y,z=None):
            p=apply_candidate(list(zip(x,y)),candidate);return project.transform(p[:,0],p[:,1])
        return transform(convert,shape(feature['native_geometry']))
    try:
        features=sorted(payload['features'],key=lambda f:('path','wall','barrier').index(f['kind']))
        for f in features:
            g=projected(f);before=len(cells);emitted=0;blocked=0
            if f['kind']=='path':
                if f.get('force_stairs'):
                    withheld['provisional_stair_trace_requires_native_path_attachment']+=1
                    continue
                line=g;stations=np.r_[np.arange(0,line.length,1),line.length];h=[]
                for s in stations:
                    p=line.interpolate(float(s));values=[ground.sample(p.x+dx,p.y+dz) for dx,dz in [(0,0),(.5,0),(-.5,0),(0,.5),(0,-.5)]]
                    values=[v for v in values if v is not None];h.append(float(np.median(values))+1 if values else np.nan)
                if not np.all(np.isfinite(h)):withheld['missing_terrain']+=1;continue
                # Symmetric 5 m smoothing avoids alternating stair directions from
                # metre-scale DTM noise while retaining real grade changes.
                h=np.convolve(np.pad(h,(2,2),mode='edge'),np.ones(5)/5,mode='valid')
                for x,z in roof_cells(line.buffer(f['width_m']/2,cap_style=2,join_style=2)):
                    p=Point(x+.5,z+.5);s=line.project(p);top=float(np.interp(s,stations,h));a=max(0,s-1);b=min(line.length,s+1)
                    grade=(float(np.interp(b,stations,h))-float(np.interp(a,stations,h)))/max(.1,b-a)
                    p0=line.interpolate(a);p1=line.interpolate(b);y,material=walking_block(top,grade,p1.x-p0.x,p1.y-p0.y,stairs=f['force_stairs'])
                    actual=ground.sample(x+.5,z+.5)
                    if actual is None or abs((y+1)-(actual+1))>1.5:blocked+=1;withheld['path_bank_cut_over_1_5m']+=1;continue
                    edits={(x,y,z):material}
                    # Ground the surface, including half-block floor slabs; only
                    # carve a small corridor through unprotected terrain.
                    for yy in range(min(y-1,math.floor(actual)),y):edits[(x,yy,z)]='stone'
                    for yy in range(y+1,max(y+3,math.floor(actual)+2)):edits[(x,yy,z)]='air'
                    if any(not safe(k) for k in edits):blocked+=1;withheld['protected_path_column']+=1;continue
                    for k,m in edits.items():put(k,m,f['id'])
                    floors[(x,z)]=y+.5 if material.endswith('_slab') else y+1;emitted+=1
            elif f['kind']=='wall':
                for x,z in roof_cells(g):
                    actual=ground.sample(x+.5,z+.5)
                    if actual is None:continue
                    near=[ground.sample(x+.5+dx,z+.5+dz) for dx,dz in [(2,0),(-2,0),(0,2),(0,-2)]];near=[v for v in near if v is not None]
                    y=math.floor(actual);height=min(3,max(1,math.ceil(max(near+[actual])-actual)))
                    edits={(x,yy,z):f['material'] for yy in range(y,y+height+1)}
                    if any(not safe(k) or k in cells for k in edits):blocked+=1;withheld['protected_wall_column']+=1;continue
                    for k,m in edits.items():put(k,m,f['id'])
                    emitted+=1
            else:
                for (x,z),s in line_cells(g).items():
                    actual=ground.sample(x+.5,z+.5)
                    if actual is None:continue
                    top=floors.get((x,z),math.floor(actual)+1);edits=barrier_column(x,z,top,f['colour'],f['height_m'])
                    # Adjacent half-height slabs need a footing immediately below
                    # the railing rather than floating at a rounded terrain top.
                    if top!=int(top):edits[(x,math.floor(top),z)]='stone_slab_top'
                    if any(not safe(k) for k in edits):blocked+=1;withheld['protected_barrier_column']+=1;continue
                    # Never place railings through a walking corridor.
                    if (x,z) in floors:blocked+=1;withheld['barrier_intersects_path']+=1;continue
                    for k,m in edits.items():put(k,m,f['id'])
                    emitted+=1
            stats.append({'id':f['id'],'kind':f['kind'],'document_id':f['document_id'],'geometry_status':f['geometry_status'],'material_status':f['material_status'],'emitted_columns':emitted,'withheld_columns':blocked,'local_geometry':mapping(g),'width_m':f.get('width_m'),'material':f.get('material'),'colour':f.get('colour')})
    finally:level.close();ground.close()
    rows=list(cells.values());counts=collections.Counter(r['material'] for r in rows)
    report={'world_name':'Alton Towers — Gardens paths and barriers V16','stations':[], 'registration_verified':False,'registration_note':payload['registration_note'],'sources':payload['sources'],'specification_sources':payload.get('specification_sources',[]),'features':stats,'feature_counts':dict(collections.Counter(f['kind'] for f in stats)),'material_counts':dict(counts),'withheld':dict(withheld),'protection_sources':protections,'limitations':['Absolute registration remains provisional.','Path widths are reviewed estimates; paving and retaining-wall materials are stone proxies where no finish is specified.','Rail routes include retained and proposed 2013 segments; drawing gaps remain gaps.','One-metre blocks round the 1.1 m railing / 0.9 m handrail spec to a 1 m proxy; green panes are the user-authorized colour proxy.','Collisions with foliage, water, ride cells and protected air are withheld; incomplete corridors are reported.','Landmark buildings and ponds are unchanged; pond-fill and planting-removal proposals are excluded.']}
    # Open the new release at an accepted, cleared garden path column.
    chosen=next((f for f in stats if f['id']=='Conservatory south promenade'),None)
    if chosen:
        midpoint=shape(chosen['local_geometry']).interpolate(.5,normalized=True)
        sites={(r['x'],r['z']) for r in rows if r['feature']==chosen['id'] and r['material']!='air'}
        if sites:
            x,z=min(sites,key=lambda k:(k[0]+.5-midpoint.x)**2+(k[1]+.5-midpoint.y)**2)
            report['spawn_minecraft_xyz']=[x,math.ceil(floors[(x,z)])+offset,-z]
    output.parent.mkdir(parents=True,exist_ok=True)
    # Standalone overlay plus all-source feature provenance survives interrupted
    # exports and can be inspected before opening a Minecraft world.
    scratch=output.with_name(output.name+'-overlay.jsonl');scratch.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    apply_overlay(source,output,rows,report,'garden_reconstruction','garden-report.json')
    scratch.replace(output/'garden-overlay.jsonl')
    report['visit_coordinates']=[{'name':f['id'],'minecraft_xyz':[math.floor(shape(f['local_geometry']).centroid.x),math.floor(ground_height)+offset+5,-math.floor(shape(f['local_geometry']).centroid.y)]} for f in stats if f['kind']=='path' for ground_height in [np.median([r['y'] for r in rows if r['feature']==f['id'] and r['material']!='air'])] if math.isfinite(ground_height)]
    (output/'garden-report.json').write_text(json.dumps(report,indent=2));print(json.dumps({'feature_counts':report['feature_counts'],'material_counts':dict(counts),'withheld':dict(withheld),'world_verification':report['world_verification']},indent=2),flush=True)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True);p.add_argument('--output',required=True);p.add_argument('--planning-files',required=True);p.add_argument('--datum-grid',required=True);p.add_argument('--protect',action='append',default=[]);p.add_argument('--features',help='Alternate reviewed geometry/provenance bundle for another park')
    a=p.parse_args();reconstruct(a.source,a.output,a.planning_files,a.datum_grid,a.protect,a.features)

if __name__=='__main__':main()
