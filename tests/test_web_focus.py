from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from PIL import Image
import pymupdf

from voxel_mapper import web_evidence as web, web_focus, web_research
from test_web_evidence import capture, PUBLIC, Session, Response, resolver


class WebFocusTests(unittest.TestCase):
    def scope(self):
        return web_focus.profile({'site':'Alton Towers','location':'Farley',
            'tags':['maximum high point','support foundation'],'applications':['SMD/2016/0315'],
            'exclude_tags':['Wildwood']})

    def test_deep_pdf_page_is_recovered_without_changing_original_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp)
            with pymupdf.open() as doc:
                for i in range(25):
                    page=doc.new_page()
                    page.insert_text((20,40),'maximum high point 201m AOD' if i==22 else 'Introduction')
                raw=doc.tobytes()
            item=capture(cache,data=raw,headers={'Content-Type':'application/pdf'})
            self.assertNotIn('201m',item['source']['text'])
            focused=web_focus.inspect(item['source'],cache,self.scope())
            self.assertIn(23,[p['page'] for p in focused['selected_pdf_pages']])
            self.assertIn('201m AOD',focused['text'])
            self.assertEqual(web.cached(PUBLIC,cache,['example.org']),item['source'])
            self.assertFalse(focused['relevance_is_identity_verification'])

    def test_tag_priority_recovers_late_links_and_original_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cache=root/'cache'
            body=('<html>'+''.join('<a href="/doc'+str(i)+'.pdf">Other drawing</a>' for i in range(100))
                +'<a href="/target.pdf">support foundation drawing</a>'
                +'<img src="/photo.png" alt="ride photo"><img src="http://127.0.0.1/private.png"></html>').encode()
            first=capture(cache,data=body)
            second=capture(cache,value=PUBLIC+'target.pdf',data=b'<html>Source drawing record.</html>')
            profile=self.scope()
            self.assertNotIn(PUBLIC+'target.pdf',[l['url'] for l in first['source']['links']])
            focused=web_focus.inspect(first['source'],cache,profile)
            self.assertEqual(focused['links'][0]['url'],PUBLIC+'target.pdf')
            self.assertIn(PUBLIC+'photo.png',[l['url'] for l in focused['links']])
            self.assertFalse(any('127.0.0.1' in l['url'] for l in focused['links']))
            result=web_research.run({'version':web_research.VERSION,'urls':[PUBLIC],
                'allowed_hosts':['example.org'],'research_profile':profile,'offline':True,'limits':{'max_sources':2}},
                root/'output',cache)
            self.assertEqual([s['url'] for s in result['sources']],[PUBLIC,PUBLIC+'target.pdf'])

    def test_image_download_preserves_original_bytes_without_fabricated_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);stream=BytesIO();Image.new('RGB',(32,24),(30,90,160)).save(stream,format='PNG');raw=stream.getvalue()
            item=capture(root/'cache',data=raw,headers={'Content-Type':'image/png'})
            self.assertEqual(item['source']['image_size_pixels'],[32,24])
            self.assertEqual(item['source']['text'],'')
            result=web_research.run({'version':web_research.VERSION,'urls':[PUBLIC],
                'allowed_hosts':['example.org'],'offline':True},root/'output',root/'cache')
            self.assertEqual((root/'output'/result['downloaded_assets'][0]['file']).read_bytes(),raw)
            self.assertEqual(web.cached(PUBLIC,root/'cache',['example.org']),item['source'])

    def test_public_discovery_keeps_private_url_rejection(self):
        config={'version':web_research.VERSION,'urls':['https://another.example/source'],
            'allowed_hosts':['example.org'],'allow_public_discovery':True}
        self.assertIn('another.example',web_research.validate(config)[0])
        with self.assertRaises(ValueError):web_research.validate({**config,'urls':['http://127.0.0.1/private']})
        with self.assertRaises(ValueError):web_focus.profile({'site':'Park','tags':['x'*81]})

    def test_public_media_redirect_is_recorded_and_private_redirect_still_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);stream=BytesIO();Image.new('RGB',(12,12),'blue').save(stream,format='PNG')
            session=Session([Response(status=302,headers={'Location':'https://images.example.org/source.png'}),
                Response(stream.getvalue(),headers={'Content-Type':'image/png'})])
            result=web.fetch(PUBLIC,root/'cache',['example.org'],session=session,resolver=resolver,allow_public_redirects=True)
            self.assertEqual(result['source']['url'],'https://images.example.org/source.png')
            cached=web.fetch(PUBLIC,root/'cache',['example.org'],offline=True,allow_public_redirects=True)
            self.assertEqual(cached['source'],result['source'])
            with self.assertRaises(ValueError):
                web.fetch(PUBLIC,root/'private',['example.org'],resolver=resolver,allow_public_redirects=True,
                    session=Session([Response(status=302,headers={'Location':'http://127.0.0.1/private'})]))


if __name__=='__main__':unittest.main()
