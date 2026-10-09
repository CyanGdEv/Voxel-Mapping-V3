import copy
import json
from pathlib import Path
import tempfile
import unittest
from shapely.affinity import rotate,scale,translate
from shapely.geometry import Polygon,box,mapping
from voxel_mapper.mapped_sheet_placement import propose,run


class MappedPlacementTests(unittest.TestCase):
    def fixture(self):
        polygons=[Polygon([(0,0),(30,0),(30,10),(10,10),(10,30),(0,30)]),Polygon([(100,10),(140,10),(140,25),(125,25),(125,40),(100,40)]),Polygon([(15,100),(35,100),(40,120),(30,140),(10,125)])]
        objects=[{'candidate_id':str(i),'geometry':g} for i,g in enumerate(polygons)]
        refs=[{'id':str(i),'geometry':translate(rotate(scale(g,xfact=2,yfact=2,origin=(0,0)),15,origin=(0,0)),1000,2000)} for i,g in enumerate(polygons)]
        return objects,refs

    def test_full_boundaries_find_rotated_shared_provisional_fit(self):
        objects,refs=self.fixture();r=propose(objects,refs)
        self.assertEqual(r['status'],'provisional_mapped_placement');self.assertEqual(len(r['hypotheses']),1)
        fit=r['hypotheses'][0];self.assertEqual(len(fit['supports']),3);self.assertAlmostEqual(fit['scale_metres_per_pdf_point'],2)
        self.assertLess(fit['centroid_rms_m'],1e-8);self.assertFalse(r['registration_verified']);self.assertEqual(r['world_geometry_additions'],0)
        from voxel_mapper.reconstruction.registration import require_accepted_review
        with self.assertRaisesRegex(ValueError,'not independently accepted'):require_accepted_review(r)

    def test_mapped_generalisation_is_reported_as_estimated_not_accepted(self):
        objects,refs=self.fixture();refs[2]['geometry']=translate(refs[2]['geometry'],2,1)
        r=propose(objects,refs);self.assertEqual(r['status'],'provisional_mapped_placement')
        self.assertGreater(r['hypotheses'][0]['centroid_rms_m'],.1);self.assertFalse(r['physical_identity_verified'])

    def test_two_objects_nested_duplicates_and_collinear_supports_not_enough(self):
        objects,refs=self.fixture();self.assertEqual(propose(objects[:2],refs)['status'],'withheld')
        objects=[{'candidate_id':str(i),'geometry':box(0,0,100+i,100+i)} for i in range(3)];refs=[{'id':str(i),'geometry':translate(o['geometry'],10,20)} for i,o in enumerate(objects)]
        self.assertEqual(propose(objects,refs)['status'],'withheld')
        objects=[{'candidate_id':str(i),'geometry':box(i*100,0,i*100+20,10)} for i in range(3)];refs=[{'id':str(i),'geometry':translate(o['geometry'],10,20)} for i,o in enumerate(objects)]
        self.assertEqual(propose(objects,refs)['status'],'withheld')

    def test_alternative_locations_remain_ambiguous(self):
        objects,refs=self.fixture();other=copy.deepcopy(refs)
        for r in other:r['id']='other'+r['id'];r['geometry']=translate(r['geometry'],500,0)
        result=propose(objects,refs+other)
        self.assertGreaterEqual(len(result['hypotheses']),2);self.assertIn('multiple_mapped_placements',result['review_flags'])

    def test_reference_and_object_limits_unique_ids_and_thresholds(self):
        objects,refs=self.fixture()
        for n in (True,0,2001):
            with self.assertRaises(ValueError):propose(objects,refs,max_seed_fits=n)
        with self.assertRaises(ValueError):propose(objects,refs,min_iou=float('nan'))
        with self.assertRaises(ValueError):propose(objects+objects,refs)
        r=propose(objects,refs,max_seed_fits=1);self.assertEqual(r['seed_fit_attempts'],1);self.assertIn('seed_fit_budget_exhausted',r['review_flags'])

    def test_all_objects_verify_after_seed_selection_budget(self):
        objects,refs=self.fixture()
        for i in range(70):objects.append({'candidate_id':'tiny'+str(i),'geometry':box(1000+i,1000,1000.1+i,1000.1)})
        r=propose(objects,refs);self.assertEqual(r['verification_objects'],73);self.assertEqual(r['seed_objects'],64)
        self.assertEqual(r['status'],'provisional_mapped_placement')

    def test_hole_topology_mismatch_cannot_supply_support(self):
        objects,refs=self.fixture()
        g=refs[2]['geometry'];x,y=g.centroid.coords[0]
        refs[2]['geometry']=Polygon(g.exterior.coords,[box(x-1,y-1,x+1,y+1).exterior.coords])
        self.assertEqual(propose(objects,refs)['status'],'withheld')

    def test_optional_park_stage_and_resume(self):
        import pymupdf
        from voxel_mapper.planning_bulk import Corpus
        from voxel_mapper.park_pipeline import run as park
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);corpus=Corpus(root/'work/corpus');doc=pymupdf.open();page=doc.new_page(width=400,height=600)
            objects,refs=self.fixture()
            for o in objects:
                s=page.new_shape();s.draw_polyline([pymupdf.Point(x+20,600-y-20) for x,y in o['geometry'].exterior.coords]);s.finish(fill=(.4,.7,.9),closePath=True);s.commit()
            data=doc.tobytes();doc.close()
            try:corpus.ingest([{'url':'https://portal.test/a','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda _:data)
            finally:corpus.close()
            (root/'refs').write_text(json.dumps({'type':'FeatureCollection','features':[{'type':'Feature','id':r['id'],'geometry':mapping(r['geometry']),'properties':{}} for r in refs]}))
            config={'work_directory':'work','acquisition':{'offline':True},'drawing_analysis':{'enabled':False},'drawing_geometry':{'enabled':True},'drawing_components':{'enabled':True},'mapped_placement':{'enabled':True,'references':'refs','reference_crs':'EPSG:27700','target_crs':'EPSG:27700'}}
            job=root/'job.json';job.write_text(json.dumps(config));first=park(job,'acquire')['stages']['mapped_placement']
            self.assertEqual(first['counts']['positioned_review_records'],3);self.assertEqual(park(job,'acquire')['stages']['mapped_placement'],first)

    def test_real_pdf_replay_and_source_output_tamper_refusal(self):
        import pymupdf
        from voxel_mapper.planning_bulk import Corpus
        from voxel_mapper.drawing_geometry import run as extract
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);corpus=Corpus(root/'corpus');doc=pymupdf.open();page=doc.new_page(width=400,height=600)
            objects,refs=self.fixture()
            for o in objects:
                points=[pymupdf.Point(x+20,600-y-20) for x,y in o['geometry'].exterior.coords];s=page.new_shape();s.draw_polyline(points);s.finish(fill=(.4,.7,.9),closePath=True);s.commit()
            data=doc.tobytes();doc.close()
            try:
                corpus.ingest([{'url':'https://portal.test/a','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda _:data);extract(corpus,root/'geometry')
                path=root/'refs';path.write_text(json.dumps({'type':'FeatureCollection','features':[{'type':'Feature','id':r['id'],'geometry':mapping(r['geometry']),'properties':{}} for r in refs]}))
                args=(root/'geometry/geometry-candidates.jsonl',path,'EPSG:27700','EPSG:27700',root/'placement',corpus)
                report=run(*args);self.assertEqual(report['counts']['provisional_mapped_placement'],1);self.assertEqual(report['counts']['positioned_review_records'],3)
                self.assertEqual(run(*args),report)
                # Interrupt after a committed fit, before completed feeds/receipt.
                interrupted=(args[0],args[1],args[2],args[3],root/'interrupted',corpus)
                def stop(_):raise RuntimeError('simulated interruption')
                with self.assertRaisesRegex(RuntimeError,'simulated'):run(*interrupted,progress=stop)
                self.assertFalse((root/'interrupted/placement-report.json').exists())
                resumed=run(*interrupted)
                self.assertEqual(resumed['counts']['page_cache_reused'],1)
                self.assertEqual(resumed['output_sha256'],report['output_sha256'])
                # A changed cached result must not be reused on incomplete resume.
                damaged=(args[0],args[1],args[2],args[3],root/'damaged',corpus)
                with self.assertRaises(RuntimeError):run(*damaged,progress=stop)
                import sqlite3
                db=sqlite3.connect(root/'damaged/page-index.sqlite');db.execute("UPDATE fits SET result=result||' '");db.commit();db.close()
                with self.assertRaisesRegex(ValueError,'page checkpoint changed'):run(*damaged)
                records=[json.loads(s) for s in (root/'placement/placed-review-geometry.jsonl').read_text().splitlines()]
                self.assertTrue(all(not r['properties']['registration_verified'] for r in records))
                pdf=corpus.root/'files'/f"{report['source_documents'][0]}.pdf";original=pdf.read_bytes();pdf.write_bytes(original+b'bad')
                with self.assertRaisesRegex(ValueError,'Source PDF'):run(*args)
                pdf.write_bytes(original);output=root/'placement/placed-review-geometry.jsonl';output.write_text(output.read_text()+'\n')
                with self.assertRaisesRegex(ValueError,'checksum'):run(*args)
                with self.assertRaisesRegex(ValueError,'inputs changed'):run(*args,min_iou=.8)
            finally:corpus.close()

if __name__=='__main__':unittest.main()
