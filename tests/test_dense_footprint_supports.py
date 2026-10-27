"""Density comes from source lines; transfer members protect lower tracks."""
import unittest
from shapely.geometry import LineString,MultiLineString,Point
from voxel_mapper.dense_footprint_supports import infill_sources,route_member


def assigned(index,xy,station):
    return {'source_foot_index':index,'source_post':{'xy':xy},'target':{'station_m':station,'xy':[2,0]},'alternative_branch_margin_m':None}


class DenseFootprintSupportTests(unittest.TestCase):
    def test_infill_starts_are_on_native_frame_edge_and_do_not_replace_symbols(self):
        line=LineString([(0.2,.2),(4.8,.2)]);lines=MultiLineString([line])
        rows=[assigned(0,[.2,.2],10),assigned(1,[4.8,.2],10)]
        groups=[{'source_cross_lines':[{'post_indices':[0,1],'source_segment_index':0}]}]
        extra,review=infill_sources(rows,groups,lines)
        self.assertEqual({int(r['source_post']['xy'][0]) for r in extra},{1,2,3})
        self.assertTrue(all(line.distance(Point(r['source_post']['xy']))<1e-8 for r in extra))
        self.assertTrue(all(not r['infill_witness']['is_measured_footing_symbol'] for r in extra))
        self.assertFalse(review['infill_outside_native_brown_lines'])

    def test_edges_between_distinct_track_visits_are_not_densified(self):
        rows=[assigned(0,[.2,.2],10),assigned(1,[4.8,.2],90)]
        groups=[{'source_cross_lines':[{'post_indices':[0,1],'source_segment_index':0}]}]
        extra,review=infill_sources(rows,groups,MultiLineString([[ (.2,.2),(4.8,.2) ]]))
        self.assertFalse(extra)
        self.assertEqual(review['unfilled_source_edges'][0]['reason'],'unresolved_or_different_branch_endpoints')

    def test_upper_member_rises_beside_lower_track_before_crossing_above_it(self):
        start=(0,1,0);end=(6,9,0)
        blocked={(x,h,0) for x in range(2,5) for h in range(3,8)}
        path=route_member(start,end,lambda k:k not in blocked)
        self.assertIsNotNone(path)
        self.assertEqual(path[0],start);self.assertEqual(path[-1],end)
        self.assertFalse(set(path)&blocked)
        self.assertTrue(all(h>=8 for x,h,y in path if 2<=x<=4))
        self.assertTrue(all(a[1]<=b[1] and sum(abs(x-y) for x,y in zip(a,b))==1 for a,b in zip(path,path[1:])))
        self.assertTrue(all(y==0 for x,h,y in path))

    def test_no_lidar_return_does_not_override_a_closed_lower_track_clearance(self):
        blocked={(3,h,0) for h in range(1,10)}
        self.assertIsNone(route_member((0,1,0),(6,9,0),lambda k:k not in blocked))

    def test_blocked_source_foot_is_not_shifted_or_replaced(self):
        start=(0,1,0)
        self.assertIsNone(route_member(start,(6,9,0),lambda k:k!=start))

if __name__=='__main__':unittest.main()
