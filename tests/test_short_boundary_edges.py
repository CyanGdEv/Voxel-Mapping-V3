import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import pymupdf
from shapely.geometry import Polygon,box,shape
from voxel_mapper.drawing_geometry import extract_page,run,validated_options
from voxel_mapper.linework_boundaries import recover_page

class ShortBoundaryTests(unittest.TestCase):
    def pdf(self):
        document=pymupdf.open();page=document.new_page(width=300,height=300)
        ring=[(20,20),(120,20),(120,120),(20,120),(20,60),(25,60),(25,55),(20,55),(20,20)]
        for a,b in zip(ring,ring[1:]):page.draw_line(a,b)
        for a,b in zip(list(box(50,50,80,80).exterior.coords),list(box(50,50,80,80).exterior.coords)[1:]):page.draw_line(a,b)
        return document,ring

    def test_short_wall_returns_close_exact_source_outline_and_preserve_hole(self):
        document,ring=self.pdf()
        try:
            page=document[0]
            baseline,_=extract_page(page,'a'*64,1)
            parents,_=extract_page(page,'a'*64,1,min_line_length_points=.25)
            self.assertEqual(len(parents)-len(baseline),3)
            self.assertNotEqual(parents[0]['extraction_contract'],baseline[0]['extraction_contract'])
            baseline_faces=[r for r in recover_page(baseline)[0] if r['geometry']['type']=='Polygon']
            faces=[r for r in recover_page(parents)[0] if r['extraction_kind']=='linework_boundaries']
            expected=Polygon([(x,300-y) for x,y in ring],holes=[[(x,300-y) for x,y in box(50,50,80,80).exterior.coords]])
            self.assertFalse(any(shape(r['geometry']).equals(expected) for r in baseline_faces))
            recovered=next(r for r in faces if shape(r['geometry']).equals(expected))
            self.assertEqual(len(shape(recovered['geometry']).interiors),1)
            self.assertFalse(recovered['physical_identity_verified']);self.assertEqual(recovered['world_geometry_additions'],0)
            source_ids={r['id'] for r in parents}
            self.assertTrue(all(p['candidate_id'] in source_ids for p in recovered['line_parent_references']))
            # Native geometry remains exact under rotation, with no endpoint snapping.
            page.set_rotation(90)
            rotated,_=extract_page(page,'a'*64,1,min_line_length_points=.25)
            self.assertEqual([r['geometry'] for r in rotated],[r['geometry'] for r in parents])
        finally:document.close()

    def test_threshold_validation_and_candidate_budget(self):
        for value in [0,.249,13,True,float('nan'),float('inf')]:
            with self.assertRaises(ValueError):validated_options({'min_line_length_points':value})
        document,_=self.pdf()
        try:
            rows,report=extract_page(document[0],'a'*64,1,min_line_length_points=.25,max_candidates=1)
            self.assertEqual(len(rows),1);self.assertEqual(report['status'],'partial_candidate_budget')
            self.assertNotIn('min_line_length_points',validated_options({}))
        finally:document.close()

    def test_retained_replay_and_pipeline_pin_cutoff(self):
        from voxel_mapper.planning_bulk import Corpus
        from voxel_mapper.drawing_footprints import retained_page_candidates
        from voxel_mapper.park_pipeline import run as park
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);corpus=Corpus(root/'corpus');document,_=self.pdf();data=document.tobytes();document.close()
            try:
                corpus.ingest([{'url':'https://portal.test/plan','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda _:data)
                baseline=run(corpus,root/'baseline')
                detailed=run(corpus,root/'details',min_line_length_points=.25)
                self.assertEqual(detailed['candidates']-baseline['candidates'],3)
                self.assertEqual(run(corpus,root/'details',min_line_length_points=.25)['resumed_pages'],1)
                row=json.loads((root/'details/geometry-candidates.jsonl').read_text().splitlines()[0])
                self.assertIn(row,retained_page_candidates(corpus,row))
                job=root/'job.json';job.write_text(json.dumps({'work_directory':'.','acquisition':{'offline':True},'drawing_analysis':{'enabled':False},'drawing_geometry':{'enabled':True,'min_line_length_points':.25},'linework_boundaries':{'enabled':True,'envelopes':True}}))
                report=park(job,'acquire')
                self.assertEqual(report['stages']['drawing_geometry']['contract'],detailed['contract'])
                self.assertGreater(report['stages']['linework_boundaries']['counts']['recovered_faces'],0)
                from voxel_mapper.area_reconstruction import run as area_run
                source_dir=root/'sources';source_dir.mkdir();sha=hashlib.sha256(data).hexdigest()
                (source_dir/(sha+'.pdf')).write_bytes(data)
                (root/'catalogue.json').write_text(json.dumps({'entries':[{'applicationReference':'A','url':'https://portal.test/plan','sha256':sha,'title':'Plan'}]}))
                area_config={'work_directory':'areas','catalogue':'catalogue.json','official_hosts':['portal.test'],
                    'offline':True,'source_directories':['sources'],'drawing_geometry_options':{'min_line_length_points':.25},
                    'areas':[{'id':'a','name':'A','application_references':['A'],'required_families':['wall']}]}
                area_job=root/'area-job.json';area_job.write_text(json.dumps(area_config))
                area=area_run(area_job)['areas']['a']
                self.assertEqual(area['extraction']['contract'],detailed['contract'])
                self.assertEqual(area_run(area_job)['areas']['a']['extraction']['resumed_pages'],1)
                area_config['drawing_geometry_options']['min_line_length_points']=1
                area_job.write_text(json.dumps(area_config))
                with self.assertRaisesRegex(ValueError,'inputs changed'):area_run(area_job)
            finally:corpus.close()
