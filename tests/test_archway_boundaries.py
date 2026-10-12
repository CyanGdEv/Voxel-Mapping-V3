import copy
import unittest
from shapely.geometry import box,mapping,shape
from tests import test_linework_boundaries as fixtures
from voxel_mapper.archway_boundaries import review


class ArchwayBoundaryTests(unittest.TestCase):
    def fixture(self):
        parents=fixtures.LineworkTests().parents([[(20,20),(100,20)],[(20,80),(100,80)],[(20,90),(100,90)]])
        refs=[{'document_sha256':parents[0]['document_sha256'],'page':parents[0]['page'],
            'reference_occurrences':[{'reference_id':'archway:1','glyph_screen':{'status':'raster_consistent_candidate'},
                'label_geometry':mapping(box(40,40,60,60))}]}]
        return parents,refs

    def test_all_brackets_retained_without_synthetic_geometry(self):
        parents,refs=self.fixture();original=copy.deepcopy((parents,refs));report=review(parents,refs)
        row=report['references'][0];self.assertEqual(len(row['boundary_pairs']),2)
        self.assertFalse(row['physical_opening_verified']);self.assertFalse(row['coordinate_control_verified'])
        self.assertEqual(report['world_geometry_additions'],0)
        for pair in row['boundary_pairs']:
            self.assertNotIn('geometry',pair)
            for boundary in pair['source_boundaries']:
                self.assertTrue(any(shape(boundary['geometry']).equals(shape(r['geometry'])) for r in parents))
        self.assertEqual((parents,refs),original)

    def test_full_label_span_hidden_dashed_and_budget(self):
        parents,refs=self.fixture();parents[0]['geometry']['coordinates']=((20,20),(50,20))
        self.assertEqual(review(parents,refs)['references'][0]['boundary_pairs'],[])
        parents,refs=self.fixture();parents[0]['paint_references'][0]['stroke_style']['dashes_pdf']='[1 2] 0'
        self.assertEqual(review(parents,refs)['references'][0]['boundary_pairs'],[])
        parents,refs=self.fixture();refs[0]['reference_occurrences'][0]['glyph_screen']['status']='withheld'
        self.assertEqual(review(parents,refs)['references'],[])
        parents,refs=self.fixture();report=review(parents,refs,max_checks=1)
        self.assertEqual(report['status'],'boundary_budget_withheld');self.assertEqual(report['references'],[])
        with self.assertRaises(ValueError):review(parents,refs,max_checks=True)
        refs[0]['page']+=1
        with self.assertRaises(ValueError):review(parents,refs)
