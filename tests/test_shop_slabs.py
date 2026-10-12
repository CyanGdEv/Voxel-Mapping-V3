import json
from pathlib import Path
import tempfile
import unittest
from voxel_mapper.shop_slabs import occupied_halves
from voxel_mapper.shop_study import plan,run

MODEL=Path(__file__).resolve().parents[1]/'evidence/wicker-shop-projection-model.json'
SHA='4beebc02761e1e694468cc94aa8e013d8036987b14a7138cc4e4e681c36b02b1'

class ShopSlabTests(unittest.TestCase):
    def test_native_half_occupancy_handles_negative_coordinates_and_top_bottom(self):
        bottom=occupied_halves({(-1,2,0):'dark_oak_slab'})
        top=occupied_halves({(-1,2,0):'dark_oak_slab_top'})
        self.assertEqual(len(bottom),4);self.assertEqual(len(top),4)
        self.assertEqual({p[1] for p in bottom},{4});self.assertEqual({p[1] for p in top},{5})
        self.assertFalse(bottom&top)
        self.assertEqual(bottom|top,occupied_halves({(-1,2,0):'dark_oak_planks'}))

    def test_only_one_to_one_shapes_remain_closed_and_doors_clear(self):
        rows,r=plan(MODEL,SHA,1,True,True,True)
        counts=r['slab_shape_audit']['material_counts']
        self.assertGreater(counts['dark_oak_slab'],0);self.assertGreater(counts['dark_oak_slab_top'],0)
        self.assertFalse(r['slab_shape_audit']['native_shape_leak_audit']['interior_reached_from_exterior'])
        self.assertTrue(r['slab_shape_audit']['door_air_verified'])
        self.assertEqual(r['model_blocks_per_source_metre'],1)
        with self.assertRaises(ValueError):plan(MODEL,SHA,4,True,True,True)

    def test_slab_states_survive_native_cold_reopen(self):
        with tempfile.TemporaryDirectory() as d:
            r=run(MODEL,SHA,Path(d)/'study',1,True,True,True)
            self.assertEqual(r['world']['round_trip_validation'],'all written blocks and all unwritten air cells verified')
