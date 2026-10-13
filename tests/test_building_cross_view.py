import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union

from voxel_mapper.building_cross_view import prepare, VERSION
from voxel_mapper.building_pipeline import run as batch


class CrossViewTests(unittest.TestCase):
    def fixture(self, root, *, states=None, duplicate_plan=False, window=False,
                bad_roof=False, width_delta=0, user_unit=None):
        states = states or ['existing']*5
        captions = ['Ground Floor Plan', 'South Elevation', 'North Elevation', 'West Elevation', 'East Elevation']
        side = [None, 'y_min', 'y_max', 'x_min', 'x_max']
        views = []
        with pymupdf.open() as document:
            for i, caption in enumerate(captions):
                page = document.new_page(width=800, height=500)
                if i == 0: points = [(40, 60), (240, 60), (240, 180), (40, 180)]
                elif i in (1, 2):
                    ridge = 210 if bad_roof and i == 2 else 180
                    points = [(40, 60), (240+width_delta, 60), (240+width_delta, 140), (140, ridge), (40, 140)]
                else: points = [(40, 60), (160, 60), (160, 140), (40, 140)]
                if i == 1 and window:
                    drawing = page.new_shape()
                    drawing.draw_polyline([(x, 500-y) for x, y in points])
                    drawing.draw_rect(pymupdf.Rect(80, 390, 110, 410))
                    drawing.finish(closePath=True, fill=(.8, .8, .8), even_odd=True)
                    drawing.commit()
                else:
                    page.draw_polyline([(x, 500-y) for x, y in points], closePath=True)
                if i == 0 and duplicate_plan:
                    page.draw_polyline([(x+350, 500-y) for x, y in points], closePath=True)
                page.insert_text((30, 460), f"{caption} 'as {states[i]}' | 1:100", fontsize=10)
                if user_unit: document.xref_set_key(page.xref, 'UserUnit', str(user_unit))
                view = {'id': 'view-'+str(i), 'kind': 'floor_plan' if i == 0 else 'elevation',
                        'page': i+1, 'bounds_pdf_native': [20, 20, 780, 250], 'caption_index': 0,
                        'scope_review_reference': 'synthetic-fixture/source-scope-'+str(i), 'reverse_x': False}
                if side[i]: view['side'] = side[i]
                views.append(view)
            raw = document.tobytes()
        (root/'original.pdf').write_bytes(raw); sha = hashlib.sha256(raw).hexdigest()
        for view in views: view['document_sha256'] = sha
        return {'version': VERSION, 'buildings': [{'building_id': 'fixture-building',
            'sources': [{'path': 'original.pdf', 'sha256': sha}], 'views': views}]}

    def test_native_views_generate_shared_spec_and_glb_but_no_ranker_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); config = self.fixture(root)
            report = prepare(config, lambda p: root/p, root/'output')
            self.assertEqual(report['shared_specs_generated'], 1, report['buildings'])
            spec = json.loads((root/'output/building-0000/building-spec.json').read_text())
            self.assertEqual(len(spec['components']), 6)
            self.assertEqual({s['state'] for s in spec['sources']}, {'existing'})
            self.assertTrue(all(c['evidence']['class'] == 'inferred' for c in spec['components']))
            self.assertEqual((root/'output/building-0000/model.glb').read_bytes()[:4], b'glTF')
            job = json.loads((root/'output/building-batch.json').read_text())
            candidate = job['buildings'][0]['candidates'][0]
            self.assertFalse(any(candidate['gates'].values()))
            self.assertEqual(candidate['features']['topology_quality'], 0)
            self.assertEqual(batch(job, root/'ranked')['built'], 0)
            self.assertEqual(report['park_world_blocks_added'], 0)
            self.assertEqual(report['training_labels_generated'], 0)
            self.assertIsNone(json.loads((root/'output/review-queue.json').read_text())['records'][0]['outcome'])
            prepare(config, lambda p: root/p, root/'replay')
            for name in ['building-batch.json', 'review-queue.json', 'report.json', 'building-0000/building-spec.json', 'building-0000/model.glb']:
                self.assertEqual((root/'output'/name).read_bytes(), (root/'replay'/name).read_bytes())
            with self.assertRaisesRegex(ValueError, 'Fresh'): prepare(config, lambda p: root/p, root/'output')

    def test_source_holes_remain_empty_and_facades_face_outwards(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); config = self.fixture(root, window=True)
            report = prepare(config, lambda p: root/p, root/'output')
            self.assertEqual(report['shared_specs_generated'], 1, report['buildings'])
            model = json.loads((root/'output/building-0000/model.json').read_text())
            expected = {'facade_y_min': (1, -1), 'facade_y_max': (1, 1), 'facade_x_min': (0, -1), 'facade_x_max': (0, 1)}
            for component in model['components']:
                if component['id'] not in expected: continue
                mesh = component['mesh']; axis, sign = expected[component['id']]
                a, b, c = [mesh['vertices'][i] for i in mesh['triangles'][0]]
                u, v = [[p[i]-a[i] for i in range(3)] for p in (b, c)]
                normal = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
                self.assertGreater(normal[axis]*sign, 0)
                if component['id'] == 'facade_y_min':
                    polygons = [Polygon([(mesh['vertices'][i][0], mesh['vertices'][i][2]) for i in t]) for t in mesh['triangles']]
                    factor = 100*.0254/72
                    self.assertFalse(unary_union(polygons).covers(Point(55*factor, 40*factor)))

    def test_ambiguous_plan_and_disagreeing_roof_do_not_emit_specs(self):
        for options in [dict(duplicate_plan=True), dict(bad_roof=True), dict(width_delta=20)]:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); config = self.fixture(root, **options)
                report = prepare(config, lambda p: root/p, root/'output')
                self.assertEqual(report['shared_specs_generated'], 0)
                self.assertFalse((root/'output/building-0000/building-spec.json').exists())
                self.assertEqual(report['park_world_blocks_added'], 0)

    def test_small_dimension_discrepancy_is_reported_without_rescaling(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); config = self.fixture(root, width_delta=1)
            report = prepare(config, lambda p: root/p, root/'output')
            self.assertEqual(report['shared_specs_generated'], 1, report['buildings'])
            result = report['buildings'][0]
            self.assertAlmostEqual(result['facade_width_differences_m']['y_min'], 100*.0254/72)
            self.assertFalse(result['original_geometry_rescaled'])
            model = json.loads((root/'output/building-0000/model.json').read_text())
            wall = next(c['mesh'] for c in model['components'] if c['id'] == 'facade_y_min')
            width = max(v[0] for v in wall['vertices'])-min(v[0] for v in wall['vertices'])
            self.assertAlmostEqual(width, 201*100*.0254/72)

    def test_missing_scope_unknown_state_and_mixed_states_are_withheld(self):
        for mode in ['no-views', 'no-review', 'unknown', 'mixed', 'unit']:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                states = ['proposed']*5 if mode not in ('unknown', 'mixed') else ['existing']*4+[('unspecified' if mode == 'unknown' else 'proposed')]
                config = self.fixture(root, states=states, user_unit=2 if mode == 'unit' else None)
                if mode == 'no-views': config['buildings'][0].pop('views')
                if mode == 'no-review': config['buildings'][0]['views'][0].pop('scope_review_reference')
                report = prepare(config, lambda p: root/p, root/'output')
                self.assertEqual(report['shared_specs_generated'], 0)

    def test_proposed_views_stay_proposed_and_cannot_train_or_place_blocks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); config = self.fixture(root, states=['proposed']*5)
            report = prepare(config, lambda p: root/p, root/'output')
            self.assertEqual(report['shared_specs_generated'], 1)
            spec = json.loads((root/'output/building-0000/building-spec.json').read_text())
            self.assertEqual({s['state'] for s in spec['sources']}, {'proposed'})
            self.assertFalse(report['world_placement_eligible'])

    def test_external_review_capture_binds_exact_features_and_all_originals(self):
        from voxel_mapper.building_source_feed import feedback_from_reviews
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); config = self.fixture(root)
            prepare(config, lambda p: root/p, root/'output')
            queue = json.loads((root/'output/review-queue.json').read_text())
            row = queue['records'][0]
            decisions = {'version': 'building-review-decisions-v1', 'records': [{
                'building_id': row['building_id'], 'candidate_sha256': row['candidate_sha256'],
                'outcome': 'rejected', 'review_basis': 'independent_review',
                'review_reference': 'synthetic-fixture/rejected-partial-envelope'}]}
            feedback = feedback_from_reviews(queue, decisions)
            self.assertEqual(feedback['records'][0]['features'], row['features'])
            self.assertEqual(feedback['records'][0]['source_sha256'], [config['buildings'][0]['sources'][0]['sha256']])
            self.assertEqual(feedback['records'][0]['outcome'], 'rejected')
            changed = copy.deepcopy(queue); changed['records'][0]['features']['source_coverage'] = 0
            with self.assertRaisesRegex(ValueError, 'queue changed'):
                feedback_from_reviews(changed, decisions)

    def test_roof_along_other_native_axis_faces_upwards(self):
        from voxel_mapper.building_cross_view import _roof
        roof = _roof({'y_min': [[0, 2], [10, 2]], 'y_max': [[0, 2], [10, 2]],
                      'x_min': [[0, 2], [3, 4], [6, 2]], 'x_max': [[0, 2], [3, 4], [6, 2]]}, 10, 6, .25)['mesh']
        for triangle in roof['triangles']:
            a, b, c = [roof['vertices'][i] for i in triangle]
            self.assertGreater((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]), 0)

    def test_one_original_face_cannot_supply_plan_and_four_elevations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with pymupdf.open() as document:
                page = document.new_page(width=800, height=500)
                page.draw_rect(pymupdf.Rect(40, 100, 240, 300))
                for i, caption in enumerate(['Ground Floor Plan', 'South Elevation', 'North Elevation', 'West Elevation', 'East Elevation']):
                    page.insert_text((30, 460-20*i), f"{caption} 'as existing' | 1:100", fontsize=10)
                raw = document.tobytes()
            (root/'original.pdf').write_bytes(raw); sha = hashlib.sha256(raw).hexdigest()
            views = [{'id': 'view-'+str(i), 'kind': 'floor_plan' if i == 0 else 'elevation',
                      'document_sha256': sha, 'page': 1, 'caption_index': i,
                      'bounds_pdf_native': [20, 20, 780, 450], 'scope_review_reference': 'fixture/reused-face'}
                     for i in range(5)]
            for view, side in zip(views[1:], ['y_min', 'y_max', 'x_min', 'x_max']): view['side'] = side
            config = {'version': VERSION, 'buildings': [{'building_id': 'fixture',
                'sources': [{'path': 'original.pdf', 'sha256': sha}], 'views': views}]}
            report = prepare(config, lambda p: root/p, root/'output')
            self.assertEqual(report['shared_specs_generated'], 0)
            reviews = report['buildings'][0]['plan_reviews']
            self.assertEqual(reviews[0]['reason'], 'one_native_face_reused_across_source_views')

    def test_declared_view_reversal_preserves_opening_and_outward_normals(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); config = self.fixture(root, window=True)
            for view in config['buildings'][0]['views'][1:]: view['reverse_x'] = True
            report = prepare(config, lambda p: root/p, root/'output')
            self.assertEqual(report['shared_specs_generated'], 1, report['buildings'])
            model = json.loads((root/'output/building-0000/model.json').read_text())
            wall = next(c['mesh'] for c in model['components'] if c['id'] == 'facade_y_min')
            polygons = [Polygon([(wall['vertices'][i][0], wall['vertices'][i][2]) for i in t]) for t in wall['triangles']]
            factor = 100*.0254/72
            self.assertFalse(unary_union(polygons).covers(Point(145*factor, 40*factor)))
            a, b, c = [wall['vertices'][i] for i in wall['triangles'][0]]
            self.assertLess((b[2]-a[2])*(c[0]-a[0])-(b[0]-a[0])*(c[2]-a[2]), 0)

    def test_partial_discovery_and_matching_budgets_discard_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); config = self.fixture(root)
            with patch('voxel_mapper.building_pdf_discovery.extract_page', return_value=([], {'status': 'partial_candidate_budget'})):
                report = prepare(config, lambda p: root/p, root/'partial')
            self.assertEqual(report['shared_specs_generated'], 0)
            for options in [{'max_checks': 1}, {'max_faces_per_view': 1}]:
                config['options'] = options
                if 'max_faces_per_view' in options:
                    config = self.fixture(root, duplicate_plan=True); config['options'] = options
                report = prepare(config, lambda p: root/p, root/('limited-'+next(iter(options))))
                self.assertEqual(report['shared_specs_generated'], 0)

    def test_changed_original_is_not_published_and_bad_buildings_are_isolated(self):
        from voxel_mapper.building_cross_view import assemble
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); config = self.fixture(root)
            def changing(*args):
                result = assemble(*args)
                path = root/'original.pdf'; path.write_bytes(path.read_bytes()+b'changed')
                return result
            with patch('voxel_mapper.building_cross_view.assemble', side_effect=changing):
                report = prepare(config, lambda p: root/p, root/'changed')
            self.assertEqual(report['shared_specs_generated'], 0)
            self.assertIn('changed during', report['buildings'][0]['reason'])
            self.assertFalse((root/'changed/building-0000/building-spec.json').exists())
            config = self.fixture(root); bad = copy.deepcopy(config['buildings'][0]); bad['building_id'] = 'bad'
            bad['sources'][0]['sha256'] = 'f'*64
            for view in bad['views']: view['document_sha256'] = 'f'*64
            config['buildings'].insert(0, bad)
            report = prepare(config, lambda p: root/p, root/'isolated')
            self.assertEqual(report['shared_specs_generated'], 1)
            self.assertEqual(report['buildings'][0]['status'], 'awaiting_cross_view_evidence')

    def test_cli_and_invalid_bindings(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from voxel_mapper.building_pipeline import main
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); config = self.fixture(root)
            (root/'config.json').write_text(json.dumps(config))
            with redirect_stdout(StringIO()): main(['assemble-views', '--config', str(root/'config.json'), '--output', str(root/'cli')])
            self.assertEqual(json.loads((root/'cli/report.json').read_text())['shared_specs_generated'], 1)
            for mutation in ['foreign-source', 'duplicate-side', 'reused-caption', 'bad-bounds', 'bad-tolerance', 'unknown-binding']:
                bad = copy.deepcopy(config)
                if mutation == 'foreign-source': bad['buildings'][0]['views'][0]['document_sha256'] = 'f'*64
                if mutation == 'duplicate-side': bad['buildings'][0]['views'][2]['side'] = 'y_min'
                if mutation == 'reused-caption': bad['buildings'][0]['views'][2]['page'] = 2
                if mutation == 'bad-bounds': bad['buildings'][0]['views'][0]['bounds_pdf_native'][2] = float('nan')
                if mutation == 'bad-tolerance': bad['options'] = {'dimension_tolerance_m': 1}
                if mutation == 'unknown-binding': bad['buildings'][0]['views'][0]['physical_identity_verified'] = True
                with self.assertRaises(ValueError): prepare(bad, lambda p: root/p, root/mutation)
                self.assertFalse((root/mutation).exists())
