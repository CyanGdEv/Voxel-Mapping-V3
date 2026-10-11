import unittest
import pymupdf
from voxel_mapper.glyph_visibility import screen_span,screen_architectural_span,VERSION,INK_VERSION


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

    def test_arbitrary_native_rotation_preserves_exact_glyph_positions(self):
        for angle in [0.093, 37, 179.907, -63]:
            with pymupdf.open() as document:
                page=document.new_page(width=400,height=300)
                anchor=pymupdf.Point(180,150)
                page.insert_text(anchor,'stone paving',fontsize=12,morph=(anchor,pymupdf.Matrix(angle)))
                span=page.get_texttrace()[0]
                result=screen_span(page,span)
                self.assertEqual(result['status'],'raster_consistent_candidate',(angle,result))
                page.draw_rect(pymupdf.Rect(span['bbox']),fill=(1,1,1),color=None)
                self.assertEqual(screen_span(page,span)['status'],'withheld')

    def subset_source(self,*,thin=False,fontsize=12):
        import io
        from fontTools.fontBuilder import FontBuilder
        from fontTools.pens.ttGlyphPen import TTGlyphPen
        builder=FontBuilder(1000,isTTF=True)
        builder.setupGlyphOrder(['.notdef','privateB'])
        builder.setupCharacterMap({0xF001:'privateB'})
        empty=TTGlyphPen(None); ink=TTGlyphPen(None)
        right=112 if thin else 500
        ink.moveTo((100,0));ink.lineTo((right,0));ink.lineTo((right,700));ink.lineTo((100,700));ink.closePath()
        builder.setupGlyf({'.notdef':empty.glyph(),'privateB':ink.glyph()})
        builder.setupHorizontalMetrics({'.notdef':(600,0),'privateB':(600,100)})
        builder.setupHorizontalHeader(ascent=800,descent=-200)
        builder.setupNameTable({'familyName':'NativeGlyphTest','styleName':'Regular','uniqueFontIdentifier':'NativeGlyphTest','fullName':'NativeGlyphTest','psName':'NativeGlyphTest'})
        builder.setupOS2(sTypoAscender=800,sTypoDescender=-200,usWinAscent=800,usWinDescent=200)
        builder.setupPost();builder.setupMaxp(); buffer=io.BytesIO();builder.save(buffer)
        document=pymupdf.open();page=document.new_page(width=400,height=200)
        font_xref=page.insert_font(fontname='native',fontbuffer=buffer.getvalue())
        document.xref_set_key(font_xref,'BaseFont','/NativeGlyphTest')
        page.insert_text((100,100),chr(0xF001),fontsize=fontsize,fontname='native')
        span=page.get_texttrace()[0]
        # Keep the original glyph ID despite a different decoded character.
        span={**span,'chars':[(98,*c[1:]) for c in span['chars']]}
        return document,page,span

    def test_subset_font_keeps_original_glyph_ids_without_unicode_reencoding(self):
        document,page,span=self.subset_source()
        try:
            result=screen_span(page,span)
            self.assertEqual(result['status'],'raster_consistent_candidate',result)
            self.assertEqual(result['glyph_encoding'],'source_glyph_ids')
            page.draw_rect(pymupdf.Rect(span['bbox']),color=None,fill=(1,1,1))
            self.assertEqual(screen_span(page,span)['status'],'withheld')
        finally:document.close()

    def test_isolated_ink_recovers_clipped_character_box_without_changing_default(self):
        document,page,span=self.subset_source()
        try:
            c=span['chars'][0]
            clipped={**span,'chars':[(c[0],c[1],c[2],(90,80,91,81))]}
            page.set_rotation(90)
            original=screen_span(page,clipped)
            self.assertEqual(original['status'],'withheld')
            self.assertEqual(original['version'],VERSION)
            self.assertNotIn('glyph_support_basis',original)
            recovered=screen_architectural_span(page,clipped)
            self.assertEqual(recovered['status'],'raster_consistent_candidate',recovered)
            self.assertEqual(recovered['version'],INK_VERSION)
            self.assertEqual(recovered['native_character_box_screen'],original)
            self.assertGreater(recovered['glyphs'][0]['core_pixels'],3)
            self.assertEqual(recovered['glyphs'][0]['unsupported_core_pixels'],0)
            self.assertEqual(page.rotation,90)
            self.assertEqual(screen_span(page,clipped),original)
            page.draw_rect(pymupdf.Rect(span['bbox']),color=None,fill=(1,1,1))
            self.assertEqual(screen_architectural_span(page,clipped)['status'],'withheld')
            self.assertEqual(page.rotation,90)
        finally:document.close()

    def test_isolated_blank_glyph_cannot_borrow_neighbor_ink_and_budget_is_bounded(self):
        document,page,span=self.subset_source()
        try:
            c=span['chars'][0]
            blank={**span,'chars':[c,(98,0,c[2],c[3])]}
            result=screen_span(page,blank,isolate_glyphs=True)
            self.assertEqual(result['status'],'withheld')
            self.assertEqual(result['glyphs'][1]['core_pixels'],0)
            many={**span,'chars':[c]*500}
            result=screen_span(page,many,zoom=24,isolate_glyphs=True)
            self.assertEqual(result['reason'],'Isolated glyph raster budget exceeded')
            self.assertEqual(page.rotation,0)
            with self.assertRaises(ValueError):screen_span(page,span,isolate_glyphs=1)
        finally:document.close()

    def test_isolated_ink_rejects_overpaint_and_missing_source_font(self):
        document,page,span=self.subset_source()
        try:
            self.assertEqual(screen_span(page,{**span,'font':'unknown'},isolate_glyphs=True)['status'],'withheld')
            page.draw_rect(pymupdf.Rect(span['bbox']),color=None,fill=(0,0,0))
            self.assertEqual(screen_span(page,span,isolate_glyphs=True)['status'],'withheld')
        finally:document.close()

    def test_antialiased_thin_original_glyph_is_supported_but_erasure_is_not(self):
        document,page,span=self.subset_source(thin=True,fontsize=4)
        try:
            self.assertEqual(screen_span(page,span)['status'],'withheld')
            result=screen_architectural_span(page,span)
            self.assertEqual(result['status'],'raster_consistent_candidate',result)
            self.assertEqual(result['glyph_ink_grayscale_threshold'],200)
            self.assertGreater(result['glyphs'][0]['core_pixels'],3)
            page.draw_rect(pymupdf.Rect(span['bbox']),color=None,fill=(1,1,1))
            self.assertEqual(screen_architectural_span(page,span)['status'],'withheld')
        finally:document.close()

    def test_one_missing_isolated_glyph_with_visible_neighbor_is_withheld(self):
        document,page,span=self.subset_source()
        try:
            page.insert_text((115,100),chr(0xF001),fontsize=12,fontname='native')
            second=page.get_texttrace()[-1]
            joined={**span,'chars':span['chars']+[(98,*c[1:]) for c in second['chars']],
                    'bbox':tuple(pymupdf.Rect(span['bbox'])|pymupdf.Rect(second['bbox']))}
            self.assertEqual(screen_span(page,joined,isolate_glyphs=True)['status'],'raster_consistent_candidate')
            page.draw_rect(pymupdf.Rect(second['bbox']),color=None,fill=(1,1,1))
            result=screen_span(page,joined,isolate_glyphs=True)
            self.assertEqual(result['status'],'withheld')
            self.assertEqual(result['glyphs'][0]['unsupported_core_pixels'],0)
            self.assertGreater(result['glyphs'][1]['unsupported_core_pixels'],0)
        finally:document.close()

    def test_unknown_font_and_budget_withheld(self):
        document,page,span=self.source()
        try:
            self.assertEqual(screen_span(page,{**span,'font':'unknown'})['status'],'withheld')
            self.assertEqual(screen_span(page,span,max_pixels=10)['status'],'withheld')
            self.assertEqual(screen_span(page,{**span,'opacity':.5})['status'],'withheld')
        finally:document.close()
