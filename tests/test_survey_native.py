from pathlib import Path
import unittest
from unittest.mock import patch
import pymupdf
from pypdf import PdfReader
from voxel_mapper.survey_landmark_discovery import inspect_page,survey_references,raster_triage,run
from voxel_mapper.survey_native import VERSION
from voxel_mapper.generation_cycles import file_hash
from voxel_mapper.planning_bulk import Corpus
from voxel_mapper.drawing_geometry import run as extract
from tests import test_survey_landmark_discovery as station_fixture


class NativeSurveyTests(unittest.TestCase):
    def setUp(self):
        self.fixture=station_fixture.StationDiscoveryTests();self.fixture.setUp();self.root=self.fixture.root
    def tearDown(self):self.fixture.tearDown()

    def form(self,*,repeat=False,rotation=0):
        source=self.fixture.pdfs[0];target=self.root/'form.pdf'
        with pymupdf.open(source) as original,pymupdf.open() as doc:
            page=doc.new_page(width=1000,height=1000)
            page.show_pdf_page(pymupdf.Rect(100,100,700,700),original,0,rotate=rotation)
            if repeat:page.show_pdf_page(pymupdf.Rect(300,300,900,900),original,0)
            doc.save(target)
        return target

    def inspect(self,path):
        with pymupdf.open(path) as doc:return inspect_page(PdfReader(path).pages[0],doc[0],file_hash(path),1)

    def test_form_text_and_marks_keep_the_transformed_native_frame(self):
        path=self.form();page=self.inspect(path)
        self.assertEqual(page['text_adapter'],VERSION)
        self.assertEqual(len(page['candidates']),3)
        self.assertTrue(all(c['status']=='source_bound_station_coordinate_candidate' for c in page['candidates']),page)
        self.assertEqual(page['candidates'][0]['local'],[150,350])
        self.assertEqual(page['candidates'][0]['table_glyph_screen']['status'],'raster_consistent_candidate')

    def test_rotated_form_text_remains_source_bound(self):
        path=self.form(rotation=90);page=self.inspect(path)
        self.assertTrue(all(c['status']=='source_bound_station_coordinate_candidate' for c in page['candidates']),page)
        # The 90-degree Form transform maps native (50,50) to (650,350).
        self.assertEqual(page['candidates'][0]['local'],[650,350])

    def test_repeated_form_cannot_select_one_station_identity(self):
        page=self.inspect(self.form(repeat=True))
        self.assertTrue(all(c['status']=='withheld_ambiguous_station_identity' for c in page['candidates']))

    def test_occluded_form_marks_are_withheld(self):
        path=self.form()
        with pymupdf.open(path) as doc:
            doc[0].draw_rect(pymupdf.Rect(140,640,160,660),fill=(1,1,1),color=None)
            changed=self.root/'occluded.pdf';doc.save(changed)
        page=self.inspect(changed)
        candidate=next(c for c in page['candidates'] if c['station_id']=='A')
        self.assertEqual(candidate['status'],'withheld_station_attachment_visibility')

    def test_clipped_form_does_not_invent_hidden_marks(self):
        source=self.fixture.pdfs[0];target=self.root/'clipped.pdf'
        with pymupdf.open(source) as original,pymupdf.open() as doc:
            page=doc.new_page(width=600,height=600)
            page.show_pdf_page(page.rect,original,0,clip=pymupdf.Rect(100,100,600,600))
            doc.save(target)
        page=self.inspect(target)
        candidates={c['station_id']:c for c in page['candidates']}
        for station in ('A','C'):
            self.assertNotEqual(candidates[station]['status'],'source_bound_station_coordinate_candidate')
        self.assertEqual(candidates['B']['status'],'source_bound_station_coordinate_candidate')

    def raster(self):
        path=self.root/'raster.pdf'
        with pymupdf.open(self.fixture.pdfs[0]) as original,pymupdf.open() as doc:
            page=doc.new_page(width=600,height=600)
            page.insert_image(page.rect,stream=original[0].get_pixmap().tobytes('png'))
            doc.save(path)
        return path

    def test_image_only_page_is_explicitly_deferred_to_ocr(self):
        page=self.inspect(self.raster())
        self.assertEqual(page['status'],'raster_page_requires_ocr')
        self.assertEqual(page['candidates'],[])

    def test_ocr_coordinates_never_become_native_station_references(self):
        path=self.raster()
        with pymupdf.open(path) as doc,patch('voxel_mapper.survey_landmark_discovery.inspect_ocr_page',return_value=(
            {'status':'ocr_candidates'},[{'text':'CP:A E=407345 N=343810','local':[50,50],'confidence':99}])):
            triage=raster_triage(doc[0])
        page=self.inspect(path);page['raster_triage']=triage
        policy={**self.fixture.policies[0],'sha256':file_hash(path)}
        refs,status=survey_references(page,[policy])
        self.assertEqual(refs,[])
        self.assertFalse(triage['registration_verified'])
        self.assertEqual(triage['accepted_controls'],0)

    def test_ocr_selection_is_bounded_and_restart_does_not_repeat_it(self):
        path=self.raster();corpus=Corpus(self.root/'raster-corpus')
        try:
            corpus.ingest([{'url':'https://example.test/raster','title':'Scan'}],['example.test'])
            corpus.acquire(fetch=lambda _:path.read_bytes());extract(corpus,self.root/'raster-geometry')
            options={'max_ocr_pages':1}
            with patch('voxel_mapper.survey_landmark_discovery.raster_triage',return_value={'status':'unverified_raster_coordinate_leads','coordinate_leads':[]}) as ocr:
                first=run(corpus,self.root/'raster-geometry',self.root/'raster-memory.sqlite',self.root/'first',**options)
                self.assertEqual(ocr.call_count,1)
            with patch('voxel_mapper.survey_landmark_discovery.raster_triage',side_effect=AssertionError('Recomputed')):
                second=run(corpus,self.root/'raster-geometry',self.root/'raster-memory.sqlite',self.root/'second',**options)
            self.assertEqual(second['reused_pages'],1)
            self.assertEqual(first['output_sha256'],second['output_sha256'])
            self.assertEqual(first['reference_count'],0)
            for invalid in [True,-1,17]:
                with self.assertRaises(ValueError):run(corpus,self.root/'raster-geometry',self.root/'x.sqlite',self.root/'x',max_ocr_pages=invalid)
        finally:corpus.close()
