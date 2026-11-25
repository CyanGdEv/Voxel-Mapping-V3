"""Bounded native Bedrock patches on fresh copies; preserve unrelated records.

Uses Amulet's existing palette codec, not its whole-chunk/world save path.
Only v9, single-storage subchunks and already present native palette entries
are supported. Unsupported formats fail closed. No prediction auto-acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate_plan(plan, baseline_hash):
    if plan.get('schema')!='bedrock-scoped-patch-v1' or plan.get('baseline_sha256')!=baseline_hash:
        raise ValueError('Patch baseline identity mismatch')
    registration=plan.get('registration',{})
    if registration.get('accepted_for_this_patch') is not True or not registration.get('evidence_sha256'):
        raise ValueError('Scoped registration acceptance is required')
    edits=plan.get('edits',[])
    if not 1<=len(edits)<=64:raise ValueError('Patch block budget must be 1..64')
    if len({tuple(e['xyz']) for e in edits})!=len(edits):raise ValueError('Duplicate block coordinates')
    chunks=set()
    allowed={'minecraft:stone_bricks','minecraft:cracked_stone_bricks','minecraft:mossy_stone_bricks',
             'minecraft:grass_block','minecraft:air','minecraft:deepslate_tiles','minecraft:cracked_deepslate_tiles'}
    for e in edits:
        if len(e['xyz'])!=3 or any(type(v) is not int for v in e['xyz']):raise ValueError('Integer block coordinates required')
        x,y,z=e['xyz'];chunks.add((x//16,z//16))
        if not -64<=y<320:raise ValueError('Unsupported Bedrock height')
        if e.get('accepted') is not True or not e.get('evidence_sha256'):raise ValueError('Unaccepted evidence')
        if e.get('source_type') not in ('reviewed_mask','measured_surface_conflict'):
            raise ValueError('Uncalibrated/model candidates cannot be written')
        if e['before'] not in allowed or e['after'] not in allowed or e['before']==e['after']:
            raise ValueError('Unsupported material transition')
        if not ((e['before'] in {'minecraft:stone_bricks','minecraft:cracked_stone_bricks','minecraft:mossy_stone_bricks'} and e['after']=='minecraft:grass_block' and e['source_type']=='reviewed_mask') or
                (e['before'] in {'minecraft:deepslate_tiles','minecraft:cracked_deepslate_tiles'} and e['after']=='minecraft:air' and e['source_type']=='measured_surface_conflict')):
            raise ValueError('Unsupported scoped transition')
    if len(chunks)>4:raise ValueError('Patch chunk budget exceeded')
    columns={(e['xyz'][0],e['xyz'][2]) for e in edits}
    heights=plan.get('height_updates',[])
    if len({tuple(h['xz']) for h in heights})!=len(heights) or {tuple(h['xz']) for h in heights}!=columns:
        raise ValueError('One explicit height precondition/update required per edited column')
    for h in heights:
        if len(h['xz'])!=2 or any(type(v) is not int for v in h['xz']+[h['before'],h['after']]):
            raise ValueError('Integer height metadata required')
        if not 0<=h['after']<=320 or h['after']>h['before']:raise ValueError('Unsupported height update')
    return edits


def patch_subchunk(raw, edits):
    import numpy as np
    from amulet.level.formats.leveldb_world.interface.chunk.base_leveldb_interface import BaseLevelDBInterface
    codec=BaseLevelDBInterface.__new__(BaseLevelDBInterface)
    if len(raw)<4 or raw[0]!=9 or raw[1]!=1 or raw[3]&1:
        raise ValueError('Only native v9 single-storage subchunks are supported')
    cy=struct.unpack('b',raw[2:3])[0]
    tail,bits,old=codec._decode_packed_array(raw[3:])
    if bits not in (1,2,3,4,5,6,8,16) or old is None:raise ValueError('Unsupported palette packing')
    values,palette,remainder=codec._load_palette_blocks(raw[3:])
    if remainder or not np.array_equal(old,values):raise ValueError('Unexpected subchunk data')
    names=[p.compound['name'].py_str for p in palette]
    if int(old.min())<0 or int(old.max())>=len(palette):raise ValueError('Invalid native palette index')
    new=old.copy();changed=set()
    for e in edits:
        x,y,z=e['xyz'];local=(x%16,y%16,z%16)
        if y//16!=cy or local in changed:raise ValueError('Subchunk coordinate mismatch/duplicate')
        if names[int(old[local])]!=e['before']:raise ValueError('Native block precondition failed')
        targets=[i for i,p in enumerate(palette) if names[i]==e['after'] and not p.compound.get_compound('states').py_dict]
        if len(targets)!=1:raise ValueError('Unique existing stateless target palette entry required')
        new[local]=targets[0];changed.add(local)
    encoded=codec._encode_packed_array(new,min_bit_size=bits)
    after=raw[:3]+encoded+tail  # Preserve original NBT/palette bytes exactly.
    rest,after_bits,decoded=codec._decode_packed_array(after[3:])
    if after_bits!=bits or rest!=tail or not np.array_equal(decoded,new):raise ValueError('Palette codec round trip failed')
    if set(map(tuple,np.argwhere(old!=decoded)))!=changed:raise ValueError('Unrequested block change')
    return after


def patch_records(records, plan):
    """Preflight every record before any database mutation; return changed values."""
    groups={};changes={}
    for e in plan['edits']:
        x,y,z=e['xyz'];key=struct.pack('<ii',x//16,z//16)+b'\x2f'+struct.pack('b',y//16)
        if struct.pack('<ii',x//16,z//16)+b'\x31' in records:
            raise ValueError('Block-entity chunks are protected')
        groups.setdefault(key,[]).append(e)
    for key,edits in groups.items():
        if key not in records:raise ValueError('Missing existing subchunk')
        changes[key]=patch_subchunk(records[key],edits)
    for h in plan['height_updates']:
        x,z=h['xz'];key=struct.pack('<ii',x//16,z//16)+b'\x2b'
        raw=changes.get(key,records.get(key,b''))
        if len(raw)<512:raise ValueError('Missing native Data3D heightmap')
        offset=2*((z%16)*16+x%16)
        if struct.unpack_from('<H',raw,offset)[0]!=h['before']:raise ValueError('Heightmap precondition failed')
        value=bytearray(raw);struct.pack_into('<H',value,offset,h['after']);changes[key]=bytes(value)
    # Enforce final column tops, including higher subchunks and secondary storage.
    from amulet.level.formats.leveldb_world.interface.chunk.base_leveldb_interface import BaseLevelDBInterface
    codec=BaseLevelDBInterface.__new__(BaseLevelDBInterface)
    for h in plan['height_updates']:
        x,z=h['xz'];prefix=struct.pack('<ii',x//16,z//16)+b'\x2f';top=None
        for key,original in records.items():
            if len(key)!=10 or key[:9]!=prefix:continue
            raw=changes.get(key,original)
            if raw[:2]!=b'\x09\x01':raise ValueError('Unsupported storage in edited column')
            cy=struct.unpack('b',raw[2:3])[0];array,palette,rest=codec._load_palette_blocks(raw[3:])
            if rest:raise ValueError('Unexpected storage tail')
            for ly in range(16):
                if palette[int(array[x%16,ly,z%16])].compound['name'].py_str!='minecraft:air':
                    top=max(top if top is not None else -65,cy*16+ly)
        if top is None or top+1!=h['after']:raise ValueError('Proposed heightmap disagrees with actual final column')
    return changes


def extract_archive(archive, root):
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        if len(names)!=len(set(names)) or not {'level.dat','levelname.txt'}.issubset(names):
            raise ValueError('Invalid native world archive')
        if sum(i.file_size for i in z.infolist())>2_000_000_000:raise ValueError('Archive extraction budget exceeded')
        for item in z.infolist():
            dest=(root/item.filename).resolve()
            if not dest.is_relative_to(root.resolve()):raise ValueError('Unsafe archive member')
        z.extractall(root)
    if not (root/'db').is_dir():raise ValueError('Missing native LevelDB')


def snapshot(root):
    import leveldb
    db=leveldb.LevelDB(str(root/'db'),create_if_missing=False)
    try:return dict(db.iterate())
    finally:db.close()


def apply(baseline, plan_path, output, report_path):
    """Publish only after re-extraction and full logical-record verification."""
    import leveldb
    plan=json.loads(plan_path.read_text());baseline_hash=digest(baseline.read_bytes())
    validate_plan(plan,baseline_hash)
    if output.exists() or report_path.exists() or output.resolve() in (baseline.resolve(),report_path.resolve()):raise ValueError('Fresh output paths required')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='bedrock-preview-') as td:
        root=Path(td)/'work';root.mkdir();extract_archive(baseline,root)
        before=snapshot(root);changes=patch_records(before,plan)
        db=leveldb.LevelDB(str(root/'db'),create_if_missing=False)
        try:
            for key,value in changes.items():db.put(key,value)
        finally:db.close()
        after=snapshot(root)
        if before.keys()!=after.keys() or {k for k in before if before[k]!=after[k]}!=changes.keys():
            raise ValueError('Unexpected database record change')
        for key,value in changes.items():
            if after[key]!=value:raise ValueError('Database write verification failed')
        archive=Path(td)/'preview.mcworld'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for p in sorted(root.rglob('*')):
                if p.is_file():z.write(p,p.relative_to(root).as_posix())
        check=Path(td)/'reopened';check.mkdir();extract_archive(archive,check)
        if snapshot(check)!=after:raise ValueError('Export/reopen changed native records')
        import amulet
        level=amulet.load_level(str(check))
        try:
            for e in plan['edits']:
                block,entity=level.get_version_block(*e['xyz'],'minecraft:overworld',('bedrock',level.level_wrapper.version))
                if block.namespaced_name!=e['after'] or entity is not None:
                    raise ValueError('Independent Amulet block verification failed')
            chunk_count=len(list(level.all_chunk_coords('minecraft:overworld')))
            native_version=list(level.level_wrapper.version)
        finally:level.close()
        if snapshot(check)!=after:raise ValueError('Native records changed during independent reopening')
        with zipfile.ZipFile(baseline) as original,zipfile.ZipFile(archive) as exported:
            original_files={n:original.read(n) for n in original.namelist() if not n.startswith('db/') and not n.endswith('/')}
            exported_files={n:exported.read(n) for n in exported.namelist() if not n.startswith('db/') and not n.endswith('/')}
            if original_files!=exported_files:raise ValueError('Non-database world assets changed')
        if digest(baseline.read_bytes())!=baseline_hash:raise ValueError('Original world changed')
        report={'schema':'bedrock-scoped-patch-result-v1','baseline_sha256':baseline_hash,
            'plan_sha256':digest(plan_path.read_bytes()),'output_sha256':digest(archive.read_bytes()),
            'blocks_changed':len(plan['edits']),'height_columns_changed':len(plan['height_updates']),
            'native_records_total':len(before),'native_records_changed':len(changes),
            'records':[{'key_hex':k.hex(),'before_sha256':digest(before[k]),'after_sha256':digest(v)} for k,v in changes.items()],
            'non_database_assets_unchanged':True,'all_other_native_records_unchanged':True,
            'export_reextraction_records_identical':True,'independent_amulet_block_checks':len(plan['edits']),
            'overworld_chunks':chunk_count,'bedrock_version':native_version,'edits':plan['edits'],
            'limitations':['Native-format verification; not an in-game Minecraft client test.','Scoped reviewed/measured evidence only; no AI model promotion.']}
        # Copy verified bytes; the source archive is never opened for writing.
        temporary=output.with_suffix(output.suffix+'.tmp')
        if temporary.exists():raise ValueError('Stale temporary output')
        try:temporary.write_bytes(archive.read_bytes());temporary.replace(output)
        finally:temporary.unlink(missing_ok=True)
        report_path.parent.mkdir(parents=True,exist_ok=True);report_path.write_text(json.dumps(report,indent=2))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('baseline','plan','output','report'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    result=apply(args.baseline,args.plan,args.output,args.report)
    print(json.dumps({k:v for k,v in result.items() if k not in ('edits','records')},indent=2))
