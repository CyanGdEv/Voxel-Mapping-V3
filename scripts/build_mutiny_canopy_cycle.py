"""Compile a bounded source canopy review over the V24 cumulative park."""
import argparse,hashlib,json,shutil,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import amulet
from pyproj import Transformer,datadir
from shapely.geometry import Polygon
from shapely.ops import transform
from voxel_mapper.mutiny_canopy import source_canopy,provisional_pose,canopy_rows
from voxel_mapper.mutiny_bay_courtyard import mapped_courtyard
from voxel_mapper.wicker_registration import apply_candidate
from voxel_mapper.reconstruction.geometry import roof_cells
from voxel_mapper.generation_cycles import CyclePlan,atomic_json,file_hash
from voxel_mapper.generation_cycle_export import run_isolated
from voxel_mapper.reconstruction.batch import GeometryStore
from voxel_mapper.bedrock import material_block


def build(job_path):
 job_path=Path(job_path).resolve();job=json.loads(job_path.read_text());resolve=lambda name:(job_path.parent/job[name]).resolve()
 root=resolve('output')
 if root.exists():raise ValueError('Fresh canopy review output required')
 root.mkdir(parents=True)
 pins={k:file_hash(resolve(k)) for k in ('roof_pdf','osm','previous_review','terrain_raster','terrain_config')};pins['base_package']=file_hash(resolve('base_world')/'park.mcworld')
 pins['base_quality']=file_hash(resolve('base_world')/'quality-report.json');pins['job']=file_hash(job_path)
 datadir.append_data_dir(str(resolve('grid_directory')))
 raw=json.loads(resolve('osm').read_text());bng=Transformer.from_crs(4326,27700,always_xy=True)
 mapped=mapped_courtyard(raw,bng.transform);old=json.loads(resolve('previous_review').read_text())['report']['planning_profile']
 source=Polygon(old['courtyard_geometry']['coordinates'][0]);candidate,alignment=provisional_pose(source,Polygon(mapped.interiors[0]))
 canopy,source_evidence=source_canopy(resolve('roof_pdf'));placed=Polygon(apply_candidate(canopy.exterior.coords,candidate))
 if not Polygon(mapped.interiors[0]).buffer(-1).covers(placed):raise ValueError('Canopy escapes the protected inner courtyard')
 quality=json.loads((resolve('base_world')/'quality-report.json').read_text())
 if quality['voxel_size_m']!=1:raise ValueError('One metre native grid required')
 offset=quality['world']['vertical_offset_blocks'];project=Transformer.from_crs(27700,quality['crs'],always_xy=True)
 placed=transform(project.transform,placed)
 # The existing mapped central placeholder limits clearance; never remove the wing ring.
 central=next(w for w in raw['elements'] if w['type']=='way' and w['id']==106842136)
 geographic=Transformer.from_crs(4326,quality['crs'],always_xy=True)
 old_foot=Polygon([geographic.transform(p['lon'],p['lat']) for p in central['geometry']])
 base=root/'base';shutil.copytree(resolve('base_world'),base)
 world=amulet.load_level(str(base/'bedrock-world'));cache={};safe={'air','stone','stone_bricks'};blocked=set()
 def block(x,y,z):return world.get_block(x,y+offset,-z,'minecraft:overworld')
 def ground(x,z):
  if (x,z) in cache:return cache[x,z]
  # Saved courtyard floor, not a synthetic flat plane; never cut below it.
  for y in range(180,175,-1):
   b=block(x,y,z)
   if b.base_name in {'grass_block','brick_block','bricks','stone_bricks','stone','dirt'} and block(x,y-1,z).base_name in {'dirt','grass_block','stone','brick_block','bricks','stone_bricks'}:
    # The base of an old solid placeholder is recognised by its terrain bearing.
    if block(x,y-1,z).base_name=='dirt':cache[x,z]=y;return y
  cache[x,z]=None;return None
 try:
  rows,detail=canopy_rows(placed,ground)
  # Withhold a whole conflicting column, preserving direct material/extra-block fixtures.
  columns=set(roof_cells(old_foot))|{(x,z) for x,y,z in rows}
  for x,z in columns:
   floor=ground(x,z)
   if floor is None:blocked.add((x,z));continue
   if any(block(x,y,z).extra_blocks or block(x,y,z).base_name not in safe for y in range(floor+1,185)):blocked.add((x,z))
  rows={key:r for key,r in rows.items() if (key[0],key[2]) not in blocked}
  for x,z in roof_cells(old_foot):
   if (x,z) in blocked:continue
   for y in range(ground(x,z)+1,185):
    if (x,y,z) not in rows and block(x,y,z).base_name in {'stone','stone_bricks'}:
     rows[x,y,z]={'x':x,'y':y,'z':z,'material':'air','kind':'structure','feature':'mutiny/canopy-placeholder-clearance'}
  changes=0
  for (x,y,z),row in rows.items():
   old_block=block(x,y,z);changes+=old_block!=material_block(row['material'])
   row.update(baseline_block_sha256=hashlib.sha256(str(old_block).encode()).hexdigest(),review_only=True,layer='mutiny-canopy')
  if not rows or not changes:raise ValueError('No new canopy review geometry')
 finally:world.close()
 contract={'snapshot_mode':'review_draft','compiler_contract':'source-derived-area-review-v1','base_package_sha256':pins['base_package'],
  'manifest':{'crs':quality['crs'],'vertical_datum':'ODN','sources':quality['sources'],'terrain_sha256':pins['terrain_raster']},
  'source':source_evidence,'alignment':alignment,'input_sha256':pins,'production_placement_eligible':False}
 store=GeometryStore(root/'geometry.sqlite',contract)
 with store.db:
  for (x,y,z),row in rows.items():
   store.db.execute('INSERT INTO voxels VALUES(?,?,?,?,?,?,?)',(x,y,z,x//16,(-z)//16,row['material'],json.dumps(row)))
   store.db.execute('INSERT INTO evidence VALUES(?,?,?,?,?)',(x,y,z,row['feature'],json.dumps({'source':source_evidence,'review_only':True})))
  for name in sorted({r['feature'] for r in rows.values()}):
   record={'id':name,'family':'review_snapshot','source':source_evidence,'review_only':True};text=json.dumps(record,sort_keys=True)
   store.db.execute('INSERT INTO feature_records VALUES(?,?)',(name,text));store.db.execute('INSERT INTO features VALUES(?,?,?)',(name,hashlib.sha256(text.encode()).hexdigest(),json.dumps({'id':name,'family':'review_snapshot','status':'source_area_review'})))
 chunks=store.db.execute('SELECT DISTINCT cx,cz FROM voxels').fetchall();store.db.execute('PRAGMA wal_checkpoint(TRUNCATE)');store.close()
 if any(file_hash(resolve(k))!=pins[k] for k in ('roof_pdf','osm','previous_review','terrain_raster','terrain_config')) or file_hash(resolve('base_world')/'park.mcworld')!=pins['base_package']:raise ValueError('Canopy inputs changed during compilation')
 settings=json.loads(resolve('terrain_config').read_text());settings['terrain']['path']=str(resolve('terrain_raster'));atomic_json(root/'terrain-config.json',settings)
 plan=CyclePlan.create(root/'cycles.sqlite',root/'geometry.sqlite',base,chunks,sections=1,batch_chunks=150,workers=10,allow_draft=True,terrain_config=root/'terrain-config.json')
 try:result=run_isolated(plan,root/'geometry.sqlite',base,root/'output',root/'terrain-config.json',10)
 finally:plan.close()
 receipt=result['progress']['cycles'][-1]['preview'];package=root/'output'/receipt['file'];target=root/'Alton_Towers_V25_Mutiny_Canopy_Review.mcworld';shutil.copyfile(package,target)
 report={'status':'partial Mutiny canopy review','area_id':'mutiny-bay','source':source_evidence,'alignment':alignment,'geometry':placed.__geo_interface__,
  'canopy':detail,'input_sha256':pins,'withheld_columns':len(blocked),'written_cells':len(rows),'native_changes':changes,'cycle_receipt':receipt,
  'world_sha256':file_hash(target),'production_placement_eligible':False,
  'limitations':['Historical measured canopy outline at printed 1:200 scale; pose remains provisional.',
   'Roof pitch, elevation, supports and spruce materials are visual estimates, not source specifications.',
   'Only generic stone placeholder cells above saved floor are cleared. Courtyard wings and paving are retained.',
   'No accepted independent registration; no full courtyard or Mutiny Bay completion claimed.']}
 atomic_json(root/'canopy-review.json',report);return report


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--job',required=True);a=p.parse_args();print(json.dumps(build(a.job),indent=2))
