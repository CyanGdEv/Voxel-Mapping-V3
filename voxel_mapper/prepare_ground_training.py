"""Package existing Alton Towers semantic/paving masks for ground training.

This preserves broad labels as broad labels. It does not invent worn-grass,
soil, mud or gravel pixels; those remain ignore until reviewed masks are added.
Requires Pillow only for the optional dataset-preparation workflow.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import zipfile

from PIL import Image


IGNORE = 255


def _remap_semantic(mask: Image.Image) -> Image.Image:
    src = mask.convert("L")
    lut = [IGNORE] * 256
    # Existing semantic classes: 1 path/plaza, 4 lawn. Other classes include
    # roofs, water, track and planted islands; do not treat them as ground.
    lut[1], lut[4] = 9, 1
    return src.point(lut)


def _remap_paving(mask: Image.Image) -> Image.Image:
    src = mask.convert("L")
    out = Image.new("L", src.size, IGNORE)
    lut = [IGNORE] * 256
    # Mutiny Bay reviewed codes: 1 brick, 2 stone edge, 3 patterned stone,
    # 4 asphalt. Stone edge and patterned stone map to the stone paving class.
    lut[1], lut[2], lut[3], lut[4] = 7, 6, 6, 8
    return src.point(lut)


def prepare(semantic_root: Path, paving_root: Path, output_zip: Path) -> dict:
    entries = []
    temp = output_zip.with_suffix(".staging")
    if temp.exists():
        import shutil
        shutil.rmtree(temp)
    temp.mkdir(parents=True)
    for path in sorted((semantic_root / "views").glob("**/classes.png")):
        image_path = path.with_name("image.png")
        if not image_path.exists():
            continue
        mask = Image.open(path)
        rgb = Image.open(image_path).convert("RGB")
        if mask.size != rgb.size:
            raise ValueError(f"image/mask size mismatch: {path}")
        rel = path.parent.relative_to(semantic_root / "views")
        out_dir = temp / "samples" / "parkwide" / rel
        out_dir.mkdir(parents=True, exist_ok=True)
        rgb.save(out_dir / "rgb.png", optimize=True)
        _remap_semantic(mask).save(out_dir / "labels.png", optimize=True)
        entries.append({"sample_id": str(rel), "source_group": str(rel).split("/")[-1],
                        "image": str((out_dir / "rgb.png").relative_to(temp)),
                        "labels": str((out_dir / "labels.png").relative_to(temp)),
                        "source_label_scheme": "parkwide_semantic_v1", "split_group": str(rel)})

    detail_root = paving_root / "paving_detail"
    samples_csv = detail_root / "samples.csv"
    if not samples_csv.exists():
        raise FileNotFoundError(samples_csv)
    with samples_csv.open(newline="") as stream:
        for row in csv.DictReader(stream):
            sample_id = row["sample_id"]
            sample_dir = detail_root / "samples" / sample_id
            rgb_path, mask_path = sample_dir / "rgb.png", sample_dir / "labels.png"
            if not rgb_path.exists() or not mask_path.exists():
                continue
            rgb = Image.open(rgb_path).convert("RGB")
            mask = Image.open(mask_path)
            if rgb.size != mask.size:
                raise ValueError(f"image/mask size mismatch: {sample_id}")
            out_dir = temp / "samples" / "paving" / sample_id
            out_dir.mkdir(parents=True, exist_ok=True)
            rgb.save(out_dir / "rgb.png", optimize=True)
            _remap_paving(mask).save(out_dir / "labels.png", optimize=True)
            entries.append({"sample_id": sample_id, "source_group": row.get("split_group", "Mutiny_Bay"),
                            "image": str((out_dir / "rgb.png").relative_to(temp)),
                            "labels": str((out_dir / "labels.png").relative_to(temp)),
                            "source_label_scheme": "mutiny_bay_paving_v1",
                            "split_group": row.get("split_group", "Mutiny_Bay_single_aerial_crop")})

    manifest = {
        "title": "Alton Towers ground surface starter dataset",
        "park_id": "alton_towers",
        "version": "2026-11-ground-v1",
        "label_map": {
            "1": "grass_unspecified", "2": "worn_grass_unlabelled",
            "3": "dry_soil_unlabelled", "4": "mud_unlabelled",
            "5": "gravel_unlabelled", "6": "stone_paving",
            "7": "brick_paving", "8": "asphalt", "9": "paving_unspecified",
            "255": "ignore_unlabelled",
        },
        "rule": "Do not convert broad lawn/path labels into fine materials. Unlabelled fine classes remain ignore.",
        "lidar_role": "Use classified ground returns for terrain support and canopy exclusion; LiDAR class does not identify surface material.",
        "samples": entries,
    }
    (temp / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (temp / "README.md").write_text(
        "# Alton Towers ground-surface starter set\n\n"
        "Contains aligned park-wide aerial images and semantic masks plus reviewed Mutiny Bay paving patches. "
        "Grass and generic path pixels are preserved as broad labels; the dataset does not claim pixel labels "
        "for worn grass, soil, mud or gravel. Those classes are ignore/unlabelled until reviewed samples are added.\n\n"
        "Augmented rotations from the same aerial crop share one split_group; keep that group in a single train/validation/test split to prevent leakage.\n\n"
        "LiDAR ground classification can filter canopy and provide elevation. It cannot distinguish grass, mud, soil or paving material by itself.\n"
    )
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(temp.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(temp))
    import shutil
    shutil.rmtree(temp)
    return {"samples": len(entries), "output": str(output_zip)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--semantic-root", type=Path, required=True)
    parser.add_argument("--paving-root", type=Path, required=True,
                        help="Alton Towers AI Training Expansion v2 directory")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.semantic_root, args.paving_root, args.output)))


if __name__ == "__main__":
    main()
