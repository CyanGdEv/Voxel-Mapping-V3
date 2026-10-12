import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pymupdf
from voxel_mapper.drawing_geometry import extract_pipeline_page,run,validated_options
from voxel_mapper.planning_bulk import Corpus

class PipelineRegionalTests(unittest.TestCase):
    def pdf(self):
        with pymupdf.open() as doc:
            page=doc.new_page(width=400,height=400)
            page.draw_rect((40,40,100,100));page.draw_rect((300,300,360,360))
            return doc.tobytes()
    def test_default_fallback_keeps_identity_and_combined_limits(self):
        data=self.pdf();sha=hashlib.sha256(data).hexdigest()
        with pymupdf.open(stream=data,filetype='pdf') as pdf:
            options={'max_paths':1,'regional_columns':2,'regional_rows':2}
            candidates,report=extract_pipeline_page(pdf[0],sha,1,**options)
            self.assertEqual(len(candidates),2)
            self.assertEqual(report['status'],'unplaced_regional_geometry_candidates')
            self.assertEqual(len(report['regions']),4)
            self.assertTrue(all(c['regional_parent_contract'] for c in candidates))
            for change in ({'max_regional_candidates':1},{'max_regional_total_points':5}):
                rows,receipt=extract_pipeline_page(pdf[0],sha,1,**options,**change)
                self.assertEqual(rows,[])
                self.assertEqual(receipt['status'],'regional_page_budget_withheld')
            self.assertEqual(extract_pipeline_page(pdf[0],sha,1,**options,regional_fallback=False)[1]['status'],'path_budget_withheld')
    def test_persistent_replay_and_changed_policy(self):
        data=self.pdf()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus=Corpus(root/'corpus')
            try:
                corpus.ingest([{'url':'https://example.test/plan'}],['example.test']);corpus.acquire(fetch=lambda _:data)
                options={'max_paths':1,'regional_columns':2,'regional_rows':2}
                first=run(corpus,root/'first',**options)
                self.assertEqual(first['candidates'],2)
                from voxel_mapper.drawing_footprints import retained_page_candidates
                candidate=json.loads((root/'first/geometry-candidates.jsonl').read_text().splitlines()[0])
                self.assertEqual(candidate['extraction_contract'],first['contract'])
                self.assertEqual(len(retained_page_candidates(corpus,candidate)),2)
                from voxel_mapper.architectural_interpretation import run as interpret
                architecture=interpret(corpus,root/'first',root/'architecture')
                self.assertEqual(architecture['pages'],1)
                page=json.loads((root/'architecture/architectural-pages.jsonl').read_text())
                self.assertEqual(page['status'],'complete_extraction_and_visible_scale_required')
                from voxel_mapper.linework_boundaries import run as recover
                self.assertEqual(recover(corpus,root/'first/geometry-candidates.jsonl',root/'boundaries')['pages'],1)

                with patch('voxel_mapper.drawing_geometry.extract_pipeline_page',side_effect=AssertionError('recomputed')):
                    again=run(corpus,root/'again',**options)
                self.assertEqual(again['resumed_pages'],1)
                self.assertEqual(first['file_sha256'],again['file_sha256'])
                changed=run(corpus,root/'disabled',**options,regional_fallback=False)
                self.assertNotEqual(first['contract'],changed['contract'])
                self.assertEqual(changed['candidates'],0)
            finally:corpus.close()
    def test_global_scan_limit_does_not_trigger_unbounded_grid(self):
        with pymupdf.open(stream=self.pdf(),filetype='pdf') as pdf:
            rows,report=extract_pipeline_page(pdf[0],'a'*64,1,max_paths=1,max_scan_paths=1)
            self.assertEqual(rows,[])
            self.assertEqual(report['regional_fallback_withheld'],'source_scan_budget')
    def test_source_change_during_extraction_is_not_cached_as_geometry(self):
        data=self.pdf()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus=Corpus(root/'corpus')
            try:
                corpus.ingest([{'url':'https://example.test/plan'}],['example.test']);corpus.acquire(fetch=lambda _:data)
                def changed(page,sha,number,**options):
                    rows,report=extract_pipeline_page(page,sha,number,**options)
                    (corpus.root/'files'/(sha+'.pdf')).write_bytes(b'changed')
                    return rows,report
                with patch('voxel_mapper.drawing_geometry.extract_pipeline_page',side_effect=changed):
                    result=run(corpus,root/'output')
                self.assertEqual(result['candidates'],0)
                record=json.loads(corpus.db.execute('SELECT result FROM geometry_pages').fetchone()[0])
                self.assertEqual(record['report']['status'],'withheld')
                self.assertIn('changed during extraction',record['report']['reason'])
            finally:corpus.close()
    def test_invalid_fallback_options(self):
        for options in ({'regional_fallback':1},{'regional_columns':0},{'regional_rows':True},
                        {'regional_overlap_points':float('nan')},{'max_regional_candidates':10001}):
            with self.assertRaises(ValueError):validated_options(options)
