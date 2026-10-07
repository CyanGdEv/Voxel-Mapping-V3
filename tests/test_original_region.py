import io
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
from voxel_mapper.drawing_ocr import original_region_label


class OriginalRegionTests(unittest.TestCase):
    def fixture(self,root,text,font_size=20):
        writer=PdfWriter();page=writer.add_blank_page(500,250)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),
                               NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):
            DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream=DecodedStreamObject();stream.set_data(f'BT /F1 {font_size} Tf 30 180 Td ({text}) Tj ET'.encode())
        page[NameObject('/Contents')]=writer._add_object(stream)
        path=root/'input.pdf'
        with path.open('wb') as handle:writer.write(handle)
        return path

    @unittest.skipUnless(shutil.which('pdftoppm') and shutil.which('tesseract'),'OCR tools unavailable')
    def test_original_pdf_region_recovers_label_at_existing_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=self.fixture(root,'168400N')
            label=original_region_label(source,1,(500,250),(500,250),(25,48,160,80),0,'left',root,
                                        dict(os.environ,OMP_THREAD_LIMIT='1'))
            self.assertEqual(label['value'],168400)
            self.assertGreaterEqual(label['confidence'],70)
            self.assertEqual(label['ocr_method'],'original_pdf_region_300dpi')

    @unittest.skipUnless(shutil.which('pdftoppm') and shutil.which('tesseract'),'OCR tools unavailable')
    def test_multiple_coordinate_words_in_one_crop_are_ambiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=self.fixture(root,'168400N 168450N',12)
            label=original_region_label(source,1,(500,250),(500,250),(25,48,170,80),0,'left',root,
                                        dict(os.environ,OMP_THREAD_LIMIT='1'))
            self.assertIsNone(label)

    def test_invalid_extent_pixel_budget_and_deadline_fail_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for box in ((-1,0,10,10),(0,0,500,250),(0,0,float('nan'),10)):
                with self.assertRaises(ValueError):
                    original_region_label(root/'missing.pdf',1,(500,250),(500,250),box,0,'left',root,{})
            with self.assertRaisesRegex(ValueError,'time budget'):
                original_region_label(root/'missing.pdf',1,(500,250),(500,250),(25,48,160,80),0,'left',root,{},time.monotonic()-1)
