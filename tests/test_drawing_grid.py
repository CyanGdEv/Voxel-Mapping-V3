import unittest
from pypdf.generic import DecodedStreamObject, NameObject
from tests.test_drawing_controls import fixture
from voxel_mapper.drawing_grid import extract_grid_controls
from voxel_mapper.drawing_controls import inspect_coordinate_labels


def grid_fixture(corrupt=False, extra='', transform=False):
    page=fixture()
    commands=['q 0.5 0 0 0.5 20 20 cm' if transform else 'q',
              'BT /F1 8 Tf 1 0 0 1 10 10 Tm (EPSG: 32630) Tj ET']
    for x in (100,300,500):
        value=500000+x+(10 if corrupt and x==300 else 0)
        commands.extend([f'{x} 50 m {x} 550 l S',
            f'BT /F1 8 Tf 1 0 0 1 {x} 50 Tm (E: {value}) Tj ET'])
    for y in (100,300,500):
        commands.extend([f'50 {y} m 550 {y} l S',
            f'BT /F1 8 Tf 1 0 0 1 50 {y} Tm (N: {5700000+y}) Tj ET'])
    commands.extend([extra,'Q'])
    stream=DecodedStreamObject();stream.set_data('\n'.join(commands).encode())
    page[NameObject('/Contents')]=stream
    return page


class GridTests(unittest.TestCase):
    def test_actual_intersections_and_content_transform(self):
        for transform,first in ((False,(100,100)),(True,(70,70))):
            page=grid_fixture(transform=transform)
            grid=extract_grid_controls(page,reuse_allowed=True)
            self.assertEqual(grid['status'],'grid_intersection_candidates')
            self.assertEqual(len(grid['pairs']),9)
            self.assertEqual(grid['pairs'][0][:2],first)
            result=inspect_coordinate_labels(page,reuse_allowed=True,require_grid=True)
            self.assertEqual(result['status'],'candidate_alignment')
            self.assertLess(result['viewports'][0]['max_withheld_error_m'],.1)
            self.assertEqual(result['registration_method'],'explicit_labelled_grid_intersections')
            self.assertEqual(result['independent_accuracy'],'not_verified')
        self.assertEqual(extract_grid_controls(grid_fixture())['status'],'blocked_reuse')

    def test_ambiguous_unsupported_inconsistent_and_budget_failures(self):
        cases=[grid_fixture(corrupt=True),grid_fixture(extra='100 50 m 200 550 l S'),
               grid_fixture(extra='0 0 m 1 1 2 2 3 3 c S'),fixture()]
        for page in cases:
            self.assertEqual(inspect_coordinate_labels(page,reuse_allowed=True,require_grid=True)['status'],'rejected')
        self.assertEqual(extract_grid_controls(grid_fixture(),reuse_allowed=True,max_text=1)['pairs'],[])
        self.assertEqual(inspect_coordinate_labels(grid_fixture(),reuse_allowed=True,require_grid=True,require_marks=True)['status'],'rejected')
