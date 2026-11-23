"""Export ArcGIS Pro LiDAR, raster and feature layers as a Voxel Mapper bundle.

Run with ArcGIS Pro's Python environment (arcpy). Input LAS data is read only;
ground classification must already be present as ASPRS class 2. This prevents
the exporter from silently changing source point-cloud classifications.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def _layer(arcpy, source: dict, output: Path, role: str, *, raster: bool = False) -> dict:
    in_path = Path(source["path"])
    if not arcpy.Exists(str(in_path)):
        raise FileNotFoundError(f"ArcGIS input not found for {role}: {in_path}")
    if raster:
        desc = arcpy.Describe(str(in_path))
        if int(getattr(desc, "bandCount", 0)) != 1:
            raise ValueError(f"{role} must be a single-band categorical raster")
        out = output / f"{role}.tif"
        arcpy.management.CopyRaster(str(in_path), str(out), format="TIFF")
        raster_sr = desc.spatialReference
        raster_code = int(getattr(raster_sr, "factoryCode", 0) or 0)
        raster_crs = f"EPSG:{raster_code}" if raster_code else raster_sr.name
        codes = source.get("class_codes")
        if not isinstance(codes, list) or not codes:
            raise ValueError("surface_labels requires class_codes in its input config")
        return {"id": role, "role": role, "path": out.name,
                "source_id": source["source_id"], "crs": raster_crs,
                "class_codes": codes, "labels_reviewed": bool(source.get("labels_reviewed", False)),
                "observed_date": source.get("observed_date"),
                "horizontal_accuracy_m": source.get("horizontal_accuracy_m"),
                "resolution_m": source.get("resolution_m")}

    out = output / f"{role}.geojson"
    # Features To JSON projects to WGS84 and emits standards-compliant GeoJSON.
    arcpy.conversion.FeaturesToJSON(
        str(in_path), str(out), "NOT_FORMATTED", "NO_Z_VALUES", "NO_M_VALUES",
        "GEOJSON", "WGS84", "USE_FIELD_NAME")
    collection = json.loads(out.read_text(encoding="utf-8"))
    kind = {"path_polygons": "path", "building_footprints": "building",
            "canopy_polygons": "canopy"}[role]
    for index, feature in enumerate(collection.get("features", [])):
        properties = feature.setdefault("properties", {})
        properties["source_id"] = source["source_id"]
        properties["kind"] = kind
        properties["evidence_type"] = source.get("evidence_type", "aerial")
        for output_name, config_name in (("height_m", "height_field"),
                                         ("base_elevation_m", "base_elevation_field"),
                                         ("width_m", "width_field")):
            field = source.get(config_name)
            if field and properties.get(field) not in (None, ""):
                properties[output_name] = properties[field]
        if not feature.get("id"):
            feature["id"] = f"{role}/{index}"
    out.write_text(json.dumps(collection, separators=(",", ":")), encoding="utf-8")
    return {"id": role, "role": role, "path": out.name,
            "source_id": source["source_id"], "crs": "EPSG:4326",
            "observed_date": source.get("observed_date"),
            "horizontal_accuracy_m": source.get("horizontal_accuracy_m"),
            "vertical_accuracy_m": source.get("vertical_accuracy_m")}


def export(config_path: Path) -> Path:
    try:
        import arcpy  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("Run this script with ArcGIS Pro's Python environment; arcpy is unavailable") from exc

    config = json.loads(config_path.read_text(encoding="utf-8"))
    output = Path(config["output_directory"]).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    inputs = config.get("inputs", {})
    lidar = inputs.get("classified_lidar")
    if not isinstance(lidar, dict) or not lidar.get("path") or not lidar.get("source_id"):
        raise ValueError("config.inputs.classified_lidar requires path and source_id")
    lasd = str(Path(lidar["path"]).expanduser().resolve())
    if not arcpy.Exists(lasd):
        raise FileNotFoundError(f"LAS dataset not found: {lasd}")
    if config.get("ground_returns_verified") is not True:
        raise ValueError("Set ground_returns_verified=true only after confirming ASPRS class 2 ground points")

    sr = arcpy.Describe(lasd).spatialReference
    if not sr or getattr(sr, "type", "") != "Projected":
        raise ValueError("The LAS dataset must use a projected coordinate system before raster export")
    linear_unit = (getattr(sr, "linearUnitName", "") or "").lower()
    if linear_unit not in {"meter", "metre", "meters", "metres"}:
        raise ValueError(f"LAS dataset coordinates must be metres, not {linear_unit or 'unknown units'}")
    factory_code = int(getattr(sr, "factoryCode", 0) or 0)
    horizontal_crs = f"EPSG:{factory_code}" if factory_code else sr.name
    resolution = float(config.get("surface_resolution_m", 1.0))
    if not 0.1 <= resolution <= 5.0:
        raise ValueError("surface_resolution_m must be between 0.1 and 5 metres")

    if arcpy.CheckExtension("3D") not in {"Available", "CheckedOut"}:
        raise RuntimeError("ArcGIS Pro 3D Analyst is required for LAS Dataset To Raster")
    arcpy.CheckOutExtension("3D")
    layers = []
    try:
        aoi = config.get("area_of_interest")
        with arcpy.EnvManager(overwriteOutput=True, cellSize=resolution,
                              extent=aoi if aoi else None):
            ground_layer = "voxel_ground_class_2"
            arcpy.management.MakeLasDatasetLayer(lasd, ground_layer, "2")
            dtm = output / "terrain_dtm.tif"
            arcpy.conversion.LasDatasetToRaster(
                ground_layer, str(dtm), "ELEVATION", "BINNING AVERAGE LINEAR",
                "FLOAT", "CELLSIZE", resolution, 1.0)
            layers.append({"id": "terrain_dtm", "role": "terrain_dtm",
                           "path": dtm.name, "source_id": lidar["source_id"],
                           "crs": horizontal_crs, "resolution_m": resolution,
                           "observed_date": lidar.get("observed_date"),
                           "horizontal_accuracy_m": lidar.get("horizontal_accuracy_m"),
                           "vertical_accuracy_m": lidar.get("vertical_accuracy_m")})

            dsm = output / "surface_dsm.tif"
            with arcpy.EnvManager(snapRaster=str(dtm)):
                surface_layer = "voxel_surface_points"
                arcpy.management.MakeLasDatasetLayer(
                    lasd, surface_layer, "0;1;2;3;4;5;6;9;11")
                arcpy.conversion.LasDatasetToRaster(
                    surface_layer, str(dsm), "ELEVATION", "BINNING MAXIMUM LINEAR",
                    "FLOAT", "CELLSIZE", resolution, 1.0)
            layers.append({"id": "surface_dsm", "role": "surface_dsm",
                           "path": dsm.name, "source_id": lidar["source_id"],
                           "crs": horizontal_crs, "resolution_m": resolution,
                           "observed_date": lidar.get("observed_date"),
                           "horizontal_accuracy_m": lidar.get("horizontal_accuracy_m"),
                           "vertical_accuracy_m": lidar.get("vertical_accuracy_m")})

        for role in ("surface_labels", "path_polygons", "building_footprints", "canopy_polygons"):
            source = inputs.get(role)
            if source:
                layers.append(_layer(arcpy, source, output, role,
                                     raster=(role == "surface_labels")))
    finally:
        arcpy.CheckInExtension("3D")

    sources = config.get("sources", [])
    source_ids = {str(s.get("id")) for s in sources if isinstance(s, dict) and s.get("id")}
    missing = sorted({layer["source_id"] for layer in layers} - source_ids)
    if missing:
        raise ValueError(f"Declare source records for every source_id; missing: {missing}")

    manifest = {
        "schema_version": "voxel-arcgis-extract-v1",
        "park": config.get("park", "Alton Towers"),
        "crs": {"horizontal": horizontal_crs,
                "vertical_datum": config.get("vertical_datum", "unknown"),
                "linear_units": "metre"},
        "sources": sources,
        "layers": layers,
        "export_notes": [
            "LAS source was read only; ground class 2 was filtered to produce the DTM.",
            "DSM uses maximum elevation from the available LAS points.",
            "Categorical surface labels were copied without inferring new material classes.",
            "Feature layers were exported to WGS84 GeoJSON for portable review.",
        ],
    }
    path = output / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="JSON inputs and provenance config")
    args = parser.parse_args()
    try:
        print(export(args.config))
    except Exception as exc:
        print(f"ArcGIS export failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
