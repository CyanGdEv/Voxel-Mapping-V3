"""Source-link and datum barriers with synthetic PDF/LAS evidence."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import CancelledError

import laspy
import pymupdf
from pyproj import CRS
from shapely.geometry import LineString

from voxel_mapper import ride_geometry_evidence as evidence


def fixture(root):
    pdf = root/'plan.pdf'
    with pymupdf.open() as doc:
        page = doc.new_page(width=250, height=200)
        page.draw_line((84,104),(96,104))
        page.draw_circle((90,104),4)
        page.draw_line((90,98),(90,110))
        page.insert_text((100,100),'HP1 - 201')
        seq = page.get_drawings()[1]['seqno']
        doc.save(pdf)
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    markings = root/'markings.json'
    markings.write_text(json.dumps({'document_sha256':sha(pdf),'coordinate_frame':'pdf_native_points_y_up',
        'records':[{'role':'track_centre','geometry_pdf_native':{'type':'LineString','coordinates':[[50,96],[150,96]]}}]}))
    profile = root/'profile.json'
    profile.write_text(json.dumps({'source_pdf_sha256':sha(pdf),'markings_sha256':sha(markings),
        'metres_per_pdf_point':.1,'source_native_height_points':200,
        'controls':[{'label':'HP1','height_m':201,'marker_vector_sequence':seq,'raw_marker_pdf_xy':[90,104]}]}))
    cloud_path = root/'cloud.las'
    header = laspy.LasHeader(point_format=3, version='1.2')
    header.add_crs(CRS.from_epsg(27700))
    cloud = laspy.LasData(header)
    cloud.x = [407500.,407500.1]
    cloud.y = [343500.,343500.1]
    cloud.z = [180.,200.]
    cloud.classification = [2,5]
    cloud.write(cloud_path)
    receipt = root/'receipt.json'
    receipt.write_text(json.dumps({'sha256':sha(cloud_path),'crs':'EPSG:27700','vertical_datum':'ODN','retained_points':2}))
    alignment = root/'alignment.json'
    alignment.write_text(json.dumps({'nominal_local_xy_to_bng_en_affine':[1,0,0,1,407491,343490.4]}))
    paths = dict(pdf=pdf,markings=markings,profile=profile,cloud=cloud_path,cloud_receipt=receipt,alignment=alignment)
    request = root/'request.json'
    request.write_text(json.dumps({'version':evidence.VERSION,'ride_id':'fixture','source_state':'proposed',
        'assets':{k:{'path':str(p),'sha256':sha(p)} for k,p in paths.items()}}))
    return request


class RideGeometryEvidenceTests(unittest.TestCase):
    def test_crossing_visits_are_not_averaged_or_silently_chosen(self):
        route = LineString([[-10,0],[10,0],[10,10],[0,10],[0,-10]])
        tied = evidence.branches(route,[0,0])
        self.assertIsNone(tied['selected'])
        self.assertEqual(len(tied['candidates']),2)
        self.assertGreater(abs(tied['candidates'][0]['station_m']-tied['candidates'][1]['station_m']),8)
        near = evidence.branches(route,[5,0])
        self.assertEqual(near['selected']['xy'],[5,0])
        self.assertIsNone(evidence.branches(route,[50,50])['selected'])

    def test_printed_source_is_linked_without_claiming_datum_or_lidar_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = fixture(root)
            result = evidence.build(request,root/'result')
            marker = result['markers'][0]
            self.assertEqual(marker['printed_level_m'],201)
            self.assertEqual(marker['printed_level_datum'],'not_established')
            self.assertFalse(marker['surveyed_xyz_training_eligible'])
            self.assertEqual(marker['lidar_context']['eligible_returns'],2)
            self.assertIsNone(marker['lidar_context']['printed_level_minus_lidar_error_m'])
            self.assertEqual(result['summary']['surveyed_xyz_training_targets'],0)
            self.assertFalse(result['model_weights_updated'])
            replay = evidence.build(root/'result'/'replay-request.json',root/'replay')
            self.assertEqual(result['markers'],replay['markers'])

    def test_changed_asset_and_printed_level_fail_before_publication(self):
        for mode in ['bytes','label']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                request = fixture(root)
                if mode == 'bytes':
                    (root/'plan.pdf').write_bytes((root/'plan.pdf').read_bytes()+b' ')
                else:
                    path = root/'profile.json'
                    value = json.loads(path.read_text());value['controls'][0]['height_m']=205
                    path.write_text(json.dumps(value))
                    value=json.loads(request.read_text());value['assets']['profile']['sha256']=hashlib.sha256(path.read_bytes()).hexdigest();request.write_text(json.dumps(value))
                with self.assertRaises(ValueError):evidence.build(request,root/'result')
                self.assertFalse((root/'result').exists())

    def test_cancellation_and_fresh_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);request=fixture(root)
            with self.assertRaises(CancelledError):evidence.build(request,root/'result',cancelled=lambda:True)
            self.assertFalse((root/'result').exists())
            (root/'result').mkdir()
            with self.assertRaises(ValueError):evidence.build(request,root/'result')


if __name__ == '__main__':
    unittest.main()
