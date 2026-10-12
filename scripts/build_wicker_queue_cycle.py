"""Publish a new source-derived Wicker queue review over the cumulative park."""
import argparse,hashlib,json,math,shutil,sqlite3,sys,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import amulet
from pyproj import Transformer,datadir
from shapely.ops import transform
from voxel_mapper.wicker_queue import source_walkway,placement,raster_review
from voxel_mapper.generation_cycles import CyclePlan,atomic_json,file_hash
from voxel_mapper.generation_cycle_export import run_isolated
from voxel_mapper.reconstruction.batch import GeometryStore
from voxel_mapper.terrain import Terrain


def build(job_path):
    job_path=Path(job_path).resolve();job=json.loads(job_path.read_text());resolve=lambda v:(job_path.parent/v).resolve()
    root=resolve(job['output'])
    if root.exists():raise ValueError('Fresh queue review output required')
    root.mkdir(parents=True);repo=Path(__file__).resolve().parents[1]
    pins={name:file_hash(resolve(job[name])) for name in ('floor_pdf','wicker_quality','base_package','base_quality','protected_geometry','terrain_config','terrain_raster')}
    pins['job']=file_hash(job_path)
    pins['floor_scale_review']=file_hash(repo/'evidence/wicker-shop-floor-scale-review.json')
    polygon,source=source_walkway(resolve(job['floor_pdf']),json.loads((repo/'evidence/wicker-shop-floor-scale-review.json').read_text()))
    wicker_quality=json.loads(resolve(job['wicker_quality']).read_text());polygon=placement(polygon,wicker_quality['station_review'])
    quality=json.loads(resolve(job['base_quality']).read_text());offset=quality['world']['vertical_offset_blocks']
    if quality['voxel_size_m']!=1:raise ValueError('One-block-per-metre baseline required')
    datadir.append_data_dir(str(resolve(job['grid_directory'])))
    tr=Transformer.from_crs('EPSG:27700',quality['crs'],always_xy=True);polygon=transform(tr.transform,polygon)
    base=root/'base';native=base/'bedrock-world';native.mkdir(parents=True)
    with zipfile.ZipFile(resolve(job['base_package'])) as archive:
        if any(Path(n).is_absolute() or '..' in Path(n).parts for n in archive.namelist()):raise ValueError('Unsafe base package')
        archive.extractall(native)
    shutil.copyfile(resolve(job['base_package']),base/'park.mcworld');atomic_json(base/'quality-report.json',quality)
    db=sqlite3.connect(resolve(job['protected_geometry']))
    protected=set(db.execute("SELECT DISTINCT x,z FROM voxels WHERE json_extract(row,'$.kind')='building' AND json_extract(row,'$.feature') LIKE '%wicker/%'"));db.close()
    settings=json.loads(resolve(job['terrain_config']).read_text());settings['terrain']['path']=str(resolve(job['terrain_raster']))
    terrain=Terrain(settings['terrain'],quality['crs'],{s['id']:s for s in settings['sources']})
    world=amulet.load_level(str(native));coords=set(world.all_chunk_coords('minecraft:overworld'))
    allowed={'grass_block','dirt','coarse_dirt','podzol','stone','andesite','granite','diorite','gravel','gray_concrete','light_gray_concrete','terracotta','bricks','mud_bricks'}
    cache={}
    def surface(x,z):
        if (x,z) in cache:return cache[x,z]
        sampled=terrain.sample(x+.5,z+.5)
        if sampled is None:return None
        # Stay near dated terrain, but choose the actual saved native surface.
        for y in range(math.floor(sampled)+3,math.floor(sampled)-9,-1):
            block=world.get_block(x,y+offset,-z,'minecraft:overworld')
            if block.base_name in allowed:
                above=[world.get_block(x,y+offset+k,-z,'minecraft:overworld').base_name for k in (1,2)]
                if above==['air','air']:cache[x,z]=y;return y
        cache[x,z]=None;return None
    try:
        rows,audit=raster_review(polygon,surface,protected,rails=job.get('review_rails',False))
        accepted={};collision=0
        for key,row in rows.items():
            x,y,z=key
            if (x//16,(-z)//16) not in coords:raise ValueError('Queue extends beyond park chunks')
            old=world.get_block(x,y+offset,-z,'minecraft:overworld')
            if old.extra_blocks or (row['kind']=='structure' and old.base_name!='air'):collision+=1;continue
            row.update(baseline_block_sha256=hashlib.sha256(str(old).encode()).hexdigest(),review_only=True,layer='wicker-queue')
            accepted[key]=row
        if not accepted:raise ValueError('No visible source queue geometry can be placed')
    finally:world.close();terrain.close()
    contract={'snapshot_mode':'review_draft','compiler_contract':'source-derived-area-review-v1','base_package_sha256':file_hash(base/'park.mcworld'),
        'manifest':{'crs':quality['crs'],'vertical_datum':'ODN','sources':quality['sources'],'terrain_sha256':file_hash(resolve(job['terrain_raster']))},'source':source,'input_sha256':pins,'production_placement_eligible':False}
    store=GeometryStore(root/'geometry.sqlite',contract)
    with store.db:
        for (x,y,z),row in accepted.items():
            store.db.execute('INSERT INTO voxels VALUES(?,?,?,?,?,?,?)',(x,y,z,x//16,(-z)//16,row['material'],json.dumps(row)))
            store.db.execute('INSERT INTO evidence VALUES(?,?,?,?,?)',(x,y,z,row['feature'],json.dumps({'source':source,'review_only':True})))
        for name in sorted({r['feature'] for r in accepted.values()}):
            record={'id':name,'family':'review_snapshot','source':source,'review_only':True};text=json.dumps(record,sort_keys=True)
            store.db.execute('INSERT INTO feature_records VALUES(?,?)',(name,text));store.db.execute('INSERT INTO features VALUES(?,?,?)',(name,hashlib.sha256(text.encode()).hexdigest(),json.dumps({'id':name,'family':'review_snapshot','status':'source_area_review'})))
    if any(file_hash(resolve(job[name]))!=pins[name] for name in ('floor_pdf','wicker_quality','base_package','base_quality','protected_geometry','terrain_config','terrain_raster')):
        store.close();raise ValueError('Queue review inputs changed during compilation')
    chunks=store.db.execute('SELECT DISTINCT cx,cz FROM voxels').fetchall();store.db.execute('PRAGMA wal_checkpoint(TRUNCATE)');store.close()
    # Writer uses the same terrain identity as the original park bundle.
    settings['terrain']['path']=str(resolve(job['terrain_raster']));atomic_json(root/'terrain-config.json',settings)
    plan=CyclePlan.create(root/'cycles.sqlite',root/'geometry.sqlite',base,chunks,sections=1,batch_chunks=150,workers=10,allow_draft=True,terrain_config=root/'terrain-config.json')
    try:result=run_isolated(plan,root/'geometry.sqlite',base,root/'output',root/'terrain-config.json',10)
    finally:plan.close()
    receipt=result['progress']['cycles'][-1]['preview'];package=root/'output'/receipt['file']
    target=root/'Alton_Towers_V24_Wicker_Queue_Review.mcworld';shutil.copyfile(package,target)
    report={'status':'partial Wicker source-derived queue review','area_id':'wicker-man','source':source,'geometry':polygon.__geo_interface__,
        'input_sha256':pins,'raster':audit,'native_collision_cells_withheld':collision,'written_cells':len(accepted),'cycle_receipt':receipt,
        'world_sha256':file_hash(target),'base_package_sha256':contract['base_package_sha256'],'production_placement_eligible':False,
        'limitations':['Only one source queue walkway outline is reconstructed; the full queue remains incomplete.',
            'Placement inherits the provisional station drawing correspondence; no accepted independent survey checks.',
            'Rail placement/material is an optional visual estimate; proposed drawing is not as-built verification.']}
    atomic_json(root/'queue-review.json',report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--job',required=True);a=p.parse_args();print(json.dumps(build(a.job),indent=2))
