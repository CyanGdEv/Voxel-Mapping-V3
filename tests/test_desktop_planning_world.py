"""Planning previews retain the exact completed source snapshot across desktop jobs."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from voxel_mapper.desktop_app import DesktopWindow, JOB_KINDS
from voxel_mapper.desktop_runtime import DesktopRuntime, HEAVY, _worker, file_hash, read_json, write_json


class DesktopPlanningWorldTests(unittest.TestCase):
    def source_job(self, runtime, *, kind='planning_collection', status='completed', pin=True):
        directory = runtime.directory/'jobs'/'source-job'
        output = directory/'output'
        relative = 'analysis/design-massing.json' if kind == 'web_planning_pilot' else 'design-massing.json'
        review = output/relative
        write_json(review, {'source_snapshot': 'unchanged original review'})
        config = directory/'source.json'
        write_json(config, {})
        runtime.store.add_job({'id': 'source-job', 'kind': kind, 'config_path': str(config),
            'config_sha256': file_hash(config), 'output_directory': str(output)})
        runtime.store.update_job('source-job', status=status,
            result={'output_sha256': {relative: file_hash(review)} if pin else {}})
        return review

    def test_registered_as_a_managed_heavy_operation(self):
        self.assertIn('planning_world_preview', HEAVY)
        self.assertIn('planning_world_preview', dict(JOB_KINDS).values())

    def test_completed_source_types_pin_the_exact_review_and_explicit_pair(self):
        for kind in ('planning_source_pilot', 'web_planning_pilot', 'planning_collection'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                runtime = DesktopRuntime(Path(tmp)/'memory', memory_budget_mb=2048)
                try:
                    review = self.source_job(runtime, kind=kind)
                    ids = ['a'*64, 'b'*64]
                    with patch.object(runtime, 'submit', return_value='preview-job') as submit:
                        self.assertEqual(runtime.submit_planning_world_preview('source-job', alternative_ids=ids), 'preview-job')
                    submit.assert_called_once()
                    submitted_kind, request_path = submit.call_args.args
                    request = read_json(request_path)
                    self.assertEqual(submitted_kind, 'planning_world_preview')
                    self.assertEqual(Path(request['review_path']), review.resolve())
                    self.assertEqual(request['review_sha256'], file_hash(review))
                    self.assertEqual(request['alternative_ids'], ids)
                    self.assertEqual(runtime.store.summary()['feedback_records'], 0)
                    self.assertEqual(runtime.store.summary()['checkpoints'], 0)
                finally:
                    runtime.close(wait=True)

    def test_unfinished_wrong_kind_missing_pin_and_tampered_sources_do_not_queue(self):
        for mode in ('unfinished', 'wrong_kind', 'missing_pin', 'tampered', 'missing_file'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                runtime = DesktopRuntime(Path(tmp)/'memory', memory_budget_mb=2048)
                try:
                    review = self.source_job(runtime,
                        kind='world_pilot' if mode == 'wrong_kind' else 'planning_collection',
                        status='running' if mode == 'unfinished' else 'completed',
                        pin=mode != 'missing_pin')
                    if mode == 'tampered':
                        review.write_bytes(review.read_bytes()+b' ')
                    elif mode == 'missing_file':
                        review.unlink()
                    with patch.object(runtime, 'submit') as submit, self.assertRaises((ValueError, OSError)):
                        runtime.submit_planning_world_preview('source-job')
                    submit.assert_not_called()
                finally:
                    runtime.close(wait=True)

    def request(self, root):
        review = root/'source files'/'design-massing.json'
        write_json(review, {'source_snapshot': 'unchanged original review'})
        path = root/'preview.json'
        write_json(path, {'version': 'planning-world-preview-v1',
            'review_path': 'source files/design-massing.json', 'review_sha256': file_hash(review)})
        return review, {'version': 'desktop-worker-v1', 'kind': 'planning_world_preview',
            'config_path': str(path), 'config_sha256': file_hash(path),
            'output_directory': str(root/'new output'), 'progress_path': str(root/'progress.json'),
            'cancel_path': str(root/'cancel')}

    def test_worker_resolves_review_relative_to_request_and_delegates_to_exporter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review, request = self.request(root)
            expected = {'status': 'conditional_world_previews_exported', 'worlds': [],
                'training_labels_generated': 0, 'world_placement_eligible': False}
            with patch('voxel_mapper.planning_world_preview.run', return_value=expected) as export:
                result = _worker(request)
            self.assertEqual(result, expected)
            export.assert_called_once()
            config, output = export.call_args.args
            self.assertEqual(Path(config['review_path']), review.resolve())
            self.assertEqual(config['review_sha256'], file_hash(review))
            self.assertEqual(output, root/'new output')
            self.assertFalse(export.call_args.kwargs['cancelled']())
            self.assertTrue(callable(export.call_args.kwargs['progress']))

    def test_queued_review_changed_before_worker_refuses_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review, request = self.request(root)
            review.write_bytes(review.read_bytes()+b' ')
            with self.assertRaises(ValueError):
                _worker(request)
            self.assertFalse((root/'new output').exists())

    def window(self, row):
        window = DesktopWindow.__new__(DesktopWindow)
        window.jobs = Mock()
        window.jobs.selection.return_value = (row['id'],)
        window.last_snapshot = {'jobs': [row]}
        window.status = Mock()
        window.runtime = Mock()
        window.runtime.submit_planning_world_preview.return_value = 'new-preview'
        window.planning_world_export = Mock()
        window._error = Mock()
        window._background = lambda action, success, failure=None: success(action())
        return window

    def test_ui_queues_selected_source_job_in_background(self):
        window = self.window({'id': 'completed-source', 'kind': 'planning_collection', 'status': 'completed'})
        window._submit_planning_world_preview()
        window.runtime.submit_planning_world_preview.assert_called_once_with('completed-source')
        window._error.assert_not_called()
        self.assertEqual(window.select_when_visible, 'new-preview')

    def test_open_world_uses_choice_page_without_selecting_a_spacing_interpretation(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            (output/'index.html').write_text('<a href="clear-gap.mcworld">World</a>', encoding='utf-8')
            window = self.window({'id': 'preview', 'kind': 'planning_world_preview',
                'status': 'completed', 'output_directory': str(output)})
            with patch('voxel_mapper.desktop_app.os.startfile', create=True) as startfile:
                window._open_job_output('park.mcworld')
            window._error.assert_not_called()
            import os
            if os.name == 'nt':
                startfile.assert_called_once_with(str(output/'index.html'))
            else:
                window.status.set.assert_called_once_with('Output: '+str(output/'index.html'))


if __name__ == '__main__':
    unittest.main()
