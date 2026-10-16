"""Resumable dense Bedrock tiles with source-bound intent and full-height readback."""
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import zipfile

from amulet.api.chunk import Chunk
from amulet.api.chunk.blocks import Blocks
from amulet.level.formats.leveldb_world import LevelDBFormat
from amulet_nbt import ByteTag,IntTag,LongTag,StringTag
import numpy as np

from .bedrock import material_block, VERSION as BEDROCK_VERSION
from .generation_cycles import atomic_json,file_hash
from .process_metrics import peak_process_rss_mib

VERSION='dense-native-tile-export-v1'
DIMENSION='minecraft:overworld'
SHAPE=(16,384,16)


def tile_hash(array):
    return hashlib.sha256(np.asarray(array,dtype='<u2').tobytes()).hexdigest()


def open_native(path):
    """Read directly through the format wrapper, without an editing history DB."""
    wrapper=LevelDBFormat(str(path));wrapper.open()
    return wrapper


def read_tile(level,cx,cz,materials):
    """Map translated native palette entries to their expected material identities."""
    chunk=(level.get_chunk(cx,cz,DIMENSION) if hasattr(level,'get_chunk')
           else level.load_chunk(cx,cz,DIMENSION))
    expected=[material_block(m) for m in materials]
    lookup=np.full(len(chunk.block_palette),-1,dtype=np.int32)
    for i,block in enumerate(chunk.block_palette):
        matches=[j for j,want in enumerate(expected) if block.namespaced_name==want.namespaced_name
                 and all(block.properties.get(k)==v for k,v in want.properties.items()) and not block.extra_blocks]
        if len(matches)==1:lookup[i]=matches[0]
    result=np.zeros(SHAPE,dtype=np.uint16)
    for section in range(-4,20):
        if section not in chunk.blocks.sub_chunks:continue
        values=lookup[chunk.blocks.get_sub_chunk(section)]
        if np.any(values<0):raise ValueError('Unexpected saved native material')
        result[:,(section+4)*16:(section+5)*16,:]=values
    level.unload()
    return result


def _chunk(cx,cz,array,materials):
    if array.shape!=SHAPE or array.dtype!=np.uint16 or np.any(array>=len(materials)):
        raise ValueError('Bounded native tile array and known material indices required')
    chunk=Chunk(cx,cz)
    for i,name in enumerate(materials):
        if chunk.block_palette.get_add_block(material_block(name))!=i:
            raise ValueError('Native palette aliases are unsupported')
    chunk.blocks=Blocks({section:array[:,(section+4)*16:(section+5)*16,:].astype(np.uint32)
                         for section in range(-4,20)
                         if np.any(array[:,(section+4)*16:(section+5)*16,:])})
    chunk.changed=True
    return chunk


def export(output,contract,coordinates,factory,materials,spawn,quality,*,chunk_limit=None,batch_size=1024,fault=None):
    """Close, reopen and check a bounded batch before committing its ready journal."""
    if (not materials or materials[0]!='air' or len(materials)>256 or len(set(materials))!=len(materials)
            or type(batch_size) is not int or not 1<=batch_size<=1024
            or (chunk_limit is not None and (type(chunk_limit) is not int or chunk_limit<1))):
        raise ValueError('Bounded native tile export settings required')
    coordinates=sorted(set(coordinates))
    if not coordinates or len(coordinates)>10_000 or any(len(c)!=2 or any(type(v) is not int or abs(v)>10000 for v in c) for c in coordinates):
        raise ValueError('Native scale trial supports at most 10,000 bounded chunks')
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    world_path=output/'bedrock-world';state_path=output/'export-state.sqlite'
    identity={**contract,'export_version':VERSION,'materials':materials,'spawn':spawn,
              'coordinates_sha256':hashlib.sha256(json.dumps(coordinates).encode()).hexdigest()}
    encoded=json.dumps(identity,sort_keys=True)
    fresh=not state_path.exists()
    if fresh and any(output.iterdir()):raise ValueError('Fresh output or resumable state required')
    state=sqlite3.connect(state_path)
    state.executescript('CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT);'
                       'CREATE TABLE IF NOT EXISTS chunks(cx INTEGER,cz INTEGER,sha TEXT,blocks INTEGER,ready INTEGER,PRIMARY KEY(cx,cz));')
    prior=state.execute("SELECT value FROM metadata WHERE key='contract'").fetchone()
    if prior and prior[0]!=encoded:state.close();raise ValueError('Changed native tile contract; use a fresh output')
    with state:state.execute("INSERT OR IGNORE INTO metadata VALUES('contract',?)",(encoded,))
    start=time.perf_counter();resumed=written=recovered=0
    wrapper=None;level=None
    try:
        if not world_path.exists():
            if state.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]:raise ValueError('Native world lost after committed chunk intent')
            wrapper=LevelDBFormat(str(world_path));wrapper.create_and_open('bedrock',BEDROCK_VERSION)
            tag=wrapper.root_tag.compound
            tag['LevelName']=StringTag(quality['name']+' — draft scale test')
            for key,value in [('GameType',1),('Difficulty',0),('SpawnX',spawn[0]),('SpawnY',spawn[1]),('SpawnZ',spawn[2])]:tag[key]=IntTag(value)
            tag['RandomSeed']=LongTag(0);tag['commandsEnabled']=ByteTag(1);tag['spawnMobs']=ByteTag(0)
            tag['doDaylightCycle']=ByteTag(0);tag['Time']=LongTag(6000)
            wrapper.save();wrapper.close();wrapper=None
        retained={(cx,cz):(sha,blocks,ready) for cx,cz,sha,blocks,ready in state.execute('SELECT * FROM chunks')}
        if not retained.keys()<=set(coordinates):raise ValueError('Unexpected retained chunk intent')
        level=open_native(world_path);present=set(level.all_chunk_coords(DIMENSION))
        if not present<=retained.keys():raise ValueError('Native chunks without a source-bound intent')
        for (cx,cz),(sha,blocks,ready) in retained.items():
            planned=factory(cx,cz)
            if tile_hash(planned)!=sha:raise ValueError('Retained tile differs from pinned source rendering')
            if (cx,cz) not in present:
                if ready:raise ValueError('Verified native chunk is missing')
                continue
            actual=read_tile(level,cx,cz,materials)
            if tile_hash(actual)!=sha:raise ValueError('Retained native chunk differs from committed intent')
            resumed+=1;recovered+=int(not ready)
            with state:state.execute('UPDATE chunks SET ready=1 WHERE cx=? AND cz=?',(cx,cz))
        level.close();level=None
        pending=[c for c in coordinates if c not in present]
        if chunk_limit is not None:pending=pending[:chunk_limit]
        for begin in range(0,len(pending),batch_size):
            batch=pending[begin:begin+batch_size]
            wrapper=LevelDBFormat(str(world_path));wrapper.open()
            for cx,cz in batch:
                array=factory(cx,cz);sha=tile_hash(array);count=int(np.count_nonzero(array))
                with state:state.execute('INSERT OR REPLACE INTO chunks VALUES(?,?,?,?,0)',(cx,cz,sha,count))
                if fault:fault('after_intent',cx,cz)
                wrapper.commit_chunk(_chunk(cx,cz,array,materials),DIMENSION)
            wrapper.save();wrapper.close();wrapper=None
            if fault:fault('after_flush',*batch[-1])
            level=open_native(world_path)
            for cx,cz in batch:
                expected=factory(cx,cz)
                actual=read_tile(level,cx,cz,materials)
                if not np.array_equal(actual,expected):raise ValueError('Native full-height tile readback differs from source rendering')
                with state:state.execute('UPDATE chunks SET ready=1 WHERE cx=? AND cz=?',(cx,cz))
                written+=1
            level.close();level=None
            atomic_json(output/'progress.json',{'verified_chunks':resumed+written,'requested_chunks':len(coordinates)})
            print(json.dumps({'stage':quality['name'],'verified_chunks':resumed+written,'total_chunks':len(coordinates)}),flush=True)
        ready,blocks=state.execute('SELECT COUNT(*),COALESCE(SUM(blocks),0) FROM chunks WHERE ready=1').fetchone()
        report={**quality,'version':VERSION,'status':'native_complete' if ready==len(coordinates) else 'partial_checkpoint',
                'requested_chunks':len(coordinates),'verified_chunks':ready,'new_chunks':written,
                'resumed_verified_chunks':resumed,'recovered_flushed_chunk_intents':recovered,
                'composed_blocks':blocks,'native_cell_positions_checked_this_run':(resumed+written)*int(np.prod(SHAPE)),
                'native_height_range_inclusive':[-64,319],'spawn_native_xyz':spawn,
                'contract':identity,'elapsed_seconds':time.perf_counter()-start,
                'peak_process_rss_mib':peak_process_rss_mib(),
                'minecraft_playtest':'not_performed','accepted_planning_components':0,'training_labels_generated':0}
        if ready!=len(coordinates):
            atomic_json(output/'checkpoint-report.json',report);return report
        level=open_native(world_path)
        if set(level.all_chunk_coords(DIMENSION))!=set(coordinates):raise ValueError('Native final chunk coverage differs')
        stored=level.root_tag.compound
        if [int(stored['Spawn'+axis]) for axis in 'XYZ']!=spawn:raise ValueError('Native spawn metadata differs')
        # A centred player needs a full supporting block and two empty blocks.
        cx,cz=spawn[0]//16,spawn[2]//16;array=read_tile(level,cx,cz,materials)
        sx,sy,sz=spawn[0]%16,spawn[1]+64,spawn[2]%16
        if not 1<=sy<382 or not array[sx,sy-1,sz] or np.any(array[sx,sy:sy+2,sz]):raise ValueError('Native scale-test spawn lacks bearing/headroom')
        level.close();level=None
        package=output/'park.mcworld';saved=output/'scale-report.json'
        if package.exists():
            previous=json.loads(saved.read_text())
            if file_hash(package)!=previous['world_sha256']:raise ValueError('Published scale package changed')
            atomic_json(output/'resume-check.json',{**report,'world_sha256':previous['world_sha256'],'existing_package_reused':True})
            return previous
        atomic_json(world_path/'voxel-scale-report.json',report)
        temporary=output/'park.mcworld.partial'
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(world_path.rglob('*')):
                if path.is_file() and path.name!='LOCK':archive.write(path,path.relative_to(world_path))
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:raise ValueError('Scale package CRC check failed')
        temporary.replace(package)
        report.update(world_sha256=file_hash(package),package_bytes=package.stat().st_size,
                      native_database_bytes=sum(p.stat().st_size for p in world_path.rglob('*') if p.is_file()),
                      elapsed_seconds=time.perf_counter()-start,peak_process_rss_mib=peak_process_rss_mib())
        atomic_json(saved,report)
        return report
    except Exception:
        (output/'park.mcworld.partial').unlink(missing_ok=True)
        raise
    finally:
        if wrapper is not None:wrapper.close()
        if level is not None:level.close()
        state.close()
