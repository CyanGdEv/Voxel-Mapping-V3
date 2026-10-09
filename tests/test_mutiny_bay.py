import unittest
from voxel_mapper.mutiny_bay import source_inventory, REFERENCES

class MutinyTests(unittest.TestCase):
    def test_area_inventory_keeps_state_and_deduplicates_only_acquisition(self):
        source={'acquired_at':'test','limitations':['Unregistered'], 'documents':[
            {'applicationReference':'SMD/2017/0472','url':'existing','state':'existing'},
            {'applicationReference':'SMD/2017/0473','url':'existing','state':'existing'},
            {'applicationReference':'SMD/2017/0472','url':'proposal','state':'proposed'}]}
        r=source_inventory([{'applicationReference':'SMD/2017/0472','url':'existing','status':'inspected'}],source)
        self.assertEqual(len(r['groups']['courtyard']['documents']),3)
        self.assertEqual(r['groups']['courtyard']['inspected_document_urls'],['existing'])
        self.assertFalse(r['registration_verified'])
        self.assertEqual(r['world_geometry_additions'],0)
        self.assertEqual({d['state'] for d in r['groups']['courtyard']['documents']},{'existing','proposed'})

    def test_retained_inventory_includes_all_nine_application_contexts(self):
        r=source_inventory()
        self.assertEqual({a for g in r['groups'].values() for a in g['applications']},set(REFERENCES))
        self.assertTrue(r['groups']['battle_galleons']['documents'])
        self.assertTrue(r['groups']['sharkbait_replacement']['documents'])
        for g in r['groups'].values():
            self.assertFalse(g['geometry_emitted'])
            for d in g['documents']:
                if d['status']=='retained_inspected':
                    self.assertEqual(len(d['sha256']),64)
                    self.assertFalse(d['registration_verified'])
