import io
import json
import random
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np
from voxel_mapper.multisource_chips import CHANNELS, empty, decode, drop_groups, build_chip, pack

try:
    import rasterio
    from rasterio.transform import from_origin
    from PIL import Image
except ImportError:
    rasterio = None

class ContextTests(unittest.TestCase):
    def test_schema_and_dropout(self):
        a=empty(4,5)
        a[:,:,0:2]=1
        buf=io.BytesIO()
        np.savez_compressed(buf,context=a,channel_names=np.asarray(CHANNELS))
        np.testing.assert_array_equal(decode(buf.getvalue(),4,5),a)
        self.assertEqual(len(CHANNELS),25)
        self.assertFalse(np.any(drop_groups(a,random.Random(1),1)))
        self.assertTrue(np.all(a[:,:,0:2]==1))

    def test_unknown_mask_rejected(self):
        a=empty(2,2)
        a[:,:,0]=1
        buf=io.BytesIO()
        np.savez_compressed(buf,context=a,channel_names=np.asarray(CHANNELS))
        with self.assertRaisesRegex(ValueError,"validity"):
            decode(buf.getvalue(),2,2)

    @unittest.skipIf(rasterio is None,"install GIS and Pillow")
    def test_alignment_and_unchanged_labels(self):
        import hashlib
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            affine=from_origin(0,20,10,10)
            data=np.array([[[1,0],[255,1]],[[2,1],[255,11]]],dtype=np.uint8)
            np.savez_compressed(root/"gis.npz",channels=data)
            report={"schema":"voxel-gis-context-v1","path":"gis.npz",
                "sha256":hashlib.sha256((root/"gis.npz").read_bytes()).hexdigest(),
                "shape":list(data.shape),"crs":rasterio.crs.CRS.from_epsg(27700).to_wkt(),
                "transform":list(affine)[:6],"channels":[{"source_id":"os-openmap-buildings"},{"source_id":"sentinel2-landcover"}]}
            (root/"gis.json").write_text(json.dumps(report))
            for name,values in (("dtm",[[100,100],[-9999,100]]),("dsm",[[112,100],[110,99]]),("intensity",[[32767,0],[-9999,65535]])):
                with rasterio.open(root/(name+".tif"),"w",driver="GTiff",height=2,width=2,count=1,
                    dtype="float32",crs="EPSG:27700",transform=affine,nodata=-9999) as dst:
                    dst.write(np.asarray(values,dtype=np.float32),1)
            meta={"source_id":"lidar","license":"OGL-3.0","observed_date":"2024-01-01","vertical_units":"m","vertical_datum":"ODN"}
            catalog={"gis":"gis.json","dtm":{**meta,"path":"dtm.tif"},"dsm":{**meta,"path":"dsm.tif"},
                     "intensity":{**meta,"path":"intensity.tif","encoding":"raw_las_uint16"}}
            spec={"crs":"EPSG:27700","transform":list(affine)[:6]}
            a,p=build_chip(spec,2,2,catalog,root)
            np.testing.assert_array_equal(a[:,:,0],[[1,0],[0,1]])
            np.testing.assert_array_equal(a[:,:,1],[[1,1],[0,1]])
            np.testing.assert_array_equal(a[:,:,20],[[1,1],[0,1]])
            np.testing.assert_allclose(a[:,:,21],[[.2,0],[0,0]])
            np.testing.assert_array_equal(a[:,:,22],[[1,1],[0,0]])
            np.testing.assert_array_equal(a[:,:,24],[[1,1],[0,1]])
            with self.assertRaisesRegex(ValueError,"datums"):
                build_chip(spec,2,2,{**catalog,"dsm":{**catalog["dsm"],"vertical_datum":"other"}},root)
            image=io.BytesIO()
            Image.new("RGB",(2,2)).save(image,format="PNG")
            labels=io.BytesIO()
            Image.new("L",(2,2),255).save(labels,format="PNG")
            manifest={"park_id":"park","samples":[{"image":"rgb.png","labels":"mask.png","georef":spec}]}
            with zipfile.ZipFile(root/"base.zip","w") as z:
                z.writestr("manifest.json",json.dumps(manifest))
                z.writestr("rgb.png",image.getvalue())
                z.writestr("mask.png",labels.getvalue())
            (root/"catalog.json").write_text(json.dumps({"parks":{"park":catalog}}))
            counts=pack(root/"base.zip",root/"catalog.json",root/"packed.zip")
            self.assertEqual(counts["aligned"],1)
            with zipfile.ZipFile(root/"packed.zip") as z:
                self.assertEqual(z.read("mask.png"),labels.getvalue())
                m=json.loads(z.read("manifest.json"))
                chip=decode(z.read(m["samples"][0]["context"]),2,2)
                np.testing.assert_array_equal(chip,a)

    @unittest.skipIf(rasterio is None,"install GIS and Pillow")
    def test_synchronized_training_augmentation(self):
        from voxel_mapper.train_ground_model import _tile
        rgb=np.zeros((3,4,3),dtype=np.uint8)
        labels=np.arange(12,dtype=np.uint8).reshape(3,4)
        rgb[:,:,0]=labels
        context=empty(3,4)
        context[:,:,0]=labels
        random.seed(42)
        x,y,c=_tile(rgb,labels,8,True,context)
        valid=y!=255
        np.testing.assert_array_equal(x[:,:,0][valid],y[valid])
        np.testing.assert_array_equal(c[:,:,0][valid],y[valid])
        self.assertTrue(np.all(c[~valid]==0))

if __name__=="__main__":
    unittest.main()
