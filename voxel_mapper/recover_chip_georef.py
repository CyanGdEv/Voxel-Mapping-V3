"""Recover chip georeferencing from an original orthophoto and exact RGB matches."""
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

def recover(dataset, index_zip, source_zip, output, *, raster_member="naip_4band_georeferenced.tif", index_member="chip_index.csv"):
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.windows import Window
    if output.resolve() in {p.resolve() for p in (dataset,index_zip,source_zip)}:
        raise ValueError("Output must not overwrite an input")
    with zipfile.ZipFile(index_zip) as ix:
        rows=list(csv.DictReader(io.StringIO(ix.read(index_member).decode("utf-8-sig"))))
    index={r["chip_id"]:r for r in rows}
    if len(index)!=len(rows):
        raise ValueError("Duplicate chip IDs")
    with zipfile.ZipFile(source_zip) as z:
        raw=z.read(raster_member)
    sha=hashlib.sha256(raw).hexdigest()
    output.parent.mkdir(parents=True,exist_ok=True)
    tmp=output.with_suffix(output.suffix+".tmp")
    counts={"verified":0,"unmatched":0,"labelled_verified":0,"labelled_pixels_verified":0}
    unmatched=[]
    try:
        with MemoryFile(raw) as mem, mem.open() as src, zipfile.ZipFile(dataset) as inp, zipfile.ZipFile(tmp,"w",compression=zipfile.ZIP_DEFLATED) as out:
            if src.crs is None or src.count<3 or any(d!="uint8" for d in src.dtypes[:3]):
                raise ValueError("Expected georeferenced uint8 RGB source")
            manifest=json.loads(inp.read("manifest.json"))
            records=manifest["samples"]
            seen=set()
            for record in records:
                sid=record["sample_id"]
                if sid in seen:
                    raise ValueError("Duplicate sample ID")
                seen.add(sid)
                # Old context depends on old georeferencing and must be regenerated.
                record.pop("context",None)
                record.pop("context_provenance",None)
                record.pop("georef",None)
                row=index.get(sid)
                reason=None
                if not row:
                    reason="missing source chip index"
                else:
                    x,y,w,h=(int(row[k]) for k in ("pixel_x","pixel_y","width_px","height_px"))
                    if min(x,y)<0 or min(w,h)<=0 or x+w>src.width or y+h>src.height:
                        reason="window outside source raster"
                    else:
                        with Image.open(io.BytesIO(inp.read(record["image"]))) as image:
                            rgb=np.asarray(image.convert("RGB"))
                        with Image.open(io.BytesIO(inp.read(record["labels"]))) as image:
                            labels=np.asarray(image.convert("L"))
                        if rgb.shape[:2]!=(h,w) or labels.shape!=(h,w):
                            reason="chip dimension mismatch"
                        elif not np.array_equal(rgb,src.read([1,2,3],window=Window(x,y,w,h)).transpose(1,2,0)):
                            reason="RGB pixels differ from source raster"
                if reason:
                    unmatched.append({"sample_id":sid,"reason":reason})
                    counts["unmatched"]+=1
                    continue
                affine=src.window_transform(Window(x,y,w,h))
                record["georef"]={"crs":src.crs.to_string(),"transform":list(affine)[:6]}
                record["georef_provenance"]={"method":"exact_rgb_source_window_match","source_raster_sha256":sha,
                    "source_pixel_window":[x,y,w,h],"source_raster_member":raster_member}
                counts["verified"]+=1
                n=int(np.count_nonzero(labels!=255))
                counts["labelled_verified"]+=int(n>0)
                counts["labelled_pixels_verified"]+=n
            for item in inp.infolist():
                if item.filename!="manifest.json" and not item.filename.startswith("gis-context/"):
                    out.writestr(item,inp.read(item))
            for key in ("context_schema","context_channels","context_report"):
                manifest.pop(key,None)
            report={**counts,"source_raster_sha256":sha,"source_crs":src.crs.to_string(),"unmatched_samples":unmatched,
                    "policy":"Exact pixel match verifies raster registration only, not survey accuracy or reviewed label quality."}
            manifest["georef_report"]=report
            out.writestr("manifest.json",json.dumps(manifest,indent=2))
        tmp.replace(output)
    finally:
        tmp.unlink(missing_ok=True)
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset",type=Path,required=True)
    p.add_argument("--index-zip",type=Path,required=True)
    p.add_argument("--source-zip",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    print(json.dumps(recover(a.dataset,a.index_zip,a.source_zip,a.output),indent=2))

if __name__=="__main__":
    main()
