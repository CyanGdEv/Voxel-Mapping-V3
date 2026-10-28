import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image,ImageDraw

from voxel_mapper import user_path_supervision as user, paving_binary_learning as binary
from voxel_mapper.generation_cycles import atomic_json,file_hash


class UserPathTests(unittest.TestCase):
    def test_fine_marker_mode_retains_dotted_boundaries_but_rejects_isolated_specks(self):
        rgb=np.zeros((80,100,3),np.uint8)
        for x in (10,17,24):rgb[20,x]=[180,30,20]
        rgb[60,80]=[180,30,20]
        regular,_=user.extract(rgb);fine,rejected=user.extract(rgb,fine_markers=True)
        self.assertEqual(len(regular),0);self.assertEqual(len(fine),3)
        self.assertGreater(rejected['path_boundary'],0)
        with self.assertRaises(ValueError):user.extract(rgb,fine_markers='false')

    def test_whole_example_holdout_and_location_vs_water_boundary_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);entries=[]
            for i in range(2):
                rgb=np.full((128,256,3),[150+i,130,110],np.uint8);rgb[40:80]=[50,100,55]
                clean=root/f'clean{i}.png';Image.fromarray(rgb).save(clean)
                reference=root/f'ref{i}.png';im=Image.fromarray(rgb);d=ImageDraw.Draw(im)
                for x in range(12,249,8):
                    d.ellipse((x-2,38,x+2,42),fill=(255,0,0))
                    d.ellipse((x-2,78,x+2,82),fill=(0,0,255))
                im.save(reference);receipt=root/f'receipt{i}.json';atomic_json(receipt,{'width':256,'height':128,
                    'image_sha256':file_hash(clean),'extent_epsg3857':[i*1000.,0.,i*1000.+128.,64.]})
                registration=root/f'reg{i}.json';atomic_json(registration,{'reference_sha256':file_hash(reference),
                    'clean_source_sha256':file_hash(clean),'metadata_sha256':file_hash(receipt),
                    'reference_size':[256,128],'clean_size':[256,128],'reference_to_clean':[[1,0,0],[0,1,0]],
                    'inliers':30,'inlier_error_clean_pixels_p95':.1})
                entries.append({'id':f'crop{i}','site_id':'same-park','reference':str(reference),'clean':str(clean),
                    'metadata':str(receipt),'registration':str(registration),'water_role':'location' if i==0 else 'boundary'})
            report=user.train_many(entries,root/'trained')
            self.assertTrue(report['same_park_examples']);self.assertFalse(report['production_eligible'])
            self.assertTrue(all(not f['held_out_source_in_fitting'] for f in report['folds']))
            self.assertTrue(all(f['minimum_training_distance_m']>=24 for f in report['folds']))
            water=json.loads((root/'trained/water-boundary-model.json').read_text());user.validate_model(water)
            self.assertEqual(water['version'],user.WATER_MODEL_VERSION)
            self.assertEqual(water['training_record_ids'],['crop1'])
            with self.assertRaises(ValueError):binary.validate_model(water)
            duplicate=[entries[0],{**entries[0],'id':'copy'}]
            with self.assertRaisesRegex(ValueError,'Same clean image'):user.train_many(duplicate,root/'bad')
            with self.assertRaisesRegex(ValueError,'Safe bounded'):
                user.train_many([entries[0],{**entries[1],'id':'../escape'}],root/'bad-id')

    def test_end_to_end_user_dots_train_only_on_separate_clean_rgb(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rgb=np.full((128,256,3),[150,130,110],np.uint8)
            rgb[40:80]=[50,100,55];clean=root/'clean.png';Image.fromarray(rgb).save(clean)
            reference=root/'reference.png';im=Image.fromarray(rgb);draw=ImageDraw.Draw(im)
            for y in (40,80):
                for x in range(12,249,8):draw.ellipse((x-2,y-2,x+2,y+2),fill=(255,0,0))
            draw.ellipse((170,15,176,21),fill=(0,255,0));draw.ellipse((180,95,186,101),fill=(0,0,255));im.save(reference)
            receipt=root/'receipt.json';atomic_json(receipt,{'width':256,'height':128,
                'image_sha256':file_hash(clean),'extent_epsg3857':[0.,0.,128.,64.]})
            registration=root/'registration.json';atomic_json(registration,{'reference_sha256':file_hash(reference),
                'clean_source_sha256':file_hash(clean),'metadata_sha256':file_hash(receipt),
                'reference_size':[256,128],'clean_size':[256,128],'reference_to_clean':[[1,0,0],[0,1,0]],
                'inliers':30,'inlier_error_clean_pixels_p95':.1})
            report=user.train(reference,clean,receipt,registration,root/'result')
            self.assertEqual(report['counts']['path_boundary'],60)
            self.assertGreater(report['head_parameters_updated_l2'],0)
            self.assertFalse(report['replaces_paving_model'])
            self.assertIn('always_boundary_reference',report['spatial_holdout'])
            model=json.loads((root/'result/model.json').read_text());user.validate_model(model)
            self.assertEqual(model['training_source_sha256'],[file_hash(clean)])
            self.assertNotIn(file_hash(reference),model['training_source_sha256'])

    def test_colour_glyphs_remain_points_and_large_tree_is_not_a_canopy_outline(self):
        im=Image.new('RGB',(160,80),(80,100,65));draw=ImageDraw.Draw(im)
        draw.ellipse((10,10,14,14),fill=(255,0,0));draw.ellipse((30,10,34,14),fill=(0,0,255))
        draw.ellipse((60,20,90,50),fill=(0,255,0));draw.rectangle((120,5,121,5),fill=(255,0,0))
        points,rejected=user.extract(np.array(im));self.assertEqual(len(points),3)
        labels={p['label']:p for p in points};self.assertEqual(labels['path_boundary']['reference_xy'],[12.,12.])
        self.assertGreater(labels['tree_location']['glyph_radius_pixels'],10)
        self.assertGreater(rejected['path_boundary'],0)
        with self.assertRaises(ValueError):user.extract(np.zeros((10,10,3),np.float32))

    def test_registration_requires_quality_and_keeps_native_coordinates(self):
        points=[{'id':'a','reference_xy':[10.,20.]}]
        registration={'reference_to_clean':[[1,0,2],[0,1,-1]],'inliers':20,
            'inlier_error_clean_pixels_p95':1.1,'clean_size':[100,100]}
        self.assertEqual(user.register(points,registration)[0]['clean_xy'],[12.,19.])
        with self.assertRaises(ValueError):user.register(points,{**registration,'inlier_error_clean_pixels_p95':3})
        with self.assertRaises(ValueError):user.register(points,{**registration,'reference_to_clean':[[0,0,0],[0,0,0]]})

    def test_sparse_targets_do_not_turn_all_unmarked_ground_into_negatives(self):
        points=[{'label':'path_boundary','clean_xy':[x,32.]} for x in range(8,121,8)]
        target=user.sparse_targets(points,(64,128));self.assertEqual(target[32,40],1)
        self.assertEqual(target[38,40],0);self.assertEqual(target[2,40],255)
        self.assertEqual(target[35,40],255)

    def test_tree_overlapping_path_fills_ground_without_erasing_hard_boundaries(self):
        shape=(40,60);foot=np.zeros(shape,bool);foot[16:24,3:57]=True
        canopy=np.zeros(shape,bool);canopy[10:30,23:38]=True
        observed=foot & ~canopy;building=np.zeros(shape,bool);building[16:20,27:30]=True
        water=np.zeros(shape,bool);water[20:24,32:35]=True
        grass=np.zeros(shape,bool);grass[16:18,35:38]=True
        final,inferred=user.fill_tree_gaps(foot,observed,canopy,building,water,grass)
        self.assertTrue(final[21,25]);self.assertTrue(inferred[21,25])
        self.assertFalse(final[17,28]);self.assertFalse(final[21,33]);self.assertFalse(final[16,36])
        self.assertFalse(final[12,25]);self.assertTrue(canopy[12,25])
        # A nearby isolated tree with no established path footprint creates no path.
        foot[2:6,2:6]=True;canopy[2:6,2:6]=True
        final,_=user.fill_tree_gaps(foot,observed,canopy,building,water,grass)
        self.assertFalse(final[3,3])

    def test_annotated_input_cannot_be_substituted_for_clean_features(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);reference=root/'reference.png';Image.new('RGB',(64,64),(255,0,0)).save(reference)
            clean=root/'clean.png';Image.new('RGB',(64,64),(140,130,120)).save(clean)
            receipt=root/'receipt.json';atomic_json(receipt,{'image_sha256':file_hash(clean)})
            registration=root/'registration.json';atomic_json(registration,{'reference_sha256':file_hash(reference),
                'clean_source_sha256':file_hash(clean),'metadata_sha256':file_hash(receipt)})
            with self.assertRaisesRegex(ValueError,'Separately pinned'):
                user.train(reference,reference,receipt,registration,root/'bad')

    def test_dedicated_boundary_checkpoint_is_rejected_by_paving_loader(self):
        from voxel_mapper import aerial_semantic_network as net
        from voxel_mapper.desktop_memory import digest
        rng=np.random.default_rng(1);x=rng.normal(size=(100,31)).astype(np.float32);y=np.arange(100)%2
        fit=net.fit(x,y,{'epochs':1,'hidden':8},class_count=2)
        rows=[{'record':{'id':'crop','site_id':'alton-towers','source_sha256':'a'*64}}]
        model=binary._model(fit,'rgb_context',{'id':'b'*64},'c'*64,rows)
        model.update(version=user.MODEL_VERSION,labels=user.BOUNDARY_LABELS,
            task='projected_path_boundary_not_paving',marker_colors_used_as_features=False)
        model['artifact_sha256']=digest({k:v for k,v in model.items() if k!='artifact_sha256'})
        user.validate_model(model)
        with self.assertRaises(ValueError):binary.validate_model(model)
        self.assertEqual(user.probabilities(x.reshape(10,10,31),model).shape,(10,10))


if __name__=='__main__':unittest.main()
