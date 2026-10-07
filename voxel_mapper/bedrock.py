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
from .transport import SURFACE_MATERIALS, CONCRETE_MATERIALS, TRANSPORT_KINDS

VERSION = (1, 21, 130)
MATERIALS = {'terrain':'grass_block','water':'water','parking':'stone','path':'stone',
             'lakebed':'stone', 'plaza':'stone',
             'road':'black_concrete','sidewalk':'stone','queue':'stone','cycleway':'stone','steps':'stone',
             'attraction':'iron_block','building':'stone_bricks','roof':'stone','structure':'stone'}
PRIORITY = {'terrain':0,'water':1,'parking':2,'path':3,'attraction':4,'building':5,'roof':7,'structure':6}
PRIORITY.update({kind: 3 for kind in ('road','sidewalk','queue','cycleway','steps')})
PRIORITY.update(lakebed=1,plaza=3)
ALLOWED_MATERIALS = set(MATERIALS.values()) | set(SURFACE_MATERIALS.values()) | CONCRETE_MATERIALS | {'dark_oak_planks','air','oak_log','spruce_log','oak_leaves','spruce_leaves'}


def material_block(material):
    if material in CONCRETE_MATERIALS:
        return Block('universal_minecraft', 'concrete', {'color': StringTag(material.removesuffix('_concrete'))})
    if material in ('oak_planks', 'dark_oak_planks'):
        return Block('universal_minecraft', 'planks', {'material': StringTag('dark_oak' if material == 'dark_oak_planks' else 'oak')})
    if material in ('oak_log','spruce_log'):
        return Block('universal_minecraft','log',{'material':StringTag(material.removesuffix('_log')),'axis':StringTag('y'),'stripped':StringTag('false')})
    if material in ('oak_leaves','spruce_leaves'):
        return Block('universal_minecraft','leaves',{'material':StringTag(material.removesuffix('_leaves')),'persistent':StringTag('true'),'distance':StringTag('7'),'check_decay':StringTag('false')})
    return Block('universal_minecraft', material)


def export_world(voxel_path, output, report, name='Voxel Park', max_blocks=40_000_000, ground_depth=16, foundation_mode='shared'):
    if report['voxel_size_m'] != 1:
        raise ValueError('Bedrock 1:1 world export requires voxel_size_m = 1')
    output = Path(output)
    world_path = output/'bedrock-world'
    package = output/'park.mcworld'
    if world_path.exists() or package.exists():
        raise ValueError('Refusing to overwrite an existing exported world')
    if not 1 <= ground_depth <= 32:
        raise ValueError('ground_depth must be between 1 and 32 blocks')
    if foundation_mode not in ('shared','chunk'):
        raise ValueError('Foundation mode must be shared or chunk')
    chunk_ground = {}
    lowest, highest, spawn_distance, spawn_x, spawn_z = math.inf, -math.inf, math.inf, 0, 0
    count = 0
    lowest_ground = math.inf
    with Path(voxel_path).open() as stream:
        for line in stream:
            record = json.loads(line)
            y = record['y']
            lowest, highest = min(lowest,y), max(highest,y)
            if record['kind'] == 'terrain':
                lowest_ground = min(lowest_ground, y)
                key = (int(record['x'])//16,(-int(record['z']))//16)
                chunk_ground[key] = min(chunk_ground.get(key,math.inf),y)
            count += 1
            distance = record['x']**2 + record['z']**2
            if distance < spawn_distance:
                spawn_distance, spawn_x, spawn_z = distance, record['x'], -record['z']
    if not count:
        raise ValueError('No voxel data exists to export')
    y_offset = 64-int(lowest)
    # One shared artificial foundation closes hillside undersides. Only measured
    # dry-land terrain columns qualify: never infer a lake bed or bridge support.
    foundation_y = max(-64, math.floor(lowest_ground)+y_offset-ground_depth) if math.isfinite(lowest_ground) else None
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
                    material = record.get('material', MATERIALS.get(kind,'stone'))
                    if material not in ALLOWED_MATERIALS:
                        raise ValueError(f'Unsupported block material: {material}')
                    # An accepted drawing material must beat generic/mapped paving
                    # at the same block, regardless of input ordering. Keep its
                    # physical layer below buildings, structures and roofs.
                    priority=PRIORITY.get(kind,6)*10
                    if record.get('material_origin') in ('estimated_reconstruction_void','estimated_reconstruction_shell'):
                        priority = 89 if material == 'air' else 90
                    if record.get('material_origin') in ('accepted_planning_void','accepted_planning_shell'):
                        priority = 95 if material == 'air' else 96
                    if kind in TRANSPORT_KINDS:
                        priority += {'mapped_transport_surface':1,'accepted_planning_paving':2}.get(record.get('material_origin'),0)
                    pending.append((x//16,z//16,x%16,y,z%16,material,priority))
                    if kind == 'terrain':
                        bottom = foundation_y if foundation_mode == 'shared' else max(-64,math.floor(chunk_ground[(x//16,z//16)])+y_offset-ground_depth)
                        for depth in range(1,y-bottom+1):
                            pending.append((x//16,z//16,x%16,y-depth,z%16,'dirt' if depth<=2 else 'stone',-1))
                    attempted += 1+(y-bottom if kind=='terrain' else 0)
                    if attempted > max_blocks:
                        raise ValueError('World block budget exceeded; split the park area')
                    if len(pending)>=10_000:
                        connection.executemany(sql,pending)
                        pending.clear()
            if pending:
                connection.executemany(sql,pending)
            connection.commit()
            stored = connection.execute("SELECT COUNT(*) FROM blocks WHERE material != 'air'").fetchone()[0]
            air_cells = connection.execute("SELECT COUNT(*) FROM blocks WHERE material = 'air'").fetchone()[0]
            if stored == 0:
                raise ValueError('No occupied blocks exist after composition')
            top = connection.execute("SELECT MAX(y) FROM blocks WHERE cx=? AND cz=? AND x=? AND z=? AND material != 'air'",
                                     (spawn_x//16,spawn_z//16,spawn_x%16,spawn_z%16)).fetchone()[0]
            if report.get('spawn_local_xyz_m') is not None:
                visit = report['spawn_local_xyz_m']
                if len(visit) != 3 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in visit):
                    raise ValueError('Finite local x/y/z spawn coordinates required')
                spawn_x,spawn_z = math.floor(visit[0]),-math.floor(visit[2])
                top = math.floor(visit[1])+y_offset-2
                if not -60 <= top+2 <= 316:
                    raise ValueError('Requested spawn is outside supported world height')
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
                        block = material_block(material)
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
                    missing = sorted(set(coords)-actual_coords)
                    extra = sorted(actual_coords-set(coords))
                    raise ValueError(f'Bedrock round-trip chunk coverage failed: {len(missing)} missing {missing[:5]}, {len(extra)} extra {extra[:5]}')
                for cx,cz in coords:
                    chunk = level.get_chunk(cx,cz,'minecraft:overworld')
                    expected_sections = {}
                    for x,y,z,material in connection.execute('SELECT x,y,z,material FROM blocks WHERE cx=? AND cz=?',(cx,cz)):
                        expected_sections.setdefault(y//16, np.zeros((16,16,16), dtype=bool))[x,y%16,z] = material != 'air'
                        actual = chunk.block_palette[int(chunk.blocks[x,y,z])]
                        expected = material_block(material)
                        if actual.namespaced_name != expected.namespaced_name or any(actual.properties.get(k) != v for k,v in expected.properties.items()):
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
                'spawn':[spawn_x,top+2,spawn_z], 'chunks':chunk_count,'composed_blocks':stored,'explicit_air_cells':air_cells,
                'ground_fill_depth_blocks':ground_depth,'round_trip_validation':'all written blocks and all unwritten air cells verified',
                'foundation':{'minecraft_y':foundation_y,'mode':foundation_mode,
                              'method':('shared artificial dry-land foundation' if foundation_mode=='shared' else 'per-chunk minimum dry-land elevation minus fill depth')+'; not measured subsurface geology or bathymetry'},
                'paving_composition':'mapped constituent materials beat assumed paving; accepted planning materials take precedence; higher structures remain intact',
                'sha256':checksum,'quality':'draft_unverified',
                'limitations':['Generic materials; solid building extrusion or DSM surface profile, not a detailed mesh','Artificial dry-land foundation; unmapped lake depths remain unknown','Outside mapped chunks Minecraft may generate unrelated terrain','This export has no automated in-game visual fidelity validation']}
    except Exception:
        if wrapper:
            wrapper.close()
        package.unlink(missing_ok=True)
        shutil.rmtree(world_path,ignore_errors=True)
        raise
