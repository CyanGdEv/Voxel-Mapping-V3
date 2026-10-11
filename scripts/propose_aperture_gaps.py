"""Build bounded source-outline hypotheses without modifying a mesh or world."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voxel_mapper.aperture_gap_proposals import run

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe',required=True,type=Path)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(run(args.recipe,args.source,args.output)))
