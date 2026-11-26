"""Acquire real park context and write a catalog for voxel-pack-multisource."""
import argparse
import hashlib
import json
from pathlib import Path

from voxel_mapper.open_gis import collect
from voxel_mapper.landcover import collect as collect_landcover
from voxel_mapper.gis_context import write_context_grid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--park-id", required=True)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    features, report = collect(config["bbox"], config.get("gis", {}), args.output)
    landcover = collect_landcover(config["bbox"], config.get("landcover", {}), args.output)
    grid = write_context_grid(config["bbox"], features, report["layers"], args.output,
                              landcover_report=landcover,
                              cell_m=config.get("gis_context", {}).get("cell_m", 5))
    catalog = {"parks": {args.park_id: {"gis": "gis-context.json"}}}
    (args.output / "training-catalog.json").write_text(json.dumps(catalog, indent=2))
    incomplete = [r["source_id"] for r in report["layers"] if r["status"] in ("partial", "unavailable")]
    if landcover["status"] != "available":
        incomplete.append("sentinel2-landcover")
    result = {"features": len(features), "context_shape": grid["shape"],
              "incomplete_sources": incomplete,
              "training_executed": False, "world_blocks_changed": 0,
              "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in args.output.iterdir() if p.is_file() and p.name != "acquisition-summary.json"}}
    (args.output / "acquisition-summary.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    if args.require_complete and incomplete:
        raise SystemExit("Acquisition incomplete; inspect source reports")


if __name__ == "__main__":
    main()
