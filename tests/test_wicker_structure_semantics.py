import json
from pathlib import Path
import unittest
import tempfile

import numpy as np
from scipy import ndimage as ndi

from tests.test_alton_aligned_world import layers
from voxel_mapper.alton_aligned_world import ChunkRenderer, ParkLayers
from voxel_mapper.wicker_structure_semantics import effigy_model, blocked_vegetation


class WickerStructureTests(unittest.TestCase):
    def profile(self):
        return json.loads((Path(__file__).resolve().parents[1]/'voxel_mapper/data/wicker-structural-reconstruction.json').read_text())['big_bob']

    def test_complete_effigy_is_connected_with_two_heads_and_curled_horn_extent(self):
        p=self.profile(); model=effigy_model(p,407530,343530,-31)
        a=np.array(list(model)); lo=a.min(axis=0);hi=a.max(axis=0)
        occupied=np.zeros(hi-lo+1,bool); q=a-lo;occupied[tuple(q.T)]=True
        components,n=ndi.label(occupied)
        sizes=np.bincount(components.ravel())[1:]
        self.assertGreater(len(model),500)
        self.assertGreater(float(sizes.max()/len(model)),.98)
        self.assertEqual(n,1)
        self.assertGreater(hi[0]-lo[0],9)
        self.assertGreater(hi[1]-lo[1],15)
        self.assertIn('oak_slab',model.values())
        self.assertIn(p['recess_material'],model.values())

    def test_body_is_a_shell_with_an_open_arch_instead_of_a_solid_box(self):
        p=self.profile(); model=effigy_model(p,407530,343530,-31)
        x=int(p['body_center_bng_en'][0]-407530)
        z=int(343530-p['body_center_bng_en'][1])
        self.assertNotIn((x,int(p['base_odn_m']+3-31),z),model)
        bbox=np.array(list(model));full=np.prod(bbox.max(axis=0)-bbox.min(axis=0)+1)
        self.assertLess(len(model),full*.6)

    def test_user_reference_palette_contains_stairs_panels_collar_and_shoulder_emitters(self):
        model=effigy_model(self.profile(),407530,343530,-31)
        values=list(model.values())
        self.assertGreater(sum('stairs' in m for m in values),20)
        self.assertGreater(sum('trapdoor' in m for m in values),6)
        self.assertGreater(values.count('smooth_stone_slab'),10)
        self.assertEqual(values.count('campfire'),6)
        self.assertIn('terracotta',values)

    def test_lit_campfire_native_state_and_block_entity_round_trip(self):
        from amulet.api.chunk import Chunk
        from amulet.level.formats.leveldb_world import LevelDBFormat
        from voxel_mapper.bedrock import material_block,VERSION
        from voxel_mapper.alton_aligned_world import _canonical
        with tempfile.TemporaryDirectory() as tmp:
            path=str(Path(tmp)/'world');w=LevelDBFormat(path);w.create_and_open('bedrock',VERSION)
            block=material_block('campfire');chunk=Chunk(0,0)
            chunk.blocks[1,64,1]=chunk.block_palette.get_add_block(block);chunk.changed=True
            w.commit_chunk(chunk,'minecraft:overworld');w.save();w.close()
            w=LevelDBFormat(path);w.open()
            try:
                c=w.load_chunk(0,0,'minecraft:overworld')
                self.assertTrue(_canonical(c.block_palette[int(c.blocks[1,64,1])],block))
                self.assertIn((1,64,1),c.block_entities)
            finally:w.close()

    def test_vegetation_exclusion_has_a_vertical_cap(self):
        l=layers();l.structural_vegetation_min=np.full((16,16),66)
        l.structural_vegetation_max=np.full((16,16),70)
        got=blocked_vegetation(l,np.array([3]*5),np.array([3]*5),np.array([65,66,68,70,71]))
        self.assertEqual(got.tolist(),[False,True,True,True,False])

    def test_native_leaves_in_support_volume_are_removed_but_canopy_above_survives(self):
        l=layers();l.cloud['vegetation'][3,3]=75
        leaf=np.array([(3*16+3)|((y+512)<<22) for y in (67,73)],np.uint64)
        l.cloud.update(leaf_voxels=leaf,leaf_chunk_offsets=np.array([0,2]))
        l.structural_vegetation_min=np.full((16,16),32767,np.int16)
        l.structural_vegetation_max=np.full((16,16),-32768,np.int16)
        l.structural_vegetation_min[3,3]=66;l.structural_vegetation_max[3,3]=70
        renderer=ChunkRenderer(l);arr,bottom=renderer.chunk(0,-1)
        self.assertEqual(renderer.materials[int(arr[3,67-bottom,3])],'air')
        self.assertTrue(renderer.materials[int(arr[3,73-bottom,3])].endswith('_leaves'))

    def test_estimated_tree_trunks_do_not_grow_from_a_timber_return_peak(self):
        l=layers();l.dtm=np.full((16,16),64.);l.cloud['vegetation'][3,3]=75
        l.ee,l.nn=np.indices((16,16));l.audit={'geometry':{}}
        l.structural_vegetation_min=np.full((16,16),32767,np.int16)
        l.structural_vegetation_max=np.full((16,16),-32768,np.int16)
        l.structural_vegetation_min[3,3]=65;l.structural_vegetation_max[3,3]=70
        ParkLayers._trees(l)
        self.assertFalse(any(l.trunks.values()))
        self.assertEqual(l.audit['geometry']['vegetation']['estimated_trunks_rejected_in_structural_columns'],1)


if __name__=='__main__':unittest.main()
