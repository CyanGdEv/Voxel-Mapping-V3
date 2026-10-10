import unittest
from unittest.mock import patch

from voxel_mapper.plan_network import recover, containing_faces
from voxel_mapper.plan_elevation_edges import match_edges


def edge(name, a, b):
    return {'id': name, 'points': [a, b]}


class NetworkTests(unittest.TestCase):
    def test_exact_fragments_join_and_retain_both_sources(self):
        network = recover([edge('a', (0, 0), (50, 0)), edge('b', (50, 0), (100, 0))])
        chain = network['chains'][0]
        self.assertEqual(chain['source_edge_ids'], ['a', 'b'])
        self.assertTrue(chain['straight_chain_candidate'])
        self.assertEqual(chain['length_pdf_points'], 100)
        self.assertEqual(len(match_edges([chain], .1, 10)), 1)
        self.assertFalse(chain['accepted_feature'])

    def test_tiny_gap_is_not_snapped_or_bridged(self):
        network = recover([edge('a', (0, 0), (50, 0)), edge('b', (50.00000001, 0), (100, 0))])
        self.assertEqual(len(network['chains']), 2)
        self.assertEqual(match_edges(network['chains'], .1, 10), [])
        self.assertEqual(match_edges(network['straight_runs'], .1, 10), [])
        self.assertFalse(network['geometry_snapping_or_gap_bridging'])

    def test_crossing_and_branch_stop_chains(self):
        network = recover([edge('a', (0, 0), (100, 0)), edge('b', (50, -10), (50, 10))])
        self.assertEqual(len(network['chains']), 4)
        self.assertEqual(network['faces'], [])
        self.assertEqual(match_edges(network['chains'], .1, 10), [])
        self.assertEqual(len(match_edges(network['straight_runs'], .1, 10)), 1)
        long = match_edges(network['straight_runs'], .1, 10)[0]
        self.assertEqual(long['junctions'], [{'point': [50, 0], 'network_degree': 4}])
        self.assertFalse(long['component_boundary_topology_verified'])

    def test_closed_outline_has_label_containment_but_no_component_acceptance(self):
        corners = [(0, 0), (20, 0), (20, 10), (0, 10), (0, 0)]
        network = recover([edge(str(i), a, b) for i, (a, b) in enumerate(zip(corners, corners[1:]))])
        self.assertEqual(len(network['faces']), 1)
        face = network['faces'][0]
        self.assertEqual(face['area_pdf_points_squared'], 200)
        self.assertEqual(containing_faces(network, (10, 5)), [face['id']])
        self.assertEqual(containing_faces(network, (0, 5)), [])
        self.assertFalse(face['physical_component_identity_verified'])
        self.assertEqual(network['world_geometry_additions'], 0)
        self.assertFalse(network['chains'][0]['straight_chain_candidate'])

    def test_duplicate_and_overlap_provenance_is_retained(self):
        network = recover([edge('a', (0, 0), (100, 0)), edge('b', (25, 0), (75, 0)), edge('c', (100, 0), (0, 0))])
        self.assertEqual(len(network['chains']), 1)
        self.assertEqual(network['chains'][0]['source_edge_ids'], ['a', 'b', 'c'])
        self.assertEqual(network['chains'][0]['length_pdf_points'], 100)

    def test_budgets_reject_before_unbounded_union(self):
        with patch('voxel_mapper.plan_network.unary_union') as union:
            with self.assertRaises(ValueError):
                recover([{}] * 20001)
            union.assert_not_called()


if __name__ == '__main__':
    unittest.main()
