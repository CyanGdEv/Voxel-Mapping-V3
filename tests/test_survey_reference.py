import unittest

from voxel_mapper.survey_reference import inspect_reference_notes
from voxel_mapper.drawing_ocr import labels_from_tsv
from tests.test_drawing_ocr import tsv


class SurveyReferenceTests(unittest.TestCase):
    def test_gnss_orientation_does_not_override_arbitrary_coordinates(self):
        result = inspect_reference_notes(
            'This survey has been orientated to the Ordnance Survey (OS) national grid via a Global Navigation\n'
            'Satellite System (GNSS). No scale factor has been applied to the survey therefore\n'
            'the coordinates shown are arbitrary and not true OS coordinates.')
        self.assertTrue(result['national_grid_orientation_claim'])
        self.assertTrue(result['national_grid_claim'])
        self.assertTrue(result['arbitrary_coordinate_warning'])
        self.assertTrue(result['scale_factor_not_applied_claim'])
        self.assertEqual(result['horizontal_coordinate_status'], 'local_grid_requires_transform')

    def test_no_scale_factor_alone_does_not_disclaim_coordinates(self):
        result = inspect_reference_notes('EPSG:27700. No scale factor has been applied.')
        self.assertFalse(result['arbitrary_coordinate_warning'])

    def test_wrapped_survey_notes_do_not_certify_crs_or_datum(self):
        result = inspect_reference_notes(
            'ALL LEVELS ARE IN METRES RELATED TO AN O.S.B.M.\nLOCATED ON A BRICK PIER\n'
            'THE SURVEY GRID IS RELATED TO NATIONAL GRID BY\nRESECTION OF DETAIL\n'
            'NO ADJUSTMENTS FOR SCALE FACTOR HAVE BEEN APPLIED')
        self.assertTrue(result['national_grid_claim'])
        self.assertTrue(result['mapping_resection_claim'])
        self.assertTrue(result['scale_factor_not_applied_claim'])
        self.assertTrue(result['os_benchmark_reference_claim'])
        self.assertEqual(result['height_units_candidate'], 'metres')
        self.assertIsNone(result['height_datum_candidate'])
        self.assertEqual(result['explicit_epsg_candidates'], [])
        self.assertFalse(result['registration_verified'])

    def test_explicit_datum_and_epsg_remain_candidates(self):
        result = inspect_reference_notes('EPSG:27700\nLevels referenced to Ordnance Datum Newlyn')
        self.assertEqual(result['explicit_epsg_candidates'], [27700])
        self.assertEqual(result['height_datum_candidate'], 'ODN')
        self.assertFalse(result['vertical_datum_verified'])

    def test_withheld_line_cannot_complete_grid_claim(self):
        result = labels_from_tsv(tsv([[('Survey grid is related to', 95)],
                                      [('not', 20)], [('National Grid', 95)]]))
        self.assertFalse(result['survey_reference_notes']['national_grid_claim'])

    def test_generic_grid_and_level_words_are_not_references(self):
        result = inspect_reference_notes('National Grid electricity network. Camera level 30.25. ODN')
        self.assertFalse(result['national_grid_claim'])
        self.assertIsNone(result['height_datum_candidate'])

    def test_reference_text_budget(self):
        with self.assertRaisesRegex(ValueError, 'budget'):
            inspect_reference_notes('x' * 8_000_001)
