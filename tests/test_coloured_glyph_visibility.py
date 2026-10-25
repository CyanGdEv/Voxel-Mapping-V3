"""Original-colour glyph support must reject erased and wrong-colour ink."""
import copy
import unittest

import pymupdf
import numpy as np

from voxel_mapper.glyph_visibility import screen_architectural_span,screen_span
from voxel_mapper.glyph_visibility import _colour_match


class ColouredGlyphTests(unittest.TestCase):
    def test_white_pixels_never_support_faint_isolated_reference_ink(self):
        # At low coverage, white is within the RGB tolerance of light grey
        # reference ink. It still supplies no actual source ink evidence.
        white=np.full((5,5,3),255,dtype=np.uint8)
        reference=np.full((5,5),195,dtype=np.uint8)
        self.assertFalse(_colour_match(white,(.8,.8,.8),reference).any())

    def source(self,colour=(.65,.65,.65),rotation=0):
        doc=pymupdf.open();page=doc.new_page(width=500,height=300)
        page.insert_text((80,150),'Plaza',fontsize=16,color=colour,rotate=rotation)
        self.addCleanup(doc.close)
        return doc,page,page.get_texttrace()[0]

    def test_original_rgb_and_gray_colours_use_native_font_without_substitution(self):
        for colour in ((.65,.65,.65),(.55,.35,.2),(.8,0,0),(0,.2,.8),(0,0,0)):
            for rotation in (0,90,180,270):
                with self.subTest(colour=colour,rotation=rotation):
                    _,page,span=self.source(colour,rotation)
                    result=screen_architectural_span(page,span)
                    self.assertEqual(result['status'],'raster_consistent_candidate',result)
                    self.assertFalse(result['visibility_verified'])
                    for actual,expected in zip(result['source_colour_rgb'],colour):
                        self.assertAlmostEqual(actual,expected,places=6)

    def test_white_black_same_colour_and_wrong_colour_covers_withhold(self):
        for colour in ((.65,.65,.65),(.7,0,0)):
            for cover in ((1,1,1),(0,0,0),colour,(0,.6,.1)):
                with self.subTest(colour=colour,cover=cover):
                    _,page,span=self.source(colour)
                    page.draw_rect(pymupdf.Rect(span['bbox']),color=None,fill=cover)
                    self.assertEqual(screen_span(page,span)['status'],'withheld')

    def test_black_glyphs_cannot_impersonate_grey_or_coloured_originals(self):
        _,page,span=self.source((0,0,0))
        for colour in ((.65,.65,.65),(.7,0,0)):
            forged=copy.deepcopy(span);forged['color']=colour
            self.assertEqual(screen_span(page,forged)['status'],'withheld')

    def test_wrong_colour_matching_luminance_does_not_pass(self):
        _,page,span=self.source((.7,0,0))
        forged=copy.deepcopy(span);forged['color']=(0,.21,0)
        self.assertEqual(screen_span(page,forged)['status'],'withheld')

    def test_lighter_grey_ink_cannot_impersonate_the_original_shade(self):
        _,page,span=self.source((.75,.75,.75))
        forged=copy.deepcopy(span);forged['color']=(.65,.65,.65)
        self.assertEqual(screen_span(page,forged)['status'],'withheld')

    def test_light_invalid_translucent_or_layered_text_stays_withheld(self):
        _,page,span=self.source()
        for value in ((.95,.95,.95),(1,1,1),(-.1,0,0),(float('nan'),0,0),(0,0,0,1),None):
            forged=copy.deepcopy(span);forged['color']=value
            self.assertEqual(screen_span(page,forged)['status'],'withheld')
        for key,value in (('opacity',.5),('layer','hidden'),('type',3)):
            forged=copy.deepcopy(span);forged[key]=value
            self.assertEqual(screen_span(page,forged)['status'],'withheld')

    def test_covered_single_letter_cannot_be_hidden_by_other_supported_glyphs(self):
        _,page,span=self.source()
        page.draw_rect(pymupdf.Rect(span['chars'][2][3]),color=None,fill=(1,1,1))
        self.assertEqual(screen_span(page,span)['status'],'withheld')

    def test_isolated_original_cff_glyphs_match_colour_and_reject_covers(self):
        from tests.test_glyph_visibility import GlyphTests
        for cover in (None,(1,1,1),(0,0,0),(.65,.65,.65)):
            with self.subTest(cover=cover):
                doc,page,_=GlyphTests().simple_cff_source()
                try:
                    content=page.get_contents()[0]
                    doc.update_stream(content,b'0.65 0.65 0.65 rg\n'+doc.xref_stream(content))
                    page=doc.reload_page(page);span=page.get_texttrace()[0]
                    if cover is not None:page.draw_rect(pymupdf.Rect(span['bbox']),color=None,fill=cover)
                    result=screen_span(page,span,isolate_glyphs=True)
                    self.assertEqual(result['status'],'raster_consistent_candidate' if cover is None else 'withheld',result)
                    self.assertEqual(result['source_colour_support'],'original_rgb_over_white_projection')
                finally:doc.close()


if __name__=='__main__':unittest.main()
