import json,tempfile,unittest
from pathlib import Path
from shapely.geometry import box,mapping,LineString
from voxel_mapper.reconstruction.model import Source,Feature
from voxel_mapper.reconstruction.sources import AdapterRegistry,evidence
from voxel_mapper.reconstruction.engine import Context,ReconstructionEngine
from voxel_mapper.reconstruction.generators import default_registry
from voxel_mapper.bedrock import material_block

class ModularTests(unittest.TestCase):
    def setUp(self):
        self.sources={'survey':Source('survey','survey','https://example.test/survey','test-fixture','EPSG:27700','ODN','accepted')}
        self.ctx=Context(self.sources,lambda x,z:100.,box(-10,-10,2000,2000),'ODN')
        self.engine=ReconstructionEngine(default_registry())
    def feature(self,id='ride',family='track',coords=None,params=None):
        return Feature(id,family,mapping(LineString(coords or [(0,0,110),(10,0,115)])),'survey',params or {'material':evidence('oak_planks','survey')})
    def test_300_rides_use_same_generator_and_keep_evidence(self):
        features=[self.feature(str(i),coords=[(i*4,0,110),(i*4,2,115),(i*4,4,110)]) for i in range(300)]
        rows,report=self.engine.plan(features,self.ctx)
        self.assertEqual(len([d for d in report['decisions'] if d['status']=='planned']),300)
        self.assertEqual(report['unique_voxel_cells'],len(rows))
        self.assertTrue(all(row['evidence'][0]['geometry_source']=='survey' for row in rows))
    def test_3d_inversion_and_vertical_segments_remain_connected(self):
        feature=self.feature(coords=[(0,0,110),(0,0,115),(4,0,120),(4,4,115),(0,4,110)])
        rows,_=self.engine.plan([feature],self.ctx);cells={(r['x'],r['y'],r['z']) for r in rows}
        self.assertTrue({(0,110,0),(0,115,0),(4,120,0),(0,110,4)}<=cells)
        reached={(0,110,0)}
        while True:
            nxt=reached|{k for k in cells if any(tuple(k[i]+delta[i] for i in range(3)) in reached for delta in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)))}
            if nxt==reached:break
            reached=nxt
        self.assertEqual(reached,cells)
    def test_missing_elevation_does_not_make_a_flat_ride(self):
        rows,report=self.engine.plan([self.feature(coords=[(0,0),(10,0)])],self.ctx)
        self.assertFalse(rows);self.assertEqual(report['decisions'][0]['status'],'withheld')
    def test_estimated_material_requires_explicit_opt_in(self):
        f=self.feature(params={'material':evidence('oak_planks','survey','estimated')})
        self.assertFalse(self.engine.plan([f],self.ctx)[0])
        self.ctx.allow_estimates=True;self.assertTrue(self.engine.plan([f],self.ctx)[0])
    def test_datum_mismatch_and_unregistered_plans_are_withheld(self):
        self.ctx.vertical_datum='ellipsoid';self.assertFalse(self.engine.plan([self.feature()],self.ctx)[0])
        self.ctx.vertical_datum='ODN';self.sources['survey']=Source('survey','planning','test','fixture','EPSG:27700','ODN')
        self.assertFalse(self.engine.plan([self.feature()],self.ctx)[0])
    def test_feature_rolls_back_on_collision_and_budget(self):
        self.ctx.occupied=lambda x,y,z:material_block('stone' if x==5 else 'air')
        rows,report=self.engine.plan([self.feature()],self.ctx)
        self.assertFalse(rows);self.assertIn('collision',report['decisions'][0]['reason'])
        self.ctx.occupied=None;self.ctx.max_feature_voxels=2
        self.assertFalse(self.engine.plan([self.feature()],self.ctx)[0])
    def test_paving_uses_palette_over_entire_polygon(self):
        f=Feature('plaza','paving',mapping(box(0,0,10,10)),'survey',{'surface':evidence('brick','survey')})
        rows,_=self.engine.plan([f],self.ctx)
        self.assertEqual(len(rows),100);self.assertTrue(all(r['material'] in ('terracotta','mud_bricks','oak_planks','granite') for r in rows))
    def test_trestle_bearing_connects_to_actual_3d_deck(self):
        deck=self.feature(coords=[(0,0,110),(12,0,110)])
        supports=self.feature('supports','trestle',coords=[(0,0,110),(12,0,110)],params={k:evidence(v,'survey') for k,v in {'spacing_m':4,'width_m':3,'post_material':'oak_fence','beam_material':'spruce_planks'}.items()})
        rows,report=self.engine.plan([deck,supports],self.ctx);cells={(r['x'],r['y'],r['z']):r['material'] for r in rows}
        self.assertEqual(len([d for d in report['decisions'] if d['status']=='planned']),2)
        for x in (0,4,8):self.assertEqual(cells[x,109,0],'spruce_planks');self.assertEqual(cells[x,110,0],'oak_planks')
    def test_plugins_and_source_adapters_are_extendable(self):
        self.engine.register('marker',lambda f,g,c:iter([((0,101,0),'stone')]))
        self.assertTrue(self.engine.plan([self.feature(family='marker')],self.ctx)[0])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input.json';path.write_text('{}')
            adapters=AdapterRegistry();adapters.register('custom',lambda data,source:[self.feature()])
            features,report=adapters.load([{'source':'survey','adapter':'custom','file':'input.json'}],self.sources,'EPSG:27700',directory)
            self.assertEqual(len(features),1);self.assertEqual(len(report[0]['sha256']),64)
            with self.assertRaises(ValueError):adapters.load([{'source':'survey','adapter':'custom','file':'input.json','sha256':'wrong'}],self.sources,'EPSG:27700',directory)
    def test_bad_feature_does_not_discard_valid_neighbours(self):
        large=Feature('oversize','paving',mapping(box(0,0,1000,1000)),'survey',{'surface':evidence('brick','survey')})
        rows,report=self.engine.plan([large,self.feature()],self.ctx)
        self.assertTrue(rows);self.assertEqual([d['status'] for d in report['decisions']],['withheld','planned'])
    def test_source_inventory_lists_ride_extent_separately_from_track(self):
        from voxel_mapper.reconstruction.inventory import source_inventory
        raw={'elements':[{'type':'way','id':1,'tags':{'roller_coaster':'track'}},{'type':'way','id':2,'tags':{'attraction':'roller_coaster'}}]}
        inventory=source_inventory(raw,[],{},[])
        self.assertEqual(inventory['candidates_by_family'],{'track':1,'ride_extent':1})
    def test_voxel_sweep_follows_unequal_axis_segment(self):
        from voxel_mapper.reconstruction.geometry import segment_cells
        cells=list(segment_cells((0.2,0.2,0.2),(3.2,8.2,2.2)))
        self.assertEqual(cells[0],(0,0,0));self.assertEqual(cells[-1],(3,8,2))
        # No five-block vertical kink from a dominant-axis Manhattan shortcut.
        self.assertTrue(all(abs(x-3*y/8)<=1.4 and abs(z-2*y/8)<=1.4 for x,y,z in cells))
        self.assertTrue(all(sum(abs(a[i]-b[i]) for i in range(3))==1 for a,b in zip(cells,cells[1:])))
    def test_duplicate_ids_do_not_silently_merge(self):
        with self.assertRaises(ValueError):self.engine.plan([self.feature(),self.feature()],self.ctx)

if __name__=='__main__':unittest.main()
