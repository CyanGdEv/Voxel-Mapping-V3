"""Outer-footing recovery and visibly separate diagonal-member planes."""
import unittest
from shapely.geometry import LineString,MultiLineString
from voxel_mapper.dense_trestle import footing_groups,separated_brace,compose_planes,bearing_tie,reference_members
from voxel_mapper import bedrock


class DenseTrestleTests(unittest.TestCase):
    def test_reference_replacement_preserves_feet_and_bearings_without_old_lattice(self):
        straight={(x,h,0):'spruce_fence' for x in [0,4] for h in range(10,19)}
        straight.update({(x,h,0):'oak_fence' for x in range(1,4) for h in [12,15,18]})
        frames=[{'beam_height':18,'post_cells_xy':[[0,0],[4,0]],'base_heights':[10,10],'crossmember_levels':[12,15,18]}]
        result,review=reference_members(straight,frames)
        self.assertEqual(result.keys(),straight.keys())
        self.assertEqual(result[0,10,0],'spruce_fence')
        self.assertEqual(result[0,15,0],'nether_brick_fence')
        self.assertEqual(result[0,18,0],'spruce_fence')
        self.assertEqual(result[2,15,0],'spruce_fence_gate_north')
        self.assertEqual(result[2,18,0],'oak_trapdoor_top')
        self.assertEqual(result[2,12,0],'spruce_trapdoor_top')
        self.assertEqual(review['diagonal_members_placed'],0)
        for material in result.values():
            self.assertIn(material,bedrock.ALLOWED_MATERIALS)
            if 'trapdoor' in material:
                native=bedrock.material_block(material)
                self.assertEqual(str(native.properties['half']),'top')
                self.assertEqual(str(native.properties['open']),'false')

    def test_reference_gate_axis_rotates_with_the_frame(self):
        straight={(0,10,y):'oak_fence' for y in range(5)}
        result,_=reference_members(straight,[])
        self.assertTrue(all(m=='spruce_fence_gate_east' for m in result.values()))

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

    def test_curved_frame_post_gets_a_short_cross_tie_without_moving_footing(self):
        tie=bearing_tie((179,199,54),[(177,199,54),(177,199,55),(178,199,55)])
        self.assertIn((179,199,54),tie)
        self.assertTrue(any(k in tie for k in [(177,199,54),(177,199,55),(178,199,55)]))
        self.assertTrue(all(k[1]==199 for k in tie))
        self.assertFalse(bearing_tie((179,199,54),[(170,199,54)]))


if __name__=='__main__':unittest.main()
