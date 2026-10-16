"""Synthetic source/terrain metadata with a reused validated mesh; no accuracy labels."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import amulet
import numpy as np
import pymupdf
import rasterio
from rasterio.transform import from_origin

from voxel_mapper.horizontal_grid import OSTN15Transform
from voxel_mapper.world_pilot import run

ROOT = Path(__file__).resolve().parents[1]


class PilotReviewTests(unittest.TestCase):
    def test_estimated_path_steps_flow_through_the_job_native_audit_and_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, job, _ = self.fixture(root)
            terrain = root / 'terrain.tif'
            with rasterio.open(terrain, 'r+') as raster:
                heights = raster.read(1)
                heights[:, 20:] = 181
                raster.write(heights, 1)
            config_path = root / 'config.json'
            config = json.loads(config_path.read_text())
            config['terrain']['sha256'] = self.pin(terrain)['sha256']
            config['sources'].append({'id': 'osm', 'kind': 'osm', 'url': 'https://example.test/map', 'license': 'CC0'})
            job['config'] = self.write(config_path, config)
            operation = OSTN15Transform(4326, 27700, {'method': 'ostn15-bng-v1',
                'path': str(ROOT / 'docs/evidence/world-pilot/alton-ostn15-grid.tif'),
                'sha256': job['horizontal_operation']['grid']['sha256']})
            job['features'] = self.write(root / 'features.json', {'features': [
                {'type': 'Feature', 'id': 'osm/path',
                 'geometry': {'type': 'LineString', 'coordinates': [operation.inverse(x, 343580) for x in (407534, 407550)]},
                 'properties': {'source_id': 'osm', 'kind': 'path', 'highway': 'footway', 'width_m': 2}}],
                'planning_geometry_records': []})
            job['review_component']['access'] = {'policy': 'estimated_each_opening_approach_v2',
                'audit_scope': 'whole_pilot', 'path_steps': {'policy': 'estimated_half_slab_joins_v1', 'max_slabs': 128}}
            self.write(path, job)
            report = run(path, root / 'scene')
            steps = report['path_steps_review']
            self.assertEqual(steps['status'], 'native_joins_verified')
            self.assertGreater(steps['verified_joins'], 0)
            self.assertEqual(steps['native_after']['mapped_supported_cells'], steps['before']['mapped_supported_cells'])
            self.assertLess(steps['native_after']['walking_surface_components'], steps['before']['walking_surface_components'])
            self.assertIn('path-steps-review.json', report['output_sha256'])
            self.assertEqual(steps, json.loads((root / 'scene/path-steps-review.json').read_text()))
            self.assertEqual(report['readiness']['planning_components_voxelized'], 0)
            with zipfile.ZipFile(root / 'scene/park.mcworld') as archive:
                embedded = json.loads(archive.read('voxel-quality-report.json'))
                self.assertEqual(embedded['path_steps_review'], steps)
            form = json.loads((root / 'scene/playtest-results.json').read_text())
            self.assertEqual(form['world']['sha256'], report['world']['sha256'])
            self.assertTrue(all(check['outcome'] == 'not_run' for check in form['checks']))
            self.assertIn('path-step-joins', [check['id'] for check in form['checks']])

    def test_path_steps_require_an_explicit_bounded_policy_and_whole_area_readback(self):
        valid = {'policy': 'estimated_half_slab_joins_v1', 'max_slabs': 128}
        for scope, steps in [('component_neighbourhood', valid), ('whole_pilot', None),
                             ('whole_pilot', {**valid, 'max_slabs': True}),
                             ('whole_pilot', {**valid, 'max_slabs': 513}),
                             ('whole_pilot', {**valid, 'excavate': True}),
                             ('whole_pilot', {**valid, 'policy': 'assume_all_walkable'})]:
            with self.subTest(scope=scope, steps=steps), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path, job, _ = self.fixture(root)
                job['review_component']['access'] = {'policy': 'estimated_each_opening_approach_v2',
                    'audit_scope': scope, 'path_steps': steps}
                self.write(path, job)
                with self.assertRaises(ValueError):
                    run(path, root / 'scene')
                self.assertFalse((root / 'scene.partial').exists())

    def test_whole_pilot_navigation_writes_pending_world_bound_walkthrough_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, job, _ = self.fixture(root)
            job['review_component']['access'] = {'policy': 'estimated_each_opening_approach_v2', 'audit_scope': 'whole_pilot'}
            self.write(path, job)
            report = run(path, root / 'scene')
            access = report['access_review']
            self.assertEqual(access['native_readback']['audit_scope'], 'whole_pilot')
            self.assertEqual(access['whole_area_navigation']['mapped_supported_cells'], 0)
            self.assertEqual(access['whole_area_navigation']['status'], 'partial_or_unresolved')
            for name in ('navigation-review.json', 'navigation-review.svg'):
                self.assertIn(name, report['output_sha256'])
                self.assertTrue((root / 'scene' / name).is_file())
            form = json.loads((root / 'scene/playtest-results.json').read_text())
            self.assertEqual(form['world']['sha256'], report['world']['sha256'])
            self.assertTrue(all(check['outcome'] == 'not_run' for check in form['checks']))
            self.assertIn('whole-area-obstacles', [check['id'] for check in form['checks']])
            with zipfile.ZipFile(root / 'scene/park.mcworld') as archive:
                embedded = json.loads(archive.read('voxel-quality-report.json'))
                self.assertEqual(embedded['access_review']['whole_area_navigation'], access['whole_area_navigation'])

    def test_invalid_audit_scope_and_unknown_access_fields_are_rejected(self):
        for access in ({'policy': 'estimated_each_opening_approach_v2', 'audit_scope': 'all_park'},
                       {'policy': 'estimated_each_opening_approach_v2', 'ignore_blocked': True}):
            with self.subTest(access=access), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path, job, _ = self.fixture(root)
                job['review_component']['access'] = access
                self.write(path, job)
                with self.assertRaisesRegex(ValueError, 'access policy'):
                    run(path, root / 'scene')
                self.assertFalse((root / 'scene').exists())

    def pin(self, path):
        return {'file': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def write(self, path, value):
        path.write_text(json.dumps(value), encoding='utf-8')
        return self.pin(path)

    def fixture(self, root):
        grid = ROOT / 'docs/evidence/world-pilot/alton-ostn15-grid.tif'
        operation = OSTN15Transform(4326, 27700, {'method': 'ostn15-bng-v1', 'path': str(grid), 'sha256': self.pin(grid)['sha256']})
        points = [operation.inverse(x, z) for x in (407530, 407596) for z in (343550, 343618)]
        bbox = [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)]
        terrain = root / 'terrain.tif'
        with rasterio.open(terrain, 'w', driver='GTiff', width=80, height=80, count=1,
                           dtype='float32', crs='EPSG:27700', transform=from_origin(407523, 343625, 1, 1)) as raster:
            raster.write(np.full((80, 80), 180, dtype='float32'), 1)
        config = {'bbox': bbox, 'voxel_size_m': 1, 'terrain': {'path': str(terrain),
                  'sha256': self.pin(terrain)['sha256'], 'source_id': 'dem', 'units': 'm', 'vertical_datum': 'TEST'},
                  'sources': [{'id': 'dem', 'url': 'https://example.test/dem', 'license': 'CC0'}]}
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((20, 20), 'Synthetic test source, not real reviewed geometry')
            original = root / 'source.pdf'
            original.write_bytes(pdf.tobytes())
        parent = root / 'parent.json'
        parent_pin = self.write(parent, {'floor_sha256': self.pin(original)['sha256']})
        model = json.loads((ROOT / 'evidence/wicker-shop-projection-model.json').read_text())
        model['input_sha256'] = {'parent.json': parent_pin['sha256']}
        model.pop('vertical_input_sha256', None)
        model.pop('projection_input_wall_sha256', None)
        model_path = root / 'model.json'
        model_pin = self.write(model_path, model)
        placement = {'id': 'synthetic-review', 'estimated': True, 'production_placement_eligible': False,
                     'anchor_bng_m': [407563, 343584], 'rotation_bng_degrees': -154.75564001904897,
                     'orientation_alternatives_bng_degrees': [-154.75564001904897, 25.244359980951014],
                     'floor_elevation_m': 184, 'vertical_datum': 'TEST', 'basis': 'Synthetic placement fixture only'}
        placement_path = root / 'placement.json'
        job = {'version': 'world-pilot-review-v1', 'name': 'Synthetic component review',
               'config': self.write(root / 'config.json', config),
               'features': self.write(root / 'features.json', {'features': [], 'planning_geometry_records': []}),
               'planning_review': self.write(root / 'readiness.json', []),
               'horizontal_operation': {'method': 'ostn15-bng-v1', 'grid': self.pin(grid),
                                       'provenance': self.pin(ROOT / 'docs/evidence/world-pilot/alton-ostn15-grid-provenance.json')},
               'review_component': {'policy': 'estimated_review_only', 'model': model_pin,
                                    'placement': self.write(placement_path, placement),
                                    'evidence': [parent_pin], 'original_pdfs': [self.pin(original)]}}
        path = root / 'job.json'
        self.write(path, job)
        return path, job, placement

    def test_review_world_reads_back_component_without_acceptance_and_replays(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, job, _ = self.fixture(root)
            model_before = Path(job['review_component']['model']['file']).read_bytes()
            report = run(path, root / 'first')
            self.assertEqual(report['status'], 'completed_provisional_review')
            self.assertEqual(report['readiness']['planning_components_voxelized'], 0)
            self.assertEqual(report['readiness']['review_components_voxelized'], 1)
            component = report['review_component']
            self.assertFalse(component['world_placement_eligible'])
            self.assertEqual(component['accepted_park_world_blocks_added'], 0)
            self.assertEqual(component['training_labels_generated'], 0)
            self.assertEqual(len(component['retained_orientation_alternatives_bng_degrees']), 2)
            self.assertEqual(component['grounding']['terrain_excavation_cells'], 0)
            self.assertTrue(component['grounding']['continuous_terrain_contact'])
            self.assertTrue(report['access_review']['native_readback']['spawn_supported'])
            self.assertEqual(report['access_review']['approach']['status'], 'not_requested')
            self.assertEqual(report['access_review']['native_readback']['minecraft_visual_inspection'], 'not_performed')
            form = json.loads((root / 'first/playtest-results.json').read_text())
            self.assertEqual(form['world']['sha256'], report['world']['sha256'])
            self.assertEqual(form['training_labels_generated'], 0)
            self.assertFalse(form['accepted_physical_geometry'])
            self.assertTrue(all(check['outcome'] == 'not_run' for check in form['checks']))
            rows = [json.loads(line) for line in (root / 'first/voxels.jsonl').read_text().splitlines()]
            cell = next(row for row in rows if row.get('feature', '').startswith('review/'))
            self.assertFalse(cell['accepted_physical_geometry'])
            level = amulet.load_level(str(root / 'first/bedrock-world'))
            try:
                self.assertNotEqual(level.get_block(cell['x'], cell['y'] + report['world']['vertical_offset_blocks'],
                                                   -cell['z'], 'minecraft:overworld').base_name, 'air')
            finally:
                level.close()
            with zipfile.ZipFile(root / 'first/park.mcworld') as archive:
                embedded = json.loads(archive.read('voxel-quality-report.json'))
                self.assertEqual(embedded['quality_status'], 'provisional_component_review')
                self.assertFalse(embedded['review_component']['world_placement_eligible'])
                self.assertEqual(embedded['access_review'], report['access_review'])
            second = run(path, root / 'second')
            self.assertEqual(report['output_sha256']['voxels.jsonl'], second['output_sha256']['voxels.jsonl'])
            self.assertEqual(model_before, Path(job['review_component']['model']['file']).read_bytes())

    def test_normal_jobs_cannot_enable_review_geometry_or_claim_accepted_placement(self):
        for fault in ('normal_version', 'accepted_flag'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path, job, placement = self.fixture(root)
                if fault == 'normal_version':
                    job['version'] = 'world-pilot-v1'
                else:
                    placement['production_placement_eligible'] = True
                    job['review_component']['placement'] = self.write(root / 'placement.json', placement)
                self.write(path, job)
                with self.assertRaises(ValueError):
                    run(path, root / 'output')
                self.assertFalse((root / 'output.partial').exists())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, job, _ = self.fixture(root)
            job['version'] = 'world-pilot-v1'
            job.pop('review_component')
            job['_prepared_review'] = {'untrusted': 'must never execute as prepared review state'}
            self.write(path, job)
            report = run(path, root / 'output')
            self.assertEqual(report['status'], 'completed_draft')
            self.assertIsNone(report['review_component'])

    def test_missing_or_changed_original_and_parent_evidence_fail_before_output(self):
        for fault in ('source', 'parent', 'missing'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path, _, _ = self.fixture(root)
                if fault == 'missing':
                    (root / 'source.pdf').unlink()
                else:
                    (root / ('source.pdf' if fault == 'source' else 'parent.json')).write_text('changed')
                with self.assertRaises((ValueError, FileNotFoundError)):
                    run(path, root / 'output')
                self.assertFalse((root / 'output.partial').exists())

    def test_terrain_intersection_and_bounds_failure_publish_no_review_world(self):
        for fault in ('floor', 'bounds'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path, job, placement = self.fixture(root)
                if fault == 'floor':
                    placement['floor_elevation_m'] = 179
                else:
                    placement['anchor_bng_m'] = [407540, 343560]
                job['review_component']['placement'] = self.write(root / 'placement.json', placement)
                self.write(path, job)
                with self.assertRaises(ValueError):
                    run(path, root / 'output')
                self.assertFalse((root / 'output').exists())
                self.assertFalse((root / 'output.partial/park.mcworld').exists())

    def test_access_policy_must_be_explicit_and_cannot_claim_verified_geometry(self):
        for settings in ({}, {'policy': 'verified_access'}, {'policy': 'estimated_half_step_approach_v1', 'accepted': True}):
            with self.subTest(settings=settings), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path, job, _ = self.fixture(root)
                job['review_component']['access'] = settings
                self.write(path, job)
                with self.assertRaisesRegex(ValueError, 'access policy'):
                    run(path, root / 'output')
                self.assertFalse((root / 'output.partial').exists())
