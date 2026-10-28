import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from voxel_mapper import layered_surface_benchmark as data


class LayeredTargetsTests(unittest.TestCase):
    def test_canopy_and_inferred_ground_never_become_observed_ground_or_grass(self):
        target=np.full((64,64),255,np.uint8);inferred=np.zeros_like(target);inferred[25:30,25:30]=255
        item={'dense_windows':[{'id':'plaza','outer':[[5,5],[58,5],[58,58],[5,58]],'base':'paving','parts':[],'unknown':[]}],
              'canopy':[{'id':'tree','outer':[[35,35],[45,35],[45,45],[35,45]]}]}
        g,c,w=data.targets(item,(64,64),(64,64),[[1,0,0],[0,1,0]],target,inferred)
        self.assertEqual(g[40,40],255);self.assertEqual(c[40,40],1)
        self.assertEqual(g[26,26],255);self.assertEqual(c[26,26],255)
        self.assertEqual(g[20,20],0);self.assertEqual(c[20,20],0)
        self.assertEqual(g[5,20],255);self.assertNotIn(2,np.unique(g))

    def test_boundary_scores_ignore_unknown_and_artificial_edges_but_find_known_interface(self):
        target=np.full((64,64),255,np.uint8);target[10:54,10:32]=0;target[10:54,32:54]=1
        pred=target.copy();perfect=data.class_metrics(target,pred,2)
        self.assertEqual(perfect['classes'][0]['iou'],1)
        self.assertEqual(perfect['boundaries']['classes'][0]['f1'],1)
        self.assertGreater(perfect['boundaries']['classes'][0]['true_boundary_pixels'],0)
        broken=data.class_metrics(target,np.zeros_like(target),2)
        self.assertEqual(broken['boundaries']['classes'][0]['f1'],0)
        sparse=np.full_like(target,255);sparse[20:30,20:30]=0
        self.assertIsNone(data.boundary_metrics(sparse,np.zeros_like(target),2)['classes'][0]['f1'])

    def test_abstentions_count_as_missed_classes(self):
        target=np.array([[0,1],[0,1]],np.uint8);p=np.full_like(target,255);s=data.class_metrics(target,p,2)
        self.assertEqual(s['abstentions_on_known_pixels'],4)
        self.assertEqual(s['classes'][1]['recall'],0);self.assertEqual(s['present_target_macro_iou'],0)

    def test_aerial_mapping_does_not_call_trees_grass_or_force_unmapped_surfaces_into_paving(self):
        from voxel_mapper.aerial_surface_encoder import zero_shot
        f=np.zeros((2,3,16),np.float32)
        for i,label in enumerate([3,1,10,5,6,4]):f[i//3,i%3,3+label]=1
        g,c=zero_shot(f)
        np.testing.assert_array_equal(g,np.array([[0,1,2],[3,255,255]],np.uint8))
        self.assertEqual(c[1,1],1);self.assertEqual(c[0,2],0)


@unittest.skipUnless(importlib.util.find_spec('torch') and importlib.util.find_spec('safetensors'),'Optional layered research dependencies absent')
class LayeredNetworkTests(unittest.TestCase):
    def test_unknown_targets_have_no_loss_or_gradients(self):
        import torch
        from voxel_mapper.layered_surface_learning import masked_loss
        torch.manual_seed(2);x=torch.randn(1,4,16,16,requires_grad=True);target=torch.full((1,16,16),255,dtype=torch.long)
        loss=masked_loss(x,target,torch.ones(4));self.assertEqual(float(loss.detach()),0);loss.backward();self.assertEqual(float(x.grad.abs().sum()),0)

    def test_balance_weights_use_fitting_targets_only_and_missing_classes_are_not_invented(self):
        import torch
        from voxel_mapper.layered_surface_learning import class_weights,masked_loss
        target=np.zeros((32,32),np.uint8);target[:2]=1;target[10:12]=255
        weights,counts=class_weights([{'ground':target}],'ground',4)
        self.assertGreater(weights[1],weights[0]);self.assertEqual(weights[2],0);self.assertEqual(counts[3],0)
        x=torch.zeros(1,4,32,32,requires_grad=True);loss=masked_loss(x,torch.from_numpy(target[None]).long(),torch.from_numpy(weights));loss.backward()
        self.assertTrue(torch.isfinite(loss));self.assertGreater(float(x.grad.abs().sum()),0)

    def test_real_training_safe_reload_and_tamper_rejection(self):
        from voxel_mapper.layered_surface_learning import fit,predict,save,load,SETTINGS
        rgb=np.zeros((96,96,3),np.float32);rgb[48:]=.8;g=np.zeros((96,96),np.uint8);g[48:]=1;c=np.zeros_like(g);c[10:20,10:20]=1;g[10:20,10:20]=255
        row={'record':{'id':'synthetic','site_id':'park','image_sha256':'a'*64},'features':rgb,'ground':g,'canopy':c}
        model,training=fit([row],settings={**SETTINGS,'steps':2,'batch':2,'patch':64});self.assertGreater(training['parameter_change_l2'],0)
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'model';save(model,[row],{'id':'b'*64},p,training);loaded,m=load(p)
            for a,b in zip(predict(model,rgb),predict(loaded,rgb)):np.testing.assert_array_equal(a,b)
            (p/'weights.safetensors').write_bytes(b'changed')
            with self.assertRaises(ValueError):load(p)

    def test_corrupt_tensor_shapes_are_rejected_before_tensor_loading(self):
        import torch
        from safetensors.torch import save_file
        from voxel_mapper.layered_surface_learning import architecture,save,load
        from voxel_mapper.desktop_memory import digest
        from voxel_mapper.generation_cycles import file_hash
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'model';model=architecture();save(model,[{'record':{'id':'x','site_id':'p','image_sha256':'a'*64},'features':np.zeros((1,1,3))}],{'id':'b'*64},p,{})
            weights={k:v for k,v in model.state_dict().items()};key=next(iter(weights));weights[key]=torch.zeros(1);save_file(weights,str(p/'weights.safetensors'))
            m=json.loads((p/'model.json').read_text());m['weights_sha256']=file_hash(p/'weights.safetensors');m['id']=digest({k:v for k,v in m.items() if k!='id'});(p/'model.json').write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError,'headers'):load(p)


if __name__=='__main__':unittest.main()
