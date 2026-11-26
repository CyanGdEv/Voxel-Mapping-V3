"""Run an existing ground checkpoint on georeferenced chips, without world writes."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile

import numpy as np

from .multisource_chips import CHANNELS, decode, empty, _grid, select_groups, scale_continuous
from .train_ground_model import build_model, _decode_rgb


def predict(checkpoint, dataset, output, *, patch_size=64, threads=2):
    import torch
    import rasterio
    if patch_size < 64 or patch_size % 16 or threads < 1:
        raise ValueError("Invalid inference patch size or thread count")
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(threads)
    saved = torch.load(checkpoint, map_location="cpu", weights_only=True)
    names = ("red", "green", "blue") + (CHANNELS if saved["input_channels"] == 28 else ())
    if tuple(saved["input_names"]) != names:
        raise ValueError("Checkpoint input schema mismatch")
    model = build_model(len(names), saved["num_classes"], architecture=saved.get("architecture","unet"),
                        residual_bound=saved.get("residual_bound",1.))
    model.load_state_dict(saved["state_dict"])
    model.eval()
    rows = []
    with zipfile.ZipFile(dataset) as source, torch.no_grad():
        manifest = json.loads(source.read("manifest.json"))
        for i, record in enumerate(manifest["samples"]):
            if not record.get("georef"):
                rows.append({"sample_id":record["sample_id"], "status":"missing_georeference"})
                continue
            rgb = _decode_rgb(source.read(record["image"]))
            h, w = rgb.shape[:2]
            crs, affine = _grid(record["georef"], h, w)
            context = None
            if len(names) == 28:
                if manifest.get("context_schema") != "voxel-multisource-v1" or tuple(manifest.get("context_channels", [])) != CHANNELS:
                    raise ValueError("Dataset context schema mismatch")
                context = decode(source.read(record["context"]), h, w) if record.get("context") else empty(h, w)
                if "context_groups" in saved:
                    context = select_groups(context, saved["context_groups"])
                context = scale_continuous(context, saved.get("context_scaling"))
            labels = np.empty((h, w), np.uint8)
            confidence = np.empty((h, w), np.float32)
            for y in range(0, h, patch_size):
                for x in range(0, w, patch_size):
                    ph, pw = min(patch_size, h-y), min(patch_size, w-x)
                    values = rgb[y:y+ph, x:x+pw].astype(np.float32)/255
                    values = np.pad(values, ((0,patch_size-ph),(0,patch_size-pw),(0,0)), mode="edge")
                    if context is not None:
                        c = np.pad(context[y:y+ph, x:x+pw], ((0,patch_size-ph),(0,patch_size-pw),(0,0)))
                        values = np.concatenate((values, c), axis=2)
                    batch = torch.from_numpy(values.copy()).permute(2,0,1)[None]
                    probs = model(batch).softmax(1)[0,:,:ph,:pw]
                    conf, pred = probs.max(0)
                    labels[y:y+ph, x:x+pw] = pred.numpy()
                    confidence[y:y+ph, x:x+pw] = conf.numpy()
            files = {}
            for role, data, nodata in (("classes", labels, 255), ("uncalibrated_confidence", confidence, -1)):
                path = output/f"{i}-{role}.tif"
                with rasterio.open(path, "w", driver="GTiff", width=w, height=h, count=1,
                                   dtype=str(data.dtype), crs=crs, transform=affine, nodata=nodata,
                                   compress="deflate") as dest:
                    dest.write(data, 1)
                files[role] = {"path":path.name, "sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
            rows.append({"sample_id":record["sample_id"], "status":"candidate_only", "files":files,
                         "context_provenance":record.get("context_provenance", [])})
    report = {"schema":"voxel-ground-prediction-v1", "checkpoint_sha256":hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
              "dataset_sha256":hashlib.sha256(dataset.read_bytes()).hexdigest(), "class_map":saved["class_map"],
              "input_channels":len(names), "architecture":saved.get("architecture","unet"),
              "context_scaling":saved.get("context_scaling"), "patch_size":patch_size, "samples":rows,
              "accepted_for_world":False, "world_blocks_changed":0,
              "policy":"Model candidates only. Softmax confidence is uncalibrated. World placement requires accepted evidence, verified world registration, ground elevation and conflict checks."}
    (output/"predictions.json").write_text(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("checkpoint", "dataset", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--patch-size", type=int, default=64)
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    report = predict(args.checkpoint, args.dataset, args.output, patch_size=args.patch_size, threads=args.threads)
    print(json.dumps({"samples":len(report["samples"]), "accepted_for_world":False}))


if __name__ == "__main__":
    main()
