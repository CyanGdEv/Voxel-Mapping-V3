import unittest
import fitz
from scripts.review_wicker_site_sections import inspect_page


class WickerSiteSectionReviewTests(unittest.TestCase):
    def test_combined_envelope_is_not_a_separate_shop_height(self):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((20,30), 'Station & Shop Building to 192.2')
            page.insert_text((20,60), 'Shop Building to 189.75')
            review = inspect_page(page, 'Sections AA BB Proposed')
            values = [(r['kind'], r['value_metres']) for r in review['level_claims']]
            self.assertEqual(values, [('combined_station_shop_top',192.2),('shop_building_top',189.75)])
            self.assertFalse(review['horizontal_geometry_eligible'])
            self.assertFalse(review['registration_verified'])
            for claim in review['level_claims']:
                self.assertFalse(claim['visible_text_verified'])
                self.assertFalse(claim['vertical_datum_verified'])
                self.assertTrue(claim['native_word_bboxes'])

    def test_overlapping_state_markers_require_visibility_review(self):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((20,30), 'Existing')
            page.insert_text((20,30), 'Proposed')
            review = inspect_page(page, 'Section Plan CC DD Proposed')
            self.assertEqual(len(review['overlapping_incompatible_title_markers']),1)
            self.assertTrue(review['text_visibility_review_required'])
            self.assertEqual(review['source_state_from_attachment_label'],'proposed')

    def test_separate_markers_do_not_form_an_overpaint_conflict(self):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((20,30), 'Existing')
            page.insert_text((20,90), 'Proposed')
            self.assertFalse(inspect_page(page,'Section GG HH Proposed')['text_visibility_review_required'])

    def test_xy_annotation_does_not_certify_plan_registration(self):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((20,30), 'X=1800 Y=1570')
            result = inspect_page(page,'Proposed Site Plan')
            self.assertTrue(result['untyped_xy_annotation_present'])
            self.assertFalse(result['registration_verified'])
            self.assertFalse(result['reference_notes']['national_grid_claim'])

if __name__ == '__main__': unittest.main()
