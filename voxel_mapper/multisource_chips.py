"""Align GIS and LiDAR context to reviewed aerial chips; never generate labels."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile

import numpy as np

VECTOR_ROLES = ("building","water","woodland","habitat","heritage","watercourse")
LAND_CLASSES = (1,2,4,5,7,8,9,11)
GROUPS = tuple((name,2) for name in VECTOR_ROLES) + (("landcover",9),("height",2),("intensity",2))
CHANNELS = tuple(n for role in VECTOR_ROLES for n in (role+"_mapped",role+"_known")) + tuple("landcover_"+str(k) for k in LAND_CLASSES) + ("landcover_known","height_0_60m","height_known","intensity_0_65535","intensity_known")
SOURCE_ROLES = {"os-openmap-buildings":"building","os-open-rivers":"watercourse",
                "living-england-4":"habitat","nfi-gb-2024":"woodland",
                "nhle-points":"heritage","nhle-polygons":"heritage","nhle-gardens":"heritage",
                "os-water":"water","os-woodland":"woodland"}

def empty(height,width):
    return np.zeros((height,width,len(CHANNELS)),dtype=np.float32)

def decode(blob, height, width):
    """Fixed channel schema; reject missing masks, non-finite values and bad shapes."""
    with np.load(io.BytesIO(blob),allow_pickle=False) as z:
        if tuple(z["channel_names"].tolist())!=CHANNELS:
            raise ValueError("Context channel schema mismatch")
        data=z["context"]
    if data.shape!=(height,width,len(CHANNELS)) or data.dtype!=np.float32:
        raise ValueError("Context chip shape or dtype mismatch")
    if not np.isfinite(data).all() or np.any((data<0)|(data>1)):
        raise ValueError("Context values must be finite in [0,1]")
    offset=0
    for _,size in GROUPS:
        group=data[:,:,offset:offset+size]
        known=group[:,:,-1]
        if not np.all((known==0)|(known==1)) or np.any(group[:,:,:-1]>known[:,:,None]):
            raise ValueError("Invalid context validity mask")
        if offset<12 and not np.all((group[:,:,0]==0)|(group[:,:,0]==1)):
            raise ValueError("Vector presence must be binary")
        if offset==12 and (not np.all((group[:,:,:-1]==0)|(group[:,:,:-1]==1)) or not np.all(group[:,:,:-1].sum(2)==known)):
            raise ValueError("Land-cover classes must be one-hot where known")
        offset+=size
    return data

def drop_groups(data, rng, probability):
    """Hide whole modalities, including validity, to train for outages."""
    result=data.copy()
    offset=0
    for _,size in GROUPS:
        if rng.random()<probability:
            result[:,:,offset:offset+size]=0
        offset+=size
    return result

def _grid(spec, height, width):
    from rasterio.crs import CRS
    from affine import Affine
    values=spec["transform"]
    if len(values)!=6 or not all(math.isfinite(float(v)) for v in values):
        raise ValueError("Chip transform must be six affine coefficients")
    affine=Affine(*values)
    if abs(affine.determinant)<1e-15 or not spec.get("crs"):
        raise ValueError("Invalid chip georeferencing")
    if height*width>4_000_000 or min(height,width)<=0:
        raise ValueError("Chip pixel budget exceeded")
    return CRS.from_user_input(spec["crs"]),affine

def _warp(values, src_crs, src_transform, dst_crs, dst_transform, dims, nodata):
    from rasterio.warp import reproject, Resampling
    dest=np.full(dims,nodata,dtype=values.dtype)
    reproject(values,dest,src_crs=src_crs,src_transform=src_transform,
              dst_crs=dst_crs,dst_transform=dst_transform,
              src_nodata=nodata,dst_nodata=nodata,resampling=Resampling.nearest)
    return dest

def _read_raster(item, root, crs, affine, dims):
    import rasterio
    if not item.get("source_id") or not item.get("license") or not item.get("observed_date"):
        raise ValueError("LiDAR source ID, license and observation date required")
    with rasterio.open(root/item["path"]) as src:
        if src.count!=1 or src.crs is None or src.nodata is None:
            raise ValueError("LiDAR raster must have one band, CRS and explicit nodata")
        if src.width*src.height>16_000_000:
            raise ValueError("LiDAR raster too large; crop to park first")
        values=src.read(1,masked=True).astype(np.float32).filled(np.nan)
        values[~np.isfinite(values)]=np.nan
        return _warp(values,src.crs,src.transform,crs,affine,dims,np.nan)

def build_chip(spec, height, width, catalog, root):
    """Use supplied reviewed image georeferencing; no image matching or guessed alignment."""
    from affine import Affine
    from rasterio.crs import CRS
    crs,affine=_grid(spec,height,width)
    dims=(height,width)
    result=empty(*dims)
    provenance=[]
    context=catalog.get("gis")
    if context:
        report_path=root/context
        report=json.loads(report_path.read_text())
        if report.get("schema")!="voxel-gis-context-v1":
            raise ValueError("Unknown GIS grid schema")
        path=report_path.parent/report["path"]
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=report["sha256"]:
            raise ValueError("GIS context checksum mismatch")
        with np.load(io.BytesIO(raw),allow_pickle=False) as z:
            data=z["channels"]
        if list(data.shape)!=report["shape"] or data.dtype!=np.uint8 or len(report["channels"])!=data.shape[0]:
            raise ValueError("GIS context shape mismatch")
        roles={**SOURCE_ROLES,**catalog.get("source_roles",{})}
        for i,meta in enumerate(report["channels"]):
            sid=meta["source_id"]
            role=roles.get(sid)
            if sid!="sentinel2-landcover" and role not in VECTOR_ROLES:
                continue
            a=_warp(data[i],CRS.from_wkt(report["crs"]),Affine(*report["transform"]),crs,affine,dims,255)
            if sid=="sentinel2-landcover":
                for j,k in enumerate(LAND_CLASSES):
                    result[:,:,12+j]=(a==k)
                result[:,:,20]=np.isin(a,LAND_CLASSES)
            else:
                j=2*VECTOR_ROLES.index(role)
                # Union of mapped features, not independent votes.
                result[:,:,j]=np.maximum(result[:,:,j],a==1)
                result[:,:,j+1]=np.maximum(result[:,:,j+1],np.isin(a,(0,1)))
            provenance.append({"source_id":sid,"role":role or "landcover","grid_sha256":report["sha256"]})
    dtm,dsm=catalog.get("dtm"),catalog.get("dsm")
    if dtm and dsm:
        if not dtm.get("vertical_datum") or dtm["vertical_datum"]!=dsm.get("vertical_datum") or str(dtm["vertical_datum"]).lower()=="unknown":
            raise ValueError("Height requires matching known vertical datums")
        if dtm.get("vertical_units")!="m" or dsm.get("vertical_units")!="m" or dtm.get("observed_date")!=dsm.get("observed_date"):
            raise ValueError("Height requires metre units and matching capture dates")
        ground=_read_raster(dtm,root,crs,affine,dims)
        surface=_read_raster(dsm,root,crs,affine,dims)
        diff=surface-ground
        valid=np.isfinite(diff)&(diff>=0)
        result[:,:,21]=np.where(valid,np.clip(diff,0,60)/60,0)
        result[:,:,22]=valid
        provenance.extend([dtm,dsm])
    intensity=catalog.get("intensity")
    if intensity:
        if intensity.get("encoding")!="raw_las_uint16":
            raise ValueError("Intensity encoding must declare raw LAS uint16 scale")
        values=_read_raster(intensity,root,crs,affine,dims)
        valid=np.isfinite(values)&(values>=0)&(values<=65535)
        result[:,:,23]=np.where(valid,values/65535,0)
        result[:,:,24]=valid
        provenance.append(intensity)
    return result,provenance

def pack(dataset, catalog_path, output):
    from PIL import Image
    if dataset.resolve()==output.resolve():
        raise ValueError("Use a new output ZIP")
    catalog=json.loads(catalog_path.read_text())
    root=catalog_path.resolve().parent
    output.parent.mkdir(parents=True,exist_ok=True)
    temp=output.with_suffix(output.suffix+".tmp")
    counts={"aligned":0,"missing_georeference":0,"no_context":0}
    try:
        with zipfile.ZipFile(dataset) as src, zipfile.ZipFile(temp,"w",compression=zipfile.ZIP_DEFLATED) as dst:
            manifest=json.loads(src.read("manifest.json"))
            records=manifest.get("samples")
            if not isinstance(records,list):
                raise ValueError("Context packing requires manifest.samples")
            park_default=manifest.get("park_id",manifest.get("park","unknown_park"))
            if isinstance(park_default,dict): park_default=park_default.get("id")
            for item in src.infolist():
                if item.filename!="manifest.json" and not item.filename.startswith("gis-context/"):
                    dst.writestr(item,src.read(item))
            for i,record in enumerate(records):
                record.pop("context",None)
                record.pop("context_provenance",None)
                georef=record.get("georef")
                if not georef:
                    counts["missing_georeference"]+=1
                    continue
                park=record.get("park_id") or park_default
                config=catalog.get("parks",{}).get(park)
                if not config:
                    counts["no_context"]+=1
                    continue
                with Image.open(io.BytesIO(src.read(record["image"]))) as image:
                    width,height=image.size
                data,provenance=build_chip(georef,height,width,config,root)
                if not np.any(data):
                    counts["no_context"]+=1
                    continue
                blob=io.BytesIO()
                np.savez_compressed(blob,context=data,channel_names=np.asarray(CHANNELS))
                name=f"gis-context/{i}.npz"
                dst.writestr(name,blob.getvalue())
                record["context"]=name
                record["context_provenance"]=provenance
                counts["aligned"]+=1
            manifest["context_schema"]="voxel-multisource-v1"
            manifest["context_channels"]=CHANNELS
            manifest["context_report"]=counts
            dst.writestr("manifest.json",json.dumps(manifest,indent=2))
        temp.replace(output)
    finally:
        temp.unlink(missing_ok=True)
    return counts

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset",type=Path,required=True)
    p.add_argument("--catalog",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    print(json.dumps(pack(a.dataset,a.catalog,a.output),indent=2))

if __name__=="__main__":
    main()
