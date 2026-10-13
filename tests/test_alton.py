import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from voxel_mapper.alton import acquire_alton, download_pdf
from voxel_mapper.alton_registration import fit_axis_labels


class AltonTests(unittest.TestCase):
    def labels(self):
        return [{'axis': axis, 'position': i*100, 'value': base+i*20}
                for axis, base in [('E', 407500), ('N', 343000)] for i in range(4)]

    def test_alignment_is_bounded_hypothesis_never_verified_geometry(self):
        report = fit_axis_labels(self.labels(), [-1.91, 52.97, -1.86, 53.01])
        self.assertEqual(report['status'], 'native_label_alignment_hypothesis')
        self.assertFalse(report['registration_verified'])
        self.assertEqual(report['world_geometry_additions'], 0)
        self.assertAlmostEqual(report['axes']['E']['slope'], .2)
        self.assertEqual(fit_axis_labels(self.labels(), [-.52, 51.4, -.5, 51.42])['status'], 'unavailable')

    def test_bad_label_is_rejected_by_withheld_checks(self):
        labels = self.labels()
        labels[1]['value'] += 5
        self.assertEqual(fit_axis_labels(labels, [-1.91, 52.97, -1.86, 53.01])['status'], 'unavailable')

    def test_shifted_border_label_is_excluded_without_relaxing_residual(self):
        labels = [{'axis': axis, 'position': i*100, 'value': base+i*20}
                  for axis, base in [('E', 407500), ('N', 343000)] for i in range(7)]
        labels[6]['position'] -= 6
        report = fit_axis_labels(labels, [-1.91, 52.97, -1.86, 53.01])
        self.assertEqual(report['status'], 'native_label_alignment_hypothesis')
        self.assertEqual(len(report['axes']['E']['excluded_label_origins']), 1)
        self.assertLess(report['axes']['E']['max_withheld_error_nominal_m'], .01)

    def test_unexpected_host_is_rejected_before_network(self):
        with patch('requests.Session') as session:
            with self.assertRaises(ValueError):
                download_pdf(session, 'https://other.example/plan.pdf')
            session.get.assert_not_called()

    def test_recorded_transport_requires_same_resource_and_historical_pin(self):
        from unittest.mock import MagicMock
        url = 'https://publicaccess.staffsmoorlands.gov.uk/plan?id=1'
        transport = url.replace('https:', 'http:')
        payload = b'%PDF-historical-original'
        pin = hashlib.sha256(payload).hexdigest()
        session = MagicMock()
        response = session.get.return_value
        response.status_code = 200
        response.iter_content.return_value = [payload]
        self.assertEqual(download_pdf(session, url, transport_url=transport,
                                      expected_sha256=pin), payload)
        session.get.assert_called_once_with(transport, timeout=(10, 30),
                                            stream=True, allow_redirects=False)
        response.close.assert_called_once()
        session.reset_mock()
        for alternative, checksum in [(transport, None), (transport, 'invalid'),
                                      (transport+'2', pin),
                                      ('http://other.example/plan?id=1', pin),
                                      (transport+'#fragment', pin)]:
            with self.subTest(alternative=alternative, checksum=checksum):
                with self.assertRaises(ValueError):
                    download_pdf(session, url, transport_url=alternative,
                                 expected_sha256=checksum)
                session.get.assert_not_called()

    def test_recorded_transport_rejects_changed_bytes_and_closes_response(self):
        from unittest.mock import MagicMock
        url = 'https://publicaccess.staffsmoorlands.gov.uk/plan'
        session = MagicMock()
        response = session.get.return_value
        response.status_code = 200
        response.iter_content.return_value = [b'%PDF-changed']
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            download_pdf(session, url, transport_url=url.replace('https:', 'http:'),
                         expected_sha256=hashlib.sha256(b'%PDF-original').hexdigest())
        response.close.assert_called_once()

    def test_acquisition_passes_recorded_transport_and_preserves_pin(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = b'%PDF-pinned'
            pin = hashlib.sha256(payload).hexdigest()
            entry = dict(url='https://publicaccess.staffsmoorlands.gov.uk/plan?id=1',
                         transport_url='http://publicaccess.staffsmoorlands.gov.uk/plan?id=1',
                         title='Existing elevation', role='elevations', sha256=pin)
            discovery = {'status': 'checked', 'documents': [entry], 'failures': []}
            with patch('voxel_mapper.alton_discovery.discover_attachments', return_value=discovery), \
                 patch('voxel_mapper.alton_discovery.merge_discovered', return_value=[entry]), \
                 patch('voxel_mapper.alton.download_pdf', return_value=payload) as download, \
                 patch('voxel_mapper.council.inspect_pdf', return_value={'pages': []}):
                result = acquire_alton(root, max_documents=1)
            download.assert_called_once_with(unittest.mock.ANY, entry['url'],
                                             transport_url=entry['transport_url'],
                                             expected_sha256=pin)
            self.assertEqual(result['documents'][0]['sha256'], pin)
            self.assertEqual(result['documents'][0]['transport_url'], entry['transport_url'])
            self.assertEqual(result['geometry_records'], [])

    def test_cache_downloads_missing_sections_before_other_uncached_documents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = b'%PDF-test-payload'
            cached = {'url': 'https://publicaccess.staffsmoorlands.gov.uk/cached',
                      'title': 'Cached report', 'role': 'context-report', 'priority': 90,
                      'file': 'cached.pdf', 'sha256': hashlib.sha256(payload).hexdigest()}
            (root/'cached.pdf').write_bytes(payload)
            section = dict(url='https://publicaccess.staffsmoorlands.gov.uk/section',
                           title='373-95-11A Sections AA BB Prop', role='elevations', priority=40)
            site = dict(url='https://publicaccess.staffsmoorlands.gov.uk/site',
                        title='Site Plan', role='site-plan', priority=10)
            discovery = {'status': 'checked', 'documents': [site, section], 'failures': []}
            with patch('voxel_mapper.alton_discovery.discover_attachments', return_value=discovery), \
                 patch('voxel_mapper.alton_discovery.merge_discovered', return_value=[cached, site, section]), \
                 patch('voxel_mapper.alton.download_pdf', return_value=payload) as download, \
                 patch('voxel_mapper.council.inspect_pdf', return_value={'pages': []}):
                result = acquire_alton(root, cache=root, max_documents=3)
            self.assertEqual([call.args[1] for call in download.call_args_list], [section['url'], site['url']])
            self.assertEqual(result['status'], 'checked')
            self.assertEqual(result['missing_download_attempts'], 2)
            self.assertEqual(result['documents'][0]['acquisition_method'], 'hash_checked_cache')
            self.assertEqual(result['documents'][1]['acquisition_method'], 'official_download')
            self.assertEqual(result['geometry_records'], [])

    def test_https_outage_does_not_defer_explicit_pinned_http_transport(self):
        import requests
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = b'%PDF-historical-original'
            entries = [dict(url='https://publicaccess.staffsmoorlands.gov.uk/'+str(i),
                            title=str(i), role='elevations') for i in range(4)]
            entries.append(dict(url='https://publicaccess.staffsmoorlands.gov.uk/pinned',
                                transport_url='http://publicaccess.staffsmoorlands.gov.uk/pinned',
                                sha256=hashlib.sha256(payload).hexdigest(),
                                title='Pinned drawing', role='elevations'))
            discovery = {'status': 'checked', 'documents': entries, 'failures': []}
            with patch('voxel_mapper.alton_discovery.discover_attachments', return_value=discovery), \
                 patch('voxel_mapper.alton_discovery.merge_discovered', return_value=entries), \
                 patch('voxel_mapper.alton.download_pdf', side_effect=[
                     requests.RequestException('HTTPS outage') for _ in range(3)]+[payload]) as download, \
                 patch('voxel_mapper.council.inspect_pdf', return_value={'pages': []}):
                result = acquire_alton(root, max_documents=5)
            self.assertEqual(download.call_count, 4)
            self.assertEqual(result['documents_deferred_council_outage'], 1)
            self.assertEqual(result['documents'][-1]['status'], 'inspected')

    def test_outage_defers_missing_downloads_but_preserves_cached_inspection(self):
        import requests
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = b'%PDF-test-payload'
            (root/'cached.pdf').write_bytes(payload)
            entries = [dict(url='https://publicaccess.staffsmoorlands.gov.uk/'+str(i),
                            title=str(i), role='elevations', priority=40,
                            file=f'missing-{i}.pdf') for i in range(5)]
            entries.append(dict(url='https://publicaccess.staffsmoorlands.gov.uk/cached',
                                title='Cached', role='context-report', priority=90,
                                file='cached.pdf', sha256=hashlib.sha256(payload).hexdigest()))
            discovery = {'status': 'checked', 'documents': entries, 'failures': []}
            with patch('voxel_mapper.alton_discovery.discover_attachments', return_value=discovery), \
                 patch('voxel_mapper.alton_discovery.merge_discovered', return_value=entries), \
                 patch('voxel_mapper.alton.download_pdf', side_effect=requests.ReadTimeout('outage')) as download, \
                 patch('voxel_mapper.council.inspect_pdf', return_value={'pages': []}):
                result = acquire_alton(root, cache=root, max_documents=6)
            self.assertEqual(download.call_count, 3)
            self.assertEqual(result['documents_deferred_council_outage'], 2)
            self.assertEqual(result['documents'][0]['status'], 'inspected')
            self.assertEqual(result['status'], 'partial')
            self.assertEqual(len(result['documents']), 6)

    def test_cache_hash_mismatch_is_not_inspected_or_promoted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalogue = json.loads((Path(__file__).parents[1]/'voxel_mapper/data/alton-planning-catalogue.json').read_text())
            from voxel_mapper.alton import is_park_application
            from voxel_mapper.alton_discovery import merge_discovered
            entries = merge_discovered([e for e in catalogue['entries'] if is_park_application(e)], {'documents': []})
            path = root/entries[0]['file']
            path.parent.mkdir(parents=True)
            path.write_bytes(b'%PDF-corrupted')
            with patch('voxel_mapper.alton_discovery.discover_attachments',
                       return_value={'status': 'checked', 'documents': [], 'failures': []}), \
                 patch('voxel_mapper.alton.download_pdf') as download, \
                 patch('voxel_mapper.council.inspect_pdf') as inspect:
                result = acquire_alton(root, cache=root, max_documents=1)
            download.assert_not_called()
            inspect.assert_not_called()
            self.assertIn('checksum mismatch', result['failures'][0]['reason'])
            self.assertEqual(result['geometry_records'], [])
            self.assertEqual(result['status'], 'partial')

    def test_missing_catalogued_pdf_is_downloaded_and_checked_against_original_pin(self):
        payload = b'%PDF-original'
        entry = dict(url='https://publicaccess.staffsmoorlands.gov.uk/plan',
                     title='Section', role='elevations', file='files/missing.pdf',
                     sha256=hashlib.sha256(payload).hexdigest())
        for downloaded, expected_status in [(payload, 'inspected'), (b'%PDF-changed', 'unavailable')]:
            with self.subTest(expected_status=expected_status), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with patch('voxel_mapper.alton_discovery.discover_attachments',
                           return_value={'status': 'checked', 'documents': [], 'failures': []}), \
                     patch('voxel_mapper.alton_discovery.merge_discovered', return_value=[entry]), \
                     patch('voxel_mapper.alton.download_pdf', return_value=downloaded) as download, \
                     patch('voxel_mapper.council.inspect_pdf', return_value={'pages': []}) as inspect:
                    result = acquire_alton(root, cache=root, max_documents=1)
                download.assert_called_once()
                row = result['documents'][0]
                self.assertEqual(row['status'], expected_status)
                self.assertEqual(row['cache_recovery_reason'], 'catalogued_pdf_missing')
                if expected_status == 'inspected':
                    self.assertEqual(Path(row['local_pdf']).read_bytes(), payload)
                    self.assertEqual(row['acquisition_method'], 'official_download')
                    self.assertEqual(row['hash_provenance'], 'matches_recovered_document')
                else:
                    inspect.assert_not_called()
                    self.assertFalse((root/'planning-documents').exists())
                    self.assertIn('checksum mismatch', row['reason'])

    def test_missing_pdf_outside_cache_is_rejected_without_downloading(self):
        entry = dict(url='https://publicaccess.staffsmoorlands.gov.uk/plan',
                     title='Section', role='elevations', file='../escaped.pdf')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch('voxel_mapper.alton_discovery.discover_attachments',
                       return_value={'status': 'checked', 'documents': [], 'failures': []}), \
                 patch('voxel_mapper.alton_discovery.merge_discovered', return_value=[entry]), \
                 patch('voxel_mapper.alton.download_pdf') as download:
                result = acquire_alton(root, cache=root, max_documents=1)
            download.assert_not_called()
            self.assertIn('escapes corpus', result['documents'][0]['reason'])
