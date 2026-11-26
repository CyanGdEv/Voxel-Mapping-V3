"""Acquire global 10 m land-cover context; never create fine material labels."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import requests
from pyproj import Transformer

URL = "https://ic.imagery1.arcgis.com/arcgis/rest/services/Sentinel2_10m_LandCover/ImageServer"
SOURCE = {"id":"sentinel2-landcover","url":URL,"license":"CC-BY-4.0",
          "attribution":"Impact Observatory, Microsoft, Esri; derived from Copernicus Sentinel-2",
          "metadata_url":"https://livingatlas.arcgis.com/landcover/",
          "lineage_family":"sentinel2-derived","role":"coarse_landcover_context"}
CLASSES = {1:"water",2:"trees",4:"flooded_vegetation",5:"crops",
           7:"built_area",8:"bare_ground",9:"snow_ice",10:"clouds",11:"rangeland"}

def request_grid(bounds):
    west,south,east,north = bounds
    if not all(math.isfinite(v) for v in bounds) or not (-180 <= west < east <= 180 and -80 <= south < north <= 84):
        raise ValueError("Invalid or unsupported land-cover bounds")
    tf = Transformer.from_crs(4326,3857,always_xy=True)
    x0,y0 = tf.transform(west,south)
    x1,y1 = tf.transform(east,north)
    grid = (math.floor(x0/10)*10,math.floor(y0/10)*10,
            math.ceil(x1/10)*10,math.ceil(y1/10)*10)
    width,height = round((grid[2]-grid[0])/10),round((grid[3]-grid[1])/10)
    if width > 4000 or height > 4000 or width*height > 2_000_000:
        raise ValueError("Land-cover pixel budget exceeded; split AOI")
    return grid,width,height

def acquire(bounds, year, output, *, get=requests.get):
    """Export native-scale categorical values, pinned to a particular year."""
    import numpy as np
    import rasterio
    from rasterio.io import MemoryFile
    if type(year) is not int or not 2017 <= year <= 2025:
        raise ValueError("Select a published land-cover year between 2017 and 2025")
    grid,width,height = request_grid(bounds)
    params = {"bbox":",".join(map(str,grid)),"bboxSR":3857,"imageSR":3857,
              "size":f"{width},{height}","format":"tiff","pixelType":"U8",
              "interpolation":"RSP_NearestNeighbor","adjustAspectRatio":"false",
              "mosaicRule":json.dumps({"mosaicMethod":"esriMosaicAttribute",
                    "where":f"Year = {year}","sortField":"Year","sortValue":str(year),
                    "mosaicOperation":"MT_FIRST"}),
              "renderingRule":json.dumps({"rasterFunction":"None"}),
              "f":"image"}
    response = get(URL+"/exportImage",params=params,timeout=(10,90),stream=True)
    try:
        response.raise_for_status()
        data = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            data.extend(chunk)
            if len(data)>32*1024*1024:
                raise ValueError("Land-cover response exceeded byte budget")
    finally:
        response.close()
    if bytes(data[:4]) not in (b"II*\x00",b"MM\x00*"):
        raise ValueError("Expected raw TIFF; service may have returned an error or rendered image")
    with MemoryFile(bytes(data)) as mem, mem.open() as src:
        if src.count != 1 or src.dtypes[0] != "uint8" or src.crs != rasterio.crs.CRS.from_epsg(3857):
            raise ValueError("Land-cover TIFF is not the expected single-band categorical raster")
        if (src.width,src.height)!=(width,height) or any(abs(a-b)>0.1 for a,b in zip(src.bounds,grid)):
            raise ValueError("Land-cover TIFF grid does not match the request")
        if abs(src.transform.b)>1e-8 or abs(src.transform.d)>1e-8 or abs(src.transform.a-10)>0.01 or abs(src.transform.e+10)>0.01:
            raise ValueError("Unexpected land-cover transform")
        values = src.read(1,masked=True)
        unique, counts = np.unique(values.compressed(),return_counts=True)
        histogram = {int(k):int(v) for k,v in zip(unique,counts)}
        unknown = set(histogram)-set(CLASSES)-{0,255}
        if unknown:
            raise ValueError(f"Unexpected land-cover codes: {sorted(unknown)}")
        valid = sum(histogram.get(k,0) for k in CLASSES if k!=10)
        if not valid:
            raise ValueError("No usable land-cover pixels in AOI")
        masked = int(np.ma.count_masked(values))
    output.mkdir(parents=True,exist_ok=True)
    path = output/f"sentinel2-landcover-{year}.tif"
    path.write_bytes(data)
    return {"status":"available","source":SOURCE,"path":path.name,"year":year,
            "request":params,"retrieved_at":datetime.now(timezone.utc).isoformat(),
            "crs":"EPSG:3857","grid_bounds":grid,"shape":[height,width],
            "sha256":hashlib.sha256(data).hexdigest(),
            "nominal_product_resolution_m":10,"grid_pixel_size_projected_m":10,
            "classes":CLASSES,"class_counts":histogram,
            "usable_fraction":valid/(width*height),"masked_pixels":masked,
            "policy":"Coarse contextual evidence only; rangeland is not verified lawn, built area is not paving, and no class is an individual block label."}

def collect(bounds, settings, output):
    year = settings.get("year",2025)
    try:
        result = acquire(bounds,year,output)
    except (ImportError, requests.RequestException, ValueError, OSError, RuntimeError) as exc:
        result = {"status":"unavailable","source":SOURCE,"year":year,"error":str(exc)[:500]}
    output.mkdir(parents=True,exist_ok=True)
    (output/"landcover-report.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    return result
