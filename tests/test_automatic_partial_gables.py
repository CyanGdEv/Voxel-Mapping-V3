import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from voxel_mapper import automatic_gable_roof as roof
from voxel_mapper import automatic_partial_gables as partial
from voxel_mapper.generation_cycles import atomic_json
from tests import test_automatic_gable_roof as roof_tests
from tests import test_automatic_facade_profile as profile_tests


class PartialGableTests(unittest.TestCase):
    def gray(self):
        image = Image.new('L', (320, 240), 255)
        # The long left side can pass the parent; the occluded right side cannot.
        ImageDraw.Draw(image).line([(50, 180), (200, 90), (253, 122)], fill=0, width=2)
        return np.asarray(image).copy()

    def line(self, name, slope, intercept, interval):
        return {'id': name, 'slope': slope, 'intercept': intercept,
            'source_x_interval': interval, 'pitch_magnitude_degrees': abs(float(np.degrees(np.arctan(slope))))}

    def original(self):
        return {'threshold': 220, 'lines': [self.line('long', -.6, 210., [50, 200])], 'gable_pairs': []}

    def short(self):
        return self.line('short', .6, -30., [202, 253])

    def fixture(self, root):
        original_gray = profile_tests.FacadeProfileTests.gray
        def extra(instance):
            im = Image.fromarray(original_gray(instance))
            ImageDraw.Draw(im).line([(170,160),(250,112),(290,136)],fill=0,width=2)
            return np.asarray(im).copy()
        with patch.object(profile_tests.FacadeProfileTests,'gray',extra):
            profile, preview, c, v, corpus, output = roof_tests.GableRoofTests().fixture(root)
        r = roof.build(profile, preview, c, v, corpus, output)
        return Path(r['directory']), profile, preview, c, v, corpus, root/'partial'

    def test_short_original_stroke_extends_evidence_without_modifying_parent(self):
        gray = self.gray(); before = gray.copy(); excluded = np.zeros_like(gray, bool)
        old = roof.slope_lines(gray, excluded, 220, lambda: None)
        scan = partial.short_slope_lines(gray, excluded, 220, lambda: None)
        self.assertFalse(any(l['slope'] > 0 for l in old['lines']))
        self.assertTrue(any(l['slope'] > 0 for l in scan['lines']))
        np.testing.assert_array_equal(gray, before)
        for l in scan['lines']:
            self.assertTrue(24 <= l['source_x_interval'][1]-l['source_x_interval'][0] < 64)
            self.assertTrue(all(p['gray']==gray[p['y'],p['x']] and p['role']==('fit' if p['x']%2==0 else 'check') for p in l['source_pixels']))
            self.assertFalse(l['source_gaps_filled']); self.assertEqual(l['source_points_removed_after_fit'], 0)

    def test_large_original_gaps_are_split_before_fit_without_corridor_extension(self):
        gray = self.gray(); gray[:,225:235] = 255
        scan = partial.short_slope_lines(gray, np.zeros_like(gray,bool), 220, lambda: None)
        for l in scan['lines']:
            columns = np.unique([p['x'] for p in l['source_pixels']])
            self.assertLessEqual(np.diff(columns).max(), 4)
            self.assertFalse(columns.min()<225 and columns.max()>=235)

    def test_native_exclusions_prevent_short_proposals_and_invalid_inputs_fail(self):
        gray = self.gray(); excluded = np.ones_like(gray,bool)
        self.assertEqual(partial.short_slope_lines(gray,excluded,235,lambda:None)['lines'], [])
        for bad_gray,bad_mask,t in [(gray.astype(float),excluded,220),(gray,excluded.astype('uint8'),220),(gray,excluded,200)]:
            with self.assertRaises(ValueError): partial.short_slope_lines(bad_gray,bad_mask,t,lambda:None)

    def test_pair_keeps_original_long_line_and_does_not_infer_depth_or_mesh(self):
        old = self.original(); before = copy.deepcopy(old)
        r = partial.partial_pairs(old,[self.short()],.1,250.,lambda:None)
        self.assertEqual(old,before); self.assertEqual(len(r['pairs']),1)
        p = r['pairs'][0]
        self.assertEqual(p['inferred_ridge_pixel'],[200.,90.]);self.assertEqual(p['nominal_ridge_height_m'],16.)
        self.assertEqual(p['status'],'conditional_partial_gable_source_support')
        self.assertIsNone(p['independent_depth_measurement_m']); self.assertIsNone(p['complete_wing_mesh'])
        self.assertFalse(p['source_long_line_refitted']);self.assertFalse(p['world_placement_eligible'])

    def test_intersection_inside_support_and_pitch_disagreement_stay_as_held_pairs(self):
        old = self.original();old['lines'][0]['source_x_interval']=[50,240]
        p = partial.partial_pairs(old,[self.short()],.1,250.,lambda:None)['pairs'][0]
        self.assertEqual(p['status'],'partial_gable_source_check_held');self.assertFalse(p['source_ridge_at_visible_support_ends'])
        old=self.original();short=self.line('steeper',.8,-70.,[202,253])
        p=partial.partial_pairs(old,[short],.1,250.,lambda:None)['pairs'][0]
        self.assertTrue(p['source_ridge_at_visible_support_ends']);self.assertFalse(p['paired_pitch_consistency_within_two_degrees'])
        self.assertEqual(p['status'],'partial_gable_source_check_held')

    def test_already_paired_parent_lines_and_far_intersections_are_not_promoted(self):
        old=self.original();old['gable_pairs']=[{'left_line_id':'long','right_line_id':'other'}]
        self.assertEqual(partial.partial_pairs(old,[self.short()],.1,250.,lambda:None)['pairs'],[])
        old=self.original();short=self.short();short['intercept']-=200
        self.assertEqual(partial.partial_pairs(old,[short],.1,250.,lambda:None)['pairs'],[])

    def test_cross_threshold_checks_retain_all_alternatives_and_failures_without_refit(self):
        a=partial.partial_pairs(self.original(),[self.short()],.1,250.,lambda:None)['pairs'][0]
        b=copy.deepcopy(a);b['id']='different';b['inferred_ridge_pixel']=[201.,90.]
        c=copy.deepcopy(a);c['id']='held';c['inferred_ridge_pixel']=[220.,90.]
        r=partial.threshold_checks([{'pairs':[a]},{'pairs':[b,c]}],lambda:None)
        self.assertEqual([p['status'] for p in r],['source_threshold_measurements_agree','source_threshold_measurements_disagree'])
        self.assertTrue(all(not p['lines_refitted'] and not p['physical_correspondence_verified'] for p in r))
        self.assertEqual(partial.threshold_checks([{'pairs':[]},{'pairs':[b]}],lambda:None),[])

    def test_source_and_pair_budgets_fail_closed(self):
        gray=np.zeros((300,300),np.uint8)
        with patch.object(partial.ndimage,'sobel',side_effect=lambda values,axis:np.ones_like(values)):
            with self.assertRaisesRegex(OverflowError,'source_pixel'):partial.short_slope_lines(gray,np.zeros_like(gray,bool),220,lambda:None)
        old=self.original();old['lines']*=129
        with self.assertRaisesRegex(OverflowError,'pair_input'):partial.partial_pairs(old,[self.short()],.1,250.,lambda:None)
        for bad in (0,True,100001):
            with self.assertRaises(ValueError):partial.build('','','','','','','',max_checks=bad)

    def test_end_to_end_source_replay_keeps_parent_mesh_and_zero_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));before=(args[0]/'gable-roof-review.json').read_bytes()
            r=partial.build(*args);self.assertEqual(r,partial.build(*args))
            self.assertEqual(before,(args[0]/'gable-roof-review.json').read_bytes())
            self.assertEqual(r['new_roof_models'],[]);self.assertFalse(r['parent_models_changed'])
            self.assertEqual(r['counts']['source_views'],1);self.assertEqual(r['accepted_physical_components'],0)

    def test_early_and_late_budget_holds_discard_partial_source_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));r=partial.build(*args,max_checks=1)
            self.assertEqual(r['status'],'partial_gable_budget_withheld');self.assertEqual(r['views'],[])
            with patch.object(partial,'partial_pairs',side_effect=OverflowError('late_pair_budget')):
                r=partial.build(*args)
            self.assertEqual(r['views'],[]);self.assertEqual(r['counts']['short_source_lines'],0)

    def test_changed_parent_raster_or_cached_output_is_rejected(self):
        for mode in ('parent','raster','cache'):
            with tempfile.TemporaryDirectory() as tmp:
                args=self.fixture(Path(tmp))
                if mode=='parent':
                    path=args[0]/'gable-roof-review.json';value=json.loads(path.read_text());value['models']=[];atomic_json(path,value)
                elif mode=='raster':(args[4]/'elevation.png').write_bytes(b'changed')
                else:
                    r=partial.build(*args);(Path(r['directory'])/'partial-gables.json').write_text('{}')
                with self.assertRaises(ValueError):partial.build(*args)

    def test_independent_original_pixel_audit_replays_the_source_chain(self):
        from scripts.audit_automatic_partial_gables import audit
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));r=partial.build(*args)
            checked=audit(r['directory'],*args[:-1],Path(tmp)/'audit.json')
            self.assertEqual(checked['status'],'passed');self.assertEqual(checked['checked']['source_threshold_variants'],2)
            self.assertEqual(checked['world_geometry_additions'],0)
            self.assertGreater(checked['checked']['separate_covariance_fits'],0)
            self.assertGreater(checked['checked']['whole_original_hough_groups'],0)


if __name__=='__main__':unittest.main()
