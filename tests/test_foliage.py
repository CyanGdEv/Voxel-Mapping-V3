import tempfile,unittest,json
from pathlib import Path
from shapely.geometry import Point,box,mapping
import amulet
from voxel_mapper.foliage import tree_cells,tree_structure,shrub_cells,stable_seed
from voxel_mapper.bedrock import ALLOWED_MATERIALS,material_block,export_world
from voxel_mapper.reconstruction.model import Feature,Source
from voxel_mapper.reconstruction.engine import Context,ReconstructionEngine
from voxel_mapper.reconstruction.sources import evidence
from voxel_mapper.reconstruction.generators import default_registry


class FoliageTests(unittest.TestCase):
    def test_branch_skeletons_are_grounded_and_face_connected(self):
        for profile in ('broadleaf','airy','conifer','pine','columnar','monkey_puzzle','weeping'):
            cells=tree_cells(0,100,0,19,4,profile,stable_seed(profile));wood={k for k,m in cells.items() if m.endswith('_fence')}
            reached={(0,101,0)};queue=list(reached)
            while queue:
                k=queue.pop()
                for axis in range(3):
                    for sign in (-1,1):
                        n=list(k);n[axis]+=sign;n=tuple(n)
                        if n in wood and n not in reached:reached.add(n);queue.append(n)
            self.assertEqual(reached,wood,profile);self.assertLessEqual(max(k[1] for k in cells),119)
            self.assertTrue(all(x*x+z*z<=16 for (x,y,z),m in cells.items() if m.endswith('_leaves')))
            self.assertFalse(any('_log' in m for m in cells.values()))
            self.assertTrue(set(cells.values())<=ALLOWED_MATERIALS)
    def test_deterministic_variation_and_invalid_bounds(self):
        a=tree_cells(0,0,0,14,4,seed=12);self.assertEqual(a,tree_cells(0,0,0,14,4,seed=12))
        self.assertNotEqual(a,tree_cells(0,0,0,14,4,seed=13))
        with self.assertRaises(ValueError):tree_cells(0,0,0,100,20)
    def test_leaf_scatter_is_branch_attached_mixed_and_open(self):
        cells=tree_cells(0,0,0,22,6,seed=73)
        wood={k for k,m in cells.items() if m.endswith('_fence')}
        leaf={k for k,m in cells.items() if m.endswith('_leaves')}
        self.assertEqual({cells[k] for k in leaf},{'oak_leaves','birch_leaves'})
        self.assertTrue(all(any((x+dx,y,z+dz) in wood for dx,dz in ((1,0),(-1,0),(0,1),(0,-1))) for x,y,z in leaf))
        full=tree_cells(0,0,0,22,6,seed=73,leaf_density=1)
        self.assertLess(len(leaf),sum(m.endswith('_leaves') for m in full.values())*.8)
        bare=tree_cells(0,0,0,22,6,seed=73,leaf_density=0)
        self.assertEqual(set(bare),wood)
        self.assertEqual(wood,{k for k,m in full.items() if m.endswith('_fence')})
        self.assertGreater(len({y for x,y,z in wood if (x,z)!=(0,0)}),7)
        self.assertTrue(any(x>0 for x,y,z in wood) and any(x<0 for x,y,z in wood))
        self.assertTrue(any(z>0 for x,y,z in wood) and any(z<0 for x,y,z in wood))
    def test_branch_count_and_leaf_parameters_are_bounded(self):
        sparse,_=tree_structure(0,0,0,20,6,seed=3,branch_count=3)
        dense,_=tree_structure(0,0,0,20,6,seed=3,branch_count=24)
        self.assertGreater(len(dense),len(sparse))
        for kwargs in ({'branch_count':0},{'branch_count':3.5},{'leaf_density':1.1},{'leaf_density':float('nan')},{'leaf_palette':[]},{'leaf_palette':['stone']}):
            with self.assertRaises(ValueError):tree_cells(0,0,0,20,6,**kwargs)
    def test_modular_tree_requires_dimensions_and_source_status(self):
        sources={'survey':Source('survey','survey','fixture','test','local','ODN','accepted')}
        ctx=Context(sources,lambda x,z:100,box(-30,-30,30,30),'ODN');engine=ReconstructionEngine(default_registry())
        f=Feature('tree','tree',mapping(Point(0,0)),'survey',{})
        self.assertFalse(engine.plan([f],ctx)[0])
        f.parameters={k:evidence(v,'survey','estimated') for k,v in {'height_m':12,'crown_radius_m':3,'profile':'broadleaf','wood':'oak','leaves':'oak'}.items()}
        self.assertFalse(engine.plan([f],ctx)[0]);ctx.allow_estimates=True;self.assertTrue(engine.plan([f],ctx)[0])
        ctx.occupied=lambda x,y,z:material_block('stone') if (x,y,z)==(0,101,0) else material_block('air')
        self.assertFalse(engine.plan([f],ctx)[0])
    def test_native_fence_leaf_and_ground_cover_palette_round_trips(self):
        materials=['oak_fence','spruce_fence','birch_fence','dark_oak_fence','birch_leaves','dark_oak_leaves','azalea_leaves','flowering_azalea_leaves','fern','short_grass','oxeye_daisy']
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);rows=[{'x':i,'y':10,'z':0,'kind':'structure','material':m} for i,m in enumerate(materials)];(p/'voxels.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            q={'voxel_size_m':1,'sources':[],'crs':'test','axis':{},'limitations':[]};meta=export_world(p/'voxels.jsonl',p,q);w=amulet.load_level(str(p/'bedrock-world'))
            try:
                for i,m in enumerate(materials):self.assertEqual(w.get_block(i,10+meta['vertical_offset_blocks'],0,'minecraft:overworld'),material_block(m),m)
            finally:w.close()
    def test_shrub_flowering_is_sparse_and_only_on_top(self):
        cells=shrub_cells(0,0,0,3,3,13,True)
        flowers=[k for k,m in cells.items() if m=='flowering_azalea_leaves'];self.assertTrue(flowers)
        self.assertLess(len(flowers),len(cells)/3)
        self.assertTrue(all((x,y+1,z) not in cells for x,y,z in flowers))

    def test_retained_world_placement_preserves_explicit_rider_clearance(self):
        import shutil,rasterio
        from voxel_mapper.cli import build
        from voxel_mapper.park_foliage import reconstruct
        import test_terrain_osm as fixtures
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);config,unused=fixtures.TerrainTests().fixture(p);config['terrain']['emit_surface']=True
            source=p/'source';q=build(config,{'features':[]},source);q['world']=export_world(source/'voxels.jsonl',source,q)
            (source/'quality-report.json').write_text(json.dumps(q));(source/'resolved-config.json').write_text(json.dumps(config))
            surface=p/'surface.tif';shutil.copy2(config['terrain']['path'],surface)
            with rasterio.open(surface,'r+') as ds:v=ds.read(1);v[:]=37;ds.write(v,1)
            (p/'osm.json').write_text(json.dumps({'elements':[]}));(p/'nodes.json').write_text(json.dumps([{'id':'1','lon':'.0005','lat':'.0005','tags':{'natural':'tree'}}]));(p/'boundary.json').write_text(json.dumps(mapping(box(-40,-40,40,40))))
            # Ground/root is 25; protecting the first trunk block must withhold
            # the entire tree, rather than leave disconnected upper branches.
            (p/'clearance.json').write_text(json.dumps([[0,26,0]]))
            report=reconstruct(source,p/'osm.json',p/'nodes.json',surface,p/'boundary.json',p/'protected',clearance_path=p/'clearance.json')
            self.assertEqual(report['tree_count'],0)
            report=reconstruct(source,p/'osm.json',p/'nodes.json',surface,p/'boundary.json',p/'grown')
            self.assertEqual(report['tree_count'],1)
            self.assertEqual(report['trees'][0]['height_method'],'DSM_minus_DTM_envelope')

    def test_neighbour_preview_cleanup_preserves_generated_skeletons(self):
        import shutil,rasterio
        from voxel_mapper.cli import build
        from voxel_mapper.park_foliage import reconstruct
        import test_terrain_osm as fixtures
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);config,_=fixtures.TerrainTests().fixture(p);config['terrain']['emit_surface']=True
            source=p/'source';q=build(config,{'features':[]},source)
            previews={}
            for x in (0,5):
                for y in range(26,32):previews[x,y,0]='oak_log'
                for xx in range(x-2,x+3):
                    for z in range(-2,3):
                        for y in range(28,35):previews.setdefault((xx,y,z),'oak_leaves')
            with (source/'voxels.jsonl').open('a') as f:
                for (x,y,z),m in previews.items():f.write(json.dumps({'x':x,'y':y,'z':z,'kind':'structure','material':m})+'\n')
            q['world']=export_world(source/'voxels.jsonl',source,q)
            (source/'quality-report.json').write_text(json.dumps(q));(source/'resolved-config.json').write_text(json.dumps(config))
            surface=p/'surface.tif';shutil.copy2(config['terrain']['path'],surface)
            with rasterio.open(surface,'r+') as ds:v=ds.read(1);v[:]=37;ds.write(v,1)
            (p/'osm.json').write_text(json.dumps({'elements':[]}));(p/'nodes.json').write_text('[]');(p/'boundary.json').write_text(json.dumps(mapping(box(-40,-40,40,40))))
            report=reconstruct(source,p/'osm.json',p/'nodes.json',surface,p/'boundary.json',p/'grown')
            self.assertEqual(report['tree_count'],2)
            w=amulet.load_level(str(p/'grown'/'bedrock-world'))
            try:
                for t in report['trees']:
                    cells=tree_cells(t['x'],t['base_odn_m'],t['z'],t['height_m'],t['crown_radius_m'],t['profile'],stable_seed(t['id']),t['wood_palette'],t['leaves_palette'])
                    for (x,y,z),m in cells.items():
                        if m.endswith('_fence'):self.assertEqual(w.get_block(x,y+q['world']['vertical_offset_blocks'],-z,'minecraft:overworld').base_name,'fence')
            finally:w.close()
