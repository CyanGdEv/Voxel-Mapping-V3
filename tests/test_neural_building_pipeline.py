"""Actual local geometry export through the neural model dispatch path."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from voxel_mapper import building_learning,neural_learning
from voxel_mapper.building_pipeline import main,run
from voxel_mapper.building_spec import VERSION,FRAME,digest


def candidate(identifier,value,building='example'):
    return {'id':identifier,'features':dict.fromkeys(neural_learning.FEATURES,value),
        'gates':dict.fromkeys(neural_learning.GATES,True),
        'spec':{'version':VERSION,'coordinate_frame':FRAME,'building_id':building,
            'sources':[{'id':'drawing','sha256':'a'*64,'state':'existing'}],
            'assumptions':['Synthetic integration fixture, not a real building.'],
            'components':[{'id':'wall','role':'wall','evidence':{'class':'inferred',
                'source_ids':['drawing'],'description':'Synthetic source-supported profile'},
                'geometry':{'kind':'extrusion','axis':1,'interval_m':[0,.3],
                    'profile':[[0,0],[2,0],[2,2],[0,2]],'holes':[]}}]}}


def job(*candidates):
    return {'version':'building-batch-v1','buildings':[{'building_id':'example','candidates':list(candidates)}]}


class NeuralBuildingPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows=[]
        for j in range(10):
            for i in range(20):
                b='training-fixture-'+str(j);positive=i%2==0
                rows.append({'id':f'{b}:{i}','building_id':b,'candidate_sha256':digest([b,i]),
                    'source_sha256':[digest(b)],'outcome':'accepted' if positive else 'rejected',
                    'review_basis':'independent_review','features':dict.fromkeys(neural_learning.FEATURES,.9 if positive else .1)})
        cls.rows=rows;cls.training=['training-fixture-'+str(i) for i in range(5)];cls.evaluation=['training-fixture-'+str(i) for i in range(5,10)]
        cls.model=neural_learning.train(rows,cls.training,cls.evaluation,epochs=100)
        assert cls.model['production_eligible']

    def ranking(self,root):return json.loads((root/'building-0000/ranking.json').read_text())

    def test_promoted_neural_model_selects_and_exports_eligible_preferred_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'preview';report=run(job(candidate('a-low',.1),candidate('z-high',.9)),root,self.model)
            self.assertEqual(report['built'],1);self.assertEqual(report['buildings'][0]['selected_id'],'z-high')
            self.assertEqual(self.ranking(root)['version'],neural_learning.VERSION)
            self.assertTrue((root/'building-0000/model.glb').is_file());self.assertTrue((root/'building-0000/model.json').is_file())
            self.assertEqual(report['training_labels_generated'],0);self.assertEqual(report['park_world_blocks_added'],0)
            self.assertFalse(report['buildings'][0]['world_placement_eligible'])

    def test_high_neural_score_cannot_bypass_identity_gate_in_real_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            high=candidate('z-high',.9);high['gates']['identity_verified']=False;root=Path(tmp)/'preview'
            report=run(job(high,candidate('a-low',.1)),root,self.model);ranking=self.ranking(root)
            self.assertEqual(report['buildings'][0]['selected_id'],'a-low')
            self.assertEqual(ranking['ranking'][0]['id'],'z-high');self.assertGreater(ranking['ranking'][0]['score'],.8)
            self.assertEqual(ranking['ranking'][0]['failed_gates'],['identity_verified'])

    def test_invalid_high_ranked_geometry_retains_failure_and_builds_next_eligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            high=candidate('z-high',.9);high['spec']['components'][0]['geometry']['interval_m']=[2,1]
            root=Path(tmp)/'preview';report=run(job(high,candidate('a-valid',.1)),root,self.model)
            self.assertEqual(report['built'],1);self.assertEqual(report['buildings'][0]['selected_id'],'a-valid')
            self.assertEqual(report['buildings'][0]['construction_failures'][0]['candidate_id'],'z-high')
            saved=json.loads((root/'building-0000/building-spec.json').read_text());self.assertEqual(saved['components'][0]['geometry']['interval_m'],[0,.3])

    def test_no_export_when_every_candidate_has_failed_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            high=candidate('high',.9);high['gates']={};root=Path(tmp)/'preview';report=run(job(high),root,self.model)
            self.assertEqual(report['built'],0);self.assertEqual(report['buildings'][0]['status'],'awaiting_eligible_candidate')
            self.assertFalse((root/'building-0000/model.glb').exists());self.assertEqual(report['training_labels_generated'],0)

    def test_unpromoted_neural_checkpoint_requires_explicit_exploratory_mode(self):
        withheld=neural_learning.train(self.rows,self.training,self.evaluation,epochs=5,min_training_records=1000)
        self.assertFalse(withheld['production_eligible'])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with self.assertRaisesRegex(ValueError,'Unpromoted'):run(job(candidate('one',.9)),root/'normal',withheld)
            self.assertFalse((root/'normal').exists())
            report=run(job(candidate('one',.9)),root/'exploratory',withheld,exploratory=True)
            self.assertEqual(report['built'],1);self.assertTrue(report['contract']['exploratory'])
            self.assertFalse(report['contract']['world_placement_eligible'])

    def test_tampered_neural_checkpoint_fails_before_output(self):
        model=copy.deepcopy(self.model);model['parameters']['output_weights'][0]+=.1
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'preview'
            with self.assertRaisesRegex(ValueError,'changed'):run(job(candidate('one',.9)),root,model)
            self.assertFalse(root.exists())

    def test_neural_baseline_is_allowed_without_claiming_trained_eligibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'preview';report=run(job(candidate('b',.9),candidate('a',.1)),root,neural_learning.baseline())
            self.assertEqual(report['buildings'][0]['selected_id'],'a')
            self.assertFalse(self.ranking(root)['model_production_eligible'])

    def test_default_and_explicit_logistic_models_preserve_existing_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for model,name in ((None,'default'),(building_learning.baseline(),'explicit')):
                report=run(job(candidate('b',.9),candidate('a',.1)),root/name,model)
                self.assertEqual(report['buildings'][0]['selected_id'],'a')
                self.assertEqual(self.ranking(root/name)['version'],building_learning.VERSION)

    def test_cli_batch_uses_supplied_neural_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'job.json').write_text(json.dumps(job(candidate('a-low',.1),candidate('z-high',.9))))
            (root/'neural-model.json').write_text(json.dumps(self.model))
            main(['batch','--job',str(root/'job.json'),'--model',str(root/'neural-model.json'),'--output',str(root/'preview')])
            self.assertEqual(self.ranking(root/'preview')['selected_id'],'z-high')
            self.assertEqual(self.ranking(root/'preview')['version'],neural_learning.VERSION)

    def test_neural_selection_can_use_existing_native_cell_export_without_park_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            configured=job(candidate('one',.9));configured['native_output']='cells';root=Path(tmp)/'preview'
            report=run(configured,root,self.model);native=report['buildings'][0]['native_output']
            self.assertEqual(report['built'],1);self.assertEqual(native['mode'],'cells');self.assertGreater(native['surface_cells'],0)
            self.assertFalse(native['world_exported']);self.assertEqual(report['park_world_blocks_added'],0)
