import tempfile
import unittest
from pathlib import Path

import laspy
from pyproj import CRS
from shapely.geometry import box

from voxel_mapper.point_cloud_audit import audit_returns


class PointCloudAuditTests(unittest.TestCase):
    def test_flags_margin_and_unclassified_returns_do_not_accept_geometry(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'crop.las'
            header=laspy.LasHeader(point_format=6,version='1.4')
            header.add_crs(CRS.from_epsg(27700));data=laspy.LasData(header)
            data.x=[.2,.3,.4,.5,1.5,9];data.y=[.2]*6;data.z=[12]*6
            data.classification=[6,6,6,1,6,2]
            data.withheld=[0,1,0,0,0,0];data.synthetic=[0,0,1,0,0,0];data.write(path)
            refs=[{'id':'comparison','name':'Building comparison','geometry':box(0,0,1,1)}]
            result=audit_returns(path,refs,margin_m=1)
            row=result['landmarks'][0]
            self.assertEqual(row['inside_classifications'],{1:1,6:3})
            self.assertEqual(row['eligible_class_6_inside'],1)
            self.assertEqual(row['eligible_class_6_in_margin'],1)
            self.assertEqual(result['scanned_points'],6)
            self.assertEqual(result['world_geometry_additions'],0)
            self.assertFalse(row['physical_identity_verified'])
            with self.assertRaisesRegex(ValueError,'budget'):audit_returns(path,refs,max_points=5)

    def test_invalid_comparison_inputs_fail_before_reading(self):
        ref={'id':'a','name':'a','geometry':box(0,0,1,1)}
        for refs,margin in (([ref,ref],3),([ref],float('nan')),([ref],0)):
            with self.assertRaises(ValueError):audit_returns('missing.las',refs,margin)
