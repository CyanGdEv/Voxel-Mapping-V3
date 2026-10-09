import unittest
from shapely.geometry import LineString
from voxel_mapper.bedrock import material_block
from voxel_mapper.reconstruction.garden_bridges import bridge_cells
from voxel_mapper.reconstruction.walking_audit import audit_walking_profile, audit_bridge_world


class WalkingAuditTests(unittest.TestCase):
    def audit(self, walk, cells):
        return audit_walking_profile(walk, lambda x, y, z: material_block(cells.get((x, y, z), 'air')))

    def test_full_bottom_slab_top_slab_and_stair_support(self):
        walk = {(0, 0): 10, (1, 0): 10.5, (2, 0): 11, (3, 0): 12}
        cells = {(0, 9, 0): 'stone', (1, 10, 0): 'stone_slab',
                 (2, 10, 0): 'stone_slab_top', (3, 11, 0): 'stone_stairs_east'}
        self.assertEqual(self.audit(walk, cells)['status'], 'passed')

    def test_water_and_missing_support_fail(self):
        for material in ('air', 'water', 'iron_bars', 'stone_slab'):
            result = self.audit({(0, 0): 10}, {(0, 9, 0): material})
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['support_error_count'], 1)

    def test_both_headroom_blocks_and_final_composition_are_checked(self):
        for y in (10, 11):
            cells = {(0, 9, 0): 'stone', (0, y, 0): 'iron_bars'}
            result = self.audit({(0, 0): 10}, cells)
            self.assertEqual(result['headroom_error_count'], 1)
            self.assertEqual(result['status'], 'failed')

    def test_diagonal_only_contact_and_large_rises_fail(self):
        for walk in ({(0, 0): 10, (1, 1): 10}, {(0, 0): 10, (1, 0): 12}):
            cells = {(x, int(h)-1, z): 'stone' for (x, z), h in walk.items()}
            result = self.audit(walk, cells)
            self.assertFalse(result['connected'])
            self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['abrupt_edge_count'], 1)

    def test_invalid_or_over_budget_profiles(self):
        for walk in ({}, {(0, 0): float('nan')}, {(0, 0): 10.2}, {(.5, 0): 10}):
            with self.assertRaises(ValueError):
                self.audit(walk, {})
        with self.assertRaises(ValueError):
            audit_walking_profile({(0, 0): 10, (1, 0): 10}, None, max_columns=1)

    def test_generated_fractional_deck_reports_actual_solid_top(self):
        cells, clear, walk = bridge_cells(LineString([(0, 0), (10, 0)]), 2, 151.5, lambda x,z:150)
        self.assertEqual(walk[5, 0], 152)
        result = self.audit(walk, cells)
        self.assertEqual(result['status'], 'passed', result)

    def test_missing_or_duplicate_retained_profile_cannot_pass(self):
        for feature in ({'id': 'a', 'status': 'emitted'},
                        {'id': 'a', 'status': 'emitted', 'walk_columns': 2,
                         'walk_heights': [[0, 0, 10], [0, 0, 10]]}):
            with self.assertRaises(ValueError):
                audit_bridge_world(None, 0, [feature])
        with self.assertRaises(ValueError):
            audit_bridge_world(None, 0, [{'id': 'a', 'status': 'withheld'}])
