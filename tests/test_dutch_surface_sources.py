import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest

import numpy as np
import rasterio
from rasterio.transform import from_origin

from voxel_mapper import dutch_surface_sources as dutch,lidar_surface_features as lidar
from voxel_mapper.generation_cycles import atomic_json,file_hash


class DutchSourcesTests(unittest.TestCase):
    def test_capabilities_require_fixed_definitive_layer_and_ahn_generation(self):
        rgb=b'<WMS><Name>2025_orthoHR</Name></WMS>';self.assertTrue(dutch.check_capabilities(rgb,'rgb'))
        with self.assertRaises(ValueError):dutch.check_capabilities(b'<WMS><Name>Actueel_orthoHR</Name></WMS>','rgb')
        ahn=b'<WCS><Abstract>Het huidige AHN is versie 4.</Abstract><CoverageId>dsm_05m</CoverageId><CoverageId>dtm_05m</CoverageId></WCS>';self.assertTrue(dutch.check_capabilities(ahn,'ahn'))
        with self.assertRaises(ValueError):dutch.check_capabilities(ahn.replace(b'versie 4',b'versie 6'),'ahn')

    def test_grid_budget_rejects_degree_coordinates_or_oversize_export(self):
        self.assertAlmostEqual(dutch.check_grid([120000,400000,120081.92,400081.92],(1024,1024)),.08)
        with self.assertRaises(ValueError):dutch.check_grid([5.1,51.1,5.2,51.2],(1024,1024))
        with self.assertRaises(ValueError):dutch.check_grid([120000,400000,120200,400200],(2500,2500))

    def test_half_metre_features_keep_physical_slope_and_preserve_gaps(self):
        y,x=np.indices((40,40));dtm=(x*.5*2+y*.5*3).astype(np.float32);dsm=dtm+6;valid=np.ones_like(dtm,bool)
        f=lidar.native_features(dtm,dsm,valid,valid,.5);self.assertAlmostEqual(float(f[20,20,0]),.2,places=6);self.assertAlmostEqual(float(f[20,20,1]),float(np.arctan(np.hypot(2,3))/(np.pi/2)),places=6);self.assertEqual(f[20,20,3],1)
        valid[20,20]=False;g=lidar.native_features(dtm,dsm,valid,valid,.5);self.assertFalse(g[17:24,17:24,3].any());self.assertTrue(np.isfinite(g).all());self.assertEqual(g[14,14,3],1)
        with self.assertRaises(ValueError):lidar.native_features(dtm,dsm,valid,valid,.08)

    def test_coarsening_removes_detail_without_changing_grid_or_input(self):
        y,x=np.indices((128,128));rgb=np.repeat((((x+y)%2)*255).astype(np.uint8)[:,:,None],3,2);before=rgb.copy();coarse,meta=dutch.coarse_rgb(rgb)
        self.assertEqual(coarse.shape,rgb.shape);self.assertLess(coarse.std(),rgb.std()/10);np.testing.assert_array_equal(rgb,before);self.assertFalse(meta['adds_optical_information']);self.assertTrue(meta['labels_and_geographic_extent_unchanged'])

    def test_native_alignment_and_source_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);tf=from_origin(120000,400016,.5,.5);shape=(32,32);dtm=np.full(shape,3,np.float32);dsm=np.full(shape,9,np.float32);dtm[14:16,14:16]=-9999;products={}
            for key,values in [('dtm',dtm),('dsm',dsm)]:
                p=root/(key+'.tif')
                with rasterio.open(p,'w',driver='GTiff',height=32,width=32,count=1,dtype='float32',crs='EPSG:28992',transform=tf,nodata=-9999) as ds:ds.write(values,1)
                products[key]={'file':p.name,'sha256':file_hash(p)}
            atomic_json(root/'height-receipt.json',{'version':'ahn4-native-pair-v1','generation':'AHN4','native_resolution_m':.5,'vertical_datum':'NAP','products':products})
            receipt={'width':128,'height':128,'image_sha256':'image','grid':{'crs':'EPSG:28992','bounds':[120003,400003,120013.24,400013.24]}}
            meta=dutch.align(receipt,root,root/'features.npz');self.assertTrue(dutch.validate_context_receipt(meta));f=np.load(root/'features.npz')['features'];self.assertEqual(f.shape,(128,128,4));self.assertLess(meta['valid_fraction'],1);self.assertAlmostEqual(float(f[0,0,0]),.2,places=6)
            bad={**meta,'vertical_datum':'ODN'}
            with self.assertRaisesRegex(ValueError,'NAP'):dutch.validate_context_receipt(bad)
            (root/'dtm.tif').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed'):dutch.align(receipt,root,root/'other.npz')

    def test_cli_rejects_non_dutch_extent_before_network_or_output(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'not-dutch';result=subprocess.run([sys.executable,'-m','voxel_mapper.dutch_surface_sources','--longitude','-1.89','--latitude','52.99','--output',str(out)],capture_output=True,text=True,timeout=20)
            self.assertNotEqual(result.returncode,0);self.assertIn('Dutch RD extent',result.stderr);self.assertFalse(out.exists());self.assertFalse((out.parent/(out.name+'-capabilities')).exists())


if __name__=='__main__':unittest.main()
