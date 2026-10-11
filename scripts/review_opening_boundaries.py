"""Review source-backed aperture outlines against a pinned local-wing seed."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voxel_mapper.native_opening_inventory import run as inventory
from voxel_mapper.opening_boundary_review import run


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['recipe','source','output']:p.add_argument('--'+name,required=True,type=Path)
    a=p.parse_args();i=inventory(a.recipe,a.source,a.output/'inventory')
    print(json.dumps(run(a.recipe,a.source,i,a.output/'boundaries'),sort_keys=True,indent=2))


if __name__=='__main__':main()
