"""Access must meet retained paving with half-step movement and clear headroom."""
from concurrent.futures import CancelledError
import copy
import unittest

from voxel_mapper.station_access import paving_approach


class StationAccessTests(unittest.TestCase):
    def scene(self):
        terrain={(x,0):{'y':7} for x in range(-6,1)}
        structures={(0,9,0):'stone_bricks'}
        return {'columns_xy':[[0,0]],'id':'entry'},terrain,structures

    def test_actual_paving_contact_half_steps_and_preservation(self):
        opening,terrain,structures=self.scene();before=copy.deepcopy((terrain,structures))
        added,r=paving_approach(opening,10,terrain,structures,set(),{(0,0)},{(-4,0)})
        self.assertEqual((terrain,structures),before)
        self.assertTrue(r['ground_to_upper_floor_connected'])
        self.assertEqual(r['retained_source_paving_endpoint_xy'],[-4,0])
        self.assertEqual(r['endpoint_ground_walking_top_m'],8)
        self.assertEqual(r['maximum_neighbour_rise_m'],.5)
        self.assertEqual(r['terrain_excavations'],0)
        self.assertFalse(r['queue_alignment_verified'])
        self.assertTrue(any(m=='stone_brick_slab' for m in added.values()))
        self.assertFalse(set(added)&set(structures))
        surfaces={tuple(p['source_cell_xy']):p['walking_top_m'] for p in r['surfaces']}
        for a,b in zip(r['ordered_route_xy'],r['ordered_route_xy'][1:]):
            self.assertEqual(sum(abs(x-y) for x,y in zip(a,b)),1)
            self.assertLessEqual(abs(surfaces[tuple(a)]-surfaces[tuple(b)]),.5)

    def test_protected_columns_and_blocked_headroom_withhold_route(self):
        opening,terrain,structures=self.scene()
        for protected,obstacles in [({(-2,0)},{}),(set(),{(-2,9,0):'spruce_planks'}),
                                     (set(),{(-4,8,0):'oak_fence'})]:
            added,r=paving_approach(opening,10,terrain,{**structures,**obstacles},protected,{(0,0)},{(-4,0)})
            self.assertEqual(added,{})
            self.assertFalse(r.get('ground_to_upper_floor_connected',False))

    def test_ground_is_not_automatically_a_paving_target(self):
        opening,terrain,structures=self.scene()
        added,r=paving_approach(opening,10,terrain,structures,set(),{(0,0)},set())
        self.assertEqual(added,{})
        self.assertEqual(r['status'],'withheld_no_preserved_paving_connection')

    def test_budget_and_cancellation_fail_without_partial_geometry(self):
        opening,terrain,structures=self.scene()
        with self.assertRaises(CancelledError):
            paving_approach(opening,10,terrain,structures,set(),{(0,0)},{(-4,0)},cancelled=lambda:True)
        added,r=paving_approach(opening,10,terrain,structures,set(),{(0,0)},{(-4,0)},max_states=1)
        self.assertEqual(added,{})
        self.assertEqual(r['status'],'withheld_access_search_budget')


if __name__=='__main__':unittest.main()
