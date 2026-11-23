"""Validate open geospatial exports before they enter the park evidence pipeline.

The adapter is intentionally an intake/QA boundary, not a Minecraft world
writer. This module checks metadata, lineage and class codes and emits a
normalized catalog for later geometry and world-generation stages.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA = "voxel-geospatial-bundle-v1"
ROLES = {
    "classified_lidar": {".las", ".laz"},
    "vegetation_points": {".las", ".laz"},
    "terrain_dtm": {".tif", ".tiff"},
    "surface_dsm": {".tif", ".tiff"},
    "surface_labels": {".tif", ".tiff"},
    "path_polygons": {".gpkg", ".geojson", ".json", ".shp"},
    "building_footprints": {".gpkg", ".geojson", ".json", ".shp"},
    "canopy_polygons": {".gpkg", ".geojson", ".json", ".shp"},
    "building_3d": {".slpk", ".obj", ".glb", ".gltf", ".multipatch"},
}
SURFACE_CODES = {
    1: "grass_unspecified", 2: "worn_grass", 3: "dry_soil", 4: "mud",
    5: "gravel", 6: "stone_paving", 7: "brick_paving", 8: "asphalt",
    9: "paving_unspecified", 10: "unknown_ground", 255: "ignore_unlabelled",
}


def _error(errors: list[str], message: str) -> None:
    errors.append(message)


def validate(root: Path, manifest_path: Path) -> dict[str, Any]:
    """Validate a bundle manifest and return a machine-readable QA report."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "errors": [f"Cannot read manifest: {exc}"], "warnings": [], "layers": []}

    if manifest.get("schema_version") != SCHEMA:
        _error(errors, f"schema_version must be {SCHEMA!r}")
    park = manifest.get("park")
    if not isinstance(park, str) or not park.strip():
        _error(errors, "park must be a non-empty name")
    crs = manifest.get("crs", {})
    if not isinstance(crs, dict) or not crs.get("horizontal"):
        _error(errors, "crs.horizontal is required (for example EPSG:27700)")
    elif crs.get("linear_units", "metre") not in {"metre", "meter", "m"}:
        _error(errors, "horizontal CRS units must be metres for the park voxel grid")

    sources = manifest.get("sources", [])
    if not isinstance(sources, list):
        _error(errors, "sources must be a list")
        sources = []
    source_ids = {str(s.get("id")) for s in sources if isinstance(s, dict) and s.get("id")}
    if len(source_ids) != len([s for s in sources if isinstance(s, dict) and s.get("id")]):
        _error(errors, "source ids must be unique")

    layers = manifest.get("layers", [])
    if not isinstance(layers, list) or not layers:
        _error(errors, "layers must contain at least one exported layer")
        layers = []
    seen_ids: set[str] = set()
    seen_roles: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for i, layer in enumerate(layers):
        prefix = f"layers[{i}]"
        if not isinstance(layer, dict):
            _error(errors, f"{prefix} must be an object")
            continue
        layer_id, role, relpath = layer.get("id"), layer.get("role"), layer.get("path")
        if not isinstance(layer_id, str) or not layer_id.strip() or layer_id in seen_ids:
            _error(errors, f"{prefix}.id must be a unique non-empty string")
        else:
            seen_ids.add(layer_id)
        if role not in ROLES:
            _error(errors, f"{prefix}.role is unsupported: {role!r}")
            continue
        seen_roles.add(role)
        if not isinstance(relpath, str) or not relpath.strip():
            _error(errors, f"{prefix}.path is required")
            continue
        posix_path = PurePosixPath(relpath)
        if posix_path.is_absolute() or ".." in posix_path.parts:
            _error(errors, f"{prefix}.path must stay inside the bundle")
            continue
        asset = (root / Path(*posix_path.parts)).resolve()
        try:
            asset.relative_to(root.resolve())
        except ValueError:
            _error(errors, f"{prefix}.path resolves outside the bundle")
            continue
        if not asset.is_file():
            _error(errors, f"{prefix} asset not found: {relpath}")
            continue
        ext = asset.suffix.lower()
        if ext not in ROLES[role]:
            _error(errors, f"{prefix} extension {ext!r} is invalid for role {role!r}")
        layer_crs = layer.get("crs", crs.get("horizontal") if isinstance(crs, dict) else None)
        if not layer_crs:
            _error(errors, f"{prefix}.crs is required or must inherit the bundle CRS")
        if layer.get("source_id") not in source_ids:
            _error(errors, f"{prefix}.source_id must reference a declared source")
        for key in ("horizontal_accuracy_m", "vertical_accuracy_m", "resolution_m"):
            value = layer.get(key)
            if value is not None and (not isinstance(value, (int, float)) or value <= 0):
                _error(errors, f"{prefix}.{key} must be a positive number")
        if role == "surface_labels":
            codes = layer.get("class_codes")
            if not isinstance(codes, list) or not codes:
                _error(errors, f"{prefix}.class_codes is required for a surface_labels raster")
            else:
                try:
                    numeric_codes = {int(c) for c in codes}
                except (TypeError, ValueError):
                    _error(errors, f"{prefix}.class_codes must contain integer codes")
                    numeric_codes = set()
                invalid = sorted(numeric_codes - set(SURFACE_CODES))
                if invalid:
                    _error(errors, f"{prefix} has unsupported surface class codes: {invalid}")
                if 2 in numeric_codes and not layer.get("labels_reviewed", False):
                    warnings.append(f"{prefix}: worn-grass labels are marked present but not reviewed")
        if role == "classified_lidar" and not layer.get("classification_scheme"):
            warnings.append(f"{prefix}: declare classification_scheme (ASPRS recommended)")

        raster_info = None
        if ext in {".tif", ".tiff"}:
            try:
                import rasterio  # type: ignore[import-not-found]
                with rasterio.open(asset) as src:
                    raster_info = {"width": src.width, "height": src.height,
                                   "bands": src.count, "crs": src.crs.to_string() if src.crs else None,
                                   "pixel_size_m": [abs(src.transform.a), abs(src.transform.e)]}
                    if src.crs and layer_crs and src.crs.to_string().upper() != str(layer_crs).upper():
                        warnings.append(f"{prefix}: raster CRS {src.crs} differs from declared {layer_crs}")
            except ImportError:
                warnings.append(f"{prefix}: rasterio unavailable; GeoTIFF metadata not independently inspected")
            except Exception as exc:  # metadata-only inspection must not hide a malformed export
                _error(errors, f"{prefix}: cannot inspect GeoTIFF metadata: {exc}")
        normalized.append({"id": layer_id, "role": role, "path": relpath,
                           "crs": layer_crs, "source_id": layer.get("source_id"),
                           "observed_date": layer.get("observed_date"),
                           "resolution_m": layer.get("resolution_m"),
                           "horizontal_accuracy_m": layer.get("horizontal_accuracy_m"),
                           "vertical_accuracy_m": layer.get("vertical_accuracy_m"),
                           "class_codes": layer.get("class_codes"), "raster_info": raster_info})

    if "surface_labels" not in seen_roles:
        warnings.append("No reviewed surface-label raster: this bundle cannot yet improve material classification")
    if "terrain_dtm" not in seen_roles and "classified_lidar" not in seen_roles:
        warnings.append("No DTM or classified LiDAR: terrain elevations are not represented")
    if "path_polygons" not in seen_roles:
        warnings.append("No path polygons: path geometry is not represented in this bundle")
    return {"ok": not errors, "schema_version": SCHEMA, "park": park,
            "crs": crs, "layers": normalized, "errors": errors, "warnings": warnings,
            "downstream_status": "validated_export_bundle" if not errors else "blocked",
            "limitation": "Validation does not convert GIS layers into Minecraft geometry."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="open geospatial bundle directory")
    parser.add_argument("--manifest", type=Path, default=Path("manifest.json"),
                        help="manifest path relative to the bundle (default: manifest.json)")
    parser.add_argument("--report", type=Path, help="optional JSON QA report path")
    args = parser.parse_args()
    manifest_path = args.manifest if args.manifest.is_absolute() else args.bundle / args.manifest
    report = validate(args.bundle, manifest_path)
    rendered = json.dumps(report, indent=2)
    if args.report:
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if report["ok"] else 2)


if __name__ == "__main__":
    main()
