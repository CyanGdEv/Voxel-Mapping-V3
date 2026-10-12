import copy
import unittest
from shapely.geometry import Polygon,mapping,shape
from tests import test_linework_boundaries as fixtures
from voxel_mapper.architectural_graph import build


class ArchitecturalGraphTests(unittest.TestCase):
    def parents(self,lines):return fixtures.LineworkTests().parents(lines)

    def test_branches_interior_crossings_and_unchanged_source_segments(self):
        parents=self.parents([[(10,20),(50,20)],[(30,10),(30,40)],[(50,20),(70,40)]])
        before=copy.deepcopy(parents);graph=build(parents)
        crossing=next(n for n in graph['nodes'] if n['point_pdf_native']==[30,20])
        self.assertEqual(crossing['drawing_degree'],2);self.assertEqual(crossing['drawing_valence'],4)
        self.assertEqual(crossing['topology_candidate'],'branch_or_crossing')
        self.assertTrue(all(i['basis']=='straight_overlay_intersection' for i in crossing['incidences']))
        self.assertFalse(crossing['physical_connectivity_verified'])
        self.assertEqual(graph['counts']['connected_subgraphs'],1)
        self.assertEqual(graph['counts']['edges'],3)
        for edge in graph['edges']:self.assertTrue(any(shape(edge['geometry']).equals(shape(p['geometry'])) for p in parents))
        self.assertEqual(parents,before);self.assertEqual(graph,build(list(reversed(parents))))
        # Two original edges may have four directions at an interior crossing.
        # Degree counts edge incidence, not inferred physical branches.

    def test_no_gap_repair_dashed_edges_and_curve_chords_are_explicit(self):
        parents=self.parents([[(10,20),(30,20)],[(30.00001,20),(50,20)],[(20,10),(20,30)]])
        parents[0]['paint_references'][0]['stroke_style']['dashes_pdf']='[2 2] 0'
        parents[2]['curve_approximation']['cubic_segments']=1
        graph=build(parents)
        self.assertEqual(graph['counts']['connected_subgraphs'],3)
        self.assertEqual(graph['counts']['dashed_pattern_edges'],1)
        self.assertEqual(graph['counts']['bounded_curve_chord_edges'],1)
        self.assertFalse(any(n['point_pdf_native']==[20,20] for n in graph['nodes']))
        curved=next(e for e in graph['edges'] if e['curve_approximation_present'])
        self.assertEqual(curved['source_geometry_basis'],'bounded_curve_chord')
        self.assertFalse(graph['view_scope_verified']);self.assertEqual(graph['world_geometry_additions'],0)

    def test_polygon_hole_rings_and_overlaps_keep_distinct_provenance(self):
        parents=self.parents([[(0,0),(100,0)],[(20,0),(80,0)]])
        graph=build(parents);self.assertEqual(graph['counts']['overlaps'],1)
        self.assertEqual(len(graph['overlaps'][0]['edge_ids']),2)
        p=parents[0];p['geometry']=mapping(Polygon([(0,0),(100,0),(100,100),(0,100)],holes=[[(20,20),(80,20),(80,80),(20,80)]]))
        graph=build([p]);self.assertEqual(graph['counts']['edges'],8)
        self.assertEqual(graph['counts']['connected_subgraphs'],2)
        self.assertEqual({e['path_role'] for e in graph['edges']},{'exterior_ring','hole_ring'})
        self.assertEqual(len(shape(graph['source_components'][0]['geometry']).interiors),1)

    def test_every_budget_discards_partial_graph_and_invalid_options_reject(self):
        parents=self.parents([[(10,20),(50,20)],[(30,10),(30,40)],[(10,20),(40,20)]])
        for opts in ({'max_edges':1},{'max_nodes':1},{'max_pair_checks':1}):
            graph=build(parents,graph_options=opts)
            self.assertEqual(graph['status'],'graph_budget_withheld')
            for name in ('edges','nodes','overlaps','connected_subgraphs','source_components'):self.assertEqual(graph[name],[])
        overlapping=self.parents([[(10,20),(50,20)],[(20,20),(60,20)],[(30,20),(70,20)]])
        graph=build(overlapping,graph_options={'max_overlaps':1})
        self.assertEqual(graph['reason'],'overlap_budget');self.assertEqual(graph['edges'],[])
        with self.assertRaises(ValueError):build(parents,graph_options={'max_edges':True})
        with self.assertRaises(ValueError):build(parents,graph_options={'snap_distance':1})
        parents[-1]['page']=2
        with self.assertRaises(ValueError):build(parents)


if __name__=='__main__':unittest.main()
