import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import pymupdf
from pypdf import PdfReader
from pypdf.generic import NameObject,NumberObject
from voxel_mapper.drawing_page_tools import native_inspection_page,pixel_to_native,native_lines,ocr_lines,inspect_ocr_page,reference_landmarks,match_landmarks
from voxel_mapper.geopdf import inspect_registration
from voxel_mapper.drawing_batch import analyze
from voxel_mapper.planning_bulk import Corpus
from tests.test_drawing_ocr import tsv

class PageToolsTests(unittest.TestCase):
    def test_rotation_inspection_preserves_native_registration_and_original_page(self):
        from tests.test_geopdf import GeoPdfTests
        for angle in (0,90,180,270):
            writer,page,_=GeoPdfTests().fixture();page[NameObject('/Rotate')]=NumberObject(angle)
            inspected,report=native_inspection_page(page)
            self.assertEqual(int(page['/Rotate']),angle)
            self.assertEqual(inspect_registration(inspected)['status'],'candidate_alignment')
            self.assertEqual(report['original_rotation_degrees'],angle)
            self.assertFalse(report['source_pdf_modified'])
    def test_units_and_invalid_angles_are_withheld(self):
        from pypdf import PdfWriter
        page=PdfWriter().add_blank_page(400,600)
        page[NameObject('/Rotate')]=NumberObject(45)
        with self.assertRaises(ValueError):native_inspection_page(page)
        page[NameObject('/Rotate')]=NumberObject(0);page[NameObject('/UserUnit')]=NumberObject(2)
        with self.assertRaises(ValueError):native_inspection_page(page)
    def test_pixel_frame_maps_known_native_point_for_all_display_rotations(self):
        # Native PDF (100,200), full 400x600 sheet: top-down (100,400).
        for angle,rendered in [(0,(100,400)),(90,(200,100)),(180,(300,200)),(270,(400,300))]:
            doc=pymupdf.open();page=doc.new_page(width=400,height=600);page.set_rotation(angle)
            point=pymupdf.Point(*rendered)*pymupdf.Matrix(pixel_to_native(page,int(page.rect.width),int(page.rect.height)))
            self.assertAlmostEqual(point.x,100);self.assertAlmostEqual(point.y,200);doc.close()
    def test_native_label_position_does_not_follow_display_rotation(self):
        doc=pymupdf.open();page=doc.new_page(width=400,height=600);page.insert_text((50,100),'Named House',fontsize=24)
        for angle in (0,90,180,270):
            page.set_rotation(angle);line=native_lines(page)[0]
            self.assertEqual(line['text'],'Named House');self.assertTrue(50<line['local'][0]<220);self.assertTrue(490<line['local'][1]<520)
        doc.close()
    def test_cropped_rotated_frame_retains_native_offsets(self):
        for angle,rendered in [(0,(80,370)),(90,(170,80)),(180,(280,170)),(270,(370,280))]:
            doc=pymupdf.open();page=doc.new_page(width=400,height=600);page.set_cropbox(pymupdf.Rect(20,30,380,570));page.set_rotation(angle)
            point=pymupdf.Point(*rendered)*pymupdf.Matrix(pixel_to_native(page,int(page.rect.width),int(page.rect.height)))
            self.assertAlmostEqual(point.x,100);self.assertAlmostEqual(point.y,200)
            self.assertEqual(page.rotation,angle);doc.close()
    def test_low_confidence_whole_line_and_invalid_pixel_bounds(self):
        doc=pymupdf.open();page=doc.new_page()
        summary,lines=ocr_lines(tsv([[('House',95),('One',30)],[('House',90),('Two',90)]]),page,100,100)
        self.assertEqual(len(lines),1);self.assertEqual(lines[0]['text'],'House Two')
        self.assertEqual(summary['low_confidence_word_count'],1)
        bad=tsv([[('House',95)]]).replace('\t0\t0\t10\t10\t95','\t150\t0\t10\t10\t95')
        with self.assertRaises(ValueError):ocr_lines(bad,page,100,100)
        doc.close()
    @unittest.skipUnless(shutil.which('tesseract'),'Tesseract needed')
    def test_real_raster_ocr_returns_unplaced_material_candidates(self):
        from PIL import Image,ImageDraw,ImageFont
        image=Image.new('RGB',(1000,200),'white');draw=ImageDraw.Draw(image);font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',38)
        draw.text((20,50),'Path surface asphalt',fill='black',font=font)
        raw=io.BytesIO();image.save(raw,format='PNG');doc=pymupdf.open();page=doc.new_page(width=500,height=100);page.insert_image(page.rect,stream=raw.getvalue())
        result,lines=inspect_ocr_page(page)
        self.assertEqual(result['status'],'ocr_candidates_only')
        self.assertTrue(any(c['material_candidate']=='asphalt' for c in result['semantic_evidence']['materials']))
        self.assertTrue(lines);self.assertEqual(result['world_geometry_additions'],0);doc.close()
    def references(self):
        return [{'id':str(i),'name':name,'target':[10+x,20+y],'target_crs':'EPSG:27700','source_id':'ref','source_sha256':'a'*64} for i,(name,x,y) in enumerate([('House One',0,0),('House Two',100,0),('House Three',0,100)])]
    def test_three_exact_names_only_form_unverified_hypothesis(self):
        lines=[{'text':r['name'],'local':[r['target'][0]-10,r['target'][1]-20],'origin':'native_text_box_center_unverified'} for r in self.references()]
        result=match_landmarks(lines,self.references(),[round(72/.0254)])
        self.assertEqual(len(result['matches']),3);self.assertFalse(result['registration_verified'])
        self.assertEqual(result['fit']['status'],'candidate_name_fit');self.assertEqual(result['world_geometry_additions'],0)
        ambiguous=match_landmarks(lines+[lines[0]],self.references(),[500])
        self.assertEqual(len(ambiguous['matches']),2);self.assertEqual(len(ambiguous['ambiguous_names']),1)
    def test_crs_and_duplicate_reference_names(self):
        data={'features':[{'id':'a','properties':{'name':'House'},'geometry':{'type':'Point','coordinates':[-1.9,52.98]}}]}
        result=reference_landmarks(data,'EPSG:4326','EPSG:27700','a'*64)
        self.assertTrue(400000<result[0]['target'][0]<450000)
        with self.assertRaises(ValueError):reference_landmarks(data,'EPSG:4326','EPSG:4326','a'*64)
        matches=match_landmarks([{'text':'House','local':[0,0]}],result+result,[500])
        self.assertFalse(matches['matches']);self.assertEqual(matches['ambiguous_names'][0]['reference_count'],2)
    def test_ocr_budget_is_deferred_then_resumed_without_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            doc=pymupdf.open();doc.new_page();data=doc.tobytes();doc.close();corpus=Corpus(directory)
            try:
                corpus.ingest([{'url':'https://portal.test/a','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda u:data)
                r=analyze(corpus,registration=False,max_ocr_pages=0)
                self.assertEqual(r['ocr_statuses'],{'deferred':1})
                with patch('voxel_mapper.drawing_batch.inspect_ocr_page',return_value=({'status':'ocr_candidates_only'},[])) as mock:
                    r=analyze(corpus,registration=False,max_ocr_pages=1)
                    self.assertEqual(mock.call_count,1);self.assertEqual(r['ocr_statuses'],{'ocr_candidates_only':1})
                    self.assertEqual(analyze(corpus,registration=False)['resumed_pages'],1)
            finally:corpus.close()
    def test_unavailable_ocr_can_recover_after_tool_or_timeout_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            doc=pymupdf.open();doc.new_page();data=doc.tobytes();doc.close();corpus=Corpus(directory)
            try:
                corpus.ingest([{'url':'https://portal.test/a','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda u:data)
                with patch('voxel_mapper.drawing_batch.inspect_ocr_page',return_value=({'status':'unavailable'},[])):
                    self.assertEqual(analyze(corpus,registration=False)['ocr_statuses'],{'unavailable':1})
                with patch('voxel_mapper.drawing_batch.inspect_ocr_page',return_value=({'status':'ocr_candidates_only'},[])) as mock:
                    self.assertEqual(analyze(corpus,registration=False)['ocr_statuses'],{'ocr_candidates_only':1})
                    self.assertEqual(mock.call_count,1)
            finally:corpus.close()

if __name__=='__main__':unittest.main()
