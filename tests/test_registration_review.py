import unittest
from voxel_mapper.reconstruction.registration import review_registration,apply_registration

class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.c=[{'id':str(i),'local':p,'target':[100-p[1],200+p[0]]} for i,p in enumerate([[0,0],[10,0],[0,10]])]
        self.q=[{'id':'q'+str(i),'local':p,'target':[100-p[1],200+p[0]]} for i,p in enumerate([[8,8],[3,6]])]
    def test_rotation_translation_independent_fit(self):
        r=review_registration(self.c,self.q);self.assertEqual(r['status'],'accepted_horizontal_fit');self.assertAlmostEqual(r['rotation_degrees'],90)
        out=apply_registration([[1,2]],r)[0];self.assertAlmostEqual(out[0],98);self.assertAlmostEqual(out[1],201)
    def test_perfect_control_fit_without_checks_is_withheld(self):
        r=review_registration(self.c,[]);self.assertEqual(r['status'],'withheld')
        with self.assertRaises(ValueError):apply_registration([[1,2]],r)
    def test_bad_independent_point_and_unexpected_scale_withheld(self):
        self.q[0]['target'][0]+=4;self.assertIn('independent_checkpoint_error',review_registration(self.c,self.q)['reasons'])
        self.assertIn('unexpected_scale',review_registration(self.c,self.q,expected_scale=2)['reasons'])
    def test_reused_points_collinear_and_nonfinite_rejected(self):
        with self.assertRaises(ValueError):review_registration(self.c,[self.c[0],self.c[1]])
        self.c[2]['local']=[20,0]
        with self.assertRaises(ValueError):review_registration(self.c,self.q)
        self.c[2]['local']=[float('nan'),1]
        with self.assertRaises(ValueError):review_registration(self.c,self.q)

    def test_failed_review_blocks_feature_even_with_manual_accepted_flag(self):
        from voxel_mapper.reconstruction.model import Source,Feature,EvidenceMissing
        report=review_registration(self.c,[])
        source=Source('plan','planning','fixture://plan','test','EPSG:27700',registration_status='accepted',metadata={'horizontal_registration_review':report})
        feature=Feature('point','marker',{'type':'Point','coordinates':[100,200]},'plan')
        with self.assertRaises(EvidenceMissing):feature.validate({'plan':source},None)
        source=Source(**{**source.__dict__,'metadata':{'horizontal_registration_review':review_registration(self.c,self.q)}})
        self.assertEqual(feature.validate({'plan':source},None).geom_type,'Point')

    def test_extrapolation_outside_verified_domain_rejected(self):
        r=review_registration(self.c,self.q)
        with self.assertRaises(ValueError):apply_registration([[100,100]],r)
