"""Real retained-area replay plus evidence recovery and publication boundaries."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

from voxel_mapper import desktop_area as area
from voxel_mapper.desktop_runtime import DesktopRuntime, _wait

REPO=Path(__file__).resolve().parents[1]


class Response:
    status_code=200
    def __init__(self,data):self.data=data
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def raise_for_status(self):pass
    def iter_content(self,size):yield self.data


class DesktopAreaTests(unittest.TestCase):
    def test_bundle_preserves_transitive_hashes_and_excludes_original_pdfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'portable';manifest=area.build_bundle(REPO,root)
            self.assertEqual(len(manifest['presets']),3)
            for preset in manifest['presets']:
                self.assertEqual(sum(r['external'] for r in preset['files']),0 if preset['id']=='alton-terrain-paths' else 4)
                for row in preset['files']:
                    path=root/row['path']
                    if row['external']:self.assertFalse(path.exists())
                    else:self.assertEqual(area._sha(path),row['sha256'])
            self.assertLess(sum(p.stat().st_size for p in root.rglob('*') if p.is_file()),2_000_000)

    def test_portable_bundle_generates_real_alton_world_with_no_false_planning_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'portable';manifest=area.build_bundle(REPO,data)
            with patch.object(area,'bundle',return_value=(data,manifest)):
                result=area.run('alton-terrain-paths',root/'world')
            self.assertEqual(result['status'],'completed_draft')
            self.assertEqual(result['generated_voxel_records_by_kind']['terrain'],7936)
            self.assertEqual(result['generated_voxel_records_by_kind']['path'],90)
            self.assertEqual(result['readiness']['planning_components_voxelized'],0)
            self.assertTrue((root/'world/park.mcworld').is_file())
            self.assertTrue((root/'world/placement-comparison.svg').is_file())
            self.assertEqual(result['desktop_area']['training_labels_generated'],0)
            self.assertLess(len(json.dumps(result)),100000)
            self.assertEqual(area._sha(root/'world/pilot-report.json'),result['desktop_area']['pilot_report_sha256'])

    def test_actual_isolated_area_worker_remembers_outcome_across_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'memory'
            runtime=DesktopRuntime(directory)
            try:
                jid=runtime.submit_area('alton-terrain-paths')
                job=_wait(runtime,jid,timeout=60)
                self.assertEqual(job['status'],'completed',job.get('error'))
                self.assertEqual(job['kind'],'area_pilot')
                self.assertEqual(runtime.store.summary()['feedback_records'],0)
                self.assertIsNone(runtime.store.setting('active_model'))
            finally:runtime.close(wait=True)
            runtime=DesktopRuntime(directory)
            try:
                self.assertEqual(runtime.store.job(jid)['status'],'completed')
                self.assertIn('area_generation',runtime.store.context(max_characters=10000))
            finally:runtime.close(wait=True)

    def test_missing_plaza_pdf_keeps_diagnostics_and_never_starts_world_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(area,'_download') as download,patch('voxel_mapper.world_pilot.run') as generate:
                with self.assertRaisesRegex(ValueError,'4 original planning PDFs unavailable'):
                    area.run('wicker-plazas-b',root/'world')
            download.assert_not_called();generate.assert_not_called()
            report=json.loads((root/'area-inputs/area-source-report.json').read_text())
            self.assertEqual(report['status'],'awaiting_original_pdfs')
            self.assertEqual(sum(r['status']=='awaiting_original_pdf' for r in report['source_status']),4)
            self.assertFalse(report['physical_acceptance_inferred'])
            self.assertFalse((root/'world').exists())
            model=json.loads((root/'area-inputs/evidence/wicker-shop-projection-model.json').read_text())
            self.assertFalse(model['world_placement_eligible'])

    def test_provider_failure_is_retained_without_guessing_or_silent_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(area,'_download',side_effect=OSError('503 Service Unavailable')):
                with self.assertRaisesRegex(ValueError,'4 original planning PDFs unavailable'):
                    area.run('wicker-plazas-a',root/'world',download_missing=True)
            report=json.loads((root/'area-inputs/area-source-report.json').read_text())
            errors=[r['error'] for r in report['source_status'] if 'error' in r]
            self.assertEqual(len(errors),4)
            self.assertTrue(all('503' in e for e in errors))
            self.assertFalse((root/'world/park.mcworld').exists())

    def test_retained_sources_are_found_by_content_hash_with_arbitrary_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);nested=root/'nested';nested.mkdir()
            pdf=nested/'user renamed drawing.pdf';pdf.write_bytes(b'%PDF-real-test-fixture')
            wanted=area._sha(pdf)
            found=area._find_originals(root,{wanted},lambda:False)
            self.assertEqual(found,{wanted:pdf.resolve()})
            self.assertEqual(area._find_originals(root,{'0'*64},lambda:False),{})

    def test_download_accepts_only_exact_pdf_and_cleans_bad_partial_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'source.pdf';data=b'%PDF-test fixture'
            row={'url':'https://publicaccess.staffsmoorlands.gov.uk/portal/servlets/AttachmentShowServlet?ImageName=1',
                 'sha256':hashlib.sha256(data).hexdigest()}
            with patch('requests.get',return_value=Response(data)) as get:
                area._download(row,target,lambda:False)
                self.assertEqual(target.read_bytes(),data)
                self.assertFalse(get.call_args.kwargs['allow_redirects'])
            target.unlink()
            with patch('requests.get',return_value=Response(b'%PDF-changed')):
                with self.assertRaisesRegex(ValueError,'checksum differs'):area._download(row,target,lambda:False)
            self.assertFalse(target.exists());self.assertFalse(target.with_suffix('.partial').exists())
            with patch('requests.get',return_value=Response(b'<html>not a PDF</html>')):
                with self.assertRaisesRegex(ValueError,'not an original PDF'):area._download(row,target,lambda:False)
            self.assertFalse(target.exists())

    def test_redirect_and_unregistered_host_cannot_supply_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'source.pdf';row={'url':'https://other.test/file.pdf','sha256':'0'*64}
            with patch('requests.get') as get,self.assertRaisesRegex(ValueError,'council attachment'):
                area._download(row,target,lambda:False)
            get.assert_not_called()
            row['url']='https://publicaccess.staffsmoorlands.gov.uk/portal/servlets/AttachmentShowServlet?ImageName=1'
            response=Response(b'%PDF-test');response.status_code=302
            with patch('requests.get',return_value=response),self.assertRaisesRegex(ValueError,'complete PDF'):
                area._download(row,target,lambda:False)
            self.assertFalse(target.exists())

    def test_recorded_transport_fallback_preserves_failed_attempt_and_exact_pdf_pin(self):
        import requests
        with tempfile.TemporaryDirectory() as tmp:
            data=b'%PDF-pinned original';target=Path(tmp)/'source.pdf'
            canonical='https://publicaccess.staffsmoorlands.gov.uk/portal/servlets/AttachmentShowServlet?ImageName=1'
            row={'url':canonical,'transport_url':canonical.replace('https://','http://',1),'sha256':hashlib.sha256(data).hexdigest()}
            with patch('requests.get',side_effect=[requests.HTTPError('503 Service Unavailable'),Response(data)]) as get:
                attempts=area._download(row,target,lambda:False)
            self.assertEqual(len(attempts),2)
            self.assertEqual(attempts[0]['status'],'unavailable')
            self.assertEqual(attempts[1]['status'],'checksum_verified')
            self.assertEqual(attempts[1]['url'],row['transport_url'])
            self.assertEqual(target.read_bytes(),data)
            self.assertEqual(get.call_count,2)

    def test_transport_fallback_cannot_change_attachment_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            row={'url':'https://publicaccess.staffsmoorlands.gov.uk/portal/servlets/AttachmentShowServlet?ImageName=1',
                 'transport_url':'http://publicaccess.staffsmoorlands.gov.uk/portal/servlets/AttachmentShowServlet?ImageName=2','sha256':'0'*64}
            with patch('requests.get') as get,self.assertRaisesRegex(ValueError,'same pinned public attachment'):
                area._download(row,Path(tmp)/'source.pdf',lambda:False)
            get.assert_not_called()

    def test_bundle_tampering_fails_before_a_world_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'portable';manifest=area.build_bundle(REPO,data)
            (data/'docs/evidence/smiler-review/ea-national-dtm.tif').write_bytes(b'changed')
            with patch.object(area,'bundle',return_value=(data,manifest)),self.assertRaisesRegex(ValueError,'Area source changed'):
                area.run('alton-terrain-paths',root/'world')
            self.assertFalse((root/'world').exists())

    def test_paths_cannot_escape_the_portable_input_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            for path in ('../outside','/absolute','C:/outside','dir\\file'):
                with self.assertRaises(ValueError):area._inside(tmp,path)

    def test_cancellation_during_download_removes_partial_without_publishing(self):
        from concurrent.futures import CancelledError
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'source.pdf'
            row={'url':'https://publicaccess.staffsmoorlands.gov.uk/portal/servlets/AttachmentShowServlet?ImageName=1','sha256':'0'*64}
            with patch('requests.get',return_value=Response(b'%PDF-test')),self.assertRaises(CancelledError):
                area._download(row,target,lambda:True)
            self.assertFalse(target.exists());self.assertFalse(target.with_suffix('.partial').exists())


if __name__=='__main__':unittest.main()
