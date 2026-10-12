import json
import shutil
import unittest
from pathlib import Path
from tests import test_drawing_registration_bridge as drawings
from tests import test_generation_cycles as worlds
from voxel_mapper.automatic_reconstruction import prepare, input_contract
from voxel_mapper.generation_cycles import file_hash


class AutomaticRecipeTests(unittest.TestCase):
    def setUp(self):
        self.drawing = drawings.BridgeTests()
        self.drawing.setUp()
        self.root = self.drawing.root
        self.drawing.batch_inputs()
        (self.root/'terrain.json').write_text('{}')
        self.config = {'automatic_reconstruction': {'enabled': True, 'manifest': 'manifest.json',
                       'references': 'refs.json', 'terrain_config': 'terrain.json'}}
        self.area = {'bounds': [0, 0, 24, 24], 'bounds_crs': 'EPSG:27700'}
        self.work = self.root/'area'
        pdfs = self.work/'corpus/files'; pdfs.mkdir(parents=True)
        shutil.copyfile(self.drawing.pdf, pdfs/(self.drawing.source.sha256+'.pdf'))
        self.available = {self.drawing.source.sha256}

    def tearDown(self):
        self.drawing.tearDown()

    def prepare(self):
        return prepare(self.config, self.area, lambda p: (self.root/p).resolve(), self.work, self.available)

    def test_native_pdf_becomes_recipe_without_object_bindings(self):
        recipe, report = self.prepare()
        self.assertEqual(report['feature_count'], 3)
        self.assertEqual(report['status'], 'recipe_ready')
        self.assertEqual(report['world_geometry_additions'], 0)
        job = json.loads(recipe.read_text())
        self.assertFalse(job['allow_estimates'])
        features = [json.loads(l) for l in Path(job['feature_records']).read_text().splitlines()]
        self.assertEqual({f['family'] for f in features}, {'path', 'wall', 'roof_surface'})
        self.assertEqual(self.prepare(), (recipe, report))
        self.assertIn('not complete', report['inventory_scope'])

    def test_other_area_pdf_and_missing_boundaries_do_not_create_recipe(self):
        self.available = {'9'*64}
        recipe, report = self.prepare()
        self.assertIsNone(recipe)
        self.assertEqual(report['status'], 'awaiting_source_policy')
        self.area = {}
        self.assertEqual(self.prepare()[1]['status'], 'awaiting_area_boundary')

    def test_no_independent_checkpoints_is_unresolved(self):
        (self.root/'refs.json').write_text(json.dumps({'landmarks': self.drawing.refs[:3]}))
        recipe, report = self.prepare()
        self.assertIsNone(recipe)
        self.assertEqual(report['status'], 'awaiting_registered_semantics')
        self.assertEqual(report['bridge']['feature_count'], 0)

    def test_whole_elements_outside_area_are_excluded(self):
        self.area['bounds'] = [0, 0, 1, 1]
        recipe, report = self.prepare()
        self.assertIsNone(recipe)
        self.assertEqual(len(report['outside_area_feature_ids']), 3)

    def test_modified_features_and_changed_policy_are_detected(self):
        recipe, _ = self.prepare()
        job = json.loads(recipe.read_text())
        Path(job['feature_records']).write_text('')
        with self.assertRaisesRegex(ValueError, 'feature output changed'):
            self.prepare()
        before = input_contract(self.config, lambda p: self.root/p)
        (self.root/'terrain.json').write_text('{"changed":true}')
        self.assertNotEqual(before, input_contract(self.config, lambda p: self.root/p))

    def test_proposed_sheet_is_not_automatically_reconstructed(self):
        path = self.root/'manifest.json'
        manifest = json.loads(path.read_text())
        manifest['sources'][0]['metadata']['drawing_state'] = 'proposed'
        path.write_text(json.dumps(manifest))
        recipe, report = self.prepare()
        self.assertIsNone(recipe)
        self.assertEqual(report['bridge']['feature_count'], 0)

    def test_invalid_area_bounds_are_rejected(self):
        self.area['bounds'] = [0, 0, float('nan'), 24]
        with self.assertRaisesRegex(ValueError, 'area bounds'):
            self.prepare()

    def test_controller_compiles_and_exports_real_world_without_area_recipe(self):
        from voxel_mapper.area_cycles import run_local
        from voxel_mapper.bedrock import material_block
        import amulet
        world_fixture = worlds.CycleTests()
        world_fixture.setUp()
        try:
            from voxel_mapper.bedrock import export_world
            base = self.root/'base'; base.mkdir()
            cells = base/'voxels.jsonl'
            cells.write_text(''.join(json.dumps({'x': x, 'y': -1, 'z': z, 'kind': 'terrain', 'material': 'grass_block'})+'\n' for x in range(24) for z in range(24)))
            quality = {'voxel_size_m': 1, 'sources': [], 'crs': 'EPSG:27700', 'axis': {}, 'limitations': []}
            quality['world'] = export_world(cells, base, quality)
            (base/'quality-report.json').write_text(json.dumps(quality))
            offset = quality['world']['vertical_offset_blocks']
            # Same flat, metre-scale terrain source as the existing native cycle fixtures.
            import numpy as np
            import rasterio
            from rasterio.transform import from_origin
            with rasterio.open(self.root/'dtm.tif', 'w', driver='GTiff', height=64, width=64,
                               count=1, dtype='float32', crs='EPSG:27700', transform=from_origin(-16,48,1,1)) as raster:
                raster.write(np.zeros((64,64), dtype='float32'), 1)
            (self.root/'terrain.json').write_text(json.dumps({'terrain': {'path': str(self.root/'dtm.tif'), 'units': 'm', 'vertical_datum': 'ODN', 'source_id': 'terrain'}, 'sources': [{'id': 'terrain'}]}))
            manifest_path = self.root/'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['terrain_sha256'] = file_hash(self.root/'dtm.tif')
            manifest_path.write_text(json.dumps(manifest))
            (self.root/'catalogue.json').write_text(json.dumps({'entries': [{'applicationReference': 'A',
                'url': 'https://example.test/drawing', 'sha256': self.drawing.source.sha256, 'title': 'Fixture'}]}))
            job = {**self.config, 'work_directory': 'resort', 'catalogue': 'catalogue.json',
                   'official_hosts': ['example.test'], 'offline': True,
                   'source_directories': ['area/corpus/files'], 'initial_base_world': 'base',
                   'initial_base_sha256': file_hash(self.root/'base/park.mcworld'),
                   'areas': [{**self.area, 'id': 'a', 'name': 'A', 'application_references': ['A'],
                              'required_families': ['paving', 'wall', 'roof_surface']} ]}
            (self.root/'job.json').write_text(json.dumps(job))
            result = run_local(self.root/'job.json', max_cycles=2)
            self.assertEqual(result['published_cycles'], 1, result)
            self.assertEqual(result['areas']['a']['status'], 'partial_area_preview')
            output = self.root/'resort/a/completed-base/bedrock-world'
            world = amulet.load_level(str(output))
            try:
                self.assertEqual(world.get_block(7,offset,-7,'minecraft:overworld'), material_block('gray_concrete'))
            finally: world.close()
        finally:
            world_fixture.tearDown()
