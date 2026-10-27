import copy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from bs4 import BeautifulSoup
from voxel_mapper import research_sources as sites, web_evidence as web, web_research, web_focus
from test_web_evidence import capture, PUBLIC


class ResearchSourcesTests(unittest.TestCase):
    def entity(self):
        return {'entities':{'Q25223509':{'labels':{'en':{'value':'Wicker Man'}},
            'descriptions':{'en':{'value':'roller coaster at Alton Towers'}},
            'aliases':{'en':[{'value':'SW8'}]},'claims':{
                'P18':[{'rank':'normal','mainsnak':{'snaktype':'value','datavalue':{'value':'Wicker Man.jpg'}}}],
                'P625':[{'mainsnak':{'snaktype':'value','datavalue':{'value':{'latitude':52.99,'longitude':-1.89}}}}],
                'P856':[{'mainsnak':{'snaktype':'value','datavalue':{'value':'http://127.0.0.1/private'}}}]
            },'sitelinks':{'enwiki':{'title':'Wicker Man','url':'https://en.wikipedia.org/wiki/Wicker_Man'}}}}}

    def test_wikidata_fields_and_literal_identifiers_offer_real_api_routes(self):
        view=sites.extract_json(json.dumps(self.entity()),'https://www.wikidata.org/wiki/Special:EntityData/Q25223509.json')
        self.assertEqual(view['structured_schema'],'wikidata_entities')
        self.assertIn('SW8',view['text']);self.assertIn('P625',view['text'])
        self.assertTrue(any(l['role']=='structured_api' and 'imageinfo' in l['url'] for l in view['links']))
        self.assertFalse(any('127.0.0.1' in l['url'] for l in view['links']))
        self.assertEqual(sites.related_urls('https://www.wikidata.org/wiki/Q25223509',['knowledge']),
            ['https://www.wikidata.org/wiki/Special:EntityData/Q25223509.json'])
        self.assertEqual(sites.related_urls('https://www.wikidata.org/wiki/Q25223509',[]),[])

    def test_json_receipt_reconstructs_offline_and_image_info_download_retains_credit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);metadata={'query':{'pages':{'1':{'title':'Ride image','imageinfo':[{
                'url':PUBLIC+'original.png','thumburl':PUBLIC+'preview.png','extmetadata':{
                    'LicenseShortName':{'value':'CC BY-SA 4.0'},'Artist':{'value':'<a href="https://example.org/author">Photographer</a>'},
                    'LicenseUrl':{'value':'https://creativecommons.org/licenses/by-sa/4.0/'}}}]}}}}
            raw=json.dumps(metadata).encode();item=capture(root/'cache',data=raw,headers={'Content-Type':'application/json'})
            stream=BytesIO();Image.new('RGB',(20,30)).save(stream,format='PNG')
            capture(root/'cache',value=PUBLIC+'preview.png',data=stream.getvalue(),headers={'Content-Type':'image/png'})
            self.assertEqual(web.cached(PUBLIC,root/'cache',['example.org']),item['source'])
            result=web_research.run({'version':web_research.VERSION,'urls':[PUBLIC],'allowed_hosts':['example.org'],
                'offline':True,'limits':{'max_sources':2}},root/'out',root/'cache')
            self.assertEqual(len(result['downloaded_assets']),1)
            self.assertEqual((root/'out'/result['downloaded_assets'][0]['file']).read_bytes(),stream.getvalue())
            self.assertIn('Photographer',item['source']['text']);self.assertIn('CC BY-SA',item['source']['text'])
            self.assertEqual(item['source']['body_sha256'],hashlib.sha256(raw).hexdigest())
            self.assertEqual(result['training_labels_generated'],0)

    def test_geojson_arcgis_planning_and_archive_schemas_remain_research_context(self):
        samples=[({'type':'FeatureCollection','features':[{'properties':{'name':'Ride','document-url':PUBLIC+'plan.pdf'},
            'geometry':{'type':'Point','coordinates':[-1.89,52.99]}}]},'geojson_features'),
            ({'features':[{'attributes':{'reference':'SMD/2026/1234','url':PUBLIC+'plan.pdf'}}]},'arcgis_features'),
            ({'entities':[{'name':'Conservation area','reference':'CA01','document-url':PUBLIC+'doc.pdf'}]},'planning_data_entities'),
            ({'results':[{'title':'Measured drawing','url':PUBLIC+'sheet.pdf'}]},'public_catalogue'),
            ({'item':{'title':'Measured drawing'},'resources':[{'pdf':PUBLIC+'measured.pdf'}]},'loc_item')]
        for sample,expected in samples:
            with self.subTest(expected=expected):
                view=sites.extract_json(json.dumps(sample),PUBLIC)
                self.assertEqual(view['structured_schema'],expected);self.assertTrue(view['links'])
                self.assertEqual(view['text_status'],'structured_public_metadata_unverified')

    def test_arcgis_item_and_layer_metadata_use_bounded_declared_api_routes(self):
        value='https://www.arcgis.com/home/item.html?id='+'a'*32
        self.assertEqual(sites.related_urls(value,['geospatial']),['https://www.arcgis.com/sharing/rest/content/items/'+'a'*32+'?f=json'])
        service='https://services.arcgis.com/abc/arcgis/rest/services/Survey/FeatureServer'
        self.assertEqual(sites.related_urls(service,['geospatial']),[service+'?f=json'])
        view=sites.extract_json(json.dumps({'layers':[{'id':0,'name':'Buildings'}],'description':'Map service'}),service+'?f=json')
        self.assertEqual(view['links'][0]['url'],service+'/0?f=json')
        self.assertEqual(view['structured_schema'],'arcgis_service')

    def test_html_jsonld_and_embedded_council_documents_do_not_change_original_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);body=b'''<html><script type="application/ld+json">{"@type":"Place","name":"Ride station","alternateName":"SW8 station","url":"https://example.org/metadata"}</script><object data="/drawings.pdf" title="Station sections"></object><iframe src="http://127.0.0.1/private"></iframe></html>'''
            item=capture(root,data=body);original=copy.deepcopy(item['source'])
            view=web_focus.inspect(original,root,web_focus.profile({'site':'Alton Towers','tags':['station']}))
            self.assertIn('SW8 station',view['text'])
            self.assertIn(PUBLIC+'drawings.pdf',[l['url'] for l in view['links']])
            self.assertFalse(any('127.0.0.1' in l['url'] for l in view['links']))
            self.assertEqual(web.cached(PUBLIC,root,['example.org']),original)

    def test_schema_budgets_invalid_json_and_api_errors_are_explicit(self):
        for raw in ['{"error":{"code":"maxlag"}}','{"x":1,"x":2}','{"a":NaN}','{"a":1e999}','{"unsupported":true}', '['*40+'0'+']'*40]:
            with self.subTest(raw=raw[:25]),self.assertRaises(ValueError):sites.extract_json(raw,PUBLIC)
        with self.assertRaises(ValueError):sites.families(['unknown'])
        with self.assertRaises(ValueError):sites.families(['rides','rides'])
        approved,*_=web_research.validate({'version':web_research.VERSION,'query':'public park','source_families':['rides']})
        self.assertIn('rcdb.com',approved)
        with self.assertRaises(ValueError):web_research.validate({'version':web_research.VERSION,'urls':['http://127.0.0.1/'],'source_families':['rides']})

    def test_family_searches_keep_public_scope_and_share_controller_budgets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);capture(root/'cache');queries=[]
            def search(query,*args,**kwargs):
                queries.append(query);return {'status':'fixture','results':[{'url':PUBLIC,'title':'Plan'}]}
            result=web_research.run({'version':web_research.VERSION,'query':'Park site:council.example',
                'urls':[PUBLIC],'allowed_hosts':['example.org'],'offline':True,'source_families':['rides','archives'],
                'research_profile':{'site':'Public Park','location':'Public Town','tags':['Ride A']},
                'limits':{'max_sources':1}},root/'out',root/'cache',search=search)
            self.assertEqual(len(queries),3)
            self.assertIn('site:rcdb.com',queries[1]);self.assertIn('Public Park Public Town',queries[1])
            self.assertNotIn('site:council.example',queries[1]);self.assertEqual(len(result['sources']),1)
            self.assertEqual(len(result['site_searches']),2);self.assertEqual(result['network_bytes'],0)

    def test_model_can_follow_resolved_api_as_an_exact_offered_link(self):
        from test_web_evidence import Session,Response,resolver
        from test_local_reasoning import Session as ModelSession,response
        from voxel_mapper import local_reasoning
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);page='https://www.wikidata.org/wiki/Q25223509';api=sites.related_urls(page,['knowledge'])[0]
            for url,data,mime in [(page,b'<html>Wicker Man</html>','text/html'),(api,json.dumps(self.entity()).encode(),'application/json')]:
                web.fetch(url,root/'cache',['www.wikidata.org'],session=Session([Response(data=data,headers={'Content-Type':mime})]),resolver=resolver)
            rounds=iter([{'summary':'Read structured metadata.','proposals':[{'action':'read_web','parameters':{'url':api},'rationale':'Offered metadata view.'}]},
                {'summary':'Metadata retained; physical identity remains unverified.','proposals':[]}])
            def reason(prompt,**kwargs):return local_reasoning.reason(prompt,**kwargs,session=ModelSession(response(next(rounds))))
            result=web_research.run({'version':web_research.VERSION,'urls':[page],'source_families':['knowledge'],
                'allowed_hosts':['www.wikidata.org'],'offline':True,'model':'fixture','limits':{'max_sources':2}},root/'out',root/'cache',reason=reason)
            self.assertEqual(len(result['sources']),2)
            self.assertEqual(len(result['read_only_model_requests_executed']),1)
            self.assertFalse(result['model_weights_updated'])


if __name__=='__main__':unittest.main()
