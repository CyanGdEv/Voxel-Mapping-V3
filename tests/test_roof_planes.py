import unittest
import numpy as np
from shapely.geometry import shape
from voxel_mapper.roof_planes import plane_patches


class RoofPlaneTests(unittest.TestCase):
    def fixture(self):
        rng=np.random.default_rng(7);points=[]
        for start,height in [(0,8),(12,11)]:
            for x in np.linspace(start,start+10,18):
                for y in np.linspace(-4,4,16):
                    points.append([407500+x,343500+y,180+height-.5*abs(y)+rng.normal(0,.008)])
        points.extend([[407503,343503,205],[407515,343502,201]])
        return np.asarray(points)

    def test_two_gables_and_unassigned_outliers(self):
        xyz=self.fixture();r=plane_patches(xyz,np.arange(len(xyz)),trials=400,min_points=30)
        self.assertEqual(len(r['patches']),4)
        ridges=[c for c in r['creases'] if c['type']=='ridge_like']
        self.assertEqual(len(ridges),2)
        heights=sorted(float(np.mean(np.asarray(c['candidate_xyz_odn_m'])[:,2])) for c in ridges)
        np.testing.assert_allclose(heights,[188,191],atol=.03)
        self.assertTrue({len(xyz)-2,len(xyz)-1}<=set(r['unassigned_point_indices']))
        self.assertFalse(r['physical_edges_verified']);self.assertIsNone(r['native_edge_uncertainty_m'])
        ids=[i for p in r['patches'] for i in p['original_crop_point_indices']]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(len(ids)+len(r['ambiguous_point_indices'])+len(r['unassigned_point_indices']),len(xyz))
        for patch in r['patches']:
            self.assertTrue(shape(patch['support_geometry']).is_valid)
            self.assertLess(patch['residual_vertical_m']['p95_absolute'],.03)

    def test_deterministic_and_source_unchanged(self):
        xyz=self.fixture();saved=xyz.copy();ids=np.arange(len(xyz));saved_ids=ids.copy()
        a=plane_patches(xyz,ids,trials=200);b=plane_patches(xyz,ids,trials=200)
        self.assertEqual(a,b);np.testing.assert_array_equal(xyz,saved);np.testing.assert_array_equal(ids,saved_ids)

    def test_intersection_points_are_withheld_when_both_planes_fit(self):
        x,y=np.meshgrid(np.linspace(0,10,14),np.linspace(-4,4,17));xyz=np.column_stack((x.ravel(),y.ravel(),10-.5*np.abs(y.ravel())))
        r=plane_patches(xyz,np.arange(len(xyz)),trials=200,min_points=20)
        self.assertGreater(len(r['ambiguous_point_indices']),0)
        assigned={i for p in r['patches'] for i in p['original_crop_point_indices']}
        self.assertFalse(assigned.intersection(r['ambiguous_point_indices']))

    def test_invalid_input_and_budgets(self):
        valid=np.array([[0,0,0],[1,0,0],[0,1,0]],dtype=float)
        for xyz,ids,kwargs in [(valid,[0,0,2],{}),(valid,[0,-1,2],{}),(valid,[0,1,2],{'trials':5000}),(valid,[0,1,2],{'tolerance_m':0}),(valid,[0,1,2],{'max_planes':100})]:
            with self.assertRaises(ValueError):plane_patches(xyz,ids,**kwargs)
        with self.assertRaises(ValueError):plane_patches(np.full((6,3),np.nan),np.arange(6))
        with self.assertRaisesRegex(ValueError,'budget'):
            plane_patches(np.zeros((20000,3)),np.arange(20000),trials=4096,max_planes=24)
        r=plane_patches(np.empty((0,3)),np.empty(0,dtype=int))
        self.assertEqual(r['status'],'insufficient_plane_support')

if __name__=='__main__':unittest.main()
