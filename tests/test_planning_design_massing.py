"""Independent source dimensions, closed-volume checks and exported GLB bounds."""
import copy
from collections import Counter
from concurrent.futures import CancelledError
import hashlib
import json
import math
from pathlib import Path
import struct
import tempfile
import unittest

import pymupdf

from voxel_mapper import building_spec, planning_design_dimensions as dimensions
from voxel_mapper import planning_design_massing as massing
from voxel_mapper.building_spec import digest


def signed(page):
    page['id'] = digest({k: v for k, v in page.items() if k != 'id'})
    return page


def source(*, length=35.85, width=2.5, height=2.5, spacing=8.05, state='proposed'):
    claim = {'kind': 'paired_row_design_dimensions', 'row_count': 2,
        'spacing_semantics': 'unspecified_apart', 'length_m': length,
        'width_m': width, 'eaves_height_m': height, 'spacing_m': spacing,
        'printed_state': state, 'ridge_height_m': 3.9}
    claim['id'] = digest(claim)
    return signed({'version': dimensions.VERSION, 'document_sha256': 'a'*64,
        'page': 1, 'analysis_complete': True, 'claims': [claim]})


def volume(mesh):
    total = 0.
    for indices in mesh['triangles']:
        a, b, c = [mesh['vertices'][i] for i in indices]
        cross = (b[1]*c[2]-b[2]*c[1], b[2]*c[0]-b[0]*c[2], b[0]*c[1]-b[1]*c[0])
        total += sum(a[i]*cross[i] for i in range(3))/6
    return abs(total)


def bounds(vertices):
    return ([min(v[k] for v in vertices) for k in range(3)],
        [max(v[k] for v in vertices) for k in range(3)])


def glb(path):
    data = path.read_bytes()
    magic, version, total = struct.unpack_from('<4sII', data)
    if magic != b'glTF' or version != 2 or total != len(data):
        raise AssertionError('Invalid GLB header')
    size, kind = struct.unpack_from('<I4s', data, 12)
    if kind != b'JSON':
        raise AssertionError('Missing GLB JSON')
    document = json.loads(data[20:20+size])
    offset = 20+size
    bin_size, bin_kind = struct.unpack_from('<I4s', data, offset)
    if bin_kind != b'BIN\0' or offset+8+bin_size != len(data):
        raise AssertionError('Invalid GLB binary chunk')
    binary = data[offset+8:]
    vertices = []
    for mesh in document['meshes']:
        accessor = document['accessors'][mesh['primitives'][0]['attributes']['POSITION']]
        view = document['bufferViews'][accessor['bufferView']]
        start = view.get('byteOffset', 0)+accessor.get('byteOffset', 0)
        assert accessor['componentType'] == 5126 and accessor['type'] == 'VEC3'
        vertices.extend(struct.unpack_from('<3f', binary, start+12*i) for i in range(accessor['count']))
    return document, vertices


class DesignMassingTests(unittest.TestCase):
    def test_printed_dimensions_retain_both_spacing_interpretations_without_selection(self):
        page = source()
        before = copy.deepcopy(page)
        result = massing.review_pages([page])
        self.assertTrue(result['analysis_complete'])
        self.assertEqual(result['summary']['conditional_design_massing_alternatives'], 2)
        self.assertEqual(result['summary']['conditional_design_row_groups'], 4)
        by_meaning = {r['spacing_interpretation']: r for r in result['alternatives']}
        self.assertEqual(set(by_meaning), {'clear_gap', 'row_centre_separation'})
        self.assertAlmostEqual(by_meaning['clear_gap']['overall_nominal_extents_m'][1], 13.05)
        self.assertAlmostEqual(by_meaning['row_centre_separation']['overall_nominal_extents_m'][1], 10.55)
        self.assertAlmostEqual(by_meaning['clear_gap']['clear_row_gap_m'], 8.05)
        self.assertAlmostEqual(by_meaning['row_centre_separation']['clear_row_gap_m'], 5.55)
        self.assertEqual(page, before)
        self.assertFalse(result['physical_height_verified'])
        self.assertFalse(result['ground_datum_verified'])
        self.assertFalse(result['world_placement_eligible'])
        self.assertEqual(result['world_geometry_additions'], 0)
        self.assertEqual(result['training_labels_generated'], 0)
        self.assertFalse(result['model_weights_updated'])

    def test_each_row_is_independently_closed_with_correct_volume_and_unplaced_source_pins(self):
        page = source()
        result = massing.review_pages([page])
        for row in result['alternatives']:
            self.assertEqual(row['source_claim_sha256'], digest(page['claims'][0]))
            self.assertEqual(row['source_page_sha256'], digest(page))
            self.assertEqual(row['spec_sha256'], digest(row['spec']))
            model = building_spec.build(row['spec'])
            self.assertEqual(len(model['components']), 2)
            for component in model['components']:
                mesh = component['mesh']
                self.assertTrue(mesh['watertight'])
                directed = Counter((triangle[i], triangle[(i+1) % 3])
                    for triangle in mesh['triangles'] for i in range(3))
                self.assertTrue(all(n == 1 and directed[(b, a)] == 1 for (a, b), n in directed.items()))
                self.assertAlmostEqual(volume(mesh), 35.85*2.5*2.5, places=7)
                self.assertEqual(component['evidence']['class'], 'inferred')
                self.assertFalse(component['evidence']['physical_component_identity_verified'])
                self.assertNotEqual(component['role'], 'roof')
            low, high = bounds([v for c in model['components'] for v in c['mesh']['vertices']])
            self.assertEqual(low, [0., 0., 0.])
            for actual, expected in zip(high, row['overall_nominal_extents_m']):
                self.assertAlmostEqual(actual, expected)
            self.assertFalse(row['individual_cabins_generated'])
            self.assertFalse(row['ridge_geometry_generated'])
            self.assertFalse(model['surveyed_complete_structure'])
            self.assertEqual(model['park_world_blocks_added'], 0)

    def test_glb_binary_geometry_has_expected_y_up_bounds_and_source_evidence(self):
        review = massing.review_pages([source()])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            massing.write_review(root, review)
            for index, row in enumerate(review['alternatives']):
                path = root/('design-massing-'+str(index).zfill(3))/'model.glb'
                document, vertices = glb(path)
                self.assertEqual(len(document['meshes']), 2)
                self.assertFalse(document['extras']['surveyed_complete_structure'])
                self.assertEqual(document['extras']['units'], 'metres')
                low, high = bounds(vertices)
                expected_low = [0., 0., -row['overall_nominal_extents_m'][1]]
                expected_high = [35.85, 2.5, 0.]
                for actual, expected in zip(low+high, expected_low+expected_high):
                    self.assertAlmostEqual(actual, expected, places=4)
                self.assertTrue(all(n['extras']['evidence']['source_claim_id'] == row['source_claim_id'] for n in document['nodes']))
            html = (root/'design-massing.html').read_text()
            self.assertIn('<canvas', html)
            self.assertIn('clear gap', html)
            self.assertIn('row centre separation', html)
            self.assertEqual(json.loads((root/'design-massing.json').read_text()), review)

    def test_identical_pages_deduplicate_and_conflicting_or_stale_pages_rejected(self):
        page = source()
        self.assertEqual(massing.review_pages([page]), massing.review_pages([page, page]))
        changed = copy.deepcopy(page)
        changed['claims'][0]['length_m'] = 34.
        with self.assertRaises(ValueError):
            massing.review_pages([changed])
        signed(changed)
        with self.assertRaises(ValueError):
            massing.review_pages([page, changed])
        changed = copy.deepcopy(page)
        changed['version'] = 'stale'
        signed(changed)
        with self.assertRaises(ValueError):
            massing.review_pages([changed])

    def test_incomplete_source_cannot_generate_massing_and_reports_hold(self):
        page = source()
        page.update(analysis_complete=False, reason='source_text_inventory_incomplete')
        signed(page)
        review = massing.review_pages([page])
        self.assertEqual(review['alternatives'], [])
        self.assertEqual(review['withheld'][0]['reason'], 'complete_dimension_page_required')
        self.assertFalse(review['source_pages']['a'*64+':1']['analysis_complete'])

    def test_overlapping_or_touching_centre_spacing_is_held_without_removing_clear_gap_alternative(self):
        review = massing.review_pages([source(spacing=2.5)])
        self.assertEqual(len(review['alternatives']), 1)
        self.assertEqual(review['alternatives'][0]['spacing_interpretation'], 'clear_gap')
        self.assertEqual(review['withheld'][0]['reason'], 'source_rows_would_overlap_or_touch')

    def test_existing_and_unknown_source_states_remain_explicit_local_hypotheses(self):
        for state in ('existing', 'unknown'):
            with self.subTest(state=state):
                review = massing.review_pages([source(state=state)])
                for row in review['alternatives']:
                    self.assertEqual(building_spec.build(row['spec'])['source_state'], state)
                    self.assertFalse(row['world_placement_eligible'])

    def test_invalid_dimension_and_spacing_claim_shapes_cannot_generate_geometry(self):
        for key, value in (('length_m', True), ('width_m', 0.), ('eaves_height_m', 1000.),
                           ('row_count', 3), ('spacing_semantics', 'clear_gap'), ('printed_state', 'new')):
            with self.subTest(key=key):
                page = source()
                page['claims'][0][key] = value
                signed(page)
                with self.assertRaises(ValueError):
                    massing.review_pages([page])

    def test_valid_text_dimensions_outside_massing_range_are_held_without_failing_other_claims(self):
        for key,value in (('length_m',600.),('spacing_m',.01)):
            page=source()
            page['claims'][0][key]=value
            signed(page)
            result=massing.review_pages([page])
            self.assertTrue(result['analysis_complete'])
            self.assertEqual(result['alternatives'],[])
            self.assertEqual(result['withheld'][0]['reason'],'source_dimensions_outside_supported_massing_range')

    def test_work_count_and_output_limits_clear_partial_alternatives(self):
        for options in ({'max_checks': 1}, {'max_alternatives': 1}):
            with self.subTest(options=options):
                result = massing.review_pages([source()], options=options)
                self.assertFalse(result['analysis_complete'])
                self.assertEqual(result['alternatives'], [])
                self.assertEqual(result['summary']['conditional_design_row_groups'], 0)
        page = source()
        page['claims'][0]['large_source_receipt'] = 'x'*20000
        signed(page)
        result = massing.review_pages([page], options={'max_output_bytes': 16384})
        self.assertFalse(result['analysis_complete'])
        self.assertEqual(result['alternatives'], [])
        for options in ({'max_checks': True}, {'max_alternatives': 65}, {'max_output_bytes': 16383}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                massing.review_pages([source()], options=options)

    def test_cancellation_and_stale_export_review_are_rejected(self):
        with self.assertRaises(CancelledError):
            massing.review_pages([source()], cancelled=lambda: True)
        review = massing.review_pages([source()])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CancelledError):
                massing.write_review(tmp, review, cancelled=lambda: True)
            self.assertFalse(list(Path(tmp).iterdir()))
            review['alternatives'][0]['spec']['components'][0]['geometry']['interval_m'][1] = 7.
            with self.assertRaises(ValueError):
                massing.write_review(tmp, review)

    def test_original_source_pdf_parser_to_two_conditional_exportable_alternatives(self):
        with pymupdf.open() as document:
            page = document.new_page(width=1000, height=400)
            page.insert_text((30, 50), 'The proposed two rows of containers are located 7m apart, '
                '30m long and 3m wide with an eaves height of 4m.', fontsize=8)
            original = document.tobytes()
        sha = hashlib.sha256(original).hexdigest()
        with pymupdf.open(stream=original, filetype='pdf') as document:
            evidence = dimensions.page_evidence(document[0], sha, 1)
            review = massing.review_pages([evidence])
        self.assertEqual(len(review['alternatives']), 2)
        self.assertTrue(all(r['spec']['sources'][0]['sha256'] == sha for r in review['alternatives']))
        spans = {r['spacing_interpretation']: r['overall_nominal_extents_m'] for r in review['alternatives']}
        self.assertEqual(spans, {'clear_gap': [30., 13., 4.], 'row_centre_separation': [30., 10., 4.]})
        self.assertFalse(review['physical_height_verified'])


if __name__ == '__main__':
    unittest.main()
