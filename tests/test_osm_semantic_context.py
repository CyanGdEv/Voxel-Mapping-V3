import unittest
import pymupdf
from shapely.geometry import box,mapping
from voxel_mapper.osm_semantic_context import map_semantics,review


class SemanticContextTests(unittest.TestCase):
    def fixture(self,page):
        source={'id':'outline','geometry':mapping(box(30,200,250,290))}
        refs=[{'id':'map','map_semantics':map_semantics({'kind':'water','natural':'water','attraction':'water_ride'})}]
        alignment={'alignment_checks':{'hypotheses':[{'held_out_checks':[{'candidate_id':'outline','reference_id':'map','passed':False}]}]}}
        return [source],refs,alignment

    def test_map_tags_do_not_certify_ground_or_roof_boundary(self):
        value=map_semantics({'kind':'building','building':'yes','roof:shape':'gabled','irrelevant':'unused'})
        self.assertEqual(value['family_hint'],'building')
        self.assertEqual(value['source_tags']['roof:shape'],'gabled')
        self.assertNotIn('irrelevant',value['source_tags'])
        self.assertFalse(value['boundary_identity_verified'])
        self.assertIn('unverified',value['boundary_role'])

    def test_visible_contained_role_can_report_conflict_without_replacing_geometry(self):
        with pymupdf.open() as doc:
            page=doc.new_page(width=300,height=300);page.insert_text((50,70),'Roof outline',fontsize=9)
            sources,refs,alignment=self.fixture(page);r=review(page,sources,refs,alignment)
            self.assertEqual(r['reviews'][0]['status'],'annotation_map_family_conflict_hint')
            self.assertEqual(r['reviews'][0]['source_annotation_hints'][0]['boundary_role_hint'],'roof_outline')
            self.assertEqual(r['geometry_replacements'],0);self.assertFalse(r['registration_verified'])
            refs[0]['map_semantics']=map_semantics({'kind':'building','building':'yes'})
            self.assertEqual(review(page,sources,refs,alignment)['reviews'][0]['status'],'same_family_boundary_convention_unverified')

    def test_title_names_hidden_labels_and_nested_containment_do_not_invent_types(self):
        with pymupdf.open() as doc:
            page=doc.new_page(width=300,height=300);page.insert_text((50,70),'Roof Plan',fontsize=9)
            sources,refs,alignment=self.fixture(page)
            alignment['landmark_labels']={'labels':[{'text':'Swiss Cottage','native_label_bounds':[50,220,100,230],'status':'unique_containment_hint'}]}
            r=review(page,sources,refs,alignment)['reviews'][0]
            self.assertEqual(r['status'],'source_boundary_role_unresolved')
            self.assertEqual(r['source_annotation_hints'],[])
            self.assertTrue(r['contained_named_annotation_clues'][0]['name_is_not_a_boundary_type'])
        with pymupdf.open() as doc:
            page=doc.new_page(width=300,height=300);page.insert_text((50,70),'Roof outline',fontsize=9)
            page.draw_rect((40,50,140,75),fill=(1,1,1),color=None)
            sources,refs,alignment=self.fixture(page)
            self.assertEqual(review(page,sources,refs,alignment)['reviews'][0]['source_annotation_hints'],[])

    def test_nested_failed_outlines_do_not_share_one_role_annotation(self):
        with pymupdf.open() as doc:
            page=doc.new_page(width=300,height=300);page.insert_text((50,70),'Roof outline',fontsize=9)
            sources,refs,alignment=self.fixture(page)
            sources.append({'id':'nested','geometry':mapping(box(40,210,230,280))})
            alignment['alignment_checks']['hypotheses'][0]['held_out_checks'].append({'candidate_id':'nested','reference_id':'map','passed':False})
            result=review(page,sources,refs,alignment)
            self.assertTrue(all(not r['source_annotation_hints'] for r in result['reviews']))

    def test_screen_and_pair_limits_are_explicit(self):
        with pymupdf.open() as doc:
            page=doc.new_page(width=300,height=300);page.insert_text((50,70),'Roof outline',fontsize=9)
            sources,refs,alignment=self.fixture(page)
            result=review(page,sources,refs,alignment,max_label_screens=0)
            self.assertEqual(result['deferred_label_screens'],1)
            self.assertEqual(result['reviews'][0]['status'],'source_boundary_role_unresolved')
            with self.assertRaises(ValueError):review(page,sources,refs,alignment,max_pairs=True)

if __name__=='__main__':unittest.main()
