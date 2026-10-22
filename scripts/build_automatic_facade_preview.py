"""Build a source-linked unplaced facade preview from an automatic inventory."""
import argparse
import json
from pathlib import Path
from voxel_mapper.automatic_facade_preview import build

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('components','views','corpus','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--max-checks',type=int,default=100000)
    args=parser.parse_args()
    result=build(args.components,args.views,args.corpus,args.output,max_checks=args.max_checks)
    print(json.dumps({k:result[k] for k in ('status','directory','counts','checks')}))
