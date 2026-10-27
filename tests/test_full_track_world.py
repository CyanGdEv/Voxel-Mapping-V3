"""Full route closure, layered crossings and bounded park modifications."""
import unittest
from concurrent.futures import CancelledError
from shapely.geometry import LineString, Polygon, mapping
from voxel_mapper import full_track_world as world


class FullTrackTests(unittest.TestCase):
    def test_closure_is_explicit_and_preserves_source_controls(self):
        line=LineString([(0,0),(10,0),(10,10),(0,1)])
        controls=[{'label':'HP1','station_m':20,'height_m':30}]
        profile={'max_closure_gap_m':2,'station_display_top_m':20,'estimated_lift_start_station_m':5}
        route,c,receipt=world.complete_route(line,controls,profile)
        self.assertTrue(route.is_ring)
        self.assertEqual(receipt['drafting_gap_closed_m'],1)
        self.assertIn(controls[0],c)
        self.assertEqual(c[0]['height_m'],c[-1]['height_m'])
        with self.assertRaises(ValueError):world.complete_route(line,controls,{**profile,'max_closure_gap_m':.5})

    def test_overpass_keeps_both_decks_in_same_xy_column(self):
        route=LineString([(-10,0),(10,0),(10,10),(0,10),(0,-10)])
        controls=[{'station_m':0,'height_m':10},{'station_m':20,'height_m':10},{'station_m':35,'height_m':20},{'station_m':route.length,'height_m':20}]
        blocks,core,head,samples,review=world.sample_route(route,controls)
        self.assertIn((0,9,0),core);self.assertIn((0,19,0),core)
        self.assertFalse(set(blocks)&head)
        self.assertEqual(review['supports_constructed'],0)
        self.assertTrue(all('_slab' in m or m=='oak_fence' or m.startswith('oak_trapdoor_') for m in blocks.values()))
        with self.assertRaises(CancelledError):world.sample_route(route,controls,lambda:True)

    def test_crossing_with_insufficient_height_refuses_export(self):
        route=LineString([(-10,0),(10,0),(10,10),(0,10),(0,-10)])
        controls=[{'station_m':0,'height_m':10},{'station_m':20,'height_m':10},{'station_m':35,'height_m':12},{'station_m':route.length,'height_m':12}]
        with self.assertRaisesRegex(ValueError,'deck collision'):world.sample_route(route,controls)

    def test_cut_receipts_preserve_original_rows_and_limit_excavation(self):
        terrain={(0,0):{'x':0,'y':20,'z':1,'kind':'terrain','material':'grass_block'}}
        polygon=mapping(Polygon([(-2,-2),(2,-2),(2,2),(-2,2)]))
        base={'parts':[],'maintenance':{'wall_geometry_nominal_local':polygon}}
        blocks={(0,18,0):'oak_slab_top'};head={(0,19,0),(0,20,0),(0,21,0)}
        ground,old,cuts,removed=world.prepare_park(terrain,{(0,19,0):'spruce_planks'},blocks,blocks,head,{'max_terrain_cut_m':3,'max_structure_removals':2},base)
        self.assertEqual(ground[0,0]['y'],17);self.assertEqual(terrain[0,0]['y'],20)
        self.assertEqual(cuts[0]['old_row'],terrain[0,0]);self.assertEqual(removed[0]['material'],'spruce_planks')
        self.assertEqual(old,{})
        with self.assertRaisesRegex(ValueError,'terrain budget'):
            world.prepare_park(terrain,{},blocks,blocks,head,{'max_terrain_cut_m':2,'max_structure_removals':2},base)
        with self.assertRaisesRegex(ValueError,'protected park'):
            world.prepare_park(terrain,{(0,19,0):'spruce_planks'},blocks,blocks,head,{'max_terrain_cut_m':3,'max_structure_removals':2},{**base,'parts':[],'maintenance':{'wall_geometry_nominal_local':mapping(Polygon([(10,10),(12,10),(12,12),(10,12)]))}})

    def test_opt_in_and_cancellation_do_not_create_output(self):
        with self.assertRaises(ValueError):world.run('missing','missing','missing','missing')
        with self.assertRaises(CancelledError):world.run('missing','missing','missing','missing',allow_provisional=True,cancelled=lambda:True)


if __name__=='__main__':unittest.main()
