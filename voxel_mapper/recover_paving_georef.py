"""Register rotated paving chips against an exact georeferenced reference crop."""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image

def rotation_to_original(k,w,h):
    from affine import Affine
    return (Affine.identity(),Affine(0,-1,w,1,0,0),
            Affine(-1,0,w,0,-1,h),Affine(0,1,0,-1,0,h))[k]

def recover(dataset, expansion, reference, output, *, west,north):
    """Use a proposed integer BNG crop origin only if all RGB pixels agree."""
    from affine import Affine
    from rasterio.io import MemoryFile
    from rasterio.windows import Window
    if output.resolve() in {p.resolve() for p in (dataset,expansion,reference)}:
        raise ValueError("Use a distinct output archive")
    if type(west) is not int or type(north) is not int:
        raise ValueError("Reference crop origin must use integer BNG metres")
    with zipfile.ZipFile(expansion) as z:
        raw=z.read("paving_detail/full_aerial_crop.png")
        crop=np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"))
        rows=list(csv.DictReader(io.StringIO(z.read("paving_detail/samples.csv").decode("utf-8-sig"))))
    index={r["sample_id"]:r for r in rows}
    if len(index)!=len(rows):
        raise ValueError("Duplicate paving sample IDs")
    h,w=crop.shape[:2]
    mosaic=np.zeros_like(crop)
    known=np.zeros((h,w),dtype=bool)
    with zipfile.ZipFile(reference) as z:
        for name in z.namelist():
            if not name.startswith("data/") or not name.endswith("/rgb.tif"): continue
            with MemoryFile(z.read(name)) as mem,mem.open() as src:
                t=src.transform
                if src.crs is None or src.crs.to_epsg()!=27700 or src.count!=3 or src.dtypes!=("uint8",)*3 or (t.a,t.b,t.d,t.e)!=(1,0,0,-1) or not float(t.c).is_integer() or not float(t.f).is_integer():
                    raise ValueError("Expected aligned 1 m EPSG:27700 RGB reference tiles")
                x,y=int(t.c)-west,north-int(t.f)
                x0,y0,x1,y1=max(x,0),max(y,0),min(x+src.width,w),min(y+src.height,h)
                if x0>=x1 or y0>=y1: continue
                part=src.read(window=Window(x0-x,y0-y,x1-x0,y1-y0)).transpose(1,2,0)
                target=mosaic[y0:y1,x0:x1]; old=known[y0:y1,x0:x1]
                if np.any(old) and not np.array_equal(target[old],part[old]):
                    raise ValueError("Conflicting overlapping reference tiles")
                target[:]=part
                old[:]=True
    if not np.all(known) or not np.array_equal(mosaic,crop):
        raise ValueError("Proposed crop fails exact RGB reference match")
    with reference.open("rb") as stream:
        ref_hash=hashlib.file_digest(stream,"sha256").hexdigest()
    crop_hash=hashlib.sha256(raw).hexdigest()
    base=Affine(1,0,west,0,-1,north)
    counts={"verified":0,"unmatched":0,"labelled_verified":0,"labelled_pixels_verified":0}
    output.parent.mkdir(parents=True,exist_ok=True)
    tmp=output.with_suffix(output.suffix+".tmp")
    try:
        with zipfile.ZipFile(dataset) as inp,zipfile.ZipFile(tmp,"w",compression=zipfile.ZIP_DEFLATED) as out:
            manifest=json.loads(inp.read("manifest.json"))
            manifest["park_id"]="alton_towers"
            seen=set()
            for record in manifest["samples"]:
                sid=record["sample_id"]
                if sid in seen: raise ValueError("Duplicate sample IDs")
                seen.add(sid)
                record["park_id"]="alton_towers"
                for field in ("georef","georef_provenance","context","context_provenance"):
                    record.pop(field,None)
                if record.get("source_label_scheme")!="mutiny_bay_paving_v1":
                    counts["unmatched"]+=1
                    continue
                row=index[sid]
                x,y,sw,sh=(int(row[key]) for key in ("x_px","y_px","width_px","height_px"))
                if min(x,y)<0 or min(sw,sh)<=0 or x+sw>w or y+sh>h:
                    raise ValueError("Paving chip window outside source crop")
                k={"r0":0,"r90":1,"r180":2,"r270":3}[row["augmentation"]]
                with Image.open(io.BytesIO(inp.read(record["image"]))) as img:
                    rgb=np.asarray(img.convert("RGB"))
                with Image.open(io.BytesIO(inp.read(record["labels"]))) as img:
                    labels=np.asarray(img.convert("L"))
                if not np.array_equal(rgb,np.rot90(crop[y:y+sh,x:x+sw],k)) or labels.shape!=rgb.shape[:2]:
                    raise ValueError("Paving sample fails exact rotated RGB match: "+sid)
                affine=base*Affine.translation(x,y)*rotation_to_original(k,sw,sh)
                record["georef"]={"crs":"EPSG:27700","transform":list(affine)[:6]}
                record["georef_provenance"]={"method":"exact_rgb_crop_and_rotation_match",
                    "source_archive_sha256":ref_hash,"source_crop_sha256":crop_hash,
                    "source_crop_origin_m":[west,north],"source_pixel_window":[x,y,sw,sh],"rotation_ccw_degrees":90*k}
                record["split_group"]="Mutiny_Bay_single_aerial_crop"
                n=int(np.count_nonzero(labels!=255))
                counts["verified"]+=1
                counts["labelled_verified"]+=int(n>0)
                counts["labelled_pixels_verified"]+=n
            for info in inp.infolist():
                if info.filename!="manifest.json" and not info.filename.startswith("gis-context/"):
                    out.writestr(info,inp.read(info))
            for field in ("context_schema","context_channels","context_report"):
                manifest.pop(field,None)
            report={**counts,"source_crs":"EPSG:27700","source_archive_sha256":ref_hash,
                    "source_crop_sha256":crop_hash,"policy":"Source-grid registration, not independent survey accuracy; other views remain ungeoreferenced."}
            manifest["georef_report"]=report
            out.writestr("manifest.json",json.dumps(manifest,indent=2))
        tmp.replace(output)
    finally:
        tmp.unlink(missing_ok=True)
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("dataset","expansion","reference","output"):
        p.add_argument("--"+key,type=Path,required=True)
    p.add_argument("--west",type=int,required=True)
    p.add_argument("--north",type=int,required=True)
    a=p.parse_args()
    print(json.dumps(recover(a.dataset,a.expansion,a.reference,a.output,west=a.west,north=a.north),indent=2))

if __name__=="__main__":
    main()
