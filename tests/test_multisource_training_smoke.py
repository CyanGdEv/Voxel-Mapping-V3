import argparse
import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image
from voxel_mapper.multisource_chips import CHANNELS, empty
from voxel_mapper.train_ground_model import train
from voxel_mapper.benchmark_multisource import compare

@unittest.skipUnless(importlib.util.find_spec("torch"),"optional CPU training smoke test requires torch")
class TrainingSmoke(unittest.TestCase):
    def test_paired_training(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            dataset=root/"synthetic.zip"
            records=[]
            with zipfile.ZipFile(dataset,"w") as z:
                for i in range(4):
                    labels=np.ones((64,64),dtype=np.uint8)
                    labels[:,32:]=6
                    rgb=np.zeros((64,64,3),dtype=np.uint8)
                    rgb[labels==1]=[20,140,20]
                    rgb[labels==6]=[140,140,140]
                    context=empty(64,64)
                    context[:,:,0]=(labels==6)
                    context[:,:,1]=1
                    for name,arr in ((f"rgb{i}.png",rgb),(f"labels{i}.png",labels)):
                        blob=io.BytesIO()
                        Image.fromarray(arr).save(blob,format="PNG")
                        z.writestr(name,blob.getvalue())
                    blob=io.BytesIO()
                    np.savez_compressed(blob,context=context,channel_names=np.asarray(CHANNELS))
                    z.writestr(f"ctx{i}.npz",blob.getvalue())
                    records.append({"sample_id":str(i),"split_group":f"zone{i}","image":f"rgb{i}.png",
                        "labels":f"labels{i}.png","context":f"ctx{i}.npz",
                        "georef":{"crs":"EPSG:27700","transform":[1,0,i*100,0,-1,64]},
                        "context_provenance":[{"source_id":"synthetic-test-only"}]})
                z.writestr("manifest.json",json.dumps({"park_id":"synthetic","label_map":{"1":"grass","6":"stone"},
                    "context_schema":"voxel-multisource-v1","context_channels":CHANNELS,"samples":records}))
            args=argparse.Namespace(dataset=[dataset],output=root/"rgb",holdout_park=None,
                 validation_fraction=.5,num_classes=10,epochs=1,batch_size=2,patch_size=64,
                 learning_rate=.001,seed=41,threads=1,cpu=True,multisource=False,context_dropout=.2)
            rgb=train(args)
            args.output=root/"multi"
            args.multisource=True
            multi=train(args)
            report=compare(rgb,multi)
            self.assertEqual(len(multi["input_names"]),28)
            self.assertEqual(len(rgb["input_names"]),3)
            self.assertTrue((root/"multi"/"model.pt").is_file())
            self.assertIn("delta_mean_iou",report)
            self.assertEqual(rgb["validation_ids"],multi["validation_ids"])
