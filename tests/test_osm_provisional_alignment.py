from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
import pymupdf
from pyproj import Transformer
from shapely.affinity import scale,rotate,translate
from shapely.geometry import Polygon,shape
from shapely.ops import transform
from voxel_mapper.planning_bulk import Corpus
from voxel_mapper.drawing_geometry import run as extract
from voxel_mapper.mapped_sheet_placement import propose
from voxel_mapper.osm_provisional_alignment import run,osm_collection
from voxel_mapper.evidence_memory import EvidenceMemory

CRS='+proj=aeqd +lat_0=52.99 +lon_0=-1.88 +datum=WGS84 +units=m +no_defs'

class OSMAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.corpus=Corpus(self.root/'corpus')
        with pymupdf.open() as doc:
            page=doc.new_page(width=600,height=600);page.insert_text((10,15),'Scale 1:100',fontsize=8)
            for i,(x,y) in enumerate([(50,50),(350,50),(50,350),(350,350),(180,200)]):
                p=Polygon([(x,y),(x+30+i*3,y),(x+30+i*3,y+10),(x+10,y+10),(x+10,y+30+i*2),(x,y+30+i*2)])
                drawing=page.new_shape();drawing.draw_polyline(list(p.exterior.coords));drawing.finish(closePath=True);drawing.commit()
            data=doc.tobytes()
        self.corpus.ingest([{'url':'https://portal.test/plan','title':'Plan'}],['portal.test']);self.corpus.acquire(fetch=lambda _:data)
        extract(self.corpus,self.root/'geometry')
        rows=[json.loads(line) for line in (self.root/'geometry/geometry-candidates.jsonl').read_text().splitlines()]
        self.objects=[{'candidate_id':r['id'],'geometry':shape(r['geometry'])} for r in rows]
        project=Transformer.from_crs(CRS,'EPSG:4326',always_xy=True);elements=[];self.refs=[]
        for i,r in enumerate(rows):
            g=translate(rotate(scale(shape(r['geometry']),100*.0254/72,100*.0254/72,origin=(0,0)),15,origin=(0,0)),50,80)
            self.refs.append({'id':'osm/way/'+str(i+1),'geometry':g})
            wgs=transform(project.transform,g)
            elements.append({'type':'way','id':i+1,'tags':{'building':'yes'},'geometry':[{'lon':x,'lat':y} for x,y in wgs.exterior.coords]})
        self.osm=self.root/'osm.json';self.osm.write_text(json.dumps({'elements':elements}))
    def tearDown(self):self.corpus.close();self.tmp.cleanup()
    def align(self,output='alignment'):
        return run(self.corpus,self.root/'geometry',self.osm,self.root/'memory.sqlite',self.root/output,target_crs=CRS)
    def test_fixed_scale_held_out_overlay_and_persistent_replay(self):
        first=self.align();self.assertEqual(first['page_statuses'],{'map_consistent_provisional_alignment':1})
        self.assertEqual(first['provisional_overlay_records'],5);self.assertFalse(first['registration_verified'])
        row=json.loads((Path(first['output_directory'])/'page-alignments.jsonl').read_text())
        self.assertEqual(row['outline_investigation']['failed_checks'],0)
        self.assertIsNone(row['absolute_error_bound_m']);self.assertLess(row['uncertainty']['held_out_map_disagreement_m'],1e-6)
        for check in row['alignment_checks']['hypotheses'][0]['held_out_checks']:
            self.assertNotIn(check['candidate_id'],check['fit_landmark_ids'])
        with patch('voxel_mapper.osm_provisional_alignment.propose',wraps=propose) as matcher:
            second=self.align('replay')
            self.assertEqual(second['reused_pages'],1);self.assertEqual(matcher.call_count,1) # input budget validation only
        self.assertEqual(first['output_sha256'],second['output_sha256'])
        self.assertEqual(first['semantic_context']['run_pages'],1)
        self.assertEqual(second['semantic_context']['reused_pages'],1)
        self.assertEqual(first['semantic_context']['output_sha256'],second['semantic_context']['output_sha256'])
    def test_wrong_scale_and_alternative_map_locations_do_not_supply_overlay(self):
        wrong=propose(self.objects,self.refs,expected_scale=.2)
        self.assertEqual(wrong['hypotheses'],[])
        alternative=[{**r,'id':'other/'+r['id'],'geometry':translate(r['geometry'],1000,0)} for r in self.refs]
        result=propose(self.objects,self.refs+alternative,expected_scale=100*.0254/72)
        self.assertGreater(len(result['hypotheses']),1)
    def test_changed_reference_snapshot_is_a_new_fact_and_source_changes_fail(self):
        first=self.align();raw=json.loads(self.osm.read_text());raw['elements'][0]['tags']['name']='Updated';self.osm.write_text(json.dumps(raw))
        second=self.align();self.assertEqual(second['run_pages'],1);self.assertNotEqual(first['contract'],second['contract'])
        self.assertEqual(second['semantic_context']['run_pages'],1)
        feed=self.root/'geometry/geometry-candidates.jsonl';feed.write_text('changed')
        with self.assertRaisesRegex(ValueError,'geometry feed changed'):self.align()
    def test_batch_budget_changes_cached_page_contract(self):
        first=self.align()
        changed=run(self.corpus,self.root/'geometry',self.osm,self.root/'memory.sqlite',
            self.root/'one-batch',target_crs=CRS,max_seed_batches=1)
        self.assertEqual(first['contract']['max_seed_batches'],8)
        self.assertEqual(changed['contract']['max_seed_batches'],1)
        self.assertEqual(changed['run_pages'],1)
        self.assertNotEqual(first['page_facts'],changed['page_facts'])

    def test_new_targeted_polygon_triggers_matching_and_replays_without_recovery(self):
        from shapely.geometry import mapping
        extra={'id':'targeted-outline','geometry':mapping(translate(self.objects[0]['geometry'],1000,1000)),
            'extraction_kind':'drawing_geometry','paint_references':[{'ordinal':0}],'extraction_contract':'fixture'}
        report={'status':'targeted_source_geometry_only','registration_verified':False,'world_geometry_additions':0}
        with patch('voxel_mapper.osm_provisional_alignment.recover_targeted',return_value=([extra],report)), \
                patch('voxel_mapper.osm_provisional_alignment.propose',wraps=propose) as matcher:
            first=self.align()
        self.assertEqual(matcher.call_count,3) # validation, initial, expanded inventory
        row=json.loads((Path(first['output_directory'])/'page-alignments.jsonl').read_text())
        self.assertEqual(row['targeted_source_recovery']['new_unique_polygons'],1)
        self.assertEqual(row['objects'],6);self.assertEqual(row['targeted_source_candidates'],json.loads(json.dumps([extra])))
        self.assertIn('initial_alignment_checks',row)
        self.assertFalse(row['registration_verified']);self.assertEqual(row['world_geometry_additions'],0)
        with patch('voxel_mapper.osm_provisional_alignment.recover_targeted',side_effect=AssertionError('recovery replayed')):
            replay=self.align('targeted-replay')
        self.assertEqual(replay['reused_pages'],1);self.assertEqual(first['output_sha256'],replay['output_sha256'])

    def test_partial_snapshot_and_invalid_scale_rejected(self):
        self.osm.write_text(json.dumps({'elements':[],'remark':'timeout'}))
        with self.assertRaisesRegex(ValueError,'Complete bounded'):osm_collection(self.osm)
        for value in (True,float('nan'),0):
            with self.assertRaises(ValueError):propose(self.objects,self.refs,expected_scale=value)
    def test_osm_api_xml_keeps_way_identity(self):
        self.osm.write_text('<osm><node id="1" lon="0" lat="0"/><node id="2" lon="0.001" lat="0"/><node id="3" lon="0.001" lat="0.001"/><way id="7" version="2" timestamp="2020-01-01T00:00:00Z"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="1"/><tag k="building" v="yes"/></way></osm>')
        collection,_,_=osm_collection(self.osm);self.assertEqual(collection['features'][0]['id'],'osm/way/7')
        self.assertEqual(collection['features'][0]['properties']['source_metadata'],{'version':'2','timestamp':'2020-01-01T00:00:00Z'})

    def test_regional_recovery_uses_complete_source_lines_without_clipping(self):
        from voxel_mapper.drawing_geometry import extract_pipeline_page
        from voxel_mapper.osm_provisional_alignment import recover_outlines
        from voxel_mapper.linework_boundaries import recover_page
        with pymupdf.open() as doc:
            page=doc.new_page(width=400,height=200)
            for x in (40,280):
                points=[(x,40),(x+50,40),(x+50,90),(x,90),(x,40)]
                for a,b in zip(points,points[1:]):page.draw_line(a,b)
            candidates,report=extract_pipeline_page(page,'a'*64,1,max_paths=4,regional_columns=2,regional_rows=1)
            self.assertEqual(len(candidates),8)
            calls=[]
            def bounded(parents):
                calls.append(len(parents))
                return ([],{'status':'network_budget_withheld','counts':{},'recovered_faces':0}) if len(calls)==1 else recover_page(parents)
            with patch('voxel_mapper.osm_provisional_alignment.recover_page',side_effect=bounded):
                faces,recovery=recover_outlines({'candidates':candidates,'report':report})
            self.assertEqual(calls,[8,4,4]);self.assertEqual(len(faces),2)
            self.assertTrue(all(shape(c['geometry']).area==2500 for c in faces))
            self.assertFalse(recovery['completeness_verified'])
