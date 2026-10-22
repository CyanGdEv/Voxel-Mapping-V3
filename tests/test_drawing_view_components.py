import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import box, mapping, shape

from tests import test_drawing_view_candidates as fixtures
from voxel_mapper.drawing_geometry import extract_page
from voxel_mapper.drawing_view_candidates import run as views_run
from voxel_mapper.drawing_view_components import inspect_view, orient, run, options, affine


class ComponentInventoryTests(unittest.TestCase):
    def source(self):
        with pymupdf.open() as document:
            page = document.new_page(width=400, height=300)
            page.draw_rect((50, 30, 180, 170))
            page.draw_rect((70, 55, 120, 115))
            page.draw_line((230, 40), (280, 40))
            page.draw_line((280, 40), (280, 100))
            page.draw_line((280, 100), (230, 100))  # Missing side stays open.
            parents, _ = extract_page(page, 'a'*64, 1, min_line_length_points=.25)
        gray = np.full((300, 400), 255, dtype=np.uint8)
        for x0, y0, x1, y1 in [(50, 30, 180, 170), (70, 55, 120, 115)]:
            gray[y0:y1, x0:x0+3] = 50; gray[y0:y1, x1:x1+3] = 50
            gray[y0:y0+3, x0:x1+3] = 50; gray[y1-3:y1, x0:x1+3] = 50
        view = {'id': 'view', 'document_sha256': 'a'*64, 'page': 1,
            'geometry': mapping(box(0, 0, 400, 300)), 'caption_text': 'South Elevation',
            'caption_evidence': {'reading_direction_pdf_native': [1, 0]},
            'printed_claim': {'view_kind': 'elevation', 'printed_state': 'unspecified'},
            'nominal_metres_per_pdf_point': .03, 'native_to_nominal_local_affine': [.03, 0, 0, .03, 0, 0]}
        return view, parents, gray, [1, 0, 0, -1, 0, 300]

    def test_native_cycles_raster_alternatives_and_open_gaps_remain_distinct(self):
        view, parents, gray, matrix = self.source(); before = copy.deepcopy(parents); pixels = gray.copy()
        result = inspect_view(view, parents, gray, matrix)
        self.assertEqual(result['counts']['closed_source_regions'], 2)
        self.assertGreaterEqual(result['counts']['native_rectangle_cycles'], 2)
        self.assertGreater(result['counts']['raster_opening_families'], 0)
        self.assertEqual(parents, before); self.assertTrue(np.array_equal(gray, pixels))
        self.assertFalse(result['physical_boundary_verified']); self.assertEqual(result['accepted_physical_components'], 0)
        self.assertEqual(result['printed_claim']['printed_state'], 'unspecified')
        for hypothesis in result['raster_opening_hypotheses']:
            self.assertIsNone(hypothesis['opening_type']); self.assertFalse(hypothesis['physical_opening_verified'])
        for frame in result['native_rectangle_review']['frames']:
            self.assertTrue(all(s['source_intervals'] for s in frame['source_side_support']))
            self.assertTrue(all(p['component_id'] in {r['id'] for r in result['source_components']}
                for side in frame['source_side_support'] for p in side['source_intervals']))

    def test_protected_holes_are_not_filled_or_replaced_by_bounds(self):
        view, parents, gray, matrix = self.source()
        polygon = copy.deepcopy(parents[0]); polygon['geometry'] = mapping(box(40, 120, 200, 280).difference(box(70, 150, 120, 220)))
        result = inspect_view(view, [polygon], gray, matrix)
        self.assertEqual(result['closed_source_regions'][0]['source_hole_count'], 1)
        native = shape(result['closed_source_regions'][0]['geometry_pdf_native'])
        self.assertTrue(native.equals_exact(shape(polygon['geometry']), 0))
        self.assertEqual(len(shape(result['closed_source_regions'][0]['geometry_nominal_local']).interiors), 1)

    def test_missing_scale_keeps_pixels_without_nominal_dimensions(self):
        view, parents, gray, matrix = self.source(); view.update(nominal_metres_per_pdf_point=None, native_to_nominal_local_affine=None)
        result = inspect_view(view, parents, gray, matrix)
        self.assertEqual(result['native_rectangle_review']['status'], 'nominal_view_scale_required')
        self.assertGreater(len(result['raster_opening_hypotheses']), 0)
        self.assertTrue(all(h['geometry_nominal_local'] is None for h in result['raster_opening_hypotheses']))

    def test_rotated_reading_frames_preserve_exact_pixel_edge_coordinates(self):
        gray = np.arange(12, dtype=np.uint8).reshape(3, 4)
        matrix = [2, 0, 0, -2, 10, 20]
        for direction, turns in [([1, 0], 0), ([0, -1], 1), ([-1, 0], 2), ([0, 1], 3)]:
            with self.subTest(direction=direction):
                rotated, new, k = orient(gray, matrix, direction)
                self.assertEqual(k, turns); self.assertTrue(np.array_equal(rotated, np.rot90(gray, turns)))
                # Each pixel centre identifies exactly the same source pixel after rotation.
                for y, x in np.ndindex(rotated.shape):
                    old = pymupdf.Point(x+.5, y+.5)*new*(~pymupdf.Matrix(matrix))
                    self.assertEqual(rotated[y, x], gray[int(old.y), int(old.x)])
        with self.assertRaises(ValueError): orient(gray, matrix, [1, 1])

    def test_raster_budget_withholds_whole_scan_and_native_frames(self):
        view, parents, gray, matrix = self.source()
        result = inspect_view(view, parents, gray, matrix, settings={'max_checks': 1})
        self.assertEqual(result['raster_opening_scan']['status'], 'scan_budget_withheld')
        self.assertEqual(result['raster_opening_hypotheses'], [])
        self.assertEqual(result['native_rectangle_review']['frames'], [])
        withheld = inspect_view(view, parents, None, matrix)
        self.assertEqual(withheld['raster_opening_scan']['status'], 'source_raster_budget_withheld')

    def test_raster_only_views_do_not_require_native_building_edges(self):
        view, _, gray, matrix = self.source()
        result = inspect_view(view, [], gray, matrix)
        self.assertEqual(result['source_components'], [])
        self.assertEqual(result['closed_source_regions'], [])
        self.assertGreater(result['counts']['raster_opening_families'], 0)

    def test_raster_scope_crossings_stay_whole_and_withheld(self):
        view, _, gray, matrix = self.source(); view['geometry'] = mapping(box(60, 0, 400, 300))
        result = inspect_view(view, [], gray, matrix)
        crossing = [r for r in result['raster_opening_hypotheses'] if r['status'] == 'candidate_scope_crossing_withheld']
        self.assertTrue(crossing)
        self.assertTrue(all(shape(r['geometry_pdf_native']).bounds[0] < 60 for r in crossing))
        self.assertEqual(result['counts']['raster_scope_crossings'], len(crossing))

    def test_wrong_source_or_crossing_parent_rejects_without_clipping(self):
        view, parents, gray, matrix = self.source()
        for altered in [{**view, 'page': 2}, {**view, 'geometry': mapping(box(80, 80, 200, 200))}]:
            with self.assertRaisesRegex(ValueError, 'Whole parents'): inspect_view(altered, parents, gray, matrix)
        for settings in [{'max_views': True}, {'max_frames': 513}, {'max_checks': 0}, {'other': 1}]:
            with self.assertRaises(ValueError): options(settings)

    def test_plan_wall_bands_do_not_bridge_missing_opposite_fragments(self):
        with pymupdf.open() as document:
            page = document.new_page(width=400, height=300)
            for a, b in [((20, 40), (200, 40)), ((20, 46), (90, 46)), ((130, 46), (200, 46))]: page.draw_line(a, b)
            parents, _ = extract_page(page, 'a'*64, 1, min_line_length_points=.25)
        view, _, _, matrix = self.source(); view['printed_claim'] = {'view_kind': 'plan', 'plan_level_or_form': 'groundfloor'}
        result = inspect_view(view, parents, None, matrix)
        self.assertEqual(result['counts']['wall_bands'], 2)
        gap = box(90, 254, 130, 260)
        self.assertTrue(all(shape(b['geometry']).intersection(gap).area == 0 for b in result['wall_band_candidates']))
        self.assertEqual(result['raster_opening_scan']['status'], 'not_an_elevation')

    def test_pack_reuses_and_rejects_changed_inputs_and_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); corpus, sha = fixtures.DrawingViewTests().prepare(root)
            try:
                pack = views_run(corpus, root/'geometry', root/'views', settings={'render_width': 400})
                first = run(corpus, root/'geometry', pack['directory'], root/'components')
                self.assertEqual(first['views'], 4); self.assertEqual(first['world_geometry_additions'], 0)
                self.assertIn('facade-alignment.json', first['output_sha256'])
                self.assertIn('sheet-scale-evidence.json', first['output_sha256'])
                self.assertIn('wall-return-corners.json', first['output_sha256'])
                self.assertIn('voxel_mapper.automatic_facade_alignment', first['contract']['kernel_sha256'])
                replay = run(corpus, root/'geometry', pack['directory'], root/'components')
                self.assertEqual(replay['run_views'], 0); self.assertEqual(first['output_sha256'], replay['output_sha256'])
                path = Path(first['directory'])/first['results'][0]['file']; data = path.read_bytes(); path.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'Component output changed'): run(corpus, root/'geometry', pack['directory'], root/'components')
                path.write_bytes(data)
                png = next(Path(pack['directory']).glob('views/*/view.png')); pixels = png.read_bytes(); png.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'Source view artifact changed'): run(corpus, root/'geometry', pack['directory'], root/'components')
                png.write_bytes(pixels); source = corpus.root/'files'/(sha+'.pdf'); source.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'Original component source changed'): run(corpus, root/'geometry', pack['directory'], root/'components')
            finally: corpus.close()

    def test_partial_view_limit_and_output_budget_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); corpus, _ = fixtures.DrawingViewTests().prepare(root)
            try:
                pack = views_run(corpus, root/'geometry', root/'views', settings={'render_width': 400})
                result = run(corpus, root/'geometry', pack['directory'], root/'components', settings={'max_views': 1})
                self.assertEqual(result['status'], 'partial_component_inventory'); self.assertEqual(result['deferred_views'], 3)
                self.assertFalse(result['all_requested_passes_completed'])
                with patch('voxel_mapper.drawing_view_components.MAX_OUTPUT_BYTES', 100):
                    with self.assertRaisesRegex(ValueError, 'output budget'): run(corpus, root/'geometry', pack['directory'], root/'small')
                self.assertEqual(list((root/'small').glob('*/component-report.json')), [])
            finally: corpus.close()

    def test_changed_feed_cannot_reuse_component_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); corpus, _ = fixtures.DrawingViewTests().prepare(root)
            try:
                pack = views_run(corpus, root/'geometry', root/'views', settings={'render_width': 400})
                result = run(corpus, root/'geometry', pack['directory'], root/'components', settings={'max_checks': 1})
                self.assertFalse(result['all_requested_passes_completed']); self.assertTrue(result['withheld_passes'])
                self.assertEqual(result['status'], 'component_candidates_with_withheld_passes')
                path = root/'geometry/geometry-candidates.jsonl'; path.write_bytes(path.read_bytes()+b'\n')
                with self.assertRaisesRegex(ValueError, 'matching source view pack and drawing feed'):
                    run(corpus, root/'geometry', pack['directory'], root/'components')
            finally: corpus.close()

    def test_area_runs_without_manual_seeds_and_exposes_component_report(self):
        from voxel_mapper.area_reconstruction import run as area_run, run_all
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); document, _ = fixtures.DrawingViewTests().source(); data = document.tobytes(); document.close()
            sha = hashlib.sha256(data).hexdigest(); (root/'sources').mkdir(); (root/'sources'/(sha+'.pdf')).write_bytes(data)
            (root/'catalogue.json').write_text(json.dumps({'entries': [{'url': 'https://portal.test/plan', 'sha256': sha, 'applicationReference': 'A'}]}))
            job = {'work_directory': 'work', 'catalogue': 'catalogue.json', 'official_hosts': ['portal.test'], 'offline': True,
                'source_directories': ['sources'], 'drawing_views': {'enabled': True, 'render_width': 400},
                'drawing_view_components': {'enabled': True},
                'areas': [{'id': 'test', 'name': 'Fixture', 'application_references': ['A'], 'required_families': ['local_building']}]}
            path = root/'job.json'; path.write_text(json.dumps(job)); result = area_run(path)['areas']['test']
            self.assertEqual(result['drawing_view_components']['views'], 4)
            self.assertIn('door_symbol_evidence', result['drawing_view_components'])
            self.assertEqual(result['world_geometry_additions'], 0)
            self.assertEqual(area_run(path)['areas']['test']['drawing_view_components']['run_views'], 0)
            self.assertIn('drawing_view_components', run_all(path, stage='extract')['results'][0])
            job['drawing_views']['enabled'] = False; path.write_text(json.dumps(job))
            with self.assertRaisesRegex(ValueError, 'requires automatic drawing views'): area_run(path)
