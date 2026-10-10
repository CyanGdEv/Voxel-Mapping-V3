import unittest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from voxel_mapper.drawing_controls import inspect_coordinate_labels
from voxel_mapper.geopdf import page_point_to_metric


def fixture(code='32630', corrupt=False):
    writer=PdfWriter()
    page=writer.add_blank_page(600,600)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
    commands=[f'BT /F1 8 Tf 1 0 0 1 10 10 Tm (EPSG: {code}) Tj ET']
    for x,y in [(100,100),(100,500),(500,500),(500,100)]:
        east=500000+x+(10 if corrupt and x==100 and y==100 else 0)
        commands.append(f'BT /F1 8 Tf 1 0 0 1 {x} {y} Tm (E: {east}; N: {5700000+y}) Tj ET')
    stream=DecodedStreamObject();stream.set_data('\n'.join(commands).encode())
    page[NameObject('/Contents')]=stream
    return page


class CoordinateLabelTests(unittest.TestCase):
    def test_native_coordinate_pairs_fit_without_mutation_or_accuracy_claim(self):
        page=fixture()
        self.assertEqual(inspect_coordinate_labels(page)['status'],'blocked_reuse')
        report=inspect_coordinate_labels(page,reuse_allowed=True)
        self.assertEqual(report['status'],'candidate_alignment')
        viewport=report['viewports'][0]
        self.assertLess(viewport['max_withheld_error_m'],.1)
        self.assertEqual(report['independent_accuracy'],'not_verified')
        self.assertEqual(report['declared_source_crs'],'EPSG:32630')
        self.assertNotIn('/VP',page)
        self.assertEqual(len(page_point_to_metric(viewport,300,300)),2)
        with self.assertRaises(ValueError):page_point_to_metric(viewport,50,50)

    def test_corruption_wrong_area_crs_and_budgets_reject(self):
        self.assertEqual(inspect_coordinate_labels(fixture(corrupt=True),reuse_allowed=True)['status'],'rejected')
        for code in ('4326','999999','32630 EPSG: 32631'):
            self.assertEqual(inspect_coordinate_labels(fixture(code),reuse_allowed=True)['status'],'rejected')
        self.assertEqual(inspect_coordinate_labels(fixture(),[10,20,10.01,20.01],reuse_allowed=True)['status'],'rejected')
        self.assertEqual(inspect_coordinate_labels(fixture(),reuse_allowed=True,max_text=1)['viewports'],[])
