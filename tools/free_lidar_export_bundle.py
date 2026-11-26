"""Build a free/open-source LiDAR evidence bundle with PDAL and GDAL.

Input LAZ tiles must already have usable ASPRS classifications. The pipeline
does not mutate the source tiles: it derives ground/DSM rasters and a separate
vegetation-point LAZ for downstream canopy reconstruction.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def _check_program(name: str) -> str:
    program = shutil.which(name)
    if not program:
        raise RuntimeError(f"{name} is required; install the free/open-source PDAL and GDAL packages")
    return program


def _run_pdal(pdal: str, pipeline: dict, workdir: Path, label: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8",
                                     dir=workdir, delete=False) as stream:
        json.dump(pipeline, stream)
        pipeline_path = Path(stream.name)
    try:
        subprocess.run([pdal, "pipeline", str(pipeline_path)], cwd=workdir, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"PDAL {label} pipeline failed with exit code {exc.returncode}") from exc
    finally:
        pipeline_path.unlink(missing_ok=True)


def export(config_path: Path) -> Path:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    pdal = _check_program("pdal")
    gdalinfo = _check_program("gdalinfo")
    output = Path(config["output_directory"]).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    inputs = [Path(p).expanduser().resolve() for p in config.get("las_tiles", [])]
    if not inputs:
        raise ValueError("las_tiles must list one or more downloaded EA LAS/LAZ tiles")
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        raise FileNotFoundError("Input point-cloud tiles not found: " + ", ".join(missing))
    if config.get("classification_verified") is not True:
        raise ValueError("Set classification_verified=true only after checking that LAS classes are meaningful")
    resolution = float(config.get("resolution_m", 1.0))
    if not 0.1 <= resolution <= 5.0:
        raise ValueError("resolution_m must be between 0.1 and 5 metres")
    grid = config.get("grid", {})
    if grid and not all(k in grid for k in ("origin_x", "origin_y", "width", "height")):
        raise ValueError("grid requires origin_x, origin_y, width and height together")
    if grid and (int(grid["width"]) <= 0 or int(grid["height"]) <= 0):
        raise ValueError("grid width and height must be positive cell counts")
    bounds = config.get("bounds")
    if bounds and (not isinstance(bounds, list) or len(bounds) != 4):
        raise ValueError("bounds must be [xmin, ymin, xmax, ymax] in the LAS projected CRS")
    if bounds and grid:
        raise ValueError("Use bounds or grid, not both")

    source_id = config.get("source_id")
    sources = config.get("sources", [])
    if not isinstance(sources, list) or not sources:
        raise ValueError("sources must declare the free data sources used for this bundle")
    allowed_license_markers = ("open government licence", "odbl", "cc0", "cc by", "public domain")
    for source in sources:
        if not isinstance(source, dict) or not source.get("id") or not source.get("url") or not source.get("license"):
            raise ValueError("Each source needs id, URL and an explicit open-data license")
        license_name = str(source["license"]).casefold().replace("-", " ").replace("_", " ")
        if not any(marker in license_name for marker in allowed_license_markers):
            raise ValueError(f"Source {source['id']} does not declare a supported open-data license")
    if not source_id or not any(s.get("id") == source_id for s in sources if isinstance(s, dict)):
        raise ValueError("source_id must reference a source record in sources")
    srs = config.get("crs", "EPSG:27700")
    readers = [{"type": "readers.las", "filename": str(path), "tag": f"tile_{i}"}
               for i, path in enumerate(inputs)]
    merge = {"type": "filters.merge", "inputs": [f"tile_{i}" for i in range(len(inputs))],
             "tag": "merged"}
    ground = {"type": "filters.range", "inputs": ["merged"],
              "limits": "Classification[2:2]", "tag": "ground"}
    dsm_limits = config.get("dsm_class_limits", "Classification[0:6],Classification[9:11]")
    surface = {"type": "filters.range", "inputs": ["merged"],
               "limits": dsm_limits, "tag": "surface"}
    veg_classes = config.get("vegetation_classes", [3, 4, 5])
    if not isinstance(veg_classes, list) or not veg_classes or any(int(v) < 0 for v in veg_classes):
        raise ValueError("vegetation_classes must be a non-empty list of LAS class codes")
    veg_limits = ",".join(f"Classification[{int(code)}:{int(code)}]" for code in veg_classes)
    vegetation = {"type": "filters.range", "inputs": ["merged"],
                  "limits": veg_limits, "tag": "vegetation"}

    grid_options = ({"origin_x": float(grid["origin_x"]), "origin_y": float(grid["origin_y"]),
                    "width": int(grid["width"]), "height": int(grid["height"]) } if grid else {})
    if bounds:
        grid_options["bounds"] = f"([{float(bounds[0])},{float(bounds[2])}], [{float(bounds[1])},{float(bounds[3])}])"
    base_writer = {"resolution": resolution, "gdaldriver": "GTiff", "data_type": "float32",
                   "binmode": True, "pdal_metadata": True, "default_srs": srs, **grid_options}
    dtm_path = output / "terrain_dtm.tif"
    dsm_path = output / "surface_dsm.tif"
    veg_path = output / "vegetation_points.laz"
    pipeline = readers + [merge, ground, surface, vegetation,
        {"type": "writers.gdal", "inputs": ["ground"], "filename": str(dtm_path),
         "output_type": "mean", **base_writer},
        {"type": "writers.gdal", "inputs": ["surface"], "filename": str(dsm_path),
         "output_type": "max", **base_writer},
        {"type": "writers.las", "inputs": ["vegetation"], "filename": str(veg_path),
         "compression": True, "forward": "all"}]
    intensity_path = output / "ground_intensity.tif"
    if config.get("export_ground_intensity", False):
        if not (grid or bounds):
            raise ValueError("Ground intensity requires explicit grid or bounds for alignment")
        pipeline.append({"type":"writers.gdal", "inputs":["ground"],
                         "filename":str(intensity_path), "dimension":"Intensity",
                         "output_type":"mean", **base_writer})
    _run_pdal(pdal, {"pipeline": pipeline}, output, "LiDAR export")

    raster_info = {}
    rasters = [dtm_path, dsm_path] + ([intensity_path] if config.get("export_ground_intensity", False) else [])
    for raster_path in rasters:
        metadata = subprocess.run([gdalinfo, "-json", str(raster_path)], check=True,
                                  capture_output=True, text=True)
        raster_info[raster_path.name] = json.loads(metadata.stdout)

    layers = [
        {"id": "terrain-dtm", "role": "terrain_dtm", "path": dtm_path.name,
         "source_id": source_id, "crs": srs, "resolution_m": resolution,
         "raster_info": {"width": raster_info[dtm_path.name]["size"][0],
                         "height": raster_info[dtm_path.name]["size"][1]},
         "observed_date": config.get("observed_date"),
         "vertical_accuracy_m": config.get("vertical_accuracy_m")},
        {"id": "surface-dsm", "role": "surface_dsm", "path": dsm_path.name,
         "source_id": source_id, "crs": srs, "resolution_m": resolution,
         "raster_info": {"width": raster_info[dsm_path.name]["size"][0],
                         "height": raster_info[dsm_path.name]["size"][1]},
         "observed_date": config.get("observed_date"),
         "vertical_accuracy_m": config.get("vertical_accuracy_m")},
        {"id": "vegetation-returns", "role": "vegetation_points", "path": veg_path.name,
         "source_id": source_id, "crs": srs, "observed_date": config.get("observed_date"),
         "classification_scheme": config.get("classification_scheme", "ASPRS LAS classes")},
    ]
    if config.get("export_ground_intensity", False):
        info = raster_info[intensity_path.name]
        layers.append({"id":"ground-intensity","role":"lidar_intensity","path":intensity_path.name,
                       "source_id":source_id,"crs":srs,"resolution_m":resolution,
                       "observed_date":config.get("observed_date"),
                       "raster_info":{"width":info["size"][0],"height":info["size"][1]},
                       "intensity_policy":"Uncalibrated mean of class 2 returns; no reflectance or material label inference."})
    manifest = {"schema_version": "voxel-geospatial-bundle-v1",
                "park": config.get("park", "Alton Towers"),
                "crs": {"horizontal": srs, "vertical_datum": config.get("vertical_datum", "unknown"),
                        "linear_units": "metre"},
                "sources": sources, "layers": layers,
                "export_notes": [
                    "Created with PDAL/GDAL; source LAS/LAZ tiles were not modified.",
                    "DTM uses only verified class 2 ground points; empty cells are left NoData.",
                    "DSM uses the maximum of configured valid classes; noise classes should be excluded.",
                    "Vegetation returns are exported separately using the configured class codes.",
                    "Raster pixel size is not a claim about the original point spacing or survey accuracy.",
                ]}
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="JSON configuration for free/open LiDAR inputs")
    args = parser.parse_args()
    try:
        print(export(args.config))
    except Exception as exc:
        print(f"LiDAR export failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
