import hashlib
import json
import sqlite3
import unittest
from voxel_mapper.bedrock import material_block
from voxel_mapper.generation_cycles import CyclePlan
from voxel_mapper.generation_cycle_export import preview
from tests import test_generation_cycles as cycle_tests


class DraftCycleTests(unittest.TestCase):
    setUp=cycle_tests.CycleTests.setUp
    tearDown=cycle_tests.CycleTests.tearDown
    workers=cycle_tests.CycleTests.workers
    block=cycle_tests.CycleTests.block

    def draft(self,correct_guard=True):
        self.plan.close();self.plan.path.unlink()
        db=sqlite3.connect(self.geometry)
        contract=json.loads(db.execute("SELECT value FROM metadata WHERE key='contract'").fetchone()[0])
        contract['snapshot_mode']='review_draft'
        with db:
            db.execute("UPDATE metadata SET value=? WHERE key='contract'",(json.dumps(contract),))
            # Replace a protected stone baseline, not just an empty air cell.
            row={'x':15,'y':0,'z':0,'feature':'crossing','material':'oak_planks','review_only':True,
                 'baseline_block_sha256':hashlib.sha256(str(material_block('stone')).encode()).hexdigest() if correct_guard else 'wrong'}
            # The fixture has no stone at x15; put the test replacement at x0.
            row['x']=0
            db.execute('DELETE FROM voxels');db.execute('DELETE FROM evidence')
            db.execute('INSERT INTO voxels VALUES(?,?,?,?,?,?,?)',(0,0,0,0,0,'oak_planks',json.dumps(row)))
            db.execute('INSERT INTO evidence VALUES(?,?,?,?,?)',(0,0,0,'crossing','{}'))
        db.close()

    def test_draft_cannot_enter_normal_cycle_plan_without_explicit_option(self):
        self.draft()
        with self.assertRaisesRegex(ValueError,'explicit allow_draft'):
            CyclePlan.create(self.root/'cycles.sqlite',self.geometry,self.base,[[x,0] for x in range(4)])
        self.plan=CyclePlan.create(self.root/'cycles.sqlite',self.geometry,self.base,[[x,0] for x in range(4)],allow_draft=True,workers=2)
        self.assertTrue(self.plan.contract['review_draft'])

    def test_guarded_draft_replacement_is_published_with_draft_status(self):
        self.draft()
        self.plan=CyclePlan.create(self.root/'cycles.sqlite',self.geometry,self.base,[[x,0] for x in range(4)],allow_draft=True,workers=2,sections=1)
        self.workers(1);receipt=preview(self.plan,self.geometry,self.base,1,self.output)
        self.assertFalse(receipt['production_placement_eligible'])
        self.assertEqual(receipt['status'],'native_review_batch_export_verified')
        self.assertEqual(self.block(self.output/receipt['file'],0,0,0),material_block('oak_planks'))

    def test_wrong_baseline_guard_prevents_export_and_cycle_advancement(self):
        self.draft(False)
        self.plan=CyclePlan.create(self.root/'cycles.sqlite',self.geometry,self.base,[[x,0] for x in range(4)],allow_draft=True,workers=2,sections=1)
        self.workers(1)
        with self.assertRaisesRegex(ValueError,'baseline block changed'):preview(self.plan,self.geometry,self.base,1,self.output)
        self.assertEqual(self.plan.next_cycle(),1)

    def test_focus_section_is_first_and_retains_exclusive_chunk_ownership(self):
        self.plan.close();self.plan.path.unlink()
        self.plan=CyclePlan.create(self.root/'cycles.sqlite',self.geometry,self.base,[[x,0] for x in range(4)],sections=3,focus_chunks=[[2,0]],workers=2)
        self.assertEqual(self.plan.chunks(1),[(2,0)])
        all_chunks=[c for cycle in self.plan.report()['cycles'] for c in self.plan.chunks(cycle['id'])]
        self.assertEqual(sorted(all_chunks),[(x,0) for x in range(4)])

    def test_oversized_or_foreign_focus_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Focus section'):
            CyclePlan.create(self.root/'bad.sqlite',self.geometry,self.base,[[x,0] for x in range(4)],focus_chunks=[[8,0]])

    def test_whole_polygon_material_policy_is_shared_with_park_extraction(self):
        from voxel_mapper.paving_palette import polygon_surface
        self.assertEqual(polygon_surface(['stone','brick paving']),'brick')
        self.assertEqual(polygon_surface(['stone','tarmac']),'asphalt')
        self.assertEqual(polygon_surface(['concrete','stone']),'concrete')
        self.assertEqual(polygon_surface([]),'stone')
        self.assertIsNone(polygon_surface(['wood','gravel']))

    def test_large_worker_payload_survives_staging_and_promotion(self):
        from concurrent.futures import ThreadPoolExecutor
        from voxel_mapper.generation_cycle_export import worker,verify_worker
        self.plan.close();self.plan.path.unlink()
        db=sqlite3.connect(self.geometry)
        with db:
            for x in range(12):
                for z in range(-12,0):
                    for y in range(2,26):
                        row={'x':x,'y':y,'z':z,'material':'oak_planks','feature':'crossing'}
                        db.execute('INSERT INTO voxels VALUES(?,?,?,?,?,?,?)',(x,y,z,0,0,'oak_planks',json.dumps(row)))
                        db.execute('INSERT INTO evidence VALUES(?,?,?,?,?)',(x,y,z,'crossing','{}'))
        db.close()
        self.plan=CyclePlan.create(self.root/'cycles.sqlite',self.geometry,self.base,[[x,0] for x in range(4)],sections=1,workers=2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            def produce(n):
                local=CyclePlan(self.plan.path)
                try:return worker(local,self.geometry,1,n,self.root/f'large-worker-{n}')
                finally:local.close()
            futures=[pool.submit(produce,n) for n in range(2)]
            for f in futures:f.result()
        self.assertGreater((self.root/'large-worker-0/chunk_0_0.jsonl').stat().st_size,500000)
        for n in range(2):verify_worker(self.plan,self.geometry,1,n,self.root/f'large-worker-{n}')

    def test_real_preparation_defers_a_future_layer_and_retains_a_resumable_plan(self):
        from pathlib import Path
        from unittest.mock import patch
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin
        from voxel_mapper.draft_park_cycles import prepare
        raster=self.root/'terrain.tif'
        with rasterio.open(raster,'w',driver='GTiff',width=200,height=200,count=1,dtype='float32',
                           crs='EPSG:27700',transform=from_origin(-100,100,1,1)) as dst:dst.write(np.full((200,200),-1,dtype='float32'),1)
        config={'terrain':{'path':str(raster),'units':'m','vertical_datum':'ODN','source_id':'terrain'},'sources':[{'id':'terrain'}]}
        (self.root/'terrain.json').write_text(json.dumps(config))
        layer=self.root/'layer.jsonl';layer.write_text(json.dumps({'x':0,'y':0,'z':0,'material':'stone','feature':'future'})+'\n')
        wicker=self.root/'wicker';wicker.mkdir();(wicker/'quality-report.json').write_text(json.dumps({'crs':'EPSG:27700','bounds_bng_m':[31,-1,34,1]}))
        (wicker/'voxels.jsonl').write_text('');(self.root/'model.json').write_text('{}')
        job={'snapshot_mode':'review_draft','output':'prepared','base_package':str(self.base/'park.mcworld'),
             'base_quality':str(self.base/'quality-report.json'),'terrain_config':'terrain.json','terrain_raster':'terrain.tif',
             'wicker_directory':'wicker','shop_model':'model.json','layers':[{'id':'review','file':'layer.jsonl','defer_above_ground':True}]}
        path=self.root/'job.json';path.write_text(json.dumps(job))
        row={'x':32,'y':1,'z':0,'material':'oak_planks','feature':'proof','kind':'structure'}
        with patch('voxel_mapper.draft_park_cycles.wicker_layer',return_value=({(32,1,0):row},{},{'production_placement_eligible':False})):
            report=prepare(path)
        self.assertEqual(report['deferred_above_ground_cells'],1)
        self.assertEqual(report['plan']['total_chunks'],4)
        prepared=self.root/'prepared'
        plan=CyclePlan(prepared/'cycles.sqlite')
        try:
            plan.validate_inputs(prepared/'geometry.sqlite',prepared/'base-world')
            self.assertEqual(plan.chunks(1),[(1,0),(2,0)])
        finally:plan.close()
        self.assertEqual(self.block(prepared/'base-world/park.mcworld',0,0,0).base_name,'air')
        with self.assertRaisesRegex(ValueError,'fresh preparation'):prepare(path)
