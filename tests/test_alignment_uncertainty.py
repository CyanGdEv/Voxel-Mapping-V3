import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import Polygon, box, mapping, shape
from voxel_mapper.alignment_uncertainty import horizontal_scope
from voxel_mapper.cross_drawing_alignment import match_page
from voxel_mapper.reconstruction.registration import review_registration
from voxel_mapper.boundary_registration import similarity
from voxel_mapper.evidence_memory import EvidenceMemory
from tests.test_cross_drawing_alignment import fixture, SHA


def registered_fixture(budget=.2):
    objects, landmarks = fixture()
    controls = [{'id': str(i), 'local': p, 'target': p} for i, p in enumerate(
        [[900, 1900], [1100, 1900], [900, 2200]])]
    checks = [{'id': str(i+3), 'local': p, 'target': p} for i, p in enumerate(
        [[1100, 2200], [1000, 2050]])]
    review = review_registration(controls, checks)
    review['reference_and_attachment_error_budget_m'] = budget
    for landmark in landmarks: landmark['registration'] = copy.deepcopy(review)
    objects.append({'id': 'nearby-path', 'family': 'path', 'geometry': mapping(box(90, 110, 100, 120))})
    return objects, landmarks


def match(objects, landmarks):
    return match_page(objects, landmarks, document_sha256=SHA, target_crs='EPSG:27700', expected_scale=.1)


class HorizontalScopeTests(unittest.TestCase):
    def test_interior_path_has_conditional_budget_but_no_registration(self):
        objects, landmarks = registered_fixture()
        result = match(objects, landmarks)
        self.assertTrue(result['unique_contextual_proposal'])
        scope = result['hypotheses'][0]['horizontal_scope_review']
        self.assertEqual(scope['status'], 'conditional_scope_assessed')
        path = next(r for r in scope['candidate_reviews'] if r['candidate_id'] == 'nearby-path')
        self.assertTrue(path['within_checked_domain'])
        self.assertEqual(path['review_flags'], [])
        self.assertGreater(path['conditional_horizontal_error_budget_m'], .2)
        self.assertFalse(path['registration_verified'])
        self.assertEqual(scope['world_geometry_additions'], 0)

    def test_missing_parent_budget_stays_unknown(self):
        objects, landmarks = fixture()
        result = match(objects, landmarks)
        scope = result['hypotheses'][0]['horizontal_scope_review']
        self.assertEqual(scope['status'], 'awaiting_parent_error_budgets')
        self.assertEqual(scope['candidate_reviews'], [])

    def test_complete_outline_not_only_centroid_must_be_inside_domain(self):
        objects, landmarks = registered_fixture()
        objects[-1]['geometry'] = mapping(box(-500, 110, 690, 120))
        scope = match(objects, landmarks)['hypotheses'][0]['horizontal_scope_review']
        path = scope['candidate_reviews'][-1]
        self.assertFalse(path['within_checked_domain'])
        self.assertIn('outside_shared_checked_domain', path['review_flags'])
        self.assertIn('horizontal_error_budget_exceeded', path['review_flags'])

    def test_parent_error_is_not_averaged_down_and_high_budget_is_flagged(self):
        objects, landmarks = registered_fixture(.9)
        scope = match(objects, landmarks)['hypotheses'][0]['horizontal_scope_review']
        self.assertGreaterEqual(scope['candidate_reviews'][-1]['conditional_horizontal_error_budget_m'], 1.1 - 1e-8)
        self.assertIn('horizontal_error_budget_exceeded', scope['candidate_reviews'][-1]['review_flags'])

    def test_parent_domain_intersection_limits_otherwise_supported_path(self):
        objects, landmarks = registered_fixture()
        # Each anchor is inside its own accepted survey domain, but the domains
        # do not overlap at the proposed path location.
        for landmark in landmarks:
            x, y = shape(landmark['feature']['geometry']).centroid.coords[0]
            points = [[x-10,y-10],[x+10,y-10],[x-10,y+10],[x+10,y+10],[x,y]]
            controls = [{'id': str(i), 'local': p, 'target': p} for i,p in enumerate(points[:3])]
            checks = [{'id': str(i+3), 'local': p, 'target': p} for i,p in enumerate(points[3:])]
            review = review_registration(controls, checks)
            review['reference_and_attachment_error_budget_m'] = .2
            landmark['registration'] = review
        scope = match(objects, landmarks)['hypotheses'][0]['horizontal_scope_review']
        self.assertFalse(scope['candidate_reviews'][-1]['within_checked_domain'])

    def test_invalid_parent_budgets_and_domains_are_rejected(self):
        for invalid in [True, -1, float('nan'), float('inf'), 2]:
            objects, landmarks = registered_fixture(invalid)
            with self.assertRaises(ValueError): match(objects, landmarks)
        objects, landmarks = registered_fixture()
        landmarks[0]['feature']['geometry'] = mapping(box(1500, 2500, 1506, 2503))
        # Directly assess a known proposal so the invalid reference is checked.
        clean_objects, clean_landmarks = registered_fixture()
        hypothesis = match(clean_objects, clean_landmarks)['hypotheses'][0]
        with self.assertRaisesRegex(ValueError, 'outside checked'):
            horizontal_scope(hypothesis, objects, landmarks)

    def test_conditional_bound_covers_adversarial_reference_perturbations(self):
        objects, landmarks = registered_fixture()
        hypothesis = match(objects, landmarks)['hypotheses'][0]
        scope = hypothesis['horizontal_scope_review']
        lookup = {o['id']: shape(o['geometry']) for o in objects}
        references = {r['id']: shape(r['feature']['geometry']) for r in landmarks}
        source = np.asarray([lookup[s['candidate_id']].centroid.coords[0] for s in hypothesis['supports']])
        target = np.asarray([references[s['reference_id']].centroid.coords[0] for s in hypothesis['supports']])
        path = lookup['nearby-path']
        nominal = affine_transform(path, [*hypothesis['matrix'][0], *hypothesis['matrix'][1], *hypothesis['translation_m']])
        rng = np.random.default_rng(8)
        bound = scope['candidate_reviews'][-1]['conditional_horizontal_error_budget_m']
        for _ in range(100):
            angles = rng.uniform(0, 2*np.pi, len(source))
            delta = np.column_stack((np.cos(angles), np.sin(angles))) * np.asarray(scope['parent_observation_error_budgets_m'])[:,None]
            matrix, translation, _, _ = similarity(source, target + delta)
            perturbed = affine_transform(path, [*matrix[0], *matrix[1], *translation])
            self.assertLessEqual(nominal.hausdorff_distance(perturbed), bound + 1e-8)

    def test_scope_tolerance_cannot_loosen_one_metre_limit(self):
        objects, landmarks = registered_fixture()
        hypothesis = match(objects, landmarks)['hypotheses'][0]
        for tolerance in [True, 0, 2, float('nan')]:
            with self.assertRaises(ValueError):
                horizontal_scope(hypothesis, objects, landmarks, tolerance_m=tolerance)

    def test_vertex_budget_withholds_whole_scope_without_partial_reviews(self):
        objects, landmarks = registered_fixture()
        hypothesis = match(objects, landmarks)['hypotheses'][0]
        angles = np.linspace(0, 2*np.pi, 16385, endpoint=False)
        objects[-1]['geometry'] = mapping(Polygon(np.column_stack((95+np.cos(angles), 115+np.sin(angles)))))
        result = horizontal_scope(hypothesis, objects, landmarks)
        self.assertEqual(result['status'], 'scope_budget_withheld')
        self.assertEqual(result['candidate_reviews'], [])

    def test_nonempty_scope_reuses_memory_and_rejection_changes_next_cycle(self):
        from voxel_mapper.planning_bulk import Corpus
        from voxel_mapper.drawing_geometry import run as extract
        from voxel_mapper.cross_drawing_alignment import run
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); corpus = Corpus(root/'corpus')
            try:
                with pymupdf.open() as doc:
                    page = doc.new_page()
                    for rectangle in [(20,20,80,50),(200,30,240,80),(40,300,60,380)]:
                        page.draw_rect(rectangle)
                    page.insert_text((20,500), 'Scale 1:100')
                    data = doc.tobytes()
                corpus.ingest([{'url':'https://portal.test/a','title':'Plan'}], ['portal.test'])
                corpus.acquire(fetch=lambda _: data)
                extract(corpus, root/'geometry')
                rows = [json.loads(line) for line in (root/'geometry/geometry-candidates.jsonl').read_text().splitlines()]
                polygons = [r for r in rows if r['geometry']['type'] == 'Polygon']
                self.assertEqual(len(polygons), 3)
                _, landmarks = registered_fixture()
                scale = 100*.0254/72
                for landmark, polygon in zip(landmarks, polygons):
                    landmark['feature']['geometry'] = mapping(affine_transform(shape(polygon['geometry']), [0,-scale,scale,0,1000,2000]))
                store = root/'memory.sqlite'
                with EvidenceMemory(store) as memory:
                    identifiers = [memory.put('registered_landmark', {'seed': r['id']}, {k:v for k,v in r.items() if k != 'id'}) for r in landmarks]
                first = run(corpus,root/'geometry',store,root/'first',target_crs='EPSG:27700')
                proposals = root/'first'/first['run_id']/'page-proposals.jsonl'
                proposal = json.loads(proposals.read_text())
                self.assertEqual(proposal['hypotheses'][0]['horizontal_scope_review']['status'], 'conditional_scope_assessed')
                with patch('voxel_mapper.cross_drawing_alignment.match_page', side_effect=AssertionError('Recomputed')):
                    second = run(corpus,root/'geometry',store,root/'second',target_crs='EPSG:27700')
                self.assertEqual(first['output_sha256'], second['output_sha256'])
                self.assertEqual(second['reused_pages'], 1)
                with EvidenceMemory(store) as memory:
                    memory.reject(identifiers[0],reviewer='qa',reason='wrong identity',review_reference='qa/1')
                updated = run(corpus,root/'geometry',store,root/'first',target_crs='EPSG:27700')
                self.assertNotEqual(first['run_id'], updated['run_id'])
                proposal = json.loads((root/'first'/updated['run_id']/'page-proposals.jsonl').read_text())
                self.assertEqual(proposal['hypotheses'], [])
                self.assertEqual(updated['registrations_accepted'], 0)
            finally: corpus.close()
