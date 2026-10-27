"""Conditional multi-part shells retain slab shapes and explicit access holds."""
from concurrent.futures import CancelledError
import copy
from pathlib import Path
import tempfile
import unittest
import numpy as np
from shapely.geometry import LineString,mapping
from voxel_mapper import planning_station_preshow_world as world
from voxel_mapper.wicker_building_models import rectangular_model


class StationPreshowTests(unittest.TestCase):
    def test_gable_and_pyramid_native_shapes_close_without_full_roof_blocks(self):
        matrix=np.array([[.8,-.6],[.6,.8]])
        for form in ['gable','pyramid']:
            model=rectangular_model(8,10,3,5,form,[('z-',0,2,2.3)]);before=copy.deepcopy(model)
            blocks,wall,boundary,openings,report=world.build_component(model,[20,30],matrix,np.array([40,50]),184,{'roof_sampling_cells':2048})
            self.assertEqual(model,before);self.assertGreater(report['roof_slab_blocks'],0)
            self.assertEqual(report['full_roof_blocks'],0);self.assertNotIn('oak_planks',blocks.values())
            self.assertFalse(report['native_slab_shape_air_flood']['interior_reached_from_exterior'])
            for p in openings:
                for x,y in p['columns_xy']:
                    for h in range(184,184+p['headroom_blocks']):self.assertNotIn((x,h,y),blocks)

    def test_upper_connections_require_headroom_and_cardinal_connectivity(self):
        cells={(x,y) for x in range(3) for y in range(3)};heights={k:180 for k in cells};seeds=[{(0,1)},{(1,1)},{(2,1)}]
        self.assertTrue(world.upper_connectivity(cells,{},heights,184,seeds)['all_three_component_interiors_connected'])
        blocked={(1,h,y):'spruce_planks' for h in [184,185] for y in range(3)}
        with self.assertRaises(ValueError):world.upper_connectivity(cells,blocked,heights,184,seeds)
        diagonal={(0,0),(1,1),(2,2)}
        with self.assertRaises(ValueError):world.upper_connectivity(diagonal,{},heights,184,[{(0,0)},{(1,1)},{(2,2)}])

    def test_entry_flight_is_bounded_and_refuses_protected_objects(self):
        opening={'id':'front','geometry_nominal_local':mapping(LineString([(0,-.8),(0,.8)]))}
        terrain={(x,y):{'y':7} for x in range(-12,3) for y in range(-4,5)};upper={(0,-1),(0,0)}
        structures={(0,9,y):'stone_bricks' for y in [-1,0]};before=dict(structures)
        added,report=world.entry_flight(opening,[-1,0],10,terrain,structures,set(),upper)
        self.assertEqual(structures,before);self.assertEqual(report['status'],'estimated_half_step_entry_flight')
        self.assertLessEqual(report['maximum_neighbour_rise_m'],1);self.assertGreater(len(added),0)
        added,held=world.entry_flight(opening,[-1,0],10,terrain,structures,set(terrain),upper)
        self.assertEqual(added,{});self.assertEqual(held['status'],'withheld_no_collision_free_entry_flight')

    def test_sampling_budgets_and_cancellation_reject_partial_components(self):
        model=rectangular_model(8,10,3,5)
        with self.assertRaises(ValueError):world.build_component(model,[0,0],np.eye(2),np.zeros(2),184,{'roof_sampling_cells':1})
        with self.assertRaises(CancelledError):world.build_component(model,[0,0],np.eye(2),np.zeros(2),184,{'roof_sampling_cells':2048},cancelled=lambda:True)

    def test_provisional_opt_in_and_cancel_produce_no_world(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'world'
            with self.assertRaises(ValueError):world.run({},'missing','missing','missing','missing',out)
            with self.assertRaises(CancelledError):world.run({},'missing','missing','missing','missing',out,allow_provisional=True,cancelled=lambda:True)
            self.assertFalse(out.exists())


if __name__=='__main__':unittest.main()
