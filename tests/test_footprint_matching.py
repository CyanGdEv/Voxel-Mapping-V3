import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from shapely.geometry import box,mapping
from voxel_mapper.footprint_matching import shortlist,reconcile,run

class MatchingTests(unittest.TestCase):
    def reference(self,id,geometry,name='Lake'):
        from voxel_mapper.footprint_matching import descriptor
        aspect,fill=descriptor(geometry)
        return {'id':id,'geometry':geometry,'name':name,'aspect':aspect,'fill':fill,'source_sha256':'b'*64}
    def feature(self,id,geometry,**metadata):
        return {'id':id,'family':'lake','source_id':id,'geometry':mapping(geometry),'metadata':metadata}
    def db(self):
        db=sqlite3.connect(':memory:');db.executescript('CREATE TABLE records(feature_id TEXT UNIQUE,payload TEXT); CREATE VIRTUAL TABLE spatial USING rtree(id,minx,maxx,miny,maxy);');return db
    def test_unplaced_shape_never_claims_size_or_position(self):
        results=shortlist(box(0,0,10,10),[self.reference('distant',box(10000,10000,11000,11000))])
        self.assertEqual(results[0]['metrics']['shape_descriptor_error'],0)
        self.assertIsNone(results[0]['metrics']['area_ratio']);self.assertIsNone(results[0]['metrics']['distance_m'])
        self.assertFalse(shortlist(box(0,0,10,10),[self.reference('distant',box(10000,10000,11000,11000))],placed=True))
    def test_registered_matching_uses_overlap_and_size(self):
        rows=[self.reference('wrong-size',box(0,0,100,100)),self.reference('correct',box(0,0,10,10))]
        results=shortlist(box(0,0,10,10),rows,placed=True)
        self.assertEqual(results[0]['reference_id'],'correct');self.assertEqual(results[0]['metrics']['intersection_over_union'],1)
    def test_name_can_shortlist_different_shape_without_acceptance(self):
        results=shortlist(box(0,0,10,10),[self.reference('lake',box(0,0,100,10))],{'lake'})
        self.assertTrue(results[0]['metrics']['exact_interior_name']);self.assertIsNone(results[0]['metrics']['intersection_over_union'])
    def test_revisions_keep_proposal_and_existing_without_winner(self):
        db=self.db()
        try:
            self.assertFalse(list(reconcile(db,self.feature('old',box(0,0,10,10),sheet_key='A',issue_date='2020-01-01',sheet_revision_reference='checked title block A',drawing_state='existing'),box(0,0,10,10))))
            decisions=list(reconcile(db,self.feature('proposal',box(1,0,11,10),sheet_key='A',issue_date='2025-01-01',sheet_revision_reference='checked title block B',drawing_state='proposed'),box(1,0,11,10)))
            self.assertEqual(decisions[0]['chronology']['later_feature_id'],'proposal');self.assertIsNone(decisions[0]['selected_feature_id']);self.assertEqual(decisions[0]['drawing_states'],['existing','proposed'])
        finally:db.close()
    def test_duplicates_different_sheet_and_invalid_dates_do_not_order(self):
        db=self.db()
        try:
            list(reconcile(db,self.feature('one',box(0,0,10,10),sheet_key='A',issue_date='2020-01-01'),box(0,0,10,10)))
            for id,key,dt in [('two','B','2025-01-01'),('three','A','Rev C')]:
                results=list(reconcile(db,self.feature(id,box(0,0,10,10),sheet_key=key,issue_date=dt),box(0,0,10,10)))
                self.assertEqual(results[0]['classification'],'duplicate_geometry');self.assertIsNone(results[0]['chronology'])
        finally:db.close()
    def test_pipeline_reports_unplaced_hypothesis_and_pins_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);geometry=box(0,0,10,10);sha='a'*64
            candidate={'id':hashlib.sha256((sha+'/1/'+geometry.normalize().wkb_hex).encode()).hexdigest(),'document_sha256':sha,'page':1,'geometry':mapping(geometry),'coordinate_frame':'pdf_native_points_y_up'}
            (root/'candidates').write_text(json.dumps(candidate)+'\n')
            (root/'refs').write_text(json.dumps({'type':'FeatureCollection','features':[{'type':'Feature','id':'lake','geometry':mapping(box(100,100,200,200)),'properties':{'name':'Lake'}}]}))
            report=run(root/'candidates',root/'refs','EPSG:27700','EPSG:27700',root/'out')
            self.assertEqual(report['counts']['native_with_shortlist'],1);self.assertEqual(report['world_geometry_additions'],0)
            result=json.loads((root/'out/associations.jsonl').read_text());self.assertFalse(result['physical_identity_verified']);self.assertEqual(result['status'],'unplaced_shape_name_hypotheses')
            with self.assertRaises(ValueError):run(root/'candidates',root/'refs','EPSG:27700','EPSG:27700',root/'out')
    def test_native_name_requires_unique_interior_and_current_pdf(self):
        import pymupdf
        from voxel_mapper.planning_bulk import Corpus
        from voxel_mapper.drawing_footprints import run as extract
        from voxel_mapper.footprint_matching import NativeNames
        for overlap in (False,True):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);corpus=Corpus(root/'corpus');doc=pymupdf.open();page=doc.new_page(width=400,height=600)
                page.draw_rect(pymupdf.Rect(100,100,300,300))
                if overlap:page.draw_rect(pymupdf.Rect(110,110,290,290))
                page.insert_text((150,200),'The Boating Lake');data=doc.tobytes();doc.close()
                try:
                    corpus.ingest([{'url':'https://portal.test/a','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda u:data);extract(corpus,root/'out')
                    candidates=[json.loads(line) for line in (root/'out/footprint-candidates.jsonl').read_text().splitlines()]
                    names=NativeNames(corpus,[self.reference('lake',box(0,0,10,10),'The Boating Lake')])
                    try:
                        matched=[names.get(c) for c in candidates]
                        self.assertEqual(any(matched),not overlap)
                        altered={**candidates[0],'paint_ordinals':[999]}
                        with self.assertRaisesRegex(ValueError,'retained'):names.get(altered)
                    finally:names.close()
                    next((root/'corpus/files').glob('*.pdf')).write_bytes(b'changed')
                    names=NativeNames(corpus,[self.reference('lake',box(0,0,10,10),'The Boating Lake')])
                    try:
                        with self.assertRaisesRegex(ValueError,'checksum'):names.get(candidates[0])
                    finally:names.close()
                finally:corpus.close()

    def test_park_acquisition_matching_resumes_and_checks_output_hash(self):
        import pymupdf
        from voxel_mapper.planning_bulk import Corpus
        from voxel_mapper.park_pipeline import run as run_job
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus=Corpus(root/'work/corpus');doc=pymupdf.open();page=doc.new_page();page.draw_rect(pymupdf.Rect(100,100,200,200));data=doc.tobytes();doc.close()
            try:
                corpus.ingest([{'url':'https://portal.test/a','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda u:data)
            finally:corpus.close()
            (root/'refs').write_text(json.dumps({'type':'FeatureCollection','features':[{'type':'Feature','id':'lake','geometry':mapping(box(100,100,200,200)),'properties':{'name':'Lake'}}]}))
            (root/'job.json').write_text(json.dumps({'work_directory':'work','acquisition':{'offline':True},'drawing_analysis':{'enabled':False},'footprint_extraction':{'enabled':True},'footprint_matching':{'enabled':True,'references':'refs','reference_crs':'EPSG:27700','target_crs':'EPSG:27700'}}))
            first=run_job(root/'job.json','acquire');second=run_job(root/'job.json','acquire')
            self.assertEqual(first['stages']['footprint_matching'],second['stages']['footprint_matching'])
            (root/'work/footprint-matching/associations.jsonl').write_text('changed')
            with self.assertRaisesRegex(ValueError,'checksum'):run_job(root/'job.json','acquire')

    def test_tampered_candidate_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'c').write_text(json.dumps({'id':'wrong','document_sha256':'a'*64,'page':1,'geometry':mapping(box(0,0,10,10)),'coordinate_frame':'pdf_native_points_y_up'})+'\n');(root/'r').write_text(json.dumps({'type':'FeatureCollection','features':[]}))
            with self.assertRaisesRegex(ValueError,'identity/frame'):run(root/'c',root/'r','EPSG:27700','EPSG:27700',root/'out')

if __name__=='__main__':unittest.main()
