"""Paired RGB versus multisource validation on identical reviewed datasets."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .train_ground_model import train

def compare(rgb, multi):
    for key in ("train_ids","validation_ids","class_map","seed","split"):
        if rgb[key]!=multi[key]:
            raise ValueError("Benchmark mismatch: "+key)
    if [s["dataset_sha256"] for s in rgb["sources"]]!=[s["dataset_sha256"] for s in multi["sources"]]:
        raise ValueError("Benchmark dataset mismatch")
    for key in ("epochs","batch_size","patch_size","learning_rate"):
        if rgb["training"][key]!=multi["training"][key]:
            raise ValueError("Benchmark hyperparameter mismatch: "+key)
    if rgb["mode"]!="rgb" or multi["mode"]!="multisource":
        raise ValueError("Expected RGB and multisource runs")
    if rgb["status"]!="trained" or multi["status"]!="trained":
        raise ValueError("Both models must have reviewed validation results")
    per_class={}
    for key,a in rgb["per_class"].items():
        b=multi["per_class"][key]
        if a["labelled_pixels"]!=b["labelled_pixels"]:
            raise ValueError("Validation pixel counts differ")
        per_class[key]={"name":a["name"],"labelled_pixels":a["labelled_pixels"],
            "rgb_iou":a["iou"],"multisource_iou":b["iou"],
            "delta_iou":b["iou"]-a["iou"] if a["iou"] is not None and b["iou"] is not None else None}
    a=rgb["training"]["best_validation_mean_iou"]
    b=multi["training"]["best_validation_mean_iou"]
    return {"schema":"voxel-multisource-benchmark-v1","split":rgb["split"],"seed":rgb["seed"],
            "rgb_mean_iou":a,"multisource_mean_iou":b,"delta_mean_iou":b-a,
            "per_class":per_class,
            "policy":"Validation-selected checkpoints; not independent test accuracy. One seed is not statistical evidence of generalization. No automatic deployment."}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset",type=Path,action="append",required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--holdout-park")
    p.add_argument("--validation-group", action="append", help="Fixed held-out source/area group; must be geographically independent")
    p.add_argument("--require-georeference", action="store_true")
    p.add_argument("--validation-fraction",type=float,default=.2)
    p.add_argument("--num-classes",type=int,default=10)
    p.add_argument("--epochs",type=int,default=20)
    p.add_argument("--batch-size",type=int,default=2)
    p.add_argument("--patch-size",type=int,default=256)
    p.add_argument("--learning-rate",type=float,default=.001)
    p.add_argument("--seed",type=int,default=41)
    p.add_argument("--threads",type=int,default=2)
    p.add_argument("--context-dropout",type=float,default=.2)
    p.add_argument("--context-group",action="append",help="Retain selected contextual groups for ablation")
    p.add_argument("--cpu",action="store_true")
    args=p.parse_args()
    if not 0<args.validation_fraction<1 or args.patch_size<64 or args.patch_size%16 or min(args.epochs,args.batch_size,args.threads)<1:
        p.error("Invalid training parameters")
    root=args.output
    if (root/"rgb"/"model.pt").exists() or (root/"multisource"/"model.pt").exists():
        p.error("Use a fresh benchmark output directory")
    args.output=root/"rgb"
    args.multisource=False
    rgb=train(args)
    args.output=root/"multisource"
    args.multisource=True
    multi=train(args)
    result=compare(rgb,multi)
    (root/"benchmark.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
if __name__=="__main__":
    main()
