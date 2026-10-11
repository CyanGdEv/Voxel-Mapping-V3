import copy
import unittest
from shapely.geometry import box,mapping,shape
from tests import test_linework_boundaries as fixtures
from voxel_mapper.archway_ends import review


class ArchwayEndTests(unittest.TestCase):
    def fixture(self):
        parents=fixtures.LineworkTests().parents([[(20,20),(100,20)],[(20,80),(100,80.2)],[(20,20),(20,80)]])
        parents[-1]['paint_references'][0]['stroke_style']['dashes_pdf']='[2 2] 0'
        refs=[{'document_sha256':parents[0]['document_sha256'],'page':parents[0]['page'],
            'reference_occurrences':[{'reference_id':'archway:4','glyph_screen':{'status':'raster_consistent_candidate'},
                'label_geometry':mapping(box(40,40,60,60))}]}]
        return parents,refs

    def test_exact_skewed_source_connection_preserves_original_geometry(self):
        parents,refs=self.fixture();before=copy.deepcopy((parents,refs));report=review(parents,refs)
        self.assertEqual(len(report['connections']),1);connection=report['connections'][0]
        self.assertFalse(connection['physical_passage_verified']);self.assertFalse(connection['closed_opening_verified'])
        self.assertFalse(connection['coordinate_control_verified']);self.assertNotIn('geometry',connection)
        self.assertEqual(report['world_geometry_additions'],0)
        for record in connection['solid_sides']+[connection['dashed_end']]:
            self.assertTrue(any(shape(record['source_component_geometry']).equals(shape(p['geometry'])) for p in parents))
        self.assertEqual((parents,refs),before)

    def test_no_snap_hidden_labels_unknown_style_and_budget(self):
        parents,refs=self.fixture();parents[-1]['geometry']=mapping(shape(parents[-1]['geometry']))
        parents[-1]['geometry']['coordinates']=((20,20),(20,79.999))
        self.assertEqual(review(parents,refs)['connections'],[])
        parents,refs=self.fixture();refs[0]['reference_occurrences'][0]['glyph_screen']['status']='withheld'
        self.assertEqual(review(parents,refs)['connections'],[])
        parents,refs=self.fixture();parents[-1]['paint_references'][0]['stroke_style']['dashes_pdf']='unknown'
        self.assertEqual(review(parents,refs)['connections'],[])
        parents,refs=self.fixture();result=review(parents,refs,max_checks=1)
        self.assertEqual(result['status'],'end_budget_withheld');self.assertEqual(result['connections'],[])
        with self.assertRaises(ValueError):review(parents,refs,max_checks=True)
        refs[0]['page']=2
        with self.assertRaises(ValueError):review(parents,refs)

    def test_competing_sides_retained_and_polyline_segment_provenance(self):
        parents,refs=self.fixture();extra=fixtures.LineworkTests().parents([[(20,80),(110,80)]])[0]
        parents.append(extra)
        self.assertEqual(len(review(parents,refs)['connections']),2)
        parents,refs=self.fixture();parents[0]['geometry']['coordinates']=((10,10),(20,20),(100,20))
        result=review(parents,refs)
        self.assertEqual(len(result['connections']),1)
        self.assertEqual(result['connections'][0]['solid_sides'][0]['segment_index'],1)


if __name__=='__main__':unittest.main()
