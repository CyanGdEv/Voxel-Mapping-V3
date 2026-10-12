from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
import pymupdf
from shapely.geometry import box
from voxel_mapper.planning_bulk import Corpus
from voxel_mapper.drawing_geometry import run as extract
from voxel_mapper.planning_components import run as mentions
from voxel_mapper.component_binding import run
from voxel_mapper.reconstruction.model import Feature
from voxel_mapper.reconstruction.batch import GeometryStore
from voxel_mapper.reconstruction.engine import Context
from voxel_mapper.reconstruction.sources import evidence
from tests import test_drawing_footprints as fixtures


class ComponentBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.corpus=Corpus(self.root/'corpus')
        pdf=pymupdf.open();page=pdf.new_page(width=400,height=600)
        page.draw_line((20,570),(40,570));page.insert_text((20,545),'timber fence 2m ht')
        data=pdf.tobytes();pdf.close()
        self.corpus.ingest([{'url':'https://portal.test/a'}],['portal.test']);self.corpus.acquire(fetch=lambda _:data)
        extract(self.corpus,self.root/'drawing');mentions(self.corpus,self.root/'drawing',self.root/'mentions')
        self.candidate=json.loads((self.root/'drawing/geometry-candidates.jsonl').read_text());self.mention=json.loads((self.root/'mentions/component-mentions.jsonl').read_text())
        helper=fixtures.FootprintTests();alignment=helper.alignment();sha=self.candidate['document_sha256']
        self.source=replace(helper.source(alignment),sha256=sha,metadata={**helper.source(alignment).metadata,'registration_document_sha256':sha})
        self.binding={**helper.review(),'candidate_id':self.candidate['id'],'feature_id':'queue/fence','family':'wood_fence',
            'line_role':'boundary','line_role_verification_reference':'fixture survey fence boundary',
            'parameters':{'height_m':evidence(2,'drawing'),'material':evidence('oak_fence','drawing')},
            'mention_id':self.mention['id'],'component_role':'fence','label_geometry_verified':True,
            'label_geometry_verification_reference':'fixture checked fence label leader and endpoints'}
        self.manifest=self.root/'manifest.json';self.manifest.write_text(json.dumps({'crs':'EPSG:27700','vertical_datum':'ODN','sources':[self.source.__dict__]}))

    def tearDown(self):self.corpus.close();self.temp.cleanup()

    def bind(self):
        p=self.root/'bindings.json';p.write_text(json.dumps([self.binding]))
        return run(self.corpus,self.root/'mentions/component-mentions.jsonl',self.root/'drawing/geometry-candidates.jsonl',p,self.manifest,self.root/'bound')

    def test_verified_binding_enters_actual_compiler_with_component_provenance(self):
        report=self.bind();self.assertEqual(report['accepted_component_ids'],['queue/fence'])
        feature=Feature(**json.loads((self.root/'bound/features.jsonl').read_text()))
        self.assertEqual(feature.metadata['component_mention_id'],self.mention['id'])
        store=GeometryStore(self.root/'geometry.sqlite',{'test':'component-binding'})
        try:
            result=store.compile([feature],Context({'drawing':self.source},lambda x,z:0,box(0,0,500,500),'ODN'))
            self.assertEqual(result['decisions'],{'planned':1});self.assertGreater(result['unique_voxel_cells'],0)
        finally:store.close()
        self.assertEqual(self.bind()['output_sha256'],report['output_sha256'])

    def test_suggestion_alone_cannot_promote_or_leave_stale_features(self):
        self.bind();self.binding['label_geometry_verified']=False
        report=self.bind();self.assertEqual(report['accepted_records'],0)
        self.assertEqual((self.root/'bound/features.jsonl').read_text(),'')
        self.assertIn('association evidence',report['decisions'][0]['reason'])

    def test_changed_native_mention_is_withheld(self):
        altered={**self.mention,'text':'Changed printed fence height'}
        (self.root/'mentions/component-mentions.jsonl').write_text(json.dumps(altered)+'\n')
        result=self.bind();self.assertEqual(result['accepted_records'],0)
        self.assertIn('current native PDF',result['decisions'][0]['reason'])

    def test_missing_independent_registration_is_not_bypassed(self):
        source=self.source.__dict__.copy();source['metadata']={**source['metadata'],'horizontal_registration_review':{}}
        self.manifest.write_text(json.dumps({'crs':'EPSG:27700','sources':[source]}))
        self.assertEqual(self.bind()['accepted_records'],0)

    def test_wrong_role_or_missing_same_page_candidate_is_withheld(self):
        self.binding['component_role']='stairs';result=self.bind();self.assertEqual(result['accepted_records'],0)
        self.assertIn('3D recipe',result['decisions'][0]['reason'])
        self.binding['component_role']='fence';self.binding['candidate_id']='missing'
        self.assertEqual(self.bind()['accepted_records'],0)

    def test_park_job_compiles_bound_components_and_rejects_changed_bindings_on_resume(self):
        import hashlib
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin
        from shapely.geometry import mapping
        from voxel_mapper.park_pipeline import run as park_run
        self.bind()
        raster=self.root/'terrain.tif'
        with rasterio.open(raster,'w',driver='GTiff',width=500,height=500,count=1,dtype='float32',crs='EPSG:27700',transform=from_origin(0,500,1,1)) as dst:dst.write(np.zeros((500,500),dtype='float32'),1)
        terrain=self.root/'terrain.json';terrain.write_text(json.dumps({'terrain':{'path':str(raster),'units':'m','vertical_datum':'ODN','source_id':'terrain'},'sources':[{'id':'terrain'}]}))
        manifest=json.loads(self.manifest.read_text());manifest.update(boundary=mapping(box(0,0,500,500)),terrain_sha256=hashlib.sha256(raster.read_bytes()).hexdigest())
        self.manifest.write_text(json.dumps(manifest))
        job={'work_directory':'park','manifest':str(self.manifest),'terrain_config':str(terrain),
             'planning_components':{'corpus':str(self.corpus.root),'mentions':str(self.root/'mentions/component-mentions.jsonl'),
                'candidates':str(self.root/'drawing/geometry-candidates.jsonl'),'bindings':str(self.root/'bindings.json')}}
        job_path=self.root/'park-job.json';job_path.write_text(json.dumps(job))
        result=park_run(job_path,'compile')
        self.assertEqual(result['stages']['planning_components']['accepted_records'],1)
        self.assertTrue((self.root/'park/geometry.sqlite').exists())
        self.assertEqual(park_run(job_path,'compile')['stages']['input_contract'],result['stages']['input_contract'])
        self.binding['parameters']['height_m']=evidence(3,'drawing')
        (self.root/'bindings.json').write_text(json.dumps([self.binding]))
        with self.assertRaisesRegex(ValueError,'inputs changed'):park_run(job_path,'compile')

    def test_known_printed_height_cannot_be_replaced_by_another_documented_value(self):
        self.binding['parameters']['height_m']=evidence(3,'drawing')
        result=self.bind();self.assertEqual(result['accepted_records'],0)
        self.assertIn('contradicts',result['decisions'][0]['reason'])
