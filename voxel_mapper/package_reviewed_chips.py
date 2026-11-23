"""Package manually reviewed Magic Kingdom chip masks as a training dataset.

Expected input is the extracted annotation-chip directory. Edit grayscale
labels/*.png masks using the shared class IDs, then package this directory.
Ignore pixels remain 255 and all-ignore chips are retained but skipped by the
trainer. Overlapping chips stay grouped under the same source tile.
"""
from __future__ import annotations

import argparse
import csv
import json
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

from PIL import Image

IGNORE = 255
LABEL_MAP = {
    1: "grass_unspecified",
    2: "worn_grass_unlabelled",
    3: "dry_soil_unlabelled",
    4: "mud_unlabelled",
    5: "gravel_unlabelled",
    6: "stone_paving",
    7: "brick_paving",
    8: "asphalt",
    9: "paving_unspecified",
}


def package(chips_dir: Path, output_zip: Path, park_id: str, zone_id: str) -> dict:
    index_path = chips_dir / "chip_index.csv"
    if not index_path.is_file():
        raise FileNotFoundError(f"chip_index.csv not found under {chips_dir}")

    entries = []
    class_counts: Counter[int] = Counter()
    labelled_chips = 0
    with tempfile.TemporaryDirectory(prefix="voxel-reviewed-chips-") as temp_name:
        temp = Path(temp_name)
        with index_path.open(newline="", encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        if not rows:
            raise ValueError("chip_index.csv contains no chip rows")

        for row in rows:
            chip_id = row.get("chip_id")
            image_rel = row.get("image")
            labels_rel = row.get("labels")
            if not chip_id or not image_rel or not labels_rel:
                raise ValueError("each chip row needs chip_id, image, and labels")
            image_path = (chips_dir / image_rel).resolve()
            labels_path = (chips_dir / labels_rel).resolve()
            root = chips_dir.resolve()
            if root not in image_path.parents or root not in labels_path.parents:
                raise ValueError(f"chip paths must stay under the input directory: {chip_id}")
            if not image_path.is_file() or not labels_path.is_file():
                raise FileNotFoundError(f"missing image or edited mask for {chip_id}")

            with Image.open(image_path) as source:
                rgb = source.convert("RGB")
            with Image.open(labels_path) as source:
                labels = source.convert("L")
            if rgb.size != labels.size:
                raise ValueError(f"image/mask dimensions differ for {chip_id}: {rgb.size} vs {labels.size}")

            values = Counter(labels.getdata())
            invalid = sorted(value for value in values if value != IGNORE and value not in LABEL_MAP)
            if invalid:
                raise ValueError(f"{chip_id} has unknown class IDs {invalid}; expected 1-9 or 255")
            labelled = sum(count for value, count in values.items() if value != IGNORE)
            if labelled:
                labelled_chips += 1
                class_counts.update({value: count for value, count in values.items() if value != IGNORE})

            sample_dir = temp / "samples" / chip_id
            sample_dir.mkdir(parents=True, exist_ok=True)
            out_image = sample_dir / "rgb.png"
            out_labels = sample_dir / "labels.png"
            rgb.save(out_image, optimize=True)
            labels.save(out_labels, optimize=True)

            entries.append({
                "sample_id": chip_id,
                "park_id": park_id,
                "zone_id": zone_id,
                "source_id": "usda_naip_2021",
                "source_group": "m_2808136_sw_17_060_20211201_20220330",
                "split_group": "m_2808136_sw_17_060_20211201_20220330",
                "source_url": "https://imagery.geoplatform.gov/iipp/rest/services/NAIP/NAIP2021_CONUS/ImageServer",
                "source_license": "Public domain",
                "capture_date": "2021-12-01/2022-03-30",
                "horizontal_crs": "EPSG:32617",
                "ground_sample_distance_m": 0.61896750697,
                "label_scheme": "voxel-ground-surface-v1",
                "review_status": "reviewed" if labelled else "unlabelled",
                "image": out_image.relative_to(temp).as_posix(),
                "labels": out_labels.relative_to(temp).as_posix(),
            })

        if labelled_chips == 0:
            raise ValueError("No reviewed pixels found: every mask is still all-ignore (255)")

        manifest = {
            "title": "Magic Kingdom reviewed ground-surface chips",
            "park_id": park_id,
            "zone_id": zone_id,
            "version": "2026-11-ground-v1",
            "label_map": {str(key): value for key, value in LABEL_MAP.items()} | {
                str(IGNORE): "ignore_unlabelled"
            },
            "source": {
                "source_id": "usda_naip_2021",
                "source_tile": "m_2808136_sw_17_060_20211201_20220330",
                "source_url": "https://imagery.geoplatform.gov/iipp/rest/services/NAIP/NAIP2021_CONUS/ImageServer",
                "source_license": "Public domain",
                "capture_date": "2021-12-01/2022-03-30",
                "horizontal_crs": "EPSG:32617",
                "ground_sample_distance_m": 0.61896750697,
            },
            "samples": entries,
        }
        (temp / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (temp / "README.md").write_text(
            "# Magic Kingdom reviewed ground-surface chips\n\n"
            f"Reviewed chips: {labelled_chips}/{len(entries)}. "
            "All remaining 255 pixels are ignored, not background.\n\n"
            "Class IDs: 1 grass, 2 worn grass, 3 dry soil, 4 mud, 5 gravel, "
            "6 stone, 7 brick, 8 asphalt, 9 unspecified paving, 255 ignore. "
            "Do not assign a fine material from imagery where it is uncertain.\n\n"
            "The source is one overlapping NAIP capture; every chip shares one split_group. "
            "Keep all chips together for leakage-safe evaluation. Use the park as a held-out "
            "domain when combining with other parks.\n",
            encoding="utf-8",
        )
        output_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(temp.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(temp).as_posix())

    return {
        "output": str(output_zip),
        "samples": len(entries),
        "labelled_samples": labelled_chips,
        "class_pixels": {str(key): class_counts[key] for key in sorted(class_counts)},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chips-dir", type=Path, required=True,
                        help="Extracted Magic Kingdom annotation-chip directory with edited labels/")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--park-id", default="walt_disney_world_magic_kingdom")
    parser.add_argument("--zone-id", default="magic_kingdom_aoi")
    args = parser.parse_args()
    print(json.dumps(package(args.chips_dir, args.output, args.park_id, args.zone_id)))


if __name__ == "__main__":
    main()
