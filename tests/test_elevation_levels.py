import copy
import unittest
from unittest.mock import patch

import pymupdf

from voxel_mapper.elevation_levels import extract,relative_reference

UNIT=100*.0254/72


class LevelTests(unittest.TestCase):
    def drawing(self,second=True):
        doc=pymupdf.open();page=doc.new_page(width=500,height=400)
        def marker(y,text):
            page.draw_circle((300,y),10,color=(0,0,0))
            page.draw_rect(pymupdf.Rect(300,y,310,y+10),fill=(0,0,0),color=None)
            page.draw_rect(pymupdf.Rect(290,y-10,300,y),fill=(0,0,0),color=None)
            page.draw_line((250,y),(290,y))
            width=pymupdf.get_text_length(text,fontname='helv',fontsize=10)
            page.insert_text((280-width,y-5),text,fontsize=10)
        marker(220,'Shop Level + 100.00')
        if second:marker(220-1/UNIT,'Ride Exit Level +101.00')
        views=[{'view_key_candidate':['2967',26,4],'display_bounds':[50,100,250,250],
            'nominal_metres_per_pdf_point_candidate':UNIT}]
        return doc,views

    def test_native_markers_glyphs_and_relative_scale_keep_all_verification_gates_closed(self):
        doc,views=self.drawing()
        try:
            before=doc.tobytes(no_new_id=True);review=extract(doc[0],'a'*64,1,views)
            self.assertEqual(len(review['records']),2)
            self.assertTrue(all(r['status']=='unverified_native_level_reference_candidate' for r in review['records']))
            reference=relative_reference(review,views[0]['view_key_candidate'])
            self.assertEqual(reference['status'],'unverified_source_relative_shop_level')
            self.assertTrue(reference['level_scale_check_available'])
            self.assertAlmostEqual(reference['datum_y_display_points'],220)
            self.assertTrue(all(p['within_level_discovery_tolerance'] for p in reference['level_pair_checks']))
            self.assertFalse(reference['physical_floor_role_verified']);self.assertFalse(reference['vertical_datum_verified'])
            self.assertEqual(doc.tobytes(no_new_id=True),before)
        finally:doc.close()

    def test_no_nearest_view_selection_duplicate_floor_and_level_conflict_withheld(self):
        doc,views=self.drawing()
        try:
            duplicated=extract(doc[0],'a'*64,1,[*views,copy.deepcopy(views[0])])
            self.assertTrue(all(r['status']=='withheld_nonunique_level_label_line_or_view' for r in duplicated['records']))
            review=extract(doc[0],'a'*64,1,views)
            duplicate=copy.deepcopy(review);duplicate['records'].append(copy.deepcopy(duplicate['records'][0]))
            self.assertEqual(relative_reference(duplicate,views[0]['view_key_candidate'])['status'],'withheld_nonunique_or_missing_shop_level')
            review['records'][1]['label']['value_m_candidate']=105.
            self.assertEqual(relative_reference(review,views[0]['view_key_candidate'])['status'],'withheld_conflicting_relative_level_scale')
            with self.assertRaisesRegex(ValueError,'budget'):extract(doc[0],'a'*64,1,views,max_checks=1)
        finally:doc.close()

    def test_hidden_label_and_missing_native_datum_line_cannot_qualify(self):
        doc,views=self.drawing(second=False)
        try:
            with patch('voxel_mapper.elevation_levels.screen_span',return_value={'status':'withheld'}):
                result=extract(doc[0],'a'*64,1,views)
            self.assertEqual(result['records'][0]['status'],'withheld_level_label_visibility')
            paths=doc[0].get_drawings(extended=True)
            paths=[p for p in paths if not (len(p.get('items',[]))==1 and p['items'][0][0]=='l')]
            with patch.object(type(doc[0]),'get_drawings',return_value=paths):
                result=extract(doc[0],'a'*64,1,views)
            self.assertEqual(result['records'][0]['status'],'withheld_nonunique_level_label_line_or_view')
        finally:doc.close()


if __name__=='__main__':unittest.main()
