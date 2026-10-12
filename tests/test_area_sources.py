import copy
import hashlib
import json
from pathlib import Path
import unittest

from voxel_mapper.area_sources import bind_associations
from voxel_mapper.area_reconstruction import select_documents


class AreaAssociationTests(unittest.TestCase):
    def setUp(self):
        self.context = 'Alton Towers Air Shop replacement arcade'
        self.url = 'https://portal.test/portal/servlets/ApplicationSearchServlet?PKID=1'
        self.config = {'official_hosts': ['portal.test'], 'areas': [
            {'id': 'valley', 'application_references': []},
            {'id': 'gardens', 'application_references': []}]}
        self.catalogue = {'entries': [
            {'applicationReference': 'A', 'application_context': self.context,
             'discovery_source': self.url, 'title': 'Existing plan'},
            {'applicationReference': 'B', 'application_context': 'Off-site staff accommodation'}]}
        self.association = {'area_id': 'valley', 'application_reference': 'A',
            'context_contains': 'Air Shop', 'application_url': self.url,
            'application_context_sha256': hashlib.sha256(self.context.encode()).hexdigest()}
        self.registry = {'associations': [self.association]}

    def test_pinned_association_selects_only_its_application_and_is_idempotent(self):
        original = copy.deepcopy(self.config)
        bound, audit = bind_associations(self.config, self.catalogue, self.registry)
        self.assertEqual(self.config, original)
        self.assertEqual(bound['areas'][0]['application_references'], ['A'])
        self.assertEqual(bound['areas'][1]['application_references'], [])
        self.assertEqual(len(select_documents(self.catalogue, bound['areas'][0])), 1)
        self.assertEqual(audit['world_geometry_additions'], 0)
        self.assertEqual(bind_associations(bound, self.catalogue, self.registry)[0], bound)

    def test_stale_context_and_wrong_application_page_do_not_expand_selection(self):
        for mutation in ('context', 'page'):
            catalogue = copy.deepcopy(self.catalogue)
            if mutation == 'context':
                catalogue['entries'][0]['application_context'] += ' changed'
            else:
                catalogue['entries'][0]['discovery_source'] += '2'
            bound, audit = bind_associations(self.config, catalogue, self.registry)
            self.assertEqual(bound['areas'][0]['application_references'], [])
            self.assertEqual(len(audit['rejected_associations']), 1)

    def test_official_host_and_location_marker_are_required(self):
        for field, value in [('application_url', 'https://unrelated.test/portal/servlets/ApplicationSearchServlet'),
                             ('application_url', 'https://portal.test/portal/servlets/ApplicationSearchServlet?PKID=wrong'),
                             ('context_contains', ''), ('context_contains', 'Gloomy Wood')]:
            registry = copy.deepcopy(self.registry)
            registry['associations'][0][field] = value
            bound, audit = bind_associations(self.config, self.catalogue, registry)
            self.assertEqual(bound['areas'][0]['application_references'], [])
            self.assertEqual(len(audit['rejected_associations']), 1)

    def test_real_registry_binds_seven_previously_empty_areas(self):
        root = Path(__file__).resolve().parents[1]
        load = lambda path: json.loads((root / path).read_text())
        config = load('examples/alton-resort-area-job.json')
        for area in config['areas']:
            if area.get('application_associations'):
                area['application_references'] = []
                area.pop('application_associations')
        bound, audit = bind_associations(config,
            load('voxel_mapper/data/alton-planning-catalogue.json'),
            load('voxel_mapper/data/alton-area-associations.json'))
        self.assertEqual(len(audit['accepted_associations']), 19)
        self.assertEqual(audit['rejected_associations'], [])
        self.assertEqual(sum(bool(a['application_references']) for a in bound['areas']), 12)
        unresolved = {a['id'] for a in bound['areas'] if not a['application_references']}
        self.assertEqual(unresolved, {'adventure-land', 'gloomy-wood', 'towers-street'})


if __name__ == '__main__':
    unittest.main()
