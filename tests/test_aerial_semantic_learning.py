import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from PIL import Image
from pyproj import Transformer

from voxel_mapper import aerial_semantic_network as net, aerial_semantic_learning as learning
from voxel_mapper.desktop_memory import digest
from voxel_mapper.generation_cycles import atomic_json,file_hash


def fixture(root):
    items=[];annotations={};colours=np.array([[160,160,160],[170,80,45],[65,65,75],[50,150,50],[35,60,120]],np.int16)
    for site in range(3):
        name='site'+str(site);source=root/name;source.mkdir();rng=np.random.default_rng(site)
        rgb=np.zeros((64,64,3),np.uint8);regions=[]
        for c,colour in enumerate(colours):
            left=c*12;right=64 if c==4 else left+12
            rgb[:,left:right]=np.clip(colour+rng.integers(-2,3,(64,right-left,3)),0,255)
            regions.append({'class':c,'points':[[left+1,4],[right-1,4],[right-1,60],[left+1,60]]})
        Image.fromarray(rgb).save(source/'source-image.bin',format='PNG');pin=file_hash(source/'source-image.bin')
        ext=[site*1000.,0.,site*1000.+64.,64.];metadata={'image_sha256':pin,'extent_epsg3857':ext,'attribution':'Synthetic fixture'}
        atomic_json(source/'report.json',{'imagery':metadata});inverse=Transformer.from_crs(3857,4326,always_xy=True)
        west,south=inverse.transform(ext[0],ext[1]);east,north=inverse.transform(ext[2],ext[3])
        items.append({'id':name,'site_id':name,'source_directory':str(source),'input_size':64,'bounds_wgs84':[west,south,east,north]});annotations[name]=regions
    ann=root/'annotations.json';atomic_json(ann,{'version':'aerial-visual-annotations-v1','status':'provisional_visible_region_annotations_not_human_ground_truth',
        'class_names':net.CLASSES,'boundary_ignore_pixels':1,'annotations':annotations})
    data=root/'dataset';learning.build_dataset(items,ann,data);return data,items


def reseal_manifest(path,manifest):
    manifest['id']=digest({k:v for k,v in manifest.items() if k!='id'});atomic_json(path,manifest)


class AerialSemanticNetworkTests(unittest.TestCase):
    def test_all_network_weights_learn_and_source_only_features_are_deterministic(self):
        rng=np.random.default_rng(5);x=rng.normal(size=(250,net.FEATURE_COUNT)).astype(np.float32)
        y=np.tile(np.arange(5),50);x[:,:5]=np.eye(5)[y]*3
        fit=net.fit(x,y,{'epochs':12,'hidden':8})
        self.assertGreater(fit['weight_change_l2'],0)
        self.assertLess(fit['loss_history'][-1]['weighted_cross_entropy'],fit['loss_history'][0]['weighted_cross_entropy'])
        rgb=np.full((32,32,3),[100,120,140],np.uint8)
        features=net.features(rgb,1)
        self.assertEqual(features.shape,(32,32,net.FEATURE_COUNT))
        np.testing.assert_array_equal(features,net.features(rgb.copy(),1))
        self.assertTrue(np.isfinite(features).all())
        with self.assertRaises(ValueError):net.fit(x,y,{'epochs':121})
        with self.assertRaises(ValueError):net.features(rgb,float('nan'))

    def test_missing_class_bad_optimizer_and_cancelled_training_are_rejected(self):
        x=np.zeros((20,net.FEATURE_COUNT),np.float32)
        with self.assertRaises(ValueError):net.fit(x,np.zeros(20,np.int64))
        with self.assertRaises(ValueError):net.fit(x,np.tile(np.arange(5),4),{'learning_rate':'0.01'})
        with self.assertRaises(net.CancelledError):net.fit(x,np.tile(np.arange(5),4),{'epochs':1},cancelled=lambda:True)


class AerialSemanticLearningTests(unittest.TestCase):
    def test_park_holdout_never_uses_held_site_and_prediction_needs_no_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data,items=fixture(root)
            report=learning.train(data,root/'model',{'epochs':3,'hidden':8})
            self.assertTrue(report['model_weights_updated']);self.assertGreater(report['weight_change_l2'],0)
            for fold in report['folds']:self.assertNotIn(fold['held_out_site'],fold['training_sites'])
            self.assertEqual(len(report['folds']),3)
            source=Path(items[0]['source_directory']);receipt=json.loads((source/'report.json').read_text())['imagery']
            model=root/'model/folds/site0/model.json'
            prediction=learning.infer(source/'source-image.bin',receipt,model,root/'prediction',threshold=.2,margin=0)
            self.assertFalse(prediction['source_in_training']);self.assertFalse(prediction['geometry_verified'])
            self.assertEqual(sum(prediction['class_pixel_counts'].values())+prediction['unknown_pixels'],4096)
            self.assertEqual(prediction['world_blocks_generated'],0)

    def test_changed_or_resealed_mask_cannot_replace_visual_annotation_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data,_=fixture(root);path=data/'dataset.json';manifest=json.loads(path.read_text());row=manifest['records'][0]
            mask=data/row['mask_file'];image=np.asarray(Image.open(mask)).copy();image[10,10]=(int(image[10,10])+1)%5;Image.fromarray(image).save(mask)
            with self.assertRaisesRegex(ValueError,'mask asset changed'):learning.read_dataset(data)
            row['mask_sha256']=file_hash(mask);reseal_manifest(path,manifest)
            with self.assertRaisesRegex(ValueError,'pinned visual annotation'):learning.read_dataset(data)

    def test_duplicate_original_and_overlapping_held_site_footprints_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data,_=fixture(root);path=data/'dataset.json';manifest=json.loads(path.read_text())
            a,b=manifest['records'][:2]
            # Equal source IDs across different sites fail even when all hashes are resealed.
            original=copy.deepcopy(manifest)
            b['source_file']=a['source_file'];b['source_sha256']=a['source_sha256'];b['metadata_file']=a['metadata_file'];b['metadata_sha256']=a['metadata_sha256'];b['extent_epsg3857']=a['extent_epsg3857']
            reseal_manifest(path,manifest)
            with self.assertRaisesRegex(ValueError,'different held-out sites'):learning.read_dataset(data)
            manifest=original;b=manifest['records'][1];b['extent_epsg3857']=manifest['records'][0]['extent_epsg3857']
            meta=json.loads((data/b['metadata_file']).read_text());meta['extent_epsg3857']=b['extent_epsg3857'];atomic_json(data/b['metadata_file'],meta);b['metadata_sha256']=file_hash(data/b['metadata_file']);reseal_manifest(path,manifest)
            with self.assertRaisesRegex(ValueError,'footprints overlap'):learning.read_dataset(data)

    def test_checkpoint_is_reused_and_modified_weights_or_model_acceptance_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data,_=fixture(root);settings={'epochs':2,'hidden':8}
            first=learning.ensure_checkpoint(data,root/'memory',settings);second=learning.ensure_checkpoint(data,root/'memory',settings)
            self.assertTrue(first['model_weights_updated']);self.assertFalse(second['model_weights_updated'])
            self.assertEqual(first['model_sha256'],second['model_sha256'])
            path=Path(first['model_file']);model=json.loads(path.read_text());model['production_eligible']=True
            model['artifact_sha256']=digest({k:v for k,v in model.items() if k!='artifact_sha256'});atomic_json(path,model)
            with self.assertRaises(ValueError):learning.load_model(path)
            with self.assertRaisesRegex(ValueError,'Persisted semantic checkpoint changed'):learning.ensure_checkpoint(data,root/'memory',settings)

    def test_new_source_dataset_version_trains_a_new_semantic_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data,items=fixture(root);settings={'epochs':2,'hidden':8}
            first=learning.ensure_checkpoint(data,root/'memory',settings)
            source=Path(items[0]['source_directory']);path=source/'source-image.bin'
            pixels=np.asarray(Image.open(path)).astype(np.int16);Image.fromarray(np.clip(pixels+8,0,255).astype(np.uint8)).save(path,format='PNG')
            receipt=json.loads((source/'report.json').read_text());receipt['imagery']['image_sha256']=file_hash(path);atomic_json(source/'report.json',receipt)
            more=root/'dataset-two';learning.build_dataset(items,root/'annotations.json',more)
            second=learning.ensure_checkpoint(more,root/'memory',settings)
            self.assertTrue(second['model_weights_updated']);self.assertNotEqual(first['model_file'],second['model_file'])
            self.assertNotEqual(first['dataset_sha256'],second['dataset_sha256'])

    def test_learned_geometry_is_subtracted_from_protected_plan_coverage(self):
        from unittest.mock import patch
        from test_aerial_material_research import cache_fixture
        from test_imagery_geometry_research import aligned_aerial_config
        from voxel_mapper import imagery_geometry_research as geometry
        from shapely.geometry import box,mapping,shape
        from shapely.ops import transform
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=aligned_aerial_config();cache_fixture(root,a)
            inverse=Transformer.from_crs(3857,4326,always_xy=True);project=Transformer.from_crs(4326,3857,always_xy=True)
            protected=transform(inverse.transform,box(-210000,6980000,-209900,6980200));plan=root/'plan.geojson'
            atomic_json(plan,{'type':'FeatureCollection','features':[{'geometry':mapping(protected)}]})
            c={'version':geometry.VERSION,'site_id':a['site_id'],'site':a['site'],'imagery':a,
                'semantic_model':{'file':'fixture-model.json','sha256':'a'*64},
                'protected_plan_coverage':{'file':str(plan),'sha256':file_hash(plan),'crs':'EPSG:4326'}}
            def infer(image,receipt,model,output,**kwargs):
                output=Path(output);output.mkdir()
                polygon=transform(inverse.transform,box(*receipt['extent_epsg3857']))
                atomic_json(output/'semantic-candidates.geojson',{'type':'FeatureCollection','features':[{'type':'Feature','geometry':mapping(polygon),'properties':{'class':'paths_plazas','geometry_verified':False}}]})
                return {'source_in_training':False,'geometry_verified':False}
            with patch.object(learning,'infer',side_effect=infer):result=geometry.run(c,root/'result',root/'cache')
            data=json.loads((root/'result/learned-semantic-candidates.geojson').read_text());self.assertTrue(data['features'])
            for feature in data['features']:
                geom=transform(project.transform,shape(feature['geometry']));self.assertLess(geom.intersection(box(-210000,6980000,-209900,6980200)).area,1e-6)
            self.assertTrue(result['learned_semantics']['protected_file_sha256'])

    def test_real_desktop_training_job_saves_checkpoint_and_memory(self):
        from voxel_mapper.desktop_runtime import DesktopRuntime
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data,_=fixture(root);request=root/'request.json'
            atomic_json(request,{'version':'desktop-aerial-semantic-training-v1','dataset_directory':'dataset','settings':{'epochs':2,'hidden':8}})
            runtime=DesktopRuntime(root/'desktop',workers=1,memory_budget_mb=2048)
            try:
                jid=runtime.submit('train_aerial_semantics',request);runtime._futures[jid].result(timeout=40)
                job=runtime.store.job(jid);self.assertEqual(job['status'],'completed',job.get('error'))
                self.assertTrue(job['result']['model_weights_updated']);self.assertIn('aerial_semantic_checkpoint',runtime.store.context(20000))
            finally:runtime.close(wait=True)

    def test_research_cycle_trains_then_reuses_separate_semantic_checkpoint(self):
        from test_research_learning_cycle import ResearchLearningCycleTests
        from voxel_mapper import research_learning_cycle as cycle
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data,_=fixture(root);config=ResearchLearningCycleTests().config(root);config['max_research_jobs']=0
            config['aerial_semantics']={'dataset_directory':str(data),'settings':{'epochs':2,'hidden':8},'use_for_geometry':False}
            first=cycle.run(config,root/'first',root/'memory',root/'cache')
            second=cycle.run(config,root/'second',root/'memory',root/'cache')
            self.assertTrue(first['aerial_semantic_checkpoint']['model_weights_updated'])
            self.assertFalse(second['aerial_semantic_checkpoint']['model_weights_updated'])
            self.assertEqual(first['aerial_semantic_checkpoint']['model_sha256'],second['aerial_semantic_checkpoint']['model_sha256'])
            self.assertFalse(second['model_weights_updated'])


if __name__=='__main__':unittest.main()
