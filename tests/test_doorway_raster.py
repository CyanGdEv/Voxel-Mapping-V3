"""Opening masks follow finite source jamb spans; native width is an approximation."""
import copy
import json
import math
from pathlib import Path
import unittest

from voxel_mapper.doorway_raster import wall_openings
from voxel_mapper.reconstruction.local_buildings import rotate_model
from voxel_mapper.shop_slabs import assemble

ROOT = Path(__file__).resolve().parents[1]


class DoorwayRasterTests(unittest.TestCase):
    def opening(self, a=(3.11129763121216, 8.008344885241272), b=(3.9258618945763346, 8.393069740242408), height=2.093077599108219):
        return {'id': 'narrow', 'endpoints': [[*a, 0], [*b, 0]], 'height_metres': height}

    def test_oblique_narrow_door_cuts_both_display_wall_columns(self):
        opening = self.opening()
        before = copy.deepcopy(opening)
        mask, report = wall_openings([opening])
        self.assertEqual(mask, {(3, 7): 2, (3, 8): 2})
        self.assertEqual(opening, before)
        evidence = report['openings'][0]
        self.assertEqual(evidence['legacy_columns_xz'], [[3, 8]])
        self.assertEqual(evidence['additional_columns_xz'], [[3, 7]])
        self.assertAlmostEqual(evidence['source_width_m'], .900848573959945)
        self.assertGreater(evidence['native_cell_envelope_width_m'], evidence['source_width_m'])
        self.assertTrue(all(v > 0 for v in evidence['endpoint_envelope_overruns_m']))
        self.assertFalse(evidence['native_geometry_exact'])
        self.assertFalse(report['source_geometry_modified'])

    def test_reversing_jambs_and_rotating_half_turn_preserve_mask_geometry(self):
        original = self.opening()
        reversed_opening = self.opening(tuple(original['endpoints'][1][:2]), tuple(original['endpoints'][0][:2]))
        base, _ = wall_openings([original])
        reverse, _ = wall_openings([reversed_opening])
        self.assertEqual(base, reverse)
        opposite = self.opening(tuple(-v for v in original['endpoints'][0][:2]),
                                tuple(-v for v in original['endpoints'][1][:2]))
        other, _ = wall_openings([opposite])
        self.assertEqual(other, {(-x - 1, -z - 1): height for (x, z), height in base.items()})

    def test_added_columns_stay_within_finite_projected_jamb_span_and_display_band(self):
        for angle in (-170, -90, -45, 0, 20, 45, 80, 170):
            with self.subTest(angle=angle):
                radians = math.radians(angle)
                ux, uz = math.cos(radians), math.sin(radians)
                a = (-2.4, 1.7)
                opening = self.opening(a, (a[0] + 2.3 * ux, a[1] + 2.3 * uz))
                _, report = wall_openings([opening])
                for x, z in report['openings'][0]['additional_columns_xz']:
                    dx, dz = x + .5 - a[0], z + .5 - a[1]
                    along = dx * ux + dz * uz
                    self.assertGreaterEqual(along, -1e-8)
                    self.assertLessEqual(along, 2.3 + 1e-8)
                    self.assertLessEqual(abs(-dx * uz + dz * ux), .5 * (abs(ux) + abs(uz)) + 1e-8)

    def test_sub_player_width_and_unrepresented_grid_spans_are_explicit(self):
        mask, report = wall_openings([self.opening((.3, .2), (.7, .2))])
        self.assertEqual(mask, {(0, 0): 2})
        self.assertEqual(report['openings'][0]['representation_status'], 'source_too_narrow_for_player')
        self.assertEqual(report['openings'][0]['additional_columns_xz'], [])
        mask, report = wall_openings([self.opening((.61, .2), (1.26, .2))])
        self.assertFalse(mask)
        self.assertEqual(report['openings'][0]['representation_status'], 'unrepresented_on_native_grid')

    def test_axis_aligned_aperture_does_not_spread_to_unrelated_columns(self):
        mask, _ = wall_openings([self.opening((.1, .2), (1.9, .2), height=2.9)])
        self.assertEqual(mask, {(0, 0): 2, (1, 0): 2})

    def test_invalid_geometry_and_sampling_budgets_fail(self):
        bad = [self.opening((0, 0), (0, 0)), self.opening((float('nan'), 0), (1, 0)),
               self.opening(height=True), self.opening(height=float('inf')),
               self.opening((-199, -199), (199, 199))]
        for opening in bad:
            with self.subTest(opening=opening), self.assertRaises(ValueError):
                wall_openings([opening])
        with self.assertRaises(ValueError):
            wall_openings([self.opening()] * 129)

    def test_both_wicker_orientations_clear_narrow_passage_without_changing_mesh(self):
        source = json.loads((ROOT / 'evidence/wicker-shop-projection-model.json').read_text())
        for angle, new_column in [(-154.84412559781634, (3, 7)), (25.15587440218366, (-4, -8))]:
            with self.subTest(angle=angle):
                model = rotate_model(source, angle)
                before = copy.deepcopy(model)
                cells, audit = assemble(model)
                self.assertTrue(all((new_column[0], y, new_column[1]) not in cells for y in (0, 1)))
                self.assertFalse(audit['native_shape_leak_audit']['interior_reached_from_exterior'])
                self.assertTrue(audit['door_air_verified'])
                self.assertEqual(model, before)
                doorway = next(r for r in audit['doorway_rasterization']['openings'] if r['id'] == 'door-NW')
                self.assertEqual(doorway['additional_columns_xz'], [list(new_column)])
