import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import amulet
import numpy as np
import rasterio
from rasterio.transform import from_origin

from voxel_mapper.world_pilot import run


class WorldPilotTests(unittest.TestCase):
    def test_normal_pilot_cannot_enable_estimated_woodland_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job_path, _, _, job = self.fixture(root)
            job['review_context'] = {'policy': 'mapped-woodland-buffer-v1'}
            self.write_json(job_path, job)
            with self.assertRaisesRegex(ValueError, 'explicit provisional component review'):
                run(job_path, root / 'output')
            self.assertFalse((root / 'output').exists())

    def pin(self, path):
        return {'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def write_json(self, path, value):
        path.write_text(json.dumps(value), encoding='utf-8')
        return self.pin(path)

    def fixture(self, root, nodata=False):
        terrain = root / 'terrain.tif'
        values = np.full((20, 20), -9999 if nodata else 25, dtype='float32')
        with rasterio.open(terrain, 'w', driver='GTiff', width=20, height=20, count=1,
                           dtype='float32', crs='EPSG:4326', transform=from_origin(0, .0002, .00001, .00001),
                           nodata=-9999) as raster:
            raster.write(values, 1)
        config = {'bbox': [.00002, .00002, .00018, .00018], 'voxel_size_m': 1,
                  'sources': [{'id': 'dem', 'url': 'https://example.test/dem', 'license': 'CC0'},
                              {'id': 'osm', 'kind': 'osm', 'url': 'https://www.openstreetmap.org/copyright', 'license': 'ODbL-1.0'},
                              {'id': 'drawing', 'kind': 'planning', 'url': 'https://example.test/plan', 'license': 'CC0'}],
                  'terrain': {'path': 'terrain.tif', 'sha256': self.pin(terrain)['sha256'],
                              'source_id': 'dem', 'units': 'm', 'vertical_datum': 'TEST'}}
        geometry = {'type': 'Polygon', 'coordinates': [[
            [.00006, .00006], [.00014, .00006], [.00014, .00014], [.00006, .00014], [.00006, .00006]]]}
        record = {'id': 'wall', 'source_id': 'drawing', 'document_id': 'test-drawing/revision-C',
                  'verification_reference': 'synthetic-independent-review', 'reuse_allowed': True,
                  'registration_verified': True, 'as_built_verified': True, 'feature_type': 'building_component',
                  'geometry': geometry, 'elevation': {'base_m': 28, 'top_m': 30, 'vertical_datum': 'TEST'}}
        withheld = copy.deepcopy(record)
        withheld.update(id='unregistered', registration_verified=False)
        features = {'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'id': 'osm/path', 'geometry': geometry,
             'properties': {'source_id': 'osm', 'kind': 'path', 'highway': 'footway', 'surface': 'asphalt'}}],
            'planning_geometry_records': [record, withheld]}
        evidence = root / 'evidence.json'
        self.write_json(evidence, {'status': 'unreviewed'})
        reviews = [{'id': 'roof', 'title': 'Roof assembly', 'required_evidence': ['Independent placement controls'],
                    'evidence': [self.pin(evidence)]}]
        job = {'version': 'world-pilot-v1', 'name': 'Synthetic pilot',
               'config': self.write_json(root / 'config.json', config),
               'features': self.write_json(root / 'features.geojson', features),
               'planning_review': self.write_json(root / 'reviews.json', reviews)}
        self.write_json(root / 'job.json', job)
        return root / 'job.json', config, features, job

    def test_real_export_distinguishes_voxelized_withheld_and_pending_and_replays(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job_path, _, _, _ = self.fixture(root)
            first = run(job_path, root / 'first')
            readiness = first['readiness']
            self.assertEqual(first['status'], 'completed_draft')
            self.assertGreater(first['placement_comparison']['native_material_matches'], 0)
            self.assertEqual(first['placement_comparison']['native_material_overrides'], 0)
            self.assertTrue((root / 'first/placement-comparison.svg').is_file())
            self.assertEqual(readiness['planning_components_voxelized'], 1)
            self.assertEqual(readiness['planning_components_withheld'], 1)
            self.assertEqual(readiness['planning_records'][1]['reason'], 'registration_verified is not confirmed')
            self.assertEqual(readiness['pending_review_tasks'][0]['status'], 'awaiting_evidence')
            self.assertIn('not_performed', first['validation']['minecraft_visual_inspection'])
            self.assertEqual(first['playtest']['status'], 'awaiting_minecraft_playtest')
            self.assertEqual(first['playtest']['ready_entrance_routes'], 0)
            form = json.loads((root / 'first/playtest-results.json').read_text())
            self.assertEqual(form['world']['sha256'], first['world']['sha256'])
            self.assertTrue(all(check['outcome'] == 'not_run' for check in form['checks']))
            with zipfile.ZipFile(root / 'first/park.mcworld') as archive:
                embedded = json.loads(archive.read('voxel-quality-report.json'))
                self.assertEqual(embedded['pilot_readiness'], readiness)
            rows = [json.loads(line) for line in (root / 'first/voxels.jsonl').read_text().splitlines()]
            self.assertFalse(any(row.get('feature') == 'planning/unregistered' for row in rows))
            wall = next(row for row in rows if row.get('feature') == 'planning/wall')
            level = amulet.load_level(str(root / 'first/bedrock-world'))
            try:
                offset = first['world']['vertical_offset_blocks']
                self.assertEqual(level.get_block(wall['x'], wall['y'] + offset, -wall['z'], 'minecraft:overworld').base_name, 'stone')
            finally:
                level.close()
            second = run(job_path, root / 'second')
            self.assertEqual(first['readiness'], second['readiness'])
            self.assertEqual(first['output_sha256']['voxels.jsonl'], second['output_sha256']['voxels.jsonl'])
            self.assertEqual(first['inputs'], second['inputs'])
            for filename, expected in first['output_sha256'].items():
                self.assertEqual(self.pin(root / 'first' / filename)['sha256'], expected)
            with self.assertRaisesRegex(ValueError, 'fresh'):
                run(job_path, root / 'first')

    def test_comparison_reports_material_overrides_without_claiming_registration_accuracy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job_path, _, features, job = self.fixture(root)
            overlap = copy.deepcopy(features['features'][0])
            overlap['id'] = 'osm/overlapping-path'
            overlap['properties'].update(surface='concrete')
            features['features'].append(overlap)
            job['features'] = self.write_json(root / 'features.geojson', features)
            self.write_json(job_path, job)
            report = run(job_path, root / 'output')
            self.assertGreater(report['placement_comparison']['native_material_overrides'], 0)
            comparison = json.loads((root / 'output/placement-comparison.json').read_text())
            self.assertEqual(comparison['independent_placement_accuracy'], 'not_verified')
            self.assertEqual(comparison['planning_features_with_emitted_records'], 1)
            self.assertIn('#cc3399', (root / 'output/placement-comparison.svg').read_text())

    def test_pinned_job_grid_is_required_and_cannot_be_declared_only_inside_config(self):
        source = Path(__file__).resolve().parents[1]
        real_job = json.loads((source / 'examples/alton-world-pilot-ostn15-job.json').read_text())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job_path, config, _, job = self.fixture(root)
            config['terrain']['horizontal_operation'] = {'method': 'ostn15-bng-v1'}
            job['config'] = self.write_json(root / 'config.json', config)
            self.write_json(job_path, job)
            with self.assertRaisesRegex(ValueError, 'pinned pilot job'):
                run(job_path, root / 'output')
            config['terrain'].pop('horizontal_operation')
            job['config'] = self.write_json(root / 'config.json', config)
            operation = real_job['horizontal_operation']
            for key in ('grid', 'provenance'):
                operation[key]['file'] = str((source / 'examples' / operation[key]['file']).resolve())
            operation['grid']['sha256'] = '0' * 64
            job['horizontal_operation'] = operation
            self.write_json(job_path, job)
            with self.assertRaisesRegex(ValueError, 'checksum'):
                run(job_path, root / 'output')
            self.assertFalse((root / 'output.partial').exists())

    def test_all_withheld_planning_still_exports_geographic_world(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job_path, _, features, job = self.fixture(root)
            features['planning_geometry_records'] = features['planning_geometry_records'][1:]
            job['features'] = self.write_json(root / 'features.geojson', features)
            self.write_json(job_path, job)
            report = run(job_path, root / 'output')
            self.assertTrue((root / 'output/park.mcworld').is_file())
            self.assertEqual(report['readiness']['planning_components_voxelized'], 0)
            self.assertEqual(report['readiness']['planning_status'], 'awaiting_evidence')

    def test_no_terrain_coverage_has_readiness_but_no_world(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job_path, _, features, job = self.fixture(root, nodata=True)
            features['planning_geometry_records'][0]['feature_type'] = 'plaza'
            features['planning_geometry_records'][0].pop('elevation')
            job['features'] = self.write_json(root / 'features.geojson', features)
            self.write_json(job_path, job)
            report = run(job_path, root / 'output')
            self.assertEqual(report['status'], 'awaiting_exportable_geometry')
            self.assertEqual(report['readiness']['planning_records'][0]['status'], 'no_voxels')
            self.assertFalse((root / 'output/park.mcworld').exists())
            self.assertIsNone(report['world'])
            self.assertNotIn('playtest', report)
            self.assertFalse((root / 'output/playtest-results.json').exists())

    def test_changed_config_terrain_and_review_evidence_fail_before_output(self):
        for filename in ('config.json', 'terrain.tif', 'evidence.json'):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                job_path, _, _, _ = self.fixture(root)
                with (root / filename).open('ab') as stream:
                    stream.write(b' ')
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    run(job_path, root / 'output')
                self.assertFalse((root / 'output').exists())
                self.assertFalse((root / 'output.partial').exists())

    def test_changed_input_during_build_does_not_publish_world(self):
        from voxel_mapper.cli import build as original_build
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job_path, _, _, _ = self.fixture(root)
            def changed(*args):
                result = original_build(*args)
                (root / 'evidence.json').write_text('{}')
                return result
            with patch('voxel_mapper.world_pilot.build', side_effect=changed):
                with self.assertRaisesRegex(ValueError, 'changed during'):
                    run(job_path, root / 'output')
            self.assertFalse((root / 'output').exists())
            self.assertFalse((root / 'output.partial/park.mcworld').exists())
            self.assertTrue((root / 'output.partial/failure.json').exists())

    def test_budget_and_planning_bypass_are_rejected(self):
        for fault in ('area', 'resolution', 'source', 'namespace', 'claim'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                job_path, config, features, job = self.fixture(root)
                if fault == 'area':
                    config['bbox'] = [0, 0, .01, .01]
                elif fault == 'resolution':
                    config['voxel_size_m'] = 2
                elif fault == 'source':
                    features['features'][0]['properties']['source_id'] = 'drawing'
                elif fault == 'namespace':
                    features['features'][0]['id'] = 'planning/wall'
                else:
                    features['features'][0]['properties']['planning_geometry_evidence'] = {'verified': True}
                job['config'] = self.write_json(root / 'config.json', config)
                job['features'] = self.write_json(root / 'features.geojson', features)
                self.write_json(job_path, job)
                with self.assertRaises(ValueError):
                    run(job_path, root / 'output')
                self.assertFalse((root / 'output.partial').exists())


if __name__ == '__main__':
    unittest.main()
