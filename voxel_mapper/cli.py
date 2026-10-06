import argparse
import hashlib
import json
import math
from pathlib import Path

import requests
from pyproj import CRS, Transformer
from shapely.geometry import Point, shape, mapping, LineString
from shapely.ops import transform, polygonize_full, unary_union
from .terrain import Terrain
from shapely.validation import explain_validity
from .acquisition import USER_AGENT


KINDS = {"building": "building", "highway": "path", "waterway": "water"}


def fetch_osm(bounds):
    west, south, east, north = bounds
    query = f'[out:json][timeout:120];(way({south},{west},{north},{east});relation["type"="multipolygon"]({south},{west},{north},{east}););out meta geom;'
    response = requests.post("https://overpass-api.de/api/interpreter", data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=180)
    response.raise_for_status()
    data = response.json()
    if data.get("remark"):
        raise ValueError("Overpass returned incomplete data: " + data["remark"])
    collection, skipped = parse_osm(data)
    return collection, data, skipped


def parse_osm(data):
    features, skipped, represented_members = [], [], set()
    elements = sorted(data.get("elements", []), key=lambda e: e["type"] != "relation")
    for element in elements:
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
        if element["type"] == "way" and element["id"] in represented_members:
            continue
        try:
            if element["type"] == "relation":
                rings = {"outer": [], "inner": []}
                for member in element.get("members", []):
                    role = member.get("role") or "outer"
                    if member.get("type") != "way" or role not in rings:
                        raise ValueError("unsupported multipolygon member")
                    coords = [(p["lon"], p["lat"]) for p in member.get("geometry", [])]
                    if len(coords) < 2:
                        raise ValueError("missing relation member geometry")
                    rings[role].append(LineString(coords))
                assembled = {}
                for role, lines in rings.items():
                    polygons, cuts, dangles, invalid = polygonize_full(lines)
                    if not cuts.is_empty or not dangles.is_empty or not invalid.is_empty:
                        raise ValueError("unclosed or invalid multipolygon rings")
                    assembled[role] = unary_union(polygons)
                outer, inner = assembled["outer"], assembled["inner"]
                if outer.is_empty or not outer.covers(inner):
                    raise ValueError("missing outer ring or inner outside outer")
                geom = outer.difference(inner)
                if not geom.is_valid or geom.is_empty:
                    raise ValueError("invalid assembled multipolygon")
                represented_members.update(m["ref"] for m in element["members"])
                geometry = mapping(geom)
            else:
                coords = [[p["lon"], p["lat"]] for p in element.get("geometry", [])]
                if len(coords) < 2:
                    raise ValueError("missing geometry")
                closed = len(coords) >= 4 and coords[0] == coords[-1]
                geometry = {"type": "Polygon", "coordinates": [coords]} if closed and (kind not in ("path", "attraction") or tags.get("area") == "yes") else {"type": "LineString", "coordinates": coords}
            features.append({"type": "Feature", "id": f'osm/{element["type"]}/{element["id"]}', "geometry": geometry,
                             "properties": {**tags, "kind": kind, "source_id": "osm"}})
        except (ValueError, KeyError) as error:
            skipped.append({"id": element["id"], "reason": str(error)})
    return {"type": "FeatureCollection", "features": features}, skipped


def validate_config(config):
    west, south, east, north = config["bbox"]
    if not (-180 <= west < east <= 180 and -90 < south < north < 90):
        raise ValueError("bbox must be west,south,east,north; antimeridian areas must be split")
    resolution = float(config.get("voxel_size_m", 1))
    if not math.isfinite(resolution) or resolution <= 0:
        raise ValueError("voxel_size_m must be positive")
    return west, south, east, north, resolution


def build(config, collection, output):
    west, south, east, north, resolution = validate_config(config)
    crs = CRS.from_proj4(f'+proj=aeqd +lat_0={(south+north)/2} +lon_0={(west+east)/2} +datum=WGS84 +units=m')
    projector = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    area = transform(projector.transform, shape({"type": "Polygon", "coordinates": [[[west,south],[east,south],[east,north],[west,north],[west,south]]]}))
    if config.get("boundary_geojson"):
        boundary = shape(config["boundary_geojson"])
        if not boundary.is_valid or boundary.geom_type not in ("Polygon", "MultiPolygon"):
            raise ValueError("Park boundary is not a valid polygon")
        area = area.intersection(transform(projector.transform, boundary))
    if area.area > config.get("max_area_m2", 4_000_000):
        raise ValueError("Area exceeds configured build budget; split into smaller areas")
    sources = {s["id"]: s for s in config.get("sources", [])}
    for source in sources.values():
        if not source.get("url") or not source.get("license"):
            raise ValueError("Every source needs url and license")
    output.mkdir(parents=True, exist_ok=True)
    issues, accepted, count = [], [], 0
    scanned = 0
    scan_budget = int(config.get("max_column_checks", 10_000_000))
    if scan_budget <= 0:
        raise ValueError("max_column_checks must be positive")
    budget = int(config.get("max_voxels", 5_000_000))
    if budget <= 0:
        raise ValueError("max_voxels must be positive")
    voxel_path = output / "voxels.jsonl"
    terrain = Terrain(config["terrain"], crs, sources) if config.get("terrain") else None
    terrain_missing = 0
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
                    width = properties.get("width_m", properties.get("width"))
                    if width is None:
                        width = config.get("fallback_width_m", 1)
                        assumptions.append(f"width assumed {width} m")
                    width = float(width)
                    if not math.isfinite(width) or width <= 0:
                        raise ValueError(f"Invalid width on {fid}")
                    geometry = geometry.buffer(width / 2).intersection(area)
                base = float(properties.get("base_elevation_m", 0))
                elevated = properties.get("bridge") not in (None, "no", False) or properties.get("tunnel") not in (None, "no", False) or str(properties.get("layer", "0")) != "0"
                use_terrain = terrain is not None and "base_elevation_m" not in properties and not elevated
                if elevated and "base_elevation_m" not in properties:
                    issues.append({"feature": fid, "severity": "error", "reason": "elevated/tunnel feature requires explicit absolute base_elevation_m; layer is not a height"})
                    continue
                if "base_elevation_m" in properties and terrain and properties.get("vertical_datum") != config["terrain"]["vertical_datum"]:
                    raise ValueError(f"Feature {fid} vertical datum must match terrain")
                if "base_elevation_m" not in properties and not use_terrain:
                    assumptions.append("base elevation assumed 0 m; terrain unavailable")
                height = properties.get("height_m", properties.get("height"))
                if height is None:
                    height = config.get("fallback_heights_m", {}).get(kind, 1)
                    assumptions.append(f"height assumed {height} m; actual vertical geometry unknown")
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
                feature_start = count
                minx, miny, maxx, maxy = geometry.bounds
                for x in range(math.floor(minx/resolution), math.ceil(maxx/resolution)):
                    for z in range(math.floor(miny/resolution), math.ceil(maxy/resolution)):
                        scanned += 1
                        if scanned > scan_budget:
                            raise ValueError("Column scan budget exceeded")
                        if not geometry.covers(Point((x+.5)*resolution, (z+.5)*resolution)):
                            continue
                        cell_base = terrain.sample((x+.5)*resolution, (z+.5)*resolution) if use_terrain else base
                        if cell_base is None:
                            terrain_missing += 1
                            continue
                        for y in range(math.floor(cell_base/resolution), math.ceil((cell_base+height)/resolution)):
                            count += 1
                            if count > budget:
                                raise ValueError("Voxel budget exceeded; reduce area or increase voxel size")
                            stream.write(json.dumps({"x": x, "y": y, "z": z, "kind": kind, "feature": fid, "source": source_id, "elevation_source": config["terrain"]["source_id"] if use_terrain else source_id}) + "\n")
                if count == feature_start:
                    issues.append({"feature": fid, "severity": "error", "reason": "feature produced no voxel columns; check coverage or voxel resolution"})
                accepted.append({**feature, "geometry": mapping(geometry)})
            if terrain and config["terrain"].get("emit_surface", True):
                minx, minz, maxx, maxz = area.bounds
                for x in range(math.floor(minx/resolution), math.ceil(maxx/resolution)):
                    for z in range(math.floor(minz/resolution), math.ceil(maxz/resolution)):
                        scanned += 1
                        if scanned > scan_budget:
                            raise ValueError("Column scan budget exceeded")
                        px, pz = (x+.5)*resolution, (z+.5)*resolution
                        if not area.covers(Point(px, pz)):
                            continue
                        elevation = terrain.sample(px, pz)
                        if elevation is None:
                            terrain_missing += 1
                            continue
                        count += 1
                        if count > budget:
                            raise ValueError("Voxel budget exceeded during terrain generation")
                        stream.write(json.dumps({"x": x, "y": math.floor(elevation/resolution), "z": z, "kind": "terrain", "source": config["terrain"]["source_id"]}) + "\n")
    except Exception:
        voxel_path.unlink(missing_ok=True)
        raise
    finally:
        if terrain:
            terrain.close()
    if terrain_missing:
        issues.append({"severity": "error", "reason": "terrain coverage/nodata gaps", "missing_column_requests": terrain_missing})
    report = {"version": "3.1.0", "voxel_size_m": resolution, "crs": crs.to_wkt(), "axis": {"x": "east", "y": "up", "z": "north"}, "sources": list(sources.values()), "voxel_records": count, "features": len(accepted), "issues": issues,
              "limitations": ["Footprint extrusion; no mesh or LiDAR reconstruction", "Overlapping feature records require downstream composition", "No automatic planning drawing georeferencing", "Metric scale is approximate away from local projection origin"],
              "sha256": file_sha256(voxel_path)}
    report["column_checks"] = scanned
    report["terrain"] = terrain.report() if terrain else None
    (output / "quality-report.json").write_text(json.dumps(report, indent=2))
    (output / "features-local.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": accepted}))
    return report


def file_sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    from .pipeline import run_auto
    parser = argparse.ArgumentParser(description="Automatically fetch public data and build a 1 block/metre Bedrock world")
    area = parser.add_mutually_exclusive_group(required=True)
    area.add_argument("--location", help="Specific park name and country/address")
    area.add_argument("--bbox", help="west,south,east,north")
    parser.add_argument("--output", default="output")
    parser.add_argument("--strict", action="store_true", help="Fail after export if evidence quality checks fail")
    args = parser.parse_args()
    bounds = list(map(float, args.bbox.split(','))) if args.bbox else None
    report = run_auto(Path(args.output), location=args.location, bounds=bounds)
    if args.strict and report["issues"]:
        raise SystemExit("Strict accuracy gate failed; draft world and evidence retained in output")


if __name__ == "__main__":
    main()
