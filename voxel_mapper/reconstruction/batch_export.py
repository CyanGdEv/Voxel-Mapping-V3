"""Resumable chunk-at-a-time Bedrock composition and complete touched-section readback."""
import hashlib
import json
import math
import sqlite3
import zipfile
from pathlib import Path

import numpy as np
from pyproj import CRS
from ..bedrock import material_block


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def section_hashes(chunk):
    palette=np.array([str(b) for b in chunk.block_palette],dtype=object)
    return {str(s):hashlib.sha256(('\n'.join(palette[chunk.blocks.get_sub_chunk(s)].ravel())+'\n').encode()).hexdigest()
            for s in chunk.blocks.sub_chunks}


def verify_sections(chunk,expected):
    actual=section_hashes(chunk)
    air=hashlib.sha256(((str(material_block('air'))+'\n')*4096).encode()).hexdigest()
    for s in set(actual)|set(expected):
        if actual.get(s,air)!=expected.get(s,air):raise ValueError('Native touched-section readback failed: '+s)


def export_world(store,source,output,ground=None):
    import amulet
    source,output=Path(source),Path(output)
    if not store.report()['unique_voxel_cells']:raise ValueError('No accepted geometry; native export withheld')
    quality=json.loads((source/'quality-report.json').read_text())
    contract=json.loads(store.db.execute("SELECT value FROM metadata WHERE key='contract'").fetchone()[0])
    if CRS.from_user_input(contract['manifest']['crs'])!=CRS.from_user_input(quality['crs']):raise ValueError('Base world CRS mismatch')
    store.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    plan_hash=file_hash(store.path)
    package=source/'park.mcworld';source_hash=file_hash(package)
    if contract.get('base_package_sha256') and contract['base_package_sha256']!=source_hash:raise ValueError('Base package changed since feature compilation')
    offset=quality['world']['vertical_offset_blocks']
    identity=json.dumps({'plan':plan_hash,'source_package':source_hash,'version':'native-batch-v1'},sort_keys=True)
    fresh=not output.exists();output.mkdir(parents=True,exist_ok=True)
    state=sqlite3.connect(output/'export-state.sqlite')
    state.executescript('CREATE TABLE IF NOT EXISTS job(identity TEXT,ready INTEGER NOT NULL DEFAULT 0); CREATE TABLE IF NOT EXISTS chunks(cx INTEGER,cz INTEGER,expected TEXT,delta INTEGER,PRIMARY KEY(cx,cz));')
    if 'ready' not in {row[1] for row in state.execute('PRAGMA table_info(job)')}:
        state.execute('ALTER TABLE job ADD COLUMN ready INTEGER NOT NULL DEFAULT 1');state.commit()
    previous=state.execute('SELECT identity,ready FROM job').fetchone()
    if previous and previous[0]!=identity:state.close();raise ValueError('Different geometry/base world; use fresh export directory')
    if not fresh and not previous:state.close();raise ValueError('Output exists without a resumable export contract')
    destination=output/'bedrock-world'
    if fresh:
        with state:state.execute('INSERT INTO job(identity,ready) VALUES(?,0)',(identity,))
    if fresh or not previous[1]:
        if state.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]:state.close();raise ValueError('Incomplete baseline has committed chunks')
        destination.mkdir(exist_ok=True)
        try:
            with zipfile.ZipFile(package) as archive:
                total=0;names=set(archive.namelist())
                for entry in archive.infolist():
                    target=(destination/entry.filename).resolve();total+=entry.file_size
                    if not target.is_relative_to(destination.resolve()) or (entry.external_attr>>16)&0o170000==0o120000 or total>20_000_000_000:
                        raise ValueError('Unsafe or oversized base world archive')
                for path in destination.rglob('*'):
                    if path.is_file() and path.relative_to(destination).as_posix() not in names:raise ValueError('Unrecognized files in interrupted baseline extraction')
                if archive.testzip() is not None:raise ValueError('Base package CRC failed')
                archive.extractall(destination)
            with state:state.execute('UPDATE job SET ready=1')
        except Exception:
            state.close();raise
    world=amulet.load_level(str(destination));coords=set(world.all_chunk_coords('minecraft:overworld'))
    try:
        if hasattr(store,'scheduled_chunks') and not store.scheduled_chunks<=coords:
            raise ValueError('Scheduled chunks exceed retained terrain coverage')
        for cx,cz in store.db.execute('SELECT DISTINCT cx,cz FROM voxels ORDER BY cx,cz'):
            if (cx,cz) not in coords:raise ValueError('Planned geometry exceeds retained terrain chunk coverage')
            chunk=world.get_chunk(cx,cz,'minecraft:overworld')
            retained=state.execute('SELECT expected FROM chunks WHERE cx=? AND cz=?',(cx,cz)).fetchone()
            if retained:verify_sections(chunk,json.loads(retained[0]));world.unload();continue
            delta=0
            for row in store.tile_rows(cx,cz):
                x,y,z=row['x'],row['y']+offset,-row['z']
                if not -64<=y<=319:raise ValueError('Planned geometry outside native height limits')
                old=chunk.block_palette[int(chunk.blocks[x%16,y,z%16])];expected=material_block(row['material'])
                decision=json.loads(store.db.execute('SELECT decision FROM features WHERE id=?',(row['feature'],)).fetchone()[0])
                draft=contract.get('snapshot_mode')=='review_draft'
                guarded=draft and row.get('baseline_block_sha256')==hashlib.sha256(str(old).encode()).hexdigest()
                if draft and not guarded:raise ValueError('Draft baseline block changed; replacement withheld')
                floor=ground is not None and decision['family'] in ('paving','path','plaza') and row['y']==math.floor(ground(row['x']+.5,row['z']+.5)) and old.base_name in ('grass_block','dirt','stone','granite','gravel','sand')
                if old.extra_blocks or (old.base_name!='air' and old!=expected and not floor and not guarded):
                    raise ValueError('Native protected-world collision; no package: '+str([row['x'],row['y'],row['z']]))
                delta+=int(expected.base_name!='air')-int(old.base_name!='air');chunk.blocks[x%16,y,z%16]=chunk.block_palette.get_add_block(expected)
            chunk.changed=True;world.put_chunk(chunk,'minecraft:overworld');expected_hashes=section_hashes(chunk)
            # LevelDB writes are flushed by closing the wrapper. Unloading
            # alone can expose stale section bytes in this backend.
            world.save();world.close();world=None;del chunk
            world=amulet.load_level(str(destination))
            reopened=world.get_chunk(cx,cz,'minecraft:overworld');verify_sections(reopened,expected_hashes)
            with state:state.execute('INSERT INTO chunks VALUES(?,?,?,?)',(cx,cz,json.dumps(expected_hashes),delta))
            del reopened
            world.unload()
        if set(world.all_chunk_coords('minecraft:overworld'))!=coords:raise ValueError('Native chunk coverage changed')
        semantic={}
        bridge_report=destination/'garden-bridges-report.json'
        if bridge_report.exists():
            from .walking_audit import require_bridge_walks
            semantic['garden_bridges']=require_bridge_walks(world,offset,json.loads(bridge_report.read_text())['features'])
    except Exception:
        state.close();raise
    finally:
        if world is not None:world.close()
    count,delta=state.execute('SELECT COUNT(*),COALESCE(SUM(delta),0) FROM chunks').fetchone();state.close()
    provenance=store.export_provenance(output/'provenance')
    report={**store.report(),'job_contract':contract,'provenance_files':provenance,'status':'native_batch_export_verified','base_package_sha256':source_hash,'geometry_store_sha256':plan_hash,
            'touched_chunks':count,'semantic_verification':semantic,'native_check':'Every cell of touched sections, including unchanged blocks/air; full chunk coverage',
            'native_memory_contract':'One active chunk; wrapper closed/reopened to flush writes; saved section hashes persisted for resume'}
    quality['park_batch']=report;quality['world']['composed_blocks']+=delta
    if contract.get('snapshot_mode')=='review_draft':
        report.update(status='native_review_batch_export_verified',production_placement_eligible=False)
        quality['world']['quality']='draft_unverified'
    (destination/'park-batch-report.json').write_text(json.dumps(report,indent=2)+'\n')
    (destination/'voxel-quality-report.json').write_text(json.dumps(quality,indent=2)+'\n')
    temporary=output/'park.mcworld.partial'
    with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(destination.rglob('*')):
            if path.is_file() and path.name!='LOCK':archive.write(path,path.relative_to(destination))
    with zipfile.ZipFile(temporary) as archive:
        if archive.testzip() is not None:raise ValueError('Output package CRC failed')
    temporary.replace(output/'park.mcworld')
    quality['world']['sha256']=file_hash(output/'park.mcworld')
    (output/'quality-report.json').write_text(json.dumps(quality,indent=2)+'\n');(output/'park-batch-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report
