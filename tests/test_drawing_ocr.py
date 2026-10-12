import io
import shutil
import unittest
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from voxel_mapper.drawing_ocr import labels_from_tsv, inspect_scanned_page
from voxel_mapper.council import inspect_pdf
from voxel_mapper.geopdf import inspect_registration


def tsv(lines):
    rows = ['level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext']
    for line, words in enumerate(lines, 1):
        for word, (text, confidence) in enumerate(words, 1):
            rows.append(f'5\t1\t1\t1\t{line}\t{word}\t0\t0\t10\t10\t{confidence}\t{text}')
    return '\n'.join(rows)


class OcrTests(unittest.TestCase):
    def test_confident_labels_are_unplaced_candidates_without_raw_text(self):
        result = labels_from_tsv(tsv([[('Path', 96), ('surface', 95), ('tarmac', 94)],
                                      [('FFL', 97), ('14.5', 93), ('m', 94), ('ODN', 96)]]))
        self.assertEqual(result['semantic_evidence']['materials'][0]['material_candidate'], 'asphalt')
        level = result['semantic_evidence']['levels'][0]
        self.assertEqual(level['value_candidate'], 14.5)
        self.assertEqual(level['text_origin'], 'ocr_unverified')
        self.assertEqual(level['ocr_line_min_confidence'], 93)
        self.assertEqual(result['world_geometry_additions'], 0)
        self.assertNotIn('raw_text', result)

    def test_low_confidence_word_withholds_whole_line(self):
        result = labels_from_tsv(tsv([[('FFL', 95), ('14.5', 40), ('m', 95)], [('concrete', 92)]]))
        self.assertEqual(result['semantic_evidence']['levels'], [])
        self.assertEqual(result['low_confidence_word_count'], 1)
        self.assertEqual(result['accepted_line_count'], 1)

    def test_literal_quote_does_not_swallow_following_tsv_rows(self):
        result = labels_from_tsv(tsv([[('"', 95)], [('concrete', 95)], [('FFL', 95), ('14.5', 95), ('m', 95)]]))
        self.assertEqual(result['word_count'], 5)
        self.assertEqual(result['accepted_line_count'], 3)
        self.assertEqual(len(result['semantic_evidence']['materials']), 1)
        self.assertEqual(result['semantic_evidence']['levels'][0]['value_candidate'], 14.5)

    def test_limits_invalid_confidence_and_missing_tools(self):
        with self.assertRaisesRegex(ValueError, 'word budget'):
            labels_from_tsv(tsv([[('concrete', 95)]]), max_words=0)
        with self.assertRaisesRegex(ValueError, 'confidence'):
            labels_from_tsv(tsv([[('concrete', float('nan'))]]))
        with patch('voxel_mapper.drawing_ocr.shutil.which', return_value=None):
            self.assertEqual(inspect_scanned_page(b'%PDF-', 1)['status'], 'unavailable')

    def test_image_content_is_inspected_with_bounded_page_count(self):
        writer = PdfWriter()
        for _ in range(3):
            page = writer.add_blank_page(400, 300)
            stream = DecodedStreamObject(); stream.set_data(b'0 0 50 50 re S')
            page[NameObject('/Contents')] = writer._add_object(stream)
        output = io.BytesIO(); writer.write(output)
        with patch('voxel_mapper.council.inspect_scanned_page', return_value={'status':'ocr_candidates_only'}) as ocr:
            report = inspect_pdf(output.getvalue())
        self.assertEqual(ocr.call_count, 2)
        self.assertEqual(report['pages'][2]['scanned_page_inspection']['status'], 'page_budget_omitted')
        self.assertEqual(report['pages'][0]['vector_extraction']['status'], 'blocked_reuse')

    def test_scale_only_viewport_does_not_become_registration(self):
        from pypdf.generic import ArrayObject, NumberObject
        writer = PdfWriter(); page = writer.add_blank_page(400, 300)
        page[NameObject('/VP')] = ArrayObject([DictionaryObject({
            NameObject('/BBox'): ArrayObject([NumberObject(v) for v in (0,0,400,300)]),
            NameObject('/Measure'): DictionaryObject({NameObject('/Subtype'):NameObject('/RL')})})])
        result = inspect_registration(page)
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(result['viewports'][0]['measure_type'], 'rectilinear_scale_only')

    @unittest.skipUnless(shutil.which('pdftoppm') and shutil.which('tesseract'), 'OCR tools unavailable')
    def test_real_render_and_ocr_extracts_surface_label(self):
        writer = PdfWriter(); page = writer.add_blank_page(600, 300)
        font = DictionaryObject({NameObject('/Type'):NameObject('/Font'),
            NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
            DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 32 Tf 30 200 Td (Path surface asphalt) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        output = io.BytesIO(); writer.write(output)
        result = inspect_scanned_page(output.getvalue(), 1)
        self.assertEqual(result['status'], 'ocr_candidates_only', result)
        self.assertIn('asphalt', [c['material_candidate'] for c in result['semantic_evidence']['materials']])
