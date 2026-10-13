"""Synthetic sources only: these fixtures do not qualify real planning geometry."""
import hashlib
import json
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

import pymupdf

from voxel_mapper.alton_discovery import HOST
from voxel_mapper.planning_archive import import_archive
from voxel_mapper.planning_bulk import Corpus
from voxel_mapper.planning_bundle import (IncompleteBundle, capture_acquisition, create_bundle,
                                          import_bundle, replay_bundle, verify_bundle)
from voxel_mapper.source_archive import checked_archive


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'original-fixtures'
        (self.source / 'files').mkdir(parents=True)
        pdf = pymupdf.open()
        pdf.new_page().insert_text((50, 50), 'SYNTHETIC FIXTURE: existing plan; no geographic controls')
        self.pdf_data = pdf.tobytes()
        pdf.close()
        self.pdf_sha = hashlib.sha256(self.pdf_data).hexdigest()
        self.pdf_member = f'files/{self.pdf_sha}.pdf'
        (self.source / self.pdf_member).write_bytes(self.pdf_data)
        self.application = {'reference': 'SMD/2016/0315',
                            'url': f'https://{HOST}/portal/servlets/ApplicationSearchServlet?PKID=1',
                            'application_context': 'SYNTHETIC FIXTURE, Alton Towers, Farley Lane'}
        html = b'<html>SMD/2016/0315 <a href="javascript:AppBlobImage(\'111\')">Fixture existing site plan</a></html>'
        self.html_sha = hashlib.sha256(html).hexdigest()
        self.html_member = f'files/{self.html_sha}.html'
        self.application.update(cached_page=self.html_member, cached_page_sha256=self.html_sha)
        (self.source / self.html_member).write_bytes(html)
        self.record = {'url': f'https://{HOST}/portal/servlets/AttachmentShowServlet?ImageName=111',
                       'file': self.pdf_member, 'sha256': self.pdf_sha, 'title': 'Fixture existing site plan',
                       'applicationReference': self.application['reference'], 'state': 'existing',
                       'application_context': self.application['application_context']}
        self.catalogue = self.source / 'catalogue.json'
        self.applications = self.source / 'applications.json'
        self.catalogue.write_text(json.dumps({'entries': [self.record]}), encoding='utf-8')
        self.applications.write_text(json.dumps({'applications': [self.application]}), encoding='utf-8')
        self.archive = self.root / 'source-bundle.zip'

    def tearDown(self):
        self.temp.cleanup()

    def create(self, **kwargs):
        return create_bundle(self.source, self.archive, [HOST], catalogues=[self.catalogue],
                             applications=[self.applications],
                             provenance={'evidence_kind': 'fixture', 'origin': 'Synthetic unittest evidence'}, **kwargs)

    def rewrite(self, transform):
        with zipfile.ZipFile(self.archive) as source:
            members = {n: source.read(n) for n in source.namelist()}
        transform(members)
        with zipfile.ZipFile(self.archive, 'w') as target:
            for name, data in members.items():
                item = zipfile.ZipInfo()
                item.filename = name  # Preserve literal unsafe names on Windows, too.
                target.writestr(item, data)
        return hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def test_portable_offline_replay_preserves_originals_and_catalogue_bytes(self):
        made = self.create()
        portable = self.root / 'another-machine'
        portable.mkdir()
        bundle = portable / 'portable.zip'
        shutil.copyfile(self.archive, bundle)
        original_catalogue = self.catalogue.read_bytes()
        original_html = (self.source / self.html_member).read_bytes()
        shutil.rmtree(self.source)
        with patch('requests.sessions.Session.request', side_effect=AssertionError('Network forbidden')):
            report = replay_bundle(bundle, made['archive_sha256'], [HOST], portable / 'corpus', portable / 'inspection')
        self.assertEqual(report['live_downloads'], 0)
        self.assertEqual(report['world_geometry_additions'], 0)
        self.assertEqual(report['sources']['evidence_kind'], 'fixture')
        self.assertEqual(report['application_replay']['parsed_pages'], 1)
        self.assertEqual(report['availability']['download_status'], {'downloaded': 1})
        self.assertEqual(report['exported_inventory']['pages'], 1)
        self.assertEqual((portable / 'corpus' / self.pdf_member).read_bytes(), self.pdf_data)
        self.assertEqual((portable / 'corpus' / self.html_member).read_bytes(), original_html)
        retained = list((portable / 'corpus' / 'bundles').rglob('pdf_catalogue-*.json'))
        self.assertEqual(retained[0].read_bytes(), original_catalogue)
        rows = [json.loads(line) for line in (portable / 'inspection' / 'page-inventory.jsonl').read_text().splitlines()]
        self.assertEqual(rows[0]['document_sha256'], self.pdf_sha)
        self.assertEqual(rows[0]['status'], 'page_inventory_only')
        repacked = create_bundle(portable / 'corpus', portable / 'repacked.zip', [HOST],
                                 catalogues=[portable / 'inspection' / 'replayed-catalogue.json'],
                                 applications=[portable / 'inspection' / 'replayed-applications.json'],
                                 inventories=[portable / 'inspection' / 'page-inventory.jsonl'],
                                 provenance={'evidence_kind': 'fixture', 'origin': 'Portable fixture repack'})
        self.assertEqual(repacked['counts']['retained_pdf_blobs'], 1)
        self.assertEqual(repacked['inspection_inventories'], 1)

    def test_replayed_new_application_reaches_acquisition_and_next_bundle_without_network(self):
        # A reference and attachment absent from the packaged historical seeds.
        from voxel_mapper.alton import acquire_alton
        reference = 'SMD/2099/9999'
        html = (f"<html>{reference} <a href=\"javascript:AppBlobImage('111')\">"
                'Fixture existing site plan</a></html>').encode()
        sha = hashlib.sha256(html).hexdigest()
        self.application.update(reference=reference, cached_page=f'files/{sha}.html',
                                cached_page_sha256=sha)
        (self.source / self.application['cached_page']).write_bytes(html)
        self.record['applicationReference'] = reference
        self.catalogue.write_text(json.dumps({'entries': [self.record]}), encoding='utf-8')
        self.applications.write_text(json.dumps({'applications': [self.application]}), encoding='utf-8')
        bundle = self.create()
        cache, replay, output = (self.root / name for name in ('portable-cache', 'replay', 'generation'))
        replay_bundle(self.archive, bundle['archive_sha256'], [HOST], cache, replay, inspect=False)
        output.mkdir()
        with patch('requests.Session.get', side_effect=AssertionError('Unexpected network access')) as get, \
             patch('voxel_mapper.council.inspect_pdf', return_value={'pages': []}):
            result = acquire_alton(output, cache=cache, application_references=[reference],
                                   planning_catalogue=replay / 'replayed-catalogue.json',
                                   planning_application_catalogue=replay / 'replayed-applications.json')
        get.assert_not_called()
        self.assertEqual(result['applications'], [reference])
        self.assertEqual(len(result['documents']), 1)
        self.assertEqual(result['documents'][0]['sha256'], self.pdf_sha)
        self.assertEqual(result['documents'][0]['acquisition_method'], 'hash_checked_cache')
        self.assertEqual(result['attachment_discovery']['applications'][0]['acquisition_method'], 'hash_checked_cache')
        self.assertEqual(result['geometry_records'], [])
        captured = capture_acquisition(output, output / 'next.zip', [HOST],
                                       origin='Synthetic replay handoff test', evidence_kind='fixture')
        self.assertEqual(captured['counts']['retained_pdf_blobs'], 1)
        self.assertEqual(captured['counts']['retained_application_pages'], 1)
        self.assertEqual(captured['counts']['missing_pdf_blobs'], 0)

    def test_capture_pins_previously_unpinned_replay_attachment(self):
        from voxel_mapper.alton import acquire_alton
        record = {k: v for k, v in self.record.items() if k not in ('sha256', 'file')}
        self.catalogue.write_text(json.dumps({'entries': [record]}), encoding='utf-8')
        output = self.root / 'downloaded-generation'
        output.mkdir()
        with patch('requests.Session.get', side_effect=AssertionError('Unexpected HTML download')), \
             patch('voxel_mapper.alton.download_pdf', return_value=self.pdf_data) as download, \
             patch('voxel_mapper.council.inspect_pdf', return_value={'pages': []}):
            result = acquire_alton(output, cache=self.source,
                                   application_references=[self.application['reference']],
                                   planning_catalogue=self.catalogue,
                                   planning_application_catalogue=self.applications)
        download.assert_called_once()
        self.assertEqual(result['documents'][0]['sha256'], self.pdf_sha)
        captured = capture_acquisition(output, output / 'next.zip', [HOST],
                                       origin='Synthetic unpinned attachment test', evidence_kind='fixture')
        self.assertEqual(captured['counts']['retained_pdf_blobs'], 1)
        self.assertEqual(captured['counts']['missing_pdf_blobs'], 0)
        with zipfile.ZipFile(output / 'next.zip') as archive:
            catalogue_member = next(n for n in archive.namelist() if 'pdf_catalogue-' in n)
            entries = json.loads(archive.read(catalogue_member))['entries']
        self.assertEqual(entries[0]['sha256'], self.pdf_sha)
        self.assertEqual(entries[0]['file'], self.pdf_member)

    def test_replayed_catalogue_validation_rejects_conflicts_and_unsafe_records(self):
        from voxel_mapper.planning_catalogues import load_planning_catalogues
        with self.assertRaisesRegex(ValueError, 'both catalogues'):
            load_planning_catalogues(self.catalogue, None, self.source)
        cases = [
            [{**self.record, 'file': '../outside.pdf'}],
            [{**self.record, 'url': 'https://other.example/plan.pdf'}],
            [self.record, {**self.record, 'sha256': 'a'*64, 'file': 'files/'+ 'a'*64 + '.pdf'}],
            [{**self.record, 'application_context': 'Another site'}],
        ]
        for rows in cases:
            with self.subTest(rows=rows):
                self.catalogue.write_text(json.dumps({'entries': rows}), encoding='utf-8')
                with patch('requests.Session.get') as get, self.assertRaises(ValueError):
                    load_planning_catalogues(self.catalogue, self.applications, self.source)
                get.assert_not_called()
        self.catalogue.write_text(json.dumps({'entries': [self.record]}), encoding='utf-8')
        self.applications.write_text(json.dumps({'applications': [self.application,
                                      {**self.application, 'url': f'https://{HOST}/different'}]}), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Conflicting retained application snapshots'):
            load_planning_catalogues(self.catalogue, self.applications, self.source)

    def test_unchanged_bundle_is_deterministic_and_import_repairs_then_resumes(self):
        first = self.create()
        self.assertEqual(first['archive_sha256'], self.create()['archive_sha256'])
        corpus = Corpus(self.root / 'corpus')
        try:
            report = import_archive(corpus, self.archive, first['archive_sha256'], [HOST])
            self.assertEqual(report['copied_blobs'], 1)
            self.assertEqual(report['copied_application_pages'], 1)
            (corpus.root / self.pdf_member).write_bytes(b'corrupt')
            (corpus.root / self.html_member).write_bytes(b'corrupt')
            report = import_bundle(corpus, self.archive, first['archive_sha256'], [HOST])
            self.assertEqual(report['copied_blobs'], 1)
            self.assertEqual(report['copied_application_pages'], 1)
            report = import_bundle(corpus, self.archive, first['archive_sha256'], [HOST])
            self.assertEqual(report['resumed_blobs'], 1)
            self.assertEqual(report['resumed_application_pages'], 1)
        finally:
            corpus.close()

    def test_original_provenance_receipt_bytes_are_retained_unchanged(self):
        receipt = b'{ "origin" : "Synthetic original receipt", "evidence_kind" : "fixture" }\n'
        made = create_bundle(self.source, self.archive, [HOST], catalogues=[self.catalogue],
                             applications=[self.applications], provenance=receipt)
        with zipfile.ZipFile(self.archive) as archive:
            name = json.loads(archive.read('bundle.json'))['provenance']['member']
            self.assertEqual(archive.read(name), receipt)
        self.assertEqual(verify_bundle(self.archive, made['archive_sha256'], [HOST])['evidence_kind'], 'fixture')

    def test_missing_files_have_explicit_reports_and_never_become_downloaded(self):
        (self.source / self.pdf_member).unlink()
        (self.source / self.html_member).unlink()
        with self.assertRaises(IncompleteBundle) as error:
            self.create()
        self.assertEqual(len(error.exception.report['missing_sources']), 2)
        self.assertFalse(self.archive.exists())
        made = self.create(allow_partial=True)
        with self.assertRaises(IncompleteBundle):
            verify_bundle(self.archive, made['archive_sha256'], [HOST])
        report = replay_bundle(self.archive, made['archive_sha256'], [HOST], self.root / 'corpus', self.root / 'output', allow_partial=True)
        self.assertEqual(report['sources']['counts']['retained_pdf_blobs'], 0)
        self.assertEqual(report['sources']['counts']['missing_application_pages'], 1)
        self.assertEqual(report['availability']['download_status'], {'pending': 1})
        self.assertEqual(report['exported_inventory']['pages'], 0)
        self.assertEqual(report['availability']['retained_blob_issues'][0]['reason'], 'Retained blob missing')

    def test_metadata_only_links_are_diagnostic_and_pending(self):
        data = json.loads(self.catalogue.read_text())
        data['entries'].append({'url': f'https://{HOST}/unhashed-attachment', 'title': 'Fixture metadata only'})
        self.catalogue.write_text(json.dumps(data))
        made = self.create(allow_partial=True)
        report = replay_bundle(self.archive, made['archive_sha256'], [HOST], self.root / 'corpus', self.root / 'output', allow_partial=True)
        self.assertEqual(report['sources']['counts']['metadata_only_records'], 1)
        self.assertEqual(report['availability']['download_status'], {'downloaded': 1, 'pending': 1})

    def test_corrupt_original_is_rejected_in_partial_mode_before_publication(self):
        for member in (self.pdf_member, self.html_member):
            with self.subTest(member=member):
                original = (self.source / member).read_bytes()
                (self.source / member).write_bytes(b'tampered')
                with self.assertRaisesRegex(ValueError, 'Corrupt original'):
                    self.create(allow_partial=True)
                self.assertFalse(self.archive.exists())
                (self.source / member).write_bytes(original)

    def test_outer_pin_and_inner_pdf_html_metadata_hashes_reject_tampering(self):
        for kind in ('pdf', 'html', 'catalogue', 'provenance'):
            with self.subTest(kind=kind):
                made = self.create()
                def change(members):
                    name = {'pdf': self.pdf_member, 'html': self.html_member}.get(kind)
                    if name is None:
                        prefix = 'pdf_catalogue-' if kind == 'catalogue' else 'provenance-'
                        name = next(n for n in members if Path(n).name.startswith(prefix))
                    members[name] = b'tampered'
                new_pin = self.rewrite(change)
                with self.assertRaisesRegex(ValueError, 'Archive checksum'):
                    verify_bundle(self.archive, made['archive_sha256'], [HOST], allow_partial=True)
                corpus = Corpus(self.root / ('corpus-' + kind))
                try:
                    with self.assertRaisesRegex(ValueError, 'checksum'):
                        import_bundle(corpus, self.archive, new_pin, [HOST], allow_partial=True)
                    self.assertEqual(corpus.report()['document_links'], 0)
                    self.assertFalse(list((corpus.root / 'files').iterdir()))
                finally:
                    corpus.close()

    def test_declared_retained_but_absent_blob_stays_missing(self):
        self.create()
        pin = self.rewrite(lambda members: members.pop(self.pdf_member))
        with self.assertRaises(IncompleteBundle):
            verify_bundle(self.archive, pin, [HOST])
        report = verify_bundle(self.archive, pin, [HOST], allow_partial=True)
        self.assertEqual(report['missing_sources'][0]['absence'], 'declared_retained_member_absent')

    def test_unsafe_names_duplicates_symlinks_and_unlisted_members_rejected(self):
        for name in ('../escape', '/absolute', 'C:/absolute', 'files\\escape', 'files/../escape'):
            self.create()
            pin = self.rewrite(lambda members: members.update({name: b'unsafe'}))
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Unsafe'):
                verify_bundle(self.archive, pin, [HOST])
        self.create()
        with zipfile.ZipFile(self.archive, 'a') as archive, warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            archive.writestr('bundle.json', b'{}')
        pin = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            verify_bundle(self.archive, pin, [HOST])
        self.create()
        with zipfile.ZipFile(self.archive, 'a') as archive:
            item = zipfile.ZipInfo('link')
            item.create_system = 3
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(item, '../outside')
        pin = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'links'):
            verify_bundle(self.archive, pin, [HOST])
        self.create()
        pin = self.rewrite(lambda members: members.update({'unexpected.txt': b'unlisted'}))
        with self.assertRaisesRegex(ValueError, 'Unlisted'):
            verify_bundle(self.archive, pin, [HOST])

    def test_archive_and_individual_member_budgets_reject_before_import(self):
        made = self.create()
        with patch('voxel_mapper.source_archive.MAX_ARCHIVE_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'compressed-byte'):
                verify_bundle(self.archive, made['archive_sha256'], [HOST])
        with patch('voxel_mapper.source_archive.MAX_MEMBERS', 1):
            with self.assertRaisesRegex(ValueError, 'member budget'):
                verify_bundle(self.archive, made['archive_sha256'], [HOST])
        with patch('voxel_mapper.planning_bundle.MAX_PDF_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'byte budget'):
                verify_bundle(self.archive, made['archive_sha256'], [HOST])
        with zipfile.ZipFile(self.archive) as archive:
            expanded = sum(i.file_size for i in archive.infolist())
        compressed = self.archive.stat().st_size
        self.assertGreater(expanded, compressed)
        with patch('voxel_mapper.source_archive.MAX_ARCHIVE_BYTES', (expanded + compressed) // 2):
            with self.assertRaisesRegex(ValueError, 'expanded-byte'):
                with checked_archive(self.archive, made['archive_sha256']):
                    self.fail('Budget exceeded')

    def test_host_rejection_and_conflicting_snapshots_do_not_mutate_corpus(self):
        made = self.create()
        corpus = Corpus(self.root / 'corpus')
        try:
            with self.assertRaisesRegex(ValueError, 'HTTPS portals'):
                import_bundle(corpus, self.archive, made['archive_sha256'], ['other.test'])
            self.assertEqual(corpus.report()['document_links'], 0)
            corpus.ingest_applications([{**self.application, 'cached_page_sha256': 'e' * 64,
                                         'cached_page': 'files/' + 'e' * 64 + '.html'}], [HOST])
            with self.assertRaisesRegex(ValueError, 'Conflicting'):
                import_bundle(corpus, self.archive, made['archive_sha256'], [HOST])
            self.assertEqual(corpus.report()['document_links'], 0)
        finally:
            corpus.close()

    def test_packaged_inventory_replays_without_renderer_and_cannot_approve_geometry(self):
        made = self.create()
        first = replay_bundle(self.archive, made['archive_sha256'], [HOST], self.root / 'corpus1', self.root / 'inspection1')
        self.assertEqual(first['exported_inventory']['pages'], 1)
        made = self.create(inventories=[self.root / 'inspection1' / 'page-inventory.jsonl'])
        with patch('voxel_mapper.planning_bulk.Corpus.inspect', side_effect=AssertionError('Renderer forbidden')):
            report = replay_bundle(self.archive, made['archive_sha256'], [HOST], self.root / 'corpus2', self.root / 'inspection2', inspect=False)
        inventory = report['bundled_inspections'][0]
        self.assertEqual(inventory['authority'], 'derived_evidence_only')
        self.assertEqual(inventory['pages'], 1)
        self.assertEqual(inventory['unavailable_original_sha256s'], [])
        path = self.root / 'corpus2' / 'bundles' / made['archive_sha256'] / inventory['member']
        self.assertEqual(path.read_bytes(), (self.root / 'inspection1' / 'page-inventory.jsonl').read_bytes())
        self.assertEqual(report['world_geometry_additions'], 0)
        # The existing genuine geometry gate still fails on annotation/inventory evidence.
        from voxel_mapper.wickerman import acceptance_report
        voxels = self.root / 'voxels.jsonl'
        voxels.write_text('')
        gate = acceptance_report({'documents': []}, {'world': 'fixture baseline'}, voxels)
        self.assertEqual(gate['status'], 'failed_missing_planning_geometry')

    def test_inventory_tampering_and_unbound_source_are_rejected(self):
        made = self.create()
        replay_bundle(self.archive, made['archive_sha256'], [HOST], self.root / 'corpus', self.root / 'inspection')
        path = self.root / 'inspection' / 'page-inventory.jsonl'
        row = json.loads(path.read_text())
        for changes in ({'world_geometry_additions': 1}, {'document_sha256': 'e' * 64},
                        {'local_pdf': 'C:/not-portable/file.pdf'}, {'status': 'accepted'}):
            path.write_text(json.dumps({**row, **changes}) + '\n')
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.create(inventories=[path])
        path.write_text(json.dumps(row) + '\n')
        self.create(inventories=[path])
        pin = self.rewrite(lambda members: members.update({next(n for n in members if n.startswith('inspection/')): b'tampered'}))
        with self.assertRaisesRegex(ValueError, 'checksum'):
            verify_bundle(self.archive, pin, [HOST])

    def test_inventory_is_withheld_when_original_was_removed_or_corrupted(self):
        made = self.create()
        corpus = Corpus(self.root / 'corpus')
        try:
            import_bundle(corpus, self.archive, made['archive_sha256'], [HOST])
            self.assertEqual(corpus.inspect()['inspected_pages'], 1)
            (corpus.root / self.pdf_member).write_bytes(b'changed')
            report = corpus.inspect()
            self.assertEqual(report['inspected_pages'], 0)
            self.assertIn('corrupt', report['inspection_errors'][0]['error'])
            self.assertEqual(corpus.export_inspection(self.root / 'excluded.jsonl')['pages'], 0)
            import_bundle(corpus, self.archive, made['archive_sha256'], [HOST])
            corpus.inspect()
            (corpus.root / self.pdf_member).unlink()
            report = corpus.acquire(offline=True)
            self.assertEqual(report['inspected_pages'], 0)
            self.assertEqual(report['retained_blob_issues'][0]['reason'], 'Retained blob missing')
        finally:
            corpus.close()

    def test_legacy_archive_restores_pinned_application_html_and_reports_missing_pages(self):
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr('metadata/alton-planning-catalogue.json', self.catalogue.read_bytes())
            archive.writestr('metadata/alton-applications.json', self.applications.read_bytes())
            archive.writestr(self.pdf_member, self.pdf_data)
            archive.writestr(self.html_member, (self.source / self.html_member).read_bytes())
        pin = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        corpus = Corpus(self.root / 'corpus')
        try:
            report = import_archive(corpus, self.archive, pin, [HOST])
            self.assertEqual(report['retained_application_pages'], 1)
            self.assertEqual(corpus.report()['application_states'], {'retained': 1})
            self.assertTrue((corpus.root / self.html_member).is_file())
            pin = self.rewrite(lambda members: members.pop(self.html_member))
            with self.assertRaisesRegex(ValueError, 'absent'):
                import_archive(corpus, self.archive, pin, [HOST])
            report = import_archive(corpus, self.archive, pin, [HOST], allow_partial=True)
            self.assertEqual(report['missing_sources'][0]['kind'], 'application_html')
        finally:
            corpus.close()

    def test_capture_retains_newly_acquired_originals_not_only_historical_pins(self):
        (self.source / 'planning-documents').mkdir()
        (self.source / self.pdf_member).replace(self.source / 'planning-documents' / Path(self.pdf_member).name)
        (self.source / 'alton-planning-inspection.json').write_text(json.dumps({'documents': [self.record]}))
        (self.source / 'alton-planning-discovery.json').write_text(json.dumps({'applications': [
            {'reference': self.application['reference'], 'page_sha256': self.html_sha, 'acquisition_method': 'fixture'}]}))
        report = capture_acquisition(self.source, self.archive, [HOST], origin='SYNTHETIC capture test', evidence_kind='fixture')
        self.assertEqual(report['counts']['retained_pdf_blobs'], 1)
        self.assertEqual(report['counts']['retained_application_pages'], 1)
        self.assertGreater(report['counts']['missing_pdf_blobs'], 0)
        self.assertEqual(verify_bundle(self.archive, report['archive_sha256'], [HOST], allow_partial=True)['live_downloads'], 0)

    def test_offline_park_job_uses_bundle_without_live_application_discovery(self):
        from voxel_mapper.park_pipeline import run
        made = self.create()
        job = {'work_directory': 'park-work',
               'acquisition': {'provider': 'alton', 'offline': True, 'official_hosts': [HOST],
                               'retained_archives': [{'file': self.archive.name, 'sha256': made['archive_sha256']}]},
               'drawing_analysis': {'enabled': False}}
        (self.root / 'job.json').write_text(json.dumps(job))
        with patch('requests.sessions.Session.request', side_effect=AssertionError('Network forbidden')):
            state = run(self.root / 'job.json', 'acquire')
        self.assertEqual(state['stages']['discovery']['status'], 'skipped_offline')
        self.assertEqual(state['stages']['retained_archive_0']['copied_application_pages'], 1)
        self.assertEqual(state['stages']['inspection']['inspected_pages'], 1)

    def test_page_budget_reports_uninspected_sources_and_resume_completes_inventory(self):
        pdf = pymupdf.open()
        for number in range(2):
            pdf.new_page().insert_text((50, 50), f'SYNTHETIC second PDF page {number + 1}')
        data = pdf.tobytes()
        pdf.close()
        sha = hashlib.sha256(data).hexdigest()
        member = f'files/{sha}.pdf'
        (self.source / member).write_bytes(data)
        self.catalogue.write_text(json.dumps({'entries': [self.record,
            {**self.record, 'url': f'https://{HOST}/second-fixture', 'file': member, 'sha256': sha}]}))
        made = self.create()
        first = replay_bundle(self.archive, made['archive_sha256'], [HOST], self.root / 'corpus', self.root / 'inspection', max_pages=1)
        self.assertFalse(first['inspection_complete_for_retained_pdfs'])
        self.assertTrue(first['inspection_page_budget_reached'])
        self.assertEqual(first['exported_inventory']['pages'], 1)
        second = replay_bundle(self.archive, made['archive_sha256'], [HOST], self.root / 'corpus', self.root / 'inspection')
        self.assertTrue(second['inspection_complete_for_retained_pdfs'])
        self.assertEqual(second['exported_inventory']['pages'], 3)


if __name__ == '__main__':
    unittest.main()
