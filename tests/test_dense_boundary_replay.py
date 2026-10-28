import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from voxel_mapper import dense_boundary_replay as dense,layered_surface_benchmark as data,layered_surface_learning as net
from voxel_mapper.desktop_memory import digest
from voxel_mapper.generation_cycles import file_hash,atomic_json


def parent_fixture(root):
    root.mkdir();records=[];atomic_json(root/'recipe.json',{'fixture':True})
    for i,(id,site,reserved) in enumerate([('train','train-park',False),('alton','alton-towers',False),('reserved','flamingo-land',True)]):
        folder=root/id;folder.mkdir();g=np.full((96,96),255,np.uint8);g[8:88,8:88]=0;c=np.full_like(g,255);c[g==0]=0;c[35:40,35:40]=1;g[c==1]=255;inferred=np.zeros_like(g);inferred[45:48,45:48]=255;g[inferred>0]=255;c[inferred>0]=255
        Image.fromarray(np.full((96,96,3),i*60,np.uint8)).save(folder/'image.png');atomic_json(folder/'receipt.json',{'image_sha256':file_hash(folder/'image.png'),'width':96,'height':96})
        r={'id':id,'site_id':site,'evaluation_only':reserved,'image_file':id+'/image.png','receipt_file':id+'/receipt.json'}
        for key,array in [('ground',g),('canopy',c),('inferred',inferred),('dense_windows',np.zeros_like(g))]:
            Image.fromarray(array).save(folder/(key+'.png'));r[key+'_file']=id+'/'+key+'.png'
        for key in ('image','receipt','ground','canopy','inferred','dense_windows'):r[key+'_sha256']=file_hash(root/r[key+'_file'])
        r['ground_counts']={k:int((g==v).sum()) for k,v in data.GROUND.items()};r['canopy_counts']={k:int((c==v).sum()) for k,v in data.CANOPY.items()};records.append(r)
    m={'version':data.VERSION,'ground_labels':data.GROUND,'canopy_labels':data.CANOPY,'records':records,'recipe_sha256':file_hash(root/'recipe.json'),'reserved_evaluation_site_ids':['flamingo-land'],'independent_human_review':False,'production_eligible':False,'hidden_ground_used_as_observed_truth':False};m['id']=digest(m);atomic_json(root/'dataset.json',m);return m


def request(m):
    return {'version':dense.VERSION,'parent_dataset_id':m['id'],'independent_human_review':False,'excluded_site_ids':['flamingo-land'],'windows':[{'id':'roof-path','source_id':'train','source_sha256':m['records'][0]['image_sha256'],'independently_verified':False,'outer':[[20,20],[75,20],[75,75],[20,75]],'base':'paving','parts':[{'id':'roof','label':'building_structure','outer':[[20,20],[48,20],[48,75],[20,75]]}],'unknown':[[[55,30],[65,30],[65,40],[55,40]]]}]}


class DenseOverlayTests(unittest.TestCase):
    def test_windows_preserve_outside_canopy_inference_and_exclude_reserved_park(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);parent=root/'parent';m=parent_fixture(parent);a=request(m);atomic_json(root/'annotations.json',a);new=dense.build(parent,root/'annotations.json',root/'new')
            self.assertEqual([r['id'] for r in new['records']],['train','alton']);self.assertFalse((root/'new/reserved').exists());self.assertTrue(new['dense_overlay_changes'][0]['existing_canopy_positive_retained'])
            g=np.array(Image.open(root/'new/train/ground.png'));c=np.array(Image.open(root/'new/train/canopy.png'));old=np.array(Image.open(parent/'train/ground.png'))
            self.assertEqual(g[28,28],1);self.assertEqual(g[50,60],0);self.assertEqual(g[35,60],255);self.assertEqual(g[37,37],255);self.assertEqual(c[37,37],1);self.assertEqual(g[46,46],255);self.assertEqual(c[46,46],255)
            np.testing.assert_array_equal(g[:20],old[:20]);self.assertEqual(file_hash(root/'new/alton/ground.png'),file_hash(parent/'alton/ground.png'));self.assertEqual(file_hash(root/'new/train/image.png'),m['records'][0]['image_sha256']);data.validate(root/'new')

    def test_source_changes_or_reserved_annotation_reject_before_writing(self):
        for change in ('hash','reserved','independent'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);m=parent_fixture(root/'parent');a=request(m)
                if change=='hash':a['windows'][0]['source_sha256']='changed'
                if change=='reserved':a['windows'][0]['source_id']='reserved'
                if change=='independent':a['windows'][0]['independently_verified']=True
                atomic_json(root/'a.json',a)
                with self.assertRaises(ValueError):dense.build(root/'parent',root/'a.json',root/'new')
                self.assertFalse((root/'new').exists())

    def test_interface_anchors_ignore_unknown_margins_and_include_both_classes(self):
        g=np.full((32,32),255,np.uint8);g[5:27,5:16]=0;self.assertEqual(len(net.interface_anchors(g)),0);g[5:27,16:27]=2;a=net.interface_anchors(g)
        self.assertEqual(len(a),44);self.assertEqual(set(g[a[:,0],a[:,1]]),{0,2});self.assertEqual(set(a[:,1]),{15,16})

    def test_reject_overcommitted_sampling_before_architecture(self):
        with patch.object(net,'architecture') as architecture:
            with self.assertRaisesRegex(ValueError,'Bounded'):net.fit([{}],settings={**net.SETTINGS,'boundary_sampling_fraction':.7,'narrow_sampling_fraction':.5})
            architecture.assert_not_called()

    def test_zero_interface_sampling_preserves_default_fit_and_new_sampler_replays(self):
        import torch
        features=np.zeros((96,96,3),np.float32);features[:,:,0]=.2;g=np.zeros((96,96),np.uint8);g[:,48:]=2;c=np.zeros_like(g)
        row={'features':features,'ground':g,'canopy':c,'ground_sampling_m':.3};settings={**net.SETTINGS,'steps':2,'batch':2}
        a,ta=net.fit([row],settings=settings);b,tb=net.fit([row],settings={**settings,'boundary_sampling_fraction':0})
        for k,v in a.state_dict().items():self.assertTrue(torch.equal(v,b.state_dict()[k]))
        model,training=net.fit([row],settings={**settings,'steps':5,'boundary_sampling_fraction':.8})
        self.assertEqual(training['interface_anchor_counts'],[192]);self.assertGreater(training['anchor_draw_counts']['interface'],0);self.assertEqual(sum(training['anchor_draw_counts'].values()),10);self.assertGreater(training['parameter_change_l2'],0)

    def test_review_notes_reject_stale_labels_and_do_not_promote_ground_truth(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'annotations.json';a={'windows':[{'id':'a','source_sha256':'source'}]};atomic_json(p,a)
            note={'version':'dense-boundary-review-notes-v1','dataset_id':'dataset','annotation_sha256':file_hash(p),'reviewer':'Reviewer','notes':[{'window_id':'a','source_sha256':'source','status':'accept','comment':'Visible edge checked'}]}
            result=dense.validate_review(note,p,'dataset');self.assertEqual(result['accepted_windows'],1);self.assertFalse(result['changes_training_labels']);self.assertFalse(result['independent_human_truth_established'])
            with self.assertRaisesRegex(ValueError,'Stale'):dense.validate_review(note,p,'different')
            a['changed']=True;atomic_json(p,a)
            with self.assertRaisesRegex(ValueError,'Stale'):dense.validate_review(note,p,'dataset')

    def test_review_notes_reject_duplicate_source_or_unknown_status(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'a.json';atomic_json(p,{'windows':[{'id':'a','source_sha256':'source'}]});base={'version':'dense-boundary-review-notes-v1','dataset_id':'dataset','annotation_sha256':file_hash(p),'reviewer':'','notes':[{'window_id':'a','source_sha256':'wrong','status':'accept','comment':''}]}
            with self.assertRaisesRegex(ValueError,'source'):dense.validate_review(base,p,'dataset')
            base['notes'][0]['source_sha256']='source';base['notes'][0]['status']='promote'
            with self.assertRaisesRegex(ValueError,'decision'):dense.validate_review(base,p,'dataset')

    def test_training_rejects_overlay_in_held_out_park_before_loading_features(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);protocol=json.loads((Path(__file__).resolve().parents[1]/'voxel_mapper/data/dense-surface-boundary-protocol.json').read_text());protocol['parent_dataset_id']='parent';atomic_json(root/'protocol.json',protocol)
            atomic_json(root/'recipe.json',{'annotations':{'protocol_sha256':file_hash(root/'protocol.json'),'windows':[{'source_id':'alton'}]}})
            manifest={'parent_dataset_id':'parent','excluded_consumed_site_ids':['flamingo-land'],'records':[{'id':'alton','site_id':'alton-towers'}]}
            with patch.object(dense.data,'validate',return_value=manifest),patch.object(dense,'load_rows') as load_rows:
                with self.assertRaisesRegex(ValueError,'held-out park'):dense.run(root,root,root,root/'protocol.json',root,root/'output',root,root)
                load_rows.assert_not_called();self.assertFalse((root/'output').exists())


if __name__=='__main__':unittest.main()
