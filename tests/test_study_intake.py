"""Synthetic contract fixtures test intake lineage; no physical labels claimed."""
from pathlib import Path
import hashlib,json,tempfile,unittest
from PIL import Image
from voxel_mapper import study_intake as intake,study_site_evaluation as evaluation,study_component_learning as reader
from voxel_mapper.building_spec import digest
from test_study_training_coverage import fixture


def dataset(root,site,source,colour,building=None):
    p=root/site;manifest=fixture(p,[(building or site+'-house',source,['roof','wall'])])
    manifest['dataset_kind']='contract_fixture_only'
    for row in manifest['records']:
        row['evidence_level']='reviewed_source_trace'
        path=p/row['input_file'];Image.new('L',(32,32),colour).save(path)
        pin=hashlib.sha256(path.read_bytes()).hexdigest();row['input_sha256']=pin;manifest['output_sha256'][row['input_file']]=pin
    manifest['id']=digest({k:v for k,v in manifest.items() if k!='id'});(p/'dataset.json').write_text(json.dumps(manifest))
    return {'id':site,'site_id':site,'directory':site,'manifest_sha256':hashlib.sha256((p/'dataset.json').read_bytes()).hexdigest()}


def request(root,definitions,evaluation_sites=None,**extras):
    p=root/'request.json';p.write_text(json.dumps({'version':intake.VERSION,'datasets':definitions,'evaluation_sites':evaluation_sites or [],**extras}));return p


class StudyIntakeTests(unittest.TestCase):
    def test_single_site_is_context_only_and_not_an_independent_benchmark(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);d=dataset(root,'park-a','a'*64,20)
            out=root/'intake';r=intake.build(request(root,[d]),out)
            self.assertEqual(r['summary']['reviewed_examples_retained'],2)
            self.assertEqual(r['site_reservation']['status'],'awaiting_independent_evaluation_site')
            self.assertFalse(r['model_weights_updated']);self.assertEqual(r['training_labels_generated'],0)
            self.assertEqual(len(reader.read_dataset(out)[1]),2)
            with self.assertRaisesRegex(ValueError,'independent evaluation site'):evaluation.train(out,root/'model')

    def test_rejected_label_is_excluded_but_accepting_a_world_never_adds_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);d=dataset(root,'park-a','a'*64,20);d['record_decisions']={'record-0-0':'rejected'}
            context=root/'world.json';context.write_text('{"preview":true}');pin=hashlib.sha256(context.read_bytes()).hexdigest()
            asset={'id':'world','site_ids':['park-a'],'kind':'minecraft_reference','path':'world.json','sha256':pin,'source':'test fixture','license':'test fixture'}
            feedback={'id':'review','result_asset_id':'world','decision':'accepted','reason':'contract only','review_basis':'synthetic test review'}
            out=root/'intake';r=intake.build(request(root,[d],context_assets=[asset],feedback=[feedback]),out)
            self.assertEqual(r['summary']['reviewed_examples_retained'],1)
            self.assertEqual(r['excluded_records'][0]['decision'],'rejected')
            self.assertFalse(r['context_assets'][0]['learning_eligible'])
            self.assertEqual(r['review_feedback'][0]['training_labels_generated'],0)

    def test_shared_sources_buildings_and_identical_crops_cannot_cross_sites(self):
        for mode in ['source','building','crop']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);a=dataset(root,'park-a','a'*64,20,building='same' if mode=='building' else None)
                b=dataset(root,'park-b','a'*64 if mode=='source' else 'b'*64,20 if mode=='crop' else 220,building='same' if mode=='building' else None)
                out=root/'intake'
                with self.assertRaisesRegex(ValueError,'leakage'):intake.build(request(root,[a,b],['park-b']),out)
                self.assertFalse(out.exists())

    def test_shared_context_file_cannot_cross_reserved_sites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=dataset(root,'park-a','a'*64,20);b=dataset(root,'park-b','b'*64,220)
            path=root/'survey.txt';path.write_text('shared original survey')
            asset={'id':'survey','site_ids':['park-a','park-b'],'kind':'lidar','path':'survey.txt','sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'source':'fixture','license':'fixture'}
            with self.assertRaisesRegex(ValueError,'shared context'):intake.build(request(root,[a,b],['park-b'],context_assets=[asset]),root/'intake')

    def test_changed_input_assets_and_manifest_fail_atomically(self):
        for mode in ['asset','manifest']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);a=dataset(root,'park-a','a'*64,20)
                if mode=='asset':next((root/'park-a'/'examples').rglob('input.png')).write_bytes(b'changed')
                else:a['manifest_sha256']='f'*64
                with self.assertRaises(ValueError):intake.build(request(root,[a]),root/'intake')
                self.assertFalse((root/'intake').exists())

    def test_site_trainer_keeps_evaluation_out_of_normalization_and_weights(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=dataset(root,'park-a','a'*64,20);b=dataset(root,'park-b','b'*64,220)
            out=root/'intake';r=intake.build(request(root,[a,b],['park-b']),out)
            with self.assertRaisesRegex(ValueError,'site-isolated trainer'):reader.read_dataset(out)
            with self.assertRaisesRegex(ValueError,'site-isolated trainer'):reader.train(out,root/'unsafe',epochs=2)
            result=evaluation.train(out,root/'safe',epochs=2,hidden_units=2)
            model=reader.load_model(root/'safe'/'model.json')
            self.assertEqual(model['training_sources'],['a'*64]);self.assertEqual(result['evaluation_sources'],['b'*64])
            self.assertEqual(result['training_records'],2);self.assertEqual(result['evaluation_records'],2)
            self.assertFalse(result['production_eligible'])
            _,rows,x,_=reader.read_dataset(out,allow_reserved_evaluation=True)
            import numpy as np
            mean=np.mean([v for v,row in zip(x,rows) if row['site_id']=='park-a'],axis=0)
            self.assertTrue(np.allclose(model['input_normalization']['mean'],mean))
            # No train+holdout refit: final checkpoint retains only park-a lineage.
            self.assertNotIn('b'*64,model['training_sources'])

    def test_rehashed_forged_reservation_is_recomputed_before_training(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=dataset(root,'park-a','a'*64,20);b=dataset(root,'park-b','b'*64,220)
            out=root/'intake';r=intake.build(request(root,[a,b],['park-b']),out)
            r['site_reservation']['training_record_ids']+=r['site_reservation']['evaluation_record_ids']
            r['id']=digest({k:v for k,v in r.items() if k!='id'});(out/'dataset.json').write_text(json.dumps(r))
            with self.assertRaisesRegex(ValueError,'reservation changed'):evaluation.train(out,root/'model',epochs=2)
            self.assertFalse((root/'model').exists())

    def test_fresh_output_and_source_snapshots_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);d=dataset(root,'park-a','a'*64,20);p=root/'park-a'/'dataset.json';before=p.read_bytes()
            q=request(root,[d]);out=root/'intake';r=intake.build(q,out)
            self.assertEqual((out/'datasets/park-a/dataset.json').read_bytes(),before)
            with self.assertRaisesRegex(ValueError,'Fresh'):intake.build(q,out)
            self.assertEqual(p.read_bytes(),before)

if __name__=='__main__':unittest.main()
