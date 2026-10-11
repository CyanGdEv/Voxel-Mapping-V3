import unittest
from shapely.geometry import Polygon
from voxel_mapper.wing_shell_study import solid
from voxel_mapper.slab_roof_study import convert
from voxel_mapper.wing_block_shapes import occupied_halves


class SlabRoofTests(unittest.TestCase):
    def test_bottom_top_courses_seal_risers_preserve_walls_and_passage(self):
        mesh=solid(Polygon([(0,3),(3,4.5),(3,4.25),(0,2.75)]),1,0,2)
        m={'components':[{'id':'roof_shell','mesh':mesh}], 'assumptions':[],
           'slab_conversion_passages':[{'native_columns':[(1,0)]}]}
        cells={(x,3,0):'dark_oak_stairs_east' for x in range(3)}
        cells[(0,0,0)]='stone_bricks';cells[(0,-1,0)]='stone_bricks'
        model,output,audit=convert(m,cells)
        self.assertTrue(audit['non_roof_cells_unchanged'])
        self.assertEqual(output[0,0,0],'stone_bricks')
        self.assertEqual(output[0,-1,0],'stone_bricks')
        self.assertFalse(any('stairs' in v for v in output.values()))
        self.assertEqual(model['native_roof_style'],'slabs')
        self.assertTrue(any(v=='dark_oak_slab_top' for v in output.values()))
        self.assertTrue(any(v=='dark_oak_slab' for v in output.values()))
        occ=occupied_halves(output)
        # Each new adjacent roof column shares occupied height with its neighbour.
        levels=[{y for x,y,z in occ if x==2*col and z==0 and y>=4} for col in range(3)]
        self.assertTrue(all(a&b for a,b in zip(levels,levels[1:])))

    def test_uncovered_wooden_roof_rejects(self):
        m={'components':[],'assumptions':[]}
        with self.assertRaisesRegex(ValueError,'outside source'):convert(m,{(1,3,1):'dark_oak_stairs_north'})

    def test_retained_stone_slab_edge_sealed_without_replacing_stone(self):
        mesh=solid(Polygon([(0,3.5),(2,2.5),(2,2.25),(0,3.25)]),1,0,1)
        model={'components':[{'id':'roof_shell','mesh':mesh}],'assumptions':[]}
        cells={(0,3,0):'dark_oak_stairs_west',(1,2,0):'dark_oak_stairs_west',(0,2,0):'stone_brick_slab'}
        _,output,audit=convert(model,cells)
        self.assertEqual(output[0,2,0],'stone_brick_slab')
        self.assertEqual(len(audit['masonry_edge_seal_repairs']),1)
        self.assertEqual(output[1,3,0],'dark_oak_slab')


if __name__=='__main__':unittest.main()
