import unittest

from pypdf.generic import DecodedStreamObject, NameObject

import test_geopdf as fixtures
from voxel_mapper.geopdf import inspect_registration
from voxel_mapper.drawing_vectors import extract_vectors
from voxel_mapper.drawing_polygons import polygon_candidates
from shapely.geometry import shape


class DrawingVectorTests(unittest.TestCase):
    def fixture(self, content):
        _,page,_ = fixtures.GeoPdfTests().fixture()
        stream = DecodedStreamObject(); stream.set_data(content)
        page[NameObject('/Contents')] = stream
        return page, inspect_registration(page,fixtures.GeoPdfTests.bounds)

    def test_reuse_gate_and_missing_registration(self):
        page,registration = self.fixture(b'100 200 m 500 600 l S')
        self.assertEqual(extract_vectors(page,registration)['status'],'blocked_reuse')
        self.assertEqual(extract_vectors(page,registration,reuse_allowed='yes')['layers'],[])
        self.assertEqual(extract_vectors(page,{},reuse_allowed=True)['status'],'registration_unavailable')

    def test_nested_transform_and_restore_metres(self):
        page,registration = self.fixture(b'q 2 0 0 2 100 200 cm q 1 0 0 1 50 0 cm 0 0 m 50 100 l S Q 0 0 m 100 100 l S Q')
        result = extract_vectors(page,registration,reuse_allowed=True)
        paths = result['layers'][0]['paths']
        self.assertEqual(len(paths),2)
        expected = [[(150,0),(200,150)],[(100,0),(200,150)]]
        for path, points in zip(paths,expected):
            for actual,wanted in zip(path['geometry']['coordinates'],points):
                for a,b in zip(actual,wanted):self.assertAlmostEqual(a,b,places=3)
        self.assertEqual(result['world_geometry_additions'],0)

    def test_fill_holes_preserved_as_separate_unclassified_boundaries(self):
        page,registration = self.fixture(b'100 200 400 400 re 200 300 100 100 re f*')
        result = extract_vectors(page,registration,reuse_allowed=True)
        paths = result['layers'][0]['paths']
        self.assertEqual(len(paths),2)
        self.assertTrue(all(p['closed'] for p in paths))
        self.assertTrue(all(p['geometry']['type']=='LineString' for p in paths))
        self.assertTrue(all(p['paint_operator']=='f*' for p in paths))
        polygons=polygon_candidates(result)['layers'][0]['polygons']
        self.assertEqual(len(polygons),1)
        self.assertEqual(len(shape(polygons[0]['geometry']).interiors),1)
        page,registration=self.fixture(b'100 200 400 400 re 50 300 100 100 re f*')
        incomplete=extract_vectors(page,registration,reuse_allowed=True)
        self.assertEqual(polygon_candidates(incomplete)['layers'][0]['polygons'],[])

    def test_crossing_control_domain_omitted_without_extrapolation(self):
        page,registration = self.fixture(b'50 400 m 550 400 l S 100 200 m 200 300 l S')
        result = extract_vectors(page,registration,reuse_allowed=True)
        self.assertEqual(len(result['layers'][0]['paths']),1)
        self.assertEqual(result['layers'][0]['omitted_outside_domain_or_degenerate'],1)

    def test_unsupported_rendering_rejects_entire_page_no_partial_results(self):
        for command in (b'W n',b'0 0 1 1 2 2 c S',b'/X Do',b'/OC /Layer BDC EMC',b'/GS gs',b'4 Tr'):
            page,registration = self.fixture(b'100 200 m 200 300 l S '+command)
            result = extract_vectors(page,registration,reuse_allowed=True)
            self.assertEqual(result['status'],'unsupported_or_rejected')
            self.assertEqual(result['layers'],[])

    def test_budget_and_malformed_state_fail_closed(self):
        for content,kwargs in ((b'Q',{}),(b'q',{}),(b'100 200 m',{}),
                               (b'100 200 m 200 300 l S',{'max_operations':1}),
                               (b'100 200 m 200 300 l S',{'max_points':1}),
                               (b'100 200 50 50 re S 200 300 50 50 re S',{'max_paths':1})):
            page,registration = self.fixture(content)
            self.assertEqual(extract_vectors(page,registration,reuse_allowed=True,**kwargs)['layers'],[])

    def test_insets_stay_separate_and_unpainted_paths_are_discarded(self):
        page,registration = self.fixture(b'100 200 m 200 300 l n 100 200 m 200 300 l s')
        registration['viewports'].append({**registration['viewports'][0],'viewport':1})
        result = extract_vectors(page,registration,reuse_allowed=True)
        self.assertEqual([l['viewport'] for l in result['layers']],[0,1])
        self.assertTrue(all(len(l['paths'])==1 for l in result['layers']))
        self.assertTrue(result['layers'][0]['paths'][0]['closed'])

    def test_crop_box_limits_candidate_geometry(self):
        from pypdf.generic import RectangleObject
        page,registration = self.fixture(b'100 200 m 500 600 l S 100 200 m 200 300 l S')
        page[NameObject('/CropBox')] = RectangleObject([100,200,300,400])
        result = extract_vectors(page,registration,reuse_allowed=True)
        self.assertEqual(len(result['layers'][0]['paths']),1)
        self.assertEqual(result['layers'][0]['omitted_outside_domain_or_degenerate'],1)
