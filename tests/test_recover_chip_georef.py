import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image
from voxel_mapper.recover_chip_georef import recover

try:
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin
except ImportError:
    rasterio=None

@unittest.skipIf(rasterio is None,"requires GIS raster dependencies")
class GeorefRecovery(unittest.TestCase):
    def test_exact_match_and_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            rgb=np.arange(3*8*8,dtype=np.uint8).reshape(3,8,8)
            with MemoryFile() as mem:
                with mem.open(driver="GTiff",width=8,height=8,count=3,dtype="uint8",crs="EPSG:32617",
                              transform=from_origin(100,200,0.5,0.5)) as dst:
                    dst.write(rgb)
                raster=mem.read()
            with zipfile.ZipFile(root/"source.zip","w") as z:
                z.writestr("naip_4band_georeferenced.tif",raster)
            with zipfile.ZipFile(root/"index.zip","w") as z:
                z.writestr("chip_index.csv","chip_id,pixel_x,pixel_y,width_px,height_px\na,2,3,2,2\nb,2,3,2,2\n")
            records=[]
            with zipfile.ZipFile(root/"base.zip","w") as z:
                for sid in ("a","b"):
                    image=rgb[:,3:5,2:4].transpose(1,2,0).copy()
                    if sid=="b": image[0,0,0]=0
                    labels=np.full((2,2),255,dtype=np.uint8)
                    labels[0,0]=9
                    for suffix,arr in (("rgb",image),("labels",labels)):
                        buf=io.BytesIO()
                        Image.fromarray(arr).save(buf,format="PNG")
                        z.writestr(f"{sid}_{suffix}.png",buf.getvalue())
                    records.append({"sample_id":sid,"image":f"{sid}_rgb.png","labels":f"{sid}_labels.png"})
                z.writestr("manifest.json",json.dumps({"samples":records}))
            report=recover(root/"base.zip",root/"index.zip",root/"source.zip",root/"out.zip")
            self.assertEqual(report["verified"],1)
            self.assertEqual(report["unmatched"],1)
            self.assertEqual(report["labelled_pixels_verified"],1)
            with zipfile.ZipFile(root/"out.zip") as z, zipfile.ZipFile(root/"base.zip") as original:
                a,b=json.loads(z.read("manifest.json"))["samples"]
                self.assertEqual(a["georef"]["transform"],[.5,0,101,0,-.5,198.5])
                self.assertNotIn("georef",b)
                self.assertEqual(z.read("a_labels.png"),original.read("a_labels.png"))
