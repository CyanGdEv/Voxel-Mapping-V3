"""Bind narrative glyphs to original direct resources without font substitution."""
import copy
import io
import unittest

import pymupdf
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from voxel_mapper.glyph_visibility import screen_architectural_span, screen_span


def embedded_alternative():
    builder=FontBuilder(1000,isTTF=True)
    builder.setupGlyphOrder(['.notdef','A']);builder.setupCharacterMap({65:'A'})
    empty=TTGlyphPen(None);ink=TTGlyphPen(None)
    ink.moveTo((100,0));ink.lineTo((500,0));ink.lineTo((500,700));ink.lineTo((100,700));ink.closePath()
    builder.setupGlyf({'.notdef':empty.glyph(),'A':ink.glyph()})
    builder.setupHorizontalMetrics({'.notdef':(600,0),'A':(600,100)})
    builder.setupHorizontalHeader(ascent=800,descent=-200)
    builder.setupNameTable({'familyName':'ArialMT','styleName':'Regular',
        'uniqueFontIdentifier':'Synthetic unrelated ArialMT subset','fullName':'ArialMT','psName':'ArialMT'})
    builder.setupOS2(sTypoAscender=800,sTypoDescender=-200,usWinAscent=800,usWinDescent=200)
    builder.setupPost();builder.setupMaxp();buffer=io.BytesIO();builder.save(buffer)
    return buffer.getvalue()


def fixture(*, alternative=True, implicit=False, duplicate=False, override=False, filler=0):
    doc=pymupdf.open();page=doc.new_page(width=600,height=500)
    descriptor=doc.get_new_xref()
    doc.update_object(descriptor,'<< /Type /FontDescriptor /FontName /ArialMT /Flags 32 '
        '/FontBBox [-665 -325 2000 1040] /ItalicAngle 0 /Ascent 905 /Descent -211 /CapHeight 700 /StemV 80 >>')
    font=doc.get_new_xref()
    widths=' '.join(str(round(pymupdf.Font('helv').glyph_advance(c)*1000)) for c in range(32,127))
    doc.update_object(font,f'<< /Type /Font /Subtype /TrueType /BaseFont /ArialMT /Name /F1 '
        f'/Encoding /WinAnsiEncoding /FirstChar 32 /LastChar 126 /Widths [{widths}] /FontDescriptor {descriptor} 0 R >>')
    resources=int(doc.xref_get_key(page.xref,'Resources')[1].split()[0])
    entries=f'/F1 {font} 0 R'
    if duplicate:
        second=doc.get_new_xref();doc.update_object(second,doc.xref_object(font))
        entries+=f' /F2 {second} 0 R'
    doc.xref_set_key(resources,'Font','<< '+entries+' >>')
    if alternative:
        other=page.insert_font(fontname='F7',fontbuffer=embedded_alternative())
        doc.xref_set_key(other,'BaseFont','/ArialMT')
    if override:
        state=doc.get_new_xref();doc.update_object(state,f'<< /Type /ExtGState /Font [{font} 0 R 11.04] >>')
        doc.xref_set_key(resources,'ExtGState',f'<< /GS1 {state} 0 R >>')
    positioning='40 400 Td' if implicit else '1 0 0 1 40 400 Tm'
    command=f'BT /F1 11.04 Tf {positioning} '+('/GS1 gs ' if override else '')+'[(The rows are 35.85m long) 15 ( and 2.5m wide.)] TJ ET'
    if duplicate:
        command+='\n'+command.replace('/F1','/F2')
    for i in range(filler):
        command+=f'\nBT /F1 8 Tf 1 0 0 1 40 {370-i*10} Tm (Unrelated paragraph {i}) Tj ET'
    contents=doc.get_new_xref();doc.update_object(contents,'<<>>');doc.update_stream(contents,command.encode())
    doc.xref_set_key(page.xref,'Contents',f'{contents} 0 R')
    data=doc.tobytes();doc.close();doc=pymupdf.open(stream=data,filetype='pdf')
    page=doc[0];return doc,page,page.get_texttrace()[0]


class DesignGlyphTests(unittest.TestCase):
    def source(self,**kwargs):
        doc,page,span=fixture(**kwargs);self.addCleanup(doc.close)
        return doc,page,span

    def test_direct_unembedded_resource_is_bound_despite_unrelated_same_name_embedded_font(self):
        doc,page,span=self.source()
        before=page.read_contents();font=next(f for f in page.get_fonts(full=True) if f[4]=='F1')
        dictionary=doc.xref_object(font[0]);result=screen_architectural_span(page,span)
        self.assertEqual(result['status'],'raster_consistent_candidate',result)
        self.assertEqual(result['glyph_encoding'],'source_unembedded_winansi_resource')
        self.assertEqual(result['source_font_xrefs'],[font[0]])
        proof=result['font_resource_resolution']
        self.assertEqual(proof['basis'],'original_direct_text_show_operator_and_native_glyph_binding')
        self.assertEqual(proof['font_resource'],'F1')
        self.assertFalse(proof['source_font_program_embedded'])
        self.assertFalse(proof['source_pdf_modified'])
        self.assertFalse(result['visibility_verified'])
        self.assertTrue(result['renderer_font_fallback_may_be_used'])
        self.assertFalse(result['font_appearance_across_renderers_verified'])
        self.assertEqual(result['max_unsupported_core_fraction_per_glyph'],.01)
        self.assertEqual(result['max_unexpected_dark_ring_fraction'],.01)
        self.assertEqual(page.read_contents(),before)
        self.assertEqual(doc.xref_object(font[0]),dictionary)

    def test_one_unembedded_resource_uses_the_same_original_dictionary(self):
        _,page,span=self.source(alternative=False)
        self.assertEqual(screen_span(page,span)['status'],'raster_consistent_candidate')

    def test_reference_proof_only_contains_requested_text_show_operators(self):
        _,page,span=self.source(filler=20)
        result=screen_span(page,span)
        self.assertEqual(result['status'],'raster_consistent_candidate',result)
        operations=result['font_resource_resolution']['source_operations']
        self.assertEqual(len(operations),1)
        self.assertEqual(operations[0]['encoded_character_count'],len(span['chars']))

    def test_page_rotation_restored_and_white_or_dark_overpaint_stays_withheld(self):
        for color in ((1,1,1),(0,0,0)):
            with self.subTest(color=color):
                _,page,span=self.source();page.set_rotation(90)
                self.assertEqual(screen_span(page,span)['status'],'raster_consistent_candidate')
                self.assertEqual(page.rotation,90)
                page.draw_rect(pymupdf.Rect(span['bbox']),color=None,fill=color)
                self.assertEqual(screen_span(page,span)['status'],'withheld')
                self.assertEqual(page.rotation,90)

    def test_character_glyph_origin_and_box_must_belong_to_original_source_inventory(self):
        _,page,span=self.source()
        for kind in ('character','glyph','origin','box'):
            altered=copy.deepcopy(span);chars=list(altered['chars']);c=list(chars[0])
            if kind=='character':c[0]=65
            elif kind=='glyph':c[1]+=1
            elif kind=='origin':c[2]=(c[2][0]+1,c[2][1])
            else:c[3]=(c[3][0]+1,*c[3][1:])
            chars[0]=tuple(c);altered['chars']=chars
            with self.subTest(kind=kind):self.assertEqual(screen_span(page,altered)['status'],'withheld')

    def test_implicit_text_positioning_font_overrides_and_resource_overprints_stay_held(self):
        for options in ({'implicit':True},{'duplicate':True},{'override':True}):
            _,page,span=self.source(**options)
            with self.subTest(options=options):self.assertEqual(screen_span(page,span)['status'],'withheld')

    def test_encoding_override_and_to_unicode_mapping_are_not_assumed_to_be_winansi(self):
        for kind in ('encoding','unicode'):
            doc,page,span=self.source();font=next(f for f in page.get_fonts() if f[4]=='F1')
            if kind=='encoding':
                doc.xref_set_key(font[0],'Encoding','<< /BaseEncoding /WinAnsiEncoding /Differences [65 /B] >>')
            else:
                mapping=doc.get_new_xref();doc.update_object(mapping,'<<>>');doc.update_stream(mapping,b'')
                doc.xref_set_key(font[0],'ToUnicode',f'{mapping} 0 R')
            with self.subTest(kind=kind):self.assertEqual(screen_span(page,span)['status'],'withheld')

    def test_form_xobject_font_context_requires_a_separate_provenance_adapter(self):
        doc,_,_=self.source();target=pymupdf.open();self.addCleanup(target.close)
        page=target.new_page(width=600,height=500);page.show_pdf_page(page.rect,doc,0)
        span=page.get_texttrace()[0]
        self.assertEqual(screen_span(page,span)['status'],'withheld')


if __name__=='__main__':
    unittest.main()
