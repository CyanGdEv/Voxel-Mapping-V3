import unittest
from voxel_mapper.alton_discovery import parse_attachments, document_role, merge_discovered,parse_application_results,search_applications
from voxel_mapper.survey_reference import inspect_reference_notes


class AltonDiscoveryTests(unittest.TestCase):
    def test_search_results_ignore_other_sites_and_external_links(self):
        html='''<table><tr><td><a href="ApplicationSearchServlet?PKID=12">SMD/2024/0064</a></td><td>Ripsaw Cafe, Alton Towers, Farley Lane</td></tr>
        <tr><td><a href="ApplicationSearchServlet?PKID=13">SMD/2024/0001</a></td><td>Other property, Leek</td></tr>
        <tr><td><a href="https://other.example/portal/servlets/ApplicationSearchServlet?PKID=14">SMD/2024/0002</a></td><td>Alton Towers</td></tr></table>'''
        rows,navigation=parse_application_results(html)
        self.assertEqual([r['reference'] for r in rows],['SMD/2024/0064'])
        self.assertIsNone(navigation)
        self.assertTrue(rows[0]['url'].startswith('https://publicaccess.staffsmoorlands.gov.uk/'))

    def test_search_navigation_rejects_external_action_and_oversized_page_count(self):
        html='''<form action="https://other.example"><input name="forward" value="Next"></form>'''
        with self.assertRaises(ValueError):parse_application_results(html)
        with self.assertRaises(ValueError):search_applications(None,None,max_pages=101)

    def test_paginated_search_keeps_partial_results_when_second_page_fails(self):
        import tempfile
        from unittest.mock import MagicMock
        from pathlib import Path
        import requests
        html=b'''<table><tr><td><a href="ApplicationSearchServlet?PKID=12">SMD/2024/0064</a></td><td>Alton Towers, Farley Lane</td></tr></table>
        <form action="ApplicationSearchServlet"><input name="LAST_ROW_ID" value="20"><input name="DIRECTION" value="F"><input name="RECORDS" value="20"><input name="forward" value="Next"></form>'''
        response=MagicMock();response.__enter__.return_value=response;response.status_code=200
        response.iter_content.return_value=[html]
        session=MagicMock();session.post.side_effect=[response,requests.RequestException('offline')]
        with tempfile.TemporaryDirectory() as temporary:
            result=search_applications(session,temporary)
            self.assertEqual(len(result['applications']),1)
            self.assertFalse(result['complete_search'])
            self.assertEqual(len(result['failures']),1)
            self.assertTrue((Path(temporary)/'alton-application-search.json').exists())

    def application(self):
        return {'reference': 'SMD/2022/0556',
                'url': 'https://publicaccess.staffsmoorlands.gov.uk/portal/servlets/ApplicationSearchServlet?PKID=165529',
                'application_context': 'Alton Towers, Farley Lane'}

    def test_legacy_links_are_parsed_without_executing_javascript(self):
        html = '''SMD/2022/0556 <a href="javascript:AppBlobImage('316054');">Existing site plan</a>
        <a href="javascript:AppBlobImage('316054');">duplicate</a>
        <a href="javascript:AppBlobImage('12');evil()">Bad</a>
        <a href="https://other.example/portal/servlets/AttachmentShowServlet?ImageName=99">Bad</a>'''
        documents = parse_attachments(html, self.application())
        self.assertEqual(len(documents), 1)
        self.assertTrue(documents[0]['url'].endswith('ImageName=316054'))
        self.assertEqual(documents[0]['state'], 'existing')

    def test_reference_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            parse_attachments('SMD/2022/0230', self.application())

    def test_ecological_surveys_do_not_displace_coordinate_surveys(self):
        self.assertEqual(document_role('2936 Master Land Survey'), ('topographical-survey', 0))
        self.assertEqual(document_role('Arboricultural Survey and Report')[0], 'context-report')

    def test_portal_drawing_names_with_underscores_and_missing_spaces_are_prioritised(self):
        self.assertEqual(document_role('ATHH-SA-XX-XX-DR-A-0105_Site_Plan_1-500'), ('site-plan',10))
        self.assertEqual(document_role('Boat ride proposed layout'), ('site-plan',10))
        self.assertEqual(document_role('ATPO-SA-FV-ZZ-DR-A-0202-P0.5-Proposed Plans'), ('site-plan',10))
        self.assertEqual(document_role('Marquee and green proposed lanscaping'), ('landscape-plan',20))
        self.assertEqual(document_role('Tree survey')[0], 'context-report')
        self.assertEqual(document_role('Project Ocean - Landscape and Visual Appraisal')[0], 'context-report')
        self.assertEqual(document_role('Habitat Survey')[0], 'context-report')
        self.assertEqual(document_role('Plans'),('unclassified-drawing',50))
        self.assertEqual(document_role('1'),('unclassified-drawing',50))
        self.assertEqual(document_role('Upper Gardens Area plan'),('site-plan',10))

    def test_new_links_do_not_inherit_hash_or_world_verification(self):
        recovered = [{'url': 'old', 'sha256': 'old-hash', 'title': 'Existing site plan', 'applicationReference': 'a'}]
        new = {'url': 'new', 'title': 'Master land survey', 'applicationReference': 'a', 'priority': 0, 'discovery_source': 'page'}
        result = merge_discovered(recovered, {'documents': [new]})
        self.assertEqual(result[0]['url'], 'new')
        self.assertNotIn('sha256', result[0])
        self.assertNotIn('registration_verified', result[0])

    def test_master_survey_reference_is_retained_without_claiming_acquisition(self):
        result = inspect_reference_notes('On Centre Surveys Drawing:2936 MASTER LAND SURVEY\n(15-6-2022).dwg')
        self.assertEqual(result['external_drawing_references'][0]['drawing_number'], '2936')
        self.assertEqual(result['external_drawing_references'][0]['status'], 'referenced_not_acquired')
        self.assertFalse(result['registration_verified'])
