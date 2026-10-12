import unittest
from unittest.mock import patch
from shapely.geometry import LineString,mapping
from voxel_mapper.osm_network_graph import disk_junctions
from voxel_mapper.osm_landmark_context import junctions,topology_checks


class DiskNetworkTests(unittest.TestCase):
    def network(self):
        return [LineString([(0,0),(1,0)]),LineString([(0,0),(-1,0)]),LineString([(0,0),(0,1)])]

    def test_disk_matches_exact_graph_and_deduplicates_edges(self):
        lines=self.network();rows,receipt=disk_junctions(lines+lines)
        self.assertEqual(rows,junctions(lines+lines));self.assertEqual(receipt['unique_edges'],3)
        self.assertFalse(receipt['registration_verified'])
        crossing=[LineString([(-1,0),(1,0)]),LineString([(0,-1),(0,1)])]
        self.assertEqual(disk_junctions(crossing)[0],[])

    def test_ids_layers_and_conflicting_node_positions_are_preserved(self):
        lines=[{'geometry':g,'node_ids':[1,i+2]} for i,g in enumerate(self.network())]
        lines[-1]['node_ids']=[9,4]
        self.assertEqual(disk_junctions(lines)[0],[])
        lines[-1]['node_ids']=[1,4]
        self.assertEqual(disk_junctions(lines)[0][0]['degree'],3)
        lines[-1]['geometry']=LineString([(0,.01),(0,1)])
        with self.assertRaisesRegex(ValueError,'Conflicting'):disk_junctions(lines)
        layered=[{'geometry':g,'layer':str(i)} for i,g in enumerate(self.network())]
        self.assertEqual(disk_junctions(layered)[0],[])

    def test_all_disk_budgets_withhold_instead_of_returning_partial_graph(self):
        for limits in ({'max_scan_vertices':2},{'max_nodes':1},{'max_edges':1}):
            with self.assertRaisesRegex(ValueError,'budget'):disk_junctions(self.network(),limits=limits)
        lines=self.network()+[LineString([(x+10,y) for x,y in g.coords]) for g in self.network()]
        with self.assertRaisesRegex(ValueError,'junction budget'):disk_junctions(lines,limits={'max_junctions':1})
        with self.assertRaises(ValueError):disk_junctions(lines,limits={'max_nodes':True})

    def test_topology_falls_back_only_for_memory_budget_exhaustion(self):
        lines=self.network();parents=[{'geometry':mapping(g)} for g in lines]
        fit={'matrix':[[1,0],[0,1]],'translation_m':[0,0]}
        with patch('voxel_mapper.osm_landmark_context.junctions',side_effect=ValueError('Network vertex budget exceeded')):
            result=topology_checks(parents,lines,[fit])
        self.assertEqual(result['source_graph']['mode'],'bounded_disk_graph')
        self.assertEqual(len(result['hypotheses'][0]['unique_junction_matches']),1)
        with patch('voxel_mapper.osm_landmark_context.junctions',side_effect=ValueError('OSM node/geometry inventory mismatch')):
            result=topology_checks(parents,lines,[fit])
        self.assertEqual(result['status'],'network_budget_withheld')
        self.assertIn('inventory mismatch',result['reason'])

    def test_negative_zero_and_integer_coordinates_share_exact_vertex_keys(self):
        lines=[LineString([(-0.,0),(1,0)]),LineString([(0,0),(-1,0)]),LineString([(0,-0.),(0,1)])]
        self.assertEqual(disk_junctions(lines)[0][0]['degree'],3)

if __name__=='__main__':unittest.main()
