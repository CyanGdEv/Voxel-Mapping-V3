"""Outer-footing recovery and visibly separate diagonal-member planes."""
import unittest
from shapely.geometry import LineString,MultiLineString
from voxel_mapper.dense_trestle import footing_groups,separated_brace,compose_planes
from voxel_mapper import bedrock


class DenseTrestleTests(unittest.TestCase):
    def test_native_cross_lines_include_outer_footing_in_same_frame(self):
        route=LineString([(0,0),(20,0)])
        posts=[{'xy':[10,-1.5],'station_m':10,'symbol_family':'main_row'},
               {'xy':[10,1.5],'station_m':10,'symbol_family':'main_row'},
               {'xy':[10,3.5],'station_m':10,'symbol_family':'outer_brace'}]
        lines=MultiLineString([[(10,-1.5),(10,1.5)],[(10,1.5),(10,3.5)]])
        groups,isolated=footing_groups(route,lines,posts)
        self.assertEqual(len(groups),1);self.assertEqual(len(groups[0]['posts']),3);self.assertFalse(isolated)
        self.assertEqual({tuple(p['xy']) for p in groups[0]['posts']},{(10,-1.5),(10,1.5),(10,3.5)})

    def test_longitudinal_line_does_not_merge_neighbouring_bents(self):
        route=LineString([(0,0),(20,0)])
        posts=[{'xy':[x,y],'station_m':x,'symbol_family':'main_row'} for x in [8,10] for y in [-1.5,1.5]]
        lines=MultiLineString([[(8,-1.5),(8,1.5)],[(10,-1.5),(10,1.5)],[(8,1.5),(10,1.5)]])
        groups,_=footing_groups(route,lines,posts);self.assertEqual(len(groups),2)

    def test_diagonal_plane_is_offset_with_directional_gate_endpoints(self):
        brace=separated_brace((0,10,0),(0,13,3),(1,0))
        self.assertTrue(all(k[0]==1 for k in brace))
        self.assertEqual(brace[1,10,0],'spruce_fence_gate_north')
        self.assertTrue(any(m=='nether_brick_fence' for m in brace.values()))
        self.assertTrue(set(brace.values())<=bedrock.ALLOWED_MATERIALS)
        block=bedrock.material_block('spruce_fence_gate_east')
        self.assertEqual(block.base_name,'fence_gate');self.assertEqual(str(block.properties['facing']),'east')

    def test_global_uprights_take_precedence_without_chopping_diagonals(self):
        straight={(0,10,0):'spruce_fence',(0,11,0):'spruce_fence'}
        colliding={(0,10,0):'nether_brick_fence',(1,10,0):'nether_brick_fence'}
        safe={(2,10,0):'nether_brick_fence',(2,11,0):'nether_brick_fence'}
        result,review=compose_planes(straight,[colliding,safe],{})
        self.assertEqual(result[0,10,0],'spruce_fence')
        self.assertNotIn((1,10,0),result)
        self.assertIn((2,10,0),result)
        self.assertEqual(review['straight_diagonal_cell_overlap'],0)
        self.assertEqual(review['diagonal_members_held_for_global_separation'],1)


if __name__=='__main__':unittest.main()
