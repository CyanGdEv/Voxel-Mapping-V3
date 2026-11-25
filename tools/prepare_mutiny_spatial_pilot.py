"""Verify archived Mutiny pixels and build a buffered, single-crop pilot split."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image


def prepare(training, pilot, output):
    with zipfile.ZipFile(pilot) as source:
        coverage = json.loads(source.read("coverage.json"))
        with np.load(io.BytesIO(source.read("offline-context.npz")), allow_pickle=False) as data:
            rgb, labels = data["rgb"], data["labels"]
    digest = hashlib.sha256(training.read_bytes()).hexdigest()
    if digest != coverage["source_sha256"]["Alton_Towers_Georeferenced_Ground_Training.zip"]:
        raise ValueError("Training archive differs from verified pilot source")
    h, w = labels.shape
    west, north = coverage["origin_bng"]
    reconstructed = np.full_like(labels, 255)
    windows = 0
    with zipfile.ZipFile(training) as source:
        manifest = json.loads(source.read("manifest.json"))
        for record in manifest["samples"]:
            provenance = record.get("georef_provenance", {})
            if provenance.get("rotation_ccw_degrees") != 0:
                continue
            x, y, sw, sh = provenance["source_pixel_window"]
            if record["georef"] != {"crs":"EPSG:27700", "transform":[1,0,west+x,0,-1,north-y]}:
                raise ValueError("Source chip georeference differs")
            image = np.asarray(Image.open(io.BytesIO(source.read(record["image"]))).convert("RGB"))
            mask = np.asarray(Image.open(io.BytesIO(source.read(record["labels"]))).convert("L"))
            if not np.array_equal(image, rgb[y:y+sh, x:x+sw]):
                raise ValueError("Archived RGB disagrees with pilot")
            dest = reconstructed[y:y+sh, x:x+sw]
            if np.any((dest != 255) & (mask != 255) & (dest != mask)):
                raise ValueError("Conflicting reviewed labels")
            dest[mask != 255] = mask[mask != 255]
            windows += 1
    if not np.array_equal(reconstructed, labels):
        raise ValueError("Deduplicated labels differ from pilot")
    # Same-source sensitivity experiment, not independent source/park validation.
    end, start, size = 134, 166, 64
    if w <= start or h < size:
        raise ValueError("Unexpected pilot dimensions")
    records = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as dest:
        def write(x, y, width, height, group):
            mask = labels[y:y+height, x:x+width]
            if not np.any(mask != 255):
                return
            name = f"{group}_{x}_{y}"
            for suffix, arr in (("rgb", rgb[y:y+height, x:x+width]), ("labels", mask)):
                blob = io.BytesIO()
                Image.fromarray(arr).save(blob, format="PNG")
                dest.writestr(f"{name}_{suffix}.png", blob.getvalue())
            records.append({"sample_id":name, "split_group":group,
                            "source_group":"Mutiny_Bay_single_aerial_crop",
                            "image":name+"_rgb.png", "labels":name+"_labels.png",
                            "georef":{"crs":"EPSG:27700", "transform":[1,0,west+x,0,-1,north-y]}})
        for y in sorted(set(range(0, h-size+1, 32)) | {h-size}):
            for x in sorted(set(range(0, end-size+1, 32)) | {end-size}):
                write(x, y, size, size, "west_train")
        write(start, 0, w-start, h, "east_validation")
        report = {"schema":"mutiny-buffered-production-pilot-v1", "park_id":"alton_towers",
                  "label_map":manifest["label_map"], "samples":records,
                  "training_sha256":digest, "pilot_sha256":hashlib.sha256(pilot.read_bytes()).hexdigest(),
                  "verified_unrotated_windows":windows,
                  "split":{"train_source_x":[0,end], "validation_source_x":[start,w], "buffer_m":start-end},
                  "policy":"Single source crop; overlapping training windows are not independent. Validation pixels occur once; no source/park generalisation claim."}
        dest.writestr("manifest.json", json.dumps(report, indent=2))
    return {"samples":len(records), "verified_windows":windows,
            "train_unique_labelled_pixels":int(np.count_nonzero(labels[:,:end] != 255)),
            "validation_unique_labelled_pixels":int(np.count_nonzero(labels[:,start:] != 255))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("training", "pilot", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.training, args.pilot, args.output), indent=2))
