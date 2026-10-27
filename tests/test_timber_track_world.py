"""Source-bound track interpolation, continuous decks and grounded timber posts."""
from concurrent.futures import CancelledError
from pathlib import Path
import tempfile
import unittest
import numpy as np
from shapely.geometry import LineString
from voxel_mapper import timber_track_world as world
from voxel_mapper.bedrock import ALLOWED_MATERIALS


class TimberTrackTests(unittest.TestCase):
    def controls(self):
        return [{'station_m':0,'height_m':24},{'station_m':20,'height_m':20},{'station_m':40,'height_m':22}]

    def test_extrema_are_exact_interpolation_has_no_overshoot_or_extrapolation(self):
        controls=self.controls()
        for r in controls:self.assertEqual(world.height_at(r['station_m'],controls),r['height_m'])
        values=[world.height_at(s,controls) for s in np.linspace(0,40,200)]
        self.assertGreaterEqual(min(values),20);self.assertLessEqual(max(values),24)
        self.assertAlmostEqual(world.height_at(20-.001,controls),20,places=6)
        with self.assertRaises(ValueError):world.height_at(40.01,controls)

    def test_submetre_samples_collapse_to_one_running_surface_per_column(self):
        blocks,core,air,samples=world.sample_deck(LineString([(0,0),(40,0)]),self.controls())
        self.assertEqual(len(core),len({(x,y) for x,h,y in core}))
        self.assertFalse(set(blocks)&air)
        self.assertTrue(set(blocks.values())<=ALLOWED_MATERIALS)
        self.assertTrue(any(m=='dark_oak_slab' for m in core.values()))
        self.assertTrue(any(m=='oak_fence' for m in blocks.values()))

    def test_source_footings_on_track_guides_preserve_ground_and_have_full_posts(self):
        controls=self.controls();line=LineString([(0,0),(40,0)])
        pair={'station_m':10,'posts':[{'xy':[10,-2]},{'xy':[10,2]}]}
        terrain={(x,y):{'y':10,'material':'blue_wool'} for x in range(8,13) for y in range(-4,5)}
        blocks,reason=world.support_bent(pair,line,controls,terrain)
        self.assertIsNone(reason)
        self.assertEqual(terrain[10,-2]['material'],'blue_wool')
        beam=int(np.ceil(round(2*world.height_at(10,controls))/2))-2
        for y in [-2,2]:
            self.assertEqual(blocks[10,11,y],'stone_bricks')
            for h in range(12,beam+1):self.assertIn(blocks[10,h,y],['oak_log','oak_log_x','oak_log_z','oak_fence'])
        self.assertTrue(any('trapdoor' in m for m in blocks.values()))

    def test_post_on_actual_paving_is_withheld_instead_of_excavated(self):
        pair={'station_m':10,'posts':[{'xy':[10,-2]},{'xy':[10,2]}]}
        terrain={(10,-2):{'y':10,'material':'stone_bricks'},(10,2):{'y':10,'material':'grass_block'}}
        blocks,reason=world.support_bent(pair,LineString([(0,0),(40,0)]),self.controls(),terrain)
        self.assertEqual(blocks,{})
        self.assertEqual(reason,'source_post_over_retained_paving_or_other_land_use')

    def test_opt_in_cancel_and_fresh_output_prevent_partial_world(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'world'
            with self.assertRaises(ValueError):world.run('missing','missing','missing',out)
            with self.assertRaises(CancelledError):world.run('missing','missing','missing',out,allow_provisional=True,cancelled=lambda:True)
            self.assertFalse(out.exists())

    def test_running_strip_rejects_diagonal_only_contact(self):
        with self.assertRaises(ValueError):world.running_connectivity({(0,10,0):'dark_oak_planks',(1,10,1):'dark_oak_planks'})
        r=world.running_connectivity({(0,10,0):'dark_oak_planks',(1,10,0):'dark_oak_planks'})
        self.assertTrue(r['all_running_columns_cardinally_connected'])


if __name__=='__main__':unittest.main()
