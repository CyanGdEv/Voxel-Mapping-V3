import tempfile
import unittest
from pathlib import Path
from voxel_mapper.cli import build

class MapperTests(unittest.TestCase):
    def setUp(self):
        self.config = {"bbox": [0, 0, .001, .001], "sources": [{"id": "survey", "url": "https://example.org/survey", "license": "CC0"}]}
        self.features = {"features": [{"type": "Feature", "id": "building", "properties": {"source_id": "survey", "kind": "building", "height_m": 3, "base_elevation_m": 10}, "geometry": {"type": "Polygon", "coordinates": [[[.0004,.0004],[.0006,.0004],[.0006,.0006],[.0004,.0006],[.0004,.0004]]]}}]}
    def test_metric_height_and_evidence(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            report = build(self.config, self.features, Path(d))
            records = [json.loads(s) for s in (Path(d)/"voxels.jsonl").read_text().splitlines()]
            self.assertEqual({r['y'] for r in records}, {10,11,12})
            self.assertEqual(report['issues'], [])
            self.assertGreater(report['voxel_records'], 1000)
    def test_missing_evidence_reported(self):
        self.features['features'][0]['properties'].pop('height_m')
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(build(self.config, self.features, Path(d))['issues'])
    def test_budget_removes_partial_map(self):
        self.config['max_voxels'] = 1
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                build(self.config, self.features, Path(d))
            self.assertFalse((Path(d)/'voxels.jsonl').exists())
    def test_unknown_source_rejected(self):
        self.config['sources'] = []
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                build(self.config, self.features, Path(d))
