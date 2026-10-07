import unittest

from voxel_mapper.raster_location import inspect_grid_location, inspect_reference_coverage
from pyproj import Transformer
from shapely.geometry import box, mapping
from shapely.ops import transform


BOUNDS = [-.5215806831352107, 51.39839024271489, -.5069331168647894, 51.40815755482665]
LABELS = [{'axis': axis, 'value': value} for axis, values in
          [('E', [503500, 503550]), ('N', [168350, 168400, 168450])] for value in values]


class RasterLocationTests(unittest.TestCase):
    def test_reference_coverage_does_not_certify_alignment(self):
        convert=Transformer.from_crs(27700,4326,always_xy=True).transform
        features=[{'id':str(i),'properties':{'kind':'building','source_id':'osm'},
                   'geometry':mapping(transform(convert,geom))} for i,geom in enumerate([
                       box(503510,168370,503520,168380),box(503540,168370,503560,168380),
                       box(503551,168370,503607,168420)])]
        result=inspect_reference_coverage(LABELS,features,27700)
        self.assertEqual([f['status'] for f in result['features']],
                         ['inside_grid_label_extent','crosses_grid_label_extent','outside_grid_label_extent'])
        self.assertFalse(result['registration_verified'])
        self.assertEqual(result['world_geometry_additions'],0)

    def test_reference_budgets_invalid_and_other_source_are_explicit(self):
        self.assertEqual(inspect_reference_coverage(LABELS,[{}]*5001,27700)['status'],'reference_budget_exceeded')
        bad={'properties':{'kind':'building','source_id':'osm'},'geometry':mapping(box(500000,100000,500001,100001))}
        result=inspect_reference_coverage(LABELS,[bad,{'properties':{'kind':'building','source_id':'planning'}}],27700)
        self.assertEqual(result['checked_building_count'],1)
        self.assertEqual(result['features'][0]['status'],'rejected_reference')

    def test_thorpe_grid_claim_is_plausible_but_not_registered(self):
        result = inspect_grid_location(LABELS, {'national_grid_claim': True}, BOUNDS)
        self.assertEqual(result['status'], 'candidate_grid_intersects_requested_area')
        self.assertAlmostEqual(result['grid_extent_overlap_fraction'], 1)
        self.assertEqual(result['crs_candidate_origin'], 'british_national_grid_hypothesis')
        self.assertFalse(result['registration_verified'])
        self.assertFalse(result['controls_exported'])
        self.assertEqual(result['world_geometry_additions'], 0)

    def test_offsite_grid_and_wrong_country_are_detected(self):
        shifted = [dict(label, value=label['value']+10000) for label in LABELS]
        self.assertEqual(inspect_grid_location(shifted, {'explicit_epsg_candidates': [27700]}, BOUNDS)['status'],
                         'grid_outside_requested_area')
        self.assertEqual(inspect_grid_location(LABELS, {'explicit_epsg_candidates': [32655]}, BOUNDS)['status'],
                         'requested_area_outside_crs_domain')

    def test_no_crs_guess_from_coordinate_magnitudes(self):
        self.assertEqual(inspect_grid_location(LABELS, {}, BOUNDS)['status'], 'missing_crs_claim')
        self.assertEqual(inspect_grid_location(LABELS, {'explicit_epsg_candidates': [27700, 3857]}, BOUNDS)['status'],
                         'ambiguous_crs_claim')
        self.assertEqual(inspect_grid_location(LABELS, {'explicit_epsg_candidates': [4326]}, BOUNDS)['status'],
                         'unsupported_crs_units')

    def test_missing_or_invalid_input_is_withheld(self):
        self.assertEqual(inspect_grid_location(LABELS, {}, None)['status'], 'not_checked')
        self.assertEqual(inspect_grid_location(LABELS[:1], {}, BOUNDS)['status'], 'insufficient_grid_extent')
        self.assertEqual(inspect_grid_location(LABELS, {}, [0, 0, 0, 1])['status'], 'rejected_location_check')
        self.assertEqual(inspect_grid_location([{'axis': 'E', 'value': float('nan')}], {}, BOUNDS)['status'],
                         'rejected_location_check')
