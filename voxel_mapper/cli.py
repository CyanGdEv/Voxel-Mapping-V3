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
        config.setdefault("sources", []).append({"id": "osm", "url": "https://www.openstreetmap.org/copyright", "license": "ODbL-1.0"})
    (output / "input.geojson").write_text(json.dumps(collection))
    report = build(config, collection, output)
    report["skipped_osm"] = skipped
    (output / "quality-report.json").write_text(json.dumps(report, indent=2))
    if config.get("strict", False) and (report["issues"] or skipped or not report["features"]):
        raise SystemExit("Strict accuracy gate failed; inspect quality-report.json")


if __name__ == "__main__":
    main()
