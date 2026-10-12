import json
import tempfile
import unittest
from pathlib import Path
from shapely.geometry import box,mapping
from voxel_mapper.reconstruction.batch import GeometryStore,DEFAULT_MAX_FEATURES
from voxel_mapper.reconstruction.engine import Context
from voxel_mapper.reconstruction.model import Feature,Source
from voxel_mapper.reconstruction.sources import evidence
from voxel_mapper.planning_bulk import Corpus

class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.source=Source('s','osm','https://example.test','test','EPSG:27700','ODN')
        self.ctx=Context({'s':self.source},lambda x,z:0,box(-100,-100,1000,1000),'ODN',max_total_voxels=200000)
        self.store=GeometryStore(self.root/'geometry.sqlite',{'test':'v1'})
    def tearDown(self):self.store.close();self.temp.cleanup()
    def feature(self,id,x=0,surface='asphalt',width=2):
        return Feature(id,'paving',mapping(box(x+.1,.1,x+width-.1,1.9)),'s',{'surface':evidence(surface,'s')})
    def test_global_conflict_is_atomic_across_chunks(self):
        self.store.compile([self.feature('a',15)],self.ctx)
        r=self.store.compile([self.feature('b',16,'stone',3)],self.ctx)
        self.assertEqual(r['unique_voxel_cells'],4)
        self.assertEqual(r['decisions'],{'planned':1,'withheld':1})
        self.assertEqual(r['native_chunks'],4)
    def test_shared_cells_keep_all_provenance_and_resume(self):
        f=self.feature('a');self.store.compile([f,self.feature('b')],self.ctx)
        r=self.store.compile([f],self.ctx)
        self.assertEqual(r['resumed_features'],1);self.assertEqual(r['provenance_links'],8)
        row=next(self.store.tile_rows(0,-1));self.assertEqual(row['provenance_count'],2)
        with self.assertRaises(ValueError):self.store.compile([self.feature('a',2)],self.ctx)
    def test_feature_budget_preserves_commits_and_resume_does_not_recount(self):
        self.assertEqual(DEFAULT_MAX_FEATURES,2_500_000)
        a,b,c=self.feature('a'),self.feature('b',10),self.feature('c',20)
        with self.assertRaisesRegex(ValueError,'Total feature budget'):
            self.store.compile([a,b,c],self.ctx,max_features=2)
        self.assertEqual(self.store.report()['features'],2)
        self.assertEqual(self.store.compile([a,b],self.ctx,max_features=2)['resumed_features'],2)
        self.assertEqual(self.store.compile([a,b,c],self.ctx,max_features=3)['features'],3)
        with self.assertRaisesRegex(ValueError,'Retained feature count'):
            self.store.compile([],self.ctx,max_features=2)

    def test_invalid_feature_budgets_rejected(self):
        for limit in (0,-1,True,2.5):
            with self.subTest(limit=limit),self.assertRaises(ValueError):
                self.store.compile([],self.ctx,max_features=limit)

    def test_changed_contract_cannot_resume(self):
        with self.assertRaises(ValueError):GeometryStore(self.root/'geometry.sqlite',{'test':'v2'})
    def test_proposal_does_not_become_current_geometry(self):
        source=Source('s','planning','https://example.test','test','EPSG:27700','ODN','accepted')
        ctx=Context({'s':source},lambda *p:0,self.ctx.boundary,'ODN')
        r=self.store.compile([self.feature('proposed')],ctx)
        self.assertEqual(r['decisions'],{'withheld':1});self.assertEqual(r['unique_voxel_cells'],0)
    def test_total_budget_leaves_committed_features_resumable(self):
        ctx=Context(self.ctx.sources,self.ctx.ground,self.ctx.boundary,'ODN',max_total_voxels=5)
        with self.assertRaises(ValueError):self.store.compile([self.feature('a'),self.feature('b',10)],ctx)
        self.assertEqual(self.store.report()['features'],1)
    def test_tile_hash_and_negative_native_coordinates(self):
        self.store.compile([self.feature('west',-2)],self.ctx)
        r=self.store.export_tiles(self.root/'tiles');self.assertGreater(r['exported_tiles'],0)
        import hashlib
        for line in (self.root/'tiles/tiles.jsonl').read_text().splitlines():
            t=json.loads(line);self.assertEqual(hashlib.sha256((self.root/'tiles'/t['file']).read_bytes()).hexdigest(),t['sha256'])

class CorpusTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.c=Corpus(self.temp.name)
    def tearDown(self):self.c.close();self.temp.cleanup()
    def records(self):return [dict(url='https://portal.test/a',title='Plan',applicationReference='A'),dict(url='https://portal.test/a',title='Plan',applicationReference='B')]
    def test_url_dedup_keeps_application_links_and_corrupt_cache_redownloads(self):
        self.c.ingest(self.records(),['portal.test']);calls=[]
        def fetch(url):calls.append(url);return b'%PDF-test'
        r=self.c.acquire(fetch=fetch);self.assertEqual(len(calls),1);self.assertEqual(r['document_links'],2)
        self.c.acquire(fetch=fetch);self.assertEqual(len(calls),1)
        next((Path(self.temp.name)/'files').glob('*.pdf')).write_bytes(b'broken')
        self.c.acquire(fetch=fetch);self.assertEqual(len(calls),2)
    def test_failure_is_retained_and_resumed(self):
        self.c.ingest(self.records(),['portal.test'])
        r=self.c.acquire(fetch=lambda url:b'<html>error</html>');self.assertEqual(r['download_status'],{'failed':1})
        self.assertEqual(self.c.acquire(fetch=lambda url:b'%PDF-ok')['download_status'],{'downloaded':1})
    def test_pin_and_portal_mismatch_rejected(self):
        with self.assertRaises(ValueError):self.c.ingest([dict(url='https://other.test/a')],['portal.test'])
        self.c.ingest([dict(url='https://portal.test/a',sha256='0'*64)],['portal.test'])
        r=self.c.acquire(fetch=lambda url:b'%PDF-changed');self.assertEqual(r['download_status'],{'failed':1})
    def test_offline_never_calls_network(self):
        self.c.ingest(self.records(),['portal.test'])
        self.assertEqual(self.c.acquire(offline=True,fetch=lambda u:self.fail('network'))['download_status'],{'pending':1})
    def test_byte_budget_stops_scheduling(self):
        self.c.ingest([dict(url=f'https://portal.test/{i}') for i in range(20)],['portal.test']);calls=[]
        def fetch(u):calls.append(u);return b'%PDF-too-big'
        self.c.acquire(workers=1,max_run_bytes=1,fetch=fetch)
        self.assertEqual(len(calls),1)

class NativeBatchTests(unittest.TestCase):
    def test_native_export_preserves_other_cells_and_resumes(self):
        from voxel_mapper.bedrock import export_world,material_block
        from voxel_mapper.reconstruction.batch_export import export_world as export_batch
        import amulet
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);base=root/'base';base.mkdir()
            rows=[dict(x=0,y=10,z=0,kind='structure',material='stone'),dict(x=8,y=10,z=0,kind='structure',material='iron_block')]
            (base/'voxels.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            quality=dict(voxel_size_m=1,sources=[],crs='EPSG:27700',axis={},limitations=[])
            quality['world']=export_world(base/'voxels.jsonl',base,quality)
            (base/'quality-report.json').write_text(json.dumps(quality))
            source=Source('s','osm','https://example.test','test','EPSG:27700','ODN')
            ctx=Context({'s':source},lambda *p:11,box(-16,-16,16,16),'ODN')
            store=GeometryStore(root/'geometry.sqlite',{'manifest':{'crs':'EPSG:27700'}})
            try:
                f=Feature('roof','paving',mapping(box(.1,.1,.9,.9)),'s',{'surface':evidence('asphalt','s')})
                store.compile([f],ctx);report=export_batch(store,base,root/'out');self.assertEqual(report['touched_chunks'],1)
                self.assertEqual(export_batch(store,base,root/'out')['touched_chunks'],1)
                w=amulet.load_level(str(root/'out/bedrock-world'))
                try:
                    self.assertEqual(w.get_block(8,10+quality['world']['vertical_offset_blocks'],0,'minecraft:overworld'),material_block('iron_block'))
                    self.assertEqual(w.get_block(0,11+quality['world']['vertical_offset_blocks'],0,'minecraft:overworld'),material_block(next(store.tile_rows(0,0))['material']))
                finally:w.close()
            finally:store.close()
    def test_unbounded_polygon_withheld_before_raster_scan(self):
        with tempfile.TemporaryDirectory() as d:
            source=Source('s','osm','https://example.test','test','EPSG:27700','ODN')
            ctx=Context({'s':source},lambda *p:0,box(0,0,1e6,1e6),'ODN',max_feature_voxels=100)
            store=GeometryStore(Path(d)/'g.sqlite',{'test':'extent'})
            try:
                feature=Feature('huge','paving',mapping(box(0,0,10000,10000)),'s',{'surface':evidence('asphalt','s')})
                self.assertEqual(store.compile([feature],ctx)['decisions'],{'withheld':1})
            finally:store.close()

class ParkFamilyTests(unittest.TestCase):
    def context(self):
        source=Source('s','osm','https://example.test','test','EPSG:27700','ODN')
        return Context({'s':source},lambda *p:178,box(-20,-20,20,20),'ODN')
    def test_metal_and_wood_fences_use_distinct_native_materials(self):
        from voxel_mapper.reconstruction.engine import ReconstructionEngine
        from voxel_mapper.reconstruction.park_generators import park_registry
        geometry={'type':'LineString','coordinates':[[0,0],[4,0]]}
        engine=ReconstructionEngine(park_registry());ctx=self.context()
        for family,material in [('metal_fence','iron_bars'),('wood_fence','dark_oak_fence')]:
            f=Feature(family,family,geometry,'s',{'height_m':evidence(1.5,'s'),'material':evidence(material,'s')})
            rows,r=engine.plan([f],ctx);self.assertEqual(r['decisions'][0]['status'],'planned');self.assertEqual({row['material'] for row in rows},{material})
    def test_water_hole_and_explicit_datum_are_preserved(self):
        from shapely.geometry import Polygon,Point
        from voxel_mapper.reconstruction.engine import ReconstructionEngine
        from voxel_mapper.reconstruction.park_generators import park_registry
        ring=Polygon(box(0,0,4,4).exterior,[box(1,1,3,3).exterior])
        f=Feature('lake','lake',mapping(ring),'s',{k:evidence(v,'s') for k,v in {'surface_elevation_m':179,'bed_elevation_m':176,'bed_material':'gravel'}.items()})
        rows,r=ReconstructionEngine(park_registry()).plan([f],self.context())
        self.assertTrue(rows);self.assertTrue(all(not box(1,1,3,3).contains(Point(row['x']+.5,row['z']+.5)) for row in rows))
        f.parameters['bed_elevation_m']['value']=178.8
        self.assertEqual(ReconstructionEngine(park_registry()).plan([f],self.context())[1]['decisions'][0]['status'],'withheld')
    def test_missing_3d_ride_heights_cannot_be_fabricated_by_alias(self):
        from voxel_mapper.reconstruction.engine import ReconstructionEngine
        from voxel_mapper.reconstruction.park_generators import park_registry
        f=Feature('ride','ride_layout',{'type':'LineString','coordinates':[[0,0],[4,0]]},'s',{'material':evidence('iron_block','s')})
        self.assertEqual(ReconstructionEngine(park_registry()).plan([f],self.context())[1]['decisions'][0]['status'],'withheld')

class DiscoveryTests(unittest.TestCase):
    def test_attachment_discovery_keeps_existing_state_and_resumes_pages(self):
        from unittest.mock import patch,MagicMock
        from voxel_mapper.planning_bulk import discover_alton
        host='publicaccess.staffsmoorlands.gov.uk'
        with tempfile.TemporaryDirectory() as d:
            corpus=Corpus(d)
            try:
                search={'applications':[{'reference':'SMD/2020/0001','application_context':'Alton Towers Farley Lane','url':f'https://{host}/portal/servlets/ApplicationSearchServlet?PKID=1'}],'complete_search':True}
                (Path(d)/'alton-application-search.json').write_text(json.dumps(search))
                response=MagicMock();response.__enter__.return_value=response;response.status_code=200
                response.iter_content.return_value=[b'''<p>SMD/2020/0001</p><a href="javascript:AppBlobImage('123');">Existing Site Plan</a>''']
                session=MagicMock();session.__enter__.return_value=session;session.get.return_value=response
                with patch('voxel_mapper.planning_bulk.requests.Session',return_value=session),patch('voxel_mapper.planning_bulk.time.sleep'):
                    result=discover_alton(corpus);self.assertEqual(result['application_states'],{'discovered':1})
                    discover_alton(corpus);self.assertEqual(session.get.call_count,1)
                record=json.loads(corpus.db.execute('SELECT record FROM documents').fetchone()[0]);self.assertEqual(record['state'],'existing')
                self.assertEqual(result['unique_urls'],1);self.assertFalse(result['complete_council_discovery'])
            finally:corpus.close()

class NormalizeTests(unittest.TestCase):
    def test_streamed_frames_identities_and_drawing_state(self):
        from voxel_mapper.reconstruction.normalize import normalize
        source=Source('drawing','planning','https://example.test','test','EPSG:27700','ODN')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);input=root/'source.geojsonl'
            records=[dict(type='Feature',id=i,geometry=mapping(box(i,0,i+1,1)),properties=dict(kind='path',surface='asphalt',drawing_state='existing')) for i in range(2)]
            input.write_text(''.join(json.dumps(r)+'\n' for r in records))
            result=normalize(input,root/'out.jsonl',source,'EPSG:27700');rows=[json.loads(l) for l in (root/'out.jsonl').read_text().splitlines()]
            self.assertEqual(result['features'],2);self.assertEqual([r['id'] for r in rows],['drawing/0','drawing/1'])
            self.assertEqual(rows[0]['metadata']['drawing_state'],'existing');self.assertEqual(rows[0]['metadata']['input_sha256'],result['input_sha256'])

class PipelineTests(unittest.TestCase):
    def test_empty_corpus_waits_for_semantics_and_changed_inputs_rejected(self):
        from voxel_mapper.park_pipeline import run
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);manifest=root/'manifest.json';manifest.write_text(json.dumps({'crs':'EPSG:27700','sources':[]}))
            job=root/'job.json';job.write_text(json.dumps({'work_directory':'work','manifest':'manifest.json','acquisition':{'offline':True}}))
            result=run(job)
            self.assertEqual(result['stages']['reconstruction']['status'],'awaiting_normalized_geometry')
            self.assertFalse((root/'work/world/park.mcworld').exists())
            self.assertEqual(run(job)['stages']['reconstruction'],result['stages']['reconstruction'])
            manifest.write_text(json.dumps({'crs':'EPSG:27700','sources':[],'changed':True}))
            with self.assertRaises(ValueError):run(job,'reconstruct')
