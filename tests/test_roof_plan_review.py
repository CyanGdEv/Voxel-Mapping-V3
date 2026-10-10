import unittest
from shapely.affinity import affine_transform
from shapely.geometry import box
from voxel_mapper.roof_plan_review import page_scale,fixed_scale_edges


class RoofPlanReviewTests(unittest.TestCase):
    def test_page_scale_excludes_alternate_paper_and_gradients(self):
        r=page_scale('1/250 @ A1 1/500 @ A3\n1:11 Gradient 1:3 slope',841/25.4*72,594/25.4*72)
        self.assertEqual(r['denominator'],250)
        self.assertEqual(len(r['explicit_paper_scales']),2)
        self.assertEqual(page_scale('1/250 @ A1 1/200 @ A1',841/25.4*72,594/25.4*72)['status'],'withheld')
        self.assertEqual(page_scale('1/250 @ A1',400,600)['status'],'withheld')

    def test_exact_boundary_keeps_orientation_ambiguity_and_no_checkpoints(self):
        p=box(0,0,200,100);s=250*.0254/72
        target=affine_transform(p,[s,0,0,s,407000,343000])
        r=fixed_scale_edges(p,target,250)
        self.assertAlmostEqual(r['best_fit']['intersection_over_union'],1,places=7)
        self.assertGreaterEqual(len(r['equivalent_orientations']),2)
        self.assertIn('ambiguous_boundary_orientation',r['review_flags'])
        self.assertFalse(r['registration_verified'])
        self.assertEqual(r['accepted_checkpoints'],0)
        self.assertEqual(len(r['best_fit']['edge_diagnostics']),4)
        self.assertLess(r['best_fit']['edge_diagnostics'][0]['distance_to_envelope_m']['max'],1e-6)

    def test_fixed_scale_does_not_absorb_size_disagreement(self):
        p=box(0,0,200,100);s=250*.0254/72
        target=affine_transform(p,[s*1.2,0,0,s*1.2,407000,343000])
        r=fixed_scale_edges(p,target,250)
        self.assertAlmostEqual(r['best_fit']['scale_metres_per_pdf_point'],s)
        self.assertLess(r['best_fit']['intersection_over_union'],.8)
        self.assertIn('poor_boundary_agreement',r['review_flags'])
