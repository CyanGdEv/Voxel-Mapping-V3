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

    def test_subset_font_keeps_original_glyph_ids_without_unicode_reencoding(self):
        import io
        from fontTools.fontBuilder import FontBuilder
        from fontTools.pens.ttGlyphPen import TTGlyphPen
        builder=FontBuilder(1000,isTTF=True)
        builder.setupGlyphOrder(['.notdef','privateB'])
        builder.setupCharacterMap({0xF001:'privateB'})
        empty=TTGlyphPen(None); ink=TTGlyphPen(None)
        ink.moveTo((100,0));ink.lineTo((500,0));ink.lineTo((500,700));ink.lineTo((100,700));ink.closePath()
        builder.setupGlyf({'.notdef':empty.glyph(),'privateB':ink.glyph()})
        builder.setupHorizontalMetrics({'.notdef':(600,0),'privateB':(600,100)})
        builder.setupHorizontalHeader(ascent=800,descent=-200)
        builder.setupNameTable({'familyName':'NativeGlyphTest','styleName':'Regular','uniqueFontIdentifier':'NativeGlyphTest','fullName':'NativeGlyphTest','psName':'NativeGlyphTest'})
        builder.setupOS2(sTypoAscender=800,sTypoDescender=-200,usWinAscent=800,usWinDescent=200)
        builder.setupPost();builder.setupMaxp(); buffer=io.BytesIO();builder.save(buffer)
        with pymupdf.open() as document:
            page=document.new_page(width=400,height=200)
            font_xref=page.insert_font(fontname='native',fontbuffer=buffer.getvalue())
            document.xref_set_key(font_xref,'BaseFont','/NativeGlyphTest')
            page.insert_text((100,100),chr(0xF001),fontsize=12,fontname='native')
            span=page.get_texttrace()[0]
            # Same glyph ID, different decoded annotation character, as in a
            # CAD PDF whose ToUnicode names its custom subset glyph as 'b'.
            span={**span,'chars':[(98,*c[1:]) for c in span['chars']]}
            result=screen_span(page,span)
            self.assertEqual(result['status'],'raster_consistent_candidate',result)
            self.assertEqual(result['glyph_encoding'],'source_glyph_ids')
            page.draw_rect(pymupdf.Rect(span['bbox']),color=None,fill=(1,1,1))
            self.assertEqual(screen_span(page,span)['status'],'withheld')

    def test_unknown_font_and_budget_withheld(self):
        document,page,span=self.source()
        try:
            self.assertEqual(screen_span(page,{**span,'font':'unknown'})['status'],'withheld')
            self.assertEqual(screen_span(page,span,max_pixels=10)['status'],'withheld')
            self.assertEqual(screen_span(page,{**span,'opacity':.5})['status'],'withheld')
        finally:document.close()
