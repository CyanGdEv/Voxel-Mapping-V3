"""Retained source coordinate supervision and explicit exclusion boundaries."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shapely.geometry import shape

from voxel_mapper import retained_study_examples as examples
from voxel_mapper.building_spec import digest
from voxel_mapper.study_dataset import connected_groups

ROOT = Path(__file__).resolve().parents[1]


def resolve(value, pointer):
    if not pointer:
        return value
    for piece in pointer.lstrip('/').split('/'):
        piece = piece.replace('~1', '/').replace('~0', '~')
        value = value[int(piece)] if isinstance(value, list) else value[piece]
    return value


def points(value):
    if len(value) == 2 and all(type(n) in (int, float) for n in value):
        return [value]
    return [point for child in value for point in points(child)]


class RetainedStudyExamplesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = examples.catalogue(ROOT)

    def test_retained_inventory_has_pinned_targets_and_no_generated_3d_labels(self):
        result = self.result
        self.assertEqual(result['version'], 'retained-study-examples-v1')
        self.assertEqual(len(result['records']), 148)
        self.assertEqual(len(result['documents']), 23)
        self.assertEqual(len({r['id'] for r in result['records']}), 148)
        self.assertTrue(all(d.get('url', '').startswith(('http://', 'https://')) for d in result['documents']))
        for relative, pin in result['input_sha256'].items():
            self.assertEqual(hashlib.sha256((ROOT/relative).read_bytes()).hexdigest(), pin)
        for record in result['records']:
            self.assertIn(record['target_geometry']['type'], ('Polygon', 'LineString'))
            self.assertTrue(shape(record['target_geometry']).is_valid)
            self.assertIn(record['source_state'], ('existing', 'proposed', 'unknown'))
            self.assertTrue(record['assumptions'])
            for ref in record['review_refs']:
                path = ROOT/ref['path']
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), ref['sha256'])
                if path.suffix in ('.json', '.geojson'):
                    resolve(json.loads(path.read_text()), ref['pointer'])
        exclusions = ' '.join(row['reason'] for row in result['excluded'])
        for text in ('join cells', 'rear', 'illustrative', 'proxy', 'Single point'):
            self.assertIn(text.lower(), exclusions.lower())
        self.assertFalse(any('wall_mesh' in ref['pointer'] for r in result['records'] for ref in r['review_refs']))

    def test_wicker_target_coordinates_are_original_pixels_without_metric_scaling(self):
        data = json.loads((ROOT/'evidence/wicker-architectural-outline-annotations.json').read_text())
        for row in self.result['records']:
            if row['id'].startswith('wicker-outline-'):
                reference = row['review_refs'][0]
                expected = copy.deepcopy(resolve(data, reference['pointer']))
                expected.append(expected[0])
                self.assertEqual(row['target_geometry']['coordinates'], [expected])
                self.assertEqual(row['source']['coordinate_frame'], 'render_pixels')
                self.assertEqual(row['source']['render_size_pixels'], [1888, 1334])
        shop = next(r for r in self.result['records'] if r['id'] == 'wicker-shop-floor-envelope')
        original = json.loads((ROOT/'evidence/wicker-shop-floor-annotations.json').read_text())['outer_corners_pixels']
        self.assertEqual(shop['target_geometry']['coordinates'][0][:-1], original)
        self.assertEqual(shop['building_id'], 'wickerman-shop')
        self.assertNotIn('normalization', shop.get('target_derivation', {}))

    def test_wicker_vertical_targets_keep_only_reviewed_trace_endpoints(self):
        raw = json.loads((ROOT/'evidence/wicker-shop-vertical-annotations.json').read_text())
        rows = [r for r in self.result['records'] if r['id'].startswith('wicker-vertical-')]
        self.assertEqual(len(rows), 9)
        for row in rows:
            trace = raw['vertical_traces'][row['id'][len('wicker-vertical-'):]]
            self.assertEqual(row['target_geometry']['coordinates'], [trace['top_pixel'], trace['bottom_pixel']])
            self.assertEqual(row['target_role'], 'elevation_height_trace')

    def test_mutiny_opening_labels_use_corrected_original_geometry_not_later_proposals(self):
        raw = json.loads((ROOT/'evidence/mutiny-north-wing-source-label-corrected-seed.json').read_text())
        rows = [r for r in self.result['records'] if r['id'].startswith('mutiny-opening-')]
        self.assertEqual(len(rows), 16)
        by_id = {r['id'][len('mutiny-opening-'):]: r for r in rows}
        self.assertIn('w3.05', by_id)
        self.assertIn('w3.06', by_id)
        self.assertNotIn('w3.13', by_id)
        for opening in raw['openings']:
            row = by_id[opening['id']]
            self.assertEqual(row['target_geometry']['coordinates'][0][:-1], opening['points_pixels'])
            self.assertEqual(row['building_id'], 'mutiny-north-range')
            self.assertEqual(row['source_state'], 'existing')
            self.assertTrue(all('window-cycle' not in ref['path'] for ref in row['review_refs']))

    def test_prospect_inverse_affine_roundtrip_preserves_each_source_profile(self):
        rows = [r for r in self.result['records'] if r['building_id'] == 'prospect-tower']
        self.assertEqual(len(rows), 63)
        seen = set()
        for row in rows:
            ref = row['review_refs'][0]
            local = resolve(json.loads((ROOT/ref['path']).read_text()), ref['pointer'])
            derivation = row['target_derivation']
            scale = derivation['metres_per_page_point']
            cx, cy = derivation['paper_center']
            actual, expected = points(row['target_geometry']['coordinates']), points(local['coordinates'])
            self.assertEqual(len(actual), len(expected))
            for a, b in zip(actual, expected):
                self.assertAlmostEqual((a[0]-cx)*scale, b[0], places=12)
                self.assertAlmostEqual((cy-a[1])*scale, b[1], places=12)
            self.assertEqual(row['source']['coordinate_frame'], 'page_points')
            self.assertEqual(row['evidence_level'], 'source_extracted_profile')
            self.assertEqual(derivation['operation'], 'inverse_nominal_profile_affine')
            seen.add(row['source']['document_sha256'])
        self.assertEqual(len(seen), 3)

    def test_details_retain_native_polygons_and_do_not_turn_rejected_platform_into_building(self):
        raw = json.loads((ROOT/'voxel_mapper/data/alton-path-details.json').read_text())
        by_geometry = {json.dumps(f['native_geometry'], sort_keys=True): f for f in raw['features']}
        rows = [r for r in self.result['records'] if r['id'].startswith('detail-')]
        self.assertEqual(len(rows), 23)
        self.assertEqual(sum(r['kind'] == 'rock' for r in rows), 14)
        self.assertEqual(sum(r['entity_type'] == 'building' for r in rows), 2)
        for row in rows:
            feature = by_geometry[json.dumps(row['target_geometry'], sort_keys=True)]
            self.assertEqual(row['source']['document_sha256'], feature['document_id'])
            self.assertEqual(row['source']['page'], feature['page'])
            self.assertEqual(row['source']['coordinate_frame'], 'page_points')
        self.assertFalse(any(r['id'].endswith('-907') for r in rows))
        self.assertTrue(any('ride platform' in e['reason'] for e in self.result['excluded']))

    def test_repeat_is_deterministic_and_source_files_are_unchanged(self):
        before = {p: (ROOT/p).read_bytes() for p in self.result['input_sha256']}
        self.assertEqual(examples.catalogue(ROOT), self.result)
        self.assertEqual(before, {p: (ROOT/p).read_bytes() for p in before})

    def test_first_127_source_targets_are_unchanged_after_surface_expansion(self):
        self.assertEqual(digest(self.result['records'][:127]),
            'b7d502800a2216be5d5c1fee0e28ea9c76e8c3d4217899644be6de37b6263082')

    def test_new_paths_keep_reviewed_source_geometry_and_group_related_garden_sheets(self):
        paths = [r for r in self.result['records'] if r['kind'] == 'path']
        self.assertEqual(len(paths), 15)
        by_group = connected_groups(self.result['records'])
        groups = {rid: g['group_id'] for g in by_group for rid in g['record_ids']}
        self.assertEqual(len({groups[r['id']] for r in paths}), 2)
        garden = [r for r in paths if r['id'].startswith('reviewed-garden-path-')]
        self.assertEqual(len(garden), 11)
        self.assertEqual(len({r['source']['document_sha256'] for r in garden}), 2)
        self.assertEqual(len({r['building_id'] for r in garden}), 1)
        for row in paths:
            ref = row['review_refs'][0]
            raw = json.loads((ROOT/ref['path']).read_text())
            original = resolve(raw, ref['pointer'])
            if row['id'].startswith('reviewed-cbeebies'):
                expected = copy.deepcopy(original)
                if expected[0] != expected[-1]:
                    expected.append(expected[0])
                self.assertEqual(row['target_geometry']['coordinates'], [expected])
                self.assertEqual(row['source_state'], 'proposed')
            else:
                self.assertEqual(row['target_geometry'], original)
                self.assertEqual(row['target_geometry']['type'], 'LineString')
                self.assertEqual(row['source_state'], 'unknown')
            self.assertEqual(row['entity_type'], 'site_detail')
            self.assertEqual(row['source']['coordinate_frame'], 'page_points')
            self.assertNotIn('width_m', row)
            self.assertNotIn('force_stairs', row)
            self.assertNotIn('height_m', row)
        paving = [r for r in self.result['records'] if r['kind'] == 'paving_surface']
        self.assertEqual(len(paving), 3)
        self.assertTrue(all(r['source_state'] == 'unknown' for r in paving))
        self.assertTrue(any('road' in ' '.join(r['assumptions']) for r in paving))

    def test_only_source_labelled_plazas_are_imported_without_display_materials_or_heights(self):
        path = ROOT/'evidence/wicker-reviewed-plaza-source.geojson'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
            'cfc09c18f2b7f1a35ff84ae4f2676b55824afd89b19e331efd4f20b38bbdf7d7')
        raw = json.loads(path.read_text())
        rows = [r for r in self.result['records'] if r['kind'] == 'plaza']
        self.assertEqual(len(rows), 3)
        self.assertEqual([r['source_state'] for r in rows], ['existing', 'existing', 'proposed'])
        for row, index in zip(rows, (4, 17, 22)):
            original = raw['features'][index]
            self.assertEqual(original['properties']['contained_labels'], ['Plaza'])
            self.assertEqual(row['target_geometry'], original['geometry'])
            self.assertEqual(row['evidence_level'], 'source_extracted_profile')
            self.assertEqual(row['source']['coordinate_frame'], 'page_points')
            self.assertEqual(row['building_id'], 'alton-site-details-SMD-2016-0315')
            for key in ('surface', 'material', 'finished_level_method', 'area_m2_printed_scale'):
                self.assertNotIn(key, row)

    def test_missing_or_oversized_known_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                examples.catalogue(tmp)
        with patch.object(examples, 'MAX_INPUT_BYTES', 1), self.assertRaises(ValueError):
            examples.catalogue(ROOT)


if __name__ == '__main__':
    unittest.main()
