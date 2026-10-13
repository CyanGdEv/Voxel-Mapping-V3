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

    def cff_font(self, *, alternative=False, different_ink=False, matrix=None):
        import io
        from fontTools.fontBuilder import FontBuilder
        from fontTools.pens.t2CharStringPen import T2CharStringPen
        from fontTools.cffLib import FDArrayIndex, FontDict, FDSelect
        builder = FontBuilder(1000, isTTF=False)
        names = ['.notdef', 'cid00042', 'cid00421']
        builder.setupGlyphOrder(names)
        builder.setupCharacterMap({0xF001: names[1], 0xF002: names[2]})
        strings = {}
        for name in names:
            pen = T2CharStringPen(600, None)
            if name != '.notdef':
                right = 900 if different_ink else 500
                pen.moveTo((100, 0)); pen.lineTo((right, 0))
                pen.lineTo((right, 700)); pen.lineTo((100, 700)); pen.closePath()
            strings[name] = pen.getCharString()
        name = 'AlternativeCID' if alternative else 'NativeCIDTest'
        builder.setupCFF(name, {'FullName': name, 'FamilyName': name, 'Weight': 'Regular'}, strings, {})
        cff = builder.font['CFF '].cff; top = cff[cff.fontNames[0]]
        top.ROS = ('Adobe', 'Identity', 0); top.CIDCount = 422
        if matrix is not None: top.FontMatrix = matrix
        array = FDArrayIndex(); fd = FontDict(); fd.Private = top.Private
        array.append(fd); top.FDArray = array
        select = FDSelect(); select.gidArray = [0]*len(names)
        top.FDSelect = select; del top.Private
        output = io.BytesIO(); cff.compile(output, builder.font)
        return output.getvalue()

    def cff_source(self):
        document = pymupdf.open(); page = document.new_page(width=400, height=200)
        xref = page.insert_font(fontname='native', fontbuffer=self.cff_font())
        document.xref_set_key(xref, 'BaseFont', '/NativeCIDTest')
        content = document.get_new_xref(); document.update_object(content, '<<>>')
        document.update_stream(content, b'BT /native 12 Tf 1 0 0 1 100 100 Tm <002a01a5> Tj ET')
        document.xref_set_key(page.xref, 'Contents', f'{content} 0 R')
        span = page.get_texttrace()[0]
        # Native CIDs 42 and 421 are neither Unicode values nor charset ordinals.
        span = {**span, 'chars': [(97+i, *c[1:]) for i, c in enumerate(span['chars'])]}
        return document, page, span

    def test_cid_cff_preserves_native_identifiers_and_rejects_overpaint(self):
        for color in [(1, 1, 1), (0, 0, 0)]:
            document, page, span = self.cff_source()
            try:
                page.set_rotation(90)
                result = screen_span(page, span)
                self.assertEqual(result['status'], 'raster_consistent_candidate', result)
                self.assertEqual(result['glyph_encoding'], 'source_cff_charset_cids')
                self.assertEqual([c[1] for c in span['chars']], [42, 421])
                self.assertTrue(all(g['core_pixels'] >= 3 for g in result['glyphs']))
                page.draw_rect(pymupdf.Rect(span['bbox']), color=None, fill=color)
                self.assertEqual(screen_span(page, span)['status'], 'withheld')
                self.assertEqual(page.rotation, 90)
            finally: document.close()

    def test_cff_unknown_cid_is_not_reinterpreted_as_charset_index(self):
        document, page, span = self.cff_source()
        try:
            c = span['chars'][0]
            unknown = {**span, 'chars': [(c[0], 1, *c[2:])]}
            result = screen_span(page, unknown)
            self.assertEqual(result['status'], 'withheld')
            self.assertIn('outside original charset', result['reason'])
        finally: document.close()

    def test_cff_same_name_alternatives_require_unique_original_ink(self):
        for different_ink in [False, True]:
            document, page, span = self.cff_source()
            try:
                xref = page.insert_font(fontname='other', fontbuffer=self.cff_font(
                    alternative=True, different_ink=different_ink))
                document.xref_set_key(xref, 'BaseFont', '/NativeCIDTest')
                result = screen_span(page, span)
                self.assertEqual(result['status'], 'raster_consistent_candidate' if different_ink else 'withheld', result)
                self.assertEqual(result['font_resource_resolution']['candidate_count'], 2)
                self.assertEqual(result['font_resource_resolution']['consistent_candidate_count'], 1 if different_ink else 2)
            finally: document.close()

    def test_cff_nonstandard_matrix_and_malformed_font_are_withheld(self):
        from voxel_mapper.glyph_visibility import cff_glyph_codes
        document, page, span = self.cff_source()
        try:
            with self.assertRaisesRegex(ValueError, 'standard-matrix'):
                cff_glyph_codes(self.cff_font(matrix=[.002, 0, 0, .002, 0, 0]), span['chars'])
            for cid in [-1, 65536, True]:
                c = span['chars'][0]
                with self.assertRaisesRegex(ValueError, 'outside original charset'):
                    cff_glyph_codes(self.cff_font(), [(c[0], cid, *c[2:])])
        finally: document.close()

    def add_font_alternative(self,document,page,*,different_ink):
        import io
        from fontTools.ttLib import TTFont
        buffer=document.extract_font(page.get_fonts()[0][0])[3]
        with TTFont(io.BytesIO(buffer)) as font:
            font['name'].setName('Alternative original subset',0,3,1,1033)
            if different_ink:
                coordinates=font['glyf']['privateB'].coordinates
                for i,(x,y) in enumerate(coordinates):
                    if x==500:coordinates[i]=(900,y)
            output=io.BytesIO();font.save(output)
        xref=page.insert_font(fontname='otherSubset',fontbuffer=output.getvalue())
        document.xref_set_key(xref,'BaseFont','/NativeGlyphTest')

    def test_same_name_subsets_require_one_original_font_with_full_raster_support(self):
        import hashlib
        document,page,span=self.subset_source()
        try:
            original=hashlib.sha256(document.extract_font(page.get_fonts()[0][0])[3]).hexdigest()
            self.add_font_alternative(document,page,different_ink=True)
            result=screen_span(page,span)
            self.assertEqual(result['status'],'raster_consistent_candidate',result)
            self.assertEqual(result['source_font_sha256'],original)
            self.assertEqual(result['font_resource_resolution']['candidate_count'],2)
            self.assertEqual(result['font_resource_resolution']['consistent_candidate_count'],1)
            self.assertFalse(result['visibility_verified'])
            page.draw_rect(pymupdf.Rect(span['bbox']),fill=(1,1,1),color=None)
            self.assertEqual(screen_span(page,span)['status'],'withheld')
        finally:document.close()

    def test_same_name_fonts_with_identical_ink_remain_ambiguous(self):
        document,page,span=self.subset_source()
        try:
            self.add_font_alternative(document,page,different_ink=False)
            result=screen_span(page,span)
            self.assertEqual(result['status'],'withheld',result)
            self.assertEqual(result['font_resource_resolution']['consistent_candidate_count'],2)
        finally:document.close()

    def test_unavailable_same_name_font_cannot_be_eliminated_by_failed_screen(self):
        document,page,span=self.subset_source()
        try:
            xref=page.insert_font(fontname='helv')
            document.xref_set_key(xref,'BaseFont','/NativeGlyphTest')
            result=screen_span(page,span)
            self.assertEqual(result['status'],'withheld',result)
            self.assertEqual(result['reason'],'Not all source font alternatives could be screened')
            self.assertEqual(result['font_resource_resolution']['consistent_candidate_count'],1)
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
