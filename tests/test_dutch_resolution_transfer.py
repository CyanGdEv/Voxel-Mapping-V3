import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from voxel_mapper import dutch_resolution_transfer as experiment,dutch_surface_sources as sources,layered_surface_benchmark as data
from voxel_mapper.surface_dataset_expansion import required_classes
from voxel_mapper.generation_cycles import atomic_json,file_hash
from voxel_mapper.desktop_memory import digest


def manifests():
    p=json.loads((Path(__file__).resolve().parents[1]/'voxel_mapper/data/dutch-resolution-transfer-protocol.json').read_text());p['parent_dataset_id']='parent'
    records=[]
    for id,site,reserved in [('old','uk',False),('efteling','efteling',False),('toverland','toverland',True)]:
        records.append({'id':id,'site_id':site,'evaluation_only':reserved,**{k+'_sha256':id+'-'+k for k in ('image','receipt','ground','canopy','inferred','dense_windows')}})
    a={'id':'native','parent_dataset_id':'parent','records':records,'reserved_evaluation_site_ids':['toverland']};b=json.loads(json.dumps(a));b.update(id='coarse',comparison_native_dataset_id='native')
    for r in b['records'][1:]:r['image_sha256']+='-coarse';r['receipt_sha256']+='-coarse'
    return a,b,p


class DutchComparisonTests(unittest.TestCase):
    def test_partial_source_scope_needs_evidence_and_keeps_four_class_default(self):
        self.assertEqual(len(required_classes({})),4)
        with self.assertRaisesRegex(ValueError,'evidence'):required_classes({'required_ground_classes':['paving']})
        self.assertEqual(required_classes({'required_ground_classes':['paving','water'],'coverage_note':'Only these surfaces are visible; lawns remain unknown.'}),['paving','water'])
        with self.assertRaises(ValueError):required_classes({'required_ground_classes':['unknown'],'coverage_note':'Unknown is not an observed class.'})

    def test_controlled_pair_rejects_changed_masks_or_old_images(self):
        a,b,p=manifests();self.assertTrue(experiment.validate_pair(a,b,p));b['records'][1]['ground_sha256']='changed'
        with self.assertRaisesRegex(ValueError,'Labels'):experiment.validate_pair(a,b,p)
        a,b,p=manifests();b['records'][0]['image_sha256']='changed'
        with self.assertRaisesRegex(ValueError,'UK'):experiment.validate_pair(a,b,p)

    def test_controlled_pair_rejects_reservation_or_promotion_changes(self):
        a,b,p=manifests();b['records'][2]['evaluation_only']=False
        with self.assertRaises(ValueError):experiment.validate_pair(a,b,p)
        a,b,p=manifests();p['automatic_promotion']=True
        with self.assertRaisesRegex(ValueError,'protocol'):experiment.validate_pair(a,b,p)

    def test_download_budget_and_known_endpoint_are_enforced(self):
        with patch.object(sources.requests,'get') as get:
            with self.assertRaisesRegex(ValueError,'endpoint'):sources.fetch('https://example.org',{},10)
            get.assert_not_called();response=get.return_value.__enter__.return_value;response.iter_content.return_value=[b'12345',b'678901'];response.url=sources.RGB
            with self.assertRaisesRegex(ValueError,'budget'):sources.fetch(sources.RGB,{},10)

    def test_real_coarsened_dataset_preserves_masks_and_uk_source_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'native';root.mkdir();records=[];rng=np.random.default_rng(3);atomic_json(root/'recipe.json',{'fixture':True})
            for i,(id,site,reserved) in enumerate([('old','uk',False),('efteling','efteling',False),('toverland','toverland',True)]):
                folder=root/id;folder.mkdir();Image.fromarray(rng.integers(0,256,(128,128,3),np.uint8)).save(folder/'rgb.png');g=np.zeros((128,128),np.uint8);c=np.zeros_like(g);r={'id':id,'site_id':site,'evaluation_only':reserved,'image_file':id+'/rgb.png','receipt_file':id+'/receipt.json'}
                atomic_json(folder/'receipt.json',{'image_sha256':file_hash(folder/'rgb.png'),'width':128,'height':128,'grid':{'spacing_m':.08},'layer':'2025_orthoHR'})
                for key,arr in [('ground',g),('canopy',c),('inferred',c),('dense_windows',c)]:Image.fromarray(arr).save(folder/(key+'.png'));r[key+'_file']=id+'/'+key+'.png'
                for key in ('image','receipt','ground','canopy','inferred','dense_windows'):r[key+'_sha256']=file_hash(root/r[key+'_file'])
                r['ground_counts']={k:int((g==v).sum()) for k,v in data.GROUND.items()};r['canopy_counts']={k:int((c==v).sum()) for k,v in data.CANOPY.items()};records.append(r)
            m={'version':data.VERSION,'records':records,'ground_labels':data.GROUND,'canopy_labels':data.CANOPY,'recipe_sha256':file_hash(root/'recipe.json'),'reserved_evaluation_site_ids':['toverland'],'independent_human_review':False,'production_eligible':False,'hidden_ground_used_as_observed_truth':False};m['id']=digest(m);atomic_json(root/'dataset.json',m)
            coarse=experiment.coarsen_dataset(root,Path(temp)/'coarse')
            for old,new in zip(m['records'],coarse['records']):
                for key in ('ground','canopy','inferred','dense_windows'):self.assertEqual(old[key+'_sha256'],new[key+'_sha256'])
            self.assertEqual(m['records'][0]['image_sha256'],coarse['records'][0]['image_sha256']);self.assertNotEqual(m['records'][1]['image_sha256'],coarse['records'][1]['image_sha256']);self.assertTrue(coarse['records'][2]['evaluation_only']);data.validate(Path(temp)/'coarse')


if __name__=='__main__':unittest.main()
