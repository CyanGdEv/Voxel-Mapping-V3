"""Read Data3D column-top metadata from an extracted working copy of a world."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import numpy as np


def extract(records, max_pixels=4_000_000):
    chunks = {}
    for key, value in records:
        # Overworld Data3D only. Dimension-prefixed keys have different lengths.
        if len(key) != 9 or key[-1] != 43:
            continue
        if len(value) < 512:
            raise ValueError("Truncated native heightmap")
        x,z = struct.unpack("<ii", key[:8])
        chunks[x,z] = np.frombuffer(value[:512], "<u2").reshape(16,16).copy()
        if len(chunks)*256 > max_pixels:
            raise ValueError("Native heightmap pixel budget exceeded")
    if not chunks:
        raise ValueError("No supported overworld Data3D heightmaps")
    x0,z0 = min(x for x,z in chunks),min(z for x,z in chunks)
    x1,z1 = max(x for x,z in chunks)+1,max(z for x,z in chunks)+1
    if (x1-x0)*(z1-z0)*256 > max_pixels:
        raise ValueError("World extent exceeds pixel budget")
    result = np.full(((z1-z0)*16,(x1-x0)*16),np.nan,np.float32)
    for (x,z), values in chunks.items():
        result[(z-z0)*16:(z-z0+1)*16,(x-x0)*16:(x-x0+1)*16] = values
    return result, [x0*16,z0*16], len(chunks)


def main():
    import leveldb
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world-copy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a fresh output path")
    database = leveldb.LevelDB(str(args.world_copy/"db"), create_if_missing=False)
    try:
        heights, origin, chunks = extract(database.iterate())
    finally:
        database.close()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(args.output, heightmap=heights, world_origin_xz=np.asarray(origin))
    report = {"schema":"bedrock-data3d-heightmap-v1", "shape":list(heights.shape),
              "world_origin_xz":origin, "overworld_chunks":chunks,
              "sha256":hashlib.sha256(args.output.read_bytes()).hexdigest(),
              "policy":"Column-top-plus-one metadata, not guaranteed ground. Run only on a working copy; LevelDB opening may update database housekeeping."}
    args.output.with_suffix(".json").write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__ == "__main__":
    main()
