from dataclasses import asdict
import hashlib,json,math,tempfile,unittest
from pathlib import Path
from shapely.geometry import box
from voxel_mapper.reconstruction.local_buildings import canonical_hash,prepare_feed
from voxel_mapper.reconstruction.registration import review_registration
from voxel_mapper.reconstruction.model import Source,Feature
from voxel_mapper.reconstruction.engine import Context,ReconstructionEngine
from voxel_mapper.reconstruction.park_generators import park_registry
from voxel_mapper.reconstruction.batch import GeometryStore,json_lines

MODEL=Path(__file__).resolve().parents[1]/'evidence/wicker-shop-projection-model.json'

class LocalBuildingTests(unittest.TestCase):
    def fixture(self,directory,angle=0):
        root=Path(directory);model=json.loads(MODEL.read_text());sha=hashlib.sha256(MODEL.read_bytes()).hexdigest()
        c,s=math.cos(math.radians(angle)),math.sin(math.radians(angle))
        def pair(id,x,z):return {'id':id,'local':[x,z],'target':[100+c*x-s*z,200+s*x+c*z]}
        review=review_registration([pair('a',-30,-30),pair('b',30,-30),pair('c',-30,30)],[pair('d',30,30),pair('e',0,40)])
        sources={'placement':Source('placement','survey','https://example.test/control','fixture','EPSG:27700','ODN','accepted',metadata={'horizontal_registration_review':review}),
                 'profile':Source('profile','local_component','local://shop','fixture','EPSG:27700',sha256=sha,metadata={'canonical_model_sha256':canonical_hash(model)}),
                 'floor':Source('floor','survey','https://example.test/floor','fixture','EPSG:27700','ODN','accepted')}
        p={'id':'shop','geometry_source':'placement','profile_source':'profile','elevation_source':'floor','anchor_xy':[100,200],'base_elevation_m':101,'floor_status':'measured','assembly_identity_verified':True}
        (root/'placement.json').write_text(json.dumps(p));(root/'model.json').write_bytes(MODEL.read_bytes())
        entry={'model':'model.json','model_sha256':sha,'placement':'placement.json'}
        manifest={'crs':'EPSG:27700','sources':[asdict(s) for s in sources.values()]}
        receipt=prepare_feed([entry],manifest,lambda p:root/p,root/'features.jsonl')
        feature=next(json_lines(root/'features.jsonl'))
        context=Context(sources,lambda x,z:100.,box(60,160,140,240),'ODN',True)
        return feature,context,receipt,entry,manifest

    def test_rotated_source_profile_compiles_and_exports_through_chunk_store(self):
        for angle in (0,25.244359980951014,90):
            with self.subTest(angle=angle),tempfile.TemporaryDirectory() as d:
                f,ctx,_,_,_=self.fixture(d,angle)
                store=GeometryStore(Path(d)/'geometry.sqlite',{'fixture':True})
                try:
                    report=store.compile([f],ctx);self.assertEqual(report['decisions'],{'planned':1})
                    self.assertGreater(report['native_chunks'],1)
                    store.export_tiles(Path(d)/'tiles')
                    materials={r['material'] for cx,cz in store.db.execute('SELECT DISTINCT cx,cz FROM voxels') for r in store.tile_rows(cx,cz)}
                    self.assertIn('dark_oak_slab',materials);self.assertIn('dark_oak_fence',materials)
                    self.assertTrue(any('_trapdoor_' in m for m in materials))
                finally:store.close()

    def test_registration_datum_estimate_and_collision_fail_atomically(self):
        with tempfile.TemporaryDirectory() as d:
            f,ctx,_,_,_=self.fixture(d);engine=ReconstructionEngine(park_registry())
            rows,_=engine.plan([f],ctx);self.assertTrue(rows)
            f.parameters['assembly_identity_verified']['value']='unverified';self.assertFalse(engine.plan([f],ctx)[0]);f.parameters['assembly_identity_verified']['value']='accepted'
            ctx.allow_estimates=False;self.assertFalse(engine.plan([f],ctx)[0]);ctx.allow_estimates=True
            ctx.vertical_datum='ellipsoid';self.assertFalse(engine.plan([f],ctx)[0]);ctx.vertical_datum='ODN'
            from voxel_mapper.bedrock import material_block
            ctx.occupied=lambda *p:material_block('stone');self.assertFalse(engine.plan([f],ctx)[0]);ctx.occupied=None
            ctx.sources['placement']=Source('placement','survey','x','fixture','EPSG:27700','ODN','accepted')
            self.assertFalse(engine.plan([f],ctx)[0])

    def test_asset_tamper_and_changed_floor_are_pinned(self):
        with tempfile.TemporaryDirectory() as d:
            f,ctx,receipt,entry,manifest=self.fixture(d);root=Path(d)
            data=json.loads((root/'placement.json').read_text());data['base_elevation_m']=102;(root/'placement.json').write_text(json.dumps(data))
            newer=prepare_feed([entry],manifest,lambda p:root/p,root/'new.jsonl')
            self.assertNotEqual(receipt['output_sha256'],newer['output_sha256'])
            (root/'model.json').write_bytes(MODEL.read_bytes()+b' ')
            with self.assertRaises(ValueError):prepare_feed([entry],manifest,lambda p:root/p,root/'bad.jsonl')

    def test_opted_in_foundations_fill_to_terrain_and_reject_grading_atomically(self):
        with tempfile.TemporaryDirectory() as d:
            f,ctx,_,entry,manifest=self.fixture(d,25.244359980951014)
            root=Path(d);p=json.loads((root/'placement.json').read_text())
            p['foundation_mode']='level_pad';(root/'placement.json').write_text(json.dumps(p))
            prepare_feed([entry],manifest,lambda p:root/p,root/'grounded.jsonl')
            f=next(json_lines(root/'grounded.jsonl'));ctx.ground=lambda x,z:97.2
            engine=ReconstructionEngine(park_registry());rows,_=engine.plan([f],ctx)
            self.assertTrue(rows)
            fill=[r for r in rows if r['y']<101]
            self.assertTrue(fill)
            self.assertTrue(all(98<=r['y']<=100 for r in fill))
            self.assertTrue(any(r['material']=='stone' for r in fill))
            self.assertTrue(any(r['material']=='spruce_planks' and r['y']==100 for r in fill))
            ctx.ground=lambda x,z:101.0
            self.assertFalse(engine.plan([f],ctx)[0])
            ctx.ground=lambda x,z:97.2
            f.parameters['foundation_mode']['value']='unreviewed_excavation'
            self.assertFalse(engine.plan([f],ctx)[0])

    def test_park_job_wiring_resumes_and_rejects_changed_placement(self):
        import numpy as np,rasterio
        from rasterio.transform import from_origin
        from shapely.geometry import mapping
        from voxel_mapper.park_pipeline import run
        with tempfile.TemporaryDirectory() as d:
            f,ctx,_,entry,manifest=self.fixture(d,25.244359980951014);root=Path(d)
            terrain=root/'ground.tif'
            with rasterio.open(terrain,'w',driver='GTiff',height=80,width=80,count=1,dtype='float32',crs='EPSG:27700',transform=from_origin(60,240,1,1)) as ds:
                ds.write(np.full((80,80),100,dtype='float32'),1)
            manifest.update(vertical_datum='ODN',boundary=mapping(ctx.boundary),terrain_sha256=hashlib.sha256(terrain.read_bytes()).hexdigest())
            (root/'manifest.json').write_text(json.dumps(manifest))
            (root/'terrain.json').write_text(json.dumps({'terrain':{'path':str(terrain),'source_id':'floor','units':'m','vertical_datum':'ODN'},'sources':[{'id':'floor'}]}))
            from voxel_mapper.bedrock import export_world
            base=root/'base';base.mkdir()
            (base/'voxels.jsonl').write_text(''.join(json.dumps({'x':x,'y':100,'z':z,'kind':'terrain','material':'grass_block'})+'\n' for x in range(80,121) for z in range(180,221)))
            quality={'voxel_size_m':1,'sources':[],'crs':'EPSG:27700','axis':{},'limitations':[]}
            quality['world']=export_world(base/'voxels.jsonl',base,quality,ground_depth=4)
            (base/'quality-report.json').write_text(json.dumps(quality))
            job={'work_directory':'work','manifest':'manifest.json','terrain_config':'terrain.json','allow_estimates':True,'local_buildings':[entry],'base_world':'base'}
            (root/'job.json').write_text(json.dumps(job))
            result=run(root/'job.json','reconstruct')
            self.assertEqual(result['stages']['reconstruction']['decisions'],{'planned':1})
            self.assertTrue((root/'work/world/park.mcworld').is_file())
            resumed=run(root/'job.json','compile')
            self.assertEqual(resumed['stages']['reconstruction']['unique_voxel_cells'],result['stages']['reconstruction']['unique_voxel_cells'])
            self.assertEqual(resumed['stages']['reconstruction']['features'],1)
            p=json.loads((root/'placement.json').read_text());p['base_elevation_m']=102;(root/'placement.json').write_text(json.dumps(p))
            with self.assertRaisesRegex(ValueError,'inputs changed'):run(root/'job.json','compile')
