from pathlib import Path
import tempfile
import unittest
from voxel_mapper.shop_study import plan,run
from voxel_mapper.bedrock import material_block

MODEL=Path(__file__).resolve().parents[1]/'evidence/wicker-shop-projection-model.json'
SHA='4beebc02761e1e694468cc94aa8e013d8036987b14a7138cc4e4e681c36b02b1'

class ShopWallDetailTests(unittest.TestCase):
    def test_details_are_additive_anchored_to_solid_walls_and_keep_doors(self):
        base,_=plan(MODEL,SHA,1,True,True,True)
        rows,r=plan(MODEL,SHA,1,True,True,True,True)
        cells={(p['x'],p['y'],p['z']):p['material'] for p in rows if p['kind']=='study_surface'}
        for p in base:
            if p['kind']=='study_surface':self.assertEqual(cells[p['x'],p['y'],p['z']],p['material'])
        detail=r['wall_detail_audit'];self.assertGreater(detail['material_counts']['dark_oak_fence'],0)
        self.assertEqual({p['edge'] for p in detail['placements']},{0,1,2,3})
        for p in detail['placements']:
            self.assertEqual(cells[tuple(p['wall_anchor_local_xyz'])],'spruce_planks')
        self.assertTrue(all(o['all_centre_samples_air'] for o in r['opening_centre_sample_audit']))

    def test_vertical_trapdoor_states_and_native_round_trip(self):
        for d in ('north','east','south','west'):
            block=material_block('spruce_trapdoor_'+d)
            self.assertEqual(str(block.properties['open']),'true')
            self.assertEqual(str(block.properties['facing']),d)
        with tempfile.TemporaryDirectory() as d:
            r=run(MODEL,SHA,Path(d)/'study',1,True,True,True,True)
            self.assertEqual(r['world']['round_trip_validation'],'all written blocks and all unwritten air cells verified')
