"""Reference slab deck must not regrow the rejected support lattice."""
import unittest
from shapely.geometry import LineString
from voxel_mapper.timber_track_world import sample_reference_deck, running_connectivity
from voxel_mapper.bedrock import ALLOWED_MATERIALS, material_block


class TrackOnlyReferenceTests(unittest.TestCase):
    def test_only_slabs_edge_fences_and_outward_trapdoors(self):
        line=LineString([(0,0),(20,0)])
        controls=[{'station_m':0,'height_m':25},{'station_m':20,'height_m':20}]
        blocks,deck,head,samples=sample_reference_deck(line,controls)
        self.assertTrue(set(blocks.values())<=ALLOWED_MATERIALS)
        self.assertTrue(all('_slab' in m or m=='oak_fence' or m.startswith('oak_trapdoor_') for m in blocks.values()))
        self.assertFalse(set(blocks)&head)
        self.assertTrue(set(deck)<=set(blocks))
        self.assertTrue(any(m=='spruce_slab' for m in deck.values()))
        self.assertTrue(any(m=='oak_fence' for m in blocks.values()))
        doors=[(k,m) for k,m in blocks.items() if '_trapdoor_' in m]
        self.assertTrue(doors)
        for (x,h,y),m in doors:
            self.assertNotIn((x,y),{(a,c) for a,b,c in deck})
            block=material_block(m)
            self.assertEqual(str(block.properties['open']),'true')
        self.assertTrue(running_connectivity(deck)['all_running_columns_cardinally_connected'])
        for (x,h,y),m in blocks.items():
            if m=='oak_fence':self.assertIn((x,h-1,y),deck)

    def test_tight_diagonal_curve_keeps_running_middle_clear(self):
        line=LineString([(0,0),(8,8),(15,8),(20,3)])
        controls=[{'station_m':0,'height_m':20},{'station_m':line.length,'height_m':23}]
        blocks,deck,head,_=sample_reference_deck(line,controls)
        self.assertFalse(set(blocks)&head)
        self.assertEqual(len(deck),len({(x,y) for x,h,y in deck}))
        self.assertTrue(running_connectivity(deck)['all_running_columns_cardinally_connected'])


if __name__=='__main__':unittest.main()
