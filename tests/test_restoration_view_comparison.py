import copy
import unittest

import pymupdf
from shapely.geometry import box,mapping

from voxel_mapper.building_facade_feed import scope_restoration_widths
from voxel_mapper.plan_elevation_correspondence import compare_restoration_widths,compare
from tests import test_plan_elevation_correspondence as fixtures


class RestorationViewTests(unittest.TestCase):
    def scope_fixture(self):
        anchors=[{'number':'1','target_page_point':[20,20]}, {'number':'2','target_page_point':[80,80]}]
        records=[{**a,'document_sha256':'a'*64,'page':1,'glyph_screen_status':'raster_consistent_candidate',
                  'drawing_view_candidate':{'view_key_candidate':['2967',26,2],
                    'nominal_metres_per_pdf_point_candidate':.1}} for a in anchors]
        alternatives=[{'id':name,'regions':[{'number':a['number'],
                      'boundary_review':{'geometry':mapping(box(0,0,width,80))}} for a in anchors]}
                      for name,width in [('first',100),('second',110)]]
        receipt={'document_sha256':'a'*64,'page':1,'raster_review':{
            'material_boundary_restoration_reviews':[{'anchors':anchors,'alternatives':alternatives}]}}
        return receipt,records

    def test_exact_view_scope_uses_original_rotation_without_mutation(self):
        receipt,records=self.scope_fixture();before=copy.deepcopy((receipt,records))
        doc=pymupdf.open();page=doc.new_page(width=300,height=200);page.set_rotation(90)
        try:
            result=scope_restoration_widths(receipt,records,page)[0]
            self.assertEqual(result['status'],'unverified_exact_anchor_view_scope')
            self.assertEqual(result['view_key_candidate'],['2967',26,2])
            self.assertEqual({r['region_width_m'] for r in result['region_widths']},{8.})
            self.assertEqual((receipt,records),before)
            # Serialized source records may use lists while original extraction uses tuples.
            records[0]['target_page_point']=tuple(records[0]['target_page_point'])
            self.assertEqual(scope_restoration_widths(receipt,records,page)[0]['status'],result['status'])
        finally:doc.close()

    def test_duplicate_anchor_cross_view_and_missing_source_cannot_scope(self):
        doc=pymupdf.open();page=doc.new_page(width=300,height=200)
        try:
            for kind in ('duplicate','wrong_source','wrong_view','unknown_scale'):
                receipt,records=self.scope_fixture()
                if kind=='duplicate':records.append(copy.deepcopy(records[0]))
                elif kind=='wrong_source':records[0]['document_sha256']='b'*64
                elif kind=='wrong_view':records[0]['drawing_view_candidate']['view_key_candidate']=['2967',26,3]
                else:records[0]['drawing_view_candidate']['nominal_metres_per_pdf_point_candidate']=None
                result=scope_restoration_widths(receipt,records,page)[0]
                self.assertEqual(result['status'],'withheld_restoration_view_scope')
                self.assertEqual(result['region_widths'],[])
        finally:doc.close()

    def test_equal_widths_keep_all_alternatives_and_wrong_view_cannot_match(self):
        review={'status':'unverified_exact_anchor_view_scope','view_key_candidate':['2967',26,2],
                'source_review_sha256':'source','region_widths':[
                    {'alternative_id':name,'number':'2','region_width_m':10.,'periodic_source_witnesses':[{}]}
                    for name in ('first','second')]}
        frame={'id':'frame','projected_extent_width_m':10.}
        matches,ambiguities=compare_restoration_widths(frame,['2967',26,2],[review],.25,lambda:None)
        self.assertEqual(len(matches),2)
        self.assertEqual(ambiguities[0]['compatible_alternative_ids'],['first','second'])
        self.assertEqual(ambiguities[0]['compatible_nominal_region_widths_m'],[10.])
        self.assertTrue(ambiguities[0]['multiple_compatible_separator_alternatives'])
        self.assertIsNone(ambiguities[0]['selected_physical_boundary_id'])
        self.assertEqual(compare_restoration_widths(frame,['2967',26,1],[review],.25,lambda:None),([],[]))
        values=fixtures.CorrespondenceTests().evidence();review['view_key_candidate']=values[1][0]['target_view_key_candidate']
        result=compare(*values,pymupdf.Matrix(1,0,0,-1,0,100),.1,None,
                       options={'max_checks':3},restoration_reviews=[review])
        self.assertEqual(result['status'],'correspondence_budget_withheld');self.assertEqual(result['views'],[])


if __name__=='__main__':unittest.main()
