"""Coordinated decks preserve geometry while maintaining walkable air."""
from pathlib import Path
import copy
import tempfile
import unittest
from shapely.geometry import box,LineString
from voxel_mapper import preshow_revision as revision


class PreshowRevisionTests(unittest.TestCase):
    def test_lower_gaps_remove_only_two_air_levels_on_bound_wall_columns(self):
        boundary={(x,y) for x in [0,4] for y in range(5)}
        blocks={(x,h,y):'stone_bricks' for x,y in boundary for h in range(178,183)}
        air,receipts=revision.lower_openings({'gaps':[LineString([(0,1),(0,3)]),LineString([(4,1),(4,3)])]},boundary,178,blocks)
        self.assertEqual(len(receipts),2);self.assertEqual({h for x,h,y in air},{178,179})
        self.assertTrue(all(p not in blocks for p in air))
        self.assertTrue(all((x,180,y) in blocks for x,h,y in air))
        self.assertEqual(blocks[0,178,4],'stone_bricks')

    def test_source_queue_polygon_and_blocked_shop_alias_are_both_retained(self):
        terrain={(x,y):{'y':7} for x in range(-1,9) for y in range(-1,6)}
        structures={(0,9,y):'stone_bricks' for y in [1,2]};protected={(2,1)}
        polygon=box(1,1,6,3);before=copy.deepcopy((terrain,structures))
        added,cells,r=revision.queue_deck({'queue':polygon},terrain,structures,{(0,1),(0,2)},protected,10)
        self.assertEqual((terrain,structures),before)
        self.assertEqual(r['requested_centre_cells'],10)
        self.assertTrue(any(p['source_cell_xy']==[2,1] for p in r['preserved_geometry_aliases']))
        self.assertFalse(any((x,y) in protected for x,h,y in added))
        self.assertEqual(r['source_area_m2'],polygon.area)
        self.assertLessEqual(r['maximum_connector_distance_from_source_m'],.75)
        self.assertTrue(all(h<10 for x,h,y in added))

    def test_relocated_gate_reaches_original_paving_with_half_steps(self):
        terrain={(x,0):{'y':7} for x in range(-8,2)}
        structures={(0,9,0):'stone_bricks'}
        added,r=revision.ground_connection({(0,0)},{(0,0)},terrain,structures,set(),10,{(-4,0)},lambda:False)
        self.assertTrue(r['ground_to_upper_floor_connected'])
        self.assertLessEqual(r['maximum_neighbour_rise_m'],.5)
        self.assertGreater(len(added),0)

    def test_narrow_queue_fences_stay_outside_walkway_and_ground_link(self):
        columns={(x,0) for x in range(1,5)};terrain={(x,y):{'y':7} for x in range(7) for y in range(-2,3)}
        route={'surfaces':[{'source_cell_xy':[0,0],'walking_top_m':10}]}
        added,r=revision.side_fences(columns,columns,terrain,{},set(),10,route)
        self.assertGreater(r['oak_fence_columns'],0)
        self.assertFalse(any((x,y) in columns|{(0,0)} for x,h,y in added))
        self.assertEqual({m for (x,h,y),m in added.items() if h==10},{'oak_fence'})

    def test_changed_alignment_receipt_is_rejected_before_geometry(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'review.json';p.write_text('{}')
            with self.assertRaises(ValueError):revision.layout_revision([],{},p)

    def test_every_queue_cell_requires_cardinal_connection_and_headroom(self):
        upper={(x,0) for x in range(5)};queue={(3,0),(4,0)}
        flight={'ordered_route_xy':[[4,0],[5,0]]}
        r=revision.circulation_check(upper,queue,{},10,{(0,0)},flight)
        self.assertTrue(r['all_queue_cells_connected_to_preshow'])
        with self.assertRaises(ValueError):revision.circulation_check(upper,queue,{(2,10,0):'stone_bricks'},10,{(0,0)},flight)


if __name__=='__main__':unittest.main()
