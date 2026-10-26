"""Original text context prevents a building name becoming an invented plaza."""
import copy
from concurrent.futures import CancelledError
import hashlib
import json
import unittest

import pymupdf
from shapely.geometry import shape

from voxel_mapper import ordinary_surfaces, planning_outline_semantics as semantics
from voxel_mapper import planning_surface_footprints as surfaces, planning_area_layout
from test_planning_area_world_preview import source_layout


def fixture(*, suffix='TAVERN', building=True, material=True, hidden=False,
            position=(160,142), fontsize=10, fontname='helv', color=(0,0,0),
            duplicate=False, rotation=0, head='COURTYARD', building_text='building'):
    doc=pymupdf.open();page=doc.new_page(width=500,height=350)
    page.draw_rect((100,80,350,230))
    page.insert_text((150,130),head,fontsize=10)
    if suffix:
        page.insert_text(position,suffix,fontsize=fontsize,fontname=fontname,color=color)
        if duplicate:page.insert_text(position,'INN',fontsize=fontsize)
    if hidden:page.draw_rect((155,131,220,145),fill=(1,1,1),color=None)
    if material:page.insert_text((150,170),'brick',fontsize=10)
    if building:page.insert_text((150,190),building_text,fontsize=10)
    page.set_rotation(rotation)
    sha=hashlib.sha256(doc.tobytes()).hexdigest()
    _,_,report=ordinary_surfaces.page_candidates(page,sha,1)
    inventory=report['source_outline_inventory']
    return doc,page,sha,inventory


class PlanningNameContextTests(unittest.TestCase):
    def analyze(self,**kwargs):
        doc,page,sha,inventory=fixture(**kwargs);self.addCleanup(doc.close)
        associations=semantics.page_candidates(page,sha,1,inventory)
        result=surfaces.page_candidates(page,sha,1,inventory,associations)
        return associations,result

    def test_visible_name_suffix_retain_explicit_building_and_withhold_floor(self):
        associations,result=self.analyze()
        self.assertEqual(len(associations['outlines']),1)
        outline=associations['outlines'][0]
        self.assertEqual(outline['status'],'visible_label_enclosure_hint')
        self.assertEqual(outline['source_role_hint'],'building')
        label=next(r for r in associations['labels'] if r['text']=='COURTYARD')
        self.assertEqual(label['status'],'qualified_building_name_withheld')
        context=label['name_context']
        self.assertEqual(context['name_text'],'COURTYARD TAVERN')
        self.assertEqual(context['candidate_id'],outline['candidate_id'])
        self.assertEqual(context['suffix']['glyph_screen']['status'],'raster_consistent_candidate')
        self.assertTrue(shape(context['suffix']['geometry_pdf_native']).is_valid)
        self.assertEqual(outline['excluded_name_label_ids'],[label['id']])
        self.assertEqual(result['candidates'],[])
        self.assertTrue(result['analysis_complete'])
        self.assertFalse(associations['physical_identity_verified'])
        self.assertEqual(result['training_labels_generated'],0)
        self.assertFalse(result['model_weights_updated'])

    def test_literal_courtyard_and_brick_already_combine_without_name_suffix(self):
        associations,result=self.analyze(suffix=None,building=False)
        self.assertEqual(associations['outlines'][0]['source_role_hint'],'plaza')
        self.assertEqual(len(result['candidates']),1)
        self.assertEqual(result['candidates'][0]['source_role_hint'],'plaza')
        self.assertEqual(result['candidates'][0]['surface'],'brick')

    def test_separate_inline_text_shows_keep_the_same_name_qualification(self):
        associations,result=self.analyze(position=(216,130))
        self.assertEqual(associations['summary']['qualified_name_labels'],1)
        self.assertEqual(associations['outlines'][0]['source_role_hint'],'building')
        self.assertEqual(result['candidates'],[])

    def test_name_alone_neither_infers_building_nor_authorizes_paving(self):
        associations,result=self.analyze(building=False)
        self.assertEqual(associations['outlines'],[])
        self.assertEqual(result['candidates'],[])
        self.assertEqual(result['boundary_decisions'][0]['reason'],
            'building_name_context_requires_interpretation')

    def test_qualified_name_retains_printed_states_and_cannot_bypass_conflicts(self):
        for building_text,expected in (('Proposed Building','mixed_printed_states_withheld'),
                ('building','visible_label_enclosure_hint')):
            associations,result=self.analyze(head='EXISTING COURTYARD',
                position=(150,142),building_text=building_text)
            self.assertEqual(associations['summary']['qualified_name_labels'],1)
            outline=associations['outlines'][0]
            self.assertEqual(outline['status'],expected)
            self.assertIn('existing',outline['printed_states'])
            self.assertEqual(result['candidates'],[])
        doc,page,sha,inventory=fixture(head='EXISTING COURTYARD',position=(150,142))
        self.addCleanup(doc.close);associations=semantics.page_candidates(page,sha,1,inventory)
        association=associations['outlines'][0]
        labels=[r for r in associations['labels'] if r['id'] in association['label_ids']]
        evidence={'kind':'coarse_building','source_outline':inventory['records'][0],
            'semantic_evidence':{'association':association,'labels':labels}}
        self.assertEqual(planning_area_layout._semantics(evidence,sha,1)[2],{'existing'})
        # A re-signed label cannot use name exclusion to discard a printed state.
        label=labels[0];label['text']='Proposed Building';label['claim']=semantics.claim(label['text'])
        with self.assertRaisesRegex(ValueError,'Conflicting source'):
            planning_area_layout._semantics(evidence,sha,1)

    def test_hidden_or_ambiguous_suffix_does_not_remove_real_role_conflict(self):
        for kwargs in ({'hidden':True},{'duplicate':True}):
            with self.subTest(kwargs=kwargs):
                associations,result=self.analyze(**kwargs)
                self.assertEqual(associations['outlines'][0]['status'],'conflicting_source_roles_withheld')
                self.assertEqual(associations['summary']['qualified_name_labels'],0)
                self.assertEqual(result['candidates'],[])
                decision=result['boundary_decisions'][0]
                self.assertEqual(set(decision['semantic_context']['label_texts']),{'COURTYARD','building'})

    def test_distant_mismatching_and_cross_boundary_words_do_not_qualify(self):
        for kwargs in ({'position':(150,215)},{'position':(330,142)},
                       {'fontsize':16,'position':(160,150)},{'fontname':'cour'},{'color':(1,0,0)},
                       {'suffix':'tavern'},{'suffix':'Path'}):
            with self.subTest(kwargs=kwargs):
                associations,result=self.analyze(**kwargs)
                self.assertEqual(associations['summary']['qualified_name_labels'],0)
                self.assertEqual(associations['outlines'][0]['status'],'conflicting_source_roles_withheld')
                self.assertEqual(result['candidates'],[])

    def test_nested_enclosures_do_not_use_name_context_to_select_one(self):
        doc,page,sha,inventory=fixture();self.addCleanup(doc.close)
        page.draw_rect((90,70,360,240));sha=hashlib.sha256(doc.tobytes()).hexdigest()
        _,_,report=ordinary_surfaces.page_candidates(page,sha,1)
        result=semantics.page_candidates(page,sha,1,report['source_outline_inventory'])
        self.assertEqual(result['outlines'],[])
        self.assertEqual(result['summary']['qualified_name_labels'],0)
        self.assertTrue(all(r['status']=='ambiguous_source_enclosures_withheld' for r in result['labels']))

    def test_context_work_and_suffix_quotas_withhold_complete_analysis(self):
        doc,page,sha,inventory=fixture(duplicate=True);self.addCleanup(doc.close)
        for options,reason in (({'max_name_context_checks':1},'name_context_work_budget_exceeded'),
                ({'max_name_context_suffixes':1},'name_context_suffix_budget_exceeded')):
            with self.subTest(options=options):
                result=semantics.page_candidates(page,sha,1,inventory,options=options)
                self.assertFalse(result['inventory_complete'])
                self.assertEqual(result['outlines'],[])
                self.assertEqual(result['reason'],reason)

    def test_rotation_replay_cancellation_and_original_source_pins(self):
        for rotation in (0,90):
            doc,page,sha,inventory=fixture(rotation=rotation);self.addCleanup(doc.close)
            before=json.dumps(inventory,sort_keys=True);data=doc.tobytes(no_new_id=True)
            first=semantics.page_candidates(page,sha,1,inventory)
            self.assertEqual(first['summary']['qualified_name_labels'],1)
            self.assertEqual(first,semantics.page_candidates(page,sha,1,inventory))
            self.assertEqual(doc.tobytes(no_new_id=True),data)
            self.assertEqual(json.dumps(inventory,sort_keys=True),before)
            self.assertEqual(page.rotation,rotation)
            with self.assertRaises(CancelledError):
                semantics.page_candidates(page,sha,1,inventory,cancelled=lambda:True)

    def test_standalone_layout_cannot_reuse_a_qualified_name_as_literal_role(self):
        layout=source_layout();evidence=copy.deepcopy(layout['candidates'][0]['source_evidence'][0])
        label=evidence['semantic_evidence'].get('labels',[evidence['semantic_evidence'].get('label')])[0]
        label['status']='qualified_building_name_withheld'
        with self.assertRaisesRegex(ValueError,'Visible whole source label'):
            planning_area_layout._semantics(evidence,layout['document_sha256'],layout['page'])

    def test_building_reload_requires_retained_visible_name_context_witnesses(self):
        doc,page,sha,inventory=fixture();self.addCleanup(doc.close)
        result=semantics.page_candidates(page,sha,1,inventory)
        association=result['outlines'][0]
        labels=[r for r in result['labels'] if r['id'] in association['label_ids']]
        evidence={'kind':'coarse_building','source_outline':inventory['records'][0],
            'semantic_evidence':{'association':association,'labels':labels}}
        self.assertEqual(planning_area_layout._semantics(evidence,sha,1)[0],'building')
        for change in ('missing','suffix','visibility','scope'):
            with self.subTest(change=change):
                modified=json.loads(json.dumps(evidence));a=modified['semantic_evidence']['association']
                if change=='missing':a['excluded_name_contexts']=[]
                else:
                    suffix=a['excluded_name_contexts'][0]['name_context']['suffix']
                    if change=='suffix':suffix['text']='PATH'
                    elif change=='visibility':suffix['glyph_screen']['status']='withheld'
                    else:suffix['geometry_pdf_native']['coordinates'][0][0][0]=450
                with self.assertRaises(ValueError):planning_area_layout._semantics(modified,sha,1)


if __name__=='__main__':unittest.main()
