import argparse
import hashlib
import json
import math
from pathlib import Path

import requests
from pyproj import CRS, Transformer
from shapely.geometry import Point, shape, mapping
from shapely.ops import transform
from shapely.validation import explain_validity


KINDS = {"building": "building", "highway": "path", "waterway": "water"}


def fetch_osm(bounds):
    west, south, east, north = bounds
    query = f'[out:json][timeout:120];(way({south},{west},{north},{east});relation["type"="multipolygon"]({south},{west},{north},{east}););out geom;'
    response = requests.post("https://overpass-api.de/api/interpreter", data={"data": query}, timeout=180)
    response.raise_for_status()
    data = response.json()
    if data.get("remark"):
        raise ValueError("Overpass returned incomplete data: " + data["remark"])
    features, skipped = [], []
    for element in data.get("elements", []):
        tags = element.get("tags", {})
        kind = next((v for k, v in KINDS.items() if k in tags), None)
        if tags.get("amenity") == "parking":
            kind = "parking"
        if tags.get("natural") == "water":
            kind = "water"
        if tags.get("attraction") or tags.get("roller_coaster"):
            kind = "attraction"
        if not kind:
            continue
        if element["type"] != "way":
            skipped.append({"id": element["id"], "reason": "multipolygon requires curated geometry"})
            continue
        coords = [[p["lon"], p["lat"]] for p in element.get("geometry", [])]
        if len(coords) < 2:
            skipped.append({"id": element["id"], "reason": "missing geometry"})
            continue
        closed = len(coords) >= 4 and coords[0] == coords[-1]
        geometry = {"type": "Polygon", "coordinates": [coords]} if closed and kind not in ("path", "attraction") else {"type": "LineString", "coordinates": coords}
        features.append({"type": "Feature", "id": f'osm/way/{element["id"]}', "geometry": geometry,
                         "properties": {**tags, "kind": kind, "source_id": "osm"}})
    return {"type": "FeatureCollection", "features": features}, data, skipped


def build(config, collection, output):
    west, south, east, north = config["bbox"]
    if not (-180 <= west < east <= 180 and -90 < south < north < 90):
        raise ValueError("bbox must be west,south,east,north; antimeridian areas must be split")
    resolution = float(config.get("voxel_size_m", 1))
    if not math.isfinite(resolution) or resolution <= 0:
        raise ValueError("voxel_size_m must be positive")
    crs = CRS.from_proj4(f'+proj=aeqd +lat_0={(south+north)/2} +lon_0={(west+east)/2} +datum=WGS84 +units=m')
    projector = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    area = transform(projector.transform, shape({"type": "Polygon", "coordinates": [[[west,south],[east,south],[east,north],[west,north],[west,south]]]}))
    if area.area > config.get("max_area_m2", 4_000_000):
        raise ValueError("Area exceeds configured build budget; split into smaller areas")
    sources = {s["id"]: s for s in config.get("sources", [])}
    for source in sources.values():
        if not source.get("url") or not source.get("license"):
            raise ValueError("Every source needs url and license")
    output.mkdir(parents=True, exist_ok=True)
    issues, accepted, count = [], [], 0
    budget = int(config.get("max_voxels", 5_000_000))
    voxel_path = output / "voxels.jsonl"
    try:
        with voxel_path.open("w") as stream:
            for feature in collection["features"]:
                fid = feature.get("id", len(accepted))
                properties = feature.get("properties", {})
                source_id = properties.get("source_id")
                if source_id not in sources:
                    raise ValueError(f"Feature {fid} has no registered source")
                geometry = shape(feature["geometry"])
                if geometry.is_empty or not geometry.is_valid:
                    issues.append({"feature": fid, "severity": "error", "reason": explain_validity(geometry)})
                    continue
                geometry = transform(projector.transform, geometry).intersection(area)
                kind = properties.get("kind", "structure")
                assumptions = []
                if geometry.geom_type in ("LineString", "MultiLineString", "Point"):
                    width = properties.get("width_m")
                    if width is None:
                        width = 1
                        assumptions.append("width assumed 1 m")
                    width = float(width)
                    if not math.isfinite(width) or width <= 0:
                        raise ValueError(f"Invalid width on {fid}")
                    geometry = geometry.buffer(width / 2).intersection(area)
                base = float(properties.get("base_elevation_m", 0))
                if "base_elevation_m" not in properties:
                    assumptions.append("base elevation assumed 0 m; terrain unavailable")
                height = properties.get("height_m", properties.get("height"))
                if height is None:
                    height = 1
                    assumptions.append("height assumed 1 m; actual vertical geometry unknown")
                try:
                    height = float(str(height).removesuffix(" m"))
                except ValueError:
                    height = 1
                    assumptions.append("unparseable height; assumed 1 m")
                if not math.isfinite(base) or not math.isfinite(height) or height <= 0:
                    raise ValueError(f"Invalid elevation or height on {fid}")
                if assumptions:
                    issues.append({"feature": fid, "severity": "warning", "reason": assumptions})
                if geometry.is_empty:
                    continue
                minx, miny, maxx, maxy = geometry.bounds
                for x in range(math.floor(minx/resolution), math.ceil(maxx/resolution)):
                    for z in range(math.floor(miny/resolution), math.ceil(maxy/resolution)):
                        if not geometry.covers(Point((x+.5)*resolution, (z+.5)*resolution)):
                            continue
                        for y in range(math.floor(base/resolution), math.ceil((base+height)/resolution)):
                            count += 1
                            if count > budget:
                                raise ValueError("Voxel budget exceeded; reduce area or increase voxel size")
                            stream.write(json.dumps({"x": x, "y": y, "z": z, "kind": kind, "feature": fid, "source": source_id}) + "\n")
                accepted.append({**feature, "geometry": mapping(geometry)})
    except Exception:
        voxel_path.unlink(missing_ok=True)
        raise
    report = {"version": "3.1.0", "voxel_size_m": resolution, "crs": crs.to_wkt(), "axis": {"x": "east", "y": "up", "z": "north"}, "sources": list(sources.values()), "voxel_records": count, "features": len(accepted), "issues": issues,
              "limitations": ["Footprint extrusion; no mesh or LiDAR reconstruction", "Overlapping feature records require downstream composition", "No automatic planning drawing georeferencing", "Metric scale is approximate away from local projection origin"],
              "sha256": hashlib.sha256(voxel_path.read_bytes()).hexdigest()}
    (output / "quality-report.json").write_text(json.dumps(report, indent=2))
    (output / "features-local.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": accepted}))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--features", help="WGS84 GeoJSON with source_id, kind, height_m, base_elevation_m")
    parser.add_argument("--output", default="output")
    parser.add_argument("--gis", action="store_true", help="Collect free Great Britain GIS evidence")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    skipped = []
    if args.features:
        collection = json.loads(Path(args.features).read_text())
    else:
        collection, raw, skipped = fetch_osm(config["bbox"])
        (output / "osm-raw.json").write_text(json.dumps(raw))
        if not any(s["id"] == "osm" for s in config.setdefault("sources", [])):
            config["sources"].append({"id": "osm", "url": "https://www.openstreetmap.org/copyright", "license": "ODbL-1.0"})
    gis_report = None
    features = []
    settings = config.get("gis", {})
    if args.gis or settings.get("enabled", False):
        from .open_gis import collect, fuse
        if config.get("strict", False) and settings.get("promote_missing_footprints", False):
            raise ValueError("Draft GIS footprint promotion is not permitted in strict mode")
        features, gis_report = collect(config["bbox"], settings, output)
        gis_report["fusion"] = fuse(collection, features, promote_missing=settings.get("promote_missing_footprints", False))
        registered = config.setdefault("sources", [])
        for source in gis_report["sources"]:
            if not any(s["id"] == source["id"] for s in registered):
                registered.append(source)
        (output / "gis-report.json").write_text(json.dumps(gis_report, indent=2), encoding="utf-8")
    landcover_report = None
    landcover_settings = config.get("landcover", {})
    if landcover_settings.get("enabled", False):
        from .landcover import collect as collect_landcover
        landcover_report = collect_landcover(config["bbox"], landcover_settings, output)
        source = landcover_report["source"]
        registered = config.setdefault("sources", [])
        if not any(s["id"] == source["id"] for s in registered):
            registered.append(source)
    context_report = None
    review_report = None
    context_settings = config.get("gis_context", {})
    if context_settings.get("enabled", False):
        from .gis_context import import_polygons, review_geometry, write_context_grid, annotate_context
        local, local_sources, local_layers = import_polygons(context_settings.get("local_polygons", []), config["bbox"], root=Path(args.config).resolve().parent)
        layers = (gis_report["layers"] if gis_report else []) + local_layers
        registered = config.setdefault("sources", [])
        for source in local_sources:
            if any(s["id"] == source["id"] for s in registered):
                raise ValueError("Duplicate local GIS source ID: " + source["id"])
            registered.append(source)
        features = features + local
        if local:
            (output / "gis-local-polygons.geojson").write_text(json.dumps({"type":"FeatureCollection","features":local}), encoding="utf-8")
        review_report, candidates = review_geometry(collection, features, config["bbox"], min_gap_m2=float(context_settings.get("min_gap_m2",4)))
        review_report["local_layers"] = local_layers
        review_report["feature_context"] = annotate_context(collection, features, config["bbox"])
        (output / "gis-geometry-review.json").write_text(json.dumps(review_report, indent=2), encoding="utf-8")
        (output / "gis-gap-candidates.geojson").write_text(json.dumps(candidates), encoding="utf-8")
        context_report = write_context_grid(config["bbox"], features, layers, output, landcover_report=landcover_report, cell_m=float(context_settings.get("cell_m",5)))
    (output / "input.geojson").write_text(json.dumps(collection))
    report = build(config, collection, output)
    report["skipped_osm"] = skipped
    if gis_report is not None:
        report["gis"] = {k: gis_report[k] for k in ("feature_count", "layers", "fusion", "policy")}
        if settings.get("required", False) and any(layer["status"] in ("partial", "unavailable") for layer in gis_report["layers"]):
            report["issues"].append({"severity": "error", "reason": "Required GIS evidence unavailable or partial"})
    if context_report is not None:
        report["gis_context"] = context_report
        report["gis_geometry_review"] = {k:v for k,v in review_report.items() if k!="comparisons"}
    if landcover_report is not None:
        report["landcover"] = landcover_report
        if landcover_settings.get("required", False) and landcover_report["status"] != "available":
            report["issues"].append({"severity":"error","reason":"Required land-cover evidence unavailable"})
    (output / "quality-report.json").write_text(json.dumps(report, indent=2))
    if landcover_report is not None and landcover_settings.get("required", False) and landcover_report["status"] != "available":
        raise SystemExit("Required land-cover evidence unavailable; inspect landcover-report.json")
    if gis_report is not None and settings.get("required", False) and any(layer["status"] in ("partial", "unavailable") for layer in gis_report["layers"]):
        raise SystemExit("Required GIS sources failed; inspect gis-report.json")
    if config.get("strict", False) and (report["issues"] or skipped or not report["features"]):
        raise SystemExit("Strict accuracy gate failed; inspect quality-report.json")


if __name__ == "__main__":
    main()
