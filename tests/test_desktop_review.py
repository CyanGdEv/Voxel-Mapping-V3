"""Provenance and feedback invariants for visual geometry corrections."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import pymupdf

from voxel_mapper.building_spec import digest
from voxel_mapper.desktop_memory import MemoryStore
from voxel_mapper.desktop_review import bind_source, load_session, resume_review, save_review
from tests.test_building_data_pipeline import candidate


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, allow_nan=False), encoding='utf-8')


def seal_queue(queue):
    queue['content_sha256'] = digest({k: v for k, v in queue.items() if k != 'content_sha256'})


class DesktopReviewTests(unittest.TestCase):
    def fixture(self, root):
        with pymupdf.open() as document:
            for name in ('Source plan', 'Source elevation'):
                page = document.new_page(width=200, height=150)
                page.insert_text((20, 30), name)
            raw = document.tobytes()
        pdf = root/'source.pdf'; pdf.write_bytes(raw)
        sha = hashlib.sha256(raw).hexdigest()
        c = candidate()
        c['spec']['sources'][0]['sha256'] = sha
        c['gates']['identity_verified'] = False
        c['candidate_sha256'] = digest(c)
        batch = {'version': 'building-batch-v1', 'buildings': [{'building_id': 'building-a', 'candidates': [c]}]}
        queue = {'version': 'building-review-queue-v1', 'records': [{
            'building_id': 'building-a', 'candidate_id': c['id'],
            'candidate_sha256': c['candidate_sha256'], 'features': c['features'],
            'source_sha256': [sha], 'outcome': None, 'review_basis': None}]}
        seal_queue(queue)
        write(root/'review-queue.json', queue); write(root/'buildings.json', batch)
        return load_session(root/'review-queue.json'), sha

    def annotation(self, sha):
        return {'type': 'outline', 'component_id': 'front', 'projection': 'xz',
                'points_m': [[0, 0], [8, 0], [8, 4.2], [0, 4.2]],
                'source_sha256': sha, 'source_page': 2}

    def save(self, root, session, **changes):
        values = {'building_id': 'building-a', 'candidate_sha256': session['records'][0]['candidate_sha256'],
                  'outcome': 'rejected', 'review_basis': 'independent_review',
                  'review_reference': 'external-review/checked-drawing-002', 'corrections': [],
                  'output_directory': root/'review'}
        values.update(changes)
        return save_review(session, **values)

    def test_source_bound_draft_is_immutable_and_never_creates_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); session, sha = self.fixture(root)
            original = copy.deepcopy(session)
            bound = bind_source(session, root/'source.pdf')
            self.assertEqual(session, original)
            result = self.save(root, bound, outcome=None, review_basis=None, review_reference='',
                                corrections=[self.annotation(sha)])
            self.assertEqual(result['status'], 'correction_draft_saved')
            self.assertIsNone(result['feedback_path']); self.assertIsNone(result['decision_path'])
            self.assertEqual(result['reviewed_records'], 0)
            self.assertEqual(result['training_labels_generated'], 0)
            self.assertFalse((root/'review/feedback.json').exists())
            saved = json.loads((root/'review/corrections.json').read_text())
            self.assertEqual(saved['corrections'][0], self.annotation(sha))
            self.assertFalse(saved['geometry_modified']); self.assertFalse(saved['corrected_geometry_verified'])
            self.assertFalse(saved['world_placement_eligible'])
            retained = json.loads(Path(result['candidate_path']).read_text())
            self.assertEqual(retained, original['records'][0]['candidate'])
            context = json.loads(Path(result['context_path']).read_text())
            self.assertEqual(context['queue_record']['candidate_sha256'], retained['candidate_sha256'])
            self.assertEqual(context['bound_sources'][sha]['pages'], 2)
            self.assertEqual(session, original)
            with self.assertRaisesRegex(ValueError, 'fresh immutable'):
                self.save(root, bound)

    def test_accepted_original_imports_existing_feedback_without_changing_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); session, _ = self.fixture(root)
            before = (root/'buildings.json').read_bytes()
            result = self.save(root, session, outcome='accepted')
            feedback = json.loads(Path(result['feedback_path']).read_text())
            self.assertEqual(feedback['records'][0]['outcome'], 'accepted')
            self.assertEqual(feedback['records'][0]['candidate_sha256'], session['records'][0]['candidate_sha256'])
            memory = MemoryStore(root/'memory')
            self.assertEqual(memory.import_feedback(feedback['records']), 1)
            self.assertEqual(memory.import_feedback(feedback['records']), 0)
            self.assertFalse(session['records'][0]['candidate']['gates']['identity_verified'])
            self.assertEqual((root/'buildings.json').read_bytes(), before)
            self.assertFalse(result['world_placement_eligible'])

    def test_rejected_original_retains_features_and_records_unverified_correction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); session, sha = self.fixture(root)
            bound = bind_source(session, root/'source.pdf')
            result = self.save(root, bound, corrections=[self.annotation(sha)])
            record = json.loads(Path(result['feedback_path']).read_text())['records'][0]
            self.assertEqual(record['outcome'], 'rejected')
            self.assertEqual(record['features'], session['records'][0]['features'])
            self.assertEqual(record['source_sha256'], [sha])
            self.assertEqual(result['reviewed_records'], 1)
            self.assertFalse(result['corrected_geometry_verified'])

    def test_changed_queue_batch_and_in_memory_session_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); session, _ = self.fixture(root)
            changed = copy.deepcopy(session)
            changed['records'][0]['features']['boundary_support'] = .1
            with self.assertRaisesRegex(ValueError, 'session changed'):
                self.save(root, changed)
            batch = json.loads((root/'buildings.json').read_text())
            batch['buildings'][0]['candidates'][0]['spec']['assumptions'].append('changed')
            write(root/'buildings.json', batch)
            with self.assertRaisesRegex(ValueError, 'hash changed'):
                self.save(root, session)
            self.assertFalse((root/'review').exists())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); session, _ = self.fixture(root)
            queue = json.loads((root/'review-queue.json').read_text())
            queue['records'][0]['features']['boundary_support'] = .1
            seal_queue(queue); write(root/'review-queue.json', queue)
            with self.assertRaisesRegex(ValueError, 'exact candidate'):
                self.save(root, session)

    def test_resealed_wrong_source_inventory_cannot_replace_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.fixture(root)
            queue = json.loads((root/'review-queue.json').read_text())
            queue['records'][0]['source_sha256'] = ['b'*64]
            seal_queue(queue); write(root/'review-queue.json', queue)
            with self.assertRaisesRegex(ValueError, 'source inventory'):
                load_session(root/'review-queue.json')

    def test_source_binding_rejects_unrelated_and_changed_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); session, sha = self.fixture(root)
            with pymupdf.open() as document:
                document.new_page(); (root/'other.pdf').write_bytes(document.tobytes())
            with self.assertRaisesRegex(ValueError, 'checksum'):
                bind_source(session, root/'other.pdf')
            bound = bind_source(session, root/'source.pdf')
            raw = (root/'source.pdf').read_bytes(); (root/'source.pdf').write_bytes(raw+b'\nchanged')
            with self.assertRaisesRegex(ValueError, 'bound original source PDF changed'):
                self.save(root, bound, corrections=[self.annotation(sha)])
            self.assertFalse((root/'review').exists())

    def test_annotations_require_original_pdf_and_existing_page_component(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); session, sha = self.fixture(root)
            with self.assertRaisesRegex(ValueError, 'Bind the original PDF'):
                self.save(root, session, corrections=[self.annotation(sha)])
            bound = bind_source(session, root/'source.pdf')
            variants = [('source_page', 3), ('source_page', True), ('component_id', 'imaginary'),
                        ('source_sha256', 'b'*64)]
            for key, value in variants:
                annotation = self.annotation(sha); annotation[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.save(root, bound, corrections=[annotation])
            self.assertFalse((root/'review').exists())

    def test_invalid_polygons_coordinates_and_annotation_fields_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); session, sha = self.fixture(root)
            bound = bind_source(session, root/'source.pdf')
            changes = [
                {'points_m': [[0, 0], [2, 2], [0, 2], [2, 0]]},
                {'points_m': [[0, 0], [1, 1], [2, 2]]},
                {'points_m': [[0, 0], [1, float('inf')], [2, 0]]},
                {'points_m': [[0, 0], [1, True], [2, 0]]},
                {'projection': 'geographic'}, {'accepted': True}, {'type': 'invent_geometry'},
                {'points_m': [[0, 0]]}]
            for change in changes:
                annotation = {**self.annotation(sha), **change}
                with self.subTest(change=change), self.assertRaises(ValueError):
                    self.save(root, bound, corrections=[annotation])

    def test_geometry_correction_cannot_label_original_candidate_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); session, sha = self.fixture(root)
            bound = bind_source(session, root/'source.pdf')
            with self.assertRaisesRegex(ValueError, 'cannot be labelled accepted'):
                self.save(root, bound, outcome='accepted', corrections=[self.annotation(sha)])
            self.assertFalse((root/'review').exists())

    def test_missing_review_reference_prediction_labels_and_empty_draft_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); session, _ = self.fixture(root)
            for changes in ({'review_reference': ''}, {'review_reference': ' '},
                            {'review_basis': 'model_prediction'}, {'outcome': 'unknown'},
                            {'outcome': None, 'review_basis': None, 'review_reference': ''}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    self.save(root, session, **changes)

    def test_dimension_and_placement_annotations_remain_local_hypotheses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); session, sha = self.fixture(root)
            bound = bind_source(session, root/'source.pdf')
            annotations = [{'type': 'dimension', 'component_id': 'front', 'value_m': 4.2, 'axis': 'z',
                            'source_sha256': sha, 'source_page': 2},
                           {'type': 'placement', 'translation_m': [1, -2, .5], 'rotation_degrees': 90,
                            'source_sha256': sha, 'source_page': 1}]
            result = self.save(root, bound, corrections=annotations)
            self.assertEqual(result['correction_count'], 2)
            self.assertFalse(result['geometry_modified'])
            self.assertEqual(session['records'][0]['candidate']['spec']['coordinate_frame'], 'local_xyz_metres_z_up')
            saved = json.loads(Path(result['corrections_path']).read_text())
            self.assertIn('positive local Z axis', saved['placement_convention'])

    def test_dimension_needs_explicit_supported_axis(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); session, sha = self.fixture(root)
            bound = bind_source(session, root/'source.pdf')
            base = {'type': 'dimension', 'component_id': 'front', 'value_m': 4.2,
                    'source_sha256': sha, 'source_page': 2}
            for annotation in (base, {**base, 'axis': 'height'}, {**base, 'axis': None},
                               {**base, 'axis': 2}):
                with self.subTest(annotation=annotation), self.assertRaises(ValueError):
                    self.save(root, bound, corrections=[annotation])
            self.assertFalse((root/'review').exists())
            for axis in ('x', 'y', 'z'):
                result = self.save(root, bound, corrections=[{**base, 'axis': axis}],
                                   output_directory=root/('axis-'+axis))
                saved = json.loads(Path(result['corrections_path']).read_text())
                self.assertEqual(saved['corrections'][0]['axis'], axis)

    def test_explicit_batch_resolves_ambiguous_siblings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); session, _ = self.fixture(root)
            (root/'building-batch.json').write_bytes((root/'buildings.json').read_bytes())
            with self.assertRaisesRegex(ValueError, 'explicitly'):
                load_session(root/'review-queue.json')
            explicit = load_session(root/'review-queue.json', root/'buildings.json')
            self.assertEqual(explicit['records'], session['records'])

    def test_fresh_reopen_restores_draft_points_dimension_axis_and_verified_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); session, sha = self.fixture(root)
            bound = bind_source(session, root/'source.pdf')
            annotations = [self.annotation(sha), {'type': 'dimension', 'component_id': 'front',
                           'value_m': 4.2, 'axis': 'z', 'source_sha256': sha, 'source_page': 2}]
            saved = self.save(root, bound, outcome=None, review_basis=None, review_reference='',
                              corrections=annotations)
            paths = {path.name: path.read_bytes() for path in (root/'review').iterdir()}
            del session, bound
            reopened = resume_review(root/'review')
            self.assertEqual(reopened['corrections'], annotations)
            self.assertEqual(reopened['building_id'], 'building-a')
            self.assertEqual(reopened['candidate_sha256'], reopened['session']['records'][0]['candidate_sha256'])
            self.assertEqual(reopened['session']['resolved_sources'][sha]['pages'], 2)
            self.assertIsNone(reopened['decision'])
            self.assertEqual(reopened['report'], saved)
            self.assertIsNone(reopened['report']['feedback_path'])
            self.assertFalse((root/'review/feedback.json').exists())
            self.assertEqual({path.name: path.read_bytes() for path in (root/'review').iterdir()}, paths)

    def test_fresh_reopen_restores_reviewed_original_without_importing_again(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); session, sha = self.fixture(root)
            bound = bind_source(session, root/'source.pdf')
            saved = self.save(root, bound, corrections=[self.annotation(sha)])
            reopened = resume_review(root/'review')
            self.assertEqual(reopened['decision']['outcome'], 'rejected')
            self.assertEqual(reopened['decision']['review_reference'], 'external-review/checked-drawing-002')
            self.assertEqual(reopened['report']['feedback_path'], saved['feedback_path'])
            self.assertFalse(reopened['report']['world_placement_eligible'])
            self.assertEqual(reopened['report']['training_labels_generated'], 0)
            self.assertFalse((root/'memory').exists())

    def test_reopen_rejects_each_changed_saved_artifact(self):
        files = ('report.json', 'review-context.json', 'corrections.json',
                 'original-candidate.json', 'decisions.json', 'feedback.json')
        for name in files:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); session, sha = self.fixture(root)
                bound = bind_source(session, root/'source.pdf')
                self.save(root, bound, corrections=[self.annotation(sha)])
                path = root/'review'/name
                changed = json.loads(path.read_text()); changed['changed_after_save'] = True
                write(path, changed)
                with self.assertRaises(ValueError):
                    resume_review(root/'review')

    def test_reopen_rejects_modified_or_missing_original_queue_and_pdf(self):
        for change in ('queue_changed', 'queue_missing', 'pdf_changed', 'pdf_missing'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); session, sha = self.fixture(root)
                bound = bind_source(session, root/'source.pdf')
                self.save(root, bound, outcome=None, review_basis=None, review_reference='',
                          corrections=[self.annotation(sha)])
                if change == 'queue_changed':
                    path = root/'review-queue.json'; path.write_bytes(path.read_bytes()+b'\n')
                elif change == 'queue_missing':
                    (root/'review-queue.json').unlink()
                elif change == 'pdf_changed':
                    path = root/'source.pdf'; path.write_bytes(path.read_bytes()+b'\nchanged')
                else:
                    (root/'source.pdf').unlink()
                with self.assertRaisesRegex(ValueError, 'missing or changed|checksum changed'):
                    resume_review(root/'review')

    def test_reopen_never_elevates_resealed_correction_acceptance_flags(self):
        for name in ('report.json', 'corrections.json'):
            for flag in ('world_placement_eligible', 'geometry_modified', 'corrected_geometry_verified'):
                with self.subTest(name=name, flag=flag), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory); session, sha = self.fixture(root)
                    bound = bind_source(session, root/'source.pdf')
                    self.save(root, bound, outcome=None, review_basis=None, review_reference='',
                              corrections=[self.annotation(sha)])
                    path = root/'review'/name
                    changed = json.loads(path.read_text()); changed[flag] = True
                    seal_queue(changed); write(path, changed)
                    with self.assertRaisesRegex(ValueError, 'cannot authorize'):
                        resume_review(root/'review')

    def test_reopen_draft_refuses_injected_feedback_even_with_valid_source_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); session, sha = self.fixture(root)
            bound = bind_source(session, root/'source.pdf')
            self.save(root, bound, outcome=None, review_basis=None, review_reference='',
                      corrections=[self.annotation(sha)])
            write(root/'review/feedback.json', {'version': 'building-feedback-v1', 'records': []})
            with self.assertRaisesRegex(ValueError, 'draft cannot contain'):
                resume_review(root/'review')


if __name__ == '__main__':
    unittest.main()
