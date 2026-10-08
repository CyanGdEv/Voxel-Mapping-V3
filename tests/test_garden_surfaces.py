import unittest
from voxel_mapper.reconstruction.garden_surfaces import barrier_material,walking_block,barrier_column
from voxel_mapper.bedrock import material_block

class GardenSurfacesTests(unittest.TestCase):
 def test_colour(self):
  self.assertEqual(barrier_material('RAL6008'),'green_stained_glass_pane')
  self.assertEqual(barrier_material('dark green'),'green_stained_glass_pane')
  self.assertEqual(barrier_material(None),'iron_bars')
 def test_walk_top(self):
  self.assertEqual(walking_block(10,0,1,0),(9,'stone'))
  self.assertEqual(walking_block(10.5,.1,1,0),(10,'stone_slab'))
  self.assertEqual(walking_block(10,.1,1,0),(9,'stone_slab_top'))
 def test_stairs_faces_uphill_in_world_axes(self):
  self.assertEqual(walking_block(10,.6,0,1)[1],'stone_stairs_north')
  self.assertEqual(walking_block(10,-.6,0,1)[1],'stone_stairs_south')
  self.assertEqual(walking_block(10,.6,1,0)[1],'stone_stairs_east')
 def test_guardrails_grounded(self):
  cells=barrier_column(1,2,10.5,'green')
  self.assertEqual({y for x,y,z in cells},{11})
 def test_finite_and_budget(self):
  with self.assertRaises(ValueError):walking_block(float('nan'),0,1,0)
  with self.assertRaises(ValueError):barrier_column(1,2,10,height_m=30)
 def test_new_native_forms(self):
  import PyMCTranslate
  manager=PyMCTranslate.new_translation_manager();version=manager.get_version('bedrock',(1,21,130))
  for name in ['green_stained_glass','green_stained_glass_pane','iron_bars','stone_brick_slab','sandstone_slab_top','brick_stairs_west','stone_stairs_north']:
   universal=material_block(name)
   native,_,_=version.block.from_universal(universal)
   from amulet.api.block import Block
   back,_,_=version.block.to_universal(native,get_block_callback=lambda loc:(Block('minecraft','air'),None))
   self.assertEqual(universal,back,name)
