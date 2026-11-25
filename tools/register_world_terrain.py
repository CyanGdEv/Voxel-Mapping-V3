"""Recover an identity-orientation metre grid; retain other orientation scores."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import rasterio
from voxel_mapper.world_registration import orientation_scores, refine_translation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("heightmap","reference","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    for name in ("coarse-bounds","fit-bounds"):
        parser.add_argument("--"+name,type=int,nargs=4,required=True)
    parser.add_argument("--validation-bounds",type=int,nargs=4,action="append",required=True)
    parser.add_argument("--minimum-height",type=float,required=True,help="Exclude artificial/unknown low columns explicitly")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a fresh report path")
    with np.load(args.heightmap,allow_pickle=False) as archive:
        world = archive["heightmap"]
        world_origin = archive["world_origin_xz"].tolist()
    with rasterio.open(args.reference) as source:
        if source.crs is None or source.crs.to_epsg() != 27700 or source.count != 1 or source.res != (1,1) or source.transform.b or source.transform.d or source.transform.e != -1:
            raise ValueError("Native north-up 1m BNG terrain required")
        if source.width*source.height > 16_000_000:
            raise ValueError("Reference pixel budget exceeded")
        reference = source.read(1,masked=True).astype(float).filled(np.nan)
        affine = source.transform
    valid = np.isfinite(world) & (world > args.minimum_height)
    x0,z0,x1,z1 = args.coarse_bounds
    if not (0 <= x0 < x1 <= world.shape[1] and 0 <= z0 < z1 <= world.shape[0]):
        raise ValueError("Coarse search window outside world")
    scores = orientation_scores(world[z0:z1,x0:x1],reference,valid[z0:z1,x0:x1])
    if scores[0]["orientation"] != "identity":
        raise ValueError("Rotated/mirrored candidate requires a separately validated transform")
    col,row = scores[0]["reference_pixel_offset"]
    result = refine_translation(world,reference,valid,[col-x0,row-z0],
                                args.fit_bounds,args.validation_bounds)
    col,row = result["best"]["reference_pixel_offset"]
    east,north = affine*(col,row)
    result.update(schema="voxel-world-terrain-registration-v1",orientation_scores=scores,
                  world_grid_origin_xz=world_origin, raster_grid_origin_bng=[east,north],
                  world_zero_grid_edge_bng=[east-world_origin[0],north+world_origin[1]],
                  source_crs="EPSG:27700",minimum_world_height=args.minimum_height,
                  source_files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.heightmap,args.reference)},
                  accepted_for_block_edits=False)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
