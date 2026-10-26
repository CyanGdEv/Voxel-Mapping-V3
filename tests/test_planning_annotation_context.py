"""Split native notes cannot become paving or remove known role conflicts."""
import copy
from concurrent.futures import CancelledError
import hashlib
import json
import unittest

import pymupdf

from voxel_mapper import ordinary_surfaces,planning_outline_semantics as semantics
from voxel_mapper import planning_surface_footprints as surfaces,planning_area_layout
from test_planning_area_world_preview import source_layout


def fixture(*,material='stone',extra_role=None,hidden=False,nested=False,rotation=0,
            words=('Path',' lowered',' and',' ground',' graded'),gap=0,font='helv',color=(0,0,0)):
    doc=pymupdf.open();page=doc.new_page(width=700,height=400)
    page.draw_rect((80,70,380,250))
    if nested:page.draw_rect((60,50,400,270))
    x=110
    for i,text in enumerate(words):
        face='helv' if i==0 else font;ink=(0,0,0) if i==0 else color
        page.insert_text((x,120),text,fontsize=10,fontname=face,color=ink)
        x+=pymupdf.get_text_length(text,fontname=face,fontsize=10)+gap
    if material:page.insert_text((110,180),material,fontsize=10)
    if extra_role:page.insert_text((110,210),extra_role,fontsize=10)
    if hidden:page.draw_rect((130,108,250,124),fill=(1,1,1),color=None)
    page.set_rotation(rotation);sha=hashlib.sha256(doc.tobytes()).hexdigest()
    _,_,report=ordinary_surfaces.page_candidates(page,sha,1)
    inventory=report['source_outline_inventory']
    return doc,page,sha,inventory


class PlanningAnnotationContextTests(unittest.TestCase):
    def analyze(self,**kwargs):
        doc,page,sha,inventory=fixture(**kwargs);self.addCleanup(doc.close)
        semantic=semantics.page_candidates(page,sha,1,inventory)
        result=surfaces.page_candidates(page,sha,1,inventory,semantic)
        return semantic,result

    def test_split_note_retains_whole_text_and_cannot_fall_back_to_material_floor(self):
        semantic,result=self.analyze()
        label=next(r for r in semantic['labels'] if r['text']=='Path')
        self.assertEqual(label['status'],semantics.ANNOTATION_WITHHELD)
        context=label['annotation_context']
        self.assertEqual(context['text'],'Path lowered and ground graded')
        self.assertEqual(len(context['parts']),5)
        self.assertTrue(context['all_parts_visible'])
        self.assertFalse(context['positive_role_material_or_state_inferred'])
        self.assertEqual(result['candidates'],[])
        self.assertIn('annotation_fragment_context_withheld',[r['reason'] for r in result['boundary_decisions']])

    def test_material_fragment_in_instruction_cannot_become_surface(self):
        semantic,result=self.analyze(words=('Ground',' graded',' down'),material=None)
        self.assertEqual(semantic['outlines'],[])
        self.assertEqual(result['candidates'],[])
        ground=next(r for r in result['labels'] if r['text']=='Ground')
        self.assertEqual(ground['status'],semantics.ANNOTATION_WITHHELD)
        self.assertEqual(result['visible_surface_labels'],0)

    def test_annotation_does_not_authorize_an_unrelated_building_inside_same_enclosure(self):
        semantic,result=self.analyze(extra_role='Building')
        self.assertEqual(semantic['outlines'][0]['status'],'annotation_fragment_context_withheld')
        self.assertEqual(semantic['summary']['associated_outline_hints'],0)
        self.assertEqual(result['candidates'],[])

    def test_standalone_labels_distant_words_and_other_typography_remain_unchanged(self):
        for kwargs in ({'words':('Path',)},{'words':('Path',' lowered'),'gap':35},
                {'words':('Path',' lowered'),'font':'cour'},
                {'words':('Path',' lowered'),'color':(1,0,0)}):
            with self.subTest(kwargs=kwargs):
                semantic,result=self.analyze(**kwargs)
                self.assertEqual(semantic['summary']['annotation_fragments_withheld'],0)
                self.assertEqual(len(result['candidates']),1)
                self.assertEqual(result['candidates'][0]['source_role_hint'],'path')

    def test_hidden_continuation_never_supplies_verified_context_or_positive_geometry(self):
        semantic,result=self.analyze(hidden=True)
        self.assertEqual(result['candidates'],[])
        for row in semantic['labels']:
            if row.get('annotation_context'):
                self.assertFalse(row['annotation_context']['all_parts_visible'])

    def test_nested_boundaries_cannot_be_resolved_by_removing_note_fragment(self):
        semantic,result=self.analyze(nested=True)
        self.assertEqual(semantic['summary']['associated_outline_hints'],0)
        self.assertEqual(result['candidates'],[])

    def test_competing_continuations_are_all_retained_without_nearest_selection(self):
        doc,page,sha,inventory=fixture(words=('Path',' lowered'));self.addCleanup(doc.close)
        page.insert_text((110+pymupdf.get_text_length('Path',fontsize=10),120),' raised',fontsize=10)
        sha=hashlib.sha256(doc.tobytes()).hexdigest()
        _,_,report=ordinary_surfaces.page_candidates(page,sha,1)
        result=semantics.page_candidates(page,sha,1,report['source_outline_inventory'])
        label=next(r for r in result['labels'] if r['text']=='Path')
        self.assertEqual(label['status'],semantics.ANNOTATION_WITHHELD)
        self.assertTrue(label['annotation_context']['ambiguous_adjacency'])
        self.assertEqual(len(label['annotation_context']['parts']),3)

    def test_split_existing_label_does_not_silently_lose_its_printed_state(self):
        semantic,result=self.analyze(words=('Existing',' Path'),extra_role='Proposed Building')
        self.assertEqual(result['candidates'],[])
        self.assertEqual(semantic['summary']['associated_outline_hints'],0)
        path=next(r for r in semantic['labels'] if r['text']=='Path')
        self.assertEqual(path['annotation_context']['text'],'Existing Path')

    def test_comparison_run_character_and_part_caps_are_all_or_nothing(self):
        doc,page,sha,inventory=fixture();self.addCleanup(doc.close)
        for options in ({'max_annotation_checks':1},{'max_annotation_runs':1},
                {'max_annotation_parts':2},{'max_annotation_characters':5}):
            with self.subTest(options=options):
                semantic=semantics.page_candidates(page,sha,1,inventory,options=options)
                self.assertFalse(semantic['inventory_complete']);self.assertEqual(semantic['outlines'],[])
        semantic=semantics.page_candidates(page,sha,1,inventory)
        result=surfaces.page_candidates(page,sha,1,inventory,semantic,options={'max_annotation_runs':1})
        self.assertFalse(result['analysis_complete']);self.assertEqual(result['candidates'],[])

    def test_rotation_replay_cancellation_and_original_bytes(self):
        for rotation in (0,90):
            doc,page,sha,inventory=fixture(rotation=rotation);self.addCleanup(doc.close)
            original=doc.tobytes(no_new_id=True);before=json.dumps(inventory,sort_keys=True)
            first=semantics.page_candidates(page,sha,1,inventory)
            self.assertEqual(first,semantics.page_candidates(page,sha,1,inventory))
            self.assertEqual(first['summary']['annotation_fragments_withheld'],1)
            self.assertEqual(doc.tobytes(no_new_id=True),original)
            self.assertEqual(json.dumps(inventory,sort_keys=True),before)
            self.assertEqual(page.rotation,rotation)
            with self.assertRaises(CancelledError):
                semantics.page_candidates(page,sha,1,inventory,cancelled=lambda:True)

    def test_saved_layout_cannot_promote_a_fragment_by_removing_status(self):
        layout=source_layout();evidence=copy.deepcopy(layout['candidates'][0]['source_evidence'][0])
        label=evidence['semantic_evidence'].get('labels',[evidence['semantic_evidence'].get('label')])[0]
        label['annotation_context']={'version':semantics.ANNOTATION_VERSION,'status':'literal_fragment_in_native_text_context'}
        with self.assertRaisesRegex(ValueError,'Visible whole source label'):
            planning_area_layout._semantics(evidence,layout['document_sha256'],layout['page'])


if __name__=='__main__':unittest.main()
