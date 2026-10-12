import unittest
from shapely.geometry import shape
from voxel_mapper.plan_boundaries import recover_boundaries
from voxel_mapper.alton import is_park_application


def stroke(points, level=0):
    return {'type': 's', 'level': level, 'color': (0, 0, 0), 'width': 1,
            'stroke_opacity': 1, 'items': [('l', a, b) for a, b in zip(points, points[1:])]}


class PlanBoundaryTests(unittest.TestCase):
    def test_closed_boundary_recovers_hole_without_becoming_world_geometry(self):
        outer = [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]
        inner = [(20, 20), (40, 20), (40, 40), (20, 40), (20, 20)]
        result = recover_boundaries([stroke(outer), stroke(inner)])
        polygons = [shape(p['geometry']) for p in result['polygons']]
        self.assertTrue(any(len(p.interiors) == 1 for p in polygons))
        self.assertEqual(result['world_geometry_additions'], 0)
        self.assertTrue(all(not p['registration_verified'] for p in result['polygons']))

    def test_clipping_scope_ends_at_same_level(self):
        ring = [(0, 0), (20, 0), (20, 20), (0, 20), (0, 0)]
        result = recover_boundaries([{'type': 'clip', 'level': 0}, stroke(ring, 1), stroke(ring, 0)])
        self.assertEqual(len(result['polygons']), 1)
        self.assertEqual(result['skipped_scoped_or_hidden_paths'], 1)

    def test_open_outline_is_not_closed_by_invented_edge(self):
        result = recover_boundaries([stroke([(0, 0), (20, 0), (20, 20), (0, 20)])])
        self.assertEqual(result['polygons'], [])

    def test_neighbouring_site_and_offsite_staff_housing_are_not_park(self):
        self.assertFalse(is_park_application({'application_context': 'Wildwood, Farley Lane, Farley'}))
        self.assertFalse(is_park_application({'application_context': 'Well Street Mill, Leek, staff housing for Alton Towers'}))
        self.assertTrue(is_park_application({'application_context': 'Alton Towers, Farley Lane, Farley, ST10 4DB'}))
