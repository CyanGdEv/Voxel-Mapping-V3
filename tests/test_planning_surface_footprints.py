"""Source-exact surface recovery, ambiguity, gaps, holes and bounded failure."""
import copy
from concurrent.futures import CancelledError
import hashlib
import json
import unittest
from unittest.mock import patch

import pymupdf
from shapely.geometry import box, shape

from voxel_mapper import ordinary_surfaces, planning_outline_semantics as semantics
from voxel_mapper import planning_surface_footprints as surfaces
from voxel_mapper.building_spec import digest


def fixture(*, labels=('Footpath', 'Plaza'), short=True, nested=False, distant=False,
            hole=False, hidden=False, conflict=None, covered=False, gap=False,
            wide=False, rotation=0):
    doc = pymupdf.open(); page = doc.new_page(width=1100 if distant or wide else 500, height=350)
    right = 1000 if wide else 300
    def edge(a, b):
        count = max(1, int(max(abs(b[0]-a[0]), abs(b[1]-a[1]))/5)) if short else 1
        for i in range(count):
            page.draw_line(tuple(a[k]+(b[k]-a[k])*i/count for k in (0, 1)),
                           tuple(a[k]+(b[k]-a[k])*(i+1)/count for k in (0, 1)))
    for a, b in (((100,80),(right,80)),((100,160),(right,160)),
                 ((100,80),(100,160)),((right,80),(right,160))):
        if not gap or a != (right,80): edge(a, b)
    if len(labels) > 1 and not wide: edge((200,80),(200,160))
    for i, text in enumerate(labels): page.insert_text((500 if wide else (140 if len(labels)==1 else 120+100*i),125), text, fontsize=8)
    if nested: page.draw_rect((90,70,310,170))
    if distant: page.draw_rect((30,30,1000,300))
    if hole:
        for a,b in (((170,90),(185,90)),((185,90),(185,105)),((185,105),(170,105)),((170,105),(170,90))):edge(a,b)
    if hidden: page.draw_rect((115,114,170,130), fill=(1,1,1), color=None)
    if conflict: page.insert_text((120,145), conflict, fontsize=8)
    if covered: page.draw_rect((98,90,102,110), fill=(1,1,1), color=None)
    page.set_rotation(rotation); sha = hashlib.sha256(doc.tobytes()).hexdigest()
    _,_,report = ordinary_surfaces.page_candidates(page,sha,1)
    inventory = report['source_outline_inventory']; associations = semantics.page_candidates(page,sha,1,inventory)
    return doc,page,sha,inventory,associations


class PlanningSurfaceFootprintsTests(unittest.TestCase):
    def analyze(self, **kwargs):
        doc,page,sha,inventory,associations = fixture(**kwargs); self.addCleanup(doc.close)
        return surfaces.page_candidates(page,sha,1,inventory,associations),inventory

    def test_short_source_edges_recover_separate_path_and_plaza_without_user_crops(self):
        result,inventory = self.analyze()
        self.assertEqual(inventory['records'],[])
        self.assertTrue(result['analysis_complete'])
        self.assertEqual(result['summary']['surface_boundary_candidates'],2)
        self.assertEqual({r['source_role_hint'] for r in result['candidates']},{'path','plaza'})
        geometries = [shape(r['geometry_pdf_native']) for r in result['candidates']]
        for expected in (box(100,190,200,270), box(200,190,300,270)):
            self.assertTrue(any(expected.equals(g) for g in geometries))
        for row in result['candidates']:
            self.assertEqual(row['source_outline']['source_record_sha256'],digest(row['source_outline']['candidate']))
            self.assertFalse(row['physical_identity_verified']); self.assertFalse(row['world_placement_eligible'])
            self.assertEqual(row['surface'],'stone')
        self.assertEqual(result['world_geometry_additions'],0)
        self.assertEqual(result['training_labels_generated'],0)

    def test_material_only_labels_retain_exact_paving_finishes(self):
        result,_ = self.analyze(labels=('brick paving','tarmac'))
        self.assertEqual({r['surface'] for r in result['candidates']},{'brick','asphalt'})
        self.assertTrue(all(r['source_role_hint']=='surface' for r in result['candidates']))
        self.assertTrue(all(r['labels'][0]['glyph_screen']['status']=='raster_consistent_candidate' for r in result['candidates']))

    def test_long_gap_is_not_closed_and_nearby_label_is_not_bound(self):
        result,_ = self.analyze(labels=('Footpath',),gap=True)
        self.assertEqual(result['candidates'],[])
        self.assertEqual(result['summary']['unresolved_surface_labels'],1)

    def test_original_holes_are_preserved_as_exclusions(self):
        result,_ = self.analyze(labels=('Footpath',),hole=True)
        self.assertEqual(len(result['candidates']),1)
        polygon = shape(result['candidates'][0]['geometry_pdf_native'])
        self.assertEqual(len(polygon.interiors),1)
        self.assertEqual(polygon.area,16000-225)

    def test_label_inside_a_hole_is_not_assigned_to_outer_surface(self):
        doc,page,sha,inventory,associations = fixture(labels=(),hole=True);self.addCleanup(doc.close)
        # A separate inner face is native geometry; it cannot authorize the outer polygon.
        page.insert_text((171,101),'Path',fontsize=2)
        sha = hashlib.sha256(doc.tobytes()).hexdigest()
        _,_,report=ordinary_surfaces.page_candidates(page,sha,1);inventory=report['source_outline_inventory']
        associations=semantics.page_candidates(page,sha,1,inventory)
        result=surfaces.page_candidates(page,sha,1,inventory,associations)
        self.assertEqual(len(result['candidates']),1)
        self.assertEqual(shape(result['candidates'][0]['geometry_pdf_native']).area,225)

    def test_nested_material_and_role_enclosures_stay_ambiguous(self):
        for labels in (('Footpath','Plaza'),('brick paving','tarmac')):
            result,_ = self.analyze(labels=labels,short=False,nested=True)
            self.assertEqual(result['candidates'],[])

    def test_known_coarse_ambiguity_cannot_disappear_at_scan_boundary(self):
        result,_ = self.analyze(short=False,distant=True)
        self.assertEqual(result['candidates'],[])
        self.assertIn('coarse_competing_enclosures_require_interpretation',
                      [r['reason'] for r in result['boundary_decisions']])

    def test_material_with_building_or_legend_context_is_withheld(self):
        for conflict in ('Building','Legend'):
            result,_ = self.analyze(labels=('brick paving','tarmac'),conflict=conflict)
            self.assertEqual(len(result['candidates']),1)
            self.assertEqual(result['candidates'][0]['surface'],'asphalt')

    def test_conflicting_path_plaza_or_state_claims_are_not_selected(self):
        for conflict in ('Plaza','Existing Path'):
            result,_ = self.analyze(labels=('Proposed Path',),conflict=conflict)
            self.assertEqual(result['candidates'],[])

    def test_hidden_material_or_role_label_supplies_no_candidate(self):
        for labels in (('Footpath','Plaza'),('brick paving','tarmac')):
            result,_ = self.analyze(labels=labels,hidden=True)
            self.assertEqual(result['visible_surface_labels'],1)
            self.assertEqual(len(result['candidates']),1)

    def test_later_paint_over_boundary_withholds_affected_face(self):
        result,_ = self.analyze(covered=True)
        self.assertEqual(len(result['candidates']),1)
        self.assertGreater(result['covered_boundaries_withheld'],0)

    def test_search_rectangle_does_not_clip_large_path_into_a_closed_surface(self):
        result,_ = self.analyze(labels=('Footpath',),wide=True,short=False)
        self.assertEqual(len(result['candidates']),1)
        self.assertTrue(shape(result['candidates'][0]['geometry_pdf_native']).equals(box(100,190,1000,270)))
        self.assertEqual(len(result['extraction']['complete_coarse_fallbacks']),1)
        self.assertGreater(result['extraction']['rejections']['complete_primitive_crosses_region_boundary'],0)
        # Without an existing complete coarse boundary, the focused scan
        # cannot turn an oversized open subset into a footprint.
        result,_=self.analyze(labels=('Footpath',),wide=True,short=True)
        self.assertEqual(result['candidates'],[])

    def test_label_candidate_and_work_budget_stops_are_all_or_none(self):
        doc,page,sha,inventory,associations=fixture(short=False);self.addCleanup(doc.close)
        for options in ({'max_surface_labels':1},{'max_native_candidates':1},{'max_association_checks':1}):
            with self.subTest(options=options):
                result=surfaces.page_candidates(page,sha,1,inventory,associations,options=options)
                self.assertFalse(result['analysis_complete']);self.assertEqual(result['candidates'],[])
                self.assertEqual(result['summary']['surface_boundary_candidates'],0)

    def test_output_budget_clears_large_candidates_and_diagnostics(self):
        doc,page,sha,inventory,associations=fixture();self.addCleanup(doc.close)
        result=surfaces.page_candidates(page,sha,1,inventory,associations,options={'max_output_bytes':16384})
        self.assertFalse(result['analysis_complete']);self.assertEqual(result['candidates'],[])
        self.assertEqual(result['reason'],'surface_output_budget_exceeded')
        self.assertLessEqual(len(json.dumps(result).encode()),16384)

    def test_unknown_or_expanded_or_boolean_limits_are_rejected(self):
        doc,page,sha,inventory,associations=fixture();self.addCleanup(doc.close)
        for options in ({'max_surface_labels':257},{'max_outlines':True},{'max_native_points':0},
                        {'max_output_bytes':1000},{'unknown':1}):
            with self.subTest(options=options),self.assertRaises(ValueError):
                surfaces.page_candidates(page,sha,1,inventory,associations,options=options)

    def test_changed_source_hash_inventory_or_association_is_rejected(self):
        doc,page,sha,inventory,associations=fixture(short=False);self.addCleanup(doc.close)
        with self.assertRaises(ValueError):surfaces.page_candidates(page,'a'*64,1,inventory,associations)
        for key in ('inventory_complete','source_inventory_sha256'):
            changed=copy.deepcopy(associations);changed[key]=False
            with self.assertRaises(ValueError):surfaces.page_candidates(page,sha,1,inventory,changed)
        changed=copy.deepcopy(inventory);changed['records'][0]['candidate']['geometry']['coordinates'][0][0][0]+=1
        altered=copy.deepcopy(associations);altered['source_inventory_sha256']=digest(changed)
        with self.assertRaises(ValueError):surfaces.page_candidates(page,sha,1,changed,altered)

    def test_rotation_replay_and_inputs_are_unchanged(self):
        doc,page,sha,inventory,associations=fixture(rotation=90);self.addCleanup(doc.close)
        source=doc.tobytes(no_new_id=True);before=json.dumps([inventory,associations],sort_keys=True)
        first=surfaces.page_candidates(page,sha,1,inventory,associations)
        self.assertEqual(first,surfaces.page_candidates(page,sha,1,inventory,associations))
        self.assertEqual(len(first['candidates']),2);self.assertEqual(page.rotation,90)
        self.assertEqual(doc.tobytes(no_new_id=True),source)
        self.assertEqual(json.dumps([inventory,associations],sort_keys=True),before)

    def test_cancellation_raises_without_partial_success(self):
        doc,page,sha,inventory,associations=fixture();self.addCleanup(doc.close)
        calls=[0]
        def cancelled():calls[0]+=1;return calls[0]>3
        with self.assertRaises(CancelledError):surfaces.page_candidates(page,sha,1,inventory,associations,cancelled=cancelled)

    def test_page_without_surface_labels_does_not_run_a_fine_scan(self):
        doc,page,sha,inventory,associations=fixture(labels=('Building',));self.addCleanup(doc.close)
        with patch.object(ordinary_surfaces,'closed_source_faces',side_effect=AssertionError('No scan')):
            result=surfaces.page_candidates(page,sha,1,inventory,associations)
        self.assertEqual(result['status'],'no_visible_surface_labels')
        self.assertEqual(result['candidates'],[])

    def test_failed_fine_extraction_retains_coarse_input_and_explicit_gap(self):
        doc,page,sha,inventory,associations=fixture();self.addCleanup(doc.close)
        with patch.object(ordinary_surfaces,'closed_source_faces',side_effect=ValueError('Bounded failure')):
            result=surfaces.page_candidates(page,sha,1,inventory,associations)
        self.assertEqual(result['reason'],'fine_source_geometry_failed')
        self.assertFalse(result['analysis_complete']);self.assertEqual(result['candidates'],[])
        self.assertEqual(result['source_inventory_sha256'],digest(inventory))


if __name__=='__main__': unittest.main()
