import hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
import pymupdf
from voxel_mapper.area_reconstruction import run,select_documents,compiled_coverage
from tests import test_generation_cycles as fixtures


class AreaSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.sources=self.root/'sources';self.sources.mkdir()
        pdf=pymupdf.open();page=pdf.new_page();page.draw_rect(pymupdf.Rect(20,20,80,80));data=pdf.tobytes();pdf.close()
        self.sha=hashlib.sha256(data).hexdigest();(self.sources/(self.sha+'.pdf')).write_bytes(data)
        self.catalogue={'entries':[{'applicationReference':ref,'url':'https://portal.test/'+ref,'sha256':self.sha,'title':'Plan '+ref} for ref in ['A','B']]}
        (self.root/'catalogue.json').write_text(json.dumps(self.catalogue))
        self.config={'work_directory':'work','catalogue':'catalogue.json','official_hosts':['portal.test'],'offline':True,'source_directories':['sources'],
          'areas':[{'id':ref.lower(),'name':ref,'application_references':[ref],'required_families':['paving','fence']} for ref in ['A','B']]}
        self.job=self.root/'job.json';self.job.write_text(json.dumps(self.config))

    def tearDown(self):self.temp.cleanup()

    def test_native_planning_extraction_is_area_scoped_and_does_not_claim_rebuild(self):
        result=run(self.job);area=result['areas']['a']
        self.assertEqual(area['document_records'],1)
        self.assertEqual(area['extraction']['pages'],1)
        self.assertGreater(area['extraction']['candidates'],0)
        self.assertEqual(area['status'],'awaiting_reconstruction')
        self.assertEqual(area['missing_components'],['paving','fence'])
        self.assertEqual(result['areas']['b']['status'],'pending')
        self.assertFalse((self.root/'work/b').exists())
        resumed=run(self.job)['areas']['a']['extraction']
        self.assertEqual(resumed['file_sha256'],area['extraction']['file_sha256'])
        self.assertEqual(resumed['run_pages'],0)
        self.assertEqual(resumed['resumed_pages'],1)

    def test_changed_catalogue_cannot_resume_an_area_run(self):
        run(self.job);self.catalogue['entries'][0]['title']='Changed source selection'
        (self.root/'catalogue.json').write_text(json.dumps(self.catalogue))
        with self.assertRaisesRegex(ValueError,'inputs changed'):run(self.job)

    def test_no_applications_is_not_a_completed_area(self):
        self.config['areas'][0]['application_references']=[];self.job.write_text(json.dumps(self.config))
        result=run(self.job)
        self.assertEqual(result['areas']['a']['status'],'awaiting_applications')
        self.assertEqual(result['areas']['b']['status'],'pending')

    def test_approval_does_not_expand_selection_to_unrelated_applications(self):
        self.assertEqual(len(select_documents(self.catalogue,self.config['areas'][0])),1)


class AreaCompileTests(unittest.TestCase):
    setUp=fixtures.CycleTests.setUp
    tearDown=fixtures.CycleTests.tearDown

    def pin(self,sha):
        db=sqlite3.connect(self.geometry)
        contract=json.loads(db.execute("SELECT value FROM metadata WHERE key='contract'").fetchone()[0])
        contract['manifest']['sources']=[{'id':'s','metadata':{'planning_document_sha256':sha}}]
        with db:db.execute("UPDATE metadata SET value=? WHERE key='contract'",(json.dumps(contract),))
        db.close()

    def test_generated_features_require_selected_area_plan_bindings(self):
        self.pin('a'*64)
        coverage,_=compiled_coverage(self.geometry,{'a'*64})
        self.assertEqual(coverage,{'paving':2})
        with self.assertRaisesRegex(ValueError,'planning provenance'):
            compiled_coverage(self.geometry,{'b'*64})

    def test_generator_aliases_cover_the_required_primitive_family(self):
        self.pin('a'*64);db=sqlite3.connect(self.geometry)
        for identifier,raw in db.execute('SELECT id,record FROM feature_records').fetchall():
            feature=json.loads(raw);feature['family']='path'
            with db:db.execute('UPDATE feature_records SET record=? WHERE id=?',(json.dumps(feature),identifier))
        db.close()
        self.assertEqual(compiled_coverage(self.geometry,{'a'*64})[0],{'paving':2})

    def test_old_voxel_replay_cannot_count_as_area_reconstruction(self):
        self.pin('a'*64);db=sqlite3.connect(self.geometry)
        contract=json.loads(db.execute("SELECT value FROM metadata WHERE key='contract'").fetchone()[0]);contract['snapshot_mode']='review_draft'
        with db:db.execute("UPDATE metadata SET value=? WHERE key='contract'",(json.dumps(contract),))
        db.close()
        with self.assertRaisesRegex(ValueError,'replay'):
            compiled_coverage(self.geometry,{'a'*64})

    def test_two_planning_recipes_publish_cumulative_area_worlds(self):
        import amulet,numpy as np,rasterio
        from rasterio.transform import from_origin
        from shapely.geometry import mapping,box
        from voxel_mapper.bedrock import material_block
        from voxel_mapper.paving_palette import palette_block
        pdf=pymupdf.open();page=pdf.new_page();page.draw_rect(pymupdf.Rect(10,10,30,30));data=pdf.tobytes();pdf.close()
        sha=hashlib.sha256(data).hexdigest();sources=self.root/'sources';sources.mkdir();(sources/(sha+'.pdf')).write_bytes(data)
        (self.root/'catalogue.json').write_text(json.dumps({'entries':[{'url':'https://portal.test/'+ref,'applicationReference':ref,'sha256':sha} for ref in ['A','B']]}))
        raster=self.root/'terrain.tif'
        with rasterio.open(raster,'w',driver='GTiff',width=200,height=200,count=1,dtype='float32',crs='EPSG:27700',transform=from_origin(-100,100,1,1)) as dst:dst.write(np.ones((200,200),dtype='float32'),1)
        (self.root/'terrain.json').write_text(json.dumps({'terrain':{'path':str(raster),'units':'m','vertical_datum':'ODN','source_id':'terrain'},'sources':[{'id':'terrain'}]}))
        manifest={'crs':'EPSG:27700','vertical_datum':'ODN','terrain_sha256':hashlib.sha256(raster.read_bytes()).hexdigest(),'boundary':mapping(box(-16,-16,64,16)),
                  'sources':[{'id':'plan','kind':'planning','url':'https://portal.test/plan','license':'test','crs':'EPSG:27700','vertical_datum':'ODN','registration_status':'accepted','sha256':sha}]}
        (self.root/'manifest.json').write_text(json.dumps(manifest));areas=[]
        for name,x,surface in [('a',1,'asphalt'),('b',33,'brick')]:
            feature={'id':name+'-plaza','family':'paving','geometry':mapping(box(x+.1,-.9,x+.9,-.1)),'geometry_source':'plan','parameters':{'surface':{'value':surface,'source':'plan','status':'documented'}},'metadata':{'drawing_state':'existing'}}
            (self.root/(name+'.jsonl')).write_text(json.dumps(feature)+'\n')
            job={'work_directory':'unused-'+name,'manifest':'manifest.json','terrain_config':'terrain.json','base_world':str(self.base),'feature_records':name+'.jsonl'}
            (self.root/(name+'-recipe.json')).write_text(json.dumps(job))
            areas.append({'id':name,'name':name,'application_references':[name.upper()],'required_families':['paving'],'required_component_ids':[name+'-plaza'],'reconstruction_job':name+'-recipe.json','bounds':[-16,-16,64,16],'bounds_crs':'EPSG:27700'})
        config={'work_directory':'areas','catalogue':'catalogue.json','official_hosts':['portal.test'],'offline':True,'source_directories':['sources'],'areas':areas}
        job=self.root/'area-job.json';job.write_text(json.dumps(config))
        first=run(job,'reconstruct',5);self.assertEqual(first['areas']['a']['status'],'complete');self.assertEqual(first['areas']['b']['status'],'pending')
        final=run(job,'reconstruct',5);self.assertEqual(final['areas']['b']['status'],'complete')
        world=amulet.load_level(str(self.root/'areas/b/completed-base/bedrock-world'))
        try:
            self.assertEqual(world.get_block(1,1+self.offset,1,'minecraft:overworld'),material_block('gray_concrete'))
            self.assertEqual(world.get_block(33,1+self.offset,1,'minecraft:overworld'),material_block(palette_block('brick',33,-1)))
        finally:world.close()
