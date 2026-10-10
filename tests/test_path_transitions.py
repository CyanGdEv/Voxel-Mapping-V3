import unittest
from voxel_mapper.reconstruction.garden_surfaces import path_transitions
class PathTransitionsTests(unittest.TestCase):
 def field(self,heights):return {(i,0):{'top':h,'family':'stone_brick','tangent':(1,0)} for i,h in enumerate(heights)}
 def test_isolated_rise_adds_slab_on_actual_lower_path(self):
  cells=path_transitions(self.field([10,10,11,11]));self.assertEqual(cells[(1,0)]['y'],10);self.assertEqual(cells[(1,0)]['material'],'stone_brick_slab');self.assertEqual(set(cells),{(1,0)})
 def test_stair_run_and_terminal_landing_follow_route(self):
  cells=path_transitions(self.field([10,11,12,13]));self.assertEqual(set(cells),{(0,0),(1,0),(2,0),(3,0)})
  self.assertEqual(cells[(0,0)]['material'],'stone_brick_slab')
  self.assertTrue(all(cells[(i,0)]['material']=='stone_brick_stairs_east' for i in range(1,4)))
  self.assertEqual([cells[(i,0)]['y'] for i in range(4)],[10,10,11,12])
 def test_descending_stairs_still_face_uphill(self):
  cells=path_transitions(self.field([13,12,11,10]));self.assertEqual(cells[(3,0)]['material'],'stone_brick_slab');self.assertTrue(all(cells[(i,0)]['material']=='stone_brick_stairs_west' for i in range(3)))
 def test_no_separate_strip_or_gap_bridging(self):
  field=self.field([10,10,11,11]);del field[(2,0)];self.assertFalse(path_transitions(field))
 def test_half_step_and_flat_untouched(self):
  self.assertFalse(path_transitions(self.field([10,10.5,11,11])))
 def test_cross_slope_does_not_rotate_stairs_off_route(self):
  f=self.field([10,10]);f[(0,1)]={'top':11,'family':'stone_brick','tangent':(1,0)};self.assertFalse(path_transitions(f))

 def test_existing_partial_blocks_are_not_stacked(self):
  f=self.field([10,10,11,11]);f[(1,0)]['partial']=True;self.assertFalse(path_transitions(f))
