import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import amulet
from shapely.geometry import box, mapping
from voxel_mapper.bedrock import export_world, material_block
from voxel_mapper.generation_cycles import CyclePlan, partition_sections, file_hash
from voxel_mapper.generation_cycle_export import ScopedGeometryStore, worker, preview, run, run_isolated, worker_directory
from voxel_mapper.reconstruction.batch import GeometryStore
from voxel_mapper.reconstruction.engine import Context
from voxel_mapper.reconstruction.model import Feature, Source
from voxel_mapper.reconstruction.sources import evidence


class CycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.base = self.root/'base'; self.base.mkdir()
        data = self.base/'voxels.jsonl'
        data.write_text(''.join(json.dumps({'x':x,'y':0,'z':0,'kind':'structure','material':'stone'})+'\n' for x in [0,16,32,48]))
        quality = {'voxel_size_m':1,'sources':[],'crs':'EPSG:27700','axis':{},'limitations':[]}
        quality['world'] = export_world(data,self.base,quality)
        (self.base/'quality-report.json').write_text(json.dumps(quality))
        self.offset = quality['world']['vertical_offset_blocks']
        self.geometry = self.root/'geometry.sqlite'
        store = GeometryStore(self.geometry, {'manifest':{'crs':'EPSG:27700'},'base_package_sha256':file_hash(self.base/'park.mcworld')})
        source = Source('s','osm','https://example.test','test','EPSG:27700','ODN')
        ctx = Context({'s':source}, lambda *p:1, box(-20,-20,100,100),'ODN')
        crossing = Feature('crossing','paving',mapping(box(15.1,-.9,17.9,-.1)),'s',{'surface':evidence('asphalt','s')})
        later = Feature('later','paving',mapping(box(33.1,-.9,33.9,-.1)),'s',{'surface':evidence('asphalt','s')})
        store.compile([crossing,later],ctx); store.close()
        self.plan = CyclePlan.create(self.root/'cycles.sqlite',self.geometry,self.base,[[x,0] for x in range(4)],sections=1,batch_chunks=1,workers=2)
        self.output = self.root/'output'

    def tearDown(self): self.plan.close(); self.tmp.cleanup()

    def workers(self, cycle):
        for n in range(2): worker(self.plan,self.geometry,cycle,n,worker_directory(self.output,cycle,n))

    def block(self, package, x, y, z):
        import zipfile
        target = self.root/('read-'+package.parent.name)
        with zipfile.ZipFile(package) as archive: archive.extractall(target)
        world = amulet.load_level(str(target))
        try: return world.get_block(x,y+self.offset,z,'minecraft:overworld')
        finally: world.close()

    def test_cumulative_world_has_prior_chunks_and_no_future_details(self):
        self.workers(1); first = preview(self.plan,self.geometry,self.base,1,self.output)
        package = self.output/first['file']
        self.assertEqual(self.block(package,15,1,1),material_block('gray_concrete'))
        self.assertEqual(self.block(package,16,1,1).base_name,'air')
        self.assertEqual(self.block(package,48,0,0),material_block('stone'))
        self.assertEqual(preview(self.plan,self.geometry,self.base,1,self.output),first)
        result = run(self.plan,self.geometry,self.base,self.output,max_cycles=3)
        self.assertEqual(result['progress']['status'],'complete')
        last = result['previews'][-1]
        self.assertEqual(last['cumulative_geometry_chunks'],3)
        self.assertEqual(last['cumulative_scheduled_chunks'],4)
        self.assertEqual(self.block(self.output/last['file'],15,1,1),material_block('gray_concrete'))
        self.assertEqual(self.block(self.output/last['file'],16,1,1),material_block('gray_concrete'))
        self.assertEqual(self.block(self.output/last['file'],33,1,1),material_block('gray_concrete'))
        self.assertEqual(file_hash(package),first['sha256'])
        self.plan.validate_inputs(self.geometry,self.base)

    def test_worker_corruption_and_missing_worker_prevent_publication(self):
        worker(self.plan,self.geometry,1,0,worker_directory(self.output,1,0))
        with self.assertRaises(FileNotFoundError): preview(self.plan,self.geometry,self.base,1,self.output)
        self.workers(1)
        tile = next(worker_directory(self.output,1,0).glob('chunk_*.jsonl'))
        tile.write_text(tile.read_text().replace('gray_concrete','stone'))
        with self.assertRaisesRegex(ValueError,'payload differs'): preview(self.plan,self.geometry,self.base,1,self.output)
        self.assertEqual(self.plan.next_cycle(),1)
        self.assertFalse((self.output/'previews').exists())

    def test_isolated_processes_publish_and_resume_verified_cycles(self):
        first=run_isolated(self.plan,self.geometry,self.base,self.output,max_cycles=2)
        self.assertEqual(first['completed_cycles'],[1,2])
        self.assertEqual(self.plan.next_cycle(),3)
        result=run_isolated(self.plan,self.geometry,self.base,self.output,max_cycles=3)
        self.assertEqual(result['completed_cycles'],[3,4])
        self.assertEqual(result['progress']['status'],'complete')
        last=result['progress']['cycles'][-1]['preview']
        self.assertEqual(self.block(self.output/last['file'],33,1,1),material_block('gray_concrete'))
        self.assertEqual(run_isolated(self.plan,self.geometry,self.base,self.output,max_cycles=2)['completed_cycles'],[])

    def test_saved_chunk_intent_resumes_after_flush_before_journal_completion(self):
        import sqlite3
        self.workers(1)
        with patch('voxel_mapper.reconstruction.batch_export.verify_sections',side_effect=RuntimeError('stopped after native flush')):
            with self.assertRaisesRegex(RuntimeError,'native flush'):
                preview(self.plan,self.geometry,self.base,1,self.output)
        with sqlite3.connect(self.output/'native/export-state.sqlite') as state:
            self.assertEqual(state.execute('SELECT ready FROM chunks').fetchone()[0],0)
        self.assertEqual(self.plan.next_cycle(),1)
        retained=preview(self.plan,self.geometry,self.base,1,self.output)
        self.assertEqual(self.plan.next_cycle(),2)
        self.assertEqual(self.block(self.output/retained['file'],15,1,1),material_block('gray_concrete'))

    def test_export_failure_does_not_advance_and_retries_without_recompilation(self):
        self.workers(1)
        with patch('voxel_mapper.reconstruction.batch_export.export_world',side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError): preview(self.plan,self.geometry,self.base,1,self.output)
        self.assertEqual(self.plan.next_cycle(),1)
        preview(self.plan,self.geometry,self.base,1,self.output)
        self.assertEqual(self.plan.next_cycle(),2)
        recovered = CyclePlan(self.plan.path)
        try: self.assertEqual(recovered.next_cycle(),2)
        finally: recovered.close()

    def test_crossing_feature_provenance_scoped_without_future_voxels(self):
        store = ScopedGeometryStore(self.geometry,[(0,0)])
        try:
            self.assertEqual(store.report()['features'],1)
            self.assertEqual(store.report()['native_chunks'],1)
            self.assertEqual(store.db.execute('SELECT id FROM feature_records').fetchone()[0],'crossing')
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM voxels WHERE cx!=0').fetchone()[0],0)
        finally: store.close()

    def test_changed_plan_and_missing_geometry_coverage_rejected(self):
        with self.assertRaisesRegex(ValueError,'Changed cycle inputs'):
            CyclePlan.create(self.plan.path,self.geometry,self.base,[[x,0] for x in range(4)],sections=2,batch_chunks=1,workers=2)
        with self.assertRaisesRegex(ValueError,'excludes compiled'):
            CyclePlan.create(self.root/'bad.sqlite',self.geometry,self.base,[[0,0]])
        with self.geometry.open('ab') as stream: stream.write(b'changed')
        with self.assertRaisesRegex(ValueError,'snapshot changed'): self.plan.validate_inputs(self.geometry)

    def test_default_scale_has_15_sections_balanced_batches_and_ten_disjoint_workers(self):
        chunks = [[x,z] for x in range(-25,25) for z in range(-25,25)]
        plan = CyclePlan.create(self.root/'large.sqlite',self.geometry,self.base,chunks)
        try:
            report = plan.report(); self.assertEqual(report['total_chunks'],2500)
            self.assertEqual(len({r['section'] for r in report['cycles']}),15)
            self.assertTrue(all(100 <= r['chunks'] <= 200 for r in report['cycles']))
            ownership = [c for n in range(10) for c in plan.chunks(1,n)]
            self.assertEqual(len(ownership),len(set(ownership)))
            self.assertEqual(set(ownership),set(plan.chunks(1)))
            self.assertTrue(set(plan.chunks(1,0)) <= set(plan.context_chunks(1,0)))
        finally: plan.close()

    def test_out_of_order_cycle_rejected(self):
        self.workers(2)
        with self.assertRaisesRegex(ValueError,'out of order'): preview(self.plan,self.geometry,self.base,2,self.output)

    def test_portable_checkpoint_continues_next_cycle(self):
        from scripts.park_cycle_actions import checkpoint
        # Match the portable Actions bundle layout.
        self.plan.close();self.plan.path.rename(self.root/'cycles.sqlite')
        self.base.rename(self.root/'base-world');self.base=self.root/'base-world'
        self.plan=CyclePlan(self.root/'cycles.sqlite')
        self.workers(1);preview(self.plan,self.geometry,self.base,1,self.output)
        checkpoint(self.root,self.root/'checkpoint')
        recovered=CyclePlan(self.root/'checkpoint/cycles.sqlite')
        try:
            result=run(recovered,self.root/'checkpoint/geometry.sqlite',self.root/'checkpoint/base-world',self.root/'checkpoint/output',max_cycles=1)
            self.assertEqual(result['progress']['next_cycle'],3)
            last=result['previews'][0]
            self.assertEqual(last['cumulative_geometry_chunks'],2)
        finally:recovered.close()

    def test_early_empty_cycle_is_explicit_terrain_context(self):
        self.plan.close(); self.geometry=self.root/'later-only.sqlite'
        store=GeometryStore(self.geometry,{'manifest':{'crs':'EPSG:27700'},'base_package_sha256':file_hash(self.base/'park.mcworld')})
        source=Source('s','osm','https://example.test','test','EPSG:27700','ODN')
        ctx=Context({'s':source},lambda *p:1,box(-20,-20,100,100),'ODN')
        store.compile([Feature('later','paving',mapping(box(33.1,-.9,33.9,-.1)),'s',{'surface':evidence('asphalt','s')})],ctx);store.close()
        self.plan=CyclePlan.create(self.root/'later-cycles.sqlite',self.geometry,self.base,[[x,0] for x in range(4)],sections=1,batch_chunks=1,workers=2)
        self.workers(1); result=preview(self.plan,self.geometry,self.base,1,self.output)
        self.assertEqual(result['status'],'base_terrain_preview_only')
        self.assertEqual(result['cumulative_voxel_cells'],0)
        self.assertEqual(result['sha256'],file_hash(self.base/'park.mcworld'))
        self.assertEqual(self.plan.next_cycle(),2)

    def test_unpinned_terrain_configuration_is_rejected(self):
        self.workers(1); config=self.root/'changed-terrain.json';config.write_text('{}')
        with self.assertRaisesRegex(ValueError,'sampling configuration changed'):
            preview(self.plan,self.geometry,self.base,1,self.output,config)
        self.assertEqual(self.plan.next_cycle(),1)


class SpatialTests(unittest.TestCase):
    def test_irregular_negative_chunks_have_single_section_ownership(self):
        chunks = [(x,z) for x in range(-20,5) for z in range(-5,10) if (x+z)%3]
        sections = partition_sections(chunks,15)
        flattened = [c for s in sections for c in s]
        self.assertEqual(set(flattened),set(chunks)); self.assertEqual(len(flattened),len(set(flattened)))
        self.assertLessEqual(max(map(len,sections))-min(map(len,sections)),1)
