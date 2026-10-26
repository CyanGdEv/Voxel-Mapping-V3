"""Complete long-stroke scopes, exact paint provenance and bounded recovery."""
import copy
from concurrent.futures import CancelledError
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf
from shapely.geometry import box,shape

from voxel_mapper import drawing_geometry,ordinary_surfaces,planning_outline_semantics,planning_surface_footprints
from voxel_mapper import planning_curve_networks as networks,planning_curve_scopes as scopes
from voxel_mapper.building_spec import digest


class CompleteCurveScopeTests(unittest.TestCase):
    def source(self,*,mixed=False,gap=0,rotation=0,duplicates=0,second_style=False,opacity=1):
        d=pymupdf.open();self.addCleanup(d.close);p=d.new_page(width=1200,height=600)
        red=(1,0,0)
        p.draw_bezier((100,150),(300,60),(900,60),(1100,150),color=red,stroke_opacity=opacity)
        for a,b in (((1100,150),(1100,350)),((1100,350),(100,350)),((100,350),(100,150+gap))):
            p.draw_line(a,b,color=(0,0,0) if mixed else red)
        for i in range(duplicates):p.draw_bezier((100,150),(300,60-i*.1),(900,60-i*.1),(1100,150),color=red)
        if second_style:p.draw_bezier((100,170),(300,100),(900,100),(1100,170),color=(0,0,1))
        p.insert_text((540,240),'Path',fontsize=8);p.set_rotation(rotation)
        return d,p

    def surface(self,d,p):
        sha=hashlib.sha256(d.tobytes(no_new_id=True)).hexdigest()
        _,_,report=ordinary_surfaces.page_candidates(p,sha,1);inventory=report['source_outline_inventory']
        semantic=planning_outline_semantics.page_candidates(p,sha,1,inventory)
        return sha,planning_surface_footprints.page_candidates(p,sha,1,inventory,semantic)

    def test_long_original_curve_and_label_scope_form_a_complete_review_scope(self):
        d,p=self.source();before=d.tobytes(no_new_id=True);sha,surface=self.surface(d,p)
        previous=networks.page_review(p,sha,1,surface);self.assertEqual(previous['records'],[])
        plan=scopes.page_plan(p,sha,1,surface);self.assertTrue(plan['analysis_complete'])
        self.assertEqual(plan['anchor_count'],1);self.assertEqual(len(plan['regions']),1)
        anchor=plan['anchors'][0];self.assertEqual(anchor['ordinal'],0)
        self.assertEqual(anchor['source_operators_pdf_native'][0]['operator'],'c')
        self.assertEqual(anchor['source_operators_pdf_native'][0]['points'][0],[100,450])
        witness={k:v for k,v in anchor.items() if k!='source_witness_sha256'}
        self.assertEqual(digest(witness),anchor['source_witness_sha256'])
        self.assertTrue(box(*plan['regions'][0]['region_native_points']).covers(box(*anchor['native_bounds_pdf_points'])))
        for seed in surface['extraction']['regions']:
            self.assertTrue(box(*plan['regions'][0]['region_native_points']).covers(box(*seed['region_native_points'])))
        review=networks.page_review(p,sha,1,surface,source_scope_plan=plan)
        self.assertTrue(review['analysis_complete'],review.get('reason'));self.assertEqual(len(review['records']),1)
        self.assertTrue(review['complete_anchor_coverage'][0]['eligible_subpaths_retained'])
        self.assertEqual(len(review['records'][0]['candidate']['source_edges']),4)
        self.assertFalse(review['physical_role_inferred_from_style']);self.assertFalse(review['world_placement_eligible'])
        self.assertEqual(review['world_geometry_additions'],0);self.assertEqual(d.tobytes(no_new_id=True),before)
        with self.assertRaises(ValueError):planning_outline_semantics.page_candidates(p,sha,1,review)

    def test_separate_paint_styles_cannot_close_each_others_half_ring(self):
        d=pymupdf.open();self.addCleanup(d.close);p=d.new_page(width=1200,height=600)
        p.draw_bezier((100,150),(300,60),(900,60),(1100,150),color=(1,0,0))
        p.draw_bezier((1100,150),(900,400),(300,400),(100,150),color=(0,0,1))
        p.insert_text((540,240),'Path',fontsize=8)
        sha,surface=self.surface(d,p);plan=scopes.page_plan(p,sha,1,surface)
        self.assertEqual(len(plan['regions']),2)
        review=networks.page_review(p,sha,1,surface,source_scope_plan=plan)
        self.assertTrue(review['analysis_complete']);self.assertEqual(review['records'],[])
        for region in review['regions']:
            self.assertEqual(region['counts']['source_edges'],1)

    def test_a_different_colour_is_not_guessed_to_be_a_matching_boundary(self):
        d,p=self.source(mixed=True);sha,surface=self.surface(d,p);plan=scopes.page_plan(p,sha,1,surface)
        review=networks.page_review(p,sha,1,surface,source_scope_plan=plan)
        self.assertTrue(review['analysis_complete']);self.assertEqual(review['records'],[])
        self.assertEqual(review['extraction']['candidates'],1)

    def test_small_source_gap_remains_open_after_scope_expansion(self):
        d,p=self.source(gap=.001);sha,surface=self.surface(d,p);plan=scopes.page_plan(p,sha,1,surface)
        review=networks.page_review(p,sha,1,surface,source_scope_plan=plan)
        self.assertTrue(review['analysis_complete']);self.assertEqual(review['records'],[])

    def test_cropped_source_stroke_cannot_be_completed_with_a_cropped_polygon(self):
        d,p=self.source();p.set_cropbox(pymupdf.Rect(200,50,1150,550));sha,surface=self.surface(d,p)
        surface=copy.deepcopy(surface)
        surface['extraction']={'regions':[{'region_native_points':[400,200,700,510]}]}
        plan=scopes.page_plan(p,sha,1,surface)
        self.assertTrue(plan['analysis_complete']);self.assertEqual(plan['anchors'],[])
        self.assertGreater(plan['counts']['complete_stroke_outside_original_frame'],0)

    def test_nonopaque_source_does_not_select_a_style_family(self):
        d,p=self.source(opacity=.5);sha,surface=self.surface(d,p);plan=scopes.page_plan(p,sha,1,surface)
        self.assertEqual(plan['anchors'],[]);self.assertGreater(plan['counts']['nonopaque_or_optional_layer'],0)

    def test_whole_source_that_already_fits_does_not_expand_the_scope(self):
        d,p=self.source();sha,surface=self.surface(d,p);surface=copy.deepcopy(surface)
        surface['extraction']['regions']=[{'region_native_points':[10,10,1190,590]}]
        plan=scopes.page_plan(p,sha,1,surface)
        self.assertEqual(plan['anchors'],[]);self.assertEqual(plan['regions'],[])
        self.assertEqual(plan['counts']['already_inside_original_scope'],1)

    def test_unrelated_source_curves_outside_seed_windows_do_not_select_a_family(self):
        d,p=self.source();sha,surface=self.surface(d,p);surface=copy.deepcopy(surface)
        surface['extraction']['regions']=[{'region_native_points':[20,20,50,50]}]
        plan=scopes.page_plan(p,sha,1,surface)
        self.assertEqual(plan['anchors'],[]);self.assertEqual(plan['counts']['outside_original_seed_scopes'],1)

    def test_primitive_close_path_is_not_misread_as_an_open_curve_anchor(self):
        d,p=self.source();p.draw_circle((600,100),200,color=(0,1,0));sha,surface=self.surface(d,p)
        plan=scopes.page_plan(p,sha,1,surface)
        self.assertTrue(all(a['stroke_style']['stroke_rgb']!=[0,1,0] for a in plan['anchors']))
        self.assertGreater(plan['counts'].get('no_supported_original_open_curve',0)+
                           plan['counts'].get('complete_stroke_outside_original_frame',0),0)

    def test_scope_anchor_operator_point_and_comparison_limits_withhold_all_scopes(self):
        d,p=self.source(duplicates=1,second_style=True);sha,surface=self.surface(d,p)
        for options in ({'max_regions':1},{'max_anchors':1},{'max_source_operators':1},
                        {'max_flattened_points':1},{'max_scope_checks':1}):
            with self.subTest(options=options):
                plan=scopes.page_plan(p,sha,1,surface,options=options)
                self.assertFalse(plan['analysis_complete']);self.assertEqual(plan['anchors'],[])
                self.assertEqual(plan['regions'],[]);self.assertEqual(plan['region_stroke_styles'],[])

    def test_scope_output_quota_withholds_complete_result(self):
        d,p=self.source(duplicates=30);sha,surface=self.surface(d,p)
        plan=scopes.page_plan(p,sha,1,surface,options={'max_output_bytes':16384})
        self.assertFalse(plan['analysis_complete']);self.assertEqual(plan['regions'],[])
        self.assertLessEqual(len(json.dumps(plan).encode()),16384)

    def test_existing_network_quotas_still_apply_to_expanded_source(self):
        d,p=self.source();sha,surface=self.surface(d,p);plan=scopes.page_plan(p,sha,1,surface)
        for options in ({'max_native_candidates':1},{'max_native_points':2},{'max_segments':1}):
            with self.subTest(options=options):
                review=networks.page_review(p,sha,1,surface,source_scope_plan=plan,options=options)
                self.assertFalse(review['analysis_complete']);self.assertEqual(review['records'],[])

    def test_source_identity_and_scope_plan_content_changes_are_rejected(self):
        d,p=self.source();sha,surface=self.surface(d,p);plan=scopes.page_plan(p,sha,1,surface)
        with self.assertRaises(ValueError):scopes.page_plan(p,'a'*64,1,surface)
        with self.assertRaises(ValueError):scopes.page_plan(p,sha,2,surface)
        altered=copy.deepcopy(plan);altered['source_surface_analysis_sha256']='b'*64
        with self.assertRaises(ValueError):networks.page_review(p,sha,1,surface,source_scope_plan=altered)
        altered=copy.deepcopy(plan);altered['source_content_sha256']='c'*64
        review=networks.page_review(p,sha,1,surface,source_scope_plan=altered)
        self.assertFalse(review['analysis_complete']);self.assertEqual(review['records'],[])

    def test_failed_planning_is_not_replaced_with_a_partial_or_default_scope(self):
        d,p=self.source();sha,surface=self.surface(d,p);plan=scopes.page_plan(p,sha,1,surface)
        plan['analysis_complete']=False
        review=networks.page_review(p,sha,1,surface,source_scope_plan=plan)
        self.assertFalse(review['analysis_complete']);self.assertEqual(review['records'],[])
        surface['analysis_complete']=False
        plan=scopes.page_plan(p,sha,1,surface);self.assertFalse(plan['analysis_complete'])

    def test_style_selector_is_exact_and_preserves_original_ordinals(self):
        d,p=self.source();sha,surface=self.surface(d,p);plan=scopes.page_plan(p,sha,1,surface)
        opts={'region_native_windows':[r['region_native_points'] for r in plan['regions']],
              'source_region_stroke_styles':plan['region_stroke_styles'],'open_stroked_primitives_only':True}
        rows,report=drawing_geometry.extract_page(p,sha,1,**opts)
        self.assertEqual(report['candidates'],4)
        self.assertEqual(sorted(ref['ordinal'] for row in rows for ref in row['paint_references']),[0,1,2,3])
        altered=copy.deepcopy(opts);altered['source_region_stroke_styles'][0]['stroke_rgb'][1]=.000001
        other,other_report=drawing_geometry.extract_page(p,sha,1,**altered)
        self.assertEqual(other,[]);self.assertEqual(other_report['candidates'],0)

    def test_malformed_or_unbounded_style_selectors_are_rejected(self):
        base={'region_native_windows':[[0,0,100,100]],'open_stroked_primitives_only':True,
              'source_region_stroke_styles':[{'stroke_rgb':[1,0,0],'width_pdf_points':1,'dashes_pdf':'[] 0'}]}
        for change in ({'open_stroked_primitives_only':False},{'source_region_stroke_styles':[]},
                       {'source_region_stroke_styles':[{'stroke_rgb':[1,0,0],'width_pdf_points':True,'dashes_pdf':'[] 0'}]},
                       {'source_region_stroke_styles':[{'stroke_rgb':[1,0,0],'width_pdf_points':1,'dashes_pdf':'[2 2] 0'}]}):
            with self.subTest(change=change),self.assertRaises(ValueError):drawing_geometry.validated_options({**base,**change})

    def test_rotation_repeat_and_cancellation_preserve_original_source(self):
        d,p=self.source(rotation=90);before=d.tobytes(no_new_id=True);sha,surface=self.surface(d,p)
        a=scopes.page_plan(p,sha,1,surface);b=scopes.page_plan(p,sha,1,surface)
        self.assertEqual(a,b);self.assertEqual(p.rotation,90);self.assertEqual(d.tobytes(no_new_id=True),before)
        self.assertEqual(a['anchor_count'],1)
        self.assertEqual(a['anchors'][0]['source_operators_pdf_native'][0]['points'][0],[100,450])
        with self.assertRaises(CancelledError):scopes.page_plan(p,sha,1,surface,cancelled=lambda:True)
        calls=0
        def stop():
            nonlocal calls
            calls+=1;return calls>6
        with self.assertRaises(CancelledError):scopes.page_plan(p,sha,1,surface,cancelled=stop)

    def test_invalid_expanded_or_boolean_scope_limits_are_rejected(self):
        d,p=self.source();sha,surface=self.surface(d,p)
        for options in ({'max_regions':33},{'max_anchors':True},{'max_output_bytes':100},{'unknown':3}):
            with self.assertRaises(ValueError):scopes.page_plan(p,sha,1,surface,options=options)

    def test_original_source_cache_is_shared_across_plan_and_review(self):
        d,p=self.source();sha,surface=self.surface(d,p)
        factory=ordinary_surfaces._source_page_cache
        with patch.object(ordinary_surfaces,'_source_page_cache',wraps=factory) as create:
            plan,review=scopes.plan_and_review(p,sha,1,surface)
        self.assertEqual(create.call_count,1);self.assertEqual(len(review['records']),1)
        self.assertEqual(plan,scopes.page_plan(p,sha,1,surface))

    def test_another_page_or_changed_source_cannot_supply_cached_strokes(self):
        d,p=self.source();sha,surface=self.surface(d,p);cache=ordinary_surfaces._source_page_cache(p)
        plan=scopes.page_plan(p,sha,1,surface,_cache=cache)
        d2,p2=self.source();sha2,surface2=self.surface(d2,p2)
        wrong=scopes.page_plan(p2,sha2,1,surface2,_cache=cache)
        self.assertFalse(wrong['analysis_complete'])
        p.insert_text((20,30),'Changed original',fontsize=8)
        changed=scopes.page_plan(p,sha,1,surface,_cache=cache)
        self.assertFalse(changed['analysis_complete'])
        review=networks.page_review(p,sha,1,surface,source_scope_plan=plan,_source_cache=cache)
        self.assertFalse(review['analysis_complete']);self.assertEqual(review['records'],[])

    def test_native_clip_scope_is_not_removed_by_the_style_selector(self):
        d,p=self.source();_,surface=self.surface(d,p)
        content=p.read_contents();xref=d.get_new_xref();d.update_object(xref,'<<>>')
        d.update_stream(xref,b'q 0 0 10 10 re W n\n'+content+b'\nQ')
        d.xref_set_key(p.xref,'Contents',f'{xref} 0 R')
        sha=hashlib.sha256(d.tobytes(no_new_id=True)).hexdigest()
        surface=copy.deepcopy(surface);surface['document_sha256']=sha
        plan=scopes.page_plan(p,sha,1,surface)
        self.assertTrue(plan['analysis_complete']);self.assertEqual(plan['anchors'],[])
        self.assertGreater(plan['counts']['complete_stroke_crosses_clip'],0)

    def test_other_style_crossings_and_later_paint_still_withhold_a_ring(self):
        for crossing in (True,False):
            with self.subTest(crossing=crossing):
                d,p=self.source()
                if crossing:p.draw_line((50,280),(1150,280),color=(0,0,0))
                else:p.draw_rect((1090,260,1110,280),color=None,fill=(1,1,1))
                sha,surface=self.surface(d,p);plan,review=scopes.plan_and_review(p,sha,1,surface)
                self.assertTrue(review['analysis_complete']);self.assertEqual(review['records'],[])
                self.assertGreater(review['counts'].get('omitted_original_stroke_conflict_faces_withheld',0)+
                    review['covered_boundaries_withheld'],0)

    def test_full_pilot_exposes_complete_scope_review_without_exporting_the_ring(self):
        from voxel_mapper import planning_area_pilot as pilot
        d,p=self.source();p.draw_rect((20,400,150,500));p.insert_text((30,450),'Building',fontsize=8)
        p.insert_text((50,560),'Site Plan Proposed | 1:100',fontsize=10)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);data=d.tobytes();(root/'source.pdf').write_bytes(data)
            sha=hashlib.sha256(data).hexdigest()
            config={'version':pilot.VERSION,'area_id':'synthetic-complete-curves','application_references':['TEST'],
                'documents':[{'file':'source.pdf','sha256':sha,'title':'Synthetic complete curve source',
                    'role':'site-plan','drawing_state':'proposed','application_reference':'TEST'}]}
            report=pilot.run(config,lambda name:root/name,root/'out')
            self.assertEqual(report['summary']['completed_pages'],1)
            record=report['pages'][0];self.assertIsNotNone(record['complete_curve_scope_overlay'])
            page=json.loads((root/'out'/record['evidence_file']).read_text())
            self.assertEqual(len(page['curve_network_review']['records']),0)
            self.assertEqual(len(page['complete_curve_scope_review']['records']),1)
            self.assertEqual(page['area_layout']['summary']['nominal_area_building_candidates'],1)
            self.assertEqual(page['area_layout']['summary']['nominal_area_path_plaza_candidates'],0)
            self.assertIn('voxel_mapper.planning_curve_scopes',report['contract']['implementations'])
            self.assertIn('Inspect complete long-curve source scopes',(root/'out/review.html').read_text())
            for name,pin in report['output_sha256'].items():
                self.assertEqual(hashlib.sha256((root/'out'/name).read_bytes()).hexdigest(),pin)


if __name__=='__main__':unittest.main()
