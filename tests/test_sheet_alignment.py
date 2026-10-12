import copy
import json
from pathlib import Path
import tempfile
import unittest

from shapely.affinity import rotate, scale, translate
from shapely.geometry import box, mapping
from voxel_mapper.sheet_alignment import fit_sheet


class SheetAlignmentTests(unittest.TestCase):
    def fixture(self):
        local=[box(10,10,30,20),box(100,15,135,40),box(30,100,45,130)]
        refs=[{'id':str(i),'geometry':translate(rotate(scale(g,xfact=2,yfact=2,origin=(0,0)),27,origin=(0,0)),1000,2000),'source_sha256':'b'*64} for i,g in enumerate(local)]
        objects=[{'candidate_id':str(i),'geometry':g,'matches':[{'reference_id':str(i),'source_sha256':'b'*64}]} for i,g in enumerate(local)]
        return objects,refs

    def test_three_objects_recover_shared_rotation_scale(self):
        objects,refs=self.fixture();result=fit_sheet(objects,refs)
        self.assertEqual(result['status'],'sheet_hypotheses_only')
        self.assertEqual(len(result['hypotheses']),1)
        fit=result['hypotheses'][0];self.assertAlmostEqual(fit['scale_metres_per_pdf_point'],2)
        self.assertAlmostEqual(fit['matrix'][0][0],1.782013048)
        self.assertEqual(len(fit['supports']),3);self.assertLess(fit['centroid_rms_m'],1e-9)
        self.assertFalse(result['registration_verified']);self.assertEqual(result['world_geometry_additions'],0)

    def test_two_objects_and_wrong_outline_withheld(self):
        objects,refs=self.fixture();self.assertEqual(fit_sheet(objects[:2],refs)['status'],'withheld')
        refs[2]['geometry']=scale(refs[2]['geometry'],xfact=3,yfact=3)
        self.assertEqual(fit_sheet(objects,refs)['status'],'withheld')

    def test_duplicate_reference_cannot_count_as_two_objects(self):
        objects,refs=self.fixture();objects[2]['matches'][0]['reference_id']='1'
        self.assertEqual(fit_sheet(objects,refs)['status'],'withheld')

    def test_noisy_pair_seeds_refit_to_one_placement(self):
        objects,refs=self.fixture();refs[2]['geometry']=translate(refs[2]['geometry'],.05,0)
        self.assertEqual(fit_sheet(objects,refs)['hypothesis_count'],1)

    def test_nested_outlines_do_not_count_as_separate_objects(self):
        objects,refs=self.fixture()
        for i,obj in enumerate(objects):
            obj['geometry']=box(0,0,100+i*10,100+i*20);refs[i]['geometry']=translate(obj['geometry'],100,200)
        self.assertEqual(fit_sheet(objects,refs)['status'],'withheld')

    def test_collinear_landmarks_withheld(self):
        objects,refs=self.fixture()
        for i,obj in enumerate(objects):
            obj['geometry']=box(i*100,0,i*100+20,10);refs[i]['geometry']=translate(obj['geometry'],100,200)
        self.assertEqual(fit_sheet(objects,refs)['status'],'withheld')

    def test_multiple_complete_placements_retained(self):
        objects,refs=self.fixture();extra=copy.deepcopy(refs)
        for ref in extra:
            ref['id']='other'+ref['id'];ref['geometry']=translate(ref['geometry'],500,0)
        for obj in objects:obj['matches'].append({'reference_id':'other'+obj['candidate_id'],'source_sha256':'b'*64})
        result=fit_sheet(objects,refs+extra)
        self.assertIn('multiple_sheet_placements',result['review_flags']);self.assertGreaterEqual(result['hypothesis_count'],2)

    def test_budgets_pins_and_option_validation(self):
        objects,refs=self.fixture()
        self.assertIn('pair_fit_budget_exhausted',fit_sheet(objects,refs,max_pair_fits=1)['review_flags'])
        self.assertEqual(fit_sheet(objects*22,refs)['reason'],'Sheet object budget exceeded')
        for value in (0,True,10001):
            with self.assertRaises(ValueError):fit_sheet([],[],max_pair_fits=value)
        with self.assertRaises(ValueError):fit_sheet([],[],tolerance_m=float('nan'))
        objects[0]['matches'][0]['source_sha256']='wrong'
        with self.assertRaisesRegex(ValueError,'pin mismatch'):fit_sheet(objects,refs)

    def test_park_pdf_pipeline_and_hash_checked_resume(self):
        import pymupdf
        from voxel_mapper.planning_bulk import Corpus
        from voxel_mapper.park_pipeline import run
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);corpus=Corpus(root/'work/corpus');doc=pymupdf.open();page=doc.new_page(width=400,height=600)
            geometries=[box(10,10,40,25),box(100,20,125,50),box(20,100,45,125)]
            for g in geometries:
                x,y,x2,y2=g.bounds;page.draw_rect(pymupdf.Rect(x,600-y2,x2,600-y))
            data=doc.tobytes();doc.close()
            try:corpus.ingest([{'url':'https://portal.test/a','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda _:data)
            finally:corpus.close()
            (root/'refs').write_text(json.dumps({'type':'FeatureCollection','features':[{'type':'Feature','id':str(i),'geometry':mapping(translate(g,100,200)),'properties':{}} for i,g in enumerate(geometries)]}))
            job={'work_directory':'work','acquisition':{'offline':True},'drawing_analysis':{'enabled':False},'footprint_extraction':{'enabled':True},'footprint_matching':{'enabled':True,'references':'refs','reference_crs':'EPSG:27700','target_crs':'EPSG:27700'},'sheet_alignment':{'enabled':True}}
            (root/'job').write_text(json.dumps(job));first=run(root/'job','acquire')['stages']['sheet_alignment']
            self.assertEqual(first['counts']['sheet_hypotheses_only'],1);self.assertEqual(first['world_geometry_additions'],0)
            self.assertEqual(run(root/'job','acquire')['stages']['sheet_alignment'],first)
            pdf=root/'work/corpus/files'/f"{first['source_documents'][0]}.pdf";original=pdf.read_bytes();pdf.write_bytes(original+b'corrupt')
            # Direct resume must recheck PDF blobs as well as output/feed hashes.
            from voxel_mapper.sheet_alignment import run as align
            corpus=Corpus(root/'work/corpus')
            try:
                with self.assertRaisesRegex(ValueError,'Source PDF checksum mismatch'):align(root/'work/footprints/footprint-candidates.jsonl',root/'work/footprint-matching',root/'refs','EPSG:27700','EPSG:27700',root/'work/sheet-alignment',corpus)
            finally:corpus.close();pdf.write_bytes(original)
            output=root/'work/sheet-alignment/sheet-hypotheses.jsonl';output.write_text(output.read_text()+'\n')
            with self.assertRaisesRegex(ValueError,'Sheet alignment inputs or output changed'):run(root/'job','acquire')

    def test_dense_sheet_records_partial_selection_without_counting_repeated_reference(self):
        import pymupdf
        from voxel_mapper.planning_bulk import Corpus
        from voxel_mapper.drawing_footprints import run as extract
        from voxel_mapper.footprint_matching import run as match
        from voxel_mapper.sheet_alignment import run as align
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);corpus=Corpus(root/'corpus');doc=pymupdf.open();page=doc.new_page(width=400,height=600)
            for i in range(66):
                x=10+(i%11)*30;y=10+(i//11)*30;page.draw_rect(pymupdf.Rect(x,y,x+10,y+5))
            data=doc.tobytes();doc.close()
            try:
                corpus.ingest([{'url':'https://portal.test/dense','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda _:data);extract(corpus,root/'footprints')
                feed=root/'footprints/footprint-candidates.jsonl'
                (root/'refs').write_text(json.dumps({'type':'FeatureCollection','features':[{'type':'Feature','id':'one','geometry':mapping(box(100,200,110,205)),'properties':{}}]}))
                match(feed,root/'refs','EPSG:27700','EPSG:27700',root/'matching',corpus=corpus)
                report=align(feed,root/'matching',root/'refs','EPSG:27700','EPSG:27700',root/'alignment',corpus)
                row=json.loads((root/'alignment/sheet-hypotheses.jsonl').read_text())
                self.assertEqual(row['selected_objects'],64);self.assertEqual(row['deferred_objects'],2)
                self.assertIn('object_selection_truncated',row['review_flags']);self.assertEqual(row['status'],'withheld')
                self.assertEqual(report['counts']['candidates_checked'],66)
            finally:corpus.close()

if __name__=='__main__':unittest.main()
