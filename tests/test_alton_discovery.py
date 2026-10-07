import unittest
from voxel_mapper.alton_discovery import parse_attachments, document_role, merge_discovered
from voxel_mapper.survey_reference import inspect_reference_notes


class AltonDiscoveryTests(unittest.TestCase):
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
