import unittest
from shapely.geometry import box
from voxel_mapper.reconstruction.replacement import compose_replacement
from voxel_mapper.bedrock import material_block


class PlaceholderReplacementTests(unittest.TestCase):
    def test_restores_surface_and_preserves_unreviewed_neighbours(self):
        existing={(0,10,0):'stone_bricks',(0,11,0):'stone_bricks',
                  (0,12,0):'air',(2,11,0):'stone_bricks',(0,9,0):'dirt'}
        rows,report=compose_replacement(existing,{(0,0):10,(2,0):10},box(0,0,1,1),
            [{'x':0,'y':12,'z':0,'material':'sandstone'}])
        cells={(r['x'],r['y'],r['z']):r['material'] for r in rows}
        self.assertEqual(cells,{(0,10,0):'grass_block',(0,11,0):'air',(0,12,0):'sandstone'})
        self.assertEqual(report['removed_placeholder_cells'],2)

    def test_refuses_collision_outside_reviewed_placeholder(self):
        for solid in ['water','fence','iron_bars','stone_bricks']:
            with self.subTest(solid=solid),self.assertRaisesRegex(ValueError,'collision'):
                compose_replacement({(0,10,0):'stone_bricks',(2,12,0):solid},
                    {(0,0):10,(2,0):10},box(0,0,1,1),
                    [{'x':2,'y':12,'z':0,'material':'sandstone'}])

    def test_refuses_buried_model_and_missing_baseline(self):
        args=({(0,10,0):'stone_bricks',(0,9,0):'dirt'},{(0,0):10},box(0,0,1,1))
        with self.assertRaisesRegex(ValueError,'buried'):
            compose_replacement(*args,[{'x':0,'y':9,'z':0,'material':'sandstone'}])
        with self.assertRaisesRegex(ValueError,'Outside'):
            compose_replacement(*args,[{'x':0,'y':20,'z':0,'material':'sandstone'}])

    def test_sandstone_has_native_roundtrip_variant(self):
        self.assertEqual(str(material_block('sandstone').properties['variant']), 'normal')
