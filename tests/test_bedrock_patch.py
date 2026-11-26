import copy
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile
from voxel_mapper.bedrock_patch import validate_plan,extract_archive,patch_subchunk,patch_records,inspect_columns


def plan():
    return {'schema':'bedrock-scoped-patch-v1','baseline_sha256':'a'*64,
        'registration':{'accepted_for_this_patch':True,'evidence_sha256':'b'*64},
        'edits':[{'xyz':[6,93,1],'before':'minecraft:stone_bricks','after':'minecraft:grass_block','accepted':True,'source_type':'reviewed_mask','evidence_sha256':'c'*64},
                 {'xyz':[6,95,1],'before':'minecraft:deepslate_tiles','after':'minecraft:air','accepted':True,'source_type':'measured_surface_conflict','evidence_sha256':'c'*64}],
        'height_updates':[{'xz':[6,1],'before':96,'after':94}]}


class PlanTests(unittest.TestCase):
    def test_fail_closed_on_identity_acceptance_budget_and_model_candidates(self):
        p=plan();self.assertEqual(len(validate_plan(p,'a'*64)),2)
        variants=[]
        q=copy.deepcopy(p);q['baseline_sha256']='wrong';variants.append(q)
        q=copy.deepcopy(p);q['registration']['accepted_for_this_patch']=False;variants.append(q)
        q=copy.deepcopy(p);q['edits'][0]['accepted']=False;variants.append(q)
        q=copy.deepcopy(p);q['edits'][0]['source_type']='model_candidate';variants.append(q)
        q=copy.deepcopy(p);q['edits']*=40;variants.append(q)
        q=copy.deepcopy(p);q['height_updates']=[];variants.append(q)
        q=copy.deepcopy(p);q['edits'][0]['after']='minecraft:water';variants.append(q)
        for q in variants:
            with self.assertRaises(ValueError):validate_plan(q,'a'*64)

    def test_archive_traversal_and_missing_native_assets_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for entries in ({'level.dat':b'x','levelname.txt':b'x','../escape':b'x'}, {'level.dat':b'x'}):
                z=root/'bad.zip'
                with zipfile.ZipFile(z,'w') as out:
                    for n,v in entries.items():out.writestr(n,v)
                with self.assertRaises(ValueError):extract_archive(z,root/'extracted')


@unittest.skipUnless(importlib.util.find_spec('amulet'),'optional isolated Bedrock environment')
class NativePatchTests(unittest.TestCase):
    def fixture(self,bits=2):
        import numpy as np
        from amulet_nbt import NamedTag,CompoundTag,StringTag,IntTag
        from amulet.level.formats.leveldb_world.interface.chunk.base_leveldb_interface import BaseLevelDBInterface
        c=BaseLevelDBInterface.__new__(BaseLevelDBInterface)
        names=['minecraft:air','minecraft:grass_block','minecraft:stone_bricks','minecraft:deepslate_tiles']
        tags=[NamedTag(CompoundTag({'name':StringTag(n),'states':CompoundTag(),'version':IntTag(18168865)})) for n in names]
        a=np.zeros((16,16,16),np.uint16);a[6,13,1]=2;a[6,15,1]=3
        tail=struct.pack('<I',4)+b''.join(t.save_to(compressed=False,little_endian=True) for t in tags)
        raw=b'\x09\x01\x05'+c._encode_packed_array(a,min_bit_size=bits)+tail
        return raw,c,a,tail

    def test_axes_palettes_other_blocks_and_packing_widths_preserved(self):
        import numpy as np
        for bits in [2,3,4,5,6,8,16]:
            raw,c,old,tail=self.fixture(bits)
            result=patch_subchunk(raw,plan()['edits'])
            rest,width,a=c._decode_packed_array(result[3:])
            self.assertEqual(width,bits);self.assertEqual(rest,tail)
            self.assertEqual(a[6,13,1],1);self.assertEqual(a[6,15,1],0)
            self.assertEqual(set(map(tuple,np.argwhere(old!=a))),{(6,13,1),(6,15,1)})

    def test_preconditions_and_final_heights_prevent_hidden_geometry_loss(self):
        raw,c,old,tail=self.fixture()
        prefix=struct.pack('<ii',0,0)
        height=bytearray(512);struct.pack_into('<H',height,2*(16+6),96)
        records={prefix+b'\x2f\x05':raw,prefix+b'\x2b':bytes(height)+b'biomes-preserved'}
        changes=patch_records(records,plan())
        self.assertEqual(set(changes),set(records))
        self.assertEqual(changes[prefix+b'\x2b'][512:],b'biomes-preserved')
        self.assertEqual(struct.unpack_from('<H',changes[prefix+b'\x2b'],44)[0],94)
        q=plan();q['edits'][0]['before']='minecraft:mossy_stone_bricks'
        with self.assertRaises(ValueError):patch_records(records,q)
        q=plan();q['height_updates'][0]['before']=95
        with self.assertRaises(ValueError):patch_records(records,q)
        q=plan();q['height_updates'][0]['after']=95
        with self.assertRaises(ValueError):patch_records(records,q)
        protected={**records,prefix+b'\x31':b'block entities'}
        with self.assertRaises(ValueError):patch_records(protected,plan())
        q=bytearray(raw);q[1]=2
        with self.assertRaises(ValueError):patch_subchunk(bytes(q),plan()['edits'])

    def test_column_inspector_rejects_stale_heightmaps(self):
        import leveldb
        raw,codec,array,tail=self.fixture()
        prefix=struct.pack('<ii',0,0)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'world';root.mkdir()
            (root/'level.dat').write_bytes(b'fixture-not-a-client-world')
            (root/'levelname.txt').write_text('fixture')
            height=bytearray(512);struct.pack_into('<H',height,44,96)
            for name,value in [('correct',96),('stale',94)]:
                struct.pack_into('<H',height,44,value)
                db=leveldb.LevelDB(str(root/'db'),create_if_missing=True)
                try:
                    db.put(prefix+b'\x2f\x05',raw)
                    db.put(prefix+b'\x2f\x06',b'\x09\x01\x06'+codec._encode_packed_array(array*0,min_bit_size=2)+tail)
                    db.put(prefix+b'\x2b',bytes(height))
                finally:db.close()
                archive=Path(td)/(name+'.zip')
                with zipfile.ZipFile(archive,'w') as z:
                    for f in root.rglob('*'):
                        if f.is_file():z.write(f,f.relative_to(root).as_posix())
                result=inspect_columns(archive,[{'x':6,'z':1,'dtm':192.,'dsm':192.02}],98)[0]
                self.assertEqual(result['supported_storage'],name=='correct')
                self.assertEqual(result['native_heightmap_top_y'],value-1)
                self.assertEqual(result['native_observed_top_y'],95)
                self.assertEqual(result['native_observed_top_block'],'minecraft:deepslate_tiles')
