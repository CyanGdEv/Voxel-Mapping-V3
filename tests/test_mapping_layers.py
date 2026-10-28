import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from shapely.geometry import Polygon, mapping

from voxel_mapper import mapping_layers as layers, mapping_layer_sources as sources
from voxel_mapper.generation_cycles import file_hash


def fixture(root):
    image = root/'image.png'
    Image.new('RGB', (128, 128), '#889977').save(image)
    receipt = root/'receipt.json'
    receipt.write_text(json.dumps({'image_sha256': file_hash(image), 'width': 128, 'height': 128,
        'extent_epsg3857': [0, 0, 128, 128], 'attribution': 'Synthetic test'}))
    return {'version': layers.VERSION, 'site': 'Synthetic comparison', 'offline': True, 'providers': [],
        'areas': [{'id': 'test', 'image_file': str(image), 'image_file_sha256': file_hash(image),
                   'receipt_file': str(receipt), 'receipt_file_sha256': file_hash(receipt)}]}


class MappingLayerTests(unittest.TestCase):
    def test_projection_clips_without_filling_polygon_holes(self):
        polygon = Polygon([(-10, -10), (110, -10), (110, 110), (-10, 110)],
                          [[(25, 25), (75, 25), (75, 75), (25, 75)]])
        fc = {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'geometry': mapping(polygon), 'properties': {'source': 'test'}}]}
        result = layers.project_features(fc, 'EPSG:3857', [0, 0, 100, 100], (200, 200))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['parts'][0]['path'].count(' Z'), 2)
        self.assertNotIn('-20', result[0]['parts'][0]['path'])
        self.assertEqual(result[0]['properties']['source'], 'test')

    def test_crs_conflicts_and_invalid_coordinates_are_rejected(self):
        fc = {'type': 'FeatureCollection', 'features': [], 'crs': {'properties': {'name': 'EPSG:27700'}}}
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            layers.project_features(fc, 'EPSG:4326', [0, 0, 100, 100], (100, 100))
        fc = {'type': 'FeatureCollection', 'features': [{'geometry': {'type': 'Point', 'coordinates': [400000, 300000]}, 'properties': {}}]}
        with self.assertRaisesRegex(ValueError, 'out of range'):
            layers.project_features(fc, 'EPSG:4326', [0, 0, 100, 100], (100, 100))

    def test_offline_build_exposes_gaps_and_does_not_create_labels(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fixture(root)
            with patch.object(sources.web, 'fetch', side_effect=AssertionError('Unexpected network')):
                result = layers.build(config, root/'output', root/'cache')
            rows = result['areas'][0]['layers']
            self.assertEqual({r['family'] for r in rows}, set(layers.FAMILIES))
            self.assertTrue(all(r['status']=='local_import_required' for r in rows))
            self.assertEqual(result['network_bytes'], 0)
            self.assertEqual(result['training_labels_added'], 0)
            self.assertEqual(result['world_blocks_generated'], 0)
            self.assertTrue(all(not r['registration_verified'] and not r['training_eligible'] for r in rows))
            self.assertIn('mapping-comparison-notes-v1', (root/'output/index.html').read_text())

    def test_imports_preserve_source_lineage_and_escape_embedded_script_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fixture(root)
            path = root/'building.geojson'
            path.write_text(json.dumps({'type': 'FeatureCollection', 'features': [{'id': 'building',
                'geometry': mapping(Polygon([(20, 20), (40, 20), (40, 40), (20, 40)])),
                'properties': {'upstream': 'OSM', 'name': '</script><script>bad()</script>'}}]}))
            config['imports'] = [{'id': 'building', 'format': 'geojson', 'family': 'overture', 'path': str(path),
                'path_sha256': file_hash(path), 'crs': 'EPSG:3857', 'metadata': {'source_url': 'https://example.org/', 'license': 'ODbL-1.0'}}]
            result = layers.build(config, root/'out', root/'cache')
            row = next(r for r in result['areas'][0]['layers'] if r['family']=='overture')
            self.assertEqual(row['status'], 'ready')
            page = (root/'out/index.html').read_text()
            self.assertNotIn('</script><script>bad()', page)
            payload = json.loads((root/'out/layers.json').read_text())
            imported = next(r for r in payload['areas'][0]['layers'] if r['family']=='overture')
            self.assertEqual(imported['features'][0]['properties']['upstream'], 'OSM')
            self.assertFalse(imported['training_eligible'])

    def test_changed_input_and_reference_receipt_mismatch_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fixture(root)
            config['areas'][0]['image_file_sha256'] = '0'*64
            with self.assertRaisesRegex(ValueError, 'changed'):
                layers.build(config, root/'changed', root/'cache')
            config = fixture(root)
            receipt = root/'receipt.json'
            data = json.loads(receipt.read_text()); data['width'] = 127
            receipt.write_text(json.dumps(data)); config['areas'][0]['receipt_file_sha256'] = file_hash(receipt)
            with self.assertRaisesRegex(ValueError, 'dimensions'):
                layers.build(config, root/'wrong-grid', root/'cache')

    def test_incomplete_or_duplicate_arcgis_pages_are_not_rendered(self):
        class Reader:
            def __init__(self, rows): self.rows = iter(rows)
            def get(self, *args, **kwargs): return next(self.rows)
        base = [{'objectIdField': 'OID'}, {'objectIds': [1, 2]}]
        for page in [{'type': 'FeatureCollection', 'features': []},
                     {'type': 'FeatureCollection', 'features': [{'id': 1}, {'id': 1}]},
                     {'type': 'FeatureCollection', 'features': [{'id': 1}, {'id': 2}], 'exceededTransferLimit': True}]:
            with self.assertRaises(ValueError):
                sources.feature_layer(Reader(copy.deepcopy(base)+[page]), sources.OPENMAP, [-1, 50, 0, 51])

    def test_empty_selection_is_not_verified_empty_ground(self):
        class Reader:
            def get(self, endpoint, params):
                return {'name': 'Test', 'copyrightText': 'Test'} if not endpoint.endswith('/query') else {'objectIds': []}
        fc, metadata = sources.feature_layer(Reader(), sources.OPENMAP, [-1, 50, 0, 51])
        self.assertEqual(fc['features'], [])
        self.assertEqual(metadata['selected_count'], 0)
        self.assertIsNone(metadata['capture_date'])

    def test_small_provider_page_limits_are_respected(self):
        batches = []
        class Reader:
            def get(self, endpoint, params):
                if not endpoint.endswith('/query'):
                    return {'name': 'Photo catalogue', 'maxRecordCount': 2, 'objectIdField': 'OID'}
                if params.get('returnIdsOnly'):
                    return {'objectIds': [1, 2, 3]}
                ids = list(map(int, params['objectIds'].split(','))); batches.append(ids)
                return {'type': 'FeatureCollection', 'features': [{'id': i} for i in ids]}
        fc, _ = sources.feature_layer(Reader(), sources.OPENMAP, [-1, 50, 0, 51])
        self.assertEqual(batches, [[1, 2], [3]])
        self.assertEqual(len(fc['features']), 3)

    def test_job_is_registered_for_desktop_workers(self):
        from voxel_mapper.desktop_app import JOB_KINDS
        from voxel_mapper.desktop_runtime import KINDS, HEAVY
        self.assertIn('mapping_source_layers', KINDS & HEAVY)
        self.assertIn('mapping_source_layers', [kind for _, kind in JOB_KINDS])

    def test_original_mapping_json_replays_offline_and_detects_changed_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            reader = sources.Reader(temp)
            raw = b'{"objectIds":[1,2],"objectIdFieldName":"OID"}'
            with patch.object(reader, '_download', return_value=raw) as fetch:
                self.assertEqual(reader.get(sources.OPENMAP)['objectIds'], [1, 2])
                fetch.assert_called_once()
            offline = sources.Reader(temp, offline=True)
            with patch.object(offline, '_download', side_effect=AssertionError('Network')):
                self.assertEqual(offline.get(sources.OPENMAP)['objectIds'], [1, 2])
            self.assertEqual(offline.budget.spent, 0)
            key = hashlib.sha256(sources.OPENMAP.encode()).hexdigest()
            (Path(temp)/'mapping-layers'/(key+'.bin')).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'changed'):
                offline.get(sources.OPENMAP)

    def test_draft_label_unknowns_remain_transparent_and_require_matching_image(self):
        import numpy as np
        from io import BytesIO
        import base64
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); config = fixture(root); area = config['areas'][0]
            mask = np.full((128, 128), 255, np.uint8); mask[:, :64] = 0
            p = root/'ground.png'; Image.fromarray(mask).save(p)
            area.update(ground_mask_file=str(p), ground_mask_file_sha256=file_hash(p), label_source_image_sha256=area['image_file_sha256'])
            layers.build(config, root/'out', root/'cache')
            data = json.loads((root/'out/layers.json').read_text())
            row = next(r for r in data['areas'][0]['layers'] if r['id']=='ground_mask_file')
            rgba = np.array(Image.open(BytesIO(base64.b64decode(row['image'].split(',')[1]))))
            self.assertTrue((rgba[:, 64:, 3]==0).all())
            self.assertTrue((rgba[:, :64, 3]>0).all())
            area['label_source_image_sha256'] = '0'*64
            with self.assertRaisesRegex(ValueError, 'differs'):
                layers.build(config, root/'bad', root/'cache')

    def test_lidar_nodata_stays_transparent_on_the_exact_reference_grid(self):
        import numpy as np
        from io import BytesIO
        import base64
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); config = fixture(root); area = config['areas'][0]
            fields = np.zeros((128, 128, 4), np.float32); fields[:, 64:, 3] = 1
            p = root/'fields.npz'; np.savez_compressed(p, features=fields)
            receipt = root/'fields.json'; receipt.write_text(json.dumps({'image_sha256': area['image_file_sha256'], 'features_sha256': file_hash(p)}))
            area.update(lidar_features_file=str(p), lidar_features_file_sha256=file_hash(p),
                        lidar_receipt_file=str(receipt), lidar_receipt_file_sha256=file_hash(receipt))
            layers.build(config, root/'out', root/'cache')
            data = json.loads((root/'out/layers.json').read_text())
            row = next(r for r in data['areas'][0]['layers'] if r['id']=='lidar-context-0')
            rgba = np.array(Image.open(BytesIO(base64.b64decode(row['image'].split(',')[1]))))
            self.assertTrue((rgba[:, :64, 3]==0).all())
            self.assertTrue((rgba[:, 64:, 3]>0).all())

    def test_overture_failure_receipt_replays_without_claiming_empty_verified_geometry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); reader = sources.Reader(root/'cache')
            empty = {'type': 'FeatureCollection', 'features': []}
            failure = {'status': 'unavailable', 'failures': ['transport unavailable']}
            with patch('voxel_mapper.overture.acquire_buildings', return_value=(empty, failure)):
                fc, metadata = sources.overture(reader, [-1, 50, 0, 51], root/'live')
            with patch('voxel_mapper.overture.acquire_buildings', side_effect=AssertionError('Network')):
                replay_fc, replay = sources.overture(sources.Reader(root/'cache', offline=True), [-1, 50, 0, 51], root/'offline')
            self.assertEqual(replay_fc, fc)
            self.assertEqual(replay, metadata)
            self.assertEqual(replay['status'], 'unavailable')

    def test_wayback_uses_pinned_tiles_and_does_not_call_release_date_capture_date(self):
        from io import BytesIO
        import numpy as np
        origin = 20037508.342789244
        span = 2*origin/(2**18)
        left = -origin+100000*span
        top = origin-100000*span
        extent = [left+span*.25, top-span*.75, left+span*.75, top-span*.25]
        calls = []
        class Reader:
            def get(self, endpoint, params=None, binary=False):
                calls.append((endpoint, params))
                if endpoint==sources.WAYBACK:
                    return {'123': {'itemURL': 'https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/tile/123/{level}/{row}/{col}',
                                    'itemTitle': 'World Imagery (Wayback 2019-12-12)', 'metadataLayerUrl': 'https://metadata.maptiles.arcgis.com/metadata'}}
                if binary:
                    stream = BytesIO(); Image.new('RGB', (256, 256), '#cc3300').save(stream, format='PNG')
                    return stream.getvalue()
                return {'results': []}
        image, metadata = sources.wayback(Reader(), '123', extent, (128, 128))
        np.testing.assert_array_equal(np.asarray(image)[64, 64], [204, 51, 0])
        self.assertIsNone(metadata['capture_date'])
        self.assertFalse(metadata['point_metadata_applies_to_whole_image'])
        self.assertIn('/123/18/100000/100000', calls[1][0])
        self.assertEqual(calls[-1][1]['mapExtent'], ','.join(map(str, extent)))

    def test_real_desktop_subprocess_opens_offline_layer_job_without_training(self):
        from voxel_mapper.desktop_runtime import DesktopRuntime, _wait
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fixture(root)
            request = root/'request.json'; request.write_text(json.dumps(config))
            runtime = DesktopRuntime(root/'runtime', workers=1, memory_budget_mb=6144)
            try:
                job = _wait(runtime, runtime.submit('mapping_source_layers', request), timeout=30)
                self.assertEqual(job['status'], 'completed', job)
                self.assertTrue((Path(job['output_directory'])/'index.html').is_file())
                self.assertEqual(runtime.store.summary()['feedback_records'], 0)
                self.assertEqual(runtime.store.summary()['checkpoints'], 0)
            finally:
                runtime.close()


if __name__=='__main__':
    unittest.main()
