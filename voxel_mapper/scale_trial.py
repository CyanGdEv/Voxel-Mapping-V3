"""Real-input, bounded scale trials; dense terrain is streamed as native chunks."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time

import numpy as np
import rasterio
from rasterio.windows import from_bounds
from shapely.geometry import Point,box,mapping,shape
from shapely.ops import transform

from .bedrock import record_priority
from .buildings import reconstruct_building
from .generation_cycles import atomic_json,file_hash
from .horizontal_grid import OSTN15Transform
from .native_tile_export import export,SHAPE
from .osm_provisional_alignment import osm_collection
from .transport import TRANSPORT_KINDS,transport_profile

VERSION='real-area-scale-trial-v1'


def _pin(descriptor,directory):
    if (not isinstance(descriptor,dict) or not isinstance(descriptor.get('file'),str)
            or not isinstance(descriptor.get('sha256'),str) or len(descriptor['sha256'])!=64):
        raise ValueError('Pinned scale-trial input required')
    path=(directory/descriptor['file']).resolve()
    if file_hash(path)!=descriptor['sha256']:raise ValueError('Scale-trial input checksum mismatch: '+path.name)
    return path


class RasterWindow:
    def __init__(self,path,bounds,source):
        self.config={'source_id':source}
        with rasterio.open(path) as dataset:
            if dataset.crs is None or dataset.crs.to_epsg()!=27700 or dataset.res!=(1,1) or dataset.count!=1:
                raise ValueError('Scale trial requires a native one-metre BNG raster')
            if not box(*dataset.bounds).covers(box(*bounds)):raise ValueError('Raster does not cover the full scale-trial area')
            window=from_bounds(*bounds,dataset.transform).round_offsets().round_lengths()
            self.values=dataset.read(1,window=window,masked=True)
            self.inverse=~dataset.window_transform(window)
            self.bounds=bounds
    def sample(self,x,z):
        col,row=self.inverse*(x,z);col,row=math.floor(col),math.floor(row)
        if not 0<=row<self.values.shape[0] or not 0<=col<self.values.shape[1]:return None
        value=self.values[row,col]
        return None if np.ma.is_masked(value) or not np.isfinite(value) else float(value)


def load_job(path):
    path=Path(path).resolve();job=json.loads(path.read_text())
    required={'version','name','area','anchor_bng_m','stages','terrain','surface','osm','horizontal_grid','budgets','sources'}
    if set(job)!=required or job['version']!=VERSION or not isinstance(job['name'],str):raise ValueError('Explicit scale-trial job required')
    stages=job['stages'];anchor=job['anchor_bng_m']
    if (not isinstance(stages,list) or not 1<=len(stages)<=3 or stages!=sorted(set(stages))
            or any(type(n) is not int or not 2<=n<=100 or n%2 for n in stages)
            or not isinstance(anchor,list) or len(anchor)!=2
            or any(type(n) is not int or n%16 for n in anchor)):
        raise ValueError('At most three increasing even chunk sizes through 100, and a chunk-aligned BNG anchor, required')
    budget=job['budgets']
    if (set(budget)!={'max_feature_columns','max_overlay_voxels','max_native_blocks'}
            or any(type(v) is not int or v<1 for v in budget.values())
            or budget['max_feature_columns']>100000 or budget['max_overlay_voxels']>2000000 or budget['max_native_blocks']>200000000):
        raise ValueError('Bounded scale-trial geometry budgets required')
    paths={key:_pin(job[key],path.parent) for key in ('terrain','surface','osm','horizontal_grid')}
    operation={'method':'ostn15-bng-v1','path':str(paths['horizontal_grid']),'sha256':job['horizontal_grid']['sha256']}
    projector=OSTN15Transform(4326,27700,operation)
    identity={'job_sha256':file_hash(path),'inputs':{k:job[k]['sha256'] for k in paths},
              'renderer_sha256':file_hash(Path(__file__)),'native_exporter_sha256':file_hash(Path(__file__).with_name('native_tile_export.py'))}
    return job,paths,projector,identity


def prepare(job_path,output):
    start=time.perf_counter();job,paths,projector,identity=load_job(job_path)
    output=Path(output);prepared=output/'prepared';prepared.mkdir(parents=True,exist_ok=True)
    contract_path=prepared/'contract.json'
    if contract_path.exists():
        saved=json.loads(contract_path.read_text())
        if saved['identity']!=identity:raise ValueError('Changed scale-trial source/renderer; use a fresh output')
        for name,digest in saved['artifacts'].items():
            if file_hash(prepared/name)!=digest:raise ValueError('Prepared scale-trial artifact changed: '+name)
        return job,identity,json.loads((prepared/'compile-report.json').read_text())
    if (prepared/'overlays.sqlite').exists():raise ValueError('Interrupted geometry preparation; use a fresh output')
    width=max(job['stages'])*16;e,n=job['anchor_bng_m'];half=width//2
    bounds=[e-half,n-half,e+half,n+half];domain=box(*bounds)
    ground=RasterWindow(paths['terrain'],bounds,'ea-dtm');surface=RasterWindow(paths['surface'],bounds,'ea-dsm')
    terrain=ground.values
    if np.ma.count(terrain)!=width*width or not np.isfinite(terrain).all():raise ValueError('Complete finite terrain coverage required; no nodata filling')
    heights=np.floor(terrain.data).astype(np.int16)
    offset=64-int(heights.min())
    if np.ma.max(surface.values)+offset>317:raise ValueError('Source height range exceeds the native build height')
    np.save(prepared/'heights.npy',heights)
    payload=gzip.decompress(paths['osm'].read_bytes())
    if len(payload)>32000000 or hashlib.sha256(payload).hexdigest()!=job['osm']['xml_sha256']:
        raise ValueError('Bounded pinned original OSM snapshot required')
    xml_path=prepared/'osm.xml';xml_path.write_bytes(payload)
    collection,osm_sha,skipped=osm_collection(xml_path)
    if len(collection['features'])>10000:raise ValueError('Scale-trial source feature budget exceeded')
    db=sqlite3.connect(prepared/'overlays.sqlite')
    db.executescript('CREATE TABLE voxels(cx INTEGER,cz INTEGER,x INTEGER,y INTEGER,z INTEGER,material TEXT,priority INTEGER,feature TEXT,PRIMARY KEY(x,y,z)) WITHOUT ROWID;'
                     'CREATE INDEX tile ON voxels(cx,cz);CREATE TABLE features(id TEXT PRIMARY KEY,kind TEXT,decision TEXT);')
    sql=('INSERT INTO voxels VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(x,y,z) DO UPDATE SET '
         'material=excluded.material,priority=excluded.priority,feature=excluded.feature WHERE excluded.priority>voxels.priority')
    decisions=[];local_features=[];generated=0
    try:
        for feature in collection['features']:
            props=feature['properties'];kind=props.get('kind');fid=feature['id']
            if kind is None:continue
            geometry=transform(projector.transform,shape(feature['geometry']))
            if geometry.is_empty or not geometry.is_valid or not geometry.intersects(domain):continue
            decision={'id':fid,'kind':kind,'status':'withheld','source':'osm','emitted_overlay_records':0}
            decisions.append(decision)
            local_features.append({'type':'Feature','id':fid,'geometry':mapping(geometry),'properties':props})
            cells=[];material=None
            elevated=props.get('bridge') not in (None,'no',False) or props.get('tunnel') not in (None,'no',False) or str(props.get('layer','0'))!='0'
            if elevated:decision['reason']='Absolute elevation/clearance is absent; layer is not a height'
            elif kind in TRANSPORT_KINDS|{'parking'}:
                profile=transport_profile(props,kind,geometry.geom_type in ('LineString','MultiLineString')) if kind!='parking' else {'material':'stone','width_m':None,'warnings':['Parking constituent material is a display assumption.']}
                decision['transport_profile']=profile;material=profile['material']
                if geometry.geom_type in ('LineString','MultiLineString'):geometry=geometry.buffer(profile['width_m']/2)
                geometry=geometry.intersection(domain)
                if geometry.is_empty or geometry.area<=0:
                    decision['reason']='No paving area inside the retained domain';continue
                x0,z0,x1,z1=geometry.bounds
                checks=(math.ceil(x1)-math.floor(x0))*(math.ceil(z1)-math.floor(z0))
                if checks>job['budgets']['max_feature_columns']:decision['reason']='Paving feature exceeds the bounded scan extent'
                else:
                    for x in range(math.floor(x0),math.ceil(x1)):
                        for z in range(math.floor(z0),math.ceil(z1)):
                            if geometry.covers(Point(x+.5,z+.5)):
                                y=ground.sample(x+.5,z+.5)
                                if y is None:raise ValueError('Missing terrain under mapped paving')
                                cells.append((x,math.floor(y),z))
            elif kind=='building' and geometry.geom_type in ('Polygon','MultiPolygon'):
                if not domain.covers(geometry):decision['reason']='Building extends outside the largest retained terrain window'
                else:
                    declared=props.get('height_m',props.get('height'))
                    try:declared=float(str(declared).removesuffix(' m')) if declared is not None else None
                    except ValueError:declared=None
                    if declared is not None and (not math.isfinite(declared) or declared<=0):declared=None
                    columns,profile=reconstruct_building(geometry,1,ground,surface,declared_height=declared,max_checks=job['budgets']['max_feature_columns'])
                    decision['surface_profile']=profile;material='stone_bricks'
                    if columns is None:decision['reason']=profile['reason']
                    else:
                        for (x,z),(base,top) in columns.items():
                            for y in range(math.floor(base),math.ceil(top)):cells.append((x,y,z))
            else:decision['reason']='Water depth/level or physical reconstruction is unsupported by this scale-trial input'
            if cells:
                generated+=len(cells)
                if generated>job['budgets']['max_overlay_voxels']:raise ValueError('Scale-trial overlay budget exceeded')
                priority=record_priority({'kind':kind,'material':material,'material_origin':'mapped_transport_surface' if kind in TRANSPORT_KINDS else 'source_profile'})
                rows=[]
                for x,y,z in cells:
                    nx,nz=x-e,n-1-z
                    if not -half<=nx<half or not -half<=nz<half:raise ValueError('Source overlay exceeds aligned tile bounds')
                    if not -64<=y+offset<320:raise ValueError('Source overlay exceeds native height limits')
                    rows.append((nx//16,nz//16,nx,y,nz,material,priority,fid))
                db.executemany(sql,rows)
                decision.update(status='mapped_display_geometry',emitted_overlay_records=len(cells),material=material)
            db.execute('INSERT INTO features VALUES(?,?,?)',(fid,kind,json.dumps(decision)))
        db.commit()
        materials=['air',*sorted({'stone','dirt','grass_block'}|{r[0] for r in db.execute('SELECT DISTINCT material FROM voxels')})]
        # Chunk-local artificial foundations remain sixteen blocks below the
        # lowest sampled terrain in each chunk; they are not subsurface survey.
        blocks=heights.reshape(width//16,16,width//16,16)
        minimum=blocks.min(axis=(1,3)).repeat(16,0).repeat(16,1)
        terrain_blocks=int(np.sum(heights.astype(np.int32)-minimum+17))
        overlay_count=db.execute('SELECT COUNT(*) FROM voxels').fetchone()[0]
        if terrain_blocks+overlay_count>job['budgets']['max_native_blocks']:raise ValueError('Dense native block upper bound exceeds the trial budget')
        report={'version':VERSION,'name':job['name'],'area':job['area'],'anchor_bng_m':job['anchor_bng_m'],
                'bounds_bng_m':bounds,'stages_chunks_per_side':job['stages'],'vertical_offset_blocks':offset,
                'terrain_columns':width*width,'terrain_coverage_fraction':1.0,'terrain_min_max_m':[float(terrain.min()),float(terrain.max())],
                'surface_coverage_fraction':float(surface.values.count()/surface.values.size),
                'terrain_foundation_blocks':terrain_blocks,'overlay_cells':overlay_count,'materials':materials,
                'feature_decisions':dict(Counter(d['status'] for d in decisions)),
                'emitted_features_by_kind':dict(Counter(d['kind'] for d in decisions if d['emitted_overlay_records'])),
                'decisions':decisions,'osm_parser_skipped':skipped,'osm_xml_sha256':osm_sha,
                'horizontal_operation':projector.report(),'sources':job['sources'],
                'preparation_seconds':time.perf_counter()-start,'accepted_planning_components':0,'training_labels_generated':0,
                'limitations':['Real terrain and mapped geometry are used; this is not a full planning-derived park reconstruction.',
                    'Building profiles are solid unverified 2.5D DSM proxies within mapped footprints, not detailed meshes or current as-built verification.',
                    'Mapping and survey epochs differ. Ride tracks, mechanisms, unsupported water and unbound planning objects are not invented.',
                    'Chunk-local foundation, default path widths and unspecified materials are display assumptions.',
                    'No AI training, whole-area walking certification or Minecraft gameplay test is performed.']}
        atomic_json(prepared/'features-bng.geojson',{'type':'FeatureCollection','crs':{'type':'name','properties':{'name':'EPSG:27700'}},'features':local_features})
        atomic_json(prepared/'compile-report.json',report)
    finally:db.close()
    artifacts={name:file_hash(prepared/name) for name in ('overlays.sqlite','heights.npy','osm.xml','features-bng.geojson','compile-report.json')}
    atomic_json(contract_path,{'identity':identity,'artifacts':artifacts})
    return job,identity,report


class TileFactory:
    def __init__(self,prepared,report):
        self.heights=np.load(prepared/'heights.npy',mmap_mode='r')
        self.db=sqlite3.connect(prepared/'overlays.sqlite')
        self.report=report;self.width=self.heights.shape[0];self.half=self.width//2
        self.materials=report['materials'];self.ids={name:i for i,name in enumerate(self.materials)}
        self.ys=np.arange(-64,320)[None,:,None]
    def __call__(self,cx,cz):
        left,top=cx*16+self.half,cz*16+self.half
        if left<0 or top<0 or left+16>self.width or top+16>self.width:raise ValueError('Tile is outside retained terrain')
        ground=self.heights[top:top+16,left:left+16].T.astype(np.int32)+self.report['vertical_offset_blocks']
        bottom=int(ground.min())-16
        solid=(self.ys>=bottom)&(self.ys<=ground[:,None,:])
        array=np.where(solid,self.ids['stone'],0).astype(np.uint16)
        array[solid&(self.ys>ground[:,None,:]-3)]=self.ids['dirt']
        np.put_along_axis(array,(ground+64)[:,None,:],self.ids['grass_block'],axis=1)
        for x,y,z,material in self.db.execute('SELECT x,y,z,material FROM voxels WHERE cx=? AND cz=?',(cx,cz)):
            array[x%16,y+self.report['vertical_offset_blocks']+64,z%16]=self.ids[material]
        return array
    def close(self):self.db.close()


def run_stage(job_path,output,chunks,*,chunk_limit=None,batch_size=1024,fault=None):
    job,identity,compiled=prepare(job_path,output)
    if chunks not in job['stages']:raise ValueError('Chunk size is not in the pinned trial progression')
    factory=TileFactory(Path(output)/'prepared',compiled)
    try:
        coordinates=[(x,z) for x in range(-chunks//2,chunks//2) for z in range(-chunks//2,chunks//2)]
        # Select a clear source-ground spawn inside the smallest shared stage.
        spawn=None
        for x,z in sorted(((x,z) for x in range(-32,33) for z in range(-32,33)),key=lambda p:(p[0]**2+p[1]**2,p)):
            tile=factory(x//16,z//16);ix,iz=x%16,z%16
            y=int(factory.heights[z+factory.half,x+factory.half])+compiled['vertical_offset_blocks']
            if tile[ix,y+64,iz] and not np.any(tile[ix,y+65:y+67,iz]):spawn=[x,y+1,z];break
        if spawn is None:raise ValueError('No clear terrain-based scale-trial spawn')
        quality={'name':job['name']+' '+str(chunks)+'×'+str(chunks),'area':job['area'],
                 'chunks_per_side':chunks,'width_m':chunks*16,'area_m2':(chunks*16)**2,
                 'coordinate_frame':'Native X=easting-anchorE; native Z=anchorN-northing; source sampled at block centres.',
                 'anchor_bng_m':job['anchor_bng_m'],'crs':'EPSG:27700','voxel_size_m':1,
                 'vertical_offset_blocks':compiled['vertical_offset_blocks'],
                 'foundation':'Artificial chunk minimum terrain minus 16 blocks; not measured subsurface geology.',
                 'sources':job['sources'],'limitations':compiled['limitations']}
        return export(Path(output)/('stage-'+str(chunks)),{**identity,'chunks_per_side':chunks},coordinates,factory,
                      factory.materials,spawn,quality,chunk_limit=chunk_limit,batch_size=batch_size,fault=fault)
    finally:factory.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--chunks',type=int);parser.add_argument('--chunk-limit',type=int)
    args=parser.parse_args()
    result=run_stage(args.job,args.output,args.chunks,chunk_limit=args.chunk_limit) if args.chunks else prepare(args.job,args.output)[2]
    print(json.dumps({k:result[k] for k in ('name','status','verified_chunks','elapsed_seconds','peak_process_rss_mib') if k in result}),flush=True)


if __name__=='__main__':main()
