from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from concurrent.futures import CancelledError
from voxel_mapper import map_planning_research as maps, research_learning_cycle as cycle

BOUNDS=[-1.9,52.98,-1.88,53.0]
XML=b'''<osm version="0.6">
<node id="1" lat="52.99" lon="-1.89" version="2"><tag k="attraction" v="roller_coaster"/><tag k="name" v="Sky Flight"/><tag k="old_name" v="Air"/><tag k="website" v="https://example.org/ride"/><tag k="wikidata" v="Q123"/><tag k="wikipedia" v="en:Sky Flight"/><tag k="ref:planning" v="APP/123"/></node>
<node id="2" lat="52.991" lon="-1.89"/><node id="3" lat="52.991" lon="-1.891"/>
<node id="4" lat="51" lon="-0.5"><tag k="name" v="Other Park Ride"/><tag k="attraction" v="roller_coaster"/></node>
<node id="5" lat="52.99" lon="-1.891"><tag k="name" v="Public Toilet"/><tag k="amenity" v="toilets"/><tag k="website" v="http://127.0.0.1/private"/></node>
<way id="10"><nd ref="1"/><nd ref="2"/><tag k="name" v="Sky Flight"/><tag k="roller_coaster" v="track"/></way>
<way id="11"><nd ref="2"/><nd ref="3"/><tag k="name" v="Ride Shop"/><tag k="building" v="yes"/></way>
<way id="12"><nd ref="99"/><tag k="name" v="Unlocated"/><tag k="building" v="yes"/></way>
<relation id="20"><member type="way" ref="11"/><tag k="name" v="Courtyard"/><tag k="place" v="locality"/></relation>
<relation id="21"><member type="relation" ref="21"/><tag k="name" v="Loop"/><tag k="place" v="locality"/></relation>
</osm>'''


def config(root):
    p=root/'map.xml';p.write_bytes(XML)
    return {'version':maps.VERSION,'site_id':'public-park','site':'Public Park','location':'Public Town',
        'map_source':{'bounds_wgs84':BOUNDS,'snapshot_path':str(p),'snapshot_sha256':hashlib.sha256(XML).hexdigest(),'offline':True},
        'planning_hosts':['council.example.org'],'max_queries':24,'max_research_jobs':0}


class MapPlanningResearchTests(unittest.TestCase):
    def test_names_aliases_relation_bounds_and_tags_have_source_identity(self):
        data=maps.analyse(XML,BOUNDS);rows={r['id']:r for r in data['features']}
        self.assertEqual(rows['osm/node/1']['names'][1],{'text':'Air','tag':'old_name'})
        self.assertEqual(rows['osm/node/1']['ride_type_hint'],'coaster')
        self.assertEqual(len(rows['osm/node/1']['links']),3)
        self.assertEqual(rows['osm/node/5']['links'],[])
        self.assertIn('osm/relation/20',rows)
        self.assertNotIn('osm/relation/21',rows)
        self.assertNotIn('osm/node/4',rows)
        self.assertEqual(data['outside_bounds_named_features'],1)
        self.assertEqual(data['unlocated_named_features'],2)
        self.assertTrue(all(not r['physical_identity_verified'] for r in rows.values()))

    def test_actual_map_tags_become_deduplicated_council_queries_with_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c=config(root);r=maps.run(c,root/'out',root/'cache')
            names=[q['research_profile']['tags'][0] for q in r['queries']]
            self.assertEqual(names.count('Sky Flight'),1)
            self.assertIn('Air',names)
            q=next(q for q in r['queries'] if q['research_profile']['tags'][0]=='Sky Flight')
            self.assertIn('site:council.example.org',q['query'])
            self.assertIn('Public Park Public Town',q['query'])
            self.assertIn('APP/123',q['research_profile']['applications'])
            self.assertEqual(q['source_body_sha256'],hashlib.sha256(XML).hexdigest())
            self.assertEqual((root/'out/osm.xml').read_bytes(),XML)
            self.assertEqual(r['network_bytes'],0);self.assertFalse(r['model_weights_updated'])

    def test_maps_handoff_to_existing_web_research_and_keep_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c=config(root);c['max_research_jobs']=2;c['focus_names']=['Sky Flight']
            c['research']={'allow_public_discovery':True,'allowed_hosts':['council.example.org']};requests=[]
            def research(request,*args,**kwargs):
                requests.append(request)
                return {'status':'fixture','sources':[]}
            r=maps.run(c,root/'out',root/'cache',research=research)
            self.assertEqual(len(requests),2)
            self.assertTrue(all('site:council.example.org' in q['query'] for q in requests))
            self.assertTrue(any('Air' in q['query'] for q in requests))
            self.assertEqual(len(r['research_results']),2)
            self.assertEqual(r['training_labels_generated'],0)
            self.assertFalse(r['production_eligible'])

    def test_query_budget_keeps_building_and_area_clues_among_many_rides(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=config(Path(tmp));features=maps.analyse(XML,BOUNDS)['features']
            rides=[{**features[0],'id':'osm/node/'+str(100+i),'names':[{'text':'Ride '+str(i),'tag':'name'}],
                'category':'ride'} for i in range(40)]
            queries=maps.queries({**c,'max_queries':5},rides+features,'a'*64)
            self.assertIn('building',[q['feature_category'] for q in queries])
            self.assertIn('area',[q['feature_category'] for q in queries])
            queries=maps.queries({**c,'max_queries':2,'focus_names':['Sky Flight']},rides+features,'a'*64)
            self.assertEqual([q['research_profile']['tags'][0] for q in queries],['Sky Flight','Air'])

    def test_malformed_unsafe_or_changed_sources_and_cancellation_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c=config(root)
            (root/'map.xml').write_bytes(XML+b' ')
            with self.assertRaisesRegex(ValueError,'changed'):maps.run(c,root/'out',root/'cache')
            with self.assertRaises(CancelledError):maps.analyse(XML,BOUNDS,cancelled=lambda:True)
            for raw in [b'<!DOCTYPE osm [<!ENTITY a "x">]><osm/>',b'<not-osm/>',b'<osm><node id="1" lat="nan" lon="1"/></osm>']:
                with self.assertRaises(ValueError):maps.analyse(raw,BOUNDS)
            with self.assertRaises(ValueError):maps.validate_source({'bounds_wgs84':[-180,-89,180,89]})
            with self.assertRaises(ValueError):maps.validate_source({'bounds_wgs84':BOUNDS,'snapshot_path':'x'})

    def test_two_parks_do_not_share_scope_or_alias_task_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c=config(root);data=maps.analyse(XML,BOUNDS)
            a=maps.queries(c,data['features'],'a'*64)
            b=maps.queries({**c,'site':'Other Park','site_id':'other','location':'Other Town'},data['features'],'a'*64)
            self.assertTrue(all('Other Park Other Town' in q['query'] for q in b))
            self.assertFalse(set(q['id'] for q in a)&set(q['id'] for q in b))

    def test_learning_cycle_uses_map_clues_then_reuses_model_and_query_memory(self):
        from test_research_learning_cycle import ResearchLearningCycleTests
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c=ResearchLearningCycleTests().config(root);m=config(root)
            c['public_sites'][0]['map_context']=m['map_source']
            c['public_sites'][0]['planning_hosts']=m['planning_hosts'];seen=[]
            def research(request,*args,**kwargs):
                seen.append(request)
                return {'status':'fixture','sources':[{'body_sha256':'d'*64,'url':'https://example.org/drawing.pdf','citation_id':'W123456789abc'}]}
            a=cycle.run(c,root/'first',root/'memory',root/'cache',research=research)
            b=cycle.run(c,root/'second',root/'memory',root/'cache',research=research)
            self.assertEqual(len(a['map_reports']),1)
            self.assertTrue(any('Ride Shop' in q['query'] for q in seen))
            self.assertEqual(len(set(q['query'] for q in seen)),2)
            self.assertTrue(a['model_weights_updated']);self.assertFalse(b['model_weights_updated'])
            self.assertEqual(a['checkpoint_sha256'],b['checkpoint_sha256'])
            self.assertEqual(a['remembered_sources'],2)
            self.assertEqual(a['web_sources_automatically_labelled'],0)

    def test_fetched_project_codes_create_cited_followup_queries_automatically(self):
        from test_web_evidence import capture, PUBLIC
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c=config(root);c['focus_names']=['Sky Flight'];c['max_research_jobs']=2
            item=capture(root/'cache',data=b'<html><body>The project was called SW8, application SMD/2016/0315.</body></html>')
            source={k:item['source'][k] for k in ['url','body_sha256','citation_id']};calls=[]
            def research(request,*args,**kwargs):
                calls.append(request['query']);return {'status':'fixture','sources':[source]}
            result=maps.run(c,root/'out',root/'cache',research=research)
            self.assertEqual(len(calls),2)
            self.assertIn('SMD/2016/0315',calls[1])
            self.assertTrue(any(d['text']=='SW8' for d in result['document_clues']))
            self.assertTrue(all(not d['identity_verified'] for d in result['document_clues']))
            self.assertTrue(all(d['source_body_sha256']==source['body_sha256'] for d in result['document_clues']))

    def test_official_api_cache_budget_and_redirect_handling(self):
        from unittest.mock import patch
        import time
        from voxel_mapper import web_evidence as web
        class Response:
            status_code=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def iter_content(self,size):yield XML
        class Client:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def get(self,url,**kwargs):
                self.request=(url,kwargs);return Response()
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp);source={'bounds_wgs84':BOUNDS};client=Client()
            with patch.object(maps.requests,'Session',return_value=client),patch.object(web,'_public_dns'):
                path,receipt=maps.acquire(source,cache,cancelled=lambda:False,deadline=time.monotonic()+10,budget=web.Budget())
            self.assertEqual(path.read_bytes(),XML)
            self.assertTrue(client.request[0].startswith(maps.API+'?bbox='))
            self.assertFalse(client.request[1]['allow_redirects'])
            path,b=maps.acquire({**source,'offline':True},cache,cancelled=lambda:False,deadline=time.monotonic()+10,budget=web.Budget())
            self.assertEqual(b['retrieval'],'cached')
            path.write_bytes(XML+b' ')
            with self.assertRaisesRegex(ValueError,'changed'):
                maps.acquire(source,cache,cancelled=lambda:False,deadline=time.monotonic()+10,budget=web.Budget())
            with patch.object(maps.requests,'Session',return_value=client),patch.object(web,'_public_dns'):
                with self.assertRaises(web.WebError):
                    maps.acquire(source,cache/'new',cancelled=lambda:False,deadline=time.monotonic()+10,budget=web.Budget(1))
                Response.status_code=302
                with self.assertRaises(web.WebError):
                    maps.acquire(source,cache/'redirect',cancelled=lambda:False,deadline=time.monotonic()+10,budget=web.Budget())

    def test_discovered_application_followup_survives_cycle_restart(self):
        from test_research_learning_cycle import ResearchLearningCycleTests
        from test_web_evidence import capture
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c=ResearchLearningCycleTests().config(root);m=config(root)
            c['public_sites'][0]['map_context']=m['map_source'];seen=[]
            item=capture(root/'cache',data=b'<html>Planning reference SMD/2016/0315; project SW8.</html>')
            source={k:item['source'][k] for k in ['url','body_sha256','citation_id']}
            def research(request,*args,**kwargs):
                seen.append(request['query']);return {'status':'fixture','sources':[source]}
            a=cycle.run(c,root/'first',root/'memory',root/'cache',research=research)
            b=cycle.run(c,root/'second',root/'memory',root/'cache',research=research)
            self.assertGreater(a['remembered_map_followups'],0)
            self.assertIn('SMD/2016/0315',seen[1])
            self.assertNotEqual(seen[0],seen[1]);self.assertFalse(b['model_weights_updated'])

    def test_desktop_worker_reads_relative_pinned_map_snapshot(self):
        from voxel_mapper.desktop_runtime import DesktopRuntime
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c=config(root);c['map_source']['snapshot_path']='map.xml'
            path=root/'request.json';path.write_text(json.dumps(c));runtime=DesktopRuntime(root/'desktop',workers=1,memory_budget_mb=2048)
            try:
                jid=runtime.submit('map_planning_research',path);runtime._futures[jid].result(timeout=30)
                job=runtime.store.job(jid);self.assertEqual(job['status'],'completed',job.get('error'))
                self.assertGreater(job['result']['feature_count'],0)
                self.assertIn('web_source_observation',runtime.store.context(20000))
            finally:runtime.close(wait=True)


if __name__=='__main__':unittest.main()
