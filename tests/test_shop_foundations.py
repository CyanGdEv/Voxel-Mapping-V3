import unittest
from voxel_mapper.shop_foundations import level_pad


class ShopFoundationTests(unittest.TestCase):
    def model(self):
        return {'outer_wall_base_outline':[[0,0,0],[3,0,0],[3,2,0],[0,2,0]]}

    def test_level_floor_and_posts_contact_variable_terrain_without_door_fill(self):
        cells = {(0,0,0):'spruce_planks',(3,0,0):'dark_oak_fence'}
        def ground(x,z): return 6.9 if x<2 else 9.2
        fill,report = level_pad(self.model(),cells,[0,0],10,ground)
        self.assertEqual(report['footprint_columns'],7)
        self.assertEqual(report['maximum_fill_depth_blocks'],3)
        self.assertTrue(report['continuous_terrain_contact'])
        self.assertEqual(report['terrain_excavation_cells'],0)
        for x,z in [(x,z) for x in range(3) for z in range(2)]+[(3,0)]:
            g=int(ground(x+.5,z+.5))-10
            for y in range(g+1,0):
                self.assertIn((x,y,z),fill)
            if g<-1:self.assertEqual(fill[x,-1,z],'spruce_planks')
        self.assertEqual(fill[0,-3,0],'stone')
        self.assertFalse(any(y>=0 for x,y,z in fill))
        self.assertEqual(cells,{(0,0,0):'spruce_planks',(3,0,0):'dark_oak_fence'})

    def test_missing_high_or_excessively_deep_terrain_is_rejected(self):
        for value,message in [(None,'coverage'),(float('nan'),'coverage'),(10.,'grading'),(-10.,'depth')]:
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,message):
                level_pad(self.model(),{},[0,0],10,lambda x,z:value)
