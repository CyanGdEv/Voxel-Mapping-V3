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
from voxel_mapper.train_ground_model import Sample, _split
from voxel_mapper.benchmark_multisource import compare


class ExplicitHoldout(unittest.TestCase):
    def test_fixed_group_across_seeds_and_invalid_selection(self):
        rows = [Sample(str(i), "park", group, None, None)
                for i, group in enumerate(("west", "west", "east"))]
        for seed in (41, 42, 43):
            train_rows, valid_rows, report = _split(rows, .2, seed, None, ["east"])
            self.assertEqual([s.sample_id for s in train_rows], ["0", "1"])
            self.assertEqual([s.sample_id for s in valid_rows], ["2"])
            self.assertEqual(report["mode"], "explicit_group")
        for groups in (["absent"], ["west", "east"]):
            with self.assertRaises(ValueError):
                _split(rows, .2, 41, None, groups)
        with self.assertRaises(ValueError):
            _split(rows, .2, 41, "park", ["east"])

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
                    context[:,:,21]=.01*(i+1)
                    context[:,:,22]=1
                    context[:,:,23]=.001*(i+1)
                    context[:,:,24]=1
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
            args.output=root/"zero-control"
            args.context_baseline=True
            control=train(args)
            self.assertEqual(control["context_groups"],[])
            self.assertEqual(len(control["input_names"]),28)
            args.context_baseline=False
            args.context_normalization="train_p95"
            args.output=root/"normalized"
            multi=train(args)
            self.assertEqual(multi["context_scaling"]["method"],"training_positive_p95_v1")
            train_values=np.concatenate([np.full(64*64,.01*(int(row[2])+1),np.float32) for row in multi["train_ids"]])
            self.assertAlmostEqual(multi["context_scaling"]["channels"]["height"]["cap"],
                                   float(np.percentile(train_values,95)),places=6)
            args.rgb_checkpoint=root/"rgb"/"model.pt"
            args.output=root/"residual"
            multi=train(args)
            self.assertEqual(multi["architecture"],"rgb_residual_v1")
            self.assertGreaterEqual(multi["training"]["best_validation_mean_iou"],multi["epoch_zero_mean_iou"])
            if importlib.util.find_spec("rasterio"):
                import rasterio
                from voxel_mapper.predict_ground_model import predict
                from voxel_mapper.train_ground_model import _decode_labels
                result = predict(root/"residual"/"model.pt", dataset, root/"predictions", threads=1)
                self.assertFalse(result["accepted_for_world"])
                validation = {row[2] for row in multi["validation_ids"]}
                matrix = np.zeros((10,10), dtype=np.int64)
                with zipfile.ZipFile(dataset) as z:
                    for i, row in enumerate(result["samples"]):
                        with rasterio.open(root/"predictions"/row["files"]["classes"]["path"]) as src:
                            self.assertEqual(src.crs.to_epsg(), 27700)
                            self.assertEqual(src.transform.c, i*100)
                            pred = src.read(1)
                        if str(i) in validation:
                            target = _decode_labels(z.read(f"labels{i}.png"))
                            matrix += np.bincount((target.astype(int)*10+pred).ravel(), minlength=100).reshape(10,10)
                np.testing.assert_array_equal(matrix, multi["validation_confusion_matrix"])
