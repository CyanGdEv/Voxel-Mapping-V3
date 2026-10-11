"""Audit native source labels and rectangular frame alternatives; export no meshes."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voxel_mapper.native_opening_inventory import run


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--recipe',required=True,type=Path)
    p.add_argument('--sources',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    seed=json.loads(a.recipe.read_text())
    source=a.sources/(seed['documents']['elevation']['sha256']+'.pdf')
    print(json.dumps(run(a.recipe,source,a.output),sort_keys=True,indent=2))


if __name__=='__main__':main()
