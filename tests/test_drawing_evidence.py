import unittest
from voxel_mapper.drawing_evidence import evidence_candidates, inspection_order


class DrawingEvidenceTests(unittest.TestCase):
    def test_labelled_levels_keep_units_datum_and_proposal_uncertainty(self):
        result=evidence_candidates('PROPOSED FFL: 15.250 m AOD\nExisting water level = 12.7m ODN\nLayer 2\nScale 1:2500\nFFL 1:2500\nFFL 12 ft\nFFL 3e2\nGround level 14.3')
        levels=result['levels']
        self.assertEqual(len(levels),3)
        self.assertEqual(levels[0]['value_candidate'],15.25)
        self.assertEqual(levels[0]['datum_label_candidate'],'AOD')
        self.assertEqual(levels[0]['construction_label'],'proposed')
        self.assertEqual(levels[1]['construction_label'],'existing_label_unverified')
        self.assertIsNone(levels[2]['unit_label_candidate'])
        self.assertTrue(all(v['association_status']=='unplaced_unverified' for v in levels))

    def test_materials_are_contextual_and_mixed_specs_are_not_collapsed(self):
        result=evidence_candidates('Concrete discussed elsewhere\nProposed plaza surface: red concrete and brick paving\nExisting boardwalk deck material: timber\npath finish: resin bound gravel')
        materials=result['materials']
        self.assertEqual({m['material_candidate'] for m in materials},{'concrete','brick','wood','resin_bound_gravel','gravel'})
        self.assertEqual(next(m for m in materials if m['material_candidate']=='concrete')['colour_candidates'],['red'])
        self.assertFalse(any('raw_text' in m for m in materials))
        bounded=evidence_candidates('Water level 12.7 m\nFFL 14.5 m',max_candidates=1)
        self.assertTrue(bounded['truncated']);self.assertEqual(len(bounded['levels']),1)
        with self.assertRaisesRegex(ValueError,'budget'):
            evidence_candidates('a'*500_001)

    def test_category_round_robin_includes_materials_before_repeated_plans(self):
        documents=[{'id':str(i),'title':title,'application_reference':'RU.22/0374'} for i,title in enumerate(
            ['Location Plan','Site Plan','Location Plan B','Materials Schedule','Flood Risk Assessment','Section','Topographic Survey'])]
        titles=[d['title'] for d in inspection_order(documents)[:5]]
        self.assertIn('Materials Schedule',titles)
        self.assertIn('Flood Risk Assessment',titles)
        self.assertIn('Section',titles)
        self.assertIn('Topographic Survey',titles)
