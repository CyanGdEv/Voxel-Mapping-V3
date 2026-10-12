import unittest
from shapely.geometry import box
from voxel_mapper.landmark_diagnostics import diagnose

class LandmarkDiagnosticsTests(unittest.TestCase):
    def test_two_matches_do_not_accept_registration(self):
        objects=[{'candidate_id':'a','geometry':box(0,0,10,5)},{'candidate_id':'b','geometry':box(20,10,26,14)}]
        refs=[{'id':'x','geometry':box(100,200,110,205)},{'id':'y','geometry':box(120,210,126,214)}]
        r=diagnose(objects,refs,'a','x')
        self.assertEqual(max(len(t['distinct_nonoverlapping_outline_matches']) for t in r['orientation_trials']),2)
        self.assertFalse(r['registration_verified']);self.assertEqual(r['world_geometry_additions'],0)
    def test_nested_outlines_cannot_inflate_matches(self):
        objects=[{'candidate_id':'a','geometry':box(0,0,10,5)},{'candidate_id':'b','geometry':box(1,1,9,4)}]
        refs=[{'id':'x','geometry':box(100,200,110,205)},{'id':'y','geometry':box(101,201,109,204)}]
        r=diagnose(objects,refs,'a','x')
        self.assertEqual(max(len(t['distinct_nonoverlapping_outline_matches']) for t in r['orientation_trials']),1)
    def test_unknown_and_duplicate_ids_rejected(self):
        objects=[{'candidate_id':'a','geometry':box(0,0,10,5)}];refs=[{'id':'x','geometry':box(100,200,110,205)}]
        with self.assertRaises(ValueError):diagnose(objects,refs,'missing','x')
        with self.assertRaises(ValueError):diagnose(objects*2,refs,'a','x')
