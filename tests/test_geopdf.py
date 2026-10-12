import io
import unittest

from pyproj import CRS, Transformer
from pypdf import PdfWriter
from pypdf.generic import ArrayObject,DictionaryObject,NameObject,NumberObject,FloatObject

from voxel_mapper.geopdf import inspect_registration,page_point_to_metric
from voxel_mapper.council import inspect_pdf


def array(values):
    return ArrayObject([FloatObject(float(v)) for v in values])


class GeoPdfTests(unittest.TestCase):
    bounds=[-.52,51.39,-.50,51.41]

    def fixture(self):
        writer=PdfWriter();page=writer.add_blank_page(600,800)
        target=CRS.from_proj4('+proj=aeqd +lat_0=51.4 +lon_0=-0.51 +datum=WGS84 +units=m')
        inverse=Transformer.from_crs(target,4326,always_xy=True)
        controls=[(0,0),(0,1),(1,1),(1,0)]
        geographic=[]
        for u,v in controls:
            lon,lat=inverse.transform(100+200*u,300*v)
            geographic.extend((lat,lon))
        measure=DictionaryObject({NameObject('/Subtype'):NameObject('/GEO'),
            NameObject('/LPTS'):array([c for p in controls for c in p]), NameObject('/GPTS'):array(geographic),
            NameObject('/GCS'):DictionaryObject({NameObject('/EPSG'):NumberObject(4326)})})
        viewport=DictionaryObject({NameObject('/BBox'):array([100,200,500,600]),NameObject('/Measure'):measure})
        page[NameObject('/VP')]=ArrayObject([viewport])
        return writer,page,measure

    def test_metric_placement_offset_axis_order_and_no_extrapolation(self):
        _,page,_=self.fixture()
        result=inspect_registration(page,self.bounds)
        self.assertEqual(result['status'],'candidate_alignment')
        registration=result['viewports'][0]
        east,north=page_point_to_metric(registration,300,400)
        self.assertAlmostEqual(east,200,places=3)
        self.assertAlmostEqual(north,150,places=3)
        self.assertLess(registration['max_withheld_error_m'],.01)
        self.assertEqual(registration['area_check'],'intersects_requested_area')
        with self.assertRaisesRegex(ValueError,'outside'):page_point_to_metric(registration,50,400)

    def test_pdf_readback_and_inspection_includes_registration(self):
        writer,_,_=self.fixture();out=io.BytesIO();writer.write(out)
        report=inspect_pdf(out.getvalue(),bounds=self.bounds)
        self.assertEqual(report['pages'][0]['registration']['status'],'candidate_alignment')
        self.assertEqual(report['pages'][0]['registration']['independent_accuracy'],'not_verified')
        self.assertEqual(report['pages'][0]['vector_extraction']['status'],'blocked_reuse')
        self.assertEqual(report['pages'][0]['vector_extraction']['layers'],[])

    def test_corrupt_control_rejected_by_withheld_validation(self):
        _,page,measure=self.fixture()
        measure['/GPTS'][0]=FloatObject(float(measure['/GPTS'][0])+.001)
        result=inspect_registration(page,self.bounds)
        self.assertEqual(result['status'],'rejected')
        self.assertIn('tolerance',result['viewports'][0]['reason'])
        self.assertGreater(result['viewports'][0]['max_withheld_error_m'],50)

    def test_degenerate_duplicate_and_three_control_sets_rejected(self):
        for controls in ([0,0,0,0,1,1,1,0],[0,0,.2,0,.5,0,1,0],[0,0,0,1,1,1]):
            _,page,measure=self.fixture();measure[NameObject('/LPTS')]=array(controls)
            measure[NameObject('/GPTS')]=array(list(measure['/GPTS'])[:len(controls)])
            self.assertEqual(inspect_registration(page,self.bounds)['status'],'rejected')

    def test_missing_unknown_and_projected_crs_not_assumed(self):
        for epsg in (None,27700,999999):
            _,page,measure=self.fixture()
            measure[NameObject('/GCS')]=DictionaryObject({} if epsg is None else {NameObject('/EPSG'):NumberObject(epsg)})
            self.assertEqual(inspect_registration(page,self.bounds)['status'],'rejected')
        _,page,measure=self.fixture()
        measure['/GCS'][NameObject('/Type')]=NameObject('/PROJCS')
        self.assertEqual(inspect_registration(page,self.bounds)['status'],'rejected')
        _,page,measure=self.fixture()
        from pypdf.generic import TextStringObject
        measure['/GCS'][NameObject('/WKT')]=TextStringObject(CRS.from_epsg(27700).to_wkt())
        self.assertIn('Conflicting',inspect_registration(page,self.bounds)['viewports'][0]['reason'])

    def test_wrong_area_rotation_and_viewport_outside_page_rejected(self):
        _,page,_=self.fixture()
        self.assertEqual(inspect_registration(page,[10,20,10.01,20.01])['status'],'rejected')
        page[NameObject('/Rotate')]=NumberObject(90)
        self.assertEqual(inspect_registration(page,self.bounds)['status'],'rejected')
        page[NameObject('/Rotate')]=NumberObject(0)
        page['/VP'][0][NameObject('/BBox')]=array([-100,0,500,600])
        self.assertEqual(inspect_registration(page,self.bounds)['status'],'rejected')

    def test_insets_separate_and_metadata_absence_explicit(self):
        _,page,_=self.fixture()
        page['/VP'].append(page['/VP'][0])
        report=inspect_registration(page,self.bounds)
        self.assertEqual(report['candidate_viewports'],2)
        self.assertEqual(len(report['viewports']),2)
        self.assertEqual(inspect_registration(page,self.bounds,max_viewports=1)['status'],'rejected')
        del page['/VP']
        self.assertEqual(inspect_registration(page,self.bounds)['status'],'metadata_missing')
        page[NameObject('/LGIDict')]=DictionaryObject({NameObject('/Type'):NameObject('/LGIDict')})
        self.assertEqual(inspect_registration(page,self.bounds)['status'],'unsupported_lgi_encoding')

    def test_nonfinite_controls_and_tolerances_rejected(self):
        _,page,measure=self.fixture()
        measure[NameObject('/LPTS')]=array([0,0,0,1,1,1,1,2])
        self.assertEqual(inspect_registration(page,self.bounds)['status'],'rejected')
        with self.assertRaises(ValueError):inspect_registration(page,self.bounds,tolerance_m=float('nan'))

    def test_registration_boundary_restricts_valid_points(self):
        _,page,measure=self.fixture()
        measure[NameObject('/Bounds')]=array([0,0,0,1,.5,1,.5,0])
        registration=inspect_registration(page,self.bounds)['viewports'][0]
        page_point_to_metric(registration,200,400)
        with self.assertRaisesRegex(ValueError,'outside'):page_point_to_metric(registration,450,400)
        measure[NameObject('/Bounds')]=array([0,0,1,1,0,1,1,0])
        self.assertEqual(inspect_registration(page,self.bounds)['status'],'rejected')
