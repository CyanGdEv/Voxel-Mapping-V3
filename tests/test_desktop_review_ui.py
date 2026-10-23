"""Actual source/candidate preview and explicit review interactions."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from voxel_mapper.desktop_review_presets import prepare_demo
from voxel_mapper.desktop_review_ui import geometry_preview, render_pdf_preview


def display_available():
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.destroy()
        return True
    except Exception:
        return False


class ReviewPreviewTests(unittest.TestCase):
    def test_real_pdf_render_has_bounded_size_and_changed_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = prepare_demo(Path(tmp)/'demo')
            source = Path(report['source_paths'][0])
            pin = hashlib.sha256(source.read_bytes()).hexdigest()
            payload = {'path': str(source), 'sha256': pin, 'pages': 1}
            png = render_pdf_preview(payload, 1)
            self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
            from PIL import Image
            from io import BytesIO
            image = Image.open(BytesIO(png))
            self.assertLessEqual(image.width * image.height, 2000000)
            with self.assertRaisesRegex(ValueError, 'page'):
                render_pdf_preview(payload, 2)
            source.write_bytes(source.read_bytes()+b'changed')
            with self.assertRaisesRegex(ValueError, 'changed'):
                render_pdf_preview(payload, 1)

    def test_geometry_preview_preserves_local_bounds_and_does_not_change_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = prepare_demo(Path(tmp)/'demo')
            batch = json.loads(Path(report['batch_path']).read_text())
            spec = batch['buildings'][0]['candidates'][0]['spec']
            original = copy.deepcopy(spec)
            preview = geometry_preview(spec)
            self.assertEqual(spec, original)
            self.assertEqual(preview['bounds'], [[0, 8], [0, .3], [0, 4]])
            self.assertGreater(preview['edge_count'], 0)
            self.assertLessEqual(preview['edge_count'], 10000)
            self.assertEqual(preview['coordinate_frame'], 'local_xyz_metres_z_up')

    def test_extreme_pdf_dimensions_are_rejected_before_native_allocation(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as tmp:
            report = prepare_demo(Path(tmp)/'demo')
            path = Path(report['source_paths'][0])
            source = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            page = Mock()
            page.rect = pymupdf.Rect(0, 0, 10000000000, 1)
            document = Mock()
            document.needs_pass = False
            document.page_count = 1
            document.__getitem__ = Mock(return_value=page)
            context = Mock()
            context.__enter__ = Mock(return_value=document)
            context.__exit__ = Mock(return_value=None)
            with patch('pymupdf.open', return_value=context):
                with self.assertRaisesRegex(ValueError, 'dimensions'):
                    render_pdf_preview(source, 1)
            page.get_pixmap.assert_not_called()


@unittest.skipUnless(display_available(), 'A Tk display is required for visual interaction tests')
class ReviewInteractionTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from voxel_mapper.desktop_review_ui import ReviewWindow
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.preset = prepare_demo(self.directory/'demo')
        self.root = tk.Tk()
        self.root.withdraw()
        self.imported = []
        self.review = ReviewWindow(self.root, self.directory/'reviews', self.imported.append)
        self.review.load_queue(self.preset['queue_path'], batch_path=self.preset['batch_path'], source_paths=self.preset['source_paths'])
        self.wait_for(lambda: self.review.pending == 0 and self.review.preview is not None and self.review._displayed_source is not None)

    def tearDown(self):
        self.review.close()
        self.root.destroy()
        self.temporary.cleanup()

    def wait_for(self, predicate):
        deadline = time.monotonic()+20
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            if self.review.last_error:
                self.fail(self.review.last_error)
            time.sleep(.01)
        self.fail('Review operation exceeded its bounded test deadline')

    def test_draft_replacement_does_not_label_original_or_enable_import(self):
        review = self.review
        for point in ('0.5, 0.5', '3, 0.5', '3, 2.5', '0.5, 2.5'):
            review.point_entry.set(point)
            review._add_exact_point()
        review.add_button.invoke()
        self.assertEqual(len(review.corrections), 1)
        self.assertEqual(review.corrections[0]['points_m'][0], [.5, .5])
        review.outcome.set('accepted')
        review.review_reference.set('synthetic UI independent-review fixture')
        review.save_decision()
        self.assertIn('Reject the original', review.last_error)
        self.assertIsNone(review.last_report)
        review.save_draft()
        self.wait_for(lambda: review.pending == 0 and review.last_report is not None)
        self.assertEqual(review.last_report['status'], 'correction_draft_saved')
        self.assertFalse(review.last_report.get('feedback_path'))
        self.assertIn('disabled', review.import_button.state())
        self.assertEqual(self.imported, [])
        self.assertEqual(review.session['records'][0]['outcome'], None)

    def test_review_requires_reference_and_import_is_an_explicit_separate_action(self):
        review = self.review
        review.outcome.set('rejected')
        review.save_decision()
        self.assertIn('external review reference', review.last_error)
        review.review_reference.set('synthetic UI fixture external decision')
        review.save_decision()
        self.wait_for(lambda: review.pending == 0 and review.last_report is not None)
        feedback_path = review.last_report['feedback_path']
        feedback = json.loads(Path(feedback_path).read_text())
        self.assertEqual(feedback['records'][0]['outcome'], 'rejected')
        self.assertEqual(self.imported, [])
        self.assertNotIn('disabled', review.import_button.state())
        review.import_button.invoke()
        self.assertEqual(self.imported, [feedback_path])
        self.assertIn('disabled', review.import_button.state())

    def test_changed_page_selection_cannot_attribute_correction_to_unseen_evidence(self):
        review = self.review
        review.correction_type.set('dimension')
        review.dimension.set('4')
        review.source_page.set(2)
        review.add_correction()
        self.assertEqual(review.corrections, [])
        self.assertIn('existing source page', review.last_error)
        review.source_page.set(1)
        review._displayed_source = None
        review.add_correction()
        self.assertIn('Show and verify', review.last_error)

    def test_dimension_correction_records_the_explicit_axis(self):
        review = self.review
        review.correction_type.set('dimension')
        review.dimension.set('4')
        review.dimension_axis.set('z')
        review.add_correction()
        self.assertEqual(review.corrections[0]['axis'], 'z')
        self.assertEqual(review.corrections[0]['value_m'], 4.)

    def test_rapid_pdf_bind_is_gated_until_current_source_operation_completes(self):
        review = self.review
        review.bind_pdf(self.preset['source_paths'][0])
        pending = review.pending
        review.bind_pdf(self.preset['source_paths'][0])
        self.assertEqual(review.pending, pending)
        self.assertIn('Wait for the current', review.last_error)
        review.last_error = None
        self.wait_for(lambda: review.pending == 0)
        self.assertEqual(set(review.session['resolved_sources']), set(review.current_record['source_sha256']))

    def test_edit_during_save_retains_receipt_without_enabling_stale_import(self):
        import threading
        from voxel_mapper.desktop_review import save_review
        review = self.review
        review.outcome.set('rejected')
        review.review_reference.set('synthetic original review')
        release = threading.Event()
        def delayed(*args, **kwargs):
            if not release.wait(5):
                raise TimeoutError('test save release was not signalled')
            return save_review(*args, **kwargs)
        with patch('voxel_mapper.desktop_review.save_review', side_effect=delayed):
            review.save_decision()
            review.review_reference.set('changed after the saved snapshot')
            release.set()
            self.wait_for(lambda: review.pending == 0)
        self.assertIsNotNone(review.last_saved_report)
        self.assertIsNone(review.last_report)
        self.assertIn('disabled', review.import_button.state())
        self.assertEqual(self.imported, [])

    def test_navigation_restores_unsaved_candidate_corrections_and_review_reference(self):
        from voxel_mapper.building_spec import digest
        review = self.review
        batch_path = Path(self.preset['batch_path'])
        queue_path = Path(self.preset['queue_path'])
        batch = json.loads(batch_path.read_text())
        queue = json.loads(queue_path.read_text())
        second = copy.deepcopy(batch['buildings'][0]['candidates'][0])
        second['id'] = 'synthetic-second'
        second['candidate_sha256'] = digest({key: value for key, value in second.items() if key != 'candidate_sha256'})
        batch['buildings'][0]['candidates'].append(second)
        row = copy.deepcopy(queue['records'][0])
        row.update(candidate_id=second['id'], candidate_sha256=second['candidate_sha256'])
        queue['records'].append(row)
        queue['content_sha256'] = digest({key: value for key, value in queue.items() if key != 'content_sha256'})
        batch_path.write_text(json.dumps(batch))
        queue_path.write_text(json.dumps(queue))
        review.load_queue(queue_path, batch_path=batch_path, source_paths=self.preset['source_paths'])
        self.wait_for(lambda: review.pending == 0)
        first_label, second_label = review.candidate_picker.cget('values')
        review.correction_type.set('dimension')
        review.dimension.set('4.2')
        review.dimension_axis.set('z')
        review.add_correction()
        review.review_reference.set('unsaved synthetic reviewer reference')
        review.candidate_choice.set(second_label)
        review._candidate_changed()
        self.wait_for(lambda: review.pending == 0)
        self.assertEqual(review.corrections, [])
        review.candidate_choice.set(first_label)
        review._candidate_changed()
        self.wait_for(lambda: review.pending == 0)
        self.assertEqual(len(review.corrections), 1)
        self.assertEqual(review.corrections[0]['value_m'], 4.2)
        self.assertEqual(review.review_reference.get(), 'unsaved synthetic reviewer reference')

    def test_saved_correction_draft_reopens_in_fresh_tk_instance_without_feedback(self):
        import tkinter as tk
        from voxel_mapper.desktop_review_ui import ReviewWindow
        review = self.review
        review.correction_type.set('dimension')
        review.dimension.set('4.25')
        review.dimension_axis.set('z')
        review.add_correction()
        review.save_draft()
        self.wait_for(lambda: review.pending == 0 and review.last_report is not None)
        saved = review.last_report
        expected = copy.deepcopy(review.corrections)
        original_bytes = Path(saved['corrections_path']).read_bytes()
        review.close()
        self.root.destroy()
        self.root = tk.Tk()
        self.root.withdraw()
        self.review = ReviewWindow(self.root, self.directory/'reviews', self.imported.append)
        self.review.load_saved_review(saved['output_directory'])
        self.wait_for(lambda: self.review.pending == 0 and self.review.preview is not None and self.review._displayed_source is not None)
        self.assertEqual(self.review.corrections, expected)
        self.assertEqual(self.review.dimension_axis.get(), 'z')
        self.assertEqual(self.review.dimension.get(), '4.25')
        self.assertEqual(self.review.outcome.get(), 'unreviewed')
        self.assertEqual(self.review.review_reference.get(), '')
        self.assertIsNone(self.review.last_report)
        self.assertIn('disabled', self.review.import_button.state())
        self.assertEqual(self.imported, [])
        self.assertFalse((Path(saved['output_directory'])/'feedback.json').exists())
        self.review.save_draft()
        self.wait_for(lambda: self.review.pending == 0 and self.review.last_report is not None)
        self.assertNotEqual(self.review.last_report['output_directory'], saved['output_directory'])
        self.assertEqual(Path(saved['corrections_path']).read_bytes(), original_bytes)

    def test_saved_original_review_restores_reference_but_never_auto_imports(self):
        import tkinter as tk
        from voxel_mapper.desktop_review_ui import ReviewWindow
        review = self.review
        review.outcome.set('rejected')
        review.review_reference.set('synthetic retained external-review reference')
        review.save_decision()
        self.wait_for(lambda: review.pending == 0 and review.last_report is not None)
        saved = review.last_report
        review.close()
        self.root.destroy()
        self.root = tk.Tk()
        self.root.withdraw()
        self.review = ReviewWindow(self.root, self.directory/'reviews', self.imported.append)
        self.review.load_saved_review(saved['output_directory'])
        self.wait_for(lambda: self.review.pending == 0 and self.review.preview is not None and self.review._displayed_source is not None)
        self.assertEqual(self.review.outcome.get(), 'rejected')
        self.assertEqual(self.review.review_reference.get(), 'synthetic retained external-review reference')
        self.assertEqual(self.imported, [])
        self.assertIsNone(self.review.last_report)
        self.assertIn('disabled', self.review.import_button.state())

    def test_close_during_background_work_never_invokes_tk_callback_after_destroy(self):
        review = self.review
        callback_calls = []
        review._background(lambda: 'finished', callback_calls.append, 'Closing test')
        review.close()
        for _ in range(4):
            self.root.update()
            time.sleep(.01)
        self.assertTrue(review.closed)
        self.assertEqual(callback_calls, [])

    def test_regeneration_requires_current_saved_corrections_and_is_explicit(self):
        review=self.review;requests=[]
        review.on_regenerate=lambda path,**options:requests.append((path,options))
        self.assertIn('disabled',review.regenerate_button.state())
        review.correction_type.set('dimension');review.dimension.set('9');review.dimension_axis.set('x');review.add_correction()
        review.save_draft();self.wait_for(lambda:review.pending==0 and review.last_report is not None)
        self.assertEqual(requests,[])
        self.assertNotIn('disabled',review.regenerate_button.state())
        review.regenerate_button.invoke()
        self.assertEqual(requests,[(review.last_report['output_directory'],{'benchmark_path':None})])
        self.assertEqual(self.imported,[])
        review.dimension.set('10')
        self.assertIn('disabled',review.regenerate_button.state())
        review.regenerate_saved()
        self.assertEqual(len(requests),1)

    def test_resumed_draft_can_regenerate_without_importing_feedback(self):
        from voxel_mapper.desktop_review_ui import ReviewWindow
        review=self.review
        review.correction_type.set('dimension');review.dimension.set('9');review.dimension_axis.set('x');review.add_correction()
        review.save_draft();self.wait_for(lambda:review.pending==0 and review.last_report is not None)
        saved=review.last_report;review.close();self.root.destroy()
        import tkinter as tk
        self.root=tk.Tk();self.root.withdraw();requests=[]
        self.review=ReviewWindow(self.root,self.directory/'reviews',self.imported.append,
            on_regenerate=lambda path,**options:requests.append((path,options)))
        self.review.load_saved_review(saved['output_directory'])
        self.wait_for(lambda:self.review.pending==0 and self.review.preview is not None)
        self.assertNotIn('disabled',self.review.regenerate_button.state())
        self.review.regenerate_button.invoke()
        self.assertEqual(requests[0][0],saved['output_directory'])
        self.assertEqual(self.imported,[])


if __name__ == '__main__':
    unittest.main()
