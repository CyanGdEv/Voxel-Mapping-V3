import unittest
import pymupdf
from voxel_mapper.glyph_visibility import screen_span


class GlyphTests(unittest.TestCase):
    def source(self):
        document=pymupdf.open();page=document.new_page(width=400,height=200)
        page.insert_text((40,60),'Timber wall cladding',fontsize=12,fontname='helv')
        return document,page,page.get_texttrace()[0]

    def test_visible_native_glyphs_supported_and_rotation_restored(self):
        document,page,span=self.source()
        try:
            page.set_rotation(90);result=screen_span(page,span)
            self.assertEqual(result['status'],'raster_consistent_candidate',result)
            self.assertEqual(page.rotation,90);self.assertFalse(result['visibility_verified'])
        finally:document.close()

    def test_white_mask_erasing_glyphs_withheld(self):
        document,page,span=self.source()
        try:
            page.draw_rect(pymupdf.Rect(span['bbox']),color=None,fill=(1,1,1),overlay=True)
            result=screen_span(page,span)
            self.assertEqual(result['status'],'withheld')
            self.assertTrue(any(g['unsupported_core_pixels']>0 for g in result['glyphs']))
        finally:document.close()

    def test_dark_cover_cannot_pass_by_matching_ink_only(self):
        document,page,span=self.source()
        try:
            page.draw_rect(pymupdf.Rect(span['bbox']),color=None,fill=(0,0,0),overlay=True)
            result=screen_span(page,span)
            self.assertEqual(result['status'],'withheld')
            self.assertGreater(result['unexpected_dark_ring_pixels'],0)
        finally:document.close()

    def test_unknown_font_and_budget_withheld(self):
        document,page,span=self.source()
        try:
            self.assertEqual(screen_span(page,{**span,'font':'unknown'})['status'],'withheld')
            self.assertEqual(screen_span(page,span,max_pixels=10)['status'],'withheld')
            self.assertEqual(screen_span(page,{**span,'opacity':.5})['status'],'withheld')
        finally:document.close()
