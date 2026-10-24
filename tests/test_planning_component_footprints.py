"""Distinct source faces, explicit gaps and bounded component recovery."""
import copy
from concurrent.futures import CancelledError
import hashlib
import json
import unittest
from unittest.mock import patch

import pymupdf
from shapely.geometry import box, shape

from voxel_mapper import ordinary_surfaces, planning_outline_semantics as semantics
from voxel_mapper import planning_component_footprints as components
from voxel_mapper import planning_area_pilot as pilot
from voxel_mapper.building_spec import digest


def fixture(*, divider=True, dashed=False, nested=False, conflict=None, hidden=False,
            hole=False, covered_edge=False, short_outer=False, rotation=0, wide=False,
            distant_outer=False):
    doc=pymupdf.open();page=doc.new_page(width=1100 if wide or distant_outer else 500,height=350)
    right=1000 if wide else 300
    def edge(a,b,short=False,dashes=None):
        count=int(max(abs(b[0]-a[0]),abs(b[1]-a[1]))/5) if short else 1
        for i in range(count):
            page.draw_line(tuple(a[k]+(b[k]-a[k])*i/count for k in (0,1)),
                           tuple(a[k]+(b[k]-a[k])*(i+1)/count for k in (0,1)),dashes=dashes)
    for a,b in (((100,80),(right,80)),((100,160),(right,160)),
                ((100,80),(100,160)),((right,80),(right,160))):edge(a,b,short_outer)
    if divider and not wide:edge((200,80),(200,160),True,'[2 2] 0' if dashed else None)
    page.insert_text((500 if wide else 120,125),'Container',fontsize=8)
    if not wide:page.insert_text((220,125),'Container',fontsize=8)
    if nested:page.draw_rect((90,70,310,170))
    if distant_outer:page.draw_rect((30,30,1000,300))
    if hole:
        for a,b in (((170,90),(185,90)),((185,90),(185,105)),
                    ((185,105),(170,105)),((170,105),(170,90))):edge(a,b)
    if conflict:page.insert_text((120,145),conflict,fontsize=8)
    if hidden:page.draw_rect((115,114,170,130),fill=(1,1,1),color=None)
    if covered_edge:page.draw_rect((98,90,102,110),fill=(1,1,1),color=None)
    page.set_rotation(rotation);sha=hashlib.sha256(doc.tobytes()).hexdigest()
    _,_,report=ordinary_surfaces.page_candidates(page,sha,1)
    inventory=report['source_outline_inventory'];associations=semantics.page_candidates(page,sha,1,inventory)
    return doc,page,sha,inventory,associations


class ComponentFootprintTests(unittest.TestCase):
    def analyze(self,**kwargs):
        doc,page,sha,inventory,associations=fixture(**kwargs);self.addCleanup(doc.close)
        return components.page_candidates(page,sha,1,inventory,associations),inventory,associations

    def test_short_shared_divider_recovers_two_exact_source_faces_from_one_coarse_enclosure(self):
        result,inventory,coarse=self.analyze()
        self.assertEqual(coarse['summary']['shared_component_enclosures'],1)
        self.assertEqual(len(inventory['records']),1)
        self.assertEqual(result['summary']['component_boundary_candidates'],2)
        geometries=[shape(r['geometry_pdf_native']) for r in result['candidates']]
        for expected in (box(100,190,200,270),box(200,190,300,270)):
            self.assertTrue(any(expected.equals(g) for g in geometries))
        for row in result['candidates']:
            record=row['source_outline'];source=record['candidate']
            self.assertEqual(record['source_record_sha256'],digest(source))
            self.assertGreater(len(source['line_parent_references']),4)
            self.assertTrue(all(p['raw_parent_references'] for p in source['line_parent_references']))
            self.assertFalse(row['physical_identity_verified'])
            self.assertFalse(row['world_placement_eligible'])
        self.assertFalse(result['registration_verified'])
        self.assertFalse(result['scale_verified'])
        self.assertEqual(result['world_geometry_additions'],0)
        self.assertEqual(result['training_labels_generated'],0)
        self.assertFalse(result['model_weights_updated'])
        self.assertIsNone(result['geometric_accuracy'])

    def test_fine_scan_recovers_boundaries_when_all_source_edges_are_below_coarse_threshold(self):
        result,inventory,_=self.analyze(short_outer=True)
        self.assertEqual(inventory['records'],[])
        self.assertEqual(result['summary']['component_boundary_candidates'],2)

    def test_missing_or_dashed_divider_never_splits_a_shared_enclosure(self):
        for kwargs in ({'divider':False},{'dashed':True}):
            with self.subTest(kwargs=kwargs):
                result,_,_=self.analyze(**kwargs)
                self.assertEqual(result['candidates'],[])
                self.assertIn('shared_component_label_enclosure_hint',
                              [r['reason'] for r in result['boundary_decisions']])

    def test_nested_source_enclosures_are_not_resolved_using_smallest_or_nearest(self):
        result,_,_=self.analyze(nested=True)
        self.assertEqual(result['candidates'],[])
        self.assertEqual(result['fine_associations']['summary']['label_statuses']['ambiguous_source_enclosures_withheld'],2)

    def test_known_coarse_competing_enclosure_cannot_disappear_at_fine_scan_border(self):
        result,_,coarse=self.analyze(distant_outer=True)
        self.assertEqual(coarse['summary']['label_statuses']['ambiguous_source_enclosures_withheld'],2)
        self.assertEqual(result['fine_associations']['summary']['associated_outline_hints'],2)
        self.assertEqual(result['candidates'],[])
        self.assertTrue(all(r['reason']=='coarse_competing_enclosures_require_interpretation'
                            for r in result['boundary_decisions']))

    def test_conflicting_path_or_legend_context_withholds_the_affected_component(self):
        for conflict in ('Path','Legend'):
            with self.subTest(conflict=conflict):
                result,_,_=self.analyze(conflict=conflict)
                self.assertEqual(len(result['candidates']),1)
                self.assertEqual(shape(result['candidates'][0]['geometry_pdf_native']).bounds,(200,190,300,270))

    def test_hidden_label_cannot_supply_an_individual_component(self):
        result,_,_=self.analyze(hidden=True)
        self.assertEqual(result['visible_component_labels'],1)
        self.assertEqual(len(result['candidates']),1)

    def test_later_fill_over_a_source_edge_withholds_that_boundary(self):
        result,_,_=self.analyze(covered_edge=True)
        self.assertEqual(len(result['candidates']),1)
        self.assertGreater(result['covered_boundaries_withheld'],0)

    def test_interior_rings_are_retained_for_interpretation_not_erased(self):
        result,_,_=self.analyze(hole=True)
        self.assertEqual(len(result['candidates']),1)
        self.assertIn('interior_rings_require_component_boundary_interpretation',
                      [r['reason'] for r in result['boundary_decisions']])

    def test_search_rectangle_does_not_close_or_clip_a_component(self):
        result,_,_=self.analyze(wide=True)
        self.assertEqual(result['candidates'],[])
        self.assertGreater(result['extraction']['rejections']['complete_primitive_crosses_region_boundary'],0)

    def test_native_budget_stop_does_not_publish_a_partial_component_set(self):
        doc,page,sha,inventory,associations=fixture();self.addCleanup(doc.close)
        result=components.page_candidates(page,sha,1,inventory,associations,options={'max_native_candidates':1})
        self.assertFalse(result['analysis_complete'])
        self.assertEqual(result['candidates'],[])
        self.assertEqual(result['reason'],'complete_geometry_extraction_required')

    def test_label_budget_is_checked_before_fine_extraction(self):
        doc,page,sha,inventory,associations=fixture();self.addCleanup(doc.close)
        with patch.object(ordinary_surfaces,'closed_source_faces',side_effect=AssertionError('No scan')):
            result=components.page_candidates(page,sha,1,inventory,associations,options={'max_component_labels':1})
        self.assertFalse(result['analysis_complete'])
        self.assertEqual(result['reason'],'component_label_budget_exceeded')

    def test_output_budget_clears_large_candidate_and_diagnostic_arrays(self):
        doc,page,sha,inventory,associations=fixture(short_outer=True);self.addCleanup(doc.close)
        result=components.page_candidates(page,sha,1,inventory,associations,options={'max_output_bytes':16384})
        self.assertFalse(result['analysis_complete'])
        self.assertEqual(result['reason'],'component_output_budget_exceeded')
        self.assertEqual(result['candidates'],[])
        self.assertLessEqual(len(json.dumps(result).encode()),16384)

    def test_limits_are_strict_lower_only_integers(self):
        doc,page,sha,inventory,associations=fixture();self.addCleanup(doc.close)
        for options in ({'max_native_candidates':10001},{'max_outlines':True},
                        {'max_component_labels':0},{'max_output_bytes':1000},{'unbounded':1}):
            with self.subTest(options=options),self.assertRaises(ValueError):
                components.page_candidates(page,sha,1,inventory,associations,options=options)

    def test_changed_source_association_and_incomplete_inventory_are_rejected(self):
        doc,page,sha,inventory,associations=fixture();self.addCleanup(doc.close)
        changed=copy.deepcopy(inventory);changed['inventory_complete']=False
        with self.assertRaises(ValueError):components.page_candidates(page,sha,1,changed,associations)
        with self.assertRaises(ValueError):components.page_candidates(page,'a'*64,1,inventory,associations)
        changed=copy.deepcopy(associations);changed['inventory_complete']=False
        with self.assertRaises(ValueError):components.page_candidates(page,sha,1,inventory,changed)

    def test_rotation_and_replay_are_deterministic_without_mutating_sources(self):
        doc,page,sha,inventory,associations=fixture(rotation=90);self.addCleanup(doc.close)
        original=doc.tobytes(no_new_id=True);before=json.dumps([inventory,associations],sort_keys=True)
        first=components.page_candidates(page,sha,1,inventory,associations)
        second=components.page_candidates(page,sha,1,inventory,associations)
        self.assertEqual(len(first['candidates']),2)
        self.assertEqual(first,second)
        self.assertEqual(page.rotation,90)
        self.assertEqual(doc.tobytes(no_new_id=True),original)
        self.assertEqual(json.dumps([inventory,associations],sort_keys=True),before)

    def test_cancellation_raises_without_returning_partial_success(self):
        doc,page,sha,inventory,associations=fixture();self.addCleanup(doc.close)
        calls=[0]
        def cancelled():calls[0]+=1;return calls[0]>2
        with self.assertRaises(CancelledError):
            components.page_candidates(page,sha,1,inventory,associations,cancelled=cancelled)

    def test_page_without_component_labels_does_not_start_a_fine_scan(self):
        doc=pymupdf.open();self.addCleanup(doc.close);page=doc.new_page()
        page.draw_rect((50,50,200,200));page.insert_text((80,100),'Footpath')
        sha=hashlib.sha256(doc.tobytes()).hexdigest()
        _,_,report=ordinary_surfaces.page_candidates(page,sha,1);inventory=report['source_outline_inventory']
        associations=semantics.page_candidates(page,sha,1,inventory)
        with patch.object(ordinary_surfaces,'closed_source_faces',side_effect=AssertionError('No scan')):
            result=components.page_candidates(page,sha,1,inventory,associations)
        self.assertEqual(result['status'],'no_visible_component_labels')
        self.assertEqual(result['candidates'],[])

    def test_optional_fine_stage_failure_preserves_coarse_page_evidence(self):
        doc,page,sha,_,_=fixture();self.addCleanup(doc.close)
        original=ordinary_surfaces.closed_source_faces
        def failed(*args,**kwargs):
            if kwargs.get('extraction_options'):raise ValueError('Synthetic fine budget stop')
            return original(*args,**kwargs)
        with patch.object(ordinary_surfaces,'closed_source_faces',side_effect=failed):
            result=pilot._page(page,sha,1,'floor-plan')
        self.assertEqual(result['summary']['closed_source_outlines'],1)
        self.assertEqual(result['component_footprints']['reason'],'fine_source_geometry_failed')
        self.assertEqual(result['summary']['component_boundary_candidates'],0)
        self.assertIn('fine_component_boundary_analysis_incomplete',result['summary']['blockers'])

    def test_floor_plan_pipeline_exposes_components_and_keeps_world_reconstruction_blocked(self):
        doc,page,sha,_,_=fixture();self.addCleanup(doc.close)
        result=pilot._page(page,sha,1,'floor-plan')
        self.assertEqual(result['summary']['component_boundary_candidates'],2)
        self.assertFalse(result['world_placement_eligible'])
        self.assertIn('component_boundary_exterior_wall_role_unverified',result['summary']['blockers'])
        result=pilot._page(page,sha,1,'site-plan')
        self.assertIsNone(result['component_footprints'])
        self.assertEqual(result['summary']['component_boundary_candidates'],0)


if __name__=='__main__':unittest.main()
