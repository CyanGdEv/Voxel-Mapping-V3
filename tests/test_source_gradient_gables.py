import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image,ImageDraw

from voxel_mapper import source_gradient_gables as gradient
from voxel_mapper import automatic_partial_gables as partial
from voxel_mapper.generation_cycles import atomic_json
from tests import test_automatic_partial_gables as parent_tests


class SourceGradientTests(unittest.TestCase):
    def gray(self):
        im=Image.new('L',(320,240),255);d=ImageDraw.Draw(im)
        d.line([(50,180),(200,90)],fill=0,width=2)
        d.line([(200,90),(253,122)],fill=228,width=2)
        return np.asarray(im).copy()

    def inventory(self):
        return {'view_id':'plan','document_sha256':'source','page':1,'nominal_metres_per_pdf_point':.1,
            'printed_claim':{'plan_level_or_form':'roof'},'source_components':[
            {'id':key,'geometry':{'type':'LineString','coordinates':[[0.,float(y)],[100.,float(y)]]},
                'rendering_status':'supported_straight_unclipped_polyline','curve_approximation':{'cubic_segments':0}}
            for key,y in [('z',0),('a',10),('b',20)]]}

    def fixture(self,root):
        gable,profile,preview,c,v,corpus,out=parent_tests.PartialGableTests().fixture(root)
        r=partial.build(gable,profile,preview,c,v,corpus,out)
        return Path(r['directory']),gable,profile,preview,c,v,corpus,root/'gradient'

    def test_bright_short_edge_recovered_by_both_contrast_levels_without_changing_source(self):
        gray=self.gray();before=gray.copy();mask=np.zeros_like(gray,bool)
        binary=partial.short_slope_lines(gray,mask,220,lambda:None)
        self.assertFalse(any(l['slope']>0 for l in binary['lines']))
        for contrast in (32,64):
            scan=gradient.gradient_lines(gray,mask,contrast,lambda:None)
            self.assertTrue(any(l['slope']>0 for l in scan['lines']))
            self.assertEqual(scan['gradient_cutoff'],contrast)
            for l in scan['lines']:
                self.assertTrue(all(p['gray']==gray[p['y'],p['x']] and p['role']==('fit' if p['x']%2==0 else 'check') for p in l['source_pixels']))
                self.assertEqual(l['source_points_removed_after_fit'],0);self.assertFalse(l['source_gaps_filled'])
        np.testing.assert_array_equal(gray,before)

    def test_large_gaps_native_exclusions_and_white_background_remain_excluded(self):
        gray=self.gray();gray[:,222:233]=255;mask=np.zeros_like(gray,bool)
        scan=gradient.gradient_lines(gray,mask,32,lambda:None)
        for l in scan['lines']:
            columns=np.unique([p['x'] for p in l['source_pixels']]);self.assertLessEqual(np.diff(columns).max(),4)
            self.assertFalse(columns.min()<222 and columns.max()>=233)
            self.assertTrue(all(p['gray']<250 for p in l['source_pixels']))
        self.assertEqual(gradient.gradient_lines(gray,np.ones_like(gray,bool),64,lambda:None)['lines'],[])

    def test_invalid_contrast_type_and_source_budgets_are_rejected(self):
        g=self.gray();m=np.zeros_like(g,bool)
        for a,b,c in [(g.astype(float),m,32),(g,m,220),(g,m.astype('uint8'),32)]:
            with self.assertRaises(ValueError):gradient.gradient_lines(a,b,c,lambda:None)
        g=np.zeros((300,300),np.uint8)
        with patch.object(gradient.ndimage,'sobel',side_effect=lambda values,axis:np.full_like(values,64)):
            with self.assertRaisesRegex(OverflowError,'source_pixel'):gradient.gradient_lines(g,np.zeros_like(g,bool),32,lambda:None)

    def test_plan_direction_roles_use_source_identity_before_target_and_preserve_points(self):
        inv=self.inventory();before=copy.deepcopy(inv);r=gradient.direction_cohorts(inv,lambda:None)
        self.assertEqual(inv,before);self.assertEqual(len(r['cohorts']),1);c=r['cohorts'][0]
        self.assertEqual(c['direction_witness_source_component_id'],'a')
        self.assertEqual(c['status'],'repeated_source_plan_direction')
        inv['source_components'].reverse();self.assertEqual(r,gradient.direction_cohorts(inv,lambda:None))
        self.assertTrue(all(not l['source_points_moved'] for l in c['lines']))
        inv['source_components'].pop();self.assertEqual(gradient.direction_cohorts(inv,lambda:None)['cohorts'][0]['status'],'insufficient_repeated_source_direction_support')

    def test_plan_curves_short_lines_and_component_overflow_do_not_supply_width_axes(self):
        inv=self.inventory();inv['source_components'][0]['curve_approximation']['cubic_segments']=1
        inv['source_components'][1]['geometry']['coordinates']=[[0.,0.],[1.,0.]]
        self.assertEqual(len(gradient.direction_cohorts(inv,lambda:None)['cohorts'][0]['lines']),1)
        inv['source_components']*=1400
        with self.assertRaises(OverflowError):gradient.direction_cohorts(inv,lambda:None)
        inv=self.inventory();inv['nominal_metres_per_pdf_point']=float('nan')
        with self.assertRaises(ValueError):gradient.direction_cohorts(inv,lambda:None)

    def test_oblique_projection_demonstrates_pitch_ambiguity_and_edge_on_hold(self):
        apparent=math.degrees(math.atan(math.tan(math.radians(30))/math.sqrt(.5)))
        self.assertAlmostEqual(gradient.projection_pitch(apparent,math.sqrt(.5)),30.,places=12)
        self.assertAlmostEqual(gradient.projection_pitch(apparent,1.),apparent)
        self.assertIsNone(gradient.projection_pitch(apparent,0.))
        self.assertIsNone(gradient.projection_pitch(apparent,math.sin(math.radians(4))))
        for p,f in [(90.,1.),(30.,float('nan')),(30.,1.1)]:
            with self.assertRaises(ValueError):gradient.projection_pitch(p,f)

    def test_variant_checks_keep_failures_and_shared_source_is_not_independent(self):
        parent=parent_tests.PartialGableTests();p=partial.partial_pairs(parent.original(),[parent.short()],.1,250.,lambda:None)['pairs'][0]
        q=copy.deepcopy(p);q['id']='near';q['inferred_ridge_pixel']=[201.,90.]
        r=copy.deepcopy(p);r['id']='far';r['inferred_ridge_pixel']=[220.,90.]
        checks=gradient.comparison_rows([p],[q,r],lambda:None,recipe='contrast',context={'source_parent_ink_threshold':220})
        self.assertEqual([c['status'] for c in checks],['source_variant_measurements_agree','source_variant_measurements_disagree'])
        self.assertTrue(all(c['original_source_pixels_can_be_shared'] and not c['independent_survey_checks'] and not c['lines_refitted'] for c in checks))

    def test_projection_keeps_all_plan_directions_and_never_selects_a_wing_mesh(self):
        plan=self.inventory();floor=copy.deepcopy(plan);floor['view_id']='floor';floor['printed_claim']['plan_level_or_form']='groundfloor';floor['document_sha256']='floor-source'
        directions=[gradient.direction_cohorts(v,lambda:None) for v in (plan,floor)]
        other=copy.deepcopy(directions[0]['cohorts'][0]);other['id']='perpendicular';other['source_direction_unit_vector']=[0.,1.];directions[0]['cohorts'].append(other)
        artwork={'id':'fixed','subject_page_key':['floor-source',1],'reference_page_key':['source',1],'subject_to_reference_linear_row_matrix':[[1.,0.],[0.,1.]]}
        frame={'id':'frame','diagnostic_axis':[1.,0.]};record={'target_elevation_view_ids':['elevation'],'target_view_key_candidate':['p',26,3],'frame_review':{'frames':[frame]}}
        reviews={'building_facade_links':{'frames':[record]},'artwork_scale_controls':{'pairs':[artwork]}}
        preview={'target_marker_checks':[{'pair_id':'fixed','key':['p',26,3],'status':'fixed_non_target_layout_agrees_at_target_annotation'}]}
        parent=parent_tests.PartialGableTests();pair=partial.partial_pairs(parent.original(),[parent.short()],.1,250.,lambda:None)['pairs'][0]
        rows=[{'view_id':'elevation','variants':[{'anchor_reviews':[{'pairs':[pair]}]}]}]
        c,d,p=gradient.plan_projection_reviews(rows,directions,{},reviews,preview,lambda:None)
        self.assertEqual(len(c),1);self.assertEqual(len(d),2);self.assertEqual(len(p),2)
        self.assertEqual(sum(v['status']=='edge_on_direction_pitch_withheld' for v in p),1)
        self.assertTrue(all(v['wing_depth_m'] is None and v['eave_endpoints'] is None and not v['true_pitch_verified'] for v in p))
        preview['target_marker_checks'][0]['status']='held'
        self.assertEqual(gradient.plan_projection_reviews(rows,directions,{},reviews,preview,lambda:None),([],[],[]))

    def test_complete_source_replay_keeps_prior_binary_hold_and_parent_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));before=(args[0]/'partial-gables.json').read_bytes();r=gradient.build(*args)
            self.assertEqual(r,gradient.build(*args));self.assertEqual(before,(args[0]/'partial-gables.json').read_bytes())
            self.assertFalse(r['previous_binary_threshold_hold_overridden']);self.assertFalse(r['parent_models_changed'])
            self.assertEqual(r['new_roof_models'],[]);self.assertEqual(r['accepted_physical_components'],0)

    def test_early_and_late_work_holds_discard_all_source_and_projection_reviews(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));r=gradient.build(*args,max_checks=1)
            self.assertEqual(r['status'],'source_gradient_gable_budget_withheld');self.assertEqual(r['views'],[])
            with patch.object(gradient,'direction_cohorts',side_effect=OverflowError('late_source_plan_budget')):r=gradient.build(*args)
            self.assertEqual(r['views'],[]);self.assertEqual(r['direction_reviews'],[]);self.assertEqual(r['pitch_projection_diagnostics'],[])
        for bad in (0,True,100001):
            with self.assertRaises(ValueError):gradient.build('','','','','','','','',max_checks=bad)

    def test_changed_parent_source_or_cache_is_rejected(self):
        for mode in ('parent','raster','cache'):
            with tempfile.TemporaryDirectory() as tmp:
                args=self.fixture(Path(tmp))
                if mode=='parent':
                    path=args[0]/'partial-gables.json';value=json.loads(path.read_text());value['views']=[];atomic_json(path,value)
                elif mode=='raster':(args[5]/'elevation.png').write_bytes(b'changed')
                else:
                    r=gradient.build(*args);(Path(r['directory'])/'source-gradient-gables.json').write_text('{}')
                with self.assertRaises(ValueError):gradient.build(*args)

    def test_independent_audit_reproduces_original_sources_and_gradient_support(self):
        from scripts.audit_source_gradient_gables import audit
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));r=gradient.build(*args)
            a=audit(r['directory'],*args[:-1],Path(tmp)/'audit.json')
            self.assertEqual(a['status'],'passed');self.assertGreater(a['checked']['original_gradient_source_pixels'],0)
            self.assertGreater(a['checked']['whole_original_hough_groups'],0)
            self.assertGreater(a['checked']['original_native_plan_lines'],0)


if __name__=='__main__':unittest.main()
