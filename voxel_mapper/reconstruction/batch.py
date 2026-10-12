"""Disk-backed atomic feature compilation with global conflicts and native chunk partitions."""
import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import math
import json
import sqlite3
import os
from pathlib import Path

from .engine import ReconstructionEngine,Context
from .model import Feature,Source
from .park_generators import park_registry

DEFAULT_MAX_FEATURES = 2_500_000

def json_lines(path):
    with Path(path).open() as stream:
        for number,line in enumerate(stream,1):
            if len(line)>8_000_000:raise ValueError('Feature JSON line exceeds 8 MB')
            if line.strip():
                try:yield Feature(**json.loads(line))
                except (TypeError,ValueError) as error:raise ValueError(f'Invalid feature record at line {number}: {error}') from error


class GeometryStore:
    def __init__(self,path,contract):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path);self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=NORMAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS features(id TEXT PRIMARY KEY,digest TEXT NOT NULL,decision TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS feature_records(id TEXT PRIMARY KEY,record TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS voxels(x INTEGER,y INTEGER,z INTEGER,cx INTEGER,cz INTEGER,material TEXT,row TEXT,PRIMARY KEY(x,y,z));
        CREATE INDEX IF NOT EXISTS tile ON voxels(cx,cz,x,y,z);
        CREATE TABLE IF NOT EXISTS evidence(x INTEGER,y INTEGER,z INTEGER,feature TEXT,record TEXT,PRIMARY KEY(x,y,z,feature));
        ''')
        identity=json.dumps(contract,sort_keys=True)
        prior=self.db.execute("SELECT value FROM metadata WHERE key='contract'").fetchone()
        if prior and prior[0]!=identity:self.db.close();raise ValueError('Changed job contract; use a fresh geometry database')
        with self.db:self.db.execute("INSERT OR IGNORE INTO metadata VALUES('contract',?)",(identity,))

    def compile(self,features,context,registry=None,*,max_features=DEFAULT_MAX_FEATURES):
        if isinstance(max_features,bool) or not isinstance(max_features,int) or max_features<1:
            raise ValueError('Feature budget must be a positive integer')
        engine=ReconstructionEngine(registry or park_registry());resumed=0
        total=self.db.execute('SELECT COUNT(*) FROM voxels').fetchone()[0]
        feature_count=self.db.execute('SELECT COUNT(*) FROM features').fetchone()[0]
        if feature_count>max_features:raise ValueError('Retained feature count exceeds job budget')
        for feature in features:
            digest=hashlib.sha256(json.dumps(feature.__dict__,sort_keys=True).encode()).hexdigest()
            previous=self.db.execute('SELECT digest FROM features WHERE id=?',(feature.id,)).fetchone()
            if previous:
                if previous[0]!=digest:raise ValueError('Changed feature during resume: '+feature.id+'; use a fresh job')
                with self.db:self.db.execute('INSERT OR IGNORE INTO feature_records VALUES(?,?)',(feature.id,json.dumps(feature.__dict__,sort_keys=True)))
                resumed+=1;continue
            if feature_count>=max_features:raise ValueError('Total feature budget exceeded; feature not committed')
            source=context.sources.get(feature.geometry_source)
            if source and source.kind in ('planning','cad') and feature.metadata.get('drawing_state') not in ('existing','as_built'):
                rows=[];decision={'id':feature.id,'family':feature.family,'status':'withheld','reason':'Existing/as-built drawing state required; proposals and unknown revisions are not current park geometry'}
            else:
                try:
                    from shapely.geometry import shape
                    geometry=shape(feature.geometry)
                    bounds=geometry.bounds
                    if len(bounds)!=4 or any(not math.isfinite(v) for v in bounds):raise ValueError('Finite bounded geometry required')
                    if geometry.geom_type in ('Polygon','MultiPolygon') and (bounds[2]-bounds[0]+2)*(bounds[3]-bounds[1]+2)>context.max_feature_voxels:
                        raise ValueError('Polygon scan extent exceeds per-feature budget; split into bounded components')
                    if geometry.geom_type=='LineString' and geometry.length>context.max_feature_voxels*.4:
                        raise ValueError('Line scan extent exceeds per-feature budget')
                    rows,report=engine.plan([feature],context);decision=report['decisions'][0]
                except (ValueError,TypeError,OverflowError) as error:
                    rows=[];decision={'id':feature.id,'family':feature.family,'status':'withheld','reason':str(error)}
            # Full-feature staging is bounded by the existing engine. No tile
            # clipping: a component crossing chunks remains atomic globally.
            with self.db:
                conflict=None;new=0
                for row in rows:
                    old=self.db.execute('SELECT material FROM voxels WHERE x=? AND y=? AND z=?',(row['x'],row['y'],row['z'])).fetchone()
                    if old and old[0]!=row['material']:conflict=(row['x'],row['y'],row['z']);break
                    new+=int(old is None)
                if conflict:
                    rows=[];decision={'id':feature.id,'family':feature.family,'status':'withheld','reason':'Global reconstruction material conflict','conflicting_cell':conflict}
                elif total+new>context.max_total_voxels:raise ValueError('Total disk geometry budget exceeded; feature transaction not committed')
                for row in rows:
                    x,y,z=row['x'],row['y'],row['z']
                    compact={k:v for k,v in row.items() if k!='evidence'}
                    self.db.execute('INSERT OR IGNORE INTO voxels VALUES(?,?,?,?,?,?,?)',(x,y,z,x//16,(-z)//16,row['material'],json.dumps(compact)))
                    for evidence in row['evidence']:
                        self.db.execute('INSERT INTO evidence VALUES(?,?,?,?,?)',(x,y,z,feature.id,json.dumps({'feature':feature.id,'geometry_source':feature.geometry_source})))
                self.db.execute('INSERT INTO feature_records VALUES(?,?)',(feature.id,json.dumps(feature.__dict__,sort_keys=True)))
                self.db.execute('INSERT INTO features VALUES(?,?,?)',(feature.id,digest,json.dumps(decision)))
                if rows:total+=new
                feature_count+=1
        report=self.report();report['resumed_features']=resumed;return report

    def report(self):
        family=Counter();status=Counter()
        for (text,) in self.db.execute('SELECT decision FROM features'):
            d=json.loads(text);family[d['family']]+=1;status[d['status']]+=1
        return {'features':sum(status.values()),'decisions':dict(status),'families':dict(family),
                'unique_voxel_cells':self.db.execute('SELECT COUNT(*) FROM voxels').fetchone()[0],
                'native_chunks':self.db.execute('SELECT COUNT(*) FROM (SELECT DISTINCT cx,cz FROM voxels)').fetchone()[0],
                'provenance_links':self.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0],
                'status':'disk_geometry_plan; native world export and verification remain separate',
                'memory_contract':'One bounded feature staged at a time; feature records normalized once, voxel/evidence links and decisions on disk'}

    def tile_rows(self,cx,cz):
        # A scoped cell retains every provenance link at that coordinate. Count
        # from the indexed canonical table without rejoining the scoped view
        # once per Python row (a substantial cost in real park payloads).
        query='''SELECT v.row,(SELECT COUNT(*) FROM main.evidence e
                 WHERE e.x=v.x AND e.y=v.y AND e.z=v.z)
                 FROM voxels v WHERE v.cx=? AND v.cz=? ORDER BY v.x,v.y,v.z'''
        for text,count in self.db.execute(query,(cx,cz)):
            row=json.loads(text)
            row['provenance_count']=count
            row['evidence_reference']={'cell':[row['x'],row['y'],row['z']],'links':'cell-provenance.jsonl','features':'feature-records.jsonl'}
            yield row

    def export_tiles(self,output):
        output=Path(output)
        if output.exists():raise ValueError('Use a fresh tile export directory')
        output.mkdir(parents=True);tiles=0
        with (output/'tiles.jsonl').open('w') as index:
            for cx,cz in self.db.execute('SELECT DISTINCT cx,cz FROM voxels ORDER BY cx,cz'):
                path=output/f'chunk_{cx}_{cz}.jsonl';digest=hashlib.sha256();count=0
                with path.open('wb') as stream:
                    for row in self.tile_rows(cx,cz):
                        data=(json.dumps(row,sort_keys=True)+'\n').encode();stream.write(data);digest.update(data);count+=1
                    stream.flush();os.fsync(stream.fileno())
                index.write(json.dumps({'native_chunk':[cx,cz],'file':path.name,'records':count,'sha256':digest.hexdigest()})+'\n');tiles+=1
        self.export_provenance(output)
        report=self.report();report['exported_tiles']=tiles
        (output/'batch-report.json').write_text(json.dumps(report,indent=2)+'\n');return report

    def export_provenance(self, output):
        output=Path(output);output.mkdir(parents=True,exist_ok=True);files=[]
        queries=[('feature-records.jsonl','SELECT record FROM feature_records ORDER BY id'),
                 ('cell-provenance.jsonl','SELECT x,y,z,feature FROM evidence ORDER BY x,y,z,feature'),
                 ('decisions.jsonl','SELECT decision FROM features ORDER BY id')]
        for name,query in queries:
            path=output/name;temporary=path.with_suffix('.partial');digest=hashlib.sha256();count=0
            with temporary.open('wb') as stream:
                for record in self.db.execute(query):
                    text=record[0] if len(record)==1 else json.dumps({'cell':list(record[:3]),'feature':record[3]})
                    data=(text+'\n').encode();stream.write(data);digest.update(data);count+=1
                stream.flush();os.fsync(stream.fileno())
            temporary.replace(path)
            temporary.unlink(missing_ok=True)
            files.append({'file':name,'sha256':digest.hexdigest(),'records':count})
        return files

    def close(self):self.db.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=['compile','tiles','native','report'])
    p.add_argument('--manifest',required=True);p.add_argument('--database',required=True);p.add_argument('--features');p.add_argument('--terrain-config');p.add_argument('--output')
    p.add_argument('--allow-estimates',action='store_true');p.add_argument('--base-world')
    a=p.parse_args();manifest=json.loads(Path(a.manifest).read_text());sources={s['id']:Source(**s) for s in manifest['sources']}
    from pyproj import CRS
    crs=CRS.from_user_input(manifest['crs'])
    if not crs.is_projected or any(abs(axis.unit_conversion_factor-1)>1e-9 for axis in crs.axis_info[:2]):raise ValueError('Projected metre CRS required')
    contract={'manifest':manifest,'allow_estimates':a.allow_estimates,'compiler_contract':'park-batch-v1'}
    if a.stage=='compile' and a.base_world:contract['base_package_sha256']=hashlib.sha256((Path(a.base_world)/'park.mcworld').read_bytes()).hexdigest()
    if a.terrain_config:contract['terrain_config_sha256']=hashlib.sha256(Path(a.terrain_config).read_bytes()).hexdigest()
    # Persist the exact contract across compile/report/export invocations.
    if a.stage!='compile':
        connection=sqlite3.connect(a.database)
        try:contract=json.loads(connection.execute("SELECT value FROM metadata WHERE key='contract'").fetchone()[0])
        finally:connection.close()
        if contract['manifest']!=manifest:raise ValueError('Manifest changed from compiled job')
    store=GeometryStore(a.database,contract)
    try:
        if a.stage=='compile':
            from ..terrain import Terrain
            from shapely.geometry import shape
            if not a.features or not a.terrain_config:p.error('compile requires --features and --terrain-config')
            config=json.loads(Path(a.terrain_config).read_text())
            if config['terrain'].get('vertical_datum')!=manifest.get('vertical_datum'):raise ValueError('Terrain datum mismatch')
            terrain=Terrain(config['terrain'],crs,{s['id']:s for s in config['sources']})
            level=None;occupied=None;cache=[None,None]
            try:
                if a.base_world:
                    import amulet
                    base=Path(a.base_world);quality=json.loads((base/'quality-report.json').read_text())
                    if CRS.from_user_input(quality['crs'])!=crs:raise ValueError('Base world CRS mismatch')
                    offset=quality['world']['vertical_offset_blocks'];level=amulet.load_level(str(base/'bedrock-world'))
                    coords=set(level.all_chunk_coords('minecraft:overworld'))
                    def occupied(x,y,z):
                        key=x//16,(-z)//16
                        if key not in coords or not -64<=y+offset<=319:raise ValueError('Feature outside retained terrain chunks/heights')
                        if cache[0]!=key:
                            level.unload();cache[:]=[key,level.get_chunk(*key,'minecraft:overworld')]
                        chunk=cache[1]
                        return chunk.block_palette[int(chunk.blocks[x%16,y+offset,(-z)%16])]
                if manifest.get('terrain_sha256')!=terrain.checksum:raise ValueError('Manifest must pin the terrain raster SHA256')
                ctx=Context(sources,terrain.sample,shape(manifest['boundary']),manifest.get('vertical_datum'),a.allow_estimates,
                            manifest.get('max_feature_voxels',100000),manifest.get('max_total_voxels',20000000),occupied)
                report=store.compile(json_lines(a.features),ctx,max_features=manifest.get('max_features',DEFAULT_MAX_FEATURES))
            finally:
                terrain.close()
                if level:level.close()
        elif a.stage=='native':
            if not a.output or not a.base_world:p.error('native requires --output and --base-world')
            from .batch_export import export_world
            ground=None;terrain=None
            if a.terrain_config:
                from ..terrain import Terrain
                config=json.loads(Path(a.terrain_config).read_text())
                terrain=Terrain(config['terrain'],crs,{s['id']:s for s in config['sources']})
                if terrain.checksum!=manifest.get('terrain_sha256'):terrain.close();raise ValueError('Native export terrain checksum mismatch')
                ground=terrain.sample
            try:report=export_world(store,a.base_world,a.output,ground)
            finally:
                if terrain:terrain.close()
        elif a.stage=='tiles':
            if not a.output:p.error('tiles requires --output')
            report=store.export_tiles(a.output)
        else:report=store.report()
        print(json.dumps(report,indent=2))
    finally:store.close()

if __name__=='__main__':main()
