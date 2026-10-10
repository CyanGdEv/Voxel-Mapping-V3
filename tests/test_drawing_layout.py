import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import pymupdf
from shapely.geometry import box, mapping

from voxel_mapper.drawing_layout import inspect_page, outline_review, run
from voxel_mapper.planning_bulk import Corpus


class LayoutTests(unittest.TestCase):
    def page(self):
        doc=pymupdf.open();page=doc.new_page(width=400,height=600)
        self.addCleanup(doc.close)
        return doc,page

    def test_paint_order_retains_but_withholds_hidden_labels(self):
        doc,page=self.page()
        page.insert_text((60,100),'Hidden Hotel')
        page.draw_rect((40,70,200,120),color=None,fill=(1,1,1))
        page.insert_text((60,100),'Visible Restaurant')
        labels={l['text']:l for l in inspect_page(page,'a'*64,1)['labels']}
        self.assertEqual(labels['Hidden Hotel']['visibility_status'],'withheld_occluded_or_invisible_text')
        self.assertEqual(labels['Visible Restaurant']['visibility_status'],'visible_native_text')
        self.assertIn('covered_by_later_opaque_fill',labels['Hidden Hotel']['visibility_reasons'])

    def test_partial_and_translucent_occlusion_are_withheld(self):
        for opacity in (1,.5):
            doc,page=self.page();page.insert_text((60,100),'Hotel')
            page.draw_rect((60,80,70,110),color=None,fill=(1,1,1),fill_opacity=opacity)
            label=inspect_page(page,'a'*64,1)['labels'][0]
            self.assertEqual(label['visibility_status'],'withheld_occluded_or_invisible_text')
            self.assertIn('partially_or_possibly_occluded',label['visibility_reasons'])

    def test_invisible_native_text_is_not_a_name(self):
        doc,page=self.page();page.insert_text((60,100),'Hidden Hotel',render_mode=3)
        label=inspect_page(page,'a'*64,1)['labels'][0]
        self.assertNotEqual(label['visibility_status'],'visible_native_text')

    def test_annotation_panels_and_paper_scales_remain_hypotheses(self):
        doc,page=self.page();page.draw_rect((20,20,200,150),color=None,fill=(1,1,1))
        page.insert_text((40,60),'LEGEND');page.insert_text((40,90),'1/1000 @ A3  1/500 @ A1')
        result=inspect_page(page,'a'*64,1)
        panel=next(r for r in result['regions'] if r['role']=='annotation_panel_hypothesis')
        self.assertEqual([s['denominator'] for s in panel['scale_labels']],[1000,500])
        candidate={'id':'outline','document_sha256':'a'*64,'page':1,'geometry':mapping(box(30,470,190,570))}
        review=outline_review(candidate,result)
        self.assertIn('annotation_panel_overlap',review['review_flags'])
        self.assertFalse(review['physical_identity_verified']);self.assertEqual(review['world_geometry_additions'],0)

    def test_rotation_preserves_native_coordinates_and_source_state(self):
        doc,page=self.page();page.insert_text((60,100),'Hotel')
        original=inspect_page(page,'a'*64,1)
        page.set_rotation(90);rotated=inspect_page(page,'a'*64,1)
        self.assertEqual(page.rotation,90)
        self.assertEqual(original['labels'],rotated['labels'])

    def test_region_budget_defers_without_dropping_labels(self):
        doc,page=self.page()
        for y in (20,200):page.draw_rect((20,y,200,y+150),color=None,fill=(1,1,1))
        page.insert_text((40,60),'Hotel')
        result=inspect_page(page,'a'*64,1,max_regions=1)
        self.assertEqual(result['regions_deferred'],1);self.assertEqual(len(result['labels']),1)

    def test_layout_resume_validates_pdf_before_reusing_cache(self):
        doc,page=self.page();page.insert_text((60,100),'Hotel');data=doc.tobytes()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus=Corpus(root/'corpus')
            try:
                corpus.ingest([{'url':'https://portal.test/a','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda u:data)
                first=run(corpus,root/'out');second=run(corpus,root/'out')
                self.assertEqual(first['output_sha256'],second['output_sha256']);self.assertEqual(second['resumed_pages'],1)
                sha=hashlib.sha256(data).hexdigest();(corpus.root/'files'/f'{sha}.pdf').write_bytes(b'changed')
                third=run(corpus,root/'out')
                self.assertEqual(third['pages'],0);self.assertIn('checksum',third['errors'][0]['reason'])
            finally:corpus.close()

    def test_matching_excludes_a_name_covered_after_extraction(self):
        from voxel_mapper.drawing_footprints import run as extract
        from voxel_mapper.footprint_matching import NativeNames
        doc,page=self.page();page.draw_rect((100,100,300,300));page.insert_text((150,200),'Hotel')
        page.draw_rect((140,180,230,210),color=None,fill=(1,1,1));data=doc.tobytes()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus=Corpus(root/'corpus')
            try:
                corpus.ingest([{'url':'https://portal.test/a','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda u:data);extract(corpus,root/'out')
                names=NativeNames(corpus,[{'name':'Hotel'}])
                try:
                    candidates=[json.loads(l) for l in (root/'out/footprint-candidates.jsonl').read_text().splitlines()]
                    self.assertTrue(candidates);self.assertFalse(any(names.get(c) for c in candidates))
                finally:names.close()
            finally:corpus.close()

    def test_fill_hole_does_not_occlude_text(self):
        doc,page=self.page();page.insert_text((100,200),'Hotel')
        paint=page.new_shape();paint.draw_rect((20,20,350,350));paint.draw_rect((80,160,200,240));paint.finish(fill=(1,1,1),color=None,even_odd=True);paint.commit()
        self.assertEqual(inspect_page(page,'a'*64,1)['labels'][0]['visibility_status'],'visible_native_text')

    def test_source_pinned_outline_stream_rejects_changed_candidate(self):
        from voxel_mapper.drawing_geometry import run as extract
        from voxel_mapper.drawing_layout import review_candidates
        doc,page=self.page();page.draw_rect((100,100,300,300));page.insert_text((150,200),'Hotel');data=doc.tobytes()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus=Corpus(root/'corpus')
            try:
                corpus.ingest([{'url':'https://portal.test/a','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda u:data);extract(corpus,root/'geometry')
                feed=root/'geometry/geometry-candidates.jsonl';report=review_candidates(corpus,feed,root/'review')
                self.assertEqual(report['candidates'],1)
                record=json.loads((root/'review/outline-review.jsonl').read_text())
                self.assertEqual(record['status'],'physical_outline_hypothesis');self.assertFalse(record['physical_identity_verified'])
                candidate=json.loads(feed.read_text());candidate['paint_references'][0]['ordinal']=999;feed.write_text(json.dumps(candidate)+'\n')
                with self.assertRaisesRegex(ValueError,'retained page'):review_candidates(corpus,feed,root/'bad-review')
            finally:corpus.close()

    def test_optional_pipeline_layout_stage_resumes(self):
        from voxel_mapper.park_pipeline import run as run_job
        doc,page=self.page();page.insert_text((60,100),'Hotel');data=doc.tobytes()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus=Corpus(root/'work/corpus')
            try:
                corpus.ingest([{'url':'https://portal.test/a','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda u:data)
            finally:corpus.close()
            job=root/'job.json';job.write_text(json.dumps({'work_directory':'work','acquisition':{'offline':True},'drawing_analysis':{'enabled':False},'drawing_layout':{'enabled':True}}))
            first=run_job(job,'acquire');second=run_job(job,'acquire')
            self.assertEqual(first['stages']['drawing_layout']['output_sha256'],second['stages']['drawing_layout']['output_sha256'])
            self.assertEqual(second['stages']['drawing_layout']['resumed_pages'],1)

if __name__=='__main__':unittest.main()
