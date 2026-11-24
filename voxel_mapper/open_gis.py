"""Bounded open ArcGIS feature-layer acquisition and mapper evidence fusion."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math

import requests
from shapely.geometry import box, shape, mapping
from shapely.strtree import STRtree
from shapely.errors import GEOSException

OS = "https://services.arcgis.com/qHLhLQrcvEnxjtPr/arcgis/rest/services/"
HE = "https://services-eu1.arcgis.com/ZOdPfBS3aqqDYPUQ/arcgis/rest/services/National_Heritage_List_for_England_NHLE_v02_VIEW/FeatureServer/"
OGL = "OGL-3.0"

def source(id, url, role, family, attribution, metadata):
    return dict(id=id, url=url, role=role, lineage_family=family,
                attribution=attribution, license=OGL, metadata_url=metadata,
                evidence_type="gis")

SOURCES = (
    source("os-openmap-buildings", OS+"OS_OpenMap_Local_Buildings/FeatureServer/1",
           "building_footprint", "ordnance-survey", "Contains OS data © Crown copyright and database right",
           "https://www.ordnancesurvey.co.uk/products/open-data"),
    source("os-open-rivers", OS+"OS_OpenRivers/FeatureServer/0", "watercourse_centerline",
           "ordnance-survey", "Contains OS data © Crown copyright and database right",
           "https://www.ordnancesurvey.co.uk/products/os-open-rivers"),
    source("living-england-4", "https://services.arcgis.com/JJzESW51TqeY9uat/arcgis/rest/services/Living_England_Habitat_Map_Phase4/FeatureServer/0",
           "habitat_context", "natural-england-satellite-derived", "Contains data supplied by ©Natural England ©Centre for Ecology and Hydrology",
           "https://naturalengland-defra.opendata.arcgis.com/datasets/living-england-habitat-map-phase-4/"),
    source("nfi-gb-2024", "https://services2.arcgis.com/mHXjwgl3OARRqqD4/ArcGIS/rest/services/National_Forest_Inventory_GB_2024/FeatureServer/0",
           "woodland_context", "forestry-commission-derived", "Contains Forestry Commission information licensed under the Open Government Licence v3.0; © Forestry Commission copyright and/or database right 2025",
           "https://environment.data.gov.uk/dataset/0dbabff6-588e-44b3-a316-6353c4e47025"),
    source("nhle-points", HE+"0", "heritage_location", "historic-england-os",
           "© Crown Copyright; contains Ordnance Survey data © Crown copyright and database right",
           "https://historicengland.org.uk/listing/the-list/data-downloads/"),
    source("nhle-polygons", HE+"3", "heritage_designation", "historic-england-os",
           "© Crown Copyright; contains Ordnance Survey data © Crown copyright and database right",
           "https://historicengland.org.uk/listing/the-list/data-downloads/"),
    source("nhle-gardens", HE+"7", "heritage_designation", "historic-england-os",
           "© Crown Copyright; contains Ordnance Survey data © Crown copyright and database right",
           "https://historicengland.org.uk/listing/the-list/data-downloads/"),
)

def _json(get, url, params):
    response = get(url, params=params, timeout=(10, 45))
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict) or "error" in result:
        raise ValueError(f"ArcGIS query error: {str(result)[:300]}")
    return result

def acquire(layer, bounds, *, get=requests.get, max_features=10000):
    """Query all matching object IDs in bounded batches; never accept truncation."""
    west, south, east, north = bounds
    if not all(math.isfinite(v) for v in bounds) or not (-180 <= west < east <= 180 and -90 < south < north < 90):
        raise ValueError("Invalid WGS84 bounds")
    url = layer["url"]
    meta = _json(get, url, {"f":"json"})
    if "geojson" not in str(meta.get("supportedQueryFormats","")).lower():
        raise ValueError("Layer does not advertise GeoJSON support")
    oid = meta.get("objectIdField") or meta.get("objectIdFieldName")
    if not oid:
        raise ValueError("Layer has no object ID field")
    common = {"where":"1=1","geometry":",".join(map(str,bounds)),
              "geometryType":"esriGeometryEnvelope","inSR":4326,
              "spatialRel":"esriSpatialRelIntersects"}
    ids_response = _json(get, url+"/query", {**common,"returnIdsOnly":"true","f":"json"})
    ids = ids_response.get("objectIds")
    if ids is None and "objectIds" in ids_response:
        ids = []
    if not isinstance(ids,list) or ids_response.get("exceededTransferLimit"):
        raise ValueError("Missing or truncated object ID list")
    ids = sorted(set(ids))
    if len(ids) > max_features:
        raise ValueError("Feature budget exceeded; split AOI")
    limit = max(1, min(int(meta.get("maxRecordCount") or 100), 100))
    area = box(*bounds)
    features, rejected, outside = [], [], 0
    for start in range(0,len(ids),limit):
        batch = ids[start:start+limit]
        result = _json(get, url+"/query", {"objectIds":",".join(map(str,batch)),
            "outFields":"*","returnGeometry":"true","returnZ":"false","returnM":"false",
            "outSR":4326,"f":"geojson"})
        if result.get("type") != "FeatureCollection" or result.get("exceededTransferLimit"):
            raise ValueError("Invalid or truncated feature batch")
        returned = set()
        for f in result["features"]:
            props = f.get("properties") or {}
            ident = props.get(oid, f.get("id"))
            if ident not in batch or ident in returned:
                raise ValueError("Unexpected or repeated object ID")
            returned.add(ident)
            try:
                geom = shape(f["geometry"])
                if geom.is_empty or not geom.is_valid:
                    raise ValueError("Invalid source geometry")
                family = geom.geom_type.removeprefix("Multi")
                geom = geom.intersection(area)
                if geom.is_empty or geom.geom_type.removeprefix("Multi") != family:
                    outside += 1
                    continue
            except (ValueError, TypeError, KeyError, GEOSException) as exc:
                rejected.append({"object_id":ident,"reason":str(exc)})
                continue
            features.append({"type":"Feature","id":f'{layer["id"]}/{ident}',
                "geometry":mapping(geom),"properties":{**props,
                    "source_id":layer["id"],"gis_role":layer["role"],
                    "lineage_family":layer["lineage_family"],
                    "context_only":True}})
        if returned != set(batch):
            raise ValueError("Incomplete batch; source changed or transfer was truncated")
    return features, {"source_id":layer["id"],"status":"partial" if rejected else "available" if features else "no_intersections",
        "matched_ids":len(ids),"accepted":len(features),"rejected":rejected,
        "outside_or_touch_only":outside,"layer_name":meta.get("name"),
        "retrieved_at":datetime.now(timezone.utc).isoformat(),
        "coverage_note":"AOI intersection only; completeness and accuracy not certified"}

def collect(bounds, settings, output, *, get=requests.get):
    """Acquire only the reviewed free registry, with isolated source failures."""
    requested = settings.get("sources", [s["id"] for s in SOURCES])
    if not isinstance(requested,list) or set(requested)-{s["id"] for s in SOURCES}:
        raise ValueError("Unknown GIS source in configuration")
    layers = [s for s in SOURCES if s["id"] in requested]
    def run(layer):
        try:
            return acquire(layer,bounds,get=get,max_features=int(settings.get("max_features_per_source",10000)))
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            return [], {"source_id":layer["id"],"status":"unavailable","error":str(exc)[:500]}
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(run,layers))
    features = [f for fs,_ in results for f in fs]
    report = {"schema":"voxel-open-gis-v1","bbox":bounds,"sources":layers,
              "layers":[r for _,r in results],"feature_count":len(features),
              "policy":"Context is not a measured block/material label; overlapping lineage is not independent evidence."}
    output.mkdir(parents=True,exist_ok=True)
    (output/"gis-evidence.geojson").write_text(json.dumps({"type":"FeatureCollection","features":features}),encoding="utf-8")
    (output/"gis-report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    return features, report

def fuse(collection, features, *, promote_missing=False):
    """Annotate footprint overlaps and optionally add isolated draft footprints.

    No elevations are inferred. Context layers never enter the voxel extruder.
    A lack of overlap is a review candidate, not proof a building is missing.
    """
    original = collection["features"]
    indexed = []
    for f in original:
        if f.get("properties",{}).get("kind") != "building":
            continue
        try:
            g = shape(f["geometry"])
        except (ValueError, TypeError, KeyError, GEOSException):
            continue
        if g.is_valid and not g.is_empty and g.area > 0:
            indexed.append((f,g))
    tree = STRtree([g for _,g in indexed])
    candidates, added = [], []
    for f in features:
        if f["properties"]["gis_role"] != "building_footprint":
            continue
        g = shape(f["geometry"])
        if g.area <= 0:
            continue
        hits = tree.query(g,predicate="intersects")
        overlap = False
        for idx in hits:
            base, other = indexed[int(idx)]
            inter = g.intersection(other).area
            if inter <= 0:
                continue
            overlap = True
            base.setdefault("properties",{}).setdefault("gis_footprint_matches",[]).append(
                {"id":f["id"],"iou":round(inter/g.union(other).area,4),
                 "lineage_family":f["properties"]["lineage_family"]})
        if not overlap:
            candidates.append(f["id"])
            if promote_missing:
                added.append({**f,"properties":{**f["properties"],"kind":"building",
                    "context_only":False,"draft_geometry":True}})
    original.extend(added)
    return {"building_review_candidates":candidates,"draft_footprints_added":len(added),
            "policy":"IoU is agreement, not surveyed accuracy. Original geometry retained."}
