import copy
from concurrent.futures import CancelledError
import hashlib
import json
import unittest
from unittest.mock import patch

import pymupdf

from voxel_mapper import planning_design_dimensions as dimensions
from voxel_mapper.building_spec import digest


TEXT = ('The two lines of portacabins are located 8.05m apart, 35.85m long and 2.5m wide with an\n'
        'eaves height of 2.5m and linked by a domed ridge approximately 5.70m above ground level.')


def fixture(text=TEXT, *, state=False, rotation=0, hidden=False, discontinuous=False):
    doc = pymupdf.open()
    page = doc.new_page(width=900, height=500)
    if state:
        text = 'The proposed layout will result in a building footprint.\n \n'+text
    if discontinuous:
        first, second = text.split('\n', 1)
        page.insert_text((30, 80), first, fontsize=9)
        page.insert_text((30, 240), second, fontsize=9)
    else:
        page.insert_text((30, 80), text, fontsize=9)
    if hidden:
        page.draw_rect((29, 70, 220, 83), color=None, fill=(1, 1, 1))
    page.set_rotation(rotation)
    return doc


class NarrativeDimensionTests(unittest.TestCase):
    def source(self, text=TEXT, **kwargs):
        doc = fixture(text, **kwargs)
        self.addCleanup(doc.close)
        sha = hashlib.sha256(doc.tobytes()).hexdigest()
        return doc[0], sha

    def test_contiguous_original_lines_preserve_numbers_glyphs_and_ambiguous_spacing(self):
        page, sha = self.source()
        result = dimensions.page_evidence(page, sha, 1)
        self.assertTrue(result['analysis_complete'])
        self.assertEqual(len(result['claims']), 1)
        claim = result['claims'][0]
        self.assertEqual(claim['kind'], 'paired_row_design_dimensions')
        self.assertEqual(claim['row_count'], 2)
        self.assertEqual(claim['spacing_m'], 8.05)
        self.assertEqual(claim['spacing_semantics'], 'unspecified_apart')
        self.assertEqual((claim['length_m'], claim['width_m'], claim['eaves_height_m']), (35.85, 2.5, 2.5))
        self.assertEqual(claim['ridge_height_m'], 5.7)
        self.assertTrue(claim['ridge_approximate'])
        self.assertEqual(claim['printed_state'], 'unknown')
        self.assertEqual(len(claim['source_evidence']['source_lines']), 2)
        self.assertEqual(len(claim['source_evidence']['line_join_evidence']), 1)
        self.assertIn('5.70m', claim['source_evidence']['source_text'])
        records = [r for line in claim['source_evidence']['source_lines'] for r in line['runs']]
        self.assertTrue(all(r['source_characters'] and r['trace_indices'] and r['character_indices'] for r in records))
        self.assertFalse(claim['physical_identity_verified'])
        self.assertFalse(claim['ground_datum_verified'])
        self.assertFalse(result['world_placement_eligible'])
        self.assertEqual(result['world_geometry_additions'], 0)
        self.assertEqual(result['id'], digest({k: v for k, v in result.items() if k != 'id'}))

    def test_visible_preceding_layout_state_is_pinned_separately(self):
        page, sha = self.source(state=True)
        result = dimensions.page_evidence(page, sha, 1)
        claim = result['claims'][0]
        self.assertEqual(claim['printed_state'], 'proposed')
        context = claim['state_context']
        self.assertIn('proposed layout', context['state_phrase'])
        self.assertEqual(context['state_phrase_glyph_status'], 'raster_consistent_candidate')
        self.assertFalse(context['scope_verified'])
        self.assertTrue(context['state_phrase_evidence'])

    def test_inline_proposed_state_without_ridge_does_not_invent_a_roof(self):
        page, sha = self.source('The proposed two rows of containers are located 7m apart, 30m long and 3m wide with an eaves height of 4m.')
        claim = dimensions.page_evidence(page, sha, 1)['claims'][0]
        self.assertEqual(claim['printed_state'], 'proposed')
        self.assertEqual(claim['family'], 'container')
        self.assertIsNone(claim['ridge_height_m'])
        self.assertFalse(claim['ridge_approximate'])

    def test_rotated_original_page_retains_same_dimensions_and_restores_rotation(self):
        page, sha = self.source(rotation=90)
        result = dimensions.page_evidence(page, sha, 1)
        self.assertEqual(result['claims'][0]['spacing_m'], 8.05)
        self.assertEqual(page.rotation, 90)
        self.assertEqual(result, dimensions.page_evidence(page, sha, 1))

    def test_hidden_source_words_withhold_claim_instead_of_trusting_extracted_text(self):
        page, sha = self.source(hidden=True)
        result = dimensions.page_evidence(page, sha, 1)
        self.assertTrue(result['analysis_complete'])
        self.assertEqual(result['claims'], [])
        self.assertTrue(result['withheld'])

    def test_discontinuous_lines_are_not_joined_into_a_dimension_sentence(self):
        page, sha = self.source(discontinuous=True)
        self.assertEqual(dimensions.page_evidence(page, sha, 1)['claims'], [])

    def test_conflicting_original_paragraphs_withhold_all_paired_row_claims(self):
        page, sha = self.source(TEXT+'\n \n'+TEXT.replace('35.85m', '40m'))
        result = dimensions.page_evidence(page, sha, 1)
        self.assertEqual(result['claims'], [])
        self.assertEqual(result['status'], 'conflicting_narrative_dimensions_withheld')
        self.assertEqual(sum(r['reason'] == 'conflicting_paired_row_dimension_paragraphs' for r in result['withheld']), 2)

    def test_height_statements_retain_roles_without_correspondence_assumptions(self):
        page, sha = self.source('The building has a maximum height of 5.4m.\n \nA structure approximately 5.5m high is proposed.')
        result = dimensions.page_evidence(page, sha, 1)
        heights = result['height_claims']
        self.assertEqual({r['height_m'] for r in heights}, {5.4, 5.5})
        self.assertEqual(len(heights), 2)
        self.assertEqual(next(r for r in heights if r['height_m'] == 5.4)['dimension_role'], 'maximum')
        self.assertTrue(next(r for r in heights if r['height_m'] == 5.5)['approximate'])
        self.assertTrue(all(not r['physical_component_correspondence_verified'] for r in heights))

    def test_wrong_count_units_negative_zero_and_out_of_range_values_do_not_supply_claims(self):
        for text in (TEXT.replace('two lines', 'three lines'), TEXT.replace('8.05m', '8.05ft'),
                     TEXT.replace('8.05m', '-8.05m'), TEXT.replace('8.05m', '0m'), TEXT.replace('2.5m wide', '1000m wide')):
            with self.subTest(text=text):
                page, sha = self.source(text)
                self.assertEqual(dimensions.page_evidence(page, sha, 1)['claims'], [])

    def test_work_line_count_and_byte_budgets_clear_successful_partial_results(self):
        page, sha = self.source(TEXT+'\n \n'+TEXT)
        for options in ({'max_checks': 1}, {'max_lines': 1}, {'max_claims': 1}):
            with self.subTest(options=options):
                result = dimensions.page_evidence(page, sha, 1, options=options)
                self.assertFalse(result['analysis_complete'])
                self.assertEqual(result['claims'], [])
                self.assertEqual(result['height_claims'], [])
        with patch.object(dimensions.glyph_visibility, 'screen_architectural_span', return_value={
                'status': 'raster_consistent_candidate', 'large_receipt': 'x'*17000}):
            result = dimensions.page_evidence(page, sha, 1, options={'max_output_bytes': 16384})
            self.assertFalse(result['analysis_complete'])
            self.assertEqual(result['claims'], [])

    def test_limits_source_identity_and_cancellation_are_enforced(self):
        page, sha = self.source()
        for options in ({'max_checks': True}, {'max_output_bytes': 16383}, {'max_claims': 17}, {'unknown': 1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                dimensions.page_evidence(page, sha, 1, options=options)
        with self.assertRaises(ValueError):
            dimensions.page_evidence(page, 'unknown', 1)
        with self.assertRaises(ValueError):
            dimensions.page_evidence(page, sha, 2)
        with self.assertRaises(CancelledError):
            dimensions.page_evidence(page, sha, 1, cancelled=lambda: True)


if __name__ == '__main__':
    unittest.main()
