"""Grounded, connected X-braced frames that preserve existing clearances."""
import unittest
from voxel_mapper import fence_support_world as support, bedrock


class FenceSupportTests(unittest.TestCase):
    def fixture(self):
        terrain={(x,y):{'y':10,'material':'grass_block'} for x in range(-4,5) for y in range(-5,6)}
        track={(0,19,y):'oak_slab_top' for y in [-1,0,1]}
        pair={'station_m':10,'posts':[{'xy':[0,-2]},{'xy':[0,2]}]}
        samples=[{'station_m':10,'cells_xy':[(0,-1),(0,0),(0,1)]}]
        return terrain,track,pair,samples,[[0,19,0]]

    def test_diagonal_voxels_form_a_continuous_cardinal_path(self):
        points=support.staircase_line((0,0,0),(5,4,3))
        self.assertEqual(points[0],(0,0,0));self.assertEqual(points[-1],(5,4,3))
        self.assertTrue(all(sum(abs(a-b) for a,b in zip(p,q))==1 for p,q in zip(points,points[1:])))
        self.assertTrue(all(type(v) is int for p in points for v in p))

    def test_source_posts_have_continuous_fence_uprights_crossbeams_and_x_braces(self):
        terrain,track,pair,samples,keys=self.fixture()
        blocks,r,reason=support.make_bent(pair,support.deck_intervals(track),terrain,samples,keys,track,{})
        self.assertIsNone(reason)
        self.assertTrue({'oak_fence','spruce_fence','nether_brick_fence'}<=set(blocks.values()))
        for y in [-2,2]:
            for h in range(11,r['beam_height']+1):self.assertEqual(blocks[0,h,y],'spruce_fence')
        self.assertGreaterEqual(r['beam_height']+1.5,r['deck_underside_m'])
        support.add_caps(blocks,r,terrain,track,set(),set())
        self.assertTrue(any('trapdoor' in m for m in blocks.values()))
        support.validate_connected(blocks,[(0,11,-2),(0,11,2)],(0,r['beam_height'],0))
        self.assertTrue(set(blocks.values())<=bedrock.ALLOWED_MATERIALS)

    def test_paving_and_low_clearance_do_not_trigger_unmeasured_post_shifts(self):
        terrain,track,pair,samples,keys=self.fixture();terrain[0,-2]['material']='stone_bricks'
        self.assertEqual(support.make_bent(pair,support.deck_intervals(track),terrain,samples,keys,track,{})[2],'post_on_paving_or_other_land_use')
        terrain[0,-2]['material']='grass_block';terrain[0,-2]['y']=19
        self.assertEqual(support.make_bent(pair,support.deck_intervals(track),terrain,samples,keys,track,{})[2],'ground_borne_or_insufficient_fence_clearance')

    def test_fence_extension_above_its_cell_cannot_intrude_in_headroom(self):
        terrain,track,_,_,_=self.fixture()
        self.assertEqual(support.conflict({(0,14,0):'spruce_fence'},terrain,{}, {(0,15,0)},set()),'track_headroom')
        self.assertEqual(support.conflict({(0,14,0):'oak_fence'},terrain,{},set(),{(0,15,0)}),'pedestrian_clearance')
        self.assertEqual(support.conflict({(0,14,0):'spruce_fence'},terrain,{(0,14,0):'stone'},set(),set()),'retained_geometry')

    def test_nether_brick_fence_uses_correct_universal_material(self):
        block=bedrock.material_block('nether_brick_fence')
        self.assertEqual(block.base_name,'fence')
        self.assertEqual(str(block.properties['material']),'nether_brick')


if __name__=='__main__':unittest.main()
