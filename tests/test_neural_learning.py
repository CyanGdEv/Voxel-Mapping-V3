from concurrent.futures import CancelledError
import copy
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from voxel_mapper import neural_learning as neural
from voxel_mapper.building_spec import digest


class NeuralLearningTests(unittest.TestCase):
    @staticmethod
    def data(buildings=10,per_building=20,invert_evaluation=False):
        rows=[]
        for j in range(buildings):
            building='building-'+str(j)
            for i in range(per_building):
                a,b=(i//2)%2,i%2;accepted=a!=b
                if invert_evaluation and j>=buildings//2:accepted=not accepted
                rows.append({'id':f'{building}:{i}','building_id':building,
                    'candidate_sha256':digest([building,i]),'source_sha256':[digest(building)],
                    'features':dict(zip(neural.FEATURES,[a,b,.5,.5,.5,.5])),
                    'outcome':'accepted' if accepted else 'rejected','review_basis':'independent_review'})
        return rows,['building-'+str(j) for j in range(buildings//2)],['building-'+str(j) for j in range(buildings//2,buildings)]

    @classmethod
    def setUpClass(cls):
        cls.rows,cls.training,cls.evaluation=cls.data()
        cls.model=neural.train(cls.rows,cls.training,cls.evaluation,epochs=250)

    def test_neural_network_learns_nonlinear_xor_on_independent_buildings(self):
        model=self.model
        self.assertTrue(model['production_eligible']);self.assertEqual(model['status'],'promotion_eligible')
        self.assertLess(model['evaluation']['candidate']['brier'],.01)
        self.assertEqual(model['evaluation']['candidate']['accept_precision'],1)
        for a,b in ((0,0),(0,1),(1,0),(1,1)):
            value=neural.score(model,dict(zip(neural.FEATURES,[a,b,.5,.5,.5,.5])))
            self.assertGreater(value,.9) if a!=b else self.assertLess(value,.1)

    def test_untrained_checkpoint_is_neutral_and_seeded(self):
        a=neural.baseline(4);b=neural.baseline(4);c=neural.baseline(5)
        self.assertEqual(a,b);self.assertNotEqual(a['parameters']['hidden_weights'],c['parameters']['hidden_weights'])
        self.assertEqual(neural.predict(a,self.rows[0]['features']),.5)
        self.assertFalse(a['production_eligible']);self.assertEqual(a['iteration'],0)

    def test_same_snapshot_seed_and_training_parameters_are_deterministic(self):
        args=(self.rows,self.training,self.evaluation)
        a=neural.train(*args,epochs=25,seed=6);b=neural.train(*args,epochs=25,seed=6)
        self.assertEqual(a,b)

    def test_feedback_order_cannot_change_the_training_snapshot(self):
        a=neural.train(self.rows,self.training,self.evaluation,epochs=20,seed=8)
        b=neural.train(list(reversed(self.rows)),self.training,self.evaluation,epochs=20,seed=8)
        self.assertEqual(a,b)

    def test_open_json_checkpoint_survives_disk_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'model.json';path.write_text(json.dumps(self.model));restored=json.loads(path.read_text())
            neural.validate_model(restored)
            self.assertEqual(neural.score(restored,self.rows[1]['features']),neural.score(self.model,self.rows[1]['features']))

    def test_parameter_and_metadata_tampering_are_rejected(self):
        for mode in ('parameter','lineage','status'):
            model=copy.deepcopy(self.model)
            if mode=='parameter':model['parameters']['output_weights'][0]+=.01
            elif mode=='lineage':model['training_sources'].append('f'*64)
            else:model['production_eligible']=False
            with self.assertRaises(ValueError):neural.validate_model(model)

    def test_bad_architecture_or_parameter_shapes_rejected_before_numpy_allocation(self):
        for mode in ('width','matrix','bias'):
            model=neural.baseline()
            if mode=='width':model['architecture']['hidden_units']=1000000
            elif mode=='matrix':model['parameters']['hidden_weights']=[[0.0]*10000]
            else:model['parameters']['output_bias']=True
            with patch.object(neural.np,'asarray',side_effect=AssertionError('unbounded allocation')),self.assertRaises(ValueError):
                neural.validate_model(model)

    def test_nonfinite_normalized_features_and_parameters_are_rejected(self):
        for value in (float('nan'),float('inf'),-1,2,True):
            features=copy.deepcopy(self.rows[0]['features']);features[neural.FEATURES[0]]=value
            with self.assertRaises(ValueError):neural.score(self.model,features)
        model=neural.baseline();model['parameters']['hidden_weights'][0][0]=float('nan')
        with self.assertRaises(ValueError):neural.validate_model(model)

    def test_high_neural_score_cannot_override_failed_evidence_gate(self):
        features=dict(zip(neural.FEATURES,[0,1,.5,.5,.5,.5]));gates={g:True for g in neural.GATES}
        bad={'id':'bad','features':features,'gates':{**gates,'identity_verified':False}}
        good={'id':'good','features':dict(zip(neural.FEATURES,[0,0,.5,.5,.5,.5])),'gates':gates}
        report=neural.rank([bad,good],self.model)
        self.assertGreater(report['ranking'][0]['score'],.9);self.assertEqual(report['selected_id'],'good')
        self.assertEqual(report['ranking'][0]['failed_gates'],['identity_verified'])

    def test_no_candidate_is_selected_without_all_existing_gates(self):
        report=neural.rank([{'id':'a','features':self.rows[1]['features'],'gates':{}}],self.model)
        self.assertIsNone(report['selected_id']);self.assertEqual(set(report['ranking'][0]['failed_gates']),set(neural.GATES))

    def test_building_overlap_and_warm_start_split_switching_are_rejected(self):
        with self.assertRaises(ValueError):neural.train(self.rows,self.training,self.evaluation+self.training[:1])
        with self.assertRaisesRegex(ValueError,'warm-start'):
            neural.train(self.rows,self.evaluation,self.training,parent=self.model,epochs=1)

    def test_shared_source_hash_between_training_and_evaluation_is_rejected(self):
        rows=copy.deepcopy(self.rows);rows[-1]['source_sha256']=rows[0]['source_sha256']
        with self.assertRaisesRegex(ValueError,'source leakage'):neural.train(rows,self.training,self.evaluation)

    def test_predictions_successful_exports_and_duplicate_candidates_are_not_labels(self):
        for mode in ('prediction','export','duplicate'):
            rows=copy.deepcopy(self.rows)
            if mode=='prediction':rows[0]['review_basis']='model_prediction'
            elif mode=='export':rows[0]['review_basis']='successful_export'
            else:rows[1]['candidate_sha256']=rows[0]['candidate_sha256']
            with self.assertRaises(ValueError):neural.train(rows,self.training,self.evaluation)

    def test_too_few_independent_buildings_withholds_trained_checkpoint(self):
        rows,training,evaluation=self.data(buildings=4,per_building=40)
        model=neural.train(rows,training,evaluation,epochs=100,min_training_records=20,min_evaluation_records=20)
        self.assertFalse(model['production_eligible']);self.assertIn('insufficient_independent_buildings',model['evaluation']['reasons'])
        self.assertEqual(model['status'],'candidate_withheld')

    def test_inverted_unseen_outcomes_block_promotion(self):
        rows,training,evaluation=self.data(invert_evaluation=True)
        model=neural.train(rows,training,evaluation,epochs=100)
        self.assertFalse(model['production_eligible']);self.assertIn('held_out_accept_precision_below_policy',model['evaluation']['reasons'])

    def test_warm_start_retains_weights_lineage_and_all_source_separation(self):
        parent=copy.deepcopy(self.model)
        model=neural.train(self.rows,self.training,self.evaluation,parent=parent,epochs=10)
        self.assertEqual(model['iteration'],parent['iteration']+1);self.assertEqual(model['parent_sha256'],parent['artifact_sha256'])
        self.assertEqual(model['training_buildings'],parent['training_buildings']);self.assertEqual(model['evaluation_sources'],parent['evaluation_sources'])
        self.assertFalse(set(model['training_sources'])&set(model['evaluation_sources']));self.assertEqual(parent,self.model)

    def test_cancellation_before_and_during_training_returns_no_checkpoint(self):
        with self.assertRaises(CancelledError):neural.train(self.rows,self.training,self.evaluation,cancelled=lambda:True)
        calls=[]
        def cancelled():calls.append(1);return len(calls)>6
        with self.assertRaises(CancelledError):neural.train(self.rows,self.training,self.evaluation,cancelled=cancelled)
        self.assertEqual(len(calls),7)

    def test_progress_is_finite_and_input_feedback_is_immutable(self):
        rows=copy.deepcopy(self.rows);before=copy.deepcopy(rows);progress=[]
        neural.train(rows,self.training,self.evaluation,epochs=3,progress=progress.append)
        self.assertEqual(rows,before);self.assertEqual([p['epoch'] for p in progress],[1,2,3])
        self.assertTrue(all(np.isfinite(p['loss']) and p['loss']>0 for p in progress))

    def test_training_and_feedback_budgets_fail_before_gradient_work(self):
        for kwargs in ({'epochs':True},{'epochs':1001},{'batch_size':0},{'learning_rate':float('nan')},{'seed':True}):
            with self.assertRaises(ValueError):neural.train(self.rows,self.training,self.evaluation,**kwargs)
        large,training,evaluation=self.data(per_building=1000)
        with patch.object(neural,'_arrays',side_effect=AssertionError('gradient allocation')),self.assertRaises(ValueError):
            neural.train(large,training,evaluation,epochs=1000,parent=neural.baseline(hidden_units=64))
        with patch.object(neural,'_records',side_effect=AssertionError('dataset validation')),self.assertRaises(ValueError):
            neural.train([{}]*10001,self.training,self.evaluation)

    def test_exact_features_and_both_reviewed_classes_are_required(self):
        rows=copy.deepcopy(self.rows);rows[0]['features']['inferred_confidence']=1
        with self.assertRaises(ValueError):neural.train(rows,self.training,self.evaluation)
        rows=copy.deepcopy(self.rows)
        for row in rows:
            if row['building_id'] in self.evaluation:row['outcome']='accepted'
        with self.assertRaisesRegex(ValueError,'Both reviewed classes'):neural.train(rows,self.training,self.evaluation)
