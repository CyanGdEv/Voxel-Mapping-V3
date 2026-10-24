"""Original PDF scale trials, literal dimensions and failure to invent height."""
import copy
from concurrent.futures import CancelledError
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf
from shapely.geometry import shape

from voxel_mapper import architectural_graph, architectural_view_layout, ordinary_surfaces
from voxel_mapper import planning_component_footprints, planning_outline_semantics
from voxel_mapper import planning_component_measurements as measurements


def page_source(page,*,components=False,sha=None):
    sha=sha or hashlib.sha256(page.parent.tobytes()).hexdigest()
    graph=architectural_graph.build([]);graph.update(document_sha256=sha,page=page.number+1)
    layout=architectural_view_layout.review(page,sha,page.number+1,graph)
    pack=None
    if components:
        _,_,report=ordinary_surfaces.page_candidates(page,sha,page.number+1)
        inventory=report['source_outline_inventory']
        labels=planning_outline_semantics.page_candidates(page,sha,page.number+1,inventory)
        pack=planning_component_footprints.page_candidates(page,sha,page.number+1,inventory,labels)
    return sha,layout,pack


def fixture(*,length_m=12.192,second_scale=False,hidden_scale=False,hidden_code=False,
            note='1 No. 8ft x 40ft Shipping containers.',hidden_note=False,
            duplicate_note=False,conflicting_note=False,other_series=False,reference=True,
            existing_note=False,rotation=0,unit=None,crop=False,paper=False,resized=False):
    floor=pymupdf.open();page=floor.new_page(width=900 if not paper or resized else 2384,height=700 if not paper or resized else 1684)
    factor=200*.0254/72
    page.draw_rect((100,100,100+length_m/factor,100+2.4384/factor))
    page.insert_text((120,125),'Container',fontsize=8)
    page.insert_text((70,500),'Proposed Ground Floor Plan | 1:200',fontsize=10)
    if second_scale:page.insert_text((70,560),'Proposed Roof Plan | 1:100',fontsize=10)
    page.insert_text((70,650),'TEST-AA-BB-CC-DR-A-0201',fontsize=8)
    if reference:page.insert_text((500,650),'0301',fontsize=8)
    if paper:page.insert_text((500,600),'As indicated @A1',fontsize=8)
    if hidden_scale:page.draw_rect((65,485,350,507),fill=(1,1,1),color=None)
    if hidden_code:page.draw_rect((65,638,250,658),fill=(1,1,1),color=None)
    if unit:floor.xref_set_key(page.xref,'UserUnit',str(unit))
    if crop:page.set_cropbox(pymupdf.Rect(0,0,page.rect.width-10,page.rect.height))
    page.set_rotation(rotation)
    notes=pymupdf.open();witness=notes.new_page(width=900,height=700)
    witness.insert_text((70,500),('Existing' if existing_note else 'Proposed')+' Section A-A | 1:100',fontsize=10)
    witness.insert_text((70,650),('OTHER' if other_series else 'TEST')+'-AA-BB-CC-DR-A-0301',fontsize=8)
    witness.insert_text((100,120),note,fontsize=10)
    if duplicate_note:witness.insert_text((100,160),note,fontsize=10)
    if conflicting_note:witness.insert_text((100,200),'1 No. 10ft x 40ft Shipping containers.',fontsize=10)
    if hidden_note:witness.draw_rect((95,105,390,125),fill=(1,1,1),color=None)
    sha,layout,components=page_source(page,components=True)
    nsha,nlayout,_=page_source(witness)
    a=measurements.page_evidence(page,sha,1,layout,components)
    b=measurements.page_evidence(witness,nsha,1,nlayout,None)
    return floor,notes,a,b,(page,sha,layout,components)


class ComponentMeasurementTests(unittest.TestCase):
    def sources(self,**kwargs):
        floor,notes,a,b,inputs=fixture(**kwargs);self.addCleanup(floor.close);self.addCleanup(notes.close)
        return a,b,inputs

    def test_exact_source_geometry_and_explicit_feet_agree_without_footprint_or_height_acceptance(self):
        a,b,_=self.sources();r=measurements.review_pages([a,b])
        self.assertEqual(r['summary']['size_consistent_component_hypotheses'],1)
        row=r['components'][0];self.assertEqual(row['printed_length_pair_m'],[2.4384,12.192])
        self.assertLess(row['maximum_span_error_m'],1e-5)
        self.assertAlmostEqual(shape(row['trials'][0]['geometry_nominal_local']).area,2.4384*12.192,places=5)
        self.assertFalse(row['component_correspondence_verified'])
        self.assertFalse(row['physical_exterior_boundary_verified'])
        self.assertFalse(row['physical_scale_verified'])
        self.assertFalse(r['world_placement_eligible'])
        self.assertEqual(r['local_3d_components'],0)
        self.assertIsNone(row['trials'][0]['height_m'])
        self.assertFalse(row['note_evidence'][0]['note']['claim']['height_supplied'])
        self.assertEqual(r['world_geometry_additions'],0)
        self.assertEqual(r['training_labels_generated'],0)
        self.assertFalse(r['model_weights_updated'])
        self.assertIsNone(r['geometric_accuracy'])

    def test_shortened_boundary_is_reported_as_a_mismatch_without_rescaling_it(self):
        a,b,_=self.sources(length_m=11.39);before=copy.deepcopy(a)
        r=measurements.review_pages([a,b]);row=r['components'][0]
        self.assertEqual(r['summary']['size_mismatched_component_hypotheses'],1)
        self.assertAlmostEqual(row['maximum_span_error_m'],.802,places=5)
        self.assertEqual(a,before)

    def test_tolerance_is_declared_lower_only_and_cannot_be_fitted_after_a_mismatch(self):
        a,b,_=self.sources(length_m=12.0)
        self.assertEqual(measurements.review_pages([a,b])['summary']['size_consistent_component_hypotheses'],1)
        self.assertEqual(measurements.review_pages([a,b],tolerance_m=.1)['summary']['size_mismatched_component_hypotheses'],1)
        for value in (.251,True,float('nan'),0):
            with self.subTest(value=value),self.assertRaises(ValueError):measurements.review_pages([a,b],tolerance_m=value)

    def test_multiple_scale_claims_are_not_selected_by_best_size_residual(self):
        a,b,_=self.sources(second_scale=True);r=measurements.review_pages([a,b])
        self.assertEqual(len(r['components'][0]['trials']),2)
        self.assertEqual(r['components'][0]['status'],'multiple_nominal_scales_withheld')
        self.assertEqual(r['summary']['size_consistent_component_hypotheses'],0)

    def test_hidden_scale_supplies_no_nominal_component_geometry(self):
        a,b,_=self.sources(hidden_scale=True)
        self.assertEqual(a['trials'],[])
        self.assertEqual(measurements.review_pages([a,b])['components'],[])

    def test_hidden_note_or_drawing_code_cannot_validate_a_size_pair(self):
        for kwargs in ({'hidden_note':True},{'hidden_code':True}):
            with self.subTest(kwargs=kwargs):
                a,b,_=self.sources(**kwargs);r=measurements.review_pages([a,b])
                self.assertEqual(r['summary']['size_consistent_component_hypotheses'],0)
                self.assertEqual(r['components'][0]['status'],'printed_size_note_context_unresolved')

    def test_wrong_drawing_series_missing_reference_and_different_states_stay_unlinked(self):
        for kwargs in ({'other_series':True},{'reference':False},{'existing_note':True}):
            with self.subTest(kwargs=kwargs):
                a,b,_=self.sources(**kwargs);r=measurements.review_pages([a,b])
                self.assertEqual(r['components'][0]['note_evidence'],[])
                self.assertEqual(r['summary']['size_consistent_component_hypotheses'],0)

    def test_conflicting_size_notes_cannot_be_resolved_using_the_best_fit(self):
        a,b,_=self.sources(conflicting_note=True);r=measurements.review_pages([a,b])
        self.assertEqual(r['components'][0]['status'],'conflicting_printed_size_notes')
        self.assertEqual(len(r['components'][0]['note_evidence']),2)

    def test_identical_note_occurrences_keep_all_source_receipts(self):
        a,b,_=self.sources(duplicate_note=True);r=measurements.review_pages([a,b])
        self.assertEqual(r['summary']['size_consistent_component_hypotheses'],1)
        self.assertEqual(len(r['components'][0]['note_evidence']),2)

    def test_distinct_sheets_in_one_original_pdf_can_supply_literal_context(self):
        a,b,(page,_,_,_)=self.sources()
        extra_floor,original_note,*_=fixture()
        self.addCleanup(extra_floor.close);self.addCleanup(original_note.close)
        combined=pymupdf.open();self.addCleanup(combined.close)
        combined.insert_pdf(page.parent);combined.insert_pdf(original_note)
        data=combined.tobytes();sha=hashlib.sha256(data).hexdigest()
        retained=pymupdf.open(stream=data,filetype='pdf');self.addCleanup(retained.close)
        _,layout,pack=page_source(retained[0],components=True,sha=sha)
        left=measurements.page_evidence(retained[0],sha,1,layout,pack)
        _,layout,_=page_source(retained[1],sha=sha)
        right=measurements.page_evidence(retained[1],sha,2,layout,None)
        r=measurements.review_pages([left,right])
        self.assertEqual(r['summary']['size_consistent_component_hypotheses'],1)
        self.assertFalse(r['components'][0]['component_correspondence_verified'])

    def test_printed_component_count_disagreement_remains_explicit(self):
        a,b,_=self.sources(note='2 No. 8ft x 40ft Shipping containers.')
        self.assertEqual(measurements.review_pages([a,b])['components'][0]['status'],'printed_component_count_disagreement')

    def test_units_are_literal_and_never_inferred_from_a_neighbor_or_container_type(self):
        self.assertEqual(measurements.printed_size('2438.4mm x 12.192m Container')['length_pair_m'],[2.4384,12.192])
        for text in ('8 x 40ft Container','8ft x 40 Container','Standard container',
                     'Height 8ft x 40ft Container','0ft x 40ft Container','-8ft x 40ft Container'):
            with self.subTest(text=text):self.assertIsNone(measurements.printed_size(text))

    def test_cropped_nonstandard_user_unit_and_resized_declared_paper_are_withheld(self):
        for kwargs in ({'unit':2},{'crop':True},{'paper':True,'resized':True}):
            with self.subTest(kwargs=kwargs):
                a,_,_=self.sources(**kwargs)
                self.assertFalse(a['analysis_complete'])
                self.assertEqual(a['trials'],[])
        a,_,_=self.sources(paper=True)
        self.assertTrue(a['analysis_complete'])
        self.assertEqual(a['matching_paper_sizes'],['A1'])

    def test_mutated_native_component_geometry_is_rejected_before_a_trial_is_emitted(self):
        _,_,(page,sha,layout,components)=self.sources()
        changed=copy.deepcopy(components);changed['candidates'][0]['geometry_pdf_native']['coordinates'][0][0][0]+=1
        with self.assertRaisesRegex(ValueError,'source-bound'):
            measurements.page_evidence(page,sha,1,layout,changed)

    def test_source_page_and_layout_changes_are_rejected(self):
        _,_,(page,sha,layout,components)=self.sources()
        with self.assertRaises(ValueError):measurements.page_evidence(page,'a'*64,1,layout,components)
        changed=copy.deepcopy(layout);changed['version']='old'
        with self.assertRaises(ValueError):measurements.page_evidence(page,sha,1,changed,components)

    def test_stale_or_conflicting_measurement_page_receipts_are_rejected(self):
        a,b,_=self.sources();changed=copy.deepcopy(a);changed['trials'][0]['printed_scale_denominator']=100
        with self.assertRaises(ValueError):measurements.review_pages([changed,b])
        changed['id']=measurements.digest({k:v for k,v in changed.items() if k!='id'})
        with self.assertRaises(ValueError):measurements.review_pages([a,changed,b])

    def test_point_evidence_and_scale_limits_withhold_all_trials(self):
        _,_,(page,sha,layout,components)=self.sources(second_scale=True)
        for options in ({'max_points':1},{'max_text_evidence':1},{'max_scale_claims':1}):
            with self.subTest(options=options):
                r=measurements.page_evidence(page,sha,1,layout,components,options=options)
                self.assertFalse(r['analysis_complete']);self.assertEqual(r['trials'],[])
        for options in ({'max_points':True},{'max_components':33},{'bad':1},{'max_output_bytes':1}):
            with self.subTest(options=options),self.assertRaises(ValueError):
                measurements.page_evidence(page,sha,1,layout,components,options=options)

    def test_late_page_output_budget_discards_partial_trial_geometry(self):
        _,_,(page,sha,layout,components)=self.sources()
        with patch.object(measurements.glyph_visibility,'screen_architectural_span',return_value={
                'status':'raster_consistent_candidate','large_diagnostic':'x'*20000}):
            result=measurements.page_evidence(page,sha,1,layout,components,options={'max_output_bytes':16384})
        self.assertFalse(result['analysis_complete']);self.assertEqual(result['trials'],[])
        self.assertLessEqual(len(json.dumps(result).encode()),16384)

    def test_pair_budget_holds_the_entire_size_review(self):
        a,b,_=self.sources();r=measurements.review_pages([a,b],max_pairs=1)
        self.assertFalse(r['analysis_complete']);self.assertEqual(r['components'],[])
        self.assertEqual(r['reason'],'size_note_pair_budget_exceeded')

    def test_incomplete_text_inventory_cannot_hide_a_competing_note(self):
        a,b,_=self.sources();incomplete=copy.deepcopy(b)
        incomplete.update(document_sha256='c'*64,analysis_complete=False,
            reason='measurement_evidence_budget_exceeded',size_notes=[])
        incomplete['id']=measurements.digest({k:v for k,v in incomplete.items() if k!='id'})
        r=measurements.review_pages([a,b,incomplete])
        self.assertFalse(r['analysis_complete']);self.assertEqual(r['components'],[])
        self.assertEqual(r['reason'],'complete_measurement_page_evidence_required')

    def test_late_review_byte_budget_does_not_publish_partial_size_success(self):
        a,b,_=self.sources()
        for row in b['size_notes']:row['glyph_screen']['large_diagnostic']='x'*20000
        b['id']=measurements.digest({k:v for k,v in b.items() if k!='id'})
        r=measurements.review_pages([a,b],max_output_bytes=16384)
        self.assertFalse(r['analysis_complete']);self.assertEqual(r['components'],[])
        self.assertLessEqual(len(json.dumps(r).encode()),16384)

    def test_rotation_replay_and_source_documents_remain_unchanged(self):
        a,b,(page,sha,layout,components)=self.sources(rotation=90)
        before=page.parent.tobytes(no_new_id=True)
        again=measurements.page_evidence(page,sha,1,layout,components)
        self.assertEqual(a,again);self.assertEqual(page.rotation,90)
        self.assertEqual(page.parent.tobytes(no_new_id=True),before)
        self.assertEqual(measurements.review_pages([a,b])['summary']['size_consistent_component_hypotheses'],1)

    def test_cancellation_does_not_return_partial_measurements_or_comparisons(self):
        a,b,(page,sha,layout,components)=self.sources()
        with self.assertRaises(CancelledError):measurements.page_evidence(page,sha,1,layout,components,cancelled=lambda:True)
        with self.assertRaises(CancelledError):measurements.review_pages([a,b],cancelled=lambda:True)

    def test_review_writes_measured_plans_and_explicitly_withholds_3d(self):
        a,b,_=self.sources();r=measurements.review_pages([a,b])
        with tempfile.TemporaryDirectory() as tmp:
            measurements.write_review(tmp,r)
            html=(Path(tmp)/'component-measurements.html').read_text()
            self.assertIn('<svg',html);self.assertIn('3D generation is withheld',html)
            self.assertEqual({p.suffix for p in Path(tmp).iterdir()},{'.html','.json'})
            saved=json.loads((Path(tmp)/'component-measurements.json').read_text())
            self.assertEqual(saved['local_3d_components'],0)
            measurements.write_review(tmp,r,max_preview_points=1)
            limited=(Path(tmp)/'component-measurements.html').read_text()
            self.assertIn('preview withheld',limited);self.assertNotIn('<svg',limited)
            self.assertEqual(json.loads((Path(tmp)/'component-measurements.json').read_text()),saved)


if __name__=='__main__':unittest.main()
