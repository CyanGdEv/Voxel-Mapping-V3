import unittest
from shapely.geometry import box, Point
from voxel_mapper.reconstruction.rocks import rock_cells, ROCK_TYPES
from voxel_mapper.bedrock import material_block

class RockTests(unittest.TestCase):
    def test_jagged_recipe_uses_all_forms_and_stays_in_footprint(self):
        footprint = box(-5,-5,6,6)
        cells, report = rock_cells(footprint, lambda x,z: 100, height_m=4)
        self.assertEqual(set(report['forms']), {'full','slab','stairs','wall'})
        self.assertEqual(sum(report['forms'].values()), len(cells))
        self.assertEqual(cells, rock_cells(footprint, lambda x,z:100, height_m=4)[0])
        for (x,y,z), material in cells.items():
            self.assertTrue(footprint.covers(Point(x+.5,z+.5)))
            self.assertTrue(101 <= y <= 104)
            material_block(material)
            if material.endswith('_wall'):
                self.assertEqual(cells[x,y-1,z], 'stone')
        self.assertFalse(report['lithology_verified'])

    def test_layered_and_granite_recipes_are_distinct(self):
        for recipe in ROCK_TYPES:
            cells, report = rock_cells(box(0,0,8,8), lambda x,z:100, recipe, 3)
            self.assertTrue(cells)
            self.assertEqual(report['rock_type'], recipe)
            for material in cells.values():
                material_block(material)
            if recipe == 'layered_sandstone':
                self.assertNotIn('wall', report['forms'])
                self.assertTrue(all(m.startswith('sandstone') for m in cells.values()))
            if recipe == 'weathered_granite':
                self.assertTrue(all(m.startswith('granite') for m in cells.values()))

    def test_missing_ground_and_unbounded_estimates_fail(self):
        for height in (0,9,float('nan')):
            with self.assertRaises(ValueError):
                rock_cells(box(0,0,2,2), lambda x,z:100, height_m=height)
        with self.assertRaises(ValueError):
            rock_cells(box(0,0,2,2), lambda x,z:None)
        with self.assertRaises(ValueError):
            rock_cells(box(0,0,2,2), lambda x,z:100, 'unknown')
