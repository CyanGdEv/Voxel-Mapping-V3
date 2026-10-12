import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import fitz
from scripts import acquire_wicker_site_sections as acquisition


class Response:
    status=200
    headers={'Content-Type':'application/pdf'}
    def __init__(self,data,url):self.data,self.url=data,url
    def read(self,n):return self.data[:n]
    def __enter__(self):return self
    def __exit__(self,*args):return False


class WickerSiteSectionAcquisitionTests(unittest.TestCase):
    def run_source(self,payload,url=None,corrupt=False):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); page=root/'page.html'
            raw=b'<td>31/05/2016</td><td><a href="javascript:AppBlobImage(\'160141\');">Proposed Block Plan</a>'
            page.write_bytes(raw);out=root/'out';out.mkdir()
            if corrupt:(out/(hashlib.sha256(payload).hexdigest()+'.pdf')).write_bytes(b'corrupt')
            with patch.object(acquisition,'PAGE_SHA',hashlib.sha256(raw).hexdigest()),patch.object(acquisition,'ATTACHMENTS',[160141]),patch.object(acquisition,'urlopen',return_value=Response(payload,url or 'http://publicaccess.staffsmoorlands.gov.uk/file')):
                result=acquisition.acquire(page,out)
            self.assertEqual(json.loads((out/'download-receipt.json').read_text()),result)
            return result['documents'][0]

    def pdf(self):
        with fitz.open() as document:
            document.new_page();return document.tobytes()

    def test_observed_link_provenance_and_valid_pdf(self):
        row=self.run_source(self.pdf())
        self.assertEqual(row['status'],'downloaded')
        self.assertEqual(row['upload_date_as_listed'],'31/05/2016')
        self.assertEqual(row['pages'],1)

    def test_html_response_and_foreign_redirect_rejected(self):
        self.assertEqual(self.run_source(b'<html>error</html>')['status'],'failed')
        row=self.run_source(self.pdf(),'https://other.example/file.pdf')
        self.assertEqual(row['status'],'failed');self.assertIn('redirect',row['reason'])

    def test_corrupt_existing_blob_is_not_overwritten(self):
        row=self.run_source(self.pdf(),corrupt=True)
        self.assertEqual(row['status'],'failed');self.assertIn('corrupt',row['reason'])

    def test_unpinned_application_page_is_rejected_before_download(self):
        with tempfile.TemporaryDirectory() as directory:
            page=Path(directory)/'page';page.write_text('unexpected')
            with patch.object(acquisition,'urlopen') as download:
                with self.assertRaisesRegex(ValueError,'Pinned'):
                    acquisition.acquire(page,Path(directory)/'out')
                download.assert_not_called()

if __name__=='__main__':unittest.main()
