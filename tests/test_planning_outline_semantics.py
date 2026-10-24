import copy
from concurrent.futures import CancelledError
import hashlib
import json
import unittest
from unittest.mock import patch

import pymupdf

from voxel_mapper import ordinary_surfaces
from voxel_mapper import planning_outline_semantics as semantics


def fixture(labels=('Container',), *, nested=False, hole=False, outside=False, covered=False, rotation=0):
    doc=pymupdf.open();page=doc.new_page(width=700,height=500)
    if hole:
        drawing=page.new_shape();drawing.draw_rect((30,30,330,300));drawing.draw_rect((70,70,270,230))
        drawing.finish(fill=(.7,.7,.7),color=None,even_odd=True);drawing.commit()
    else:
        page.draw_rect((30,30,330,300))
        if nested:page.draw_rect((50,50,310,270))
    for index,text in enumerate(labels):
        page.insert_text((400 if outside else 90,110+35*index),text,fontsize=10)
    if covered:page.draw_rect((80,90,250,120),fill=(1,1,1),color=None)
    page.set_rotation(rotation);sha=hashlib.sha256(doc.tobytes()).hexdigest()
    _,_,report=ordinary_surfaces.page_candidates(page,sha,1)
    return doc,page,sha,report['source_outline_inventory']


class PlanningOutlineSemanticsTests(unittest.TestCase):
    def analyze(self,labels=('Container',),**kwargs):
        doc,page,sha,inventory=fixture(labels,**kwargs);self.addCleanup(doc.close)
        return semantics.page_candidates(page,sha,1,inventory),inventory

    def test_visible_label_binds_one_source_outline_without_physical_acceptance(self):
        result,inventory=self.analyze()
        self.assertEqual(result['summary']['associated_outline_hints'],1)
        outline=result['outlines'][0]
        self.assertEqual(outline['source_role_hint'],'building')
        self.assertEqual(outline['source_record_sha256'],inventory['records'][0]['source_record_sha256'])
        self.assertFalse(outline['component_footprints_resolved'])
        self.assertFalse(outline['physical_identity_verified'])
        self.assertFalse(result['world_placement_eligible'])
        self.assertEqual(result['training_labels_generated'],0)
        self.assertFalse(result['model_weights_updated'])
        self.assertIsNone(result['geometric_accuracy'])

    def test_multiple_component_labels_are_one_shared_enclosure_not_component_footprints(self):
        result,_=self.analyze(('Container','Container','Container'))
        self.assertEqual(result['summary']['associated_outline_hints'],1)
        self.assertEqual(result['summary']['shared_component_enclosures'],1)
        outline=result['outlines'][0]
        self.assertEqual(outline['status'],'shared_component_label_enclosure_hint')
        self.assertEqual(outline['component_label_count'],3)
        self.assertFalse(outline['component_footprints_resolved'])

    def test_nested_enclosures_are_never_resolved_using_smallest_or_nearest(self):
        result,_=self.analyze(nested=True)
        self.assertEqual(result['summary']['associated_outline_hints'],0)
        self.assertEqual(result['labels'][0]['status'],'ambiguous_source_enclosures_withheld')
        self.assertGreater(len(result['labels'][0]['candidate_ids']),1)

    def test_unbound_and_hole_labels_cannot_be_assigned_to_nearby_geometry(self):
        for kwargs in ({'outside':True},{'hole':True}):
            with self.subTest(kwargs=kwargs):
                result,_=self.analyze(**kwargs)
                self.assertEqual(result['summary']['associated_outline_hints'],0)
                self.assertEqual(result['labels'][0]['candidate_ids'],[])

    def test_hidden_native_label_does_not_supply_a_role(self):
        result,_=self.analyze(covered=True)
        self.assertEqual(result['summary']['associated_outline_hints'],0)
        self.assertEqual(result['labels'][0]['status'],'glyph_visibility_withheld')

    def test_building_path_and_plaza_claims_do_not_override_conflicting_roles(self):
        for labels in (('Container','Path'),('Path','Plaza'),('Tree','Building')):
            with self.subTest(labels=labels):
                result,_=self.analyze(labels)
                self.assertEqual(result['summary']['associated_outline_hints'],0)
                self.assertEqual(result['outlines'][0]['status'],'conflicting_source_roles_withheld')

    def test_surface_noun_can_support_path_claim_without_inventing_material(self):
        result,_=self.analyze(('Footpath','Paving'))
        self.assertEqual(result['summary']['associated_outline_hints'],1)
        self.assertEqual(result['outlines'][0]['source_role_hint'],'path')
        self.assertNotIn('material',result['outlines'][0])

    def test_mixed_existing_and_proposed_claims_stay_withheld(self):
        result,_=self.analyze(('Existing Container','Proposed Container'))
        self.assertEqual(result['summary']['associated_outline_hints'],0)
        self.assertEqual(result['outlines'][0]['status'],'mixed_printed_states_withheld')
        self.assertEqual(result['outlines'][0]['printed_states'],['existing','proposed'])

    def test_literal_legend_context_cannot_become_a_building_hint(self):
        result,_=self.analyze(('Legend','Building'))
        self.assertEqual(result['summary']['associated_outline_hints'],0)
        self.assertEqual(result['outlines'][0]['status'],'annotation_context_withheld')

    def test_tree_role_remains_vegetation_without_building_or_path_promotion(self):
        result,_=self.analyze(('Tree',))
        self.assertEqual(result['outlines'][0]['source_role_hint'],'vegetation')
        self.assertFalse(result['outlines'][0]['world_placement_eligible'])

    def test_parser_accepts_standalone_nouns_and_rejects_prose_or_dimensions(self):
        for text in ('No building','Building to be demolished','Path width 2m','Container 12m',
                     'Proposed Ground Floor Plan','Trees to be removed hatched thus','Existing buildings to be'):
            with self.subTest(text=text):self.assertIsNone(semantics.claim(text))
        self.assertEqual(semantics.claim('Proposed Shipping Container')['printed_state'],'proposed')
        self.assertEqual(semantics.claim('Courtyard')['role'],'plaza')

    def test_record_mutation_duplicate_identity_and_wrong_source_are_rejected(self):
        doc,page,sha,inventory=fixture();self.addCleanup(doc.close)
        wrong=copy.deepcopy(inventory);wrong['records'][0]['candidate']['geometry']['coordinates'][0][0][0]+=10
        with self.assertRaisesRegex(ValueError,'source-bound'):semantics.page_candidates(page,sha,1,wrong)
        wrong=copy.deepcopy(inventory);wrong['records'].append(copy.deepcopy(wrong['records'][0]))
        with self.assertRaises(ValueError):semantics.page_candidates(page,sha,1,wrong)
        with self.assertRaises(ValueError):semantics.page_candidates(page,'a'*64,1,inventory)
        wrong=copy.deepcopy(inventory);wrong['inventory_complete']=False
        with self.assertRaises(ValueError):semantics.page_candidates(page,sha,1,wrong)

    def test_limits_are_lower_only_and_exhaustion_withholds_outline_hints(self):
        doc,page,sha,inventory=fixture(('Container','Container'));self.addCleanup(doc.close)
        for options in ({'max_labels':True},{'max_labels':129},{'bad':1},{'max_output_bytes':10}):
            with self.subTest(options=options),self.assertRaises(ValueError):
                semantics.page_candidates(page,sha,1,inventory,options=options)
        for options in ({'max_labels':1},{'max_checks':1}):
            result=semantics.page_candidates(page,sha,1,inventory,options=options)
            self.assertEqual(result['status'],'source_label_associations_withheld')
            self.assertFalse(result['inventory_complete'])
            self.assertEqual(result['summary']['associated_outline_hints'],0)

    def test_rotation_preserves_source_geometry_and_deterministic_hashes(self):
        doc,page,sha,inventory=fixture(rotation=90);self.addCleanup(doc.close)
        first=semantics.page_candidates(page,sha,1,inventory)
        second=semantics.page_candidates(page,sha,1,json.loads(json.dumps(inventory)))
        self.assertEqual(first['summary']['associated_outline_hints'],1)
        self.assertEqual(json.dumps(first,sort_keys=True),json.dumps(second,sort_keys=True))
        self.assertEqual(page.rotation,90)

    def test_output_budget_never_returns_partial_hints_as_completed_analysis(self):
        doc,page,sha,inventory=fixture();self.addCleanup(doc.close)
        with patch.object(semantics.glyph_visibility,'screen_architectural_span',return_value={
                'status':'raster_consistent_candidate','diagnostic':'x'*20000}):
            result=semantics.page_candidates(page,sha,1,inventory,options={'max_output_bytes':16384})
        self.assertFalse(result['inventory_complete'])
        self.assertEqual(result['reason'],'semantic_output_budget_exceeded')
        self.assertEqual(result['outlines'],[])
        self.assertLessEqual(len(json.dumps(result).encode()),16384)

    def test_native_inventory_and_original_page_are_unchanged_by_association(self):
        doc,page,sha,inventory=fixture();self.addCleanup(doc.close)
        before=json.dumps(inventory,sort_keys=True);source=doc.tobytes(no_new_id=True)
        semantics.page_candidates(page,sha,1,inventory)
        self.assertEqual(json.dumps(inventory,sort_keys=True),before)
        self.assertEqual(doc.tobytes(no_new_id=True),source)

    def test_cancellation_never_returns_partial_success(self):
        doc,page,sha,inventory=fixture(('Container','Container'));self.addCleanup(doc.close)
        calls=[0]
        def cancelled():calls[0]+=1;return calls[0]>3
        with self.assertRaises(CancelledError):
            semantics.page_candidates(page,sha,1,inventory,cancelled=cancelled)


if __name__=='__main__':unittest.main()
