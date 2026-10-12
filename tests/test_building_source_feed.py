import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from voxel_mapper.building_spec import from_study,build,digest
from voxel_mapper.building_source_feed import prepare,feedback_from_reviews,VERSION,diagnostics
from voxel_mapper.building_learning import rank
from tests.test_building_data_pipeline import spec


def write(root,name,value):
    raw=json.dumps(value).encode(); (root/name).write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


class SourceFeedTests(unittest.TestCase):
    def fixture(self,root,state='existing'):
        raw=b'%PDF-1.7 fixture content'; source=hashlib.sha256(raw).hexdigest(); (root/(source+'.pdf')).write_bytes(raw)
        model=build(spec()); model['source_pdf_sha256']={'plan':source,'elevation':source}
        model['width_check']={'difference_m':.1,'combined_sampling_bound_m':.5}
        model['source_state']=state
        for row in model['sources']: row['state']=state
        sha=write(root,'model.json',model)
        audit={'corrected_model_sha256':sha,'document_sha256':source,'opening_rows':[{'reviewed_perimeter_pixels':10,'near_source_fraction':.8,'status':'no_complete_outline_within_trace_bound'}]}
        auditsha=write(root,'audit.json',audit)
        config={'version':VERSION,'buildings':[{'building_id':'building-a','model':'model.json','model_sha256':sha,
            'diagnostics':[{'path':'audit.json','sha256':auditsha}],'source_directories':['.']}]}
        return config,source

    def test_computes_real_features_and_preserves_missing_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config,source=self.fixture(root)
            job,report=prepare(config,lambda p:root/p,root/'feed')
            c=job['buildings'][0]['candidates'][0]
            self.assertEqual(c['features']['source_coverage'],1)
            self.assertEqual(c['features']['boundary_support'],.8)
            self.assertAlmostEqual(c['features']['view_agreement'],.8)
            self.assertEqual(c['features']['opening_support'],0)
            self.assertFalse(c['gates']['identity_verified']);self.assertIsNone(rank([c])['selected_id'])
            self.assertEqual(c['features']['topology_quality'],0)
            self.assertIn('topology_quality',c['source_feed']['missing_features'])
            self.assertIn('missing_declared_floor_anchor',c['source_feed']['native_structural_review']['reasons'])
            self.assertEqual(c['source_feed']['original_pdf_sha256'],[source])
            self.assertEqual(report['training_labels_generated'],0)
            with self.assertRaisesRegex(ValueError,'Fresh'):prepare(config,lambda p:root/p,root/'feed')

    def test_missing_or_changed_pdf_does_not_become_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config,source=self.fixture(root);pdf=root/(source+'.pdf');pdf.unlink()
            job,report=prepare(config,lambda p:root/p,root/'missing')
            c=job['buildings'][0]['candidates'][0]
            self.assertEqual(c['features']['source_coverage'],0);self.assertFalse(c['gates']['source_verified'])
            pdf.write_bytes(b'changed')
            job,report=prepare(config,lambda p:root/p,root/'changed')
            self.assertEqual(job['buildings'],[]);self.assertIn('checksum',report['buildings'][0]['reason'])

    def test_bad_diagnostics_isolated_from_other_building(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config,_=self.fixture(root)
            second=copy.deepcopy(config['buildings'][0]);second['building_id']='building-b'
            config['buildings'][0]['diagnostics'][0]['sha256']='0'*64;config['buildings'].append(second)
            job,report=prepare(config,lambda p:root/p,root/'feed')
            self.assertEqual(len(job['buildings']),1);self.assertEqual(job['buildings'][0]['building_id'],'building-b')
            self.assertEqual(report['buildings'][0]['status'],'invalid_source_input')

    def test_proposed_state_not_relabelled_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config,_=self.fixture(root,'proposed')
            job,report=prepare(config,lambda p:root/p,root/'feed')
            c=job['buildings'][0]['candidates'][0]
            self.assertEqual(c['spec']['sources'][0]['state'],'proposed')
            self.assertFalse(c['gates']['source_verified']);self.assertEqual(report['buildings'][0]['source_state'],'proposed')

    def test_unknown_parent_and_mixed_state_handling(self):
        m={'wall_mesh':{'vertices':[[0,0,0],[1,0,0],[0,1,0]],'triangles':[[0,1,2]]}}
        self.assertEqual(from_study(m,'unknown','a'*64)['sources'][0]['state'],'unknown')
        m['wall_mesh']['source_state']='existing';m['roof_mesh']=copy.deepcopy(m['wall_mesh']);m['roof_mesh']['source_state']='proposed'
        with self.assertRaisesRegex(ValueError,'Mixed'):from_study(m,'mixed','a'*64)
        s=spec();s['sources'].append({'id':'other','sha256':'b'*64,'state':'proposed'})
        with self.assertRaisesRegex(ValueError,'separate'):build(s)

    def test_invalid_numeric_diagnostics_reject_instead_of_scoring_high(self):
        with self.assertRaises(ValueError):diagnostics({'width_check':{'difference_m':float('nan'),'combined_sampling_bound_m':1}},[],1)
        with self.assertRaises(ValueError):diagnostics({},[{'opening_rows':[{'near_source_fraction':2,'reviewed_perimeter_pixels':10}]}],1)

    def test_review_collection_binds_computed_features_to_exact_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config,_=self.fixture(root);prepare(config,lambda p:root/p,root/'feed')
            queue=json.loads((root/'feed/review-queue.json').read_text());row=queue['records'][0]
            decision={'version':'building-review-decisions-v1','records':[{'building_id':row['building_id'],
                'candidate_sha256':row['candidate_sha256'],'outcome':'rejected','review_basis':'independent_review','review_reference':'review-42'}]}
            feedback=feedback_from_reviews(queue,decision);record=feedback['records'][0]
            self.assertEqual(record['features'],row['features']);self.assertEqual(record['source_sha256'],row['source_sha256'])
            decision['records'][0]['candidate_sha256']='f'*64
            with self.assertRaisesRegex(ValueError,'Unknown'):feedback_from_reviews(queue,decision)

    def test_predictions_and_duplicate_reviews_are_not_training_labels(self):
        queue={'version':'building-review-queue-v1','records':[{'building_id':'a','candidate_sha256':'a'*64,'features':{},'source_sha256':[]}]}
        queue['content_sha256']=digest(queue)
        review={'building_id':'a','candidate_sha256':'a'*64,'outcome':'accepted','review_basis':'model_prediction','review_reference':'prediction'}
        decisions={'version':'building-review-decisions-v1','records':[review]}
        with self.assertRaisesRegex(ValueError,'reviewed'):feedback_from_reviews(queue,decisions)
        review['review_basis']='independent_review';decisions['records'].append(copy.deepcopy(review))
        with self.assertRaisesRegex(ValueError,'duplicate'):feedback_from_reviews(queue,decisions)


if __name__=='__main__':unittest.main()


class FeedIntegrityTests(unittest.TestCase):
    def test_unrelated_diagnostic_and_changed_queue_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture=SourceFeedTests();config,_=fixture.fixture(root)
            audit=json.loads((root/'audit.json').read_text());audit['corrected_model_sha256']='b'*64
            config['buildings'][0]['diagnostics'][0]['sha256']=write(root,'audit.json',audit)
            job,report=prepare(config,lambda p:root/p,root/'bad')
            self.assertEqual(job['buildings'],[]);self.assertIn('exact model',report['buildings'][0]['reason'])
            config,_=fixture.fixture(root);prepare(config,lambda p:root/p,root/'good')
            queue=json.loads((root/'good/review-queue.json').read_text());queue['records'][0]['features']['source_coverage']=0
            with self.assertRaisesRegex(ValueError,'queue changed'):
                feedback_from_reviews(queue,{'version':'building-review-decisions-v1','records':[]})
