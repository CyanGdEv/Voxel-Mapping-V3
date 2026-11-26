import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import numpy as np
from PIL import Image
from affine import Affine
from rasterio.io import MemoryFile

from voxel_mapper.recover_paving_georef import load_reference_mosaic, recover
from voxel_mapper.view_registration import fit_correspondences, matched_georef, apply_review, resized_points
from voxel_mapper.train_ground_model import _read_samples


def png(values):
    stream = io.BytesIO()
    Image.fromarray(values).save(stream,format='PNG')
    return stream.getvalue()


class ViewRegistrationTests(unittest.TestCase):
    def test_reference_gaps_stay_unknown_and_conflicts_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            def raster(value,left):
                with MemoryFile() as mem:
                    with mem.open(driver='GTiff',width=2,height=2,count=3,dtype='uint8',
                                  crs='EPSG:27700',transform=Affine(1,0,left,0,-1,2)) as dst:
                        dst.write(np.full((3,2,2),value,np.uint8))
                    return mem.read()
            with zipfile.ZipFile(root/'ref.zip','w') as z:
                z.writestr('data/a/rgb.tif',raster(10,0))
                z.writestr('data/b/rgb.tif',raster(20,4))
            rgb,known,tf=load_reference_mosaic(root/'ref.zip')
            self.assertEqual(rgb.shape,(2,6,3))
            self.assertFalse(known[:,2:4].any())
            with zipfile.ZipFile(root/'ref.zip','a') as z:
                z.writestr('data/conflict/rgb.tif',raster(30,0))
            with self.assertRaisesRegex(ValueError,'Conflicting'):
                load_reference_mosaic(root/'ref.zip')

    def test_resize_coordinate_centres_and_rounded_dimensions(self):
        points = np.array([[0.,0.],[99.,49.]])
        actual = resized_points(points,(100,200),(50,100))
        np.testing.assert_array_equal(actual,[[.5,.5],[198.5,98.5]])
        np.testing.assert_allclose(resized_points(np.array([[0.,0.]]),(100,200),(200,400)),[[-.25,-.25]])
        # Raster corner coordinates commute with explicit integer resize dimensions.
        a = resized_points(np.array([[5.,7.]]),(1514,1069),(1024,723))
        np.testing.assert_allclose(a+.5,[[5.5*1069/723,7.5*1514/1024]])
    def test_pixel_centres_composed_before_corner_georeferencing(self):
        base = Affine(1,0,407000,0,-1,344000)
        matrix = np.array([[.05,-.01,20],[.01,.05,30]])
        result = matched_georef(base,matrix)
        for x,y in ((0,0),(10,20),(999,1300)):
            ref = matrix@np.array([x,y,1])
            np.testing.assert_allclose(result*(x+.5,y+.5),base*(ref[0]+.5,ref[1]+.5))

    @unittest.skipUnless(importlib.util.find_spec('cv2'),'install matching extra')
    def test_withheld_cells_detect_wrong_fit_and_duplicate_points(self):
        y,x = np.mgrid[4:93:11,4:93:11]
        query = np.column_stack((x.ravel(),y.ravel())).astype(float)
        target = query+[30,20]
        result = fit_correspondences(query,target,(96,96))
        self.assertEqual(result['status'],'geometric_candidate')
        cells = np.floor(query/[24,24]).astype(int)
        held = (cells[:,0]+cells[:,1])%3==0
        bad = target.copy();bad[held]+=20
        result = fit_correspondences(query,bad,(96,96))
        self.assertIn('withheld_checkpoint_error',result['reasons'])
        with self.assertRaises(ValueError):
            fit_correspondences(np.vstack([query,query[0]]),np.vstack([target,target[0]]),(96,96))

    @unittest.skipUnless(importlib.util.find_spec('cv2'),'install matching extra')
    def test_review_replay_byte_preservation_groups_and_registration_filter(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reference = np.random.default_rng(8).integers(0,255,(160,160,3),dtype=np.uint8)
            with MemoryFile() as mem:
                with mem.open(driver='GTiff',width=160,height=160,count=3,dtype='uint8',
                              crs='EPSG:27700',transform=Affine(1,0,0,0,-1,160)) as dst:
                    dst.write(reference.transpose(2,0,1))
                raw = mem.read()
            with zipfile.ZipFile(root/'reference.zip','w') as z:z.writestr('data/tile/rgb.tif',raw)
            mosaic,known,base = load_reference_mosaic(root/'reference.zip')
            np.testing.assert_array_equal(mosaic,reference)
            self.assertTrue(known.all())
            image = png(reference[20:116,30:126]);labels = png(np.ones((96,96),np.uint8))
            old_geo = {'crs':'EPSG:27700','transform':[1,0,30,0,-1,140]}
            manifest = {'park_id':'test','label_map':{'1':'grass'},'samples':[
                {'sample_id':'old','image':'old.png','labels':'old-mask.png','georef':old_geo,'split_group':'old'},
                {'sample_id':'view','image':'view.png','labels':'view-mask.png','split_group':'new'},
                {'sample_id':'unknown','image':'unknown.png','labels':'unknown-mask.png','split_group':'unknown'}]}
            with zipfile.ZipFile(root/'data.zip','w') as z:
                z.writestr('manifest.json',json.dumps(manifest))
                for row in manifest['samples']:z.writestr(row['image'],image);z.writestr(row['labels'],labels)
            y,x = np.mgrid[4:93:11,4:93:11];q=np.column_stack((x.ravel(),y.ravel())).astype(float)
            fit=fit_correspondences(q,q+[30,20],(96,96));fit.update(status='validated_relative_candidate',sample_id='view',
                image_shape=[96,96],image_sha256=hashlib.sha256(image).hexdigest(),labels_sha256=hashlib.sha256(labels).hexdigest())
            report={'dataset_sha256':hashlib.sha256((root/'data.zip').read_bytes()).hexdigest(),
                    'reference_archive_sha256':hashlib.sha256((root/'reference.zip').read_bytes()).hexdigest(),
                    'query_long_side':1024,'views':[fit]}
            repeat=copy.deepcopy(report);repeat['query_long_side']=512
            review={k:report[k] for k in ('dataset_sha256','reference_archive_sha256')}
            review.update(visual_alignment_reviewed=True,accepted_ids=['view'])
            summary=apply_review(root/'data.zip',root/'reference.zip',report,repeat,review,root/'out.zip')
            self.assertEqual(summary['registered_total'],2)
            self.assertEqual(summary['remaining_unregistered'],1)
            with zipfile.ZipFile(root/'out.zip') as z,zipfile.ZipFile(root/'data.zip') as source:
                self.assertIsNone(z.testzip())
                for name in source.namelist():
                    if name!='manifest.json':self.assertEqual(z.read(name),source.read(name))
                records=json.loads(z.read('manifest.json'))['samples']
                self.assertEqual(records[0]['georef'],old_geo)
                np.testing.assert_allclose(records[1]['georef']['transform'],old_geo['transform'],atol=1e-7)
                self.assertEqual(records[0]['split_group'],records[1]['split_group'])
                self.assertNotIn('georef',records[2])
            samples,_,stats=_read_samples(root/'out.zip')
            self.assertEqual(len(samples),2)
            self.assertEqual(stats['skipped_unregistered'],1)
            bad=copy.deepcopy(report);bad['views'][0]['matrix'][0][2]+=5
            with self.assertRaisesRegex(ValueError,'replay'):
                apply_review(root/'data.zip',root/'reference.zip',bad,repeat,review,root/'bad.zip')
            bad_repeat=copy.deepcopy(repeat);bad_repeat['views'][0]['matrix'][0][2]+=.1
            with self.assertRaisesRegex(ValueError,'replay'):
                apply_review(root/'data.zip',root/'reference.zip',report,bad_repeat,review,root/'bad-repeat.zip')
            from tools.prepare_registered_broad_chips import prepare
            # The grass-only fixture cannot provide both broad validation classes.
            with self.assertRaises(ValueError):
                prepare(root/'out.zip',root/'reference.zip',root/'broad.zip','view')
            self.assertFalse((root/'broad.zip').exists())
            self.assertFalse((root/'broad.zip.tmp').exists())
            with zipfile.ZipFile(root/'other-reference.zip','w') as z:
                z.writestr('data/tile/rgb.tif',raw);z.writestr('identity.txt',b'another source archive')
            with self.assertRaisesRegex(ValueError,'identities differ'):
                prepare(root/'out.zip',root/'other-reference.zip',root/'wrong-source.zip','view')
            # The shared mosaic reader also preserves exact paving recovery.
            with zipfile.ZipFile(root/'expansion.zip','w') as z:
                z.writestr('paving_detail/full_aerial_crop.png',image)
                z.writestr('paving_detail/samples.csv','sample_id,x_px,y_px,width_px,height_px,augmentation\npatch,0,0,96,96,r0\n')
            with zipfile.ZipFile(root/'patch.zip','w') as z:
                z.writestr('rgb.png',image);z.writestr('labels.png',labels)
                z.writestr('manifest.json',json.dumps({'samples':[{'sample_id':'patch','image':'rgb.png','labels':'labels.png','source_label_scheme':'mutiny_bay_paving_v1'}]}))
            recovered=recover(root/'patch.zip',root/'expansion.zip',root/'reference.zip',root/'exact.zip',west=30,north=140)
            self.assertEqual(recovered['verified'],1)
