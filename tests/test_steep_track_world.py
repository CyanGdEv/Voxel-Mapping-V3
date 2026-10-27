"""Solid steep steps preserve top elevations and existing clearance."""
import unittest
from voxel_mapper import steep_track_world as world


class SteepDeckTests(unittest.TestCase):
    profile={'minimum_steep_rise_m':1,'sample_padding':0,'max_changes':100}
    def fixture(self,half=False,gentle=False):
        a=(0,9,0);b=(1,10,0)
        core={a:'oak_slab' if half else 'oak_slab_top',b:'spruce_slab' if half else 'spruce_slab_top'}
        if gentle:core[b]='spruce_slab'
        ground={(0,0):{'y':5},(1,0):{'y':5}}
        samples=[{'station_m':0,'cells_xy':[(0,0)]},{'station_m':1,'cells_xy':[(1,0)]}]
        return core,ground,samples,[list(a),list(b)]

    def test_whole_height_steep_steps_become_matching_full_blocks(self):
        core,ground,samples,keys=self.fixture()
        track,new,changes,r=world.thicken(core,core,ground,set(),samples,keys,self.profile)
        self.assertEqual(set(changes.values()),{'oak_planks','spruce_planks'})
        self.assertEqual(len(r['thickened_deck_cells']),2)
        for k,m in core.items():self.assertEqual(world.surface_top(k,m),world.surface_top(k,new[k]))

    def test_half_height_steps_get_two_touching_half_slabs_without_raising_top(self):
        core,ground,samples,keys=self.fixture(half=True)
        track,new,changes,r=world.thicken(core,core,ground,set(),samples,keys,self.profile)
        self.assertEqual(changes,{(0,8,0):'oak_slab_top',(1,9,0):'spruce_slab_top'})
        self.assertEqual(new,core)
        self.assertTrue(all(p['kind']=='paired_half_slabs' for p in r['thickened_deck_cells']))

    def test_half_block_gentle_rise_keeps_slabs(self):
        core,ground,samples,keys=self.fixture(gentle=True)
        _,new,changes,r=world.thicken(core,core,ground,set(),samples,keys,self.profile)
        self.assertEqual(changes,{})
        self.assertEqual(new,core)

    def test_steep_outer_edge_is_detected_even_when_centre_is_level(self):
        core,ground,samples,keys=self.fixture()
        core[(1,10,0)]='spruce_slab_top'
        # Centre stays on the same flat sample; only the lateral edge rises.
        keys=[keys[0],keys[0]]
        _,_,changes,r=world.thicken(core,core,ground,set(),samples,keys,self.profile)
        self.assertIn((1,10,0),changes)
        self.assertTrue(r['steep_edge_pairs'])

    def test_underdeck_fill_cannot_overwrite_ground_geometry_or_lower_headroom(self):
        core,ground,samples,keys=self.fixture(half=True)
        occupied={**core,(0,8,0):'stone_bricks'}
        _,_,changes,r=world.thicken(core,occupied,ground,{(1,9,0)},samples,keys,self.profile)
        self.assertFalse(changes)
        self.assertEqual({p['reason'] for p in r['withheld_deck_cells']},{'existing_geometry','lower_track_headroom'})
        ground[0,0]['y']=8
        _,_,changes,r=world.thicken(core,core,ground,set(),samples,keys,self.profile)
        self.assertNotIn((0,8,0),changes)
        self.assertTrue(any(p['reason']=='retained_terrain' for p in r['withheld_deck_cells']))


if __name__=='__main__':unittest.main()
