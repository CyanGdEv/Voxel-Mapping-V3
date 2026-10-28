import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np
from affine import Affine

from voxel_mapper.lidar_surface_features import native_features,sample_native


class LidarContextTests(unittest.TestCase):
    def test_local_separator_checks_do_not_confuse_routes_connected_elsewhere(self):
        from voxel_mapper.tight_path_review import evaluate
        target=np.full((64,64),2,np.uint8);target[10:16,5:55]=0;target[40:46,5:55]=0;target[10:46,5:11]=0
        reg={'reference_to_clean':[[1,0,0],[0,1,0]]};probe={'id':'island','a_reference_xy':[30,12],'b_reference_xy':[30,42],'reference_box_xyxy':[25,8,35,49],'expected_local_connection':False}
        correct=evaluate(target,target,reg,[probe]);self.assertEqual(correct['false_local_grass_bridges'],0)
        bridged=target.copy();bridged[12:44,29:32]=0
        self.assertEqual(evaluate(target,bridged,reg,[probe])['false_local_grass_bridges'],1)

    def test_source_probe_endpoints_must_be_supported_by_observed_paving(self):
        from voxel_mapper.tight_path_review import evaluate
        target=np.full((32,32),255,np.uint8);probe={'id':'unsupported','a_reference_xy':[5,5],'b_reference_xy':[20,20],'reference_box_xyxy':[2,2,28,28],'expected_local_connection':True}
        with self.assertRaisesRegex(ValueError,'supported'):evaluate(target,target,{'reference_to_clean':[[1,0,0],[0,1,0]]},[probe])

    def test_height_is_relative_and_gaps_remain_invalid(self):
        dtm=np.full((32,32),100.,np.float32);dsm=dtm.copy();dsm[8:24,8:24]=120.;valid=np.ones(dtm.shape,bool)
        f=native_features(dtm,dsm,valid,valid)
        self.assertAlmostEqual(float(f[16,16,0]),20/30,places=6);self.assertEqual(float(f[16,16,2]),0)
        self.assertGreater(float(f[8,16,2]),0);self.assertEqual(float(f[4,4,0]),0)
        mask=valid.copy();mask[16,16]=False;missing=dsm.copy();missing[16,16]=np.nan;f=native_features(dtm,missing,valid,mask)
        self.assertFalse(f[15:18,15:18,3].any());self.assertFalse(f[16,16].any())

    def test_slope_and_height_are_independent_and_nearest_cells_do_not_fill_outside(self):
        y,x=np.indices((16,16));dtm=100+2*x.astype(float);valid=np.ones_like(dtm,bool);f=native_features(dtm,dtm+5,valid,valid)
        self.assertAlmostEqual(float(f[8,8,0]),5/30,places=6)
        self.assertAlmostEqual(float(f[8,8,1]),np.arctan(2)/(np.pi/2),places=6)
        synthetic=np.zeros((4,4,4),np.float32);synthetic[:,:,0]=np.arange(16).reshape(4,4)
        out=sample_native(synthetic,np.array([[.1,.9,1.1,4.1]]),np.array([[3.9,3.1,3.9,3.9]]),Affine(1,0,0,0,-1,4))
        np.testing.assert_array_equal(out[0,:,0],[0,0,1,0])

    def test_narrow_sampling_targets_path_interiors_without_relabelling_grass(self):
        from voxel_mapper.layered_surface_learning import narrow_path_anchors
        target=np.full((160,160),255,np.uint8);target[20:26,10:130]=0;target[70:140,10:140]=0;target[40:55,10:130]=2
        anchors=narrow_path_anchors(target,.5,4.);self.assertTrue(((anchors[:,0]>=21)&(anchors[:,0]<=24)).any())
        self.assertFalse(((anchors[:,0]==100)&(anchors[:,1]==70)).any());self.assertTrue((target[anchors[:,0],anchors[:,1]]==0).all())


@unittest.skipUnless(importlib.util.find_spec('torch') and importlib.util.find_spec('safetensors'),'Optional neural dependencies absent')
class LidarNetworkTests(unittest.TestCase):
    def test_twenty_channel_training_requires_pinned_lidar_and_reloads_exactly(self):
        from voxel_mapper.layered_surface_learning import fit,predict,save,load,SETTINGS
        features=np.zeros((96,96,20),np.float32);features[:,:,:3]=.4;features[:,:,19]=1;target=np.zeros((96,96),np.uint8);target[48:]=1;canopy=np.zeros_like(target)
        row={'record':{'id':'synthetic','site_id':'park','image_sha256':'a'*64},'features':features,'ground':target,'canopy':canopy,'ground_sampling_m':.5}
        model,training=fit([row],settings={**SETTINGS,'steps':2,'batch':2,'patch':64,'lidar_dropout':.15,'narrow_sampling_fraction':.5,'narrow_max_width_m':4.})
        self.assertGreater(training['parameter_change_l2'],0)
        with tempfile.TemporaryDirectory() as temp:
            row['lidar_pin']='c'*64;p=Path(temp)/'checkpoint';save(model,[row],{'id':'b'*64},p,training,'d'*64);loaded,meta=load(p)
            self.assertEqual(meta['lidar_feature_receipts_sha256'],['c'*64])
            for a,b in zip(predict(model,features),predict(loaded,features)):np.testing.assert_array_equal(a,b)


if __name__=='__main__':unittest.main()
