import json
from pathlib import Path
import tempfile
import unittest

import pymupdf

from voxel_mapper.drawing_geometry import run as extract
from voxel_mapper.outline_batch import priority,run
from voxel_mapper.planning_bulk import Corpus


class OutlineBatchTests(unittest.TestCase):
    def fixture(self,root,label='Hotel'):
        corpus=Corpus(root/'corpus');doc=pymupdf.open();page=doc.new_page(width=400,height=600)
        page.draw_rect((100,100,300,300));page.insert_text((150,200),label);data=doc.tobytes();doc.close()
        corpus.ingest([{'url':'https://portal.test/plan','title':'Test layout','state':'proposed'}],['portal.test']);corpus.acquire(fetch=lambda u:data)
        extract(corpus,root/'geometry');return corpus,root/'geometry/geometry-candidates.jsonl'

    def test_resume_identical_feeds_and_ranking_stays_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus,feed=self.fixture(root)
            try:
                first=run(corpus,feed,root/'review');second=run(corpus,feed,root/'review')
                self.assertEqual(first['file_sha256'],second['file_sha256']);self.assertEqual(second['run_candidates'],0);self.assertEqual(second['resumed_candidates'],1)
                row=json.loads((root/'review/alignment-priority.jsonl').read_text())
                self.assertEqual(row['hinted_polygons'],1);self.assertEqual(row['review_priority_tier'],1)
                self.assertEqual(row['sources'][0]['drawing_state'],'proposed');self.assertFalse(row['registration_verified']);self.assertEqual(row['world_geometry_additions'],0)
            finally:corpus.close()

    def test_changed_input_refused_before_reusing_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus,feed=self.fixture(root)
            try:
                run(corpus,feed,root/'review');feed.write_text(feed.read_text()+'\n')
                with self.assertRaisesRegex(ValueError,'inputs changed'):run(corpus,feed,root/'review')
            finally:corpus.close()

    def test_corrupt_pdf_refused_on_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus,feed=self.fixture(root)
            try:
                run(corpus,feed,root/'review');candidate=json.loads(feed.read_text());(corpus.root/'files'/f"{candidate['document_sha256']}.pdf").write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'checksum'):run(corpus,feed,root/'review')
            finally:corpus.close()

    def test_duplicate_and_forged_candidate_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus,feed=self.fixture(root)
            try:
                data=feed.read_text();feed.write_text(data+data)
                with self.assertRaisesRegex(ValueError,'Duplicate'):run(corpus,feed,root/'duplicate')
                record=json.loads(data);record['paint_references'][0]['ordinal']=999;feed.write_text(json.dumps(record)+'\n')
                with self.assertRaisesRegex(ValueError,'retained page'):run(corpus,feed,root/'forged')
            finally:corpus.close()

    def test_interruption_keeps_committed_decisions_and_resumes(self):
        from unittest.mock import patch
        from voxel_mapper.drawing_layout import OutlineReview
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus=Corpus(root/'corpus');doc=pymupdf.open();page=doc.new_page(width=400,height=600)
            # Distinct open paths produce enough records for the checkpoint.
            for i in range(1002):
                y=20+i*.5;page.draw_line((20,y),(100,y))
            data=doc.tobytes();doc.close()
            try:
                corpus.ingest([{'url':'https://portal.test/plan','title':'Lines'}],['portal.test']);corpus.acquire(fetch=lambda u:data);extract(corpus,root/'geometry')
                feed=root/'geometry/geometry-candidates.jsonl';original=OutlineReview.get;calls=0
                def interrupted(reviewer,candidate):
                    nonlocal calls
                    calls+=1
                    if calls==1001:raise RuntimeError('interrupted')
                    return original(reviewer,candidate)
                with patch.object(OutlineReview,'get',interrupted):
                    with self.assertRaisesRegex(RuntimeError,'interrupted'):run(corpus,feed,root/'review')
                result=run(corpus,feed,root/'review');self.assertEqual(result['resumed_candidates'],1000);self.assertEqual(result['run_candidates'],2)
                clean=run(corpus,feed,root/'clean');self.assertEqual(result['file_sha256'],clean['file_sha256'])
            finally:corpus.close()

    def test_withheld_layout_ranks_below_hint_counts(self):
        self.assertEqual(priority({'layout_status':'withheld','hinted_polygons':100}),5)

    def test_optional_park_stage_resumes(self):
        from voxel_mapper.park_pipeline import run as run_job
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus,feed=self.fixture(root);corpus.close()
            job=root/'job.json';job.write_text(json.dumps({'work_directory':'.','acquisition':{'offline':True},'drawing_analysis':{'enabled':False},'drawing_geometry':{'enabled':True},'outline_review':{'enabled':True}}))
            first=run_job(job,'acquire');second=run_job(job,'acquire')
            self.assertEqual(first['stages']['outline_review']['file_sha256'],second['stages']['outline_review']['file_sha256'])
            self.assertEqual(second['stages']['outline_review']['resumed_candidates'],1)

    def test_resume_is_stable_across_process_hash_seeds(self):
        import os
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus,feed=self.fixture(root,'Hotel Water Wall');corpus.close();hashes=[]
            for seed in ('11','22'):
                subprocess.run([sys.executable,'-m','voxel_mapper.outline_batch','--corpus',str(root/'corpus'),'--candidates',str(feed),'--output',str(root/'review')],env={**os.environ,'PYTHONHASHSEED':seed},check=True,capture_output=True)
                hashes.append(json.loads((root/'review/outline-batch-report.json').read_text())['file_sha256'])
            self.assertEqual(hashes[0],hashes[1])

    def test_damaged_checkpoint_is_refused(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus,feed=self.fixture(root)
            try:
                run(corpus,feed,root/'review');path=root/'review/outline-index.sqlite'
                db=sqlite3.connect(path);page=db.execute("select rootpage from sqlite_master where name='sqlite_autoindex_reviews_1'").fetchone()[0];size=db.execute('pragma page_size').fetchone()[0];db.close()
                with path.open('r+b') as stream:stream.seek((page-1)*size);stream.write(b'\0'*size)
                with self.assertRaisesRegex(ValueError,'integrity check'):run(corpus,feed,root/'review')
            finally:corpus.close()

if __name__=='__main__':unittest.main()
