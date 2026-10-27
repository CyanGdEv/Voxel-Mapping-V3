from pathlib import Path
import tempfile
import unittest
import json

from voxel_mapper import research_learning_cycle as cycle, study_pretrained_encoder as encoder
from test_study_transfer_learning import color_fixture
from test_study_site_transfer import build as held_site_fixture


class ResearchLearningCycleTests(unittest.TestCase):
    def config(self,root):
        dataset=root/'data';color_fixture(dataset,groups=3,per_group=4)
        graph=root/'encoder.onnx';encoder.synthetic_encoder(graph)
        return {'version':cycle.VERSION,'dataset_directory':str(dataset),'encoder_path':str(graph),
            'encoder_sha256':encoder.SYNTHETIC_SHA256,'public_sites':[
                {'site_id':'public-park','name':'Public Park','location':'Public Town','ride_types':['coaster']}],
            'max_research_jobs':1,'research':{'allowed_hosts':['example.org'],'offline':True}}

    def test_cycle_trains_once_remembers_sources_and_reuses_unchanged_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=self.config(root);queries=[]
            def research(request,*args,**kwargs):
                queries.append(request['query'])
                return {'status':'synthetic_research_fixture','sources':[{'body_sha256':'c'*64,
                    'url':'https://example.org/source.pdf','citation_id':'W123456789abc'}]}
            a=cycle.run(config,root/'first',root/'memory',root/'cache',research=research)
            b=cycle.run(config,root/'second',root/'memory',root/'cache',research=research)
            self.assertTrue(a['model_weights_updated']);self.assertFalse(b['model_weights_updated'])
            self.assertEqual(a['checkpoint_sha256'],b['checkpoint_sha256'])
            self.assertEqual(a['new_source_bodies'],1);self.assertEqual(b['new_source_bodies'],0)
            self.assertEqual(b['remembered_sources'],1)
            self.assertEqual(len(set(queries)),2)
            self.assertEqual(b['web_sources_automatically_labelled'],0)
            self.assertFalse(b['production_eligible'])

    def test_new_dataset_version_triggers_new_fitted_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=self.config(root);config['max_research_jobs']=0
            a=cycle.run(config,root/'first',root/'memory',root/'cache')
            more=root/'more-data';color_fixture(more,groups=3,per_group=6)
            config['dataset_directory']=str(more)
            b=cycle.run(config,root/'second',root/'memory',root/'cache')
            self.assertTrue(b['model_weights_updated']);self.assertNotEqual(a['checkpoint_directory'],b['checkpoint_directory'])
            self.assertNotEqual(a['checkpoint_sha256'],b['checkpoint_sha256'])

    def test_desktop_worker_cycle_persists_checkpoint_across_restart(self):
        from voxel_mapper.desktop_runtime import DesktopRuntime
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=self.config(root);config['max_research_jobs']=0
            path=root/'request.json';path.write_text(json.dumps(config));results=[]
            for i in range(2):
                runtime=DesktopRuntime(root/'desktop',workers=1,memory_budget_mb=2048)
                try:
                    identifier=runtime.submit('research_learning_cycle',path)
                    runtime._futures[identifier].result(timeout=30)
                    job=runtime.store.job(identifier)
                    self.assertEqual(job['status'],'completed',job.get('error'))
                    results.append(job['result'])
                finally:
                    runtime.close(wait=True)
            self.assertTrue(results[0]['model_weights_updated'])
            self.assertFalse(results[1]['model_weights_updated'])
            self.assertEqual(results[0]['checkpoint_sha256'],results[1]['checkpoint_sha256'])

    def test_invalid_public_profiles_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=self.config(Path(tmp));config['public_sites']=[None]
            with self.assertRaisesRegex(ValueError,'profiles must be objects'):cycle.validate(config)
            config['public_sites']=[{'site_id':[]}]
            with self.assertRaisesRegex(ValueError,'identities'):cycle.validate(config)

    def test_reserved_evaluation_rows_cannot_be_refitted_by_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=self.config(root);held=root/'held';held.mkdir();data=held_site_fixture(held)
            config['dataset_directory']=str(data)
            with self.assertRaisesRegex(ValueError,'site-isolated trainer'):
                cycle.run(config,root/'output',root/'memory',root/'cache')
            self.assertFalse((root/'output').exists())

    def test_curriculum_targets_coverage_without_leaking_local_paths_or_wrong_ride_type(self):
        rows=[{'kind':'ride_track_profile','group_id':'g','site_id':'wood-park'}]
        sites=[{'site_id':'wood-park','name':'Wood Park','location':'Town','ride_types':['coaster']},
            {'site_id':'steel-park','name':'Steel Park','location':'Town','ride_types':['coaster']},
            {'site_id':'carousel','name':'Carousel Park','ride_types':['carousel']}]
        tasks=cycle.curriculum(rows,sites,{'ride_track_profile':.9})
        self.assertEqual(tasks[0]['site_id'],'steel-park')
        self.assertEqual(tasks[0]['additional_groups_requested'],2)
        self.assertTrue(all(t['site_id']!='carousel' for t in tasks))
        self.assertIn('track elevation',tasks[0]['query'])


if __name__=='__main__':unittest.main()
