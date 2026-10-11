import unittest
from unittest.mock import patch
import pymupdf
from voxel_mapper.benchmark_label_evidence import review


class BenchmarkLabelTests(unittest.TestCase):
    def page(self, extra=False):
        doc=pymupdf.open();page=doc.new_page()
        page.insert_text((40,40),'O.S.B.M.')
        page.insert_text((40,58),'(value 178.90m)')
        if extra:page.insert_text((40,76),'(value 180.00m)')
        return doc,page

    def test_original_labels_values_and_layout_are_retained_without_datum(self):
        doc,page=self.page()
        try:
            with patch('voxel_mapper.benchmark_label_evidence.screen_architectural_span',return_value={'status':'raster_consistent_candidate'}):
                r=review(page,'a'*64,1)
            self.assertEqual(r['printed_values'][0]['printed_value'],178.9)
            self.assertEqual(r['printed_values'][0]['printed_units'],'m')
            self.assertEqual(r['layout_links'][0]['status'],'one_visible_printed_value_layout_candidate')
            self.assertFalse(r['vertical_datum_verified']);self.assertFalse(r['coordinate_control_verified'])
            self.assertEqual(r['markers'][0]['text'],'O.S.B.M.')
            self.assertEqual(r['coordinate_frame'],'pdf_native_points_y_up')
        finally:doc.close()

    def test_competing_values_are_not_selected_and_hidden_markers_withhold(self):
        doc,page=self.page(extra=True)
        try:
            with patch('voxel_mapper.benchmark_label_evidence.screen_architectural_span',return_value={'status':'raster_consistent_candidate'}):
                r=review(page,'a'*64,1)
            self.assertEqual(len(r['layout_links'][0]['candidate_value_ids']),2)
            self.assertEqual(r['layout_links'][0]['status'],'missing_or_competing_value_layout')
            with patch('voxel_mapper.benchmark_label_evidence.screen_architectural_span',return_value={'status':'hidden'}):
                r=review(page,'a'*64,1)
            self.assertEqual(r['layout_links'][0]['status'],'benchmark_visibility_withheld')
        finally:doc.close()

    def test_budget_discards_partial_records_and_page_rotation_is_preserved(self):
        doc,page=self.page(extra=True)
        try:
            page.set_rotation(90)
            with patch('voxel_mapper.benchmark_label_evidence.screen_architectural_span',return_value={'status':'raster_consistent_candidate'}):
                r=review(page,'a'*64,1,max_checks=1)
            self.assertEqual(page.rotation,90)
            self.assertEqual(r['status'],'benchmark_budget_withheld')
            self.assertEqual(r['markers'],[]);self.assertEqual(r['printed_values'],[]);self.assertEqual(r['layout_links'],[])
        finally:doc.close()
