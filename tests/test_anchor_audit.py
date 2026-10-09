import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import pymupdf
from pypdf.generic import DecodedStreamObject,NameObject
from tests.test_drawing_controls import fixture
from voxel_mapper.coordinate_text import coordinate_runs
from voxel_mapper.planning_archive import import_archive
from voxel_mapper.planning_bulk import Corpus
from voxel_mapper.anchor_audit import run as audit,page_audit

class AnchorTests(unittest.TestCase):
    def test_text_show_origins_do_not_follow_delayed_text_visitor(self):
        runs=coordinate_runs(fixture());self.assertEqual([r['origin'] for r in runs[1:]],[[100,100],[100,500],[500,500],[500,100]])
    def test_unpositioned_advances_and_leading_kerning_are_not_guessed(self):
        page=fixture();stream=DecodedStreamObject();stream.set_data(b'BT /F1 8 Tf 1 0 0 1 100 100 Tm (E: 500100) Tj (N: 5700100) Tj 1 0 0 1 200 200 Tm [20 (EPSG: 32630)] TJ ET');page[NameObject('/Contents')]=stream
        runs=coordinate_runs(page);self.assertEqual(len(runs),1);self.assertEqual(runs[0]['text'],'E: 500100')
    def test_custom_encoding_and_operation_budget_withhold(self):
        page=fixture();page['/Resources']['/Font']['/F1'][NameObject('/Encoding')]=NameObject('/Identity-H')
        self.assertFalse(coordinate_runs(page))
        with self.assertRaises(ValueError):coordinate_runs(fixture(),max_operations=1)
        for operator in (b'4 Tr',b'2 Ts'):
            page=fixture();stream=DecodedStreamObject();stream.set_data(operator+ b'\n'+page.get_contents().get_data());page[NameObject('/Contents')]=stream
            with self.assertRaises(ValueError):coordinate_runs(page)
    def make_archive(self,root,*,bad_pdf=False,bad_member=False):
        doc=pymupdf.open();page=doc.new_page();page.insert_text((50,50),'Easting: 407216 Northing: 343693');data=doc.tobytes();doc.close();sha=hashlib.sha256(data).hexdigest();member=f'files/{sha}.pdf' if not bad_member else '../escape.pdf'
        record={'url':'https://portal.test/a','file':member,'sha256':sha,'title':'Application form','applicationReference':'SMD/test','state':'unknown'}
        path=root/'source.zip'
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('metadata/alton-planning-catalogue.json',json.dumps({'entries':[record]}));z.writestr(member,b'changed' if bad_pdf else data)
        return path,hashlib.sha256(path.read_bytes()).hexdigest()
    def test_archive_import_resume_and_repair_source_blob(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,sha=self.make_archive(root);corpus=Corpus(root/'corpus')
            try:
                self.assertEqual(import_archive(corpus,path,sha,['portal.test'])['copied_blobs'],1)
                self.assertEqual(import_archive(corpus,path,sha,['portal.test'])['resumed_blobs'],1)
                next((root/'corpus/files').glob('*.pdf')).write_bytes(b'corrupt')
                self.assertEqual(import_archive(corpus,path,sha,['portal.test'])['copied_blobs'],1)
                self.assertEqual(corpus.report()['download_status'],{'downloaded':1})
            finally:corpus.close()
    def test_bad_archive_pdf_hash_paths_and_hosts_rejected(self):
        for options in ({'bad_pdf':True},{'bad_member':True},{}):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);path,sha=self.make_archive(root,**options);corpus=Corpus(root/'corpus')
                try:
                    with self.assertRaises(ValueError):import_archive(corpus,path,sha,['wrong.test'] if not options else ['portal.test'])
                    self.assertEqual(corpus.report()['document_links'],0)
                    with self.assertRaisesRegex(ValueError,'Archive checksum'):import_archive(corpus,path,'0'*64,['portal.test'])
                finally:corpus.close()
    def test_application_location_is_not_a_drawing_anchor_and_corrupt_source_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,sha=self.make_archive(root);corpus=Corpus(root/'corpus')
            try:
                import_archive(corpus,path,sha,['portal.test']);report=audit(corpus,root/'out',[-2,52,-1,54]);self.assertEqual(report['counts']['application_location_hints'],1)
                row=json.loads((root/'out/anchor-candidates.jsonl').read_text());self.assertFalse(row['application_location_hints'][0]['registration_eligible']);self.assertIsNone(row['application_location_hints'][0]['crs']);self.assertFalse(row['registration_verified'])
                self.assertEqual(audit(corpus,root/'out',[-2,52,-1,54])['resumed_pages'],1)
                next((root/'corpus/files').glob('*.pdf')).write_bytes(b'corrupt');report=audit(corpus,root/'out',[-2,52,-1,54]);self.assertTrue(report['errors']);self.assertEqual((root/'out/anchor-candidates.jsonl').read_text(),'')
            finally:corpus.close()
    def test_park_job_imports_archive_and_resumes_anchor_audit(self):
        from voxel_mapper.park_pipeline import run as run_job
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,sha=self.make_archive(root)
            job={'work_directory':'work','acquisition':{'official_hosts':['portal.test'],'offline':True,'retained_archives':[{'file':path.name,'sha256':sha}]},'drawing_analysis':{'enabled':False},'anchor_audit':{'enabled':True,'bounds_wgs84':[-2,52,-1,54]}}
            (root/'job.json').write_text(json.dumps(job));first=run_job(root/'job.json','acquire');second=run_job(root/'job.json','acquire')
            self.assertEqual(first['stages']['retained_archive_0']['copied_blobs'],1);self.assertEqual(second['stages']['retained_archive_0']['resumed_blobs'],1);self.assertEqual(second['stages']['anchor_audit']['resumed_pages'],1)

if __name__=='__main__':unittest.main()
