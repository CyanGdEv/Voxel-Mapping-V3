import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from voxel_mapper import boundary_alignment_review as review
from voxel_mapper.generation_cycles import file_hash


def fixture(root):
    def put(name, value):
        p=root/name; p.write_text(json.dumps(value)); return p
    def image(name, array):
        p=root/name; Image.fromarray(array).save(p); return p
    def pin(entry, key, path):
        entry[key]=path.name; entry[key+'_sha256']=file_hash(path)
    rgb=image('rgb.png',np.full((128,128,3),130,np.uint8))
    ground=np.full((128,128),255,np.uint8);ground[20:24,10:110]=0;ground[25:27,10:100]=2
    canopy=image('canopy.png',np.zeros((128,128),np.uint8));target=image('ground.png',ground)
    fields=np.zeros((128,128,4),np.float32);fields[:,:,3]=1
    np.savez_compressed(root/'fields.npz',features=fields)
    receipt=put('receipt.json',{'image_sha256':file_hash(rgb),'width':128,'height':128,'extent_epsg3857':[0,0,128,128]})
    field_receipt=put('fields.json',{'image_sha256':file_hash(rgb),'features_sha256':file_hash(root/'fields.npz')})
    area={'id':'synthetic','label_source_image_sha256':file_hash(rgb)}
    for key,path in [('image_file',rgb),('receipt_file',receipt),('ground_mask_file',target),('canopy_mask_file',canopy),('lidar_features_file',root/'fields.npz'),('lidar_receipt_file',field_receipt)]:pin(area,key,path)
    source=put('source-config.json',{'version':'mapping-source-layers-v1','site':'Synthetic','areas':[area],'providers':[],'offline':True})
    comparison=put('comparison.json',{'version':'mapping-source-layers-v1','areas':[{'id':'synthetic','title':'Synthetic','size':[128,128],'extent_epsg3857':[0,0,128,128],'reference_receipt':json.loads(receipt.read_text()),'layers':[]}]})
    pred=image('prediction.png',np.zeros((128,128),np.uint8))
    model=put('model.json',{'version':'layered-surface-cpu-model-v1','training_record_ids':['different-image'],'training_site_ids':['other-park'],'training_source_sha256':['a'*64]})
    entry={'area_id':'synthetic','site_id':'park','scope':'park_held_out','source_image_sha256':file_hash(rgb)};pin(entry,'path',pred);pin(entry,'model_file',model)
    config={'version':review.VERSION,'predictions':[entry]};pin(config,'comparison_file',comparison);pin(config,'source_config_file',source)
    return config


class BoundaryReviewTests(unittest.TestCase):
    def correspondences(self):
        reference=np.array([[24*x+8+i,24*y+8+i] for x in range(7) for y in range(5) for i in (0,3,6)],float)
        return reference-np.array([5.,-3.]),reference

    def test_translation_has_spatial_checks_and_never_applies_transform(self):
        source,reference=self.correspondences();result=review.translation_review(source,reference,[1,1])
        self.assertEqual(result['status'],'relative_translation_supported')
        np.testing.assert_allclose(result['shift_source_to_reference_pixels'],[5,-3])
        self.assertGreaterEqual(result['check_matches'],8)
        self.assertFalse(result['registration_verified']);self.assertFalse(result['automatic_transform_applied'])

    def test_check_points_do_not_select_the_fitted_translation(self):
        source,reference=self.correspondences();first=review.translation_review(source,reference,[1,1])
        roles=np.array([p['role']=='check' for p in first['points']]);source[roles]+=np.array([8,0])
        second=review.translation_review(source,reference,[1,1])
        np.testing.assert_array_equal(second['shift_source_to_reference_pixels'],first['shift_source_to_reference_pixels'])
        self.assertEqual(second['status'],'relative_fit_requires_review')
        self.assertGreater(second['check_after_p50_m'],5)

    def test_sparse_matches_do_not_emit_a_shift(self):
        source,reference=self.correspondences();result=review.translation_review(source[:5],reference[:5],[1,1])
        self.assertEqual(result['status'],'insufficient_spatial_support')
        self.assertNotIn('shift_source_to_reference_pixels',result)

    def test_sampling_is_ground_metres_not_web_mercator_metres(self):
        near_equator=review.ground_sampling([0,0,100,100],(100,100))
        high_latitude=review.ground_sampling([0,8399737,100,8399837],(100,100))
        self.assertGreater(near_equator[0],.99);self.assertLess(high_latitude[0],.51)

    def inputs(self):
        rgb=np.full((32,32,3),130,np.uint8);ground=np.full((32,32),255,np.uint8);ground[12:16,4:28]=0
        canopy=np.zeros((32,32),np.uint8);fields=np.zeros((32,32,4),np.float32);prediction=np.zeros((32,32),np.uint8)
        return rgb,ground,canopy,fields,prediction,np.zeros((32,32),bool),np.zeros((32,32),bool)

    def test_missing_lidar_cannot_be_used_as_low_flat_paving(self):
        args=self.inputs();masks=review.disagreement_masks(*args,[1,1])
        self.assertFalse(masks['unknown_path_margin'].any())
        self.assertFalse(masks['path_building_overlap'].any())

    def test_roof_and_tree_overlap_remain_separate_review_reasons(self):
        rgb,g,c,f,p,b,w=self.inputs();b[13,8]=True;f[13,8]=[.5,0,0,1]
        masks=review.disagreement_masks(rgb,g,c,f,p,b,w,[1,1]);self.assertTrue(masks['path_building_overlap'][13,8])
        rgb[13,8]=[30,150,30];c[13,8]=1
        masks=review.disagreement_masks(rgb,g,c,f,p,b,w,[1,1]);self.assertFalse(masks['path_building_overlap'][13,8]);self.assertTrue(masks['path_canopy_check'][13,8])

    def test_unknown_ground_is_not_scored_as_labelled_grass_or_water(self):
        rgb,g,c,f,p,b,w=self.inputs();w[1:5,1:5]=True
        masks=review.disagreement_masks(rgb,g,c,f,p,b,w,[1,1])
        self.assertFalse(masks['water_map_disagreement'][1:5,1:5].any())
        self.assertFalse(masks['grass_predicted_paving'].any())

    def test_queue_reports_its_truncation_and_keeps_category_diversity(self):
        masks={k:np.zeros((64,64),bool) for k in ('path_prediction_miss','water_map_disagreement')}
        masks['path_prediction_miss'][::4,::4]=True;masks['water_map_disagreement'][20:22,20:22]=True
        rows,stats=review.components(masks,[1,1],limit=48,include_stats=True)
        self.assertEqual(len(rows),48);self.assertGreater(stats['omitted_by_window_limit'],0)
        self.assertIn('water_map_disagreement',{r['category'] for r in rows})

    def test_park_holdout_lineage_rejects_same_park_even_with_a_different_image_id(self):
        model={'version':'layered-surface-cpu-model-v1','training_record_ids':['other-view'],'training_site_ids':['park'],'training_source_sha256':['a'*64]}
        with self.assertRaisesRegex(ValueError,'exclude'):
            review.prediction_lineage(model,{'site_id':'park'},'new-view','b'*64)

    def test_pinned_build_is_deterministic_and_never_edits_source_labels(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config=fixture(root);before=file_hash(root/'ground.png')
            a=review.run(config,root/'a',base=root);b=review.run(config,root/'b',base=root)
            self.assertEqual(a,b);self.assertGreater(a['queue_windows'],0)
            self.assertEqual(a['training_labels_changed'],0);self.assertEqual(a['transforms_applied'],0)
            self.assertFalse(a['training_readiness']['ready']);self.assertEqual(file_hash(root/'ground.png'),before)

    def test_changed_prediction_pin_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config=fixture(root);(root/'prediction.png').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed'):
                review.run(config,root/'out',base=root)

    def test_note_import_requires_exact_parent_source_pins(self):
        queue={'id':'queue','source_comparison_sha256':'c'*64,'items':[{'id':'one','area_id':'area','reference_sha256':'a'*64,'parent_ground_sha256':'b'*64}]}
        note={'version':'boundary-alignment-review-notes-v1','queue_id':'queue','source_comparison_sha256':'c'*64,'automatically_approved':False,'training_labels_changed':0,'transforms_applied':0,'notes':[{'item_id':'one','area_id':'area','reference_sha256':'a'*64,'parent_ground_sha256':'b'*64,'decision':'correction_needed','notes':'Check source survey.'}]}
        self.assertEqual(review.validate_notes(note,queue)['valid_notes'],1)
        note['notes'][0]['parent_ground_sha256']='d'*64
        with self.assertRaisesRegex(ValueError,'differs'):review.validate_notes(note,queue)

    def test_desktop_job_is_registered(self):
        from voxel_mapper.desktop_app import JOB_KINDS
        from voxel_mapper.desktop_runtime import KINDS,HEAVY
        self.assertIn('boundary_alignment_review',KINDS&HEAVY)
        self.assertIn('boundary_alignment_review',[k for _,k in JOB_KINDS])

    def test_desktop_subprocess_builds_queue_without_training(self):
        from voxel_mapper.desktop_runtime import DesktopRuntime,_wait
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config=fixture(root);request=root/'request.json';request.write_text(json.dumps(config))
            runtime=DesktopRuntime(root/'runtime',workers=1,memory_budget_mb=6144)
            try:
                job=_wait(runtime,runtime.submit('boundary_alignment_review',request),timeout=30)
                self.assertEqual(job['status'],'completed',job)
                report=json.loads((Path(job['output_directory'])/'report.json').read_text())
                self.assertGreater(report['queue_windows'],0)
                self.assertEqual(report['training_labels_changed'],0)
                self.assertFalse(report['models_retrained'])
                self.assertEqual(runtime.store.summary()['checkpoints'],0)
            finally:runtime.close(wait=True)


if __name__=='__main__':unittest.main()
