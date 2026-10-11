import hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
import pymupdf
from voxel_mapper.area_reconstruction import run,run_all,select_documents,compiled_coverage
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

    def test_explicit_area_preserves_unfinished_previous_area(self):
        first=run(self.job);previous=first['areas']['a'].copy()
        result=run(self.job,area_id='b')
        self.assertEqual(result['areas']['a'],previous)
        self.assertEqual(result['active_area_id'],'b')
        self.assertEqual(result['areas']['b']['status'],'awaiting_reconstruction')
        self.assertEqual(result['areas']['b']['selected_documents'][0]['title'],'Plan B')
        self.assertEqual(run(self.job,area_id='b')['areas']['b']['extraction']['run_pages'],0)
        self.assertEqual(run(self.job)['active_area_id'],'b')

    def test_unknown_area_is_rejected_without_source_work(self):
        with self.assertRaisesRegex(ValueError,'Unknown resort area'):run(self.job,area_id='missing')
        self.assertFalse((self.root/'work/area-state.json').exists())

    def test_full_sweep_visits_later_areas_after_source_blocker(self):
        self.config['areas'][0]['application_references']=[];self.job.write_text(json.dumps(self.config))
        report=run_all(self.job)
        self.assertEqual(report['areas_tested'],2)
        self.assertEqual([r['status'] for r in report['results']],['awaiting_applications','awaiting_reconstruction'])
        self.assertEqual(report['status'],'completed_with_blockers')
        self.assertEqual(report['areas_with_native_preview'],0)
        self.assertGreater(report['results'][1]['extraction']['candidates'],0)
        self.assertEqual(report,json.loads((self.root/'work/sweep-report.json').read_text()))

    def test_sweep_records_error_and_continues_without_claiming_world_output(self):
        from unittest.mock import patch
        real_run=run
        def fail_first(*args):
            if args[-1]=='a':raise ValueError('Deliberate area test failure')
            return real_run(*args)
        with patch('voxel_mapper.area_reconstruction.run',side_effect=fail_first):report=run_all(self.job)
        self.assertEqual(report['results'][0]['status'],'test_error')
        self.assertEqual(report['results'][1]['status'],'awaiting_reconstruction')
        self.assertEqual(report['areas_with_native_preview'],0)

    def test_explicit_initial_baseline_rejects_changed_package(self):
        base=self.root/'baseline';base.mkdir();package=base/'park.mcworld';package.write_bytes(b'pinned review')
        self.config.update(initial_base_world='baseline',initial_base_sha256=hashlib.sha256(package.read_bytes()).hexdigest())
        self.job.write_text(json.dumps(self.config));run(self.job,area_id='b')
        package.write_bytes(b'changed review')
        with self.assertRaisesRegex(ValueError,'baseline checksum'):run(self.job,area_id='b')

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

    def two_area_fixture(self):
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
        config={'work_directory':'areas','catalogue':'catalogue.json','official_hosts':['portal.test'],'offline':True,'source_directories':['sources'],'areas':areas,
                'initial_base_world':str(self.base),'initial_base_sha256':hashlib.sha256((self.base/'park.mcworld').read_bytes()).hexdigest()}
        job=self.root/'area-job.json';job.write_text(json.dumps(config))
        return job

    def test_two_planning_recipes_publish_cumulative_area_worlds(self):
        import amulet
        from voxel_mapper.bedrock import material_block
        from voxel_mapper.paving_palette import palette_block
        job=self.two_area_fixture()
        first=run(job,'reconstruct',5);self.assertEqual(first['areas']['a']['status'],'complete');self.assertEqual(first['areas']['b']['status'],'pending')
        final=run(job,'reconstruct',5);self.assertEqual(final['areas']['b']['status'],'complete')
        world=amulet.load_level(str(self.root/'areas/b/completed-base/bedrock-world'))
        try:
            self.assertEqual(world.get_block(1,1+self.offset,1,'minecraft:overworld'),material_block('gray_concrete'))
            self.assertEqual(world.get_block(33,1+self.offset,1,'minecraft:overworld'),material_block(palette_block('brick',33,-1)))
        finally:world.close()

    def test_automatic_workers_finish_area_cycles_and_retain_partial_geometry(self):
        from voxel_mapper.area_cycles import prepare,produce,assemble
        from voxel_mapper.bedrock import material_block
        from voxel_mapper.paving_palette import palette_block
        import amulet
        job=self.two_area_fixture();config=json.loads(job.read_text())
        config['areas'][0]['required_component_ids'].append('a-missing-fence')
        config['areas'][0]['batch_chunks']=1
        feature=json.loads((self.root/'a.jsonl').read_text());feature['id']='a-second-plaza'
        feature['geometry']['coordinates']=[[[17.1,-.9],[17.9,-.9],[17.9,-.1],[17.1,-.1],[17.1,-.9]]]
        with (self.root/'a.jsonl').open('a') as out:out.write(json.dumps(feature)+'\n')
        job.write_text(json.dumps(config))
        first=prepare(job);self.assertEqual(first['active_cycle']['area_id'],'a')
        # A missing worker must neither publish nor advance the area cursor.
        produce(job,0)
        with self.assertRaises((ValueError,FileNotFoundError)):assemble(job)
        self.assertEqual(json.loads((self.root/'areas/auto-cycle-state.json').read_text())['published_cycles'],0)
        for number in range(10):produce(job,number)
        first=assemble(job);self.assertEqual(first['cursor'],0)
        self.assertEqual(prepare(job,1)['status'],'paused_cycle_budget')
        second=prepare(job,3);self.assertEqual(second['active_cycle']['area_id'],'a')
        for number in range(10):produce(job,number)
        # Simulate interruption after the native publish, before controller save.
        run(job,'assemble',1,'a')
        third=prepare(job);self.assertEqual(third['published_cycles'],2)
        self.assertEqual(third['areas']['a']['status'],'partial_area_preview')
        self.assertEqual(third['active_cycle']['area_id'],'b')
        for number in range(10):produce(job,number)
        assemble(job);final=prepare(job)
        self.assertEqual(final['status'],'completed_with_blockers')
        self.assertEqual(final['published_cycles'],3)
        world=amulet.load_level(str(self.root/'areas/b/completed-base/bedrock-world'))
        try:
            self.assertEqual(world.get_block(1,1+self.offset,1,'minecraft:overworld'),material_block('gray_concrete'))
            self.assertEqual(world.get_block(17,1+self.offset,1,'minecraft:overworld'),material_block('gray_concrete'))
            self.assertEqual(world.get_block(33,1+self.offset,1,'minecraft:overworld'),material_block(palette_block('brick',33,-1)))
        finally:world.close()
