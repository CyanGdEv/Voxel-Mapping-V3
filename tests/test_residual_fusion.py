import importlib.util
import unittest
import copy
from voxel_mapper.train_ground_model import build_model,validate_rgb_teacher

class TeacherValidationTests(unittest.TestCase):
    def test_rejects_membership_and_source_mismatches(self):
        expected={'train_ids':[['park','west','one']],'validation_ids':[['park','east','two']],'seed':41}
        report={'mode':'rgb','status':'trained',**expected,'sources':[{'dataset_sha256':'good'}]}
        validate_rgb_teacher(report,expected,report['sources'])
        for key in expected:
            altered=copy.deepcopy(report);altered[key]=None
            with self.assertRaises(ValueError):validate_rgb_teacher(altered,expected,report['sources'])
        with self.assertRaises(ValueError):validate_rgb_teacher(report,expected,[{'dataset_sha256':'different'}])

@unittest.skipUnless(importlib.util.find_spec('torch'),'requires optional torch')
class ResidualFusionTests(unittest.TestCase):
    def test_frozen_rgb_bounded_update_and_exact_outage_fallback(self):
        import torch
        torch.set_num_threads(1)
        model=build_model(28,10,architecture='rgb_residual_v1',residual_bound=1.)
        x=torch.rand(2,28,64,64);x[:,[4,6,8,10,12,14,23,25,27]]=1
        model.train()
        self.assertFalse(model.rgb.training)
        before={k:v.clone() for k,v in model.rgb.state_dict().items()}
        expected=model.rgb(x[:,:3]).detach()
        torch.testing.assert_close(model(x),expected,rtol=0,atol=0)
        optimizer=torch.optim.AdamW((p for p in model.parameters() if p.requires_grad),lr=.01)
        loss=model(x).square().mean();loss.backward();optimizer.step()
        self.assertTrue(any(p.grad is not None for p in model.adapter.parameters()))
        self.assertTrue(all(p.grad is None for p in model.rgb.parameters()))
        for k,v in model.rgb.state_dict().items():torch.testing.assert_close(v,before[k],rtol=0,atol=0)
        self.assertLessEqual(float(model.residual(x).detach().abs().max()),1.)
        x[:,3:]=0
        torch.testing.assert_close(model(x),model.rgb(x[:,:3]),rtol=0,atol=0)
        for bound in (0,float('nan'),3):
            with self.assertRaises(ValueError):build_model(28,10,architecture='rgb_residual_v1',residual_bound=bound)

    def test_capacity_control_cannot_read_context_values(self):
        import torch
        torch.set_num_threads(1)
        model=build_model(28,10,architecture='rgb_residual_control_v1')
        torch.nn.init.normal_(model.adapter[-1].weight)
        a=torch.rand(1,28,64,64)
        a[:,[4,6,8,10,12,14,23,25,27]]=1
        b=a.clone();b[:,3:]=1
        torch.testing.assert_close(model(a),model(b),rtol=0,atol=0)
