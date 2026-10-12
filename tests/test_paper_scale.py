from pathlib import Path
import tempfile
import unittest
import pymupdf
from voxel_mapper.mapped_alignment_checks import printed_scale_review

class PaperScaleTests(unittest.TestCase):
    def review(self,width,height,*,hidden=False,crop=False,rotation=0):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'paper.pdf'
            with pymupdf.open() as doc:
                page=doc.new_page(width=width*72/25.4,height=height*72/25.4)
                page.insert_text((40,60),'1/800 @ A1',fontsize=12)
                page.insert_text((40,90),'1/1600 @ A3',fontsize=12)
                if hidden:page.draw_rect((35,40,160,65),fill=(1,1,1),color=None)
                if crop:page.set_cropbox(pymupdf.Rect(0,0,page.rect.width-10,page.rect.height))
                page.set_rotation(rotation);doc.save(path)
            return printed_scale_review(path,1)
    def test_selects_actual_sheet_and_rotation(self):
        for width,height,denominator in [(841,594,800),(420,297,1600)]:
            for rotation in (0,90,180,270):
                result=self.review(width,height,rotation=rotation)
                self.assertEqual(result['status'],'one_visible_printed_scale')
                self.assertEqual(result['denominators'],[denominator])
    def test_hidden_resized_and_cropped_withheld(self):
        for args,kwargs in [((841,594),{'hidden':True}),((800,600),{}),((841,594),{'crop':True})]:
            self.assertIsNone(self.review(*args,**kwargs)['expected_metres_per_pdf_point'])

    def test_fragmented_duplicate_native_glyphs(self):
        from voxel_mapper.mapped_alignment_checks import fragmented_scale_runs
        from voxel_mapper.ordinary_surfaces import label_runs
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'glyphs.pdf'
            with pymupdf.open() as doc:
                page=doc.new_page(width=841*72/25.4,height=594*72/25.4)
                x=40
                for char in '1/800 @ A1':
                    for _ in range(2):page.insert_text((x,60),char,fontsize=12)
                    x+=pymupdf.get_text_length(char,fontsize=12)
                joined=fragmented_scale_runs(label_runs(page.get_texttrace()))
                self.assertEqual(len(joined),1)
                self.assertEqual(''.join(chr(c[0]) for c in joined[0]['chars']),'1/800 @ A1')
                self.assertEqual(len(joined[0]['trace_indices']),20)
                doc.save(path)
            self.assertEqual(printed_scale_review(path,1)['denominators'],[800])
    def test_nonstandard_native_unit_is_withheld(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'unit.pdf'
            with pymupdf.open() as doc:
                page=doc.new_page(width=420.5*72/25.4,height=297*72/25.4)
                page.insert_text((40,60),'1/800 @ A1',fontsize=12)
                doc.xref_set_key(page.xref,'UserUnit','2');doc.save(path)
            result=printed_scale_review(path,1)
            self.assertEqual(result['matching_paper_sizes'],['A1'])
            self.assertFalse(result['native_unit_supported'])
            self.assertIsNone(result['expected_metres_per_pdf_point'])
