import hashlib
import unittest
import pymupdf
from voxel_mapper.planning_components import claims,page_mentions


class ComponentMentionTests(unittest.TestCase):
    def test_printed_fence_material_and_height_do_not_invent_units(self):
        result=claims('steel post & wire mesh fence 2.00ht')
        self.assertEqual(result['fence_description'],'steel')
        self.assertEqual(result['printed_height_value'],2)
        self.assertEqual(result['height_units'],'unspecified')
        self.assertEqual(claims('timber fence 1.2m ht')['height_units'],'m')
        self.assertEqual(claims('rustic fence ht 1.20')['printed_height_value'],1.2)

    def test_canopy_or_inspection_label_is_not_a_queue_shelter_or_passenger_floor(self):
        self.assertIsNone(claims('edge of canopy'))
        self.assertIsNone(claims('Station Platform Inspection'))
        self.assertEqual(claims('queue canopy')['roles'],['queue'])
        self.assertEqual(claims('Preshow inspection')['level_role'],'inspection; not passenger platform')

    def test_rotated_native_pdf_mentions_have_stable_ids_and_only_suggestions(self):
        pdf=pymupdf.open();page=pdf.new_page(width=300,height=200)
        page.insert_text((30,40),'Queue Line walkways');page.set_rotation(90)
        candidate={'id':'queue-border','geometry':{'type':'LineString','coordinates':[[30,160],[130,160]]}}
        sha=hashlib.sha256(pdf.tobytes()).hexdigest()
        rows,_=page_mentions(page,sha,1,[candidate]);again,_=page_mentions(page,sha,1,[candidate])
        self.assertEqual(rows,again);self.assertEqual(len(rows),1)
        self.assertGreater(rows[0]['label_bounds'][1],150)
        self.assertEqual(rows[0]['nearby_candidate_suggestions'][0]['candidate_id'],'queue-border')
        self.assertFalse(rows[0]['physical_identity_verified'])
        self.assertEqual(rows[0]['world_geometry_additions'],0)
        self.assertEqual(rows[0]['geometry_binding_status'],'unbound');pdf.close()

    def test_mention_budget_is_reported_and_distant_candidates_are_excluded(self):
        pdf=pymupdf.open();page=pdf.new_page(width=1000,height=1000)
        page.insert_text((30,40),'Queue');page.insert_text((30,70),'stairs')
        far={'id':'other','geometry':{'type':'LineString','coordinates':[[900,900],[950,900]]}}
        rows,withheld=page_mentions(page,'a'*64,1,[far],limit=1)
        self.assertEqual(len(rows),1);self.assertEqual(withheld,1)
        self.assertEqual(rows[0]['nearby_candidate_suggestions'],[]);pdf.close()
