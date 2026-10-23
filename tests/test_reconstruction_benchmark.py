"""Geometric error and evidence/lineage failures must remain measurable."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from voxel_mapper.building_spec import digest
from voxel_mapper.reconstruction_benchmark import (
    VERSION, evaluate, main, reference_digest, run,
)


def rectangle(x=0, y=0, width=10, height=8):
    return [[x,y],[x+width,y],[x+width,y+height],[x,y+height]]


def benchmark():
    geometry={'footprint_m':rectangle(), 'height_m':4., 'position_m':[410000.,345000.,120.]}
    config={'version':VERSION, 'dataset_kind':'synthetic',
            'coordinate_frame':'EPSG:27700 horizontal; ODN vertical', 'units':'metres',
            'cases':[{'id':'synthetic-shop', 'building_id':'synthetic-building',
                      'source_sha256':[digest('synthetic source only')],
                      'reference':{'geometry':geometry,'review_basis':'independent_review',
                                   'review_reference':'synthetic fixture, not a real building review'},
                      'prediction':copy.deepcopy(geometry)}]}
    config['reference_sha256']=reference_digest(config)
    return config


def repin(config):
    config['reference_sha256']=reference_digest(config)
    return config


def empty_lineage():
    return {'training_buildings':[], 'evaluation_buildings':[],
            'training_sources':[], 'evaluation_sources':[]}


class ReconstructionBenchmarkTests(unittest.TestCase):
    def test_exact_synthetic_geometry_never_becomes_physical_acceptance(self):
        config=benchmark();report=evaluate(config)
        metrics=report['cases'][0]['metrics']
        self.assertEqual(metrics['footprint_iou'],1.)
        self.assertEqual(metrics['boundary_hausdorff_m'],0.)
        self.assertEqual(metrics['height_error_m'],0.)
        self.assertEqual(metrics['position_error_m'],0.)
        self.assertTrue(report['summary']['all_cases_within_thresholds'])
        self.assertEqual(report['dataset_kind'],'synthetic')
        self.assertEqual(report['lineage_check']['status'],'not_assessed')
        self.assertFalse(report['real_world_accuracy_established'])
        self.assertFalse(report['physical_acceptance_authorized'])
        self.assertFalse(report['model_promoted'])
        self.assertEqual(report['training_labels_generated'],0)
        self.assertEqual(report['park_world_blocks_added'],0)

    def test_known_shape_height_and_xyz_displacements(self):
        config=benchmark();prediction=config['cases'][0]['prediction']
        prediction.update(footprint_m=rectangle(x=1),height_m=4.5,position_m=[410003.,345004.,120.])
        report=evaluate(config);result=report['cases'][0];metrics=result['metrics']
        self.assertAlmostEqual(metrics['footprint_iou'],72/88)
        self.assertAlmostEqual(metrics['boundary_hausdorff_m'],1.)
        self.assertAlmostEqual(metrics['height_error_m'],.5)
        self.assertAlmostEqual(metrics['position_error_m'],5.)
        self.assertEqual(set(result['failed_checks']),{
            'footprint_iou','boundary_hausdorff_m','height_error_m','position_error_m'})
        self.assertFalse(report['summary']['all_cases_within_thresholds'])

    def test_reference_hole_is_included_in_polygon_measurement(self):
        config=benchmark()
        config['cases'][0]['reference']['geometry']['footprint_m']={
            'exterior':rectangle(), 'holes':[rectangle(2,2,2,2)]}
        report=evaluate(repin(config));metrics=report['cases'][0]['metrics']
        self.assertAlmostEqual(metrics['footprint_iou'],76/80)
        self.assertGreater(metrics['boundary_hausdorff_m'],0.)

    def test_missing_prediction_is_not_a_perfect_zero_error(self):
        config=benchmark();config['cases'][0]['prediction']=None
        report=evaluate(config);result=report['cases'][0]
        self.assertEqual(result['status'],'missing_prediction')
        self.assertFalse(result['within_thresholds'])
        self.assertEqual(report['summary']['missing_predictions'],1)
        for name,aggregate in report['summary']['metrics'].items():
            self.assertIsNone(result['metrics'][name])
            self.assertIsNone(aggregate['mean'])
            self.assertEqual(aggregate['unassessed_cases'],1)

    def test_partial_prediction_remains_incomplete(self):
        config=benchmark();config['cases'][0]['prediction']={'height_m':4.}
        result=evaluate(config)['cases'][0]
        self.assertEqual(result['status'],'incomplete_prediction')
        self.assertFalse(result['within_thresholds'])
        self.assertEqual(set(result['failed_checks']),{'footprint_m','position_m'})

    def test_missing_cases_are_retained_in_aggregate_denominators(self):
        config=benchmark();second=copy.deepcopy(config['cases'][0])
        second.update(id='missing-other-view',prediction=None)
        config['cases'].append(second)
        report=evaluate(repin(config));aggregate=report['summary']['metrics']['height_error_m']
        self.assertEqual(aggregate['measured_cases'],1)
        self.assertEqual(aggregate['unassessed_cases'],1)
        self.assertEqual(report['summary']['cases_within_thresholds'],1)
        self.assertEqual(report['summary']['case_count'],2)

    def test_openings_use_one_to_one_matches_and_count_false_positives(self):
        config=benchmark();case=config['cases'][0]
        case['reference']['geometry']['openings_m']=[rectangle(1,1,1,2),rectangle(4,1,1,2)]
        case['prediction']['openings_m']=[rectangle(1,1,1,2),rectangle(7,1,1,2)]
        result=evaluate(repin(config))['cases'][0];openings=result['metrics']['openings']
        self.assertEqual(openings['matched_count'],1)
        self.assertEqual(openings['false_positive_count'],1)
        self.assertEqual(openings['false_negative_count'],1)
        self.assertEqual(openings['precision'],.5)
        self.assertEqual(openings['recall'],.5)
        self.assertIn('opening_precision',result['failed_checks'])
        self.assertIn('opening_recall',result['failed_checks'])

    def test_declared_no_openings_differs_from_missing_opening_prediction(self):
        config=benchmark();case=config['cases'][0]
        case['reference']['geometry']['openings_m']=[];repin(config)
        result=evaluate(config)['cases'][0]
        self.assertIn('openings_m',result['failed_checks'])
        case['prediction']['openings_m']=[]
        result=evaluate(config)['cases'][0]
        self.assertTrue(result['within_thresholds'])
        self.assertEqual(result['metrics']['openings']['precision'],1.)
        case['prediction']['openings_m']=[rectangle(1,1,1,2)]
        result=evaluate(config)['cases'][0]
        self.assertFalse(result['within_thresholds'])
        self.assertEqual(result['metrics']['openings']['false_positive_count'],1)

    def test_frozen_reference_rejects_changes_but_allows_new_predictions(self):
        config=benchmark();pin=config['reference_sha256']
        config['cases'][0]['prediction']['height_m']=5.
        self.assertEqual(reference_digest(config),pin)
        self.assertEqual(evaluate(config)['cases'][0]['metrics']['height_error_m'],1.)
        config['cases'][0]['reference']['geometry']['height_m']=5.
        with self.assertRaisesRegex(ValueError,'checksum'):evaluate(config)

    def test_building_or_shared_source_exposure_in_either_split_is_rejected(self):
        for key in ('training_buildings','evaluation_buildings','training_sources','evaluation_sources'):
            with self.subTest(key=key):
                config=benchmark();config['lineage']=empty_lineage()
                case=config['cases'][0]
                config['lineage'][key]=[case['building_id'] if key.endswith('buildings') else case['source_sha256'][0]]
                with self.assertRaisesRegex(ValueError,'Benchmark leakage'):evaluate(config)

    def test_complete_disjoint_declared_lineage_and_neural_checkpoint(self):
        from voxel_mapper.neural_learning import baseline
        config=benchmark();config['lineage']=empty_lineage()
        config['lineage']['training_buildings']=['different-building']
        config['lineage']['training_sources']=[digest('another source')]
        model=baseline()
        report=evaluate(config,model)
        self.assertEqual(report['lineage_check']['status'],'no_declared_overlap')
        self.assertEqual(report['lineage_check']['model_sha256'],model['artifact_sha256'])
        self.assertFalse(report['lineage_check']['untouched_independence_proven'])
        model['parameters']['output_bias']=1.
        with self.assertRaisesRegex(ValueError,'changed'):evaluate(config,model)

    def test_incomplete_trained_logistic_lineage_cannot_claim_unseen_sources(self):
        from voxel_mapper.building_learning import baseline
        config=benchmark();model=baseline();model['iteration']=1
        model['evaluation_buildings']=['other-evaluated-building']
        model['artifact_sha256']=digest({k:v for k,v in model.items() if k!='artifact_sha256'})
        with self.assertRaisesRegex(ValueError,'complete evaluation source lineage'):evaluate(config,model)
        config['lineage']=empty_lineage()
        report=evaluate(config,model)
        self.assertEqual(report['lineage_check']['status'],'no_declared_overlap')

    def test_lineage_complement_cannot_introduce_cross_split_exposure(self):
        # Legacy logistic checkpoint metadata passes its own integrity checker;
        # the combined benchmark lineage must still reject a conflicting role.
        from voxel_mapper.building_learning import baseline as logistic_baseline
        model=logistic_baseline();model['training_buildings']=['different-building']
        model['artifact_sha256']=digest({k:v for k,v in model.items() if k!='artifact_sha256'})
        config=benchmark();config['lineage']=empty_lineage()
        config['lineage']['evaluation_buildings']=['different-building']
        with self.assertRaisesRegex(ValueError,'Merged'):evaluate(config,model)

    def test_invalid_geometry_and_review_provenance_are_rejected(self):
        mutations=[
            lambda c:c['cases'][0]['reference'].update(review_reference=' '),
            lambda c:c['cases'][0]['reference'].update(review_basis='model_prediction'),
            lambda c:c['cases'][0].update(source_sha256=['not-a-source-hash']),
            lambda c:c['cases'][0]['prediction'].update(footprint_m=[[0,0],[2,2],[2,0],[0,2]]),
            lambda c:c['cases'][0]['prediction'].update(height_m=True),
            lambda c:c['cases'][0]['prediction'].update(position_m=[0,0]),
            lambda c:c['cases'][0]['prediction'].update(footprint_m={'exterior':rectangle(),'holes':[rectangle(20,20,1,1)]}),
            lambda c:c['cases'][0]['prediction'].update(openings_m=[rectangle(1,1,1,2),rectangle(1,1,1,2)]),
            lambda c:c.update(units='degrees'),
            lambda c:c.update(thresholds={'opening_iou_min':0}),
            lambda c:c.update(thresholds={'unknown':1}),
        ]
        for index,mutate in enumerate(mutations):
            with self.subTest(index=index):
                config=benchmark();mutate(config);repin(config)
                with self.assertRaises(ValueError):evaluate(config)

    def test_nonfinite_coordinates_and_budget_excess_are_rejected(self):
        for value in (float('nan'),float('inf'),100000001):
            config=benchmark();config['cases'][0]['prediction']['position_m'][0]=value
            with self.assertRaises(ValueError):evaluate(config)
        config=benchmark();config['cases']*=129
        with self.assertRaisesRegex(ValueError,'128'):evaluate(repin(config))

    def test_real_designation_does_not_authenticate_review_or_prove_accuracy(self):
        config=benchmark();config['dataset_kind']='reviewed_real'
        report=evaluate(repin(config))
        self.assertEqual(report['dataset_kind'],'reviewed_real')
        self.assertFalse(report['real_world_accuracy_established'])
        self.assertIn('not authenticated',report['reference_provenance'])

    def test_output_is_fresh_and_retains_exact_reference_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=benchmark();snapshot=copy.deepcopy(config)
            report=run(config,root/'run')
            self.assertEqual(config,snapshot)
            self.assertEqual(json.loads((root/'run'/'config.json').read_text()),config)
            self.assertEqual(json.loads((root/'run'/'report.json').read_text()),report)
            with self.assertRaisesRegex(ValueError,'Fresh'):run(config,root/'run')
            invalid=copy.deepcopy(config);invalid['reference_sha256']='0'*64
            with self.assertRaises(ValueError):run(invalid,root/'invalid')
            self.assertFalse((root/'invalid').exists())

    def test_packaged_synthetic_example_runs_through_cli(self):
        sample=Path(__file__).resolve().parents[1]/'examples'/'desktop'/'reconstruction-benchmark-synthetic.json'
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'benchmark'
            self.assertEqual(main(['--config',str(sample),'--output',str(output)]),0)
            report=json.loads((output/'report.json').read_text())
            self.assertEqual(report['dataset_kind'],'synthetic')
            self.assertEqual(report['summary']['case_count'],3)
            self.assertEqual(report['summary']['missing_predictions'],1)
            self.assertFalse(report['summary']['all_cases_within_thresholds'])


if __name__=='__main__':unittest.main()
