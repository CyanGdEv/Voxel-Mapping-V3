import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from voxel_mapper.smiler_reconstruction import reconstruction_audit, audit_svg, survey_observations, main


def fixture():
    pts=[[0,0],[10,10],[0,10],[10,0]]
    route={'segments':[{'start':p,'end':pts[(i+1)%4],'way_id':i+1,
                       'station_start_m':i*10,'station_end_m':(i+1)*10} for i,p in enumerate(pts)],
           'plan_length_m':48.28,'crossings':[{'segment_indices':[0,2],
             'geometry':{'type':'Point','coordinates':[5,5]}}]}
    station={'osm_way_id':100,'footprint':{'type':'Polygon','coordinates':[[[0,0],[1,0],[1,1],[0,0]]]}}
    return route,station


class SmilerAuditTests(unittest.TestCase):
    def test_geometry_has_no_invented_height_direction_or_phase(self):
        route,station=fixture();before=copy.deepcopy(route)
        report,geometry=reconstruction_audit(route,station,'local-test-crs')
        self.assertEqual(route,before)
        self.assertEqual(report['world_records_emitted'],0)
        self.assertEqual(report['accepted_3d_controls'],[])
        for feature in geometry['features'][:4]:
            self.assertIsNone(feature['properties']['track_height_odn_m'])
            self.assertEqual(feature['properties']['travel_direction'],'unresolved')
            self.assertEqual(feature['properties']['ride_phase'],'unresolved')
        self.assertEqual(geometry['coordinate_frame']['crs_wkt'],'local-test-crs')

    def test_crossings_remain_unresolved(self):
        report,geometry=reconstruction_audit(*fixture(),'local')
        self.assertEqual(report['unresolved_crossing_count'],1)
        self.assertIsNone(geometry['features'][-1]['properties']['vertical_separation_m'])
        self.assertIn('rejected',audit_svg(geometry))

    def test_route_fingerprint_changes_with_geometry(self):
        route,station=fixture()
        original=reconstruction_audit(route,station,'local')[0]['route_sha256']
        route['segments'][0]['start']=[-1,0];route['segments'][-1]['end']=[-1,0]
        self.assertNotEqual(reconstruction_audit(route,station,'local')[0]['route_sha256'],original)

    def test_broken_or_nonfinite_route_is_rejected(self):
        route,station=fixture();route['segments'][0]['end']=[4,4]
        with self.assertRaises(ValueError):reconstruction_audit(route,station,'local')
        route,station=fixture();route['segments'][0]['start']=[float('nan'),0]
        with self.assertRaises(ValueError):reconstruction_audit(route,station,'local')

    def test_old_world_command_rejected_before_any_output(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'world'
            with patch('sys.argv',['smiler','--park-output',temp,'--output',str(output)]):
                with self.assertRaises(SystemExit) as caught:main()
            self.assertEqual(caught.exception.code,2)
            self.assertFalse(output.exists())

    def test_survey_surfaces_never_become_track_controls(self):
        rows=survey_observations(fixture()[0],lambda x,z:160,lambda x,z:180,lambda x,z:161)
        self.assertEqual(rows[0]['ground_change_m'],-1)
        self.assertEqual(rows[0]['surface_minus_ground_m'],20)
        self.assertTrue(all(r['identified_track_height_odn_m'] is None for r in rows))
        with self.assertRaises(ValueError):
            survey_observations(fixture()[0],lambda x,z:None,lambda x,z:180,lambda x,z:161)


if __name__=='__main__':unittest.main()
