import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np

from voxel_mapper import connected_surfaces as surfaces


def rectangle(label,x0,y0,x1,y1):
    return {'id':label,'label':label,'outer':[[x0,y0],[x1,y0],[x1,y1],[x0,y1]],'reason':'Synthetic test','origin':'synthetic'}


class ConnectedSurfaceTests(unittest.TestCase):
    def test_purple_roof_markers_are_opt_in_and_phone_ui_is_excluded(self):
        from voxel_mapper.user_path_supervision import extract
        rgb=np.zeros((80,100,3),np.uint8)
        for x in (10,17,24):rgb[20:22,x:x+2]=[160,20,180]
        for x in (50,57,64):rgb[50:52,x:x+2]=[200,20,20]
        points,_=extract(rgb,fine_markers=True,building_markers=True,exclusion_boxes=[[48,48,68,54]])
        self.assertEqual(len(points),3);self.assertEqual({p['label'] for p in points},{'building_boundary'})
        default,_=extract(rgb,fine_markers=True)
        self.assertNotIn('building_boundary',{p['label'] for p in default})
        with self.assertRaises(ValueError):extract(rgb,exclusion_boxes=[[0,0,101,80]])

    def test_site_holdout_excludes_both_alton_images(self):
        from voxel_mapper.surface_segmentation import fitting_rows
        rows=[{'record':{'id':str(i),'site_id':site}} for i,site in enumerate(['alton','alton','chessington'])]
        self.assertEqual(fitting_rows(rows,rows[0]),[rows[2]])
        self.assertEqual(fitting_rows(rows,rows[2]),rows[:2])
        self.assertEqual(fitting_rows(rows[:2],rows[0]),[rows[1]])

    def test_parallel_edges_remain_separate_and_large_gaps_stay_open(self):
        points=[{'id':str(i),'label':'path_boundary','reference_xy':p} for i,p in enumerate([[x,y] for y in (10,14) for x in range(0,61,6)])]
        graph=surfaces.connect(points)
        for edge in graph['edges']:
            self.assertEqual(edge['reference_xy'][0][1],edge['reference_xy'][1][1])
        self.assertFalse(graph['closed_chain_is_paving_automatically'])
        broken=[p for p in points if p['reference_xy'][0]<15 or p['reference_xy'][0]>45]
        for edge in surfaces.connect(broken)['edges']:self.assertLessEqual(edge['gap_pixels'],12)

    def test_holes_conflicts_caps_and_under_canopy_stay_out_of_observed_truth(self):
        walk=rectangle('paving',3,3,55,35);walk['holes']=[[[12,12],[20,12],[20,20],[12,20]]]
        building=rectangle('building_structure',30,5,38,15)
        corridor={'id':'open','label':'paving','line':[[5,45],[50,45]],'half_width':3,'reason':'Synthetic','origin':'synthetic'}
        points=[{'label':'tree_location','reference_xy':[45,20]}]
        target,inferred,stats,_=surfaces.masks([walk,building,corridor],(64,64),(64,64),[[1,0,0],[0,1,0]],points)
        self.assertEqual(target[16,16],255);self.assertEqual(target[10,34],255)
        self.assertEqual(target[20,45],255);self.assertTrue(inferred[20,45])
        self.assertEqual(target[45,5],255);self.assertEqual(target[45,25],0)
        self.assertGreater(stats['conflict_pixels'],0)
        self.assertEqual(target[4,4],0)

    def test_invalid_geometry_and_transform_rejected(self):
        bad=rectangle('water',0,0,30,30);bad['outer'][0][0]=float('nan')
        with self.assertRaises(ValueError):surfaces.geometry(bad,(64,64))
        with self.assertRaises(ValueError):surfaces.masks([], (64,64),(64,64),[[1,0]],[])


@unittest.skipUnless(importlib.util.find_spec('torch'),'Optional CPU segmentation dependency not installed')
class SpatialNetworkTests(unittest.TestCase):
    def test_training_accepts_missing_classes_without_inventing_water_or_grass(self):
        from voxel_mapper.surface_segmentation import fit
        target=np.full((96,96),255,np.uint8);target[10:40,10:80]=0;target[50:80,10:80]=1
        _,report=fit([{'rgb':np.full((96,96,3),120,np.uint8),'target':target}], 'pixel',
            {'seed':137,'steps':2,'batch':2,'patch':64,'learning_rate':.002,'threads':2})
        self.assertGreater(report['parameter_change_l2'],0)
        with self.assertRaises(ValueError):fit([{'rgb':np.zeros((96,96,3),np.uint8),'target':np.full((96,96),255,np.uint8)}],'pixel')

    def test_spatial_context_changes_neighbour_output_while_pixel_control_does_not(self):
        import torch
        from voxel_mapper.surface_segmentation import architecture
        torch.manual_seed(137);x=torch.rand(1,3,32,32);changed=x.clone();changed[:,:,14:17,14:17]=1
        for kind in ('pixel','spatial'):
            model=architecture(kind).eval()
            with torch.no_grad():a=model(x);b=model(changed)
            difference=(a[:,:,18:20,14:17]-b[:,:,18:20,14:17]).abs().max().item()
            self.assertEqual(difference==0,kind=='pixel')

    def test_saved_weights_roundtrip_and_tamper_rejection_without_pickle(self):
        import torch
        from voxel_mapper.surface_segmentation import architecture,save,load,predict
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'checkpoint';torch.manual_seed(3);model=architecture('spatial').eval()
            rows=[{'record':{'id':'source','image_sha256':'a'*64}}]
            save(model,'spatial',rows,{'id':'b'*64},root,{})
            loaded,metadata=load(root);rgb=np.full((96,96,3),140,np.uint8)
            np.testing.assert_array_equal(predict(model,rgb),predict(loaded,rgb))
            (root/'weights.npz').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'weights'):load(root)

    def test_oversized_tensor_header_is_rejected_before_array_allocation(self):
        import io,json,zipfile
        from voxel_mapper.surface_segmentation import architecture,save,load
        from voxel_mapper.generation_cycles import file_hash
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'checkpoint';model=architecture('spatial')
            save(model,'spatial',[{'record':{'id':'source','image_sha256':'a'*64}}],{'id':'b'*64},root,{})
            p=root/'weights.npz'
            with zipfile.ZipFile(p) as z:entries={n:z.read(n) for n in z.namelist()}
            header=io.BytesIO();np.lib.format.write_array_header_1_0(header,{'descr':'<f4','fortran_order':False,'shape':(1000000000,)})
            entries[next(iter(entries))]=header.getvalue()
            with zipfile.ZipFile(p,'w') as z:
                for n,data in entries.items():z.writestr(n,data)
            metadata=json.loads((root/'model.json').read_text());metadata['weights_sha256']=file_hash(p)
            (root/'model.json').write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError,'headers'):load(root)

    def test_training_ignores_unknown_and_changes_real_spatial_parameters(self):
        from voxel_mapper.surface_segmentation import fit
        rgb=np.zeros((96,96,3),np.uint8);target=np.full((96,96),255,np.uint8)
        for i in range(4):rgb[i*24:(i+1)*24]=[i*60,100,150];target[i*24+3:(i+1)*24-3,4:90]=i
        settings={'seed':137,'steps':2,'batch':2,'patch':64,'learning_rate':.002,'threads':2}
        _,report=fit([{'rgb':rgb,'target':target}],'spatial',settings)
        self.assertGreater(report['parameter_change_l2'],0);self.assertEqual(len(report['loss_history']),2)


if __name__=='__main__':unittest.main()
