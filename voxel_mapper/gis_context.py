"""Metric GIS evidence fusion and aligned contextual ML inputs, not labels."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

from pyproj import CRS, Transformer
from shapely.geometry import box, mapping, shape
from shapely.ops import transform, unary_union
from shapely.strtree import STRtree
from shapely.errors import GEOSException

ROLES = {"building_footprint":"building", "water_polygon":"water",
         "woodland_polygon":"vegetation", "woodland_context":"vegetation",
         "habitat_context":"habitat", "watercourse_centerline":"watercourse",
         "heritage_location":"heritage", "heritage_designation":"heritage"}
KINDS = {"building":"building", "water":"water", "vegetation":"vegetation",
         "tree":"vegetation","woodland":"vegetation","canopy":"vegetation"}
EXACT_ROLES = {"building_footprint","water_polygon","woodland_polygon"}

def metric_crs(bounds):
    w,s,e,n = bounds
    if not all(math.isfinite(v) for v in bounds) or not (-180 <= w < e <= 180 and -90 < s < n < 90):
        raise ValueError("Invalid park bounds")
    return CRS.from_proj4(f"+proj=aeqd +lat_0={(s+n)/2} +lon_0={(w+e)/2} +datum=WGS84 +units=m")

def projected(feature, projector, area):
    try:
        g = shape(feature["geometry"])
        if g.is_empty or not g.is_valid:
            return None
        g = transform(projector.transform,g).intersection(area)
        return g if not g.is_empty and g.is_valid else None
    except (ValueError, TypeError, KeyError, GEOSException):
        return None

def import_polygons(config, bounds, *, root=Path(".")):
    """Read explicit open OS GeoJSON exports, never infer width from lines."""
    area = box(*bounds)
    features, sources, reports = [], [], []
    for item in config:
        role = item["role"]
        if role not in EXACT_ROLES:
            raise ValueError("Local import supports building/water/woodland polygons")
        sid = item["id"]
        if not sid or any(s["id"]==sid for s in sources):
            raise ValueError("Local GIS source IDs must be unique")
        if item.get("license") not in ("OGL-3.0","CC-BY-4.0","CC0-1.0","ODbL-1.0") or not item.get("url") or not item.get("attribution") or not item.get("lineage_family"):
            raise ValueError("Explicit open license, URL, attribution and lineage required")
        if item.get("crs")!="EPSG:4326":
            raise ValueError("Export local vectors as WGS84 GeoJSON first")
        path = root / item["path"]
        if path.stat().st_size > 128*1024*1024:
            raise ValueError("Local vector byte budget exceeded")
        raw = path.read_bytes()
        data = json.loads(raw)
        if data.get("type")!="FeatureCollection" or "crs" in data:
            raise ValueError("Expected RFC 7946 FeatureCollection")
        if len(data["features"])>100000:
            raise ValueError("Local vector feature budget exceeded")
        rejected, count = 0, 0
        for i,f in enumerate(data["features"]):
            try:
                g = shape(f["geometry"])
                if g.geom_type not in ("Polygon","MultiPolygon") or not g.is_valid or g.is_empty or not box(-180,-90,180,90).covers(g):
                    raise ValueError("Invalid WGS84 polygon")
                g = g.intersection(area)
                if g.is_empty or g.area==0:
                    continue
                if g.geom_type not in ("Polygon","MultiPolygon"):
                    raise ValueError("Non-polygon intersection")
            except (ValueError,TypeError,KeyError,GEOSException):
                rejected += 1
                continue
            features.append({"type":"Feature","id":f"{sid}/{i}","geometry":mapping(g),
                "properties":{**(f.get("properties") or {}),"source_id":sid,"gis_role":role,
                    "lineage_family":item["lineage_family"],"context_only":True}})
            count += 1
        sources.append({k:v for k,v in item.items() if k!="path"})
        reports.append({"source_id":sid,"status":"partial" if rejected else "available" if count else "no_intersections",
                        "accepted":count,"rejected_count":rejected,"sha256":hashlib.sha256(raw).hexdigest()})
    return features,sources,reports

def review_geometry(collection, features, bounds, *, min_gap_m2=4.0):
    """Report unmatched areas and offsets without editing higher-detail geometry."""
    if not math.isfinite(min_gap_m2) or min_gap_m2<=0:
        raise ValueError("min_gap_m2 must be positive")
    crs = metric_crs(bounds)
    tf = Transformer.from_crs(4326,crs,always_xy=True)
    inv = Transformer.from_crs(crs,4326,always_xy=True)
    area = transform(tf.transform,box(*bounds))
    groups = defaultdict(list)
    for f in collection["features"]:
        p = f.get("properties",{})
        kind = KINDS.get(p.get("kind"))
        if not kind or p.get("draft_geometry") or p.get("context_only"):
            continue
        g = projected(f,tf,area)
        if g is not None and g.area>0 and g.geom_type in ("Polygon","MultiPolygon"):
            groups[kind].append((f,g))
    trees = {k:STRtree([g for _,g in items]) for k,items in groups.items()}
    records, candidates = [], []
    for f in features:
        p = f["properties"]
        role = p.get("gis_role")
        if role not in EXACT_ROLES:
            continue
        kind = ROLES[role]
        g = projected(f,tf,area)
        if g is None or g.area<=0 or g.geom_type not in ("Polygon","MultiPolygon"):
            continue
        items = groups[kind]
        hits = trees[kind].query(g,predicate="intersects") if kind in trees else []
        matches = [(items[int(i)][0],items[int(i)][1]) for i in hits if g.intersection(items[int(i)][1]).area>0]
        covered = unary_union([x for _,x in matches]) if matches else None
        overlap = g.intersection(covered).area if covered is not None else 0
        gap = g.difference(covered) if covered is not None else g
        record = {"source_feature_id":f["id"],"kind":kind,"source_id":p.get("source_id"),
                  "lineage_family":p.get("lineage_family"),"source_area_m2":round(g.area,3),
                  "covered_fraction":round(overlap/g.area,4),"unmatched_area_m2":round(gap.area,3),
                  "matches":[{"feature_id":other.get("id"),"iou":round(g.intersection(h).area/g.union(h).area,4),
                              "centroid_offset_m":round(g.centroid.distance(h.centroid),3),
                              "boundary_hausdorff_m":round(g.boundary.hausdorff_distance(h.boundary),3)}
                             for other,h in matches]}
        records.append(record)
        if gap.area>=min_gap_m2:
            parts = [gap] if gap.geom_type=="Polygon" else list(getattr(gap,"geoms",[]))
            for i,part in enumerate(parts):
                if part.geom_type!="Polygon" or part.area<min_gap_m2:
                    continue
                candidates.append({"type":"Feature","id":f"{f['id']}/gap/{i}",
                    "geometry":mapping(transform(inv.transform,part)),
                    "properties":{"source_id":p.get("source_id"),"source_feature_id":f["id"],
                                  "kind":kind,"area_m2":round(part.area,3),"review_only":True,
                                  "reason":"GIS polygon not covered by existing non-draft polygons"}})
    return {"comparison_count":len(records),"candidate_count":len(candidates),
            "comparisons":records,"policy":"Area and distance measure agreement, not absolute accuracy; gaps require independent review."}, {"type":"FeatureCollection","features":candidates}

def write_context_grid(bounds, features, layers, output, *, landcover_report=None, cell_m=5.0):
    """Write per-source contextual channels in the same CRS/origin as the mapper.

    1=mapped presence, 0=no mapped feature (not verified absence), 255=unknown.
    Sentinel codes retain their original semantics and nominal 10 m resolution.
    """
    import numpy as np
    import rasterio
    from rasterio.features import rasterize
    from rasterio.transform import from_origin
    from rasterio.warp import reproject, Resampling
    if not math.isfinite(cell_m) or not 1<=cell_m<=50:
        raise ValueError("context cell size must be 1..50 m")
    crs = metric_crs(bounds)
    tf = Transformer.from_crs(4326,crs,always_xy=True)
    area = transform(tf.transform,box(*bounds))
    x0,y0,x1,y1 = area.bounds
    x0,y0 = math.floor(x0/cell_m)*cell_m,math.floor(y0/cell_m)*cell_m
    x1,y1 = math.ceil(x1/cell_m)*cell_m,math.ceil(y1/cell_m)*cell_m
    width,height = round((x1-x0)/cell_m),round((y1-y0)/cell_m)
    if width*height>4_000_000 or len(layers)>32 or width*height*(len(layers)+1)>64_000_000:
        raise ValueError("Context grid memory budget exceeded; split AOI")
    affine = from_origin(x0,y1,cell_m,cell_m)
    dims = (height,width)
    inside = rasterize([(area,1)],out_shape=dims,transform=affine,dtype="uint8").astype(bool)
    by_source = defaultdict(list)
    for f in features:
        g = projected(f,tf,area)
        if g is not None:
            by_source[f["properties"]["source_id"]].append(g)
    channels, metadata = [], []
    for layer in layers:
        sid = layer["source_id"]
        geoms = by_source[sid]
        status = layer["status"]
        arr = np.full(dims,255,dtype=np.uint8)
        if status in ("available","no_intersections"):
            arr[inside]=0
        if status in ("available","partial") and geoms:
            mask = rasterize([(g,1) for g in geoms],out_shape=dims,transform=affine,dtype="uint8",all_touched=True)
            arr[(mask==1)&inside]=1
        channels.append(arr)
        metadata.append({"source_id":sid,"status":status,"encoding":{"0":"not mapped","1":"mapped","255":"unknown"},
                         "all_touched":True,"mapped_cells":int((arr==1).sum())})
    if landcover_report and landcover_report.get("status")=="available":
        arr = np.full(dims,255,dtype=np.uint8)
        path = output / landcover_report["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest()!=landcover_report["sha256"]:
            raise ValueError("Land-cover evidence checksum mismatch")
        with rasterio.open(path) as src:
            reproject(source=rasterio.band(src,1),destination=arr,src_transform=src.transform,src_crs=src.crs,
                      src_nodata=src.nodata,dst_transform=affine,dst_crs=crs,dst_nodata=255,
                      resampling=Resampling.nearest)
        arr[(~inside)|(arr==0)|(arr==10)]=255
        channels.append(arr)
        metadata.append({"source_id":"sentinel2-landcover","year":landcover_report["year"],
                         "nominal_resolution_m":10,"encoding":landcover_report["classes"],"unknown":255})
    output.mkdir(parents=True,exist_ok=True)
    path = output/"gis-context.npz"
    stack = np.stack(channels) if channels else np.empty((0,*dims),dtype=np.uint8)
    np.savez_compressed(path,channels=stack,inside_aoi=inside)
    report = {"schema":"voxel-gis-context-v1","path":path.name,"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
              "crs":crs.to_wkt(),"transform":list(affine)[:6],"shape":list(stack.shape),
              "cell_size_m":cell_m,"channels":metadata,"axis":"rows north to south; columns west to east",
              "policy":"Context input only; never a material target or evidence of absence. Resampling adds no source detail."}
    (output/"gis-context.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    return report
