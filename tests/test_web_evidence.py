import copy
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from concurrent.futures import CancelledError

import pymupdf
import requests

from voxel_mapper import web_evidence as web
from voxel_mapper.desktop_memory import digest
from voxel_mapper.generation_cycles import atomic_json


PUBLIC='https://example.org/'


def resolver(name,port,**kwargs):
    return [(2,1,6,'',('93.184.216.34',port))]


class Response:
    def __init__(self,data=b'<html><title>Source</title><body>Evidence text.</body></html>',
                 status=200,headers=None):
        self.data=data;self.status_code=status;self.headers={'Content-Type':'text/html',**(headers or {})};self.closed=False

    def iter_content(self,chunk_size=65536):
        for i in range(0,len(self.data),min(chunk_size,1024)):yield self.data[i:i+min(chunk_size,1024)]

    def close(self):self.closed=True


class Session:
    def __init__(self,responses):
        self.responses=list(responses);self.calls=[];self.cookies=requests.cookies.RequestsCookieJar();self.closed=False

    def get(self,value,**kwargs):
        self.calls.append((value,kwargs));result=self.responses.pop(0)
        if isinstance(result,Exception):raise result
        return result

    def close(self):self.closed=True


def capture(root,value=PUBLIC,data=None,headers=None):
    return web.fetch(value,root,['example.org'],session=Session([Response(data=data or b'<html><title>Source</title><body>Evidence text.</body></html>',headers=headers)]),resolver=resolver)


class WebEvidenceTests(unittest.TestCase):
    def test_main_content_and_drawing_links_precede_navigation(self):
        data=('<html><title>Application</title><nav>Ignore navigation</nav><main>SMD/2024/0136 '
            +''.join('<a href="/navigation/'+str(i)+'">Navigation</a>' for i in range(40))
            +'<a href="/drawing.pdf">Proposed floor plan</a></main></html>').encode()
        result=web._extract(data,'text/html',PUBLIC)
        self.assertTrue(result['text'].startswith('SMD/2024/0136'))
        self.assertNotIn('Ignore navigation',result['text'])
        self.assertEqual(result['links'][0]['url'],PUBLIC+'drawing.pdf')
        self.assertEqual(len(result['links']),web.MAX_LINKS)

    def test_malformed_pdf_is_a_source_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(web.WebError) as error: capture(tmp,data=b'%PDF-invalid bytes')
            self.assertEqual(error.exception.code,'unreadable_content')

    def test_html_fetch_pins_original_bytes_and_offline_cache_reextracts_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);body=b'<html><title>Planning</title><script>run_shell()</script><body>Proposed plan<a href="/plan.pdf">Original plan</a></body></html>'
            session=Session([Response(body)]);result=web.fetch(PUBLIC,root,['example.org'],session=session,resolver=resolver)
            record=result['source'];self.assertEqual(record['title'],'Planning')
            self.assertNotIn('run_shell',record['text']);self.assertEqual(record['links'][0]['url'],PUBLIC+'plan.pdf')
            self.assertEqual(record['body_sha256'],hashlib.sha256(body).hexdigest())
            self.assertFalse(record['source_evidence_verified']);self.assertEqual(record['training_labels_generated'],0)
            value,kwargs=session.calls[0];self.assertFalse(kwargs['allow_redirects'])
            self.assertIsInstance(kwargs['auth'],web._NoOriginAuth)
            self.assertNotIn('verify',kwargs)
            cached=web.fetch(PUBLIC,root,['example.org'],offline=True,resolver=lambda *a,**k:self.fail('No DNS offline'))
            self.assertEqual(cached['source'],record);self.assertEqual(cached['network_bytes'],0)

    def test_source_scope_private_hosts_credentials_and_ports_are_rejected(self):
        bad=['file:///etc/passwd','http://127.0.0.1/a','http://169.254.169.254/',
             'http://localhost/','http://metadata.google.internal/','http://2130706433/',
             'https://user:secret@example.org/','https://example.org:444/a',
             'https://example.org/\nheader','https://example.org\\@localhost/']
        for value in bad:
            with self.subTest(value=value),self.assertRaises(ValueError):web.url(value)
        with self.assertRaises(ValueError):web.url('https://other.org/',['example.org'])
        self.assertEqual(web.url('https://EXAMPLE.org:443/page#fragment'),'https://example.org/page')

    def test_private_dns_or_redirect_never_reaches_disallowed_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            session=Session([Response()])
            with self.assertRaises(web.WebError):
                web.fetch(PUBLIC,tmp,['example.org'],session=session,
                    resolver=lambda *a,**k:[(2,1,6,'',('10.0.0.1',443))])
            self.assertEqual(session.calls,[])
            first=Response(status=302,headers={'Location':'http://127.0.0.1/secret'});session=Session([first])
            with self.assertRaises(ValueError):web.fetch(PUBLIC,tmp,['example.org'],session=session,resolver=resolver)
            self.assertEqual(len(session.calls),1);self.assertTrue(first.closed)

    def test_allowed_redirect_keeps_each_hop_and_clears_cookies(self):
        with tempfile.TemporaryDirectory() as tmp:
            session=Session([Response(status=302,headers={'Location':'/final'}),Response()])
            session.cookies.set('account','must_not_send')
            result=web.fetch(PUBLIC,tmp,['example.org'],session=session,resolver=resolver)
            self.assertEqual(result['source']['url'],PUBLIC+'final')
            self.assertEqual(len(result['source']['redirects']),1);self.assertEqual(len(session.cookies),0)

    def test_pdf_native_text_and_scanned_pdf_are_distinguished(self):
        with tempfile.TemporaryDirectory() as tmp:
            for index,text in enumerate(('Container 8ft x 40ft','')):
                with pymupdf.open() as document:
                    page=document.new_page(width=400,height=200)
                    if text:page.insert_text((20,40),text)
                    data=document.tobytes()
                result=capture(Path(tmp)/str(index),data=data,headers={'Content-Type':'application/pdf'})
                record=result['source'];self.assertEqual(record['format'],'pdf')
                self.assertEqual(record['text_status'],'native_text' if text else 'no_native_text_ocr_required')
                self.assertEqual(web.cached(PUBLIC,Path(tmp)/str(index),['example.org']),record)

    def test_byte_budget_cancellation_and_deadline_have_no_completed_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mode in ('bytes','cancel','deadline'):
                root=Path(tmp)/mode;session=Session([Response(b'x'*4096)])
                kwargs={'budget':web.Budget(100)} if mode=='bytes' else {'cancelled':lambda:True} if mode=='cancel' else {'deadline':time.monotonic()-1}
                with self.assertRaises((web.WebError,CancelledError)):
                    web.fetch(PUBLIC,root,['example.org'],session=session,resolver=resolver,**kwargs)
                self.assertIsNone(web.cached(PUBLIC,root,['example.org']))

    def test_cached_source_bytes_and_resealed_fabricated_excerpt_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);record=capture(root)['source'];pin=record['artifact_sha256']
            changed=copy.deepcopy(record);changed['text']='Invented building measurement'
            changed['artifact_sha256']=digest({k:v for k,v in changed.items() if k!='artifact_sha256'})
            atomic_json(root/'snapshots'/(changed['artifact_sha256']+'.json'),changed)
            atomic_json(root/'urls'/(digest(PUBLIC)+'.json'),{'artifact_sha256':changed['artifact_sha256']})
            with self.assertRaisesRegex(ValueError,'extraction changed'):web.cached(PUBLIC,root,['example.org'])
            atomic_json(root/'urls'/(digest(PUBLIC)+'.json'),{'artifact_sha256':pin})
            web._body_path(root,record).write_bytes(b'corrupted')
            with self.assertRaises(ValueError):web.cached(PUBLIC,root,['example.org'])

    def test_refresh_failure_reuses_pinned_cache_with_explicit_stale_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            record=capture(tmp)['source']
            result=web.fetch(PUBLIC,tmp,['example.org'],session=Session([Response(status=503)]),resolver=resolver)
            self.assertEqual(result['source'],record);self.assertEqual(result['retrieval'],'cached_after_network_failure')
            self.assertIn('503',result['network_error'])

    def test_legacy_council_attachment_ids_are_links_without_javascript_execution(self):
        value='https://publicaccess.staffsmoorlands.gov.uk/application'
        data=b'''<html><a href="javascript:AppBlobImage('353044');">Floor plan</a><a href="javascript:run_shell('x')">Bad</a></html>'''
        result=web._extract(data,'text/html',value)
        self.assertEqual(len(result['links']),1)
        self.assertTrue(result['links'][0]['url'].endswith('AttachmentShowServlet?ImageName=353044'))

    def test_scoped_search_uses_actual_result_links_and_explicit_query_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            query='Alton planning';value='https://html.duckduckgo.com/html/?q=Alton+planning'
            data=b'''<html><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fplan">Plan</a><a class="result__a" href="https://other.org/">Other site</a></html>'''
            web.fetch(value,tmp,[web.SEARCH_HOST],session=Session([Response(data)]),resolver=resolver)
            report=web.search(query,tmp,['example.org'],offline=True)
            self.assertEqual(report['results'],[{'url':PUBLIC+'plan','title':'Plan'}])
            self.assertEqual(report['status'],'scoped_results_found')


if __name__=='__main__':unittest.main()
