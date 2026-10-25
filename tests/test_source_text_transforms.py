"""Original PDF matrices, encoded shows and native traces, without raster fitting."""
import copy
import hashlib
import unittest
from unittest.mock import patch

import pymupdf

from voxel_mapper import source_text_transforms as transforms
from voxel_mapper.glyph_visibility import screen_architectural_span
from tests import test_glyph_visibility as glyph_fixtures


class SourceTextTransformTests(unittest.TestCase):
    def source(self, *, matrix='1.4 0 0 1', prefix='', show='(AB) Tj',
               duplicate=False, implicit=False, suffix='', rotation=0):
        doc,page,_=glyph_fixtures.GlyphTests().simple_cff_source();self.addCleanup(doc.close)
        tm='100 100 Td' if implicit else matrix+' 100 100 Tm'
        command=f'q {prefix} 1 0 0 rg BT /original 12 Tf {tm} {show} ET Q'
        if duplicate:command+='\n'+command
        command+=suffix
        content=page.get_contents()[0];doc.update_stream(content,command.encode('ascii'))
        page=doc.reload_page(page);page.set_rotation(rotation)
        return doc,page,page.get_texttrace()[0]

    def test_original_anisotropy_passes_where_uniform_reference_fails(self):
        for matrix in ('1.4 0 0 1','0.8 0 0 1'):
            with self.subTest(matrix=matrix):
                _,page,span=self.source(matrix=matrix)
                original=page.read_contents();result=screen_architectural_span(page,span)
                self.assertEqual(result['status'],'raster_consistent_candidate',result)
                proof=result['source_text_transform']
                self.assertEqual(proof['encoded_glyph_count'],2)
                self.assertEqual(proof['page_content_sha256'],hashlib.sha256(original).hexdigest())
                self.assertEqual(proof['encoded_glyph_bytes_sha256'],hashlib.sha256(b'AB').hexdigest())
                self.assertNotEqual(proof['effective_font_basis_pdf_native'][0],proof['effective_font_basis_pdf_native'][3])
                self.assertFalse(proof['physical_identity_verified'])
                self.assertEqual(result['max_unsupported_core_fraction_per_glyph'],.01)
                self.assertEqual(result['colour_residual_tolerance_rgb_levels'],12)
                self.assertEqual(page.read_contents(),original)
                with patch.object(transforms,'bind',return_value=None):
                    self.assertEqual(screen_architectural_span(page,span)['status'],'withheld')

    def test_original_graphics_matrix_and_page_rotation_are_preserved(self):
        for rotation in (0,90,180,270):
            _,page,span=self.source(prefix='0.8 0 0 0.8 10 20 cm',rotation=rotation)
            result=screen_architectural_span(page,span)
            self.assertEqual(result['status'],'raster_consistent_candidate',result)
            proof=result['source_text_transform']
            for actual,expected in zip(proof['source_graphics_matrix'],(.8,0,0,.8,10,20)):
                self.assertAlmostEqual(actual,expected,places=6)
            self.assertEqual(page.rotation,rotation)

    def test_covered_erased_wrong_colour_and_uniform_matching_paint_still_fail(self):
        for cover in ((1,1,1),(0,0,0),(0,.6,0),(1,0,0)):
            _,page,span=self.source()
            page.draw_rect(pymupdf.Rect(span['bbox']),color=None,fill=cover)
            result=screen_architectural_span(page,span)
            self.assertEqual(result['status'],'withheld',result)
            self.assertIn('source_text_transform',result)

    def test_forged_origins_codes_and_partial_native_runs_cannot_bind(self):
        _,page,span=self.source();fonts=page.get_fonts(full=True)
        self.assertIsNotNone(transforms.bind(page,span,fonts,[65,66],2))
        self.assertIsNone(transforms.bind(page,span,fonts,[65,65],2))
        self.assertIsNone(transforms.bind(page,{**span,'chars':span['chars'][:1]},fonts,[65],2))
        forged=copy.deepcopy(span);char=forged['chars'][0]
        forged['chars']=[(char[0],char[1],(char[2][0]+.001,char[2][1]),char[3]),*forged['chars'][1:]]
        self.assertIsNone(transforms.bind(page,forged,fonts,[65,66],2))
        self.assertIsNone(transforms.bind(page,span,[],[65,66],2))

    def test_implicit_positioning_duplicate_shows_shear_and_unsupported_rise_do_not_bind(self):
        for kwargs in ({'implicit':True},{'duplicate':True},{'matrix':'1 .2 0 1'},
                       {'prefix':'BT 4 Ts ET'},{'show':'[-100 (AB)] TJ'}):
            with self.subTest(kwargs=kwargs):
                _,page,span=self.source(**kwargs)
                self.assertIsNone(transforms.bind(page,span,page.get_fonts(full=True),[65,66],2))

    def test_tj_array_kerning_keeps_exact_native_origins(self):
        _,page,span=self.source(show='[(A) 150 (B)] TJ')
        result=screen_architectural_span(page,span)
        self.assertEqual(result['status'],'raster_consistent_candidate',result)
        self.assertEqual(result['source_text_transform']['encoded_glyph_count'],2)

    def test_budget_exhaustion_cannot_publish_partial_matrix_inventory(self):
        for limit in ('MAX_BYTES','MAX_OPERATORS','MAX_SHOWS','MAX_CHARACTERS'):
            _,page,span=self.source()
            with patch.object(transforms,limit,0):
                self.assertIsNone(transforms.bind(page,span,page.get_fonts(full=True),[65,66],2))

    def test_cache_reuses_inventory_and_invalidates_original_stream_changes(self):
        doc,page,span=self.source();first=transforms.bind(page,span,page.get_fonts(full=True),[65,66],2)
        with patch('pypdf.generic.ContentStream',side_effect=AssertionError('Inventory parsed twice')):
            self.assertEqual(transforms.bind(page,span,page.get_fonts(full=True),[65,66],2),first)
        content=page.get_contents()[0];doc.update_stream(content,page.read_contents()+b'\n% changed original stream\n')
        second=transforms.bind(page,span,page.get_fonts(full=True),[65,66],2)
        self.assertNotEqual(first['page_content_sha256'],second['page_content_sha256'])
        self.assertEqual(first['effective_font_basis_pdf_native'],second['effective_font_basis_pdf_native'])

    def test_forms_cropped_pages_and_non_default_units_do_not_get_new_binding(self):
        for case in ('form','crop','unit'):
            with self.subTest(case=case):
                doc,page,span=self.source()
                if case=='crop':page.set_cropbox(pymupdf.Rect(0,0,390,200))
                elif case=='unit':doc.xref_set_key(page.xref,'UserUnit','2')
                else:
                    with pymupdf.open() as other:
                        p=other.new_page();p.insert_text((50,50),'Separate form text')
                        page.show_pdf_page(pymupdf.Rect(200,10,390,80),other,0)
                self.assertIsNone(transforms.bind(page,span,page.get_fonts(full=True),[65,66],2))


if __name__=='__main__':unittest.main()
