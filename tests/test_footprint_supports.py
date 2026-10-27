"""Branch assignment and lower-track protection regressions."""
import unittest
from shapely.geometry import LineString,MultiLineString
from voxel_mapper.footprint_supports import source_targets,obstruction


class FootprintSupportTests(unittest.TestCase):
    def test_two_crossings_in_one_source_group_do_not_share_a_median_height(self):
        route=LineString([(0,0),(20,0),(20,10),(0,10)])
        posts=[{'xy':[10,y],'source_polygon_index':i} for i,y in enumerate([-2,2,8,12])]
        lines=MultiLineString([[(10,-2),(10,2)],[(10,2),(10,8)],[(10,8),(10,12)]])
        group={'posts':posts,'station_m':25,'source_cross_lines':[{'post_indices':[i,i+1],'source_segment_index':i} for i in range(3)]}
        assigned,held,_=source_targets(route,[group],[],lines)
        self.assertFalse(held)
        self.assertEqual([r['target']['station_m'] for r in assigned],[10,10,40,40])
        self.assertEqual([r['source_post']['xy'] for r in assigned],[p['xy'] for p in posts])

    def test_equally_connected_crossing_branches_are_withheld(self):
        route=LineString([(0,0),(20,0),(20,10),(0,10)])
        posts=[{'xy':[10,y],'source_polygon_index':i} for i,y in enumerate([-2,2,5,8,12])]
        lines=MultiLineString([[(10,-2),(10,2)],[(10,2),(10,5)],[(10,5),(10,8)],[(10,8),(10,12)]])
        group={'posts':posts,'station_m':25,'source_cross_lines':[{'post_indices':[i,i+1],'source_segment_index':i} for i in range(4)]}
        assigned,held,_=source_targets(route,[group],[],lines)
        self.assertEqual(len(assigned),4)
        self.assertEqual(held[0]['source_foot_index'],2)
        self.assertEqual(held[0]['reason'],'ambiguous_source_crossing_branch')

    def test_crossing_clearance_rejects_entire_member_including_fence_extension(self):
        terrain={(0,0):{'y':0},(1,0):{'y':0},(2,0):{'y':0}}
        path=[(0,1,0),(0,2,0),(1,2,0),(1,3,0),(2,3,0)]
        self.assertEqual(obstruction(path,terrain,{}, {(1,4,0)},path[0],(2,4,0)),'lower_track_or_walking_clearance')
        self.assertEqual(obstruction(path,terrain,{(1,2,0):'oak_slab'},set(),path[0],(2,4,0)),'retained_geometry_or_lower_track')
        self.assertIsNone(obstruction(path,terrain,{(2,4,0):'oak_slab'},set(),path[0],(2,4,0)))
        self.assertIsNone(obstruction(path,terrain,{(1,4,0):'oak_slab_top',(2,4,0):'oak_slab'},set(),path[0],{(1,4,0),(2,4,0)}))
        self.assertEqual(obstruction(path,terrain,{(1,4,0):'oak_slab_top'}, {(1,4,0)},path[0],{(1,4,0)}),'lower_track_or_walking_clearance')

    def test_footprint_without_native_centreline_connection_is_not_infilled(self):
        post={'xy':[5,4],'source_polygon_index':0}
        assigned,held,_=source_targets(LineString([(0,0),(10,0)]),[],[post],MultiLineString([[(5,3),(5,5)]]))
        self.assertFalse(assigned)
        self.assertEqual(held[0]['reason'],'no_native_cross_line_to_centre')

if __name__=='__main__':unittest.main()
