"""Courtyard additions must retain the Wicker world and fail atomically."""
import copy
from concurrent.futures import CancelledError
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from shapely.geometry import Polygon, mapping
from voxel_mapper import courtyard_plan_expansion as courtyard, planning_geometry_world as world
from tests.test_planning_geometry_world import inputs, request


def fixture():
    p=courtyard.profile()
    layout={'document_sha256':p['target_document_sha256'],'candidates':[{
        'id':p['target_tavern_candidate_id'], 'role':'building',
        'geometry_pdf_native':mapping(Polygon([c['target_wicker_native'] for c in p['controls']]))}]}
    proof={'source_pdf_sha256':p['source_pdf_sha256'],
           'source_render_samples_sha256':p['source_render_samples_sha256'],'source_verified':True}
    return courtyard.request(proof,{'layout':'a'*64},layout),layout


class CourtyardExpansionTests(unittest.TestCase):
    def test_fixed_scale_and_checked_pose_are_not_survey_registration(self):
        value,_=fixture()
        self.assertAlmostEqual(value['pose']['source_metres_per_pixel'],.046723456790123456)
        self.assertFalse(value['world_placement_eligible'])
        self.assertFalse(value['pose']['independent_registration_verified'])
        self.assertEqual(len(value['features']),11)

    def test_changed_geometry_base_pins_or_source_is_rejected(self):
        value,layout=fixture()
        changes=[lambda v:v['features'][0]['geometry_nominal_local']['coordinates'][0][0].__setitem__(0,999),
                 lambda v:v['baseline_source_pins'].__setitem__('layout','b'*64),
                 lambda v:v['source_proof'].__setitem__('source_verified',False)]
        for change in changes:
            v=copy.deepcopy(value);change(v)
            with self.assertRaises(ValueError):courtyard.validate(v,{'layout':'a'*64},layout)

    def test_existing_ground_and_edging_always_take_precedence(self):
        value,_=fixture();cells,_=courtyard.apply(value,{},{});keys=list(cells)
        ground={keys[0]:'orange_wool'};rocks={keys[1]:[(1,'oak_fence')]}
        before=copy.deepcopy(rocks);added,report=courtyard.apply(value,ground,rocks)
        self.assertEqual(ground[keys[0]],'orange_wool');self.assertEqual(rocks,before)
        self.assertNotIn(keys[0],added);self.assertNotIn(keys[1],added)
        self.assertTrue(report['baseline_features_preserved'])

    def test_cancel_or_budget_failure_does_not_partially_mutate(self):
        value,_=fixture()
        for kwargs,error in [({'max_checks':1},ValueError),({'cancelled':lambda:True},CancelledError)]:
            ground={(0,0):'blue_wool'};before=dict(ground)
            with self.assertRaises(error):courtyard.apply(value,ground,{},**kwargs)
            self.assertEqual(ground,before)

    def test_raster_expansion_retains_all_baseline_cells_and_spawn(self):
        data=inputs();before=world.rasterize(data);value,_=fixture();data['expansion']=value
        after=world.rasterize(data)
        self.assertTrue(all(after['ground'][k]==v for k,v in before['ground'].items()))
        self.assertEqual(before['rocks'],after['rocks'])
        self.assertEqual(before['retained_spawn_local_xyz_m'],after['retained_spawn_local_xyz_m'])
        self.assertGreater(len(after['expansion_cells']),0)

    def test_native_export_checks_the_added_cells_and_retained_spawn(self):
        data=inputs();value,_=fixture();data['expansion']=value
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);config=request(root,data)
            # Input provenance has separate rejection tests; exercise native save with a small base fixture.
            with patch.object(world,'read_inputs',return_value=data):result=world.run(config,root/'world')
            self.assertTrue(result['saved_geometry_validation']['native_block_states_verified'])
            self.assertTrue(result['archive_validation']['saved_world_reopened'])
            self.assertTrue(result['spawn_validation']['verified'])
            self.assertTrue((root/'world/courtyard-expansion-cells.json').is_file())


if __name__=='__main__':unittest.main()
