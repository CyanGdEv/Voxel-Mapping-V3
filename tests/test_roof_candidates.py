import unittest
import numpy as np
from shapely.geometry import box,shape
from voxel_mapper.roof_candidates import components,roof_candidates


class RoofCandidateTests(unittest.TestCase):
    def test_components_include_outside_seed_and_separate_high_neighbour(self):
        xyz=np.array([[0,0,10],[1,0,10],[0,1,10],[1,1,10],[2,1,10],[2,2,20]],float)
        r=roof_candidates(xyz,np.arange(6),box(-.1,-.1,1.1,1.1),(-10,-10,10,10),radii=(1.1,),height_steps=(1,))
        c=r['candidates'][0]
        self.assertEqual(c['original_crop_point_indices'],[0,1,2,3,4])
        self.assertEqual(c['seed_point_count'],4)
        self.assertEqual(shape(c['geometry']).bounds[2],2)
        self.assertFalse(c['crop_edge_within_connectivity_radius'])
        self.assertEqual(r['accepted_checkpoints'],0)
        self.assertIsNone(r['native_edge_uncertainty_m'])

    def test_distance_change_retains_merge_and_edge_truncation_evidence(self):
        xyz=np.array([[0,0,10],[.5,0,10],[0,.5,10],[.5,.5,10],[1.5,.5,10],[1.5,1,10]],float)
        r=roof_candidates(xyz,np.arange(6),box(-.1,-.1,.6,.6),(-1,-1,2,2),radii=(.6,1.1),height_steps=(1,))
        self.assertEqual([c['point_count'] for c in r['candidates']],[4,6])
        self.assertGreater(r['maximum_connectivity_boundary_spread_m'],0)
        self.assertTrue(r['candidates'][1]['crop_edge_within_connectivity_radius'])
        self.assertEqual(len(r['distinct_observed_envelopes']),2)
        self.assertEqual(r['component_expansions'][0]['added_point_count'],2)
        self.assertEqual(r['component_expansions'][0]['added_z_odn_m']['median'],10)

    def test_bad_input_and_dense_pair_budget_fail_closed(self):
        with self.assertRaisesRegex(ValueError,'comparison budget'):
            components(np.zeros((20,3)),1,1,max_comparisons=10)
        with self.assertRaises(ValueError):components(np.array([[0,0,np.nan]]),1,1)
        with self.assertRaises(ValueError):
            roof_candidates(np.zeros((2,3)),np.array([1,1]),box(0,0,1,1),(0,0,2,2))
        r=roof_candidates(np.empty((0,3)),np.array([],dtype=int),box(0,0,1,1),(0,0,2,2))
        self.assertIsNone(r['maximum_connectivity_boundary_spread_m'])
        self.assertTrue(all(c['status']=='no_seeded_component' for c in r['candidates']))
