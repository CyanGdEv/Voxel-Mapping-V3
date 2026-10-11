import copy
from pathlib import Path
import tempfile
import unittest
from shapely.affinity import scale, translate
from shapely.geometry import box, Polygon
from voxel_mapper.mapped_alignment_checks import check


class HeldOutMapTests(unittest.TestCase):
    def fixture(self):
        centres = [(0,0),(100,0),(0,100),(100,100),(45,60)]
        objects = [{'candidate_id':str(i),'geometry':box(x,y,x+10+i,y+12+i)} for i,(x,y) in enumerate(centres)]
        refs = [{'id':'r'+o['candidate_id'],'geometry':translate(scale(o['geometry'],.1,.1,origin=(0,0)),400000,300000)} for o in objects]
        hypothesis = {'supports':[{'candidate_id':o['candidate_id'],'reference_id':r['id']} for o,r in zip(objects,refs)]}
        return objects, refs, [hypothesis]

    def test_printed_scale_and_all_held_out_boundaries_pass_but_never_register(self):
        objects, refs, fits = self.fixture(); result = check(objects,refs,fits,expected_scale=.1)
        self.assertEqual(result['status'],'map_consistent_candidate')
        checks = result['hypotheses'][0]['held_out_checks']; self.assertEqual(len(checks),5)
        for row in checks:
            self.assertNotIn(row['candidate_id'],row['fit_landmark_ids'])
            self.assertTrue(row['passed'])
        self.assertFalse(result['registration_verified']); self.assertEqual(result['independent_survey_checkpoints'],0)
        from voxel_mapper.reconstruction.registration import require_accepted_review
        with self.assertRaises(ValueError): require_accepted_review(result)

    def test_wrong_or_missing_printed_scale_is_withheld(self):
        objects, refs, fits = self.fixture()
        for expected in [None,.2]:
            self.assertEqual(check(objects,refs,fits,expected_scale=expected)['status'],'withheld')

    def test_one_shifted_landmark_cannot_validate_its_own_fit(self):
        objects, refs, fits = self.fixture(); refs[-1]['geometry'] = translate(refs[-1]['geometry'],2,0)
        result = check(objects,refs,fits,expected_scale=.1)
        self.assertEqual(result['status'],'withheld')
        self.assertFalse(result['hypotheses'][0]['held_out_checks'][-1]['passed'])

    def test_centroid_agreement_does_not_hide_wrong_boundary(self):
        objects, refs, fits = self.fixture(); refs[-1]['geometry'] = scale(refs[-1]['geometry'],2,2)
        result = check(objects,refs,fits,expected_scale=.1)
        self.assertEqual(result['status'],'withheld')
        self.assertLess(result['hypotheses'][0]['held_out_checks'][-1]['intersection_over_union'],.85)

    def test_fewer_than_five_reused_or_collinear_landmarks_fail(self):
        objects, refs, fits = self.fixture()
        fits[0]['supports'] = fits[0]['supports'][:3]
        self.assertEqual(check(objects,refs,fits,expected_scale=.1)['status'],'withheld')
        objects, refs, fits = self.fixture(); fits[0]['supports'][-1] = fits[0]['supports'][0]
        self.assertEqual(check(objects,refs,fits,expected_scale=.1)['status'],'withheld')
        objects, refs, fits = self.fixture()
        for i in range(5):
            objects[i]['geometry'] = box(i*100,0,i*100+10,10)
            refs[i]['geometry'] = translate(scale(objects[i]['geometry'],.1,.1,origin=(0,0)),400000,300000)
        self.assertEqual(check(objects,refs,fits,expected_scale=.1)['status'],'withheld')

    def test_alternative_location_and_exhausted_search_do_not_qualify(self):
        objects, refs, fits = self.fixture()
        self.assertEqual(check(objects,refs,fits+copy.deepcopy(fits),expected_scale=.1)['status'],'withheld')
        self.assertEqual(check(objects,refs,fits,expected_scale=.1,search_flags=['seed_fit_budget_exhausted'])['status'],'withheld')

    def test_invalid_thresholds_are_refused(self):
        objects, refs, fits = self.fixture()
        for options in [{'expected_scale':True},{'expected_scale':float('nan')},{'tolerance_m':2},
                        {'scale_tolerance':.1},{'min_iou':float('nan')}]:
            with self.assertRaises(ValueError):check(objects,refs,fits,**options)

    def test_nested_landmarks_cannot_inflate_support(self):
        objects, refs, fits = self.fixture()
        objects[-1]['geometry'] = box(1,1,4,5)
        refs[-1]['geometry'] = translate(scale(objects[-1]['geometry'],.1,.1,origin=(0,0)),400000,300000)
        result = check(objects,refs,fits,expected_scale=.1)
        self.assertIn('overlapping_map_landmarks',result['hypotheses'][0]['reasons'])

    def test_native_scale_labels_check_visibility_and_ambiguity(self):
        import pymupdf
        from voxel_mapper.mapped_alignment_checks import printed_scale_review
        with tempfile.TemporaryDirectory() as directory:
            for mode in ['visible','hidden','ambiguous']:
                path = Path(directory)/(mode+'.pdf')
                with pymupdf.open() as document:
                    page = document.new_page(width=300,height=300)
                    page.insert_text((20,40),'Scale 1 : 200',fontsize=10)
                    if mode == 'hidden':page.draw_rect(pymupdf.Rect(15,20,110,45),fill=(1,1,1),color=None)
                    if mode == 'ambiguous':page.insert_text((20,80),'1 : 500',fontsize=10)
                    document.save(path)
                review = printed_scale_review(path,1)
                if mode == 'visible':
                    self.assertEqual(review['status'],'one_visible_printed_scale')
                    self.assertAlmostEqual(review['expected_metres_per_pdf_point'],200*.0254/72)
                else:self.assertIsNone(review['expected_metres_per_pdf_point'])
