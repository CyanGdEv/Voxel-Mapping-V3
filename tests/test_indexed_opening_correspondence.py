import copy
import unittest

from shapely.geometry import box,mapping

from voxel_mapper.indexed_opening_correspondence import compare
from voxel_mapper.raster_opening_scan import scan
from voxel_mapper.building_spec import digest
from tests import test_raster_opening_scan as fixtures


class IndexedCorrespondenceTests(unittest.TestCase):
    def evidence(self):
        indexed=scan(fixtures.OpeningScanTests().frame(),representation='indexed')
        view={'indexed_opening_scan':indexed,'document_sha256':'a'*64,'page':1,
            'view_key_candidate':['2967',26,4],'source_png_sha256':'b'*64,'indexed_scan_sha256':digest(indexed),
            'pixel_edge_to_pdf_native_matrix':[1,0,0,-1,0,160]}
        region={'id':'region','document_sha256':'a'*64,'page':1,'view_key_candidate':['2967',26,4],
            'display_geometry':mapping(box(0,0,240,160)),'nominal_metres_per_pdf_point_candidate':.1,
            'component_class_candidate':'wall_face','unrotated_mupdf_to_pdf_native_matrix':[1,0,0,-1,0,160],
            'unrotated_mupdf_to_display_matrix':[1,0,0,1,0,0]}
        projection={'source_gap_id':'gap','width_m':12.7,'position_interval_m':[4.3,17.]}
        return view,projection,{'id':'frame','projected_extent_width_m':24.},region

    def test_width_and_position_match_retains_all_threshold_references(self):
        evidence=self.evidence();before=copy.deepcopy(evidence)
        result=compare(*evidence,.25,lambda:None)
        self.assertTrue(result['matches']);self.assertEqual(evidence,before)
        for match in result['matches']:
            self.assertFalse(match['physical_correspondence_verified'])
            self.assertFalse(match['floor_or_vertical_datum_verified'])
            family=evidence[0]['indexed_opening_scan']['index']['consensus_families'][match['indexed_family_index']]
            self.assertEqual(match['second_threshold_pair_indices'],family['second_pair_indices'])
        evidence[1]['position_interval_m']=[0,12.7]
        self.assertEqual(compare(*evidence,.25,lambda:None)['matches'],[])
        evidence[1]['position_interval_m']=[7.,19.7]
        reversed_matches=compare(*evidence,.25,lambda:None)['matches']
        self.assertTrue(reversed_matches)
        self.assertTrue(all(m['elevation_x_reversed'] for m in reversed_matches))

    def test_index_query_work_uses_whole_candidate_budget(self):
        import pymupdf
        from voxel_mapper.plan_elevation_correspondence import compare as compare_plan
        from tests import test_plan_elevation_correspondence as plan_fixtures
        values=plan_fixtures.CorrespondenceTests().evidence()
        view,_,_,_=self.evidence()
        view['view_key_candidate']=values[1][0]['target_view_key_candidate']
        view['scan']={'status':'scan_budget_withheld','candidates':[]}
        values[3][:]=[view]
        values[2][0].update(document_sha256=view['document_sha256'],page=1)
        result=compare_plan(*values,pymupdf.Matrix(1,0,0,-1,0,100),.1,None,options={'max_checks':3})
        self.assertEqual(result['status'],'correspondence_budget_withheld')
        self.assertEqual(result['views'],[])

    def test_source_relative_height_and_component_overlap_do_not_promote_openings(self):
        view,projection,frame,region=self.evidence()
        view['relative_level_reference']={'status':'unverified_source_relative_shop_level',
            'document_sha256':view['document_sha256'],'page':1,'view_key_candidate':view['view_key_candidate'],
            'nominal_metres_per_pdf_point_candidate':.1,'datum_y_display_points':152.45,
            'reference_id':'source-level','source_level_review_sha256':'c'*64,'level_scale_check_available':True}
        result=compare(view,projection,frame,region,.25,lambda:None,source_regions=[region])
        self.assertTrue(result['matches'])
        for match in result['matches']:
            vertical=match['relative_height_and_component_review']
            self.assertAlmostEqual(vertical['nominal_bottom_above_printed_shop_level_m'],2.745)
            self.assertFalse(vertical['bottom_within_shop_level_discovery_tolerance'])
            self.assertFalse(vertical['physical_floor_role_verified']);self.assertFalse(vertical['vertical_datum_verified'])
            component=match['component_region_review']
            self.assertTrue(component['same_view_wall_region_comparisons'][0]['rectangle_covered_by_region_candidate'])
            self.assertFalse(component['complete_wall_component_scope_verified'])
            self.assertFalse(match['physical_correspondence_verified'])
        view['relative_level_reference']['datum_y_display_points']=125.
        near=compare(view,projection,frame,region,.25,lambda:None)['matches'][0]
        self.assertTrue(near['relative_height_and_component_review']['bottom_within_shop_level_discovery_tolerance'])
        self.assertFalse(near['physical_correspondence_verified'])
        view['relative_level_reference']['document_sha256']='d'*64
        rejected=compare(view,projection,frame,region,.25,lambda:None)['matches'][0]
        self.assertEqual(rejected['relative_height_and_component_review']['status'],'withheld_source_relative_level_reference')

    def test_wrong_source_missing_hash_skew_and_withheld_index_cannot_match(self):
        for fault in ('source','hash','skew','budget'):
            view,projection,frame,region=self.evidence()
            if fault=='source':view['document_sha256']='c'*64
            elif fault=='hash':view.pop('source_png_sha256')
            elif fault=='skew':view['pixel_edge_to_pdf_native_matrix'][1]=.1
            else:view['indexed_opening_scan']={'status':'scan_budget_withheld','index':None}
            result=compare(view,projection,frame,region,.25,lambda:None)
            self.assertTrue(result['status'].startswith('withheld_'));self.assertEqual(result['matches'],[])


if __name__=='__main__':unittest.main()
