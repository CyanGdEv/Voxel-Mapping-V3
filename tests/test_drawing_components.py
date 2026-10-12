import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import pymupdf
from shapely.geometry import shape
from shapely.ops import unary_union

from voxel_mapper.drawing_components import run,split_page
from voxel_mapper.drawing_geometry import run as extract
from voxel_mapper.drawing_footprints import retained_page_candidates,reviewed_feature
from voxel_mapper.planning_bulk import Corpus
from voxel_mapper.survey_context import inspect_survey_context


class ComponentTests(unittest.TestCase):
    def fixture(self,root):
        corpus=Corpus(root/'corpus');doc=pymupdf.open();page=doc.new_page(width=600,height=600)
        paint=page.new_shape();paint.draw_rect((50,50,200,200));paint.draw_rect((80,80,120,120));paint.draw_rect((300,300,450,450));paint.finish(fill=(.5,.5,.5),color=None,even_odd=True);paint.commit()
        page.draw_rect((300,300,450,450));page.insert_text((320,380),'Hotel')
        data=doc.tobytes();doc.close();corpus.ingest([{'url':'https://portal.test/plan','title':'Components'}],['portal.test']);corpus.acquire(fetch=lambda u:data);extract(corpus,root/'geometry')
        return corpus,root/'geometry/geometry-candidates.jsonl'

    def test_union_holes_identity_and_duplicate_parent_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus,feed=self.fixture(root)
            try:
                parents=[json.loads(l) for l in feed.read_text().splitlines()];parts=split_page(parents)
                self.assertEqual(len(parts),2);self.assertTrue(unary_union([shape(p['geometry']) for p in parts]).equals(unary_union([shape(p['geometry']) for p in parents])))
                self.assertEqual(sum(len(shape(p['geometry']).interiors) for p in parts),1)
                self.assertEqual(sorted(len(p['parent_references']) for p in parts),[1,2])
                for p in parts:
                    expected=hashlib.sha256((p['document_sha256']+'/1/'+shape(p['geometry']).normalize().wkb_hex).encode()).hexdigest();self.assertEqual(p['id'],expected)
                    self.assertFalse(p['component_semantics_verified'])
                first=run(corpus,feed,root/'components');second=run(corpus,feed,root/'components');self.assertEqual(first['file_sha256'],second['file_sha256'])
            finally:corpus.close()

    def test_matching_binds_component_to_all_original_parents(self):
        from voxel_mapper.footprint_matching import NativeNames
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus,feed=self.fixture(root)
            try:
                run(corpus,feed,root/'components');parts=[json.loads(l) for l in (root/'components/polygon-candidates.jsonl').read_text().splitlines()];names=NativeNames(corpus,[{'name':'Hotel'}])
                try:
                    self.assertEqual(sum(bool(names.get(p)) for p in parts),1)
                    forged=json.loads(json.dumps(parts[0]));forged['parent_references'][0]['component_index']=99
                    with self.assertRaisesRegex(ValueError,'retained page'):names.get(forged)
                finally:names.close()
                with self.assertRaisesRegex(ValueError,'parent/component'):reviewed_feature(parts[0],None,None,None,None)
            finally:corpus.close()

    def test_pdf_and_parent_tampering_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus,feed=self.fixture(root)
            try:
                parents=[json.loads(l) for l in feed.read_text().splitlines()];forged=json.loads(json.dumps(parents));forged[0]['paint_references'][0]['ordinal']=999;feed.write_text(''.join(json.dumps(p)+'\n' for p in forged))
                with self.assertRaisesRegex(ValueError,'retained extraction'):run(corpus,feed,root/'bad')
                feed.write_text(''.join(json.dumps(p)+'\n' for p in parents));(corpus.root/'files'/f"{parents[0]['document_sha256']}.pdf").write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'checksum'):run(corpus,feed,root/'corrupt')
            finally:corpus.close()

    def test_partial_parent_page_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus,feed=self.fixture(root)
            try:
                feed.write_text(feed.read_text().splitlines()[0]+'\n')
                with self.assertRaisesRegex(ValueError,'Complete retained'):run(corpus,feed,root/'partial')
            finally:corpus.close()

    def test_survey_mentions_do_not_override_arbitrary_grid(self):
        r=inspect_survey_context('OSGB36 via OSTN15. No scale factor has been applied. The coordinates shown are arbitrary and not true OS coordinates. Refer to the on-site grid.')
        self.assertTrue(r['national_grid_mentioned']);self.assertEqual(r['coordinate_use'],'local_or_restricted_grid');self.assertFalse(r['direct_national_grid_registration_eligible']);self.assertIn('not_true_os_coordinates',r['restriction_flags'])
        self.assertFalse(inspect_survey_context('EPSG:27700')['registration_verified'])

    def test_component_pipeline_matching_and_resume(self):
        from voxel_mapper.park_pipeline import run as run_job
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus,feed=self.fixture(root);corpus.close()
            (root/'refs').write_text(json.dumps({'type':'FeatureCollection','features':[]}))
            job=root/'job.json';job.write_text(json.dumps({'work_directory':'.','acquisition':{'offline':True},'drawing_analysis':{'enabled':False},'drawing_geometry':{'enabled':True},'drawing_components':{'enabled':True},'footprint_matching':{'enabled':True,'references':'refs','reference_crs':'EPSG:27700','target_crs':'EPSG:27700'},'sheet_alignment':{'enabled':True}}))
            first=run_job(job,'acquire');second=run_job(job,'acquire')
            self.assertEqual(first['stages']['drawing_components']['file_sha256'],second['stages']['drawing_components']['file_sha256']);self.assertEqual(first['stages']['sheet_alignment'],second['stages']['sheet_alignment'])
            self.assertEqual(first['stages']['drawing_components']['components'],2)

    def test_anchor_audit_withholds_axis_fit_when_grid_is_arbitrary(self):
        from unittest.mock import patch
        from pypdf import PdfReader
        from io import BytesIO
        from voxel_mapper.anchor_audit import page_audit
        doc=pymupdf.open();page=doc.new_page();page.insert_text((40,80),'Coordinates shown are arbitrary and not true OS coordinates.');data=doc.tobytes();reader=PdfReader(BytesIO(data))
        try:
            with patch('voxel_mapper.anchor_audit.fit_axis_labels',return_value={'status':'native_label_alignment_hypothesis'}):r=page_audit(reader.pages[0],page,[-2,52,-1,54])
            self.assertEqual(r['axis_alignment']['status'],'withheld_survey_grid_restriction');self.assertFalse(r['registration_verified'])
        finally:doc.close()

    def test_failed_matching_does_not_publish_partial_outputs(self):
        import sqlite3
        from voxel_mapper.footprint_matching import run as match
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus,feed=self.fixture(root)
            try:
                run(corpus,feed,root/'components');polys=root/'components/polygon-candidates.jsonl';records=polys.read_text().splitlines();polys.write_text(records[0]+'\n'+records[0]+'\n')
                (root/'refs').write_text(json.dumps({'type':'FeatureCollection','features':[]}))
                with self.assertRaises(sqlite3.IntegrityError):match(polys,root/'refs','EPSG:27700','EPSG:27700',root/'matching',corpus=corpus)
                self.assertFalse((root/'matching/associations.jsonl').exists());self.assertFalse((root/'matching/matching-report.json').exists())
            finally:corpus.close()

if __name__=='__main__':unittest.main()
