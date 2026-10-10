"""Prepare checksum-pinned draft park layers for the normal cycle workers.

This imports retained review geometry. It never grants planning registration
acceptance or silently substitutes a draft for the production compiler.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import shutil
import sqlite3
import zipfile

import numpy as np
from pyproj import Transformer, datadir
from .bedrock import ALLOWED_MATERIALS, material_block
from .generation_cycles import CyclePlan, atomic_json, file_hash
from .reconstruction.batch import GeometryStore
from .reconstruction.batch_export import section_hashes, verify_sections
from .reconstruction.local_buildings import rotate_model
from .shop_slabs import assemble
from .shop_wall_details import decorate
from .shop_foundations import level_pad
from .shop_shell import opening_columns
from .wicker_access import build_access
from .terrain import Terrain


def read_rows(path):
    path=Path(path)
    if path.suffix=='.json':
        yield from json.loads(path.read_text())
    else:
        with path.open() as stream:
            for line in stream:
                if len(line)>8_000_000:raise ValueError('Layer line budget exceeded')
                if line.strip():yield json.loads(line)


def wicker_layer(directory,shop_model,crs,ground):
    """Rotate meshes in the destination CRS before sampling, preserving doors."""
    directory=Path(directory);quality=json.loads((directory/'quality-report.json').read_text())
    tr=Transformer.from_crs(quality['crs'],crs,always_xy=True)
    shop=quality['shop_hypothesis'];origin=np.array(shop['anchor_bng_m']);anchor=np.array(tr.transform(*origin))
    # The two projected metre frames differ by a small local bearing and scale.
    north=np.array(tr.transform(*(origin+[0,100])))-anchor
    east=np.array(tr.transform(*(origin+[100,0])))-anchor
    convergence=math.degrees(math.atan2(east[1],east[0]))
    if max(abs(np.linalg.norm(v)/100-1) for v in (north,east))>.002:
        raise ValueError('CRS conversion is not locally compatible with 1:1 mesh dimensions')
    parts=[{'id':'shop','model':json.loads(Path(shop_model).read_text()),'anchor_bng_m':origin.tolist(),
            'rotation_degrees':shop['rotation_degrees'],'provisional_base_m':184}]
    for p in quality['station_review']['parts']:
        parts.append({**p,'model':json.loads((directory/(p['id']+'-model.json')).read_text())})
    rows={};apertures=set();audits=[];clear_columns={}
    for p in sorted(parts,key=lambda p:0 if p['id']=='shop' else p['model']['dimensions']['eave_m']):
        ax,az=tr.transform(*p['anchor_bng_m']);angle=p['rotation_degrees']+convergence;floor=p['provisional_base_m']
        model=rotate_model(p['model'],angle);cells,shell=assemble(model);cells,details=decorate(model,cells)
        fill,foundation=level_pad(model,cells,[ax,az],floor,ground)
        for (x,z),head in opening_columns(model['opening_base_segments'],1).items():
            apertures.update((x+round(ax),y+round(floor),z+round(az)) for y in range(head))
        for (x,y,z),material in {**fill,**cells}.items():
            point=(x+round(ax),y+round(floor),z+round(az))
            if material.endswith('_trapdoor_north'):material=material.removesuffix('_north')+'_south'
            elif material.endswith('_trapdoor_south'):material=material.removesuffix('_south')+'_north'
            rows[point]={'x':point[0],'y':point[1],'z':point[2],'material':material,'feature':'wicker/'+p['id'],'kind':'building'}
            clear_columns[point[0],point[2]]=max(clear_columns.get((point[0],point[2]),0),round(floor)+12)
        audit={'id':p['id'],'anchor_bng_m':[ax,az],'rotation_degrees':angle,'provisional_base_m':floor,
               'model_sha256':hashlib.sha256(json.dumps(p['model'],sort_keys=True).encode()).hexdigest(),
               'foundation':foundation,'shell':shell,'details':details}
        if p['id']!='shop':audit['dimensions']=p['dimensions']
        audits.append(audit)
    # Reproject the *source* access geometry via the same local rigid frame.
    station=next(p for p in quality['station_review']['parts'] if p['id']=='station')
    theta=math.radians(station['rotation_degrees'])
    m=np.array([[math.cos(theta),-math.sin(theta)],[math.sin(theta),math.cos(theta)]])
    source=station['source_outline']['geometry']['coordinates'][0][:-1]
    t=np.array(station['anchor_bng_m'])-m@np.mean(source,axis=0)
    a=math.radians(convergence);rotation=np.array([[math.cos(a),-math.sin(a)],[math.sin(a),math.cos(a)]])
    access,access_audit=build_access(rotation@m,anchor+rotation@(t-origin),
                                  [p for p in audits if p['id']!='shop'],ground,183.3,set(rows),[-5000,-5000,5000,5000])
    for point,row in access.items():rows[point]={**row,'feature':'wicker/'+row['feature']}
    for x,y,z in apertures:
        rows.pop((x,y,z),None)
        rows[x,y,z]={'x':x,'y':y,'z':z,'material':'air','feature':'wicker/apertures','kind':'structure'}
    landscape_count=0
    for r in read_rows(directory/'voxels.jsonl'):
        if not r.get('feature','').startswith('landscape/'):continue
        x,z=tr.transform(r['x']+.5,r['z']+.5);x,z=math.floor(x),math.floor(z)
        if (x,z) in clear_columns:continue
        # Ground paving follows the park raster; raised bed/rock detail retains
        # its relative height above the Wicker test terrain surface.
        surface=ground(x+.5,z+.5)
        if surface is None:raise ValueError('Wicker landscape lacks park terrain')
        y=math.floor(surface)+(1 if r['material'].endswith('leaves') else 0)
        p=x,y,z
        if p not in rows:rows[p]={**r,'x':x,'y':y,'z':z,'feature':'wicker/'+r['feature']};landscape_count+=1
    return rows,clear_columns,{'parts':audits,'access':access_audit,'paving_and_ground_cells':landscape_count,
                             'crs_conversion':{'source':quality['crs'],'target':crs,'bearing_correction_degrees':convergence,
                                               'grid':tr.description,'dimension_scale_change_not_applied':True},
                             'source_rows_sha256':file_hash(directory/'voxels.jsonl'),
                             'production_placement_eligible':False,
                             'limitations':['Horizontal placement and station floor remain provisional.',
                                            'Destination meshes are rotated before sampling; landscape raster cells are resnapped.',
                                            'Legacy solids in the bounded replacement columns are cleared up to 12 m above the base.']}


def prepare(job_path):
    import amulet
    job_path=Path(job_path).resolve();job=json.loads(job_path.read_text())
    if job.get('snapshot_mode')!='review_draft':raise ValueError('Explicit review_draft mode required')
    def resolve(value):return (job_path.parent/value).resolve()
    root=resolve(job['output'])
    if root.exists() and any(root.iterdir()):raise ValueError('Use a fresh preparation directory; resume completed bundles through the cycle runner')
    root.mkdir(parents=True,exist_ok=True)
    package=resolve(job['base_package']);quality_path=resolve(job['base_quality']);terrain_path=resolve(job['terrain_config'])
    pins={str(p):file_hash(p) for p in [job_path,package,quality_path,terrain_path]}
    quality=json.loads(quality_path.read_text());crs=quality['crs'];offset=quality['world']['vertical_offset_blocks']
    if quality['voxel_size_m']!=1:raise ValueError('1:1 park base required')
    config=json.loads(terrain_path.read_text());raster=resolve(job['terrain_raster']);config['terrain']['path']=str(raster)
    if job.get('proj_grid_directory'):datadir.append_data_dir(str(resolve(job['proj_grid_directory'])))
    pins[str(raster)]=file_hash(raster)
    terrain=Terrain(config['terrain'],crs,{s['id']:s for s in config['sources']})
    cache={}
    def ground(x,z):
        key=math.floor(x),math.floor(z)
        if key not in cache:cache[key]=terrain.sample(key[0]+.5,key[1]+.5)
        value=cache[key]
        if value is None or not math.isfinite(value):raise ValueError('Draft layer lacks terrain coverage')
        return value
    base=root/'base-world';base.mkdir(exist_ok=True);native=base/'bedrock-world';native.mkdir(exist_ok=True)
    with zipfile.ZipFile(package) as archive:
        if any(Path(n).is_absolute() or '..' in Path(n).parts for n in archive.namelist()):raise ValueError('Unsafe base archive')
        if sum(e.file_size for e in archive.infolist())>2_000_000_000:raise ValueError('Base archive size budget exceeded')
        archive.extractall(native)
    stage=sqlite3.connect(root/'staging.sqlite')
    stage.executescript('CREATE TABLE IF NOT EXISTS candidates(x INTEGER,y INTEGER,z INTEGER,cx INTEGER,cz INTEGER,row TEXT,defer INTEGER,force INTEGER,PRIMARY KEY(x,y,z)); CREATE INDEX IF NOT EXISTS chunks ON candidates(cx,cz);')
    counts=Counter()
    def insert(row,layer,defer=False,force=False):
        x,y,z=(row[k] for k in ('x','y','z'))
        if any(type(v) is not int for v in (x,y,z)):raise ValueError('Integer layer cells required')
        if row['material'] not in ALLOWED_MATERIALS:raise ValueError('Unsupported draft material')
        if not -64<=y+offset<=319:raise ValueError('Draft cell outside native height range')
        feature=layer+'/'+str(row.get('feature','unclassified'))
        compact={**row,'feature':feature,'review_only':True,'layer':layer}
        stage.execute('INSERT OR REPLACE INTO candidates VALUES(?,?,?,?,?,?,?,?)',
                      (x,y,z,x//16,(-z)//16,json.dumps(compact),int(defer),int(force)))
        counts[layer]+=1
    with stage:
        for layer in job['layers']:
            path=resolve(layer['file']);pins[str(path)]=file_hash(path)
            for row in read_rows(path):
                if row['material']=='air':continue # Superseded legacy removals are already in the base context.
                insert(row,layer['id'],layer.get('defer_above_ground',False))
    wicker=resolve(job['wicker_directory']);shop_model=resolve(job['shop_model']);pins[str(shop_model)]=file_hash(shop_model)
    rows,clear_columns,wicker_report=wicker_layer(wicker,shop_model,crs,ground)
    pins[str(wicker/'quality-report.json')]=file_hash(wicker/'quality-report.json')
    pins[str(wicker/'voxels.jsonl')]=file_hash(wicker/'voxels.jsonl')
    for path in wicker.glob('*-model.json'):pins[str(path)]=file_hash(path)
    with stage:
        # Finite replacement masks explicitly retain the existing terrain and
        # remove legacy extrusion only above it, within source building columns.
        for (x,z),head in clear_columns.items():
            for y in range(math.floor(ground(x,z))+1,head+1):
                insert({'x':x,'y':y,'z':z,'material':'air','kind':'structure','feature':'legacy-shell-clearance'},'wicker',False,True)
        for row in rows.values():insert(row,'wicker',False,True)
    world=amulet.load_level(str(native));coords=set(world.all_chunk_coords('minecraft:overworld'))
    contract={'snapshot_mode':'review_draft','compiler_contract':'draft-retained-layers-v1',
              'manifest':{'crs':crs,'vertical_datum':'ODN','sources':quality['sources']},
              'input_sha256':pins,'production_placement_eligible':False}
    store=GeometryStore(root/'geometry.sqlite',contract);features={};expected={};changed=0;removed=0;skipped=0
    try:
        for cx,cz in stage.execute('SELECT DISTINCT cx,cz FROM candidates ORDER BY cx,cz'):
            if (cx,cz) not in coords:raise ValueError('Draft geometry exceeds park chunks')
            chunk=world.get_chunk(cx,cz,'minecraft:overworld');dirty=False
            with store.db:
                for x,y,z,text,defer,force in stage.execute('SELECT x,y,z,row,defer,force FROM candidates WHERE cx=? AND cz=? ORDER BY x,y,z',(cx,cz)):
                    row=json.loads(text);old=chunk.block_palette[int(chunk.blocks[x%16,y+offset,(-z)%16])]
                    target=material_block(row['material'])
                    if old.extra_blocks:raise ValueError('Draft replacement cannot erase layered native blocks')
                    matches=old.namespaced_name==target.namespaced_name and all(old.properties.get(k)==v for k,v in target.properties.items())
                    if not force and not matches:skipped+=1;continue # Later retained revisions win.
                    if force and target.base_name=='air' and old.base_name=='air':continue
                    baseline=old
                    if defer and y>math.floor(ground(x,z)) and old.base_name!='air':
                        baseline=material_block('air');chunk.blocks[x%16,y+offset,(-z)%16]=chunk.block_palette.get_add_block(baseline)
                        dirty=True;removed+=1
                    row['baseline_block_sha256']=hashlib.sha256(str(baseline).encode()).hexdigest()
                    feature=row['feature'];features.setdefault(feature,{'id':feature,'family':'review_snapshot','source':row['layer'],'review_only':True})
                    store.db.execute('INSERT INTO voxels VALUES(?,?,?,?,?,?,?)',(x,y,z,cx,cz,row['material'],json.dumps(row)))
                    store.db.execute('INSERT INTO evidence VALUES(?,?,?,?,?)',(x,y,z,feature,json.dumps({'feature':feature,'snapshot_mode':'review_draft'})))
            if dirty:
                chunk.changed=True;world.put_chunk(chunk,'minecraft:overworld');expected[cx,cz]=section_hashes(chunk);changed+=1
                world.save()
            world.unload()
        with store.db:
            for feature,record in features.items():
                text=json.dumps(record,sort_keys=True)
                store.db.execute('INSERT INTO feature_records VALUES(?,?)',(feature,text))
                store.db.execute('INSERT INTO features VALUES(?,?,?)',(feature,hashlib.sha256(text.encode()).hexdigest(),json.dumps({'id':feature,'family':'review_snapshot','status':'draft_review'})))
        world.close();world=None
        world=amulet.load_level(str(native))
        for (cx,cz),hashes in expected.items():verify_sections(world.get_chunk(cx,cz,'minecraft:overworld'),hashes);world.unload()
        if set(world.all_chunk_coords('minecraft:overworld'))!=coords:raise ValueError('Baseline chunk coverage changed')
        world.close();world=None
        quality['world']['composed_blocks']-=removed
        quality['world']['quality']='draft_unverified'
        quality['draft_cycles']={'snapshot_mode':'review_draft','deferred_detail_cells':removed,'baseline_changed_chunks':changed,
                                  'legacy_context_preserved':True,'production_placement_eligible':False}
        if any(file_hash(path)!=digest for path,digest in pins.items()):raise ValueError('Preparation input changed during compilation')
        atomic_json(native/'voxel-quality-report.json',quality)
        (native/'levelname.txt').write_text('Alton Towers V23 — progressive draft cycles')
        with zipfile.ZipFile(base/'park.mcworld','w',zipfile.ZIP_DEFLATED) as archive:
            for p in sorted(native.rglob('*')):
                if p.is_file() and p.name!='LOCK':archive.write(p,p.relative_to(native))
        quality['world']['sha256']=file_hash(base/'park.mcworld');atomic_json(base/'quality-report.json',quality)
        contract['base_package_sha256']=quality['world']['sha256']
        with store.db:store.db.execute("UPDATE metadata SET value=? WHERE key='contract'",(json.dumps(contract,sort_keys=True),))
        geometry_report=store.report();store.db.execute('PRAGMA wal_checkpoint(TRUNCATE)');store.close();store=None
        # A bounded Wicker focus is the first section; the remaining park is
        # balanced into fourteen sections. Every chunk still has one owner.
        corners=[]
        tr=Transformer.from_crs(json.loads((wicker/'quality-report.json').read_text())['crs'],crs,always_xy=True)
        b=json.loads((wicker/'quality-report.json').read_text())['bounds_bng_m']
        for x,z in ((b[0],b[1]),(b[2],b[1]),(b[2],b[3]),(b[0],b[3])):corners.append(tr.transform(x,z))
        xmin,zmin=np.min(corners,axis=0);xmax,zmax=np.max(corners,axis=0)
        focus=[(cx,cz) for cx,cz in coords if cx*16<xmax and (cx+1)*16>xmin and -cz*16>zmin and -(cz+1)*16<zmax]
        plan=CyclePlan.create(root/'cycles.sqlite',root/'geometry.sqlite',base,sorted(coords),allow_draft=True,focus_chunks=focus)
        report={'snapshot_mode':'review_draft','production_placement_eligible':False,'input_sha256':pins,
                'staged_records':dict(counts),'superseded_layer_cells_skipped':skipped,'deferred_above_ground_cells':removed,
                'baseline_changed_chunks':changed,'geometry':geometry_report,'wicker':wicker_report,
                'plan':plan.report(),'limitations':['Retained draft geometry is replayed, not newly inferred from every park planning PDF.',
                                                   'Legacy context remains visible; only selected future foliage is deferred.',
                                                   'Planning coverage and detailed source meshes remain incomplete outside reviewed areas.']}
        plan.close();atomic_json(root/'draft-snapshot-report.json',report)
        stage.close();(root/'staging.sqlite').unlink()
        return report
    finally:
        if world is not None:world.close()
        if store is not None:store.close()
        terrain.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--job',required=True)
    args=parser.parse_args();report=prepare(args.job)
    print(json.dumps({'status':'draft_cycle_bundle_ready','chunks':report['plan']['total_chunks'],
                      'cycles':len(report['plan']['cycles']),'geometry_cells':report['geometry']['unique_voxel_cells']}))


if __name__=='__main__':main()
