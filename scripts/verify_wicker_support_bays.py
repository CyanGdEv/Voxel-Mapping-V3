"""Read-only native leaf audit inside registered brown-footing support bays."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from amulet.level.formats.leveldb_world import LevelDBFormat
from voxel_mapper.generation_cycles import atomic_json,file_hash
from voxel_mapper.wicker_support_bays import support_bay_caps


def audit(folder,output):
    folder=Path(folder);geo=json.loads((folder/'voxel-georeferencing.json').read_text())
    path=folder/'Wicker-Man-Retained-Detail-Report.json';q=json.loads(path.read_text())
    e0,n0,e1,n1=geo['bounds_bng'];width,height=e1-e0,n1-n0
    l=SimpleNamespace(wicker_quality=q,ground=np.zeros((height,width),np.int16),
        offset=geo['vertical_offset_blocks'],e0=e0,n0=n0,width=width,height=height)
    record=support_bay_caps(l,{'maximum_adjacent_station_gap_m':3,'maximum_adjacent_footing_gap_m':5})
    low=min(row['start_cell_xyz'][1] for row in q['fence_supports']['constructed_supports'])+l.offset
    world=LevelDBFormat(str(folder));world.open();cache={};materials=Counter();leaves=[];checked=0
    try:
        for r,c in zip(*np.nonzero(l.ride_support_bay_caps>-32768)):
            z=int(r-height);x=int(c);key=x//16,z//16
            if key not in cache:cache[key]=world.load_chunk(*key,'minecraft:overworld')
            chunk=cache[key]
            for y in range(low,int(l.ride_support_bay_caps[r,c])+1):
                b=chunk.block_palette[int(chunk.blocks[x%16,y,z%16])];materials[b.base_name]+=1;checked+=1
                if b.base_name=='leaves':leaves.append([x,y,z])
    finally:world.close()
    assert not leaves,('Native leaves remain inside registered support bays',len(leaves),leaves[:20])
    record.update(status='passed',native_cells_checked=checked,native_chunks_checked=len(cache),
        remaining_native_leaves_inside_capped_registered_bays=0,native_material_counts=dict(materials),
        retained_support_report_sha256=file_hash(path),
        registered_cap_grid_sha256=hashlib.sha256(l.ride_support_bay_caps.astype('<i2').tobytes()).hexdigest(),
        world_geometry_modified=False,
        limitation='This checks bounded adjacent-footing bays below their deck undersides; it does not label all nearby canopy as timber or prove survey completeness.')
    atomic_json(output,record);return record


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--world',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();print(json.dumps(audit(a.world,a.output),indent=2))


if __name__=='__main__':main()
