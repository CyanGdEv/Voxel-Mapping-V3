import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from rasterio.transform import from_origin

from voxel_mapper.surface_dataset_expansion import literal_masks,training_records
from voxel_mapper.survey_mosaic import place,select_tiles
from voxel_mapper.survey import BASE


class ExpansionTests(unittest.TestCase):
    def test_conflicts_canopy_and_sparse_edges_stay_unknown(self):
        def region(label,x):return {'id':label,'label':label,'outer':[[x,4],[x+20,4],[x+20,30],[x,30]]}
        ann={'ground_regions':[region('paving',4),region('grass_island',16)],'canopy':[{'id':'crown','outer':[[7,9],[13,9],[13,15],[7,15]]}]}
        g,c,_=literal_masks(ann,(48,40))
        self.assertEqual(g[20,10],0);self.assertEqual(g[20,20],255);self.assertEqual(g[20,30],2)
        self.assertEqual(g[4,10],255);self.assertEqual(g[12,10],255);self.assertEqual(c[12,10],1)

    def test_whole_park_reservation_and_excluded_park(self):
        records=[{'id':str(i),'site_id':s,'evaluation_only':s=='reserved'} for i,s in enumerate(['old','new','reserved','reserved'])]
        manifest={'records':records,'reserved_evaluation_site_ids':['reserved']}
        self.assertEqual([r['id'] for r in training_records(manifest)],['0','1'])
        self.assertEqual([r['id'] for r in training_records(manifest,['old'])],['1'])
        # A mislabeled flag must not override the manifest's whole-park guard.
        records[2]['evaluation_only']=False
        self.assertEqual([r['id'] for r in training_records(manifest)],['0','1'])

    def test_fit_and_save_reject_reserved_before_training_or_writing(self):
        from voxel_mapper import layered_surface_learning as net
        row={'record':{'evaluation_only':True}}
        with self.assertRaisesRegex(ValueError,'Reserved'):net.fit([row])
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'must-not-exist'
            with self.assertRaisesRegex(ValueError,'Reserved'):net.save(None,[row],{},folder,{})
            self.assertFalse(folder.exists())

    def test_class_weights_never_consume_reserved_targets(self):
        from voxel_mapper.layered_surface_learning import class_weights
        m={'records':[{'id':'fit','site_id':'train'},{'id':'test','site_id':'held','evaluation_only':True}],'reserved_evaluation_site_ids':['held']}
        masks={'fit':np.zeros((4,4),np.uint8),'test':np.full((4,4),3,np.uint8)}
        def counts():return class_weights([{'ground':masks[r['id']]} for r in training_records(m)],'ground',4)[1]
        before=counts();masks['test'][:]=2;np.testing.assert_array_equal(before,counts());self.assertEqual(before.tolist(),[16,0,0,0])

    def test_protocol_rejects_selection_before_output_or_fit(self):
        from unittest.mock import patch
        from voxel_mapper import surface_transfer_experiment as experiment,layered_surface_learning as net
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);protocol=root/'protocol.json';protocol.write_text(json.dumps({'version':'surface-expansion-protocol-v1','settings':{**net.SETTINGS,'lidar_dropout':.15},'parent_dataset_id':'parent','reserved_site':'reserved','automatic_promotion':False,'selection_on_reserved_scores':True}))
            with patch.object(experiment.data,'validate',return_value={'parent_dataset_id':'parent','reserved_evaluation_site_ids':['reserved']}),patch.object(experiment.net,'fit') as fit:
                with self.assertRaisesRegex(ValueError,'protocol'):experiment.run(root,root,root,protocol,root,root,root/'out')
                fit.assert_not_called();self.assertFalse((root/'out').exists())

    def test_source_feature_cache_rejects_changed_hash_or_encoder(self):
        from PIL import Image
        from voxel_mapper.surface_transfer_experiment import load_rows
        from voxel_mapper import aerial_surface_encoder as aerial
        from voxel_mapper.generation_cycles import file_hash
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);Image.fromarray(np.zeros((96,96,3),np.uint8)).save(root/'rgb.png');Image.fromarray(np.zeros((96,96),np.uint8)).save(root/'mask.png')
            r={'id':'source','image_file':'rgb.png','ground_file':'mask.png','canopy_file':'mask.png','image_sha256':file_hash(root/'rgb.png')}
            features=np.zeros((96,96,16),np.float32);np.savez_compressed(root/'source.npz',features=features)
            receipt={'features_sha256':file_hash(root/'source.npz'),'encoder_sha256':'wrong','source_sha256':r['image_sha256']};(root/'source.json').write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError,'encoder'):load_rows(root,root,root,{'records':[r]})
            receipt['encoder_sha256']=aerial.WEIGHTS;receipt['features_sha256']='changed';(root/'source.json').write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError,'hash'):load_rows(root,root,root,{'records':[r]})


class NativeMosaicTests(unittest.TestCase):
    def test_latest_common_matched_year_not_newest_single_tile(self):
        entries=[]
        for tile,years in [('SE7575',['2021']),('SE7580',['2021','2022'])]:
            for year in years:
                for kind in ('dtm','dsm'):
                    product='national_lidar_programme_'+kind
                    entries.append({'tile':{'id':tile},'year':{'id':year},'resolution':{'id':'1'},'product':{'id':product},'uri':f'{BASE}/{product}/{year}/1/{tile}'})
        selected=select_tiles({'count':len(entries),'results':entries});self.assertEqual([r[1] for r in selected],['2021','2021'])
        with self.assertRaisesRegex(ValueError,'common year'):select_tiles({'count':len(entries)-1,'results':entries[1:]})

    def test_native_copy_preserves_gaps_and_rejects_overlap_or_shift(self):
        a=np.full((4,5),np.nan,np.float32);tf=from_origin(0,4,1,1);src=np.array([[3,np.nan],[5,6]],np.float32)
        place(a,tf,src,from_origin(1,3,1,1));self.assertEqual(a[1,1],3);self.assertTrue(np.isnan(a[1,2]));self.assertTrue(np.isnan(a[0,0]))
        with self.assertRaisesRegex(ValueError,'disagree'):place(a,tf,np.full((2,2),9),from_origin(1,3,1,1))
        with self.assertRaisesRegex(ValueError,'origins'):place(a,tf,src,from_origin(1.2,3,1,1))
        with self.assertRaisesRegex(ValueError,'one-metre'):place(a,tf,src,from_origin(1,3,2,2))


if __name__=='__main__':unittest.main()
