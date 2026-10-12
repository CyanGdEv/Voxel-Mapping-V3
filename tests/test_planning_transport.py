import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from voxel_mapper.planning_bulk import Corpus

HOST='publicaccess.staffsmoorlands.gov.uk'
URL=f'https://{HOST}/portal/servlets/AttachmentShowServlet?ImageName=1'
HTTP=URL.replace('https:','http:',1)
DATA=b'%PDF-1.7\ntransport-test-fixture'
SHA=hashlib.sha256(DATA).hexdigest()


class PlanningTransportTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.corpus=Corpus(self.root)
    def tearDown(self):self.corpus.close();self.tmp.cleanup()
    def ingest(self,**changes):
        self.corpus.ingest([{'url':URL,'sha256':SHA,'transport_url':HTTP,**changes}],[HOST])

    def test_explicit_pinned_transport_fetches_same_resource_and_retains_canonical_identity(self):
        self.ingest();called=[]
        result=self.corpus.acquire(fetch=lambda url:(called.append(url) or DATA),interval=0)
        self.assertEqual(called,[HTTP]);self.assertEqual(result['distinct_pdf_blobs'],1)
        row=self.corpus.db.execute('SELECT url,expected_sha,sha,transport_url FROM downloads').fetchone()
        self.assertEqual(row,(URL,SHA,SHA,HTTP))
        self.assertEqual((self.root/'files'/f'{SHA}.pdf').read_bytes(),DATA)
        self.corpus.acquire(fetch=lambda _:self.fail('Refetched'),interval=0)

    def test_unpinned_http_and_foreign_resource_transports_are_rejected(self):
        for transport in ['http://other.test/portal/servlets/AttachmentShowServlet?ImageName=1',
            HTTP.replace('ImageName=1','ImageName=2'),HTTP.replace('/portal/','/different/'),
            HTTP+'#fragment',HTTP.replace(HOST,'user:secret@'+HOST),
            HTTP.replace(HOST,HOST+':443'),HTTP.replace('http:','ftp:')]:
            with self.assertRaisesRegex(ValueError,'same declared official resource'):self.ingest(transport_url=transport)
        with self.assertRaisesRegex(ValueError,'Pinned PDF hash'):self.ingest(sha256=None)
        self.assertEqual(self.corpus.report()['unique_urls'],0)

    def test_hash_mismatch_cannot_retain_transport_payload(self):
        self.ingest();result=self.corpus.acquire(fetch=lambda _:DATA+b'changed',interval=0,attempts=1)
        self.assertEqual(result['download_status'],{'failed':1})
        self.assertEqual(list((self.root/'files').glob('*.pdf')),[])
        self.assertIn('Pinned drawing changed',result['failed_urls'][0]['error'])

    def test_no_transport_keeps_https_request_and_does_not_probe_http(self):
        self.ingest(transport_url=None);called=[]
        self.corpus.acquire(fetch=lambda url:(called.append(url) or DATA),interval=0)
        self.assertEqual(called,[URL])

    def test_existing_corpus_migrates_without_losing_download_records(self):
        self.corpus.close()
        self.corpus.db=None
        old=self.root/'legacy';old.mkdir();db=sqlite3.connect(old/'corpus.sqlite')
        db.execute("CREATE TABLE downloads(url TEXT PRIMARY KEY,expected_sha TEXT,status TEXT DEFAULT 'pending',attempts INTEGER DEFAULT 0,sha TEXT,size INTEGER,error TEXT)")
        db.execute('INSERT INTO downloads(url,expected_sha) VALUES(?,?)',(URL,SHA));db.commit();db.close()
        with_corpus=Corpus(old)
        try:
            self.assertEqual(with_corpus.db.execute('SELECT url,expected_sha,transport_url FROM downloads').fetchone(),(URL,SHA,None))
            with_corpus.ingest([{'url':URL,'sha256':SHA,'transport_url':HTTP}],[HOST])
            self.assertEqual(with_corpus.acquire(fetch=lambda _:DATA,interval=0)['distinct_pdf_blobs'],1)
        finally:with_corpus.close()
        self.corpus=Corpus(self.root)
