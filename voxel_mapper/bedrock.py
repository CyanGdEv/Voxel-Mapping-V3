"""Write and verify a real Bedrock LevelDB world, packaged as .mcworld."""
import hashlib
import json
import math
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

import amulet
import numpy as np
from amulet.api.block import Block
from amulet.api.chunk import Chunk
from amulet.level.formats.leveldb_world import LevelDBFormat
from amulet_nbt import ByteTag, IntTag, LongTag, StringTag

VERSION = (1, 21, 130)
MATERIALS = {'terrain':'grass_block','water':'water','parking':'stone','path':'stone',
             'attraction':'iron_block','building':'stone_bricks','structure':'stone'}
PRIORITY = {'terrain':0,'water':1,'parking':2,'path':3,'attraction':4,'building':5,'structure':6}


def export_world(voxel_path, output, report, name='Voxel Park', max_blocks=40_000_000, ground_depth=4):
    if report['voxel_size_m'] != 1:
        raise ValueError('Bedrock 1:1 world export requires voxel_size_m = 1')
    output = Path(output)
    world_path = output/'bedrock-world'
    package = output/'park.mcworld'
    if world_path.exists() or package.exists():
        raise ValueError('Refusing to overwrite an existing exported world')
    if not 1 <= ground_depth <= 32:
        raise ValueError('ground_depth must be between 1 and 32 blocks')
    lowest, highest, spawn_distance, spawn_x, spawn_z = math.inf, -math.inf, math.inf, 0, 0
    count = 0
    with Path(voxel_path).open() as stream:
        for line in stream:
            record = json.loads(line)
            y = record['y']
            lowest, highest = min(lowest,y), max(highest,y)
            count += 1
            distance = record['x']**2 + record['z']**2
            if distance < spawn_distance:
                spawn_distance, spawn_x, spawn_z = distance, record['x'], -record['z']
    if not count:
        raise ValueError('No voxel data exists to export')
    y_offset = 64-int(lowest)
    if highest+y_offset > 317:
        raise ValueError('Park exceeds Bedrock vertical range; cannot retain 1:1 scale without cropping')
    wrapper = None
    try:
        with tempfile.TemporaryDirectory(prefix='voxel-world-') as temp:
            connection = sqlite3.connect(str(Path(temp)/'blocks.sqlite'))
            connection.execute('PRAGMA journal_mode=OFF')
            connection.execute('PRAGMA synchronous=OFF')
            connection.execute('CREATE TABLE blocks (cx INTEGER, cz INTEGER, x INTEGER, y INTEGER, z INTEGER, material TEXT, priority INTEGER, PRIMARY KEY(cx,cz,x,y,z)) WITHOUT ROWID')
            sql = 'INSERT INTO blocks VALUES (?,?,?,?,?,?,?) ON CONFLICT(cx,cz,x,y,z) DO UPDATE SET material=excluded.material, priority=excluded.priority WHERE excluded.priority > blocks.priority'
            pending = []
            attempted = 0
            with Path(voxel_path).open() as stream:
                for line in stream:
                    record = json.loads(line)
                    x,z,y = int(record['x']),-int(record['z']),int(record['y'])+y_offset
                    kind = record['kind']
                    material = MATERIALS.get(kind,'stone')
                    pending.append((x//16,z//16,x%16,y,z%16,material,PRIORITY.get(kind,6)))
                    if kind == 'terrain':
                        for depth in range(1,ground_depth+1):
                            pending.append((x//16,z//16,x%16,y-depth,z%16,'dirt' if depth<=2 else 'stone',-1))
                    attempted += 1+(ground_depth if kind=='terrain' else 0)
                    if attempted > max_blocks:
                        raise ValueError('World block budget exceeded; split the park area')
                    if len(pending)>=10_000:
                        connection.executemany(sql,pending)
                        pending.clear()
            if pending:
                connection.executemany(sql,pending)
            connection.commit()
            stored = connection.execute('SELECT COUNT(*) FROM blocks').fetchone()[0]
            top = connection.execute('SELECT MAX(y) FROM blocks WHERE cx=? AND cz=? AND x=? AND z=?',
                                     (spawn_x//16,spawn_z//16,spawn_x%16,spawn_z%16)).fetchone()[0]
            wrapper = LevelDBFormat(str(world_path))
            wrapper.create_and_open('bedrock',VERSION)
            root = wrapper.root_tag.compound
            root['LevelName'] = StringTag(str(name)+' — draft 1:1')
            root['GameType'] = IntTag(1)
            root['Difficulty'] = IntTag(0)
            root['SpawnX'],root['SpawnY'],root['SpawnZ'] = IntTag(spawn_x),IntTag(top+2),IntTag(spawn_z)
            root['RandomSeed'] = LongTag(0)
            root['commandsEnabled'] = ByteTag(1)
            root['spawnMobs'] = ByteTag(0)
            root['doDaylightCycle'] = ByteTag(0)
            root['Time'] = LongTag(6000)
            chunk_count = 0
            # Direct chunk commits keep the working set bounded to one chunk.
            coords = connection.execute('SELECT DISTINCT cx,cz FROM blocks ORDER BY cx,cz').fetchall()
            for cx,cz in coords:
                chunk = Chunk(cx,cz)
                # New chunk arrays initialise to palette index zero. It must be air.
                air_id = chunk.block_palette.get_add_block(Block("universal_minecraft", "air"))
                if air_id != 0:
                    raise ValueError("New chunk palette must reserve index zero for air")
                palette = {"air": air_id}
                for x,y,z,material in connection.execute('SELECT x,y,z,material FROM blocks WHERE cx=? AND cz=?',(cx,cz)):
                    if material not in palette:
                        block = Block('universal_minecraft',material)
                        palette[material] = chunk.block_palette.get_add_block(block)
                    chunk.blocks[x,y,z] = palette[material]
                chunk.changed = True
                wrapper.commit_chunk(chunk,'minecraft:overworld')
                chunk_count += 1
            wrapper.save()
            wrapper.close()
            wrapper = None
            # The writer can log translation errors rather than raising them. Reopen
            # and compare every block against the composed output before packaging.
            level = amulet.load_level(str(world_path))
            try:
                actual_coords = set(level.all_chunk_coords('minecraft:overworld'))
                if actual_coords != set(coords):
                    raise ValueError('Bedrock round-trip chunk coverage failed')
                for cx,cz in coords:
                    chunk = level.get_chunk(cx,cz,'minecraft:overworld')
                    expected_sections = {}
                    for x,y,z,material in connection.execute('SELECT x,y,z,material FROM blocks WHERE cx=? AND cz=?',(cx,cz)):
                        expected_sections.setdefault(y//16, np.zeros((16,16,16), dtype=bool))[x,y%16,z] = True
                        actual = chunk.block_palette[int(chunk.blocks[x,y,z])]
                        if actual.base_name != material:
                            raise ValueError(f'Bedrock block round-trip failed at {cx*16+x},{y},{cz*16+z}: {actual} != {material}')
                    is_solid = np.array([block.base_name != "air" for block in chunk.block_palette], dtype=bool)
                    for section in set(chunk.blocks.sub_chunks) | set(expected_sections):
                        expected_mask = expected_sections.get(section)
                        if expected_mask is None:
                            expected_mask = np.zeros((16,16,16), dtype=bool)
                        actual_mask = is_solid[chunk.blocks.get_sub_chunk(section)]
                        if not np.array_equal(actual_mask, expected_mask):
                            unexpected = int(np.count_nonzero(actual_mask & ~expected_mask))
                            missing = int(np.count_nonzero(expected_mask & ~actual_mask))
                            raise ValueError(f"Bedrock air/solid occupancy failed in chunk {cx},{cz}, section {section}: {unexpected} unexpected and {missing} missing blocks")
                    level.unload()
            finally:
                level.close()
                connection.close()
        (world_path/'voxel-quality-report.json').write_text(json.dumps(report,indent=2))
        (world_path/'voxel-georeferencing.json').write_text(json.dumps({'blocks_per_metre':1,'crs':report.get('crs'),'vertical_offset_blocks':y_offset,'minecraft_z':'negative north','quality':'draft_unverified'},indent=2))
        attribution = ['Voxel Mapper 3.1 — draft, unverified reconstruction. 1 block = 1 metre.']
        attribution += [f"{source['id']}: {source.get('attribution',source.get('license',''))} {source['url']}" for source in report.get('sources',[])]
        attribution += [source['attribution_url'] for source in report.get('sources',[]) if source.get('attribution_url')]
        (world_path/'ATTRIBUTION.txt').write_text('\n'.join(attribution)+'\n')
        with zipfile.ZipFile(package,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(world_path.rglob('*')):
                if path.is_file() and path.name != 'LOCK':
                    archive.write(path,path.relative_to(world_path))
        with package.open('rb') as stream:
            checksum = hashlib.file_digest(stream,'sha256').hexdigest()
        return {'format':'Bedrock .mcworld','file':package.name,'target_version':list(VERSION),
                'blocks_per_metre':1,'horizontal_transform':{'minecraft_x':'east','minecraft_z':'negative north'},
                'vertical_offset_blocks':y_offset,'geographic_elevation_m':'Minecraft Y minus vertical_offset_blocks',
                'spawn':[spawn_x,top+2,spawn_z], 'chunks':chunk_count,'composed_blocks':stored,
                'ground_fill_depth_blocks':ground_depth,'round_trip_validation':'all written blocks and all unwritten air cells verified',
                'sha256':checksum,'quality':'draft_unverified',
                'limitations':['Generic block materials and solid building extrusion','Ground filled only a few blocks below sampled terrain','Outside mapped chunks Minecraft may generate unrelated terrain','Not yet tested by importing into the Minecraft game']}
    except Exception:
        if wrapper:
            wrapper.close()
        package.unlink(missing_ok=True)
        shutil.rmtree(world_path,ignore_errors=True)
        raise
