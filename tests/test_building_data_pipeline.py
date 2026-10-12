import copy
import json
import tempfile
import unittest
from pathlib import Path
from voxel_mapper.building_spec import build, from_study, VERSION, FRAME, digest
from voxel_mapper.building_learning import baseline, FEATURES, GATES, train, rank, score
from voxel_mapper.building_pipeline import run, main, iterate


def spec(name='building-a'):
    return {'version': VERSION, 'coordinate_frame': FRAME, 'building_id': name,
            'sources': [{'id': 'drawing', 'sha256': 'a'*64, 'state': 'existing'}],
            'assumptions': ['Wall thickness is a display hypothesis.'],
            'components': [{'id': 'front', 'role': 'wall', 'evidence': {'class': 'inferred', 'source_ids': ['drawing'], 'description': 'Traced profile; assumed thickness'},
                'geometry': {'kind': 'extrusion', 'axis': 1, 'interval_m': [0, .3],
                             'profile': [[0,0],[8,0],[8,4],[0,4]],
                             'holes': [[[1,1],[2,1],[2,2],[1,2]]]}}]}


def candidate(identifier='candidate-a', name='building-a', value=.9):
    return {'id': identifier, 'features': dict.fromkeys(FEATURES, value),
            'gates': dict.fromkeys(GATES, True), 'spec': spec(name)}


def feedback(n=4):
    rows = []
    for building in range(n):
        for sample in range(4):
            positive = sample % 2 == 0
            rows.append({'id': f'b{building}-r{sample}', 'building_id': f'b{building}',
                'outcome': 'accepted' if positive else 'rejected', 'review_basis': 'independent_review',
                'source_sha256': [f'{building+1:064x}'], 'candidate_sha256': f'{building*4+sample+1:064x}',
                'features': dict.fromkeys(FEATURES, .9 if positive else .1)})
    return rows


class BuildingSpecTests(unittest.TestCase):
    def test_extruded_hole_preserved_and_closed_volume(self):
        model = build(spec()); mesh = model['components'][0]['mesh']
        self.assertTrue(mesh['watertight']); self.assertAlmostEqual(mesh['volume_m3'], 9.3)
        self.assertFalse(model['world_placement_eligible'])
        self.assertEqual(model['park_world_blocks_added'], 0)

    def test_invalid_source_geometry_and_duplicate_component_reject(self):
        changes = [lambda s: s['sources'][0].update(state='proposed'),
                   lambda s: s['components'].append(copy.deepcopy(s['components'][0])),
                   lambda s: s['components'][0]['geometry'].update(interval_m=[0,float('nan')]),
                   lambda s: s['components'][0]['evidence'].update(source_ids=['missing']),
                   lambda s: s.update(assumptions=[])]
        for change in changes:
            s = spec(); change(s)
            with self.assertRaises(ValueError): build(s)

    def test_study_adapter_retains_mesh_without_changing_coordinates(self):
        parent = build(spec())
        common = from_study(parent, 'other-building', 'b'*64)
        result = build(common)
        self.assertEqual(result['components'][0]['mesh'], parent['components'][0]['mesh'])
        self.assertEqual(result['building_id'], 'other-building')

    def test_false_watertight_claim_rejects(self):
        s = spec(); s['components'][0]['geometry'] = {'kind': 'mesh', 'mesh': {
            'vertices': [[0,0,0],[1,0,0],[0,1,0]], 'triangles': [[0,1,2]], 'watertight': True}}
        with self.assertRaisesRegex(ValueError, 'closed'): build(s)
        s['components'][0]['geometry']['mesh']['watertight'] = False
        self.assertFalse(build(s)['components'][0]['mesh']['watertight'])


class LearningTests(unittest.TestCase):
    def test_training_improves_unseen_building_score_and_keeps_small_trial_withheld(self):
        m = train(feedback(), ['b0','b1'], ['b2','b3'])
        self.assertLess(m['evaluation']['candidate']['brier'], m['evaluation']['previous']['brier'])
        self.assertGreater(score(m, dict.fromkeys(FEATURES, .9)), .8)
        self.assertFalse(m['production_eligible'])
        self.assertIn('insufficient_reviewed_samples', m['evaluation']['reasons'])

    def test_model_is_deterministic_under_record_order_and_warm_start(self):
        rows = feedback(); a = train(rows, ['b0','b1'], ['b2','b3'])
        b = train(list(reversed(rows)), ['b1','b0'], ['b3','b2'])
        self.assertEqual(a, b)
        c = train(rows, ['b0','b1'], ['b2','b3'], parent=a)
        self.assertEqual(c['iteration'], 2); self.assertEqual(c['parent_sha256'], a['artifact_sha256'])
        self.assertLess(c['evaluation']['candidate']['brier'], c['evaluation']['previous']['brier'])

    def test_source_and_building_leakage_rejected_including_parent_history(self):
        rows = feedback()
        with self.assertRaisesRegex(ValueError, 'leakage'): train(rows, ['b0','b1'], ['b1','b2','b3'])
        rows[8]['source_sha256'] = rows[0]['source_sha256']
        with self.assertRaisesRegex(ValueError, 'leakage'): train(rows, ['b0','b1'], ['b2','b3'])
        parent = train(feedback(), ['b0','b1'], ['b2','b3'])
        with self.assertRaisesRegex(ValueError, 'leakage'): train(feedback(), ['b2','b3'], ['b0','b1'], parent)

    def test_self_predictions_invalid_labels_features_and_checkpoint_reject(self):
        rows = feedback(); rows[0]['review_basis'] = 'model_prediction'
        with self.assertRaisesRegex(ValueError, 'reviewed'): train(rows, ['b0','b1'], ['b2','b3'])
        c = candidate(); c['features']['boundary_support'] = float('nan')
        with self.assertRaises(ValueError): rank([c])
        m = baseline(); m['weights'][0] = 9
        with self.assertRaisesRegex(ValueError, 'changed'): rank([candidate()], m)

    def test_failed_gate_cannot_win_despite_higher_learned_score(self):
        m = train(feedback(), ['b0','b1'], ['b2','b3'])
        high, low = candidate('high',value=.99), candidate('low',value=.2)
        high['gates']['dimensions_verified'] = False
        r = rank([high,low], m)
        self.assertEqual(r['ranking'][0]['id'], 'high'); self.assertEqual(r['selected_id'], 'low')
        low['gates']['source_verified'] = False
        self.assertIsNone(rank([high,low],m)['selected_id'])

    def test_balanced_large_review_fixture_can_meet_promotion_policy(self):
        rows = feedback(35)
        m = train(rows, [f'b{i}' for i in range(30)], [f'b{i}' for i in range(30,35)])
        self.assertTrue(m['production_eligible'])
        self.assertEqual(m['evaluation']['candidate']['accept_precision'], 1)

    def test_bad_learning_iteration_is_withheld(self):
        parent = train(feedback(), ['b0','b1'], ['b2','b3'])
        rows = feedback()
        for row in rows[:8]: row['outcome'] = 'rejected' if row['outcome']=='accepted' else 'accepted'
        m = train(rows, ['b0','b1'], ['b2','b3'], parent)
        self.assertFalse(m['production_eligible'])
        self.assertIn('no_held_out_brier_improvement', m['evaluation']['reasons'])

    def test_duplicate_feedback_missing_class_and_excess_work_reject(self):
        rows = feedback(); rows.append(copy.deepcopy(rows[0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate'): train(rows, ['b0','b1'], ['b2','b3'])
        rows = feedback(); rows[1]['candidate_sha256'] = rows[0]['candidate_sha256']
        with self.assertRaisesRegex(ValueError, 'Duplicate feedback'): train(rows, ['b0','b1'], ['b2','b3'])
        rows = feedback()
        for row in rows[8:]: row['outcome'] = 'accepted'
        with self.assertRaisesRegex(ValueError, 'Both'): train(rows, ['b0','b1'], ['b2','b3'])
        with self.assertRaisesRegex(ValueError, 'budget'): train(feedback(), ['b0','b1'], ['b2','b3'], epochs=1001)


class BuildingBatchTests(unittest.TestCase):
    def test_batch_builds_valid_candidates_and_isolates_bad_building(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = candidate('invalid'); a['spec']['components'][0]['geometry']['interval_m'] = [2,1]
            b = candidate('valid'); bad = candidate('blocked','building-b'); bad['gates'] = {}
            job = {'version': 'building-batch-v1', 'buildings': [
                {'building_id':'building-a','candidates':[a,b]},
                {'building_id':'building-b','candidates':[bad]}]}
            report = run(job, Path(tmp)/'batch')
            self.assertEqual(report['built'],1)
            self.assertEqual(report['buildings'][0]['selected_id'],'valid')
            self.assertEqual(report['buildings'][1]['status'],'awaiting_eligible_candidate')
            self.assertEqual(report['training_labels_generated'],0)
            self.assertTrue((Path(tmp)/'batch/building-0000/model.glb').is_file())
            with self.assertRaisesRegex(ValueError, 'Fresh'): run(job, Path(tmp)/'batch')

    def test_unpromoted_weights_require_exploratory_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = train(feedback(), ['b0','b1'], ['b2','b3'])
            job = {'version':'building-batch-v1','buildings':[{'building_id':'building-a','candidates':[candidate()]}]}
            with self.assertRaisesRegex(ValueError, 'Unpromoted'): run(job, Path(tmp)/'blocked',m)
            self.assertEqual(run(job, Path(tmp)/'trial',m,True)['built'],1)

    def test_cli_import_and_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); parent = root/'parent.json'; parent.write_text(json.dumps(build(spec())))
            main(['import-study','--model',str(parent),'--building-id','building-a','--output',str(root/'spec.json')])
            self.assertEqual(json.loads((root/'spec.json').read_text())['building_id'],'building-a')


class LearningIterationTests(unittest.TestCase):
    def test_iteration_retains_baseline_when_candidate_withheld(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = {'version':'building-batch-v1','buildings':[{'building_id':'building-a','candidates':[candidate()]}]}
            report = iterate(job, {'version':'building-feedback-v1','records':feedback()},
                             {'training_buildings':['b0','b1'],'evaluation_buildings':['b2','b3']}, Path(tmp)/'iteration')
            self.assertFalse(report['promoted']); self.assertEqual(report['built'],1)
            self.assertEqual(report['selected_sha256'], baseline()['artifact_sha256'])
            self.assertEqual(report['training_labels_generated'],0)
            with self.assertRaisesRegex(ValueError, 'Fresh'):
                iterate(job, {'version':'building-feedback-v1','records':feedback()},
                        {'training_buildings':['b0','b1'],'evaluation_buildings':['b2','b3']}, Path(tmp)/'iteration')

    def test_iteration_auto_selects_only_passing_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = {'version':'building-batch-v1','buildings':[{'building_id':'building-a','candidates':[candidate()]}]}
            report = iterate(job, {'version':'building-feedback-v1','records':feedback(35)},
                             {'training_buildings':[f'b{i}' for i in range(30)],
                              'evaluation_buildings':[f'b{i}' for i in range(30,35)]}, Path(tmp)/'iteration')
            self.assertTrue(report['promoted'])
            self.assertEqual(report['candidate_sha256'], report['selected_sha256'])
