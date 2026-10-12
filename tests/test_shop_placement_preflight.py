import json
from pathlib import Path
import tempfile
import unittest

from scripts.preflight_wicker_shop_placement import review, terrain_clearance

ROOT = Path(__file__).resolve().parents[1]


class PlacementPreflightTests(unittest.TestCase):
    def test_real_candidates_keep_opposite_orientation_and_unaccepted_floor(self):
        result = review(*(ROOT/'evidence'/n for n in ['wicker-shop-projection-model.json',
                       'wicker-shop-model-lidar-review.json', 'wicker-shop-context-review.json']))
        self.assertEqual(len(result['hypotheses']), 2)
        self.assertAlmostEqual(result['hypotheses'][0]['rotation_degrees'], -154.75564001904897)
        self.assertTrue(result['hypotheses'][0]['context_preferred'])
        self.assertFalse(result['hypotheses'][1]['context_preferred'])
        for row in result['hypotheses']:
            self.assertFalse(row['placement_eligible'])
            self.assertIsNone(row['terrain_clearance'])
            self.assertIn('dark_oak_fence', row['materials'])
            self.assertIn('poor_boundary_agreement', row['boundary_review_flags'])
        self.assertEqual(result['world_geometry_additions'], 0)
        self.assertEqual(result['accepted_checkpoints'], 0)

    def test_missing_and_intersecting_terrain_cannot_pass(self):
        cells = {(0, 0, 0): 'spruce_planks', (0, 1, 0): 'spruce_planks', (1, 0, 0): 'spruce_planks'}
        requests = []
        def ground(x, z):
            requests.append((x, z))
            return 182.7 if x < 11 else None
        result = terrain_clearance(cells, [10.2, 20.8], 182.647, ground)
        self.assertEqual(requests, [(10.5, 21.5), (11.5, 21.5)])
        self.assertEqual(result['sampled_columns'], 2)
        self.assertEqual(result['missing_columns'], 1)
        self.assertFalse(result['terrain_clearance_passed'])
        self.assertEqual(terrain_clearance(cells, [0, 0], 182.5, lambda x,z:182.0)['intersecting_columns'], 2)
        self.assertTrue(terrain_clearance(cells, [0, 0], 182.647, lambda x,z:182.0)['terrain_clearance_passed'])

    def test_changed_evidence_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'model.json'
            path.write_bytes((ROOT/'evidence/wicker-shop-projection-model.json').read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError, 'Pinned model'):
                review(path, ROOT/'evidence/wicker-shop-model-lidar-review.json', ROOT/'evidence/wicker-shop-context-review.json')
